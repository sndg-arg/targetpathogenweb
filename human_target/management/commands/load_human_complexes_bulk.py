"""Load CORUM human protein complexes and link them to their member proteins.

CORUM's download API (mips.helmholtz-muenchen.de/fastapi-corum) serves an
incomplete TLS chain, so neither nodo0 nor the login node can fetch it with
certificate checks on. Download `humanComplexes.txt` in a browser
(https://mips.helmholtz-muenchen.de/corum/download, "Human complexes", txt),
put it on the login node, and read it from there:

    python manage.py load_human_complexes_bulk \
        --remote-file /storage/home/agutson/corum/corum_humanComplexes.txt [--dry-run]

or pass a local copy with --file. Re-running replaces every complex and link,
so a newer CORUM release can be loaded over an older one.

CORUM is CC BY-NC 4.0: academic use with attribution.
"""

import configparser
import csv
import io
import sys
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from human_target.models.HumanComplex import HumanComplex
from human_target.models.HumanProteinComplex import HumanProteinComplex
from human_target.services.human_targets import human_proteins_queryset

_EMPTY = ("", "None", "NULL")


def _clean(value):
    value = (value or "").strip()
    return "" if value in _EMPTY else value


def _split(value):
    value = _clean(value)
    return [part.strip() for part in value.split(";")] if value else []


def _at(values, index):
    return _clean(values[index]) if index < len(values) else ""


def parse_corum(text):
    """CORUM's tab-separated export -> one dict per human complex. Pure."""
    csv.field_size_limit(2**31 - 1)
    complexes = []
    reader = csv.DictReader(io.StringIO(text), delimiter="\t", quoting=csv.QUOTE_NONE)
    for row in reader:
        corum_id = _clean(row.get("complex_id"))
        if not corum_id.isdigit() or _clean(row.get("organism")) not in ("Human", "Homo sapiens"):
            continue
        accessions = _split(row.get("subunits_uniprot_id"))
        genes = _split(row.get("subunits_gene_name"))
        names = _split(row.get("subunits_protein_name"))
        subunits = [
            {"accession": accession, "gene": _at(genes, i), "name": _at(names, i)}
            for i, accession in enumerate(accessions)
            if _clean(accession)
        ]
        go_ids = _split(row.get("functions_go_id"))
        go_names = _split(row.get("functions_go_name"))
        go_terms = [
            {"id": go_id, "name": _at(go_names, i)}
            for i, go_id in enumerate(go_ids)
            if go_id.startswith("GO:")
        ]
        # "MI:0007:anti tag coimmunoprecipitation" -> the readable name.
        methods = list(
            dict.fromkeys(
                method.split(":", 2)[-1].strip()
                for method in _split(row.get("purification_methods"))
                if _clean(method)
            )
        )
        complexes.append(
            {
                "corum_id": int(corum_id),
                "name": _clean(row.get("complex_name"))[:512] or f"CORUM {corum_id}",
                "synonyms": _clean(row.get("synonyms")),
                "cell_line": _clean(row.get("cell_line")),
                "pmid": _clean(row.get("pmid"))[:32],
                "comment": _clean(row.get("comment_complex")),
                "disease_comment": _clean(row.get("comment_disease")),
                "purification_methods": methods,
                "go_terms": go_terms,
                "subunits": subunits,
            }
        )
    return complexes


def canonical_accession(accession):
    """CORUM sometimes names an isoform (P12345-2); proteins are canonical."""
    return accession.split("-", 1)[0].strip().upper()


class Command(BaseCommand):
    help = "Load CORUM human complexes and link them to human proteins."

    def add_arguments(self, parser):
        source = parser.add_mutually_exclusive_group(required=True)
        source.add_argument("--file", help="Local CORUM humanComplexes .txt")
        source.add_argument("--remote-file", help="CORUM .txt on the login node")
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        text = self._read(options)
        complexes = parse_corum(text)
        if not complexes:
            raise CommandError("No human complexes found; is this the CORUM txt export?")

        protein_ids = dict(human_proteins_queryset().values_list("uniprot_accession", "id"))
        links = {
            (protein_ids[accession], row["corum_id"])
            for row in complexes
            for accession in {canonical_accession(s["accession"]) for s in row["subunits"]}
            if accession in protein_ids
        }
        linked_proteins = len({protein for protein, _ in links})
        self.stdout.write(
            f"CORUM: {len(complexes)} human complexes; {len(links)} links "
            f"to {linked_proteins} of {len(protein_ids)} human proteins."
        )
        if options["dry_run"]:
            return

        with transaction.atomic():
            HumanProteinComplex.objects.all().delete()
            HumanComplex.objects.all().delete()
            created = HumanComplex.objects.bulk_create(
                [HumanComplex(**row) for row in complexes], batch_size=1000
            )
            by_corum = {item.corum_id: item.id for item in created}
            HumanProteinComplex.objects.bulk_create(
                [
                    HumanProteinComplex(human_protein_id=protein, complex_id=by_corum[corum])
                    for protein, corum in links
                ],
                batch_size=5000,
            )
        self.stdout.write(self.style.SUCCESS("CORUM complexes loaded."))

    def _read(self, options):
        if options["file"]:
            return Path(options["file"]).read_text(encoding="utf-8")
        pipeline_dir = str(settings.BASE_DIR / "pipeline")
        if pipeline_dir not in sys.path:
            sys.path.insert(0, pipeline_dir)
        from ligq_remote import _build_ligq_config
        from slurm_remote_command import _close_remote_session, _open_remote_session

        cfg = configparser.ConfigParser()
        cfg.read(Path(pipeline_dir) / "settings.ini")
        ssh, scp, sftp = _open_remote_session(_build_ligq_config(cfg))
        try:
            with sftp.open(options["remote_file"], "rb") as handle:
                return handle.read().decode("utf-8")
        except OSError as exc:
            raise CommandError(f"Cannot read {options['remote_file']}: {exc}") from exc
        finally:
            _close_remote_session(ssh, scp, sftp)
