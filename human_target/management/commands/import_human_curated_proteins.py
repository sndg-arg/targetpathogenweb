"""Ingest the curated human protein demo set into the Human Targets section.

Reads a local `new_data/` tree (already downloaded from the target-human-web
Zenodo archive -- see ../target-human-web/README.md) and populates:
  - one `Biodatabase` row (the internal storage container, never surfaced
    via the Genomes list -- see human_target/services/human_targets.py)
  - one `Bioentry` + `HumanProtein` row per accession, parsed from
    `<ACC>_full.json`
  - `Binders` rows via the existing `load_ligq_2_results` command, unmodified
  - `PDB`/`BioentryStructure` rows via the existing `load_af_model` command,
    once per structure file

Usage:
    python manage.py import_human_curated_proteins /path/to/new_data \
        [--accession P10721 --accession Q1AE95 ...] \
        [--overwrite] [--dry-run] [--skip-ligands] [--skip-structures]

NOTE: the UniProt JSON field paths below (proteinDescription, comments,
features, uniProtKBCrossReferences, ...) follow the standard UniProt REST
`/uniprotkb/{accession}` response shape and target-human-web's documented
field usage, but have not been validated against a real downloaded
`<ACC>_full.json` in this environment (no internet access here). Parsing is
defensive (falls back to empty values) specifically so a field-name mismatch
degrades gracefully into sparse HumanProtein content rather than aborting
the whole ingestion -- verify field-by-field against one real file before
trusting this in production, per CLAUDE.md's "no local execution
environment" note.
"""

import csv
import json
import xml.etree.ElementTree as ET
from pathlib import Path

from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError

from bioseq.models.Bioentry import Bioentry
from bioseq.models.Ontology import Ontology

from human_target.models.HumanPathway import HumanPathway
from human_target.models.HumanProtein import HumanProtein
from human_target.models.HumanProteinPathway import HumanProteinPathway
from human_target.services.human_targets import (
    DEMO_ACCESSIONS,
    get_or_create_human_biodatabase,
)
from tpweb.models.BioentryStructure import ExperimentalStructureXref
from tpweb.services.functional_annotations import persist_ec_go_annotations

DEFAULT_DATADIR = "/app/targetpathogenweb/data"

_COMMENT_TEXT_TYPES = {
    "FUNCTION": "function_text",
    "CAUTION": "caution_text",
    "SUBUNIT": "subunit_text",
    "POLYMORPHISM": "polymorphism_text",
}


def _load_json(path):
    if not path.exists():
        return None
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def _texts_for_comment(comment):
    return [
        (text.get("value") or "").strip()
        for text in comment.get("texts", []) or []
        if (text.get("value") or "").strip()
    ]


def _extract_comments(entry):
    """FUNCTION/CAUTION/SUBUNIT/POLYMORPHISM free text + DISEASE comments."""
    out = {field: "" for field in _COMMENT_TEXT_TYPES.values()}
    diseases = []
    for comment in entry.get("comments", []) or []:
        ctype = comment.get("commentType", "")
        if ctype in _COMMENT_TEXT_TYPES:
            texts = _texts_for_comment(comment)
            if texts:
                out[_COMMENT_TEXT_TYPES[ctype]] = " ".join(texts)
        elif ctype == "DISEASE":
            disease = comment.get("disease") or {}
            diseases.append(
                {
                    "name": disease.get("diseaseId", ""),
                    "acronym": disease.get("acronym", ""),
                    "description": disease.get("description", ""),
                    "mim": disease.get("diseaseCrossReference", {}).get("id", ""),
                }
            )
    return out, diseases


def _extract_catalytic_activity(entry):
    catalytic = []
    for comment in entry.get("comments", []) or []:
        if comment.get("commentType") != "CATALYTIC ACTIVITY":
            continue
        reaction = comment.get("reaction") or {}
        rhea_id = ""
        for xref in reaction.get("reactionCrossReferences", []) or []:
            if xref.get("database") == "Rhea":
                rhea_id = xref.get("id", "")
                break
        catalytic.append(
            {
                "ec": reaction.get("ecNumber", ""),
                "rhea": rhea_id,
                "reaction": reaction.get("name", ""),
            }
        )
    return catalytic


