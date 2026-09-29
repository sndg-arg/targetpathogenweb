from django.test import TestCase

from bioseq.models.Biodatabase import Biodatabase
from bioseq.models.Bioentry import Bioentry

from human_target.services.human_dashboard_summary import build_human_dashboard_context
from human_target.services.human_targets import HUMAN_BIODATABASE_NAME
from tpweb.models.Binders import Binders


class BuildHumanDashboardContextTests(TestCase):
    def _make_bioentry(self, accession):
        biodatabase, _ = Biodatabase.objects.get_or_create(name=HUMAN_BIODATABASE_NAME)
        return Bioentry.objects.create(
            biodatabase=biodatabase, name=accession, accession=accession, identifier=accession
        )

    def _make_binder(self, bioentry, source, is_direct, score=None):
        return Binders.objects.create(
            ccd_id="LIG1",
            locustag=bioentry,
            smiles="C",
            source=source,
            is_direct=is_direct,
            score=score,
        )

    def test_counts_are_zero_with_no_proteins_or_binders(self):
        context = build_human_dashboard_context()
        self.assertEqual(context["total_proteins"], 0)
        self.assertEqual(context["total_ligand_records"], 0)
        self.assertEqual(context["proteins_with_ligands"], 0)

    def test_aggregates_by_source_evidence_and_richness(self):
        protein_a = self._make_bioentry("P10721")
        protein_b = self._make_bioentry("O00116")

        self._make_binder(protein_a, Binders.SOURCE_PDB, is_direct=True)
        self._make_binder(protein_a, Binders.SOURCE_CHEMBL, is_direct=True, score=7.5)
        self._make_binder(protein_a, Binders.SOURCE_CHEMBL, is_direct=False, score=3.0)
        self._make_binder(protein_b, Binders.SOURCE_PROPOSED, is_direct=False)

        context = build_human_dashboard_context()

        self.assertEqual(context["total_proteins"], 2)
        self.assertEqual(context["total_ligand_records"], 4)
        self.assertEqual(context["proteins_with_ligands"], 2)
        self.assertEqual(context["proteins_without_ligands"], 0)
        self.assertEqual(context["by_source"], {"pdb": 1, "chembl": 2, "zinc": 1})
        self.assertEqual(context["by_evidence"], {"direct": 2, "homolog": 2})

        bin_68 = next(b for b in context["pchembl_bins"] if b["label"] == "6 – 8")
        self.assertEqual(bin_68["count"], 1)
        bin_1 = next(b for b in context["richness_bins"] if b["label"] == "1")
        self.assertEqual(bin_1["count"], 1)
        bin_25 = next(b for b in context["richness_bins"] if b["label"] == "2–5")
        self.assertEqual(bin_25["count"], 1)
