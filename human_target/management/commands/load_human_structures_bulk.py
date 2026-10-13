"""Load AlphaFold-own-model and experimental PDB structures for the full
human proteome, at scale.

Scale companion to the pilot's per-protein `_load_structures`
(`import_human_curated_proteins.py`), which reads local `AlphaFoldDB/`,
`AlphaFill/`, `PDB-X-Ray/`, `PDB-NMR/` folders the reference app's own
pipeline produced for 10 proteins. At full-proteome scale there is no such
per-protein tree, so this command reads from two bulk sources instead:

  1. AlphaFold DB's own per-organism archive, already downloaded and
     extracted by `scripts/cluster/fetch_human_proteome_bulk.sh` (one file
     per accession, `AF-<accession>-F1-model_v<N>.cif[.gz]`) -- the
     extracted directory is passed in via `--alphafold-dir`, wherever it's
     been rsync'd to from the login node. Indexed once by filename at
     startup rather than globbed per accession, so this stays fast at
     ~30,000 proteins against ~23,600 files.
  2. Experimental PDB structures, fetched one CIF per *distinct* PDB ID
     actually referenced by our proteins' own `PDB` cross-references
     (already stored in `cross_references_raw` by the UniProt ingest, no
     extra call to look them up) -- files.rcsb.org has no organism-scoped
     bulk export, but an entry shared by several human proteins (common for
     well-studied targets) is only downloaded and parsed once; every later
     protein sharing it is a cheap re-link (see `load_af_model`'s
     re-link-on-existing-row branch, added earlier this session).

Both reuse `load_af_model` completely unchanged, exactly like the pilot
does -- including catching its SystemExit/CommandError for a graceful
per-structure skip instead of aborting the whole run.

AlphaFill is intentionally out of scope here -- no bulk source exists for
it (see the saved full-proteome scaling plan); a future, separate,
opt-in/rate-limited command would be needed for it.

Usage:
    python manage.py load_human_structures_bulk --alphafold-dir /path/to/extracted \
        [--accession P10721 --accession O00116 ...] [--accession-file PATH] \
        [--datadir /app/targetpathogenweb/data] [--overwrite] \
        [--skip-alphafold] [--skip-experimental]
"""

import re
import tempfile
from pathlib import Path

import requests
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError

from human_target.services.human_targets import human_proteins_queryset
from tpweb.models.BioentryStructure import ExperimentalStructureXref

RCSB_CIF_URL = "https://files.rcsb.org/download/{pdb_id}.cif"
PROGRESS_EVERY = 250

_AF_FILENAME_RE = re.compile(r"^AF-([A-Za-z0-9]+)-F1-model_v\d+\.cif(\.gz)?$")
_EXPTL_METHOD_RE = re.compile(r"_exptl\.method\s+['\"]?([^'\"\n]+)")


def _index_alphafold_dir(alphafold_dir):
    """One directory scan, not one glob per accession -- {accession: path}."""
    index = {}
    for entry in Path(alphafold_dir).iterdir():
        if not entry.is_file():
            continue
        match = _AF_FILENAME_RE.match(entry.name)
        if match:
            index[match.group(1)] = entry
    return index


def _pdb_ids_from_cross_references(cross_references_raw):
    return [
        (xref.get("id") or "").strip().upper()
        for xref in cross_references_raw or []
        if xref.get("database") == "PDB" and (xref.get("id") or "").strip()
    ]


def _guess_experimental_method(cif_text):
    """Cheap, no-extra-call method label straight out of the CIF we already
    downloaded (e.g. "X-RAY DIFFRACTION", "SOLUTION NMR") -- the pilot got
    this from a manifest file the reference pipeline produced, which
    doesn't exist at bulk scale."""
    match = _EXPTL_METHOD_RE.search(cif_text)
    return match.group(1).strip() if match else ""


