from io import StringIO

from django.core.management import call_command
from django.test import TestCase

from bioseq.models.Biodatabase import Biodatabase
from bioseq.models.Bioentry import Bioentry
from bioseq.models.BioentryDbxref import BioentryDbxref
from bioseq.models.Dbxref import Dbxref
from tpweb.models import IdenticalSequenceGroup, IdenticalSequenceMember
from tpweb.models.Binders import Binders
from tpweb.services.binder_directness import protein_uniprot_map


class BinderDirectnessTests(TestCase):
    def setUp(self):
        self.group = IdenticalSequenceGroup.objects.create(source_note="test")
        self.kp13 = self.protein("public__KpKP13", "KP13_1", "KP13")
        self.va569 = self.protein("public__VA569", "MO417_1", "ST11_VA569")
        uniprot = Dbxref.objects.create(dbname="UnipTr", accession="A0A0H3H0G8", version=0)
        BioentryDbxref.objects.create(bioentry=self.kp13, dbxref=uniprot, rank=0)

    def protein(self, genome, accession, strain):
        database, _ = Biodatabase.objects.get_or_create(name=genome + Biodatabase.PROT_POSTFIX)
        protein = Bioentry.objects.create(
            biodatabase=database, accession=accession, name=accession, identifier=accession
        )
        IdenticalSequenceMember.objects.create(
            group=self.group, strain_label=strain, locus_tag=accession, bioentry=protein
        )
        return protein

    def test_identical_copy_contributes_its_uniprot_entry(self):
        mapping = protein_uniprot_map(["MO417_1"])
        self.assertEqual(mapping["MO417_1"], frozenset({"A0A0H3H0G8"}))

    def test_command_marks_same_protein_records_direct_and_leaves_homologs(self):
        same = Binders.objects.create(
            ccd_id="ACP",
            uniprot="A0A0H3H0G8",
            locustag=self.va569,
            smiles="C",
            source=Binders.SOURCE_PDB,
            is_direct=False,
        )
        other = Binders.objects.create(
            ccd_id="ATP",
            uniprot="P00001",
            locustag=self.va569,
            smiles="C",
            source=Binders.SOURCE_CHEMBL,
            is_direct=False,
        )
        call_command("recompute_binder_directness", "public__VA569", stdout=StringIO())
        same.refresh_from_db()
        other.refresh_from_db()
        self.assertTrue(same.is_direct)
        self.assertFalse(other.is_direct)

    def test_dry_run_writes_nothing(self):
        record = Binders.objects.create(
            ccd_id="ACP",
            uniprot="A0A0H3H0G8",
            locustag=self.va569,
            smiles="C",
            source=Binders.SOURCE_PDB,
            is_direct=False,
        )
        call_command(
            "recompute_binder_directness", "public__VA569", dry_run=True, stdout=StringIO()
        )
        record.refresh_from_db()
        self.assertFalse(record.is_direct)
