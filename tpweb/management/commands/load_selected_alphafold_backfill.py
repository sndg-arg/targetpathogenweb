import csv
import math
import os

import requests
from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError

from bioseq.io.SeqStore import SeqStore
from bioseq.models.Biodatabase import Biodatabase
from bioseq.models.Bioentry import Bioentry
from tpweb.management.commands.load_af_model import store_structure_file
from tpweb.models.BioentryStructure import BioentryStructure
from tpweb.models.pdb import PDB


DEFAULT_DATA_DIR = str(settings.BASE_DIR / "data")
DEFAULT_TIMEOUT = 60
AFDB_API_URL = "https://alphafold.ebi.ac.uk/api/prediction/{accession}"


def clean(value):
    value = str(value or "").strip()
    if value.lower() in {"", "nan", "none", "null"}:
        return ""
    return value


def as_bool(value):
    return clean(value).lower() in {"1", "true", "yes", "y"}


def folder_path(datadir, genome_name):
    acclen = len(genome_name)
    folder_name = genome_name[math.floor(acclen / 2 - 1):math.floor(acclen / 2 + 2)]
    return os.path.join(datadir, folder_name, genome_name)


def default_manifest(datadir, genome_name):
    return os.path.join(
        folder_path(datadir, genome_name),
        "selected_alphafold_jobs",
        f"{genome_name}_selected_alphafold.tsv",
    )


def default_model_dir(datadir, genome_name):
    return os.path.join(folder_path(datadir, genome_name), "selected_alphafold_jobs", "models")