class Command(BaseCommand):
    help = (
        "Load AlphaFold-own-model (from an already-extracted bulk archive) and "
        "deduped experimental PDB structures for the full human proteome."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--alphafold-dir",
            default=None,
            metavar="PATH",
            help="Directory of extracted AlphaFold DB CIFs (AF-<accession>-F1-model_v<N>.cif[.gz]).",
        )
        parser.add_argument(
            "--accession",
            action="append",
            default=None,
            help="Restrict to this accession. Repeatable. Default: every curated human protein.",
        )
        parser.add_argument(
            "--accession-file",
            default=None,
            metavar="PATH",
            help="Newline-separated file of accessions, added to --accession (for a small trial batch).",
        )
        parser.add_argument("--datadir", default="/app/targetpathogenweb/data")
        parser.add_argument("--overwrite", action="store_true")
        parser.add_argument("--skip-alphafold", action="store_true")
        parser.add_argument("--skip-experimental", action="store_true")

    def handle(self, *args, **options):
        if not options["skip_alphafold"] and not options["alphafold_dir"]:
            raise CommandError("--alphafold-dir is required unless --skip-alphafold is set.")

        accessions = list(options["accession"] or [])
        if options["accession_file"]:
            with open(options["accession_file"], encoding="utf-8") as f:
                accessions.extend(line.strip() for line in f if line.strip())

        proteins_qs = human_proteins_queryset()
        if accessions:
            proteins_qs = proteins_qs.filter(uniprot_accession__in=accessions)
        # .values_list(), not full HumanProtein instances: at full-proteome
        # scale, materializing every row pulls in uniprot_raw (the complete
        # original UniProt record, kept as an audit trail) and every other
        # JSON field this command never touches -- confirmed via an OOM kill
        # in production (~3.7GB for ~31,000 rows) in the sibling pathways
        # command before the same fix was applied there. Only
        # cross_references_raw and the bioentry FK id are actually needed.
        rows = list(
            proteins_qs.values_list("uniprot_accession", "cross_references_raw", "bioentry_id")
        )
        if not rows:
            raise CommandError("No matching human proteins found.")

        if not options["skip_alphafold"]:
            self._load_alphafold(rows, options)
        if not options["skip_experimental"]:
            self._load_experimental(rows, options)

    def _call_load_af_model(self, code, path, accession, experiment, options):
        try:
            call_command(
                "load_af_model",
                code,
                str(path),
                accession,
                experiment=experiment,
                datadir=options["datadir"],
                overwrite=options["overwrite"],
            )
            return True
        except SystemExit as exc:
            self.stderr.write(f"  {code} for {accession}: {exc}")
            return False
        except CommandError as exc:
            self.stderr.write(f"  {code} for {accession} failed: {exc}")
            return False

    def _load_alphafold(self, rows, options):
        self.stdout.write(f"Indexing {options['alphafold_dir']} ...")
        index = _index_alphafold_dir(options["alphafold_dir"])
        self.stdout.write(f"  {len(index)} AlphaFold model files found.")

        loaded = 0
        missing = 0
        total = len(rows)
        for i, (accession, _cross_refs, _bioentry_id) in enumerate(rows, start=1):
            path = index.get(accession)
            if path is None:
                missing += 1
            elif self._call_load_af_model(f"AF_{accession}", path, accession, "AF", options):
                loaded += 1

            if i % PROGRESS_EVERY == 0 or i == total:
                self.stdout.write(f"  AlphaFold: {i}/{total} processed")

        self.stdout.write(
            self.style.SUCCESS(f"AlphaFold: loaded={loaded} missing={missing} of {total}")
        )

    def _load_experimental(self, rows, options):
        pdb_to_accessions = {}
        for accession, cross_refs, _bioentry_id in rows:
            for pdb_id in _pdb_ids_from_cross_references(cross_refs):
                pdb_to_accessions.setdefault(pdb_id, []).append(accession)

        if not pdb_to_accessions:
            self.stdout.write(
                self.style.WARNING("No PDB cross-references found -- nothing to load.")
            )
            return

        accession_to_bioentry_id = {accession: bioentry_id for accession, _, bioentry_id in rows}
        total = len(pdb_to_accessions)
        self.stdout.write(f"{total} distinct experimental PDB entries across {len(rows)} proteins.")

        linked = 0
        failed = 0
        with tempfile.TemporaryDirectory(prefix="human_pdb_bulk_") as tmp_dir:
            for i, (pdb_id, member_accessions) in enumerate(
                sorted(pdb_to_accessions.items()), start=1
            ):
                try:
                    resp = requests.get(RCSB_CIF_URL.format(pdb_id=pdb_id), timeout=60)
                    resp.raise_for_status()
                except requests.RequestException as exc:
                    self.stderr.write(f"  {pdb_id}: failed to download ({exc}), skipping")
                    failed += 1
                    continue

                cif_path = Path(tmp_dir) / f"{pdb_id}.cif"
                cif_path.write_text(resp.text, encoding="utf-8")
                method = _guess_experimental_method(resp.text)

                for accession in member_accessions:
                    # Unlike the pilot's _load_structures, this writes
                    # ExperimentalStructureXref unconditionally, not only when
                    # load_af_model returns normally. load_af_model raises
                    # SystemExit(1) both on a real failure *and* on its
                    # re-link-an-existing-row branch (the expected path for
                    # every protein here after the first one to reference a
                    # given PDB id, since sharing one is the common case at
                    # this scale) -- skipping the xref write there, as the
                    # pilot does, would leave every such protein's structure
                    # correctly linked but missing from its Structure tab's
                    # own bookkeeping.
                    ok = self._call_load_af_model(pdb_id, cif_path, accession, "EX", options)
                    ExperimentalStructureXref.objects.update_or_create(
                        bioentry_id=accession_to_bioentry_id[accession],
                        pdb_id=pdb_id,
                        defaults={"method": method},
                    )
                    if ok:
                        linked += 1

                if i % PROGRESS_EVERY == 0 or i == total:
                    self.stdout.write(f"  Experimental: {i}/{total} PDB entries processed")

        self.stdout.write(
            self.style.SUCCESS(
                f"Experimental: pdb_entries={total - failed} failed={failed} links={linked}"
            )
        )
