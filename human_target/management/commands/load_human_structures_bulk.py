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
     re-link-on-existing-row branch, added earlier this session). Fetched
     with `--workers` parallel threads (default 4, matching the pipeline's
     own AlphaFold-download concurrency) since this step is the real
     bottleneck at full-proteome scale (tens of thousands of distinct PDB
     entries). Resumable: a PDB id already loaded by an earlier (possibly
     interrupted) run is detected up front and never re-downloaded, only
     re-linked for whichever proteins still need it.

Both reuse `load_af_model` completely unchanged, exactly like the pilot
does -- including catching its SystemExit/CommandError for a graceful
per-structure skip instead of aborting the whole run.

AlphaFill is opt-in via --alphafill-dir, staged with
scripts/cluster/fetch_human_alphafill_bulk.sh using the public rsync bank.
Only canonical F1 models are loaded, as in the AlphaFold pass.

Usage:
    python manage.py load_human_structures_bulk --alphafold-dir /path/to/extracted \
        [--accession P10721 --accession O00116 ...] [--accession-file PATH] \
        [--datadir /app/targetpathogenweb/data] [--overwrite] [--workers 4] \
        [--skip-alphafold] [--skip-experimental] [--alphafill-dir PATH]
"""

import re
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError

from human_target.services.human_targets import human_proteins_queryset
from tpweb.models.BioentryStructure import BioentryStructure, ExperimentalStructureXref
from tpweb.models.pdb import PDB

RCSB_CIF_URL = "https://files.rcsb.org/download/{pdb_id}.cif"
PROGRESS_EVERY = 250
DEFAULT_EXPERIMENTAL_WORKERS = 4

_AF_FILENAME_RE = re.compile(r"^AF-([A-Za-z0-9]+)-F1-model_v\d+\.cif(\.gz)?$")
_AFILL_FILENAME_RE = re.compile(r"^AF-([A-Za-z0-9]+)-F1-filled_v(\d+)\.cif(\.gz)?$")
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


def _index_alphafill_dir(directory):
    """Read a flat or rsync-sharded bank; prefer the newest numeric version."""
    index = {}
    versions = {}
    root = Path(directory)
    folders = [root, *(entry for entry in root.iterdir() if entry.is_dir())]
    for folder in folders:
        for entry in sorted(folder.iterdir()):
            match = _AFILL_FILENAME_RE.fullmatch(entry.name)
            if not match or not entry.is_file():
                continue
            accession, version = match.group(1), int(match.group(2))
            if version > versions.get(accession, -1):
                versions[accession] = version
                index[accession] = entry
    return index


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
        "deduped experimental PDB structures for the full human proteome, with optional AlphaFill."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--alphafill-dir",
            metavar="PATH",
            help="Optional flat or rsync-sharded directory of AlphaFill filled_v<N> CIFs.",
        )
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
        parser.add_argument(
            "--workers",
            type=int,
            default=DEFAULT_EXPERIMENTAL_WORKERS,
            help=(
                "Parallel download/parse workers for the experimental-PDB pass "
                f"(default {DEFAULT_EXPERIMENTAL_WORKERS}, matching the pipeline's own "
                "AlphaFold-download concurrency)."
            ),
        )

    def handle(self, *args, **options):
        if not options["skip_alphafold"] and not options["alphafold_dir"]:
            raise CommandError("--alphafold-dir is required unless --skip-alphafold is set.")
        if options["alphafill_dir"] and not Path(options["alphafill_dir"]).is_dir():
            raise CommandError("--alphafill-dir must be an existing directory.")

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
        if options["alphafill_dir"]:
            self._load_alphafill(rows, options)

    def _load_alphafill(self, rows, options):
        index = _index_alphafill_dir(options["alphafill_dir"])
        if not index:
            raise CommandError("No canonical AlphaFill filled_v<N> CIF files found.")
        completed = set()
        if not options["overwrite"]:
            completed = set(
                BioentryStructure.objects.filter(
                    bioentry_id__in=[row[2] for row in rows],
                    pdb__experiment="AFILL",
                    pdb__deprecated=False,
                ).values_list("bioentry_id", "pdb__code")
            )
        loaded = missing = skipped = failed = 0
        for i, (accession, _cross_refs, bioentry_id) in enumerate(rows, start=1):
            code = f"AFILL_{accession}"
            if (bioentry_id, code) in completed:
                skipped += 1
            elif accession not in index:
                missing += 1
            elif self._call_load_af_model(code, index[accession], accession, "AFILL", options):
                loaded += 1
            else:
                failed += 1
            if i % PROGRESS_EVERY == 0 or i == len(rows):
                self.stdout.write(f"  AlphaFill: {i}/{len(rows)} processed")
        self.stdout.write(
            f"AlphaFill: loaded={loaded} skipped={skipped} missing={missing} failed={failed}"
        )
        if failed:
            raise CommandError(f"AlphaFill: {failed} structures failed; rerun to retry.")

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
            return BioentryStructure.objects.filter(
                bioentry__accession=accession,
                pdb__code=code,
                pdb__experiment=experiment,
                pdb__deprecated=False,
            ).exists()
        except SystemExit as exc:
            self.stderr.write(f"  {code} for {accession}: {exc}")
            return BioentryStructure.objects.filter(
                bioentry__accession=accession,
                pdb__code=code,
                pdb__experiment=experiment,
                pdb__deprecated=False,
            ).exists()
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
        completed = set()
        if not options["overwrite"]:
            bioentry_ids = {bioentry_id for _, _, bioentry_id in rows}
            completed = set(
                ExperimentalStructureXref.objects.filter(bioentry_id__in=bioentry_ids)
                .values_list("bioentry_id", "pdb_id")
                .iterator(chunk_size=2000)
            )
            # An xref alone is not proof that load_af_model succeeded.
            completed.intersection_update(
                BioentryStructure.objects.filter(bioentry_id__in=bioentry_ids, pdb__experiment="EX")
                .values_list("bioentry_id", "pdb__code")
                .iterator(chunk_size=2000)
            )

        pdb_to_accessions = {}
        skipped = 0
        for accession, cross_refs, bioentry_id in rows:
            for pdb_id in dict.fromkeys(_pdb_ids_from_cross_references(cross_refs)):
                if (bioentry_id, pdb_id) in completed:
                    skipped += 1
                    continue
                pdb_to_accessions.setdefault(pdb_id, []).append(accession)

        self.stdout.write(f"Experimental: skipped {skipped} already-linked protein-PDB pairs.")
        if not pdb_to_accessions:
            self.stdout.write(
                self.style.SUCCESS("No pending PDB cross-references -- nothing to load.")
            )
            return

        accession_to_bioentry_id = {accession: bioentry_id for accession, _, bioentry_id in rows}
        total = len(pdb_to_accessions)
        workers = max(1, options["workers"])
        self.stdout.write(
            f"{total} distinct experimental PDB entries across {len(rows)} proteins "
            f"({workers} parallel workers)."
        )

        linked = 0
        failed = 0
        done = 0
        progress_lock = threading.Lock()
        with tempfile.TemporaryDirectory(prefix="human_pdb_bulk_") as tmp_dir:
            with ThreadPoolExecutor(max_workers=workers) as pool:
                futures = {
                    pool.submit(
                        self._process_one_experimental_entry,
                        pdb_id,
                        member_accessions,
                        accession_to_bioentry_id,
                        options,
                        tmp_dir,
                    ): pdb_id
                    for pdb_id, member_accessions in pdb_to_accessions.items()
                }
                for future in as_completed(futures):
                    pdb_id = futures[future]
                    try:
                        entry_linked, entry_failed = future.result()
                    except (
                        Exception
                    ) as exc:  # pragma: no cover -- defensive, workers shouldn't raise
                        self.stderr.write(f"  {pdb_id}: unexpected error ({exc}), skipping")
                        entry_linked, entry_failed = 0, 1

                    with progress_lock:
                        linked += entry_linked
                        failed += entry_failed
                        done += 1
                        if done % PROGRESS_EVERY == 0 or done == total:
                            self.stdout.write(
                                f"  Experimental: {done}/{total} PDB entries processed"
                            )

        self.stdout.write(
            self.style.SUCCESS(
                f"Experimental: pdb_entries={total - failed} failed={failed} links={linked}"
            )
        )

    def _process_one_experimental_entry(
        self, pdb_id, member_accessions, accession_to_bioentry_id, options, tmp_dir
    ):
        """Runs in a worker thread -- download (or reuse) one PDB entry's
        CIF and link every protein that references it. Returns
        (linked_count, failed_count) for the caller to aggregate; an
        ordinary network/parse failure is counted as failed=1 here, never
        raised, consistent with this command's graceful-skip design
        elsewhere. Each thread gets its own DB connection automatically
        (Django's connections are thread-local) -- no extra locking needed
        around the ORM calls themselves, only around the shared progress
        counters in the caller."""
        cif_path = Path(tmp_dir) / f"{pdb_id}.cif"
        if PDB.objects.filter(code=pdb_id, experiment="EX").exists():
            # Already downloaded and parsed by an earlier (possibly
            # interrupted) run -- skip the network fetch entirely, just
            # make sure every member protein ends up linked. load_af_model
            # still checks os.path.exists(pdb_file) *before* checking
            # whether the PDB row already exists, so it needs *a* file at
            # this path -- an empty placeholder is enough, since its
            # content is never read on the already-exists branch.
            if not cif_path.exists():
                cif_path.touch()
            method = (
                ExperimentalStructureXref.objects.filter(pdb_id=pdb_id)
                .exclude(method="")
                .values_list("method", flat=True)
                .first()
                or ""
            )
        else:
            try:
                resp = requests.get(RCSB_CIF_URL.format(pdb_id=pdb_id), timeout=60)
                resp.raise_for_status()
            except requests.RequestException as exc:
                self.stderr.write(f"  {pdb_id}: failed to download ({exc}), skipping")
                return 0, 1
            cif_path.write_text(resp.text, encoding="utf-8")
            method = _guess_experimental_method(resp.text)

        linked = 0
        failed = False
        for accession in member_accessions:
            ok = self._call_load_af_model(pdb_id, cif_path, accession, "EX", options)
            if not ok:
                failed = True
                continue
            ExperimentalStructureXref.objects.update_or_create(
                bioentry_id=accession_to_bioentry_id[accession],
                pdb_id=pdb_id,
                defaults={"method": method},
            )
            if ok:
                linked += 1
        return linked, int(failed)