def read_manifest(path):
    if not os.path.exists(path):
        raise CommandError(f"Manifest not found: {path}")
    with open(path, newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def structure_code(accession):
    return f"AF_{clean(accession).upper()}"


def resolve_afdb_model_url(accession, fallback_url, timeout):
    api_url = AFDB_API_URL.format(accession=accession)
    try:
        response = requests.get(api_url, timeout=timeout)
        if response.status_code == 404:
            return "", "unavailable"
        response.raise_for_status()
        payload = response.json()
        if isinstance(payload, list) and payload:
            pdb_url = clean(payload[0].get("pdbUrl"))
            if pdb_url:
                return pdb_url, "api"
        return "", "unavailable"
    except Exception as exc:
        if fallback_url:
            return fallback_url, f"fallback:{exc}"
        return "", f"failed:{exc}"


def download_model(accession, fallback_url, dest_path, timeout):
    url, source = resolve_afdb_model_url(accession, fallback_url, timeout)
    if not url:
        return source

    os.makedirs(os.path.dirname(dest_path), exist_ok=True)
    tmp_path = f"{dest_path}.tmp"
    try:
        with requests.get(url, stream=True, timeout=timeout) as response:
            if response.status_code == 404:
                return "unavailable"
            response.raise_for_status()
            with open(tmp_path, "wb") as handle:
                for chunk in response.iter_content(chunk_size=1024 * 1024):
                    if chunk:
                        handle.write(chunk)
        if os.path.getsize(tmp_path) <= 100:
            return "empty"
        os.replace(tmp_path, dest_path)
        os.chmod(dest_path, 0o644)
        return f"downloaded:{source}"
    except Exception as exc:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
        return f"failed:{exc}"


def ensure_seqstore_copy(seqstore, genome_name, locus, code, model_path):
    destination = seqstore.structure(genome_name, locus, code)
    if os.path.exists(destination) and os.path.getsize(destination) > 100:
        return False
    store_structure_file(model_path, destination)
    return True


def link_existing_structure(protein, pdb_obj):
    _link, created = BioentryStructure.objects.get_or_create(bioentry=protein, pdb=pdb_obj)
    return created


def job_is_linked(job, proteins):
    return BioentryStructure.objects.filter(
        bioentry=proteins[job["locus"]],
        pdb__code=job["code"],
        pdb__experiment="AF",
    ).exists()


class Command(BaseCommand):
    help = "Download/load selected AlphaFold DB models from curated selected-source manifests."

    def add_arguments(self, parser):
        parser.add_argument("genome_name")
        parser.add_argument("--datadir", default=DEFAULT_DATA_DIR)
        parser.add_argument("--manifest", default=None)
        parser.add_argument("--model-dir", default=None)
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument(
            "--include-loaded",
            action="store_true",
            help="Process rows already linked in TPW. By default batches are resumable and skip linked jobs before applying --limit.",
        )
        parser.add_argument("--limit", type=int, default=None)
        parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT)
        parser.add_argument("--redownload", action="store_true")
        parser.add_argument("--overwrite-structures", action="store_true")

    def handle(self, *args, **options):
        genome_name = options["genome_name"]
        datadir = options["datadir"].rstrip("/\\")
        manifest_path = options["manifest"] or default_manifest(datadir, genome_name)
        model_dir = options["model_dir"] or default_model_dir(datadir, genome_name)
        dry_run = options["dry_run"]
        include_loaded = options["include_loaded"]
        limit = options["limit"]
        timeout = options["timeout"]
        redownload = options["redownload"]
        overwrite_structures = options["overwrite_structures"]

        db_name = genome_name + Biodatabase.PROT_POSTFIX
        try:
            db = Biodatabase.objects.get(name=db_name)
        except Biodatabase.DoesNotExist as exc:
            raise CommandError(f"Protein database not found: {db_name}") from exc

        proteins = {p.accession: p for p in Bioentry.objects.filter(biodatabase=db).only("bioentry_id", "accession")}
        rows = read_manifest(manifest_path)

        jobs = {}
        missing_loci = 0
        for row in rows:
            if clean(row.get("genome")) and clean(row.get("genome")) != genome_name:
                continue
            locus = clean(row.get("locus"))
            accession = clean(row.get("uniprot_accession")).upper()
            if not locus or not accession:
                continue
            if locus not in proteins:
                missing_loci += 1
                continue
            key = (locus, accession)
            job = jobs.setdefault(key, {
                "locus": locus,
                "accession": accession,
                "code": structure_code(accession),
                "url": clean(row.get("model_url")),
                "need_fpocket": False,
                "need_p2rank": False,
                "selected_by": set(),
            })
            if as_bool(row.get("need_fpocket")):
                job["need_fpocket"] = True
                job["selected_by"].add("FPocket")
            if as_bool(row.get("need_p2rank")):
                job["need_p2rank"] = True
                job["selected_by"].add("P2Rank")

        all_jobs = sorted(jobs.values(), key=lambda item: (item["locus"], item["accession"]))
        pending_jobs = [
            job for job in all_jobs
            if include_loaded or not job_is_linked(job, proteins)
        ]
        job_list = pending_jobs[:limit] if limit is not None else pending_jobs

        self.stdout.write(self.style.MIGRATE_HEADING(f"Selected AlphaFold model backfill for {genome_name}"))
        self.stdout.write(f"Manifest rows: {len(rows)}")
        self.stdout.write(f"Unique locus/accession jobs: {len(jobs)}")
        self.stdout.write(f"Pending jobs: {len(pending_jobs)}")
        self.stdout.write(f"Already linked jobs: {len(all_jobs) - len(pending_jobs)}")
        self.stdout.write(f"Missing loci in DB: {missing_loci}")
        if limit is not None:
            self.stdout.write(f"Processing limit: {len(job_list)}/{len(pending_jobs)} pending")
        self.stdout.write(f"Model dir: {model_dir}")
        if dry_run:
            existing_models = existing_links = unavailable = 0
            for job in job_list:
                model_path = os.path.join(model_dir, f"{job['code']}.pdb")
                if os.path.exists(model_path) and os.path.getsize(model_path) > 100:
                    existing_models += 1
                if job_is_linked(job, proteins):
                    existing_links += 1
                if not job.get("url"):
                    unavailable += 1
            self.stdout.write(f"Existing local model files: {existing_models}")
            self.stdout.write(f"Already linked structures: {existing_links}")
            self.stdout.write(f"Rows without model URL: {unavailable}")
            self.stdout.write("Examples:")
            for job in job_list[:25]:
                methods = ",".join(sorted(job["selected_by"])) or "-"
                self.stdout.write(f"  would load {job['locus']} {job['code']} ({methods}) {job['url']}")
            if len(job_list) > 25:
                self.stdout.write(f"  ... {len(job_list) - 25} more")
            return

        os.makedirs(model_dir, exist_ok=True)
        seqstore = SeqStore(datadir)
        downloaded = reused_file = unavailable = download_failed = loaded = linked = copied = skipped_existing = failed = 0

        for job in job_list:
            locus = job["locus"]
            accession = job["accession"]
            code = job["code"]
            url = job["url"]
            protein = proteins[locus]
            model_path = os.path.join(model_dir, f"{code}.pdb")

            if os.path.exists(model_path) and os.path.getsize(model_path) > 100 and not redownload:
                reused_file += 1
            elif not url:
                unavailable += 1
                self.stderr.write(f"missing model URL: {locus} {code}")
                continue
            else:
                status = download_model(accession, url, model_path, timeout)
                if status.startswith("downloaded"):
                    downloaded += 1
                elif status == "unavailable":
                    unavailable += 1
                    self.stderr.write(f"model unavailable: {locus} {code} {url}")
                    continue
                else:
                    download_failed += 1
                    self.stderr.write(f"download failed: {locus} {code}: {status}")
                    continue

            pdb_obj = PDB.objects.filter(code=code, experiment="AF", deprecated=False).first()
            if pdb_obj is None or overwrite_structures:
                try:
                    call_command(
                        "load_af_model",
                        code,
                        model_path,
                        locus,
                        experiment="AF",
                        datadir=datadir,
                        overwrite=overwrite_structures,
                        verbosity=0,
                    )
                    pdb_obj = PDB.objects.get(code=code, experiment="AF", deprecated=False)
                    loaded += 1
                except SystemExit as exc:
                    if exc.code == 0:
                        pdb_obj = PDB.objects.filter(code=code, experiment="AF", deprecated=False).first()
                        loaded += 1
                    else:
                        failed += 1
                        self.stderr.write(f"load_af_model exited {exc.code}: {locus} {code}")
                        continue
                except Exception as exc:
                    failed += 1
                    self.stderr.write(f"load_af_model failed: {locus} {code}: {exc}")
                    continue
            else:
                skipped_existing += 1

            if pdb_obj is None:
                failed += 1
                self.stderr.write(f"loaded PDB object not found: {locus} {code}")
                continue

            if link_existing_structure(protein, pdb_obj):
                linked += 1
            if ensure_seqstore_copy(seqstore, genome_name, locus, code, model_path):
                copied += 1

        self.stdout.write("")
        self.stdout.write(f"Downloaded: {downloaded}")
        self.stdout.write(f"Reused local files: {reused_file}")
        self.stdout.write(f"Unavailable models: {unavailable}")
        self.stdout.write(f"Download failed: {download_failed}")
        self.stdout.write(f"Loaded new structures: {loaded}")
        self.stdout.write(f"Skipped existing structures: {skipped_existing}")
        self.stdout.write(f"Created new protein links: {linked}")
        self.stdout.write(f"Copied files to SeqStore: {copied}")
        self.stdout.write(f"Failed loads: {failed}")
