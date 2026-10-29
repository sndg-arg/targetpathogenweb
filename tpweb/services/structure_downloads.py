"""Downloadable structure bundles for the protein page: the raw structure
files of a protein (optionally one source only), their FPocket/P2Rank pockets
as a TSV, and a self-contained PyMOL script per structure."""

import base64
import io
import re
import zipfile
import zlib

from bioseq.io.BioIO import BioIO
from tpweb.models.pdb import PDBResidueSet, Residue
from tpweb.services.pocket_geometry import filter_pdbresidueset_by_chain
from tpweb.services.structure_files import (
    detect_structure_format_from_text,
    display_code,
    read_structure_text,
    structure_file_path,
)
from tpweb.services.structure_sources import (
    STRUCTURE_SOURCE_ALPHAFOLD,
    STRUCTURE_SOURCE_COLABFOLD,
    STRUCTURE_SOURCE_EXPERIMENTAL,
    STRUCTURE_SOURCE_MODEL,
    classify_structure_experiment,
    sort_structures_by_preference,
    structure_source_label,
)
from tpweb.services.structure_summary import _pdb_reference_rows

DOWNLOAD_SOURCE_ALL = "all"
# Folder name inside the ZIP for each source.
DOWNLOAD_SOURCE_FOLDERS = {
    STRUCTURE_SOURCE_EXPERIMENTAL: "pdb",
    STRUCTURE_SOURCE_ALPHAFOLD: "alphafold_db",
    STRUCTURE_SOURCE_COLABFOLD: "colabfold",
    STRUCTURE_SOURCE_MODEL: "model",
}
DOWNLOAD_SOURCE_LABELS = {
    STRUCTURE_SOURCE_EXPERIMENTAL: "Experimental (PDB)",
    STRUCTURE_SOURCE_ALPHAFOLD: "AlphaFold DB",
    STRUCTURE_SOURCE_COLABFOLD: "ColabFold",
    STRUCTURE_SOURCE_MODEL: "Other models",
}
# Same number of pockets the protein page shows per method; the rest are
# still created as (disabled) PyMOL objects and listed in the TSV.
SHOWN_POCKETS = {"fpocket": 4, "p2rank": 5}
POCKET_COLORS = ("magenta", "cyan", "orange", "green", "yellow", "salmon", "slate", "violet")

_SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9_]+")


def _safe_name(value):
    return _SAFE_NAME_RE.sub("_", str(value)).strip("_") or "structure"


def link_genome_name(link):
    return link.bioentry.biodatabase.name.replace(BioIO.GENOME_PROT_POSTFIX, "")


def structure_pockets(pdb, chain=""):
    """Every FPocket and P2Rank pocket of `pdb` (on `chain`, when given), best
    first per method: [{method, name, score_name, score, residues}]."""
    ref = _pdb_reference_rows()
    methods = (
        ("fpocket", ref["FPocketPocket"], ref["druggability_score"]),
        ("p2rank", ref["P2RankPocket"], ref["probability"]),
    )
    pockets = []
    for method, residue_set, score_prop in methods:
        qs = filter_pdbresidueset_by_chain(
            PDBResidueSet.objects.filter(pdb=pdb, residue_set=residue_set), chain
        ).prefetch_related("properties", "residue_set_residue__residue")
        rows = []
        for pocket in qs:
            score = next(
                (p.value for p in pocket.properties.all() if p.property_id == score_prop.id),
                None,
            )
            residues = sorted(
                {
                    (rsr.residue.chain.strip(), rsr.residue.resid, rsr.residue.resname)
                    for rsr in pocket.residue_set_residue.all()
                },
                key=lambda r: (r[0], r[1]),
            )
            rows.append(
                {
                    "method": method,
                    "name": str(pocket.name),
                    "score_name": score_prop.name,
                    "score": score,
                    "residues": residues,
                }
            )
        rows.sort(key=lambda r: (r["score"] is None, -(r["score"] or 0)))
        pockets += rows
    return pockets


