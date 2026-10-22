import csv
import gzip
import hashlib
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory

from django.core.management.base import CommandError
from django.test import TestCase, SimpleTestCase
from bioseq.models.Biodatabase import Biodatabase
from bioseq.models.Bioentry import Bioentry
from bioseq.models.BioentryDbxref import BioentryDbxref
from bioseq.models.Dbxref import Dbxref
from bioseq.models.Ontology import Ontology
from tpweb.management.commands.load_interpro_go import Command, collect_go
from tpweb.management.commands.load_genbank_ec import Command as GenBankECCommand
from Bio.Seq import Seq
from Bio.SeqRecord import SeqRecord
from Bio.SeqFeature import SeqFeature, FeatureLocation


CHECKSUM = hashlib.md5(b"MAU").hexdigest()


def row(locus="LOC1", checksum=CHECKSUM, length="3", terms="GO:0016020|GO:0022857"):
    return [locus, checksum, length] + ["-"] * 10 + [terms]


class InterproGoParserTests(SimpleTestCase):
    def test_repeated_domains_and_go_provenance_collapse_to_unique_terms(self):
        expected = {"LOC1": (42, CHECKSUM, 3)}
        self.assertEqual(
            collect_go(
                [
                    row(terms="GO:0016020(InterPro)|GO:0022857(PANTHER)"),
                    row(),
                ],
                expected,
            ),
            {42: {"GO:0016020", "GO:0022857"}},
        )

    def test_unknown_locus_or_changed_sequence_is_rejected(self):
        for bad in [row(locus="UNKNOWN"), row(checksum="0" * 32), row(length="4")]:
            with self.subTest(bad=bad), self.assertRaises(CommandError):
                collect_go([bad], {"LOC1": (42, CHECKSUM, 3)})

    def test_rows_without_go_are_not_invented_annotations(self):
        self.assertEqual(collect_go([row(terms="-"), ["short"]], {}), {})


class InterproGoImportTests(TestCase):
    def setUp(self):
        self.genome = "public__interpro_go_test"
        database = Biodatabase.objects.create(name=self.genome + Biodatabase.PROT_POSTFIX)
        self.protein = Bioentry.objects.create(
            biodatabase=database, accession="LOC1", name="LOC1", identifier="LOC1"
        )
        relation = Bioentry._meta.get_field("seq")
        model = relation.related_model
        available = {field.name for field in model._meta.fields}
        values = {
            key: value
            for key, value in {
                "seq": "MAU",
                "length": 3,
                "version": 0,
                "alphabet": "protein",
            }.items()
            if key in available
        }
        if relation.auto_created:
            model.objects.create(bioentry=self.protein, **values)
        else:
            self.protein.seq = model.objects.create(**values)
            self.protein.save(update_fields=["seq"])

    def run_import(self, rows, apply=True, compressed=False):
        with TemporaryDirectory() as temp:
            path = Path(temp) / ("interpro.tsv.gz" if compressed else "interpro.tsv")
            opener = gzip.open if compressed else open
            with opener(path, "wt", newline="", encoding="utf-8") as handle:
                csv.writer(handle, delimiter="\t").writerows(rows)
            output = StringIO()
            Command(stdout=output).handle(
                genome_name=self.genome,
                interpro_tsv=str(path),
                apply=apply,
            )
            return output.getvalue()

    def test_preview_validates_without_writes(self):
        self.assertIn("1/1 proteins", self.run_import([row()], apply=False))
        self.assertEqual(Dbxref.objects.count(), 0)
        self.assertEqual(Ontology.objects.count(), 0)

    def test_additive_import_is_idempotent_and_supports_gzip(self):
        old = Dbxref.objects.create(dbname=Ontology.GO, accession="GO:9999999", version=0)
        BioentryDbxref.objects.create(bioentry=self.protein, dbxref=old, rank=0)
        self.run_import([row(), row()])
        self.assertEqual(BioentryDbxref.objects.count(), 3)
        self.run_import([row()], compressed=True)
        self.assertEqual(BioentryDbxref.objects.count(), 3)
        self.assertTrue(BioentryDbxref.objects.filter(dbxref=old).exists())

    def test_late_sequence_mismatch_does_not_partially_import_earlier_rows(self):
        with self.assertRaises(CommandError):
            self.run_import([row(), row(checksum="0" * 32)])
        self.assertEqual(Dbxref.objects.count(), 0)
        self.assertEqual(BioentryDbxref.objects.count(), 0)


class GenBankECImportTests(TestCase):
    setUp = InterproGoImportTests.setUp

    def run_import(self, sequence="MAU", apply=True, extra=None):
        record = SeqRecord(Seq("ATG"), id="TEST", annotations={"molecule_type": "DNA"})
        record.features = [
            SeqFeature(
                FeatureLocation(0, 3),
                type="CDS",
                qualifiers={
                    "locus_tag": ["LOC1"],
                    "translation": [sequence],
                    "EC_number": ["2.7.1.-", "2.7.1.-", "2.7.7.7"],
                },
            )
        ]
        if extra:
            record.features.append(extra)
        from Bio import SeqIO

        with TemporaryDirectory() as temp:
            path = Path(temp) / "genome.gbk"
            SeqIO.write([record], path, "genbank")
            output = StringIO()
            GenBankECCommand(stdout=output).handle(
                genome_name=self.genome, genbank=str(path), apply=apply
            )
            return output.getvalue()

    def test_preview_does_not_write(self):
        self.assertIn("1/1 proteins", self.run_import(apply=False))
        self.assertEqual(Dbxref.objects.count(), 0)

    def test_partial_ec_and_existing_annotations_are_preserved_on_repeat(self):
        old = Dbxref.objects.create(dbname="ec", accession="1.1.1.1", version=0)
        BioentryDbxref.objects.create(bioentry=self.protein, dbxref=old, rank=0)
        self.run_import()
        self.run_import()
        self.assertEqual(BioentryDbxref.objects.count(), 3)
        self.assertTrue(BioentryDbxref.objects.filter(dbxref=old).exists())
        self.assertTrue(Dbxref.objects.filter(dbname=Ontology.EC, accession="2.7.1.-").exists())

    def test_mismatched_sequence_or_late_invalid_ec_rolls_back_all(self):
        with self.assertRaises(CommandError):
            self.run_import(sequence="MAX")
        extra = SeqFeature(
            FeatureLocation(0, 3),
            type="CDS",
            qualifiers={
                "locus_tag": ["LOC1"],
                "translation": ["MAU"],
                "EC_number": ["bad"],
            },
        )
        with self.assertRaises(CommandError):
            self.run_import(extra=extra)
        self.assertEqual(BioentryDbxref.objects.count(), 0)
        self.assertEqual(Dbxref.objects.count(), 0)
