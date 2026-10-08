"""Full-proteome ingestion: UniProt bulk JSON stream -> HumanProtein (+
Biosequence, Bioentry, dbxrefs, EC/GO annotations).

Scale companion to `import_human_curated_proteins.py`'s fixture-based ingest.
Reuses its pure parsing helpers (`_build_human_protein_fields` and everything
it calls, `_extract_ec_numbers`) and its `_write_uniprot_dbxref` instance
method completely unchanged -- confirmed this session, field-by-field against
the real UniProt bulk stream, that the per-entry JSON shape is identical to
the single-accession/fixture shape those helpers already expect (the only
diff observed was `entryAudit.entryVersion` being two ahead of the Zenodo
snapshot, i.e. normal upstream drift, not a shape mismatch).

Reads a local copy of UniProt's bulk reference-proteome stream:

    https://rest.uniprot.org/uniprotkb/stream?query=proteome:UP000005640&format=json&compressed=true

downloaded once onto the cluster's assigned storage via
`scripts/cluster/fetch_human_proteome_bulk.sh`, then rsynced to wherever this
container can read it (see docs/CLUSTER_DEPLOY.md). Streams the file with
`ijson` instead of `json.load()` -- the full proteome is a few GB
uncompressed, no reason to hold it all in memory at once.

Also writes a `bioseq.models.Biosequence` row per protein (`seq`/`length`),
which `import_human_curated_proteins.py` never did -- without it, the
bacterial-shared `dump_genome_proteins_fasta` command (needed later to dump a
FASTA for LigQ_2) silently finds no sequence for any human protein and writes
nothing. Apply the same fix to the pilot's own ingest in the same change.

Usage:
    python manage.py import_human_proteome_bulk /path/to/uniprot_human_proteome.json.gz \
        [--accession P10721 --accession O00116 ...] [--dry-run] [--batch-size 500]
"""

import gzip

import ijson
from django.core.management.base import BaseCommand
from django.db import transaction

from bioseq.models.Bioentry import Bioentry
from bioseq.models.Biosequence import Biosequence
from bioseq.models.Ontology import Ontology

from human_target.management.commands.import_human_curated_proteins import (
    Command as PilotCommand,
)
from human_target.management.commands.import_human_curated_proteins import (
    _build_human_protein_fields,
    _extract_ec_numbers,
)
from human_target.models.HumanProtein import HumanProtein
from human_target.services.human_targets import get_or_create_human_biodatabase
from tpweb.services.functional_annotations import persist_ec_go_annotations

PROGRESS_EVERY = 1000


def _open_bulk_file(path):
    return gzip.open(path, "rb") if path.endswith(".gz") else open(path, "rb")


class Command(BaseCommand):
    help = "Ingest the full human reference proteome from a local bulk UniProt JSON stream."

    def add_arguments(self, parser):
        parser.add_argument(
            "bulk_json_path",
            help="Local path to the downloaded UniProt bulk stream (.json or .json.gz).",
        )
        parser.add_argument(
            "--accession",
            action="append",
            default=None,
            help="Restrict ingestion to this accession. Repeatable. Default: every entry in the file.",
        )
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument(
            "--batch-size",
            type=int,
            default=500,
            help="How many accessions' worth of parsed fields to buffer before writing (default 500).",
        )

    def handle(self, *args, **options):
        path = options["bulk_json_path"]
        accession_filter = set(options["accession"]) if options["accession"] else None
        dry_run = options["dry_run"]
        batch_size = options["batch_size"]

        biodatabase = ec_ontology = go_ontology = None
        if not dry_run:
            biodatabase = get_or_create_human_biodatabase()
            ec_ontology, _ = Ontology.objects.get_or_create(
                name=Ontology.EC, defaults={"definition": ""}
            )
            go_ontology, _ = Ontology.objects.get_or_create(
                name=Ontology.GO, defaults={"definition": ""}
            )

        # Reused only for its _write_uniprot_dbxref instance method -- that
        # method has no state of its own, instantiating the pilot command
        # just to call it is cheaper than extracting it for one caller.
        pilot = PilotCommand()

        attempted = succeeded = failed = skipped_filtered = 0
        batch = []

        with _open_bulk_file(path) as fh:
            for entry in ijson.items(fh, "results.item"):
                accession = entry.get("primaryAccession", "")
                if not accession:
                    continue
                if accession_filter and accession not in accession_filter:
                    skipped_filtered += 1
                    continue

                attempted += 1
                try:
                    fields = _build_human_protein_fields(entry)
                except Exception as exc:  # noqa: BLE001 -- one bad entry must not abort the stream
                    self.stderr.write(f"skip {accession}: field extraction failed: {exc}")
                    failed += 1
                    continue

                if dry_run:
                    self.stdout.write(
                        f"[dry-run] would ingest {accession}: {fields['sequence_length']} aa"
                    )
                    succeeded += 1
                    continue

                batch.append((accession, entry, fields))
                if len(batch) >= batch_size:
                    s, f = self._write_batch(batch, biodatabase, ec_ontology, go_ontology, pilot)
                    succeeded += s
                    failed += f
                    batch = []

                if attempted % PROGRESS_EVERY == 0:
                    self.stdout.write(
                        f"  ... {attempted} attempted, {succeeded} succeeded, {failed} failed so far"
                    )

            if batch:
                s, f = self._write_batch(batch, biodatabase, ec_ontology, go_ontology, pilot)
                succeeded += s
                failed += f

        self.stdout.write(
            self.style.SUCCESS(
                f"attempted={attempted} succeeded={succeeded} failed={failed} "
                f"skipped_filtered={skipped_filtered}"
            )
        )

    def _write_batch(self, batch, biodatabase, ec_ontology, go_ontology, pilot):
        succeeded = failed = 0
        for accession, entry, fields in batch:
            try:
                with transaction.atomic():
                    bioentry, _ = Bioentry.objects.get_or_create(
                        biodatabase=biodatabase,
                        accession=accession,
                        defaults={"name": accession, "identifier": accession},
                    )
                    HumanProtein.objects.update_or_create(
                        bioentry=bioentry,
                        defaults={"uniprot_accession": accession, **fields},
                    )
                    Biosequence.objects.update_or_create(
                        bioentry=bioentry,
                        defaults={
                            "seq": fields["sequence"],
                            "length": fields["sequence_length"] or len(fields["sequence"]),
                        },
                    )
                    pilot._write_uniprot_dbxref(bioentry, accession, fields["is_reviewed"])
                    persist_ec_go_annotations(
                        bioentry, _extract_ec_numbers(entry), "ec", ec_ontology
                    )
                    persist_ec_go_annotations(
                        bioentry, fields["go_terms"], Ontology.GO, go_ontology
                    )
                succeeded += 1
            except Exception as exc:  # noqa: BLE001 -- one bad accession must not abort the batch
                self.stderr.write(f"failed {accession}: {exc}")
                failed += 1
        return succeeded, failed