def pockets_tsv(pockets):
    lines = ["method\tpocket\trank\tscore_name\tscore\tn_residues\tresidues"]
    ranks = {}
    for p in pockets:
        ranks[p["method"]] = ranks.get(p["method"], 0) + 1
        score = "" if p["score"] is None else f"{p['score']:.3f}"
        residues = ";".join(
            f"{chain}:{resname}{resid}" if chain else f"{resname}{resid}"
            for chain, resid, resname in p["residues"]
        )
        lines.append(
            f"{p['method']}\t{p['name']}\t{ranks[p['method']]}\t{p['score_name']}\t"
            f"{score}\t{len(p['residues'])}\t{residues}"
        )
    return "\n".join(lines) + "\n"


def with_pocket_pseudo_atoms(pdb_text, pdb, pocket_names):
    """FPocket's alpha-sphere pseudo-atoms (resname STP, resid = pocket
    number) are only stored in the DB (tpweb.io.FPocket2SQL), never in the
    structure file on disk. Re-serialize them with Residue.lines() and splice
    them in before the END record, so VMD/PyMOL selections on "STP" find
    something. PDB-format text only."""
    pocket_resids = []
    for name in pocket_names:
        try:
            pocket_resids.append(int(name))
        except (TypeError, ValueError):
            pass
    if not pocket_resids:
        return pdb_text

    pocket_lines = []
    for residue in Residue.objects.prefetch_related("atoms").filter(
        pdb=pdb, resname="STP", resid__in=pocket_resids
    ):
        pocket_lines += residue.lines()
    if not pocket_lines:
        return pdb_text

    lines = pdb_text.splitlines()
    insert_at = len(lines)
    for i in range(len(lines) - 1, -1, -1):
        if lines[i].rstrip() == "END":
            insert_at = i
            break
    lines[insert_at:insert_at] = pocket_lines
    return "\n".join(lines) + "\n"


def _pymol_residue_selection(obj, residues):
    by_chain = {}
    for chain, resid, _resname in residues:
        # PyMOL reads "-" in resi as a range; negative numbers need escaping.
        by_chain.setdefault(chain, []).append(f"\\{resid}" if resid < 0 else str(resid))
    parts = []
    for chain, resids in by_chain.items():
        chain_sel = f"chain {chain} and " if chain else ""
        parts.append(f"({chain_sel}resi {'+'.join(resids)})")
    return f"{obj} and ({' or '.join(parts)})"


def pymol_script(structure_text, structure_format, obj_name, title, source, pockets):
    """A .pml that opens on its own: the coordinates are embedded (compressed),
    so PyMOL doesn't need to find a separate file next to it."""
    obj = _safe_name(obj_name)
    payload = base64.b64encode(zlib.compress(structure_text.encode("utf-8"), 9)).decode("ascii")
    wrapped = "\n".join(payload[i : i + 100] for i in range(0, len(payload), 100))
    lines = [
        f"# {title}",
        "# Generated by Target Pathogen. Open with PyMOL (File > Run Script, or double-click).",
        "python",
        "import base64, zlib",
        "from pymol import cmd",
        f'_data = """{wrapped}"""',
        f'cmd.load_raw(zlib.decompress(base64.b64decode("".join(_data.split()))).decode(), '
        f'"{structure_format}", "{obj}")',
        "python end",
        f"hide everything, {obj}",
        f"show cartoon, {obj}",
        "set cartoon_transparency, 0.1",
    ]
    if source in (STRUCTURE_SOURCE_ALPHAFOLD, STRUCTURE_SOURCE_COLABFOLD):
        lines += [
            "# Predicted model: colored by pLDDT (B-factor column), blue = confident.",
            f"spectrum b, orange_yellow_cyan_blue, {obj}, minimum=50, maximum=90",
        ]
    else:
        lines.append(f"color grey80, {obj}")
    lines += [
        f"show sticks, {obj} and hetatm and not resn HOH+WAT+STP",
        f"color atomic, {obj} and hetatm and not elem C",
    ]

    # One object per pocket, grouped by method, so each can be shown or
    # hidden from PyMOL's object panel instead of being painted onto the
    # protein. Pockets past the ones the page shows start disabled.
    shown = {method: 0 for method in SHOWN_POCKETS}
    groups = {}
    hidden = []
    for color_index, p in enumerate(q for q in pockets if q["residues"]):
        name = _safe_name(f"{p['method']}_{p['name']}")
        atoms = _pymol_residue_selection(obj, p["residues"])
        if p["method"] == "fpocket" and structure_format == "pdb":
            atoms = f"({atoms}) or ({obj} and resn STP and resi {p['name']})"
        color = POCKET_COLORS[color_index % len(POCKET_COLORS)]
        score = "" if p["score"] is None else f" {p['score_name']}={p['score']:.2f}"
        lines += [
            f"# {p['method']} pocket {p['name']}{score}",
            f"create {name}, {atoms}",
            f"hide everything, {name}",
            f"show sticks, {name} and not resn STP and not name N+C+O",
            f"color {color}, {name} and elem C",
            f"show spheres, {name} and resn STP",
            f"color {color}, {name} and resn STP",
        ]
        groups.setdefault(p["method"], []).append(name)
        if shown[p["method"]] < SHOWN_POCKETS[p["method"]]:
            shown[p["method"]] += 1
        else:
            hidden.append(name)
    lines += [f"group {method}_pockets, {' '.join(names)}" for method, names in groups.items()]
    lines += [f"disable {name}" for name in hidden]
    lines += [
        "set sphere_scale, 0.35",
        "set sphere_transparency, 0.4",
        "deselect",
        f"orient {obj}",
        "",
    ]
    return "\n".join(lines)


