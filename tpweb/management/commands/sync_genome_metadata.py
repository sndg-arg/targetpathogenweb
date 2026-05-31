import gzip
import os
from collections import Counter

from Bio import SeqIO
from django.core.management.base import BaseCommand, CommandError

from bioseq.models.Biodatabase import Biodatabase
from bioseq.models.BiodatabaseQualifierValue import BiodatabaseQualifierValue
from bioseq.models.Ontology import Ontology
from bioseq.models.Term import Term


METADATA_KEYS = (
    "EntryLength",
    "COUNT_gene",
    "COUNT_CDS",
    "COUNT_tRNA",
    "COUNT_rRNA",
    "COUNT_ncRNA",
    "COUNT_tmRNA",
)


def _open_gbk(path):
    if path.endswith(".gz"):
        return gzip.open(path, "rt")
    return open(path, "rt")


class Command(BaseCommand):
    help = "Sync genome-level metadata qualifiers from a GBK file into the assembly biodatabase."

    def add_arguments(self, parser):
        parser.add_argument("assembly_name")
        parser.add_argument("gbk_path")

    def _resolve_term(self, key):
        term = (
            Term.objects.filter(identifier=key).first()
            or Term.objects.filter(name=key).first()
        )
        if term is not None:
            return term

        sample_qv = BiodatabaseQualifierValue.objects.select_related("term__ontology").first()
        ontology = None
        if sample_qv and sample_qv.term:
            ontology = sample_qv.term.ontology
        if ontology is None:
            ontology, _ = Ontology.objects.get_or_create(name="bioindex", defaults={"definition": ""})

        return Term.objects.create(
            name=key,
            identifier=key,
            definition=key,
            ontology=ontology,
        )

    def handle(self, *args, **options):
        assembly_name = str(options["assembly_name"] or "").strip()
        gbk_path = str(options["gbk_path"] or "").strip()
        if not assembly_name:
            raise CommandError("assembly_name is required")
        if not gbk_path or not os.path.exists(gbk_path):
            raise CommandError(f"GBK file not found: {gbk_path}")

        with _open_gbk(gbk_path) as handle:
            records = list(SeqIO.parse(handle, "genbank"))

        if not records:
            raise CommandError(f"No GenBank records found in: {gbk_path}")

        counts = Counter()
        entry_length = 0
        for record in records:
            entry_length += len(record.seq)
            counts.update(feature.type for feature in record.features)
        values = {
            "EntryLength": str(entry_length),
            "COUNT_gene": str(counts.get("gene", 0)),
            "COUNT_CDS": str(counts.get("CDS", 0)),
            "COUNT_tRNA": str(counts.get("tRNA", 0)),
            "COUNT_rRNA": str(counts.get("rRNA", 0)),
            "COUNT_ncRNA": str(counts.get("ncRNA", 0)),
            "COUNT_tmRNA": str(counts.get("tmRNA", 0)),
        }

        biodb = Biodatabase.objects.get(name=assembly_name)
        updated = 0
        for key in METADATA_KEYS:
            term = self._resolve_term(key)
            obj, _created = BiodatabaseQualifierValue.objects.get_or_create(
                biodatabase=biodb,
                term=term,
                defaults={"value": values[key], "rank": 0},
            )
            obj.value = values[key]
            obj.rank = 0
            obj.save(update_fields=["value", "rank"])
            updated += 1

        self.stdout.write(
            f"Synced {updated} genome metadata values for {assembly_name}: "
            + ", ".join(f"{key}={values[key]}" for key in METADATA_KEYS)
        )