def _extract_ec_numbers(entry):
    ec_numbers = []
    protein_desc = entry.get("proteinDescription", {}) or {}
    name_blocks = [protein_desc.get("recommendedName", {}) or {}]
    name_blocks += protein_desc.get("alternativeNames", []) or []
    name_blocks += protein_desc.get("submissionNames", []) or []
    for block in name_blocks:
        for ec in block.get("ecNumbers", []) or []:
            value = (ec.get("value") or "").strip()
            if value:
                ec_numbers.append({"id": value, "name": ""})
    return ec_numbers


def _extract_go_terms(entry):
    go_terms = []
    for xref in entry.get("uniProtKBCrossReferences", []) or []:
        if xref.get("database") != "GO":
            continue
        go_id = (xref.get("id") or "").strip()
        if not go_id:
            continue
        name = ""
        aspect = ""
        for prop in xref.get("properties", []) or []:
            if prop.get("key") == "GoTerm":
                raw = prop.get("value", "")
                if ":" in raw:
                    aspect_code, name = raw.split(":", 1)
                    aspect = {"P": "P", "C": "C", "F": "F"}.get(aspect_code.strip(), "")
                    name = name.strip()
        go_terms.append({"id": go_id, "name": name, "aspect": aspect})
    return go_terms


def _extract_cross_references(entry):
    return [
        {"database": xref.get("database", ""), "id": xref.get("id", "")}
        for xref in entry.get("uniProtKBCrossReferences", []) or []
        if xref.get("database") and xref.get("id")
    ]


def _extract_features(entry):
    features = []
    for feature in entry.get("features", []) or []:
        location = feature.get("location", {}) or {}
        start = (location.get("start") or {}).get("value")
        end = (location.get("end") or {}).get("value")
        if start is None:
            continue
        features.append(
            {
                "type": feature.get("type", ""),
                "description": feature.get("description", ""),
                "start": start,
                "end": end if end is not None else start,
            }
        )
    return features


def _extract_keywords(entry):
    return [kw.get("name", "") for kw in entry.get("keywords", []) or [] if kw.get("name")]


def _extract_subcellular_locations(entry):
    """UniProt repeats one SUBCELLULAR LOCATION comment per isoform (`molecule`
    field), often with the same location value -- dedupe while preserving
    order so the Overview tab doesn't show e.g. "Cell membrane" three times."""
    locations = []
    seen = set()
    for comment in entry.get("comments", []) or []:
        if comment.get("commentType") != "SUBCELLULAR LOCATION":
            continue
        for loc in comment.get("subcellularLocations", []) or []:
            value = (loc.get("location", {}) or {}).get("value", "")
            if value and value not in seen:
                seen.add(value)
                locations.append(value)
    return locations


def _extract_publications(entry):
    publications = []
    for ref in entry.get("references", []) or []:
        citation = ref.get("citation", {}) or {}
        pubmed_id = ""
        for xref in citation.get("citationCrossReferences", []) or []:
            if xref.get("database") == "PubMed":
                pubmed_id = xref.get("id", "")
                break
        if pubmed_id:
            publications.append({"pubmed": pubmed_id, "title": citation.get("title", "")})
    return publications


def _parse_kgml(kgml_path):
    """Parse one KEGG KGML pathway file into a pruned node/edge graph:
    gene/ortholog entries only (compound/map entries dropped, matching the
    reference app's own pruning rule), and only nodes that participate in at
    least one relation (isolated nodes dropped). Pure function -- takes a
    path, returns plain dicts/lists, no DB access -- so it's reusable
    unchanged by a future live-KEGG-fetch ingest command."""
    tree = ET.parse(kgml_path)
    root = tree.getroot()

    nodes = {}
    for entry in root.findall("entry"):
        if entry.get("type") not in ("gene", "ortholog"):
            continue
        entry_id = entry.get("id", "")
        if not entry_id:
            continue
        kegg_ids = (entry.get("name", "") or "").split()
        graphics = entry.find("graphics")
        label = ""
        if graphics is not None:
            label = (graphics.get("name", "") or "").split(",")[0].strip()
        nodes[entry_id] = {
            "id": entry_id,
            "label": label or (kegg_ids[0] if kegg_ids else entry_id),
            "kegg_ids": kegg_ids,
        }

    edges = []
    connected_ids = set()
    for relation in root.findall("relation"):
        entry1 = relation.get("entry1", "")
        entry2 = relation.get("entry2", "")
        if entry1 not in nodes or entry2 not in nodes:
            continue
        subtypes = [
            subtype.get("name", "")
            for subtype in relation.findall("subtype")
            if subtype.get("name")
        ]
        edges.append({"source": entry1, "target": entry2, "subtypes": subtypes})
        connected_ids.add(entry1)
        connected_ids.add(entry2)

    return {
        "nodes": [node for node_id, node in nodes.items() if node_id in connected_ids],
        "edges": edges,
    }