def structure_bundle_files(link):
    """(structure_text, structure_format, pockets) for one BioentryStructure
    link; raises FileNotFoundError/OSError when the file is missing. FPocket
    alpha spheres are spliced into PDB-format text."""
    pdb = link.pdb
    path = structure_file_path(link_genome_name(link), link.bioentry.accession, pdb.code)
    text = read_structure_text(path)
    structure_format = detect_structure_format_from_text(text)
    pockets = structure_pockets(pdb, link.chain)
    if structure_format == "pdb":
        text = with_pocket_pseudo_atoms(
            text, pdb, [p["name"] for p in pockets if p["method"] == "fpocket"]
        )
    return text, structure_format, pockets


def structure_pymol_script(link):
    text, structure_format, pockets = structure_bundle_files(link)
    source = classify_structure_experiment(link.pdb.experiment)
    code = display_code(link.pdb.code)
    title = f"{link.bioentry.accession} - {code} ({structure_source_label(source)})"
    return pymol_script(text, structure_format, code, title, source, pockets)


def available_download_sources(structures):
    """[(source_key, label, count)] for the sources this protein actually has."""
    counts = {}
    for link in structures:
        source = classify_structure_experiment(link.pdb.experiment)
        counts[source] = counts.get(source, 0) + 1
    return [
        (source, DOWNLOAD_SOURCE_LABELS[source], counts[source])
        for source in DOWNLOAD_SOURCE_FOLDERS
        if source in counts
    ]


def build_structures_zip(protein, source=DOWNLOAD_SOURCE_ALL):
    """ZIP bytes with every structure of `protein` from `source` (or all):
    <folder>/<code>.<pdb|cif>, <code>_pockets.tsv and <code>.pml. Returns
    (bytes, n_structures); n_structures is 0 when nothing could be read."""
    links = protein.structures.all()
    if not getattr(protein, "shared_sequence_evidence", None):
        links = links.select_related("pdb", "bioentry__biodatabase")
    links = sort_structures_by_preference(links)
    stream = io.BytesIO()
    written = 0
    with zipfile.ZipFile(stream, mode="w", compression=zipfile.ZIP_DEFLATED) as zip_file:
        seen = set()
        for link in links:
            link_source = classify_structure_experiment(link.pdb.experiment)
            if source != DOWNLOAD_SOURCE_ALL and link_source != source:
                continue
            try:
                text, structure_format, pockets = structure_bundle_files(link)
            except (FileNotFoundError, OSError):
                continue
            code = display_code(link.pdb.code)
            stem = f"{DOWNLOAD_SOURCE_FOLDERS[link_source]}/{_safe_name(code)}"
            if stem in seen:
                continue
            seen.add(stem)
            title = f"{protein.accession} - {code} ({structure_source_label(link_source)})"
            zip_file.writestr(f"{stem}.{structure_format}", text)
            zip_file.writestr(f"{stem}_pockets.tsv", pockets_tsv(pockets))
            zip_file.writestr(
                f"{stem}.pml",
                pymol_script(text, structure_format, code, title, link_source, pockets),
            )
            written += 1
    return stream.getvalue(), written