def _build_human_protein_fields(entry):
    comments, diseases = _extract_comments(entry)
    protein_desc = entry.get("proteinDescription", {}) or {}
    recommended = protein_desc.get("recommendedName", {}) or {}
    protein_name = (recommended.get("fullName", {}) or {}).get("value", "")
    genes = entry.get("genes", []) or []
    gene_symbol = ""
    if genes:
        gene_symbol = (genes[0].get("geneName", {}) or {}).get("value", "")
    organism = entry.get("organism", {}) or {}
    lineage = organism.get("lineage", []) or []
    sequence = entry.get("sequence", {}) or {}
    audit = entry.get("entryAudit", {}) or {}

    fields = {
        "protein_name": protein_name,
        "gene_symbol": gene_symbol,
        "organism_name": organism.get("scientificName", "Homo sapiens"),
        "taxon_id": organism.get("taxonId"),
        "sequence_length": sequence.get("length"),
        "mass_da": sequence.get("molWeight"),
        "annotation_score": entry.get("annotationScore"),
        "entry_version": audit.get("entryVersion"),
        "is_reviewed": entry.get("entryType", "").startswith("UniProtKB reviewed"),
        "chromosome": "",
        "lineage": lineage,
        "keywords": _extract_keywords(entry),
        "subcellular_locations": _extract_subcellular_locations(entry),
        "disease_comments": diseases,
        "catalytic_activity": _extract_catalytic_activity(entry),
        "go_terms": _extract_go_terms(entry),
        "publications": _extract_publications(entry),
        "features_raw": _extract_features(entry),
        "cross_references_raw": _extract_cross_references(entry),
        "sequence": sequence.get("value", ""),
        "uniprot_raw": entry,
    }
    fields.update(comments)
    return fields


class Command(BaseCommand):
    help = "Ingest curated human proteins (Human Targets section) from a local new_data/ tree."

    def add_arguments(self, parser):
        parser.add_argument(
            "data_dir", help="Local root containing <ACC>/ folders (downloaded from Zenodo)."
        )
        parser.add_argument(
            "--accession",
            action="append",
            default=None,
            help="Restrict ingestion to this accession. Repeatable. Default: the 10 demo accessions.",
        )
        parser.add_argument("--overwrite", action="store_true")
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument("--skip-ligands", action="store_true")
        parser.add_argument("--skip-structures", action="store_true")
        parser.add_argument("--skip-expression", action="store_true")
        parser.add_argument("--skip-pathways", action="store_true")
        parser.add_argument("--datadir", default=DEFAULT_DATADIR)

    def handle(self, *args, **options):
        data_dir = Path(options["data_dir"]).resolve()
        if not data_dir.is_dir():
            raise CommandError(f"Data directory not found: {data_dir}")

        accessions = options["accession"] or DEMO_ACCESSIONS
        dry_run = options["dry_run"]
        overwrite = options["overwrite"]

        biodatabase = None
        if not dry_run:
            biodatabase = get_or_create_human_biodatabase()

        ec_ontology = go_ontology = None
        if not dry_run:
            ec_ontology, _ = Ontology.objects.get_or_create(
                name=Ontology.EC, defaults={"definition": ""}
            )
            go_ontology, _ = Ontology.objects.get_or_create(
                name=Ontology.GO, defaults={"definition": ""}
            )

        for accession in accessions:
            protein_dir = data_dir / accession
            if not protein_dir.is_dir():
                self.stderr.write(f"skip {accession}: no folder at {protein_dir}")
                continue
            self.stdout.write(f"== {accession} ==")

            entry_json = _load_json(protein_dir / f"{accession}_full.json")
            if entry_json is None:
                self.stderr.write(f"skip {accession}: {accession}_full.json not found")
                continue

            # <ACC>_full.json is target-human-web's own pipeline-shaped document
            # (features/comments/cross_references regrouped by type for its own
            # app's convenience) -- the genuine UniProt REST response our
            # extraction helpers below expect lives untouched under "raw_entry".
            # Confirmed present in all 10 curated accessions' real Zenodo files.
            entry = entry_json.get("raw_entry") or entry_json

            fields = _build_human_protein_fields(entry)
            fields["ingest_source_path"] = str(protein_dir)

            if dry_run:
                self.stdout.write(
                    f"  [dry-run] would ingest {accession}: "
                    f"{fields['sequence_length']} aa, {len(fields['go_terms'])} GO terms, "
                    f"{len(fields['cross_references_raw'])} xrefs"
                )
                continue

            bioentry, _ = Bioentry.objects.get_or_create(
                biodatabase=biodatabase,
                accession=accession,
                defaults={"name": accession, "identifier": accession},
            )
            human_protein, _ = HumanProtein.objects.update_or_create(
                bioentry=bioentry,
                defaults={"uniprot_accession": accession, **fields},
            )
            self._write_uniprot_dbxref(bioentry, accession, fields["is_reviewed"])

            ec_created = persist_ec_go_annotations(
                bioentry, _extract_ec_numbers(entry), "ec", ec_ontology
            )
            go_created = persist_ec_go_annotations(
                bioentry, fields["go_terms"], Ontology.GO, go_ontology
            )
            self.stdout.write(f"  EC created: {ec_created}, GO created: {go_created}")

            if not options["skip_ligands"]:
                self._load_ligands(protein_dir, accession)

            if not options["skip_structures"]:
                self._load_structures(
                    protein_dir, accession, bioentry, options["datadir"], overwrite
                )

            if not options["skip_expression"]:
                self._load_expression(protein_dir, accession, human_protein)

            if not options["skip_pathways"]:
                self._load_pathways(protein_dir, accession, human_protein)

    def _write_uniprot_dbxref(self, bioentry, accession, is_reviewed):
        """Human `Bioentry.accession` already *is* the UniProt accession, but
        `load_ligq_2_results`'s `is_direct` classification only checks for a
        `UnipSp`/`UnipTr` `BioentryDbxref` pointing at it (same lookup bacteria
        get from `gbk2uniprot_map`) -- without this, every human ligand match
        silently falls back to "homolog"."""
        from bioseq.models.BioentryDbxref import BioentryDbxref
        from bioseq.models.Dbxref import Dbxref

        db = "UnipSp" if is_reviewed else "UnipTr"
        dbxref, _ = Dbxref.objects.get_or_create(dbname=db, accession=accession)
        BioentryDbxref.objects.get_or_create(dbxref=dbxref, bioentry=bioentry)

    def _load_expression(self, protein_dir, accession, human_protein):
        """Bgee's per-(tissue, cell type) expression export. Anatomical-system
        bucketing happens at render time (`human_expression_summary.py`), not
        here -- this just keeps the fields the UI needs, coerced to the right
        types, with blank/unscored rows dropped."""
        tsv_path = protein_dir / "Bgee-genex-heatmap.tsv"
        if not tsv_path.exists():
            self.stdout.write(f"  no Bgee-genex-heatmap.tsv for {accession}, skipping expression")
            return

        rows = []
        with tsv_path.open(encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle, delimiter="\t"):
                score_raw = (row.get("expression_score") or "").strip()
                try:
                    score = float(score_raw)
                except ValueError:
                    continue
                rows.append(
                    {
                        "tissue": (row.get("anat_entity_name") or "").strip(),
                        "cell_type": (row.get("cell_type_name") or "").strip(),
                        "score": score,
                        "confidence": (row.get("expression_score_confidence") or "").strip(),
                        "quality": (row.get("expression_quality") or "").strip(),
                        "fdr": (row.get("fdr") or "").strip(),
                        "data_types": (row.get("data_types_with_data") or "").strip(),
                        "state": (row.get("expression_state") or "").strip(),
                        "cluster": (row.get("cluster_index") or "").strip(),
                    }
                )

        human_protein.expression_json = rows
        human_protein.save(update_fields=["expression_json"])
        self.stdout.write(f"  expression rows loaded: {len(rows)}")

    def _load_pathways(self, protein_dir, accession, human_protein):
        """KEGG pathway membership, via the same `kegg_kgml/` tree target-
        human-web's own pipeline produced. `HumanPathway` rows are shared
        reference data across proteins (get_or_create by kegg_id, so a
        pathway shared by two curated proteins is stored once), while
        `HumanProteinPathway` is the per-protein link, carrying which of the
        pathway's own graph nodes is *this* protein (matched via its NCBI
        GeneID cross-reference)."""
        kegg_dir = protein_dir / "kegg_kgml"
        index_path = kegg_dir / "index.json"
        if not index_path.exists():
            self.stdout.write(f"  no kegg_kgml/index.json for {accession}, skipping pathways")
            return

        index = _load_json(index_path) or []
        gene_id = ""
        for xref in human_protein.cross_references_raw or []:
            if xref.get("database") == "GeneID":
                gene_id = (xref.get("id") or "").strip()
                break
        target_kegg_gene = f"hsa:{gene_id}" if gene_id else ""

        linked = 0
        for item in index:
            kegg_id = (item.get("id") or "").strip()
            kgml_path = kegg_dir / (item.get("file") or f"{kegg_id}.kgml")
            if not kegg_id or not kgml_path.exists():
                continue
            try:
                graph = _parse_kgml(kgml_path)
            except ET.ParseError as exc:
                self.stderr.write(f"  failed to parse {kgml_path}: {exc}")
                continue

            pathway, _ = HumanPathway.objects.update_or_create(
                kegg_id=kegg_id,
                defaults={
                    "title": item.get("title", ""),
                    "entry_count": item.get("entries") or 0,
                    "relation_count": item.get("relations") or 0,
                    "graph_json": graph,
                },
            )

            highlighted_node_id = ""
            if target_kegg_gene:
                for node in graph["nodes"]:
                    if target_kegg_gene in node["kegg_ids"]:
                        highlighted_node_id = node["id"]
                        break

            HumanProteinPathway.objects.update_or_create(
                human_protein=human_protein,
                pathway=pathway,
                defaults={"highlighted_node_id": highlighted_node_id},
            )
            linked += 1

        self.stdout.write(f"  pathways linked: {linked}")

    def _load_ligands(self, protein_dir, accession):
        ligq_dir = protein_dir / "ligq"
        if not ligq_dir.is_dir():
            self.stdout.write(f"  no ligq/ directory for {accession}, skipping ligands")
            return
        try:
            call_command(
                "load_ligq_2_results",
                str(ligq_dir),
                locustag_fallback=accession,
            )
        except (CommandError, SystemExit) as exc:
            self.stderr.write(f"  ligand load failed for {accession}: {exc}")

    def _load_structures(self, protein_dir, accession, bioentry, datadir, overwrite):
        jobs = []
        af_file = protein_dir / "AlphaFoldDB" / f"{accession}.cif"
        if af_file.exists():
            jobs.append((f"AF_{accession}", af_file, "AF", None))
        afill_file = protein_dir / "AlphaFill" / f"{accession}.cif"
        if afill_file.exists():
            jobs.append((f"AFILL_{accession}", afill_file, "AFILL", None))

        structures_manifest = _load_json(protein_dir / "structures.json") or {}
        method_by_pdb_id = {}
        for key in ("pdb_xray", "pdb_nmr"):
            for item in structures_manifest.get(key, []) or []:
                pdb_id = (item.get("id") or "").strip().upper()
                if pdb_id:
                    method_by_pdb_id[pdb_id] = item.get("method", "")

        for subdir, is_nmr in (("PDB-X-Ray", False), ("PDB-NMR", True)):
            folder = protein_dir / subdir
            if not folder.is_dir():
                continue
            for cif_file in sorted(folder.glob(f"{accession}_*.cif")):
                pdb_id = cif_file.stem.split(f"{accession}_", 1)[-1].upper()
                jobs.append(
                    (
                        pdb_id,
                        cif_file,
                        "EX",
                        method_by_pdb_id.get(pdb_id, "NMR" if is_nmr else "X-RAY"),
                    )
                )

        for code, path, experiment, method in jobs:
            try:
                call_command(
                    "load_af_model",
                    code,
                    str(path),
                    accession,
                    experiment=experiment,
                    datadir=datadir,
                    overwrite=overwrite,
                )
            except SystemExit as exc:
                self.stderr.write(f"  structure {code} for {accession}: {exc}")
                continue
            except CommandError as exc:
                self.stderr.write(f"  structure {code} for {accession} failed: {exc}")
                continue

            if experiment == "EX":
                ExperimentalStructureXref.objects.update_or_create(
                    bioentry=bioentry,
                    pdb_id=code,
                    defaults={"method": method or ""},
                )
