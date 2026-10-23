from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import TestCase
from django.urls import reverse

from bioseq.models.Biodatabase import Biodatabase
from bioseq.models.Bioentry import Bioentry

from human_target.models.HumanProtein import HumanProtein
from human_target.services.human_targets import HUMAN_BIODATABASE_NAME

User = get_user_model()


class HumanTargetsPermissionGateTests(TestCase):
    """Access to the whole Human Targets section is gated by
    tpweb.can_view_human_targets (granted by default on approval, see
    tpweb.services.user_approval, revocable per user from the /users
    "Edit" modal) -- covers the same admin-controlled-per-user visibility
    as tpweb.can_view_restricted_genomes, just for this sister app."""

    def setUp(self):
        self.user = User.objects.create_user(
            username="human-targets-user", password="x", is_active=True
        )
        self.client.force_login(self.user)

    def test_list_view_forbidden_without_permission(self):
        response = self.client.get(reverse("human_target:human_protein_list"))
        self.assertEqual(response.status_code, 403)

    def test_detail_view_forbidden_without_permission(self):
        response = self.client.get(
            reverse("human_target:human_protein", kwargs={"accession": "P10721"})
        )
        self.assertEqual(response.status_code, 403)

    def test_list_view_allowed_with_permission(self):
        self.user.user_permissions.add(
            Permission.objects.get(
                content_type__app_label="tpweb", codename="can_view_human_targets"
            )
        )

        response = self.client.get(reverse("human_target:human_protein_list"))

        self.assertEqual(response.status_code, 200)


class HumanProteinListViewPaginationTests(TestCase):
    """DB-side search + real pagination (PAGE_SIZE=40) -- needs to scale to
    the full proteome, not just the 10-protein pilot."""

    def setUp(self):
        user = User.objects.create_user(username="human-targets-user", password="x")
        user.user_permissions.add(
            Permission.objects.get(
                content_type__app_label="tpweb", codename="can_view_human_targets"
            )
        )
        self.client.force_login(user)

    def _make_human_proteins(self, n):
        biodatabase, _ = Biodatabase.objects.get_or_create(name=HUMAN_BIODATABASE_NAME)
        for i in range(n):
            accession = f"P{i:05d}"
            bioentry = Bioentry.objects.create(
                biodatabase=biodatabase, name=accession, accession=accession, identifier=accession
            )
            HumanProtein.objects.create(
                bioentry=bioentry, uniprot_accession=accession, gene_symbol=f"GENE{i}"
            )

    def test_first_page_shows_only_page_size_rows(self):
        self._make_human_proteins(55)

        response = self.client.get(reverse("human_target:human_protein_list"))

        self.assertEqual(len(response.context["proteins"]), 40)
        self.assertEqual(response.context["total_count"], 55)

    def test_second_page_shows_the_remainder(self):
        self._make_human_proteins(55)

        response = self.client.get(reverse("human_target:human_protein_list"), {"page": 2})

        self.assertEqual(len(response.context["proteins"]), 15)

    def test_search_filters_before_pagination(self):
        self._make_human_proteins(55)

        response = self.client.get(reverse("human_target:human_protein_list"), {"q": "P00001"})

        self.assertEqual(response.context["total_count"], 1)
        self.assertEqual(len(response.context["proteins"]), 1)

    def test_out_of_range_page_falls_back_to_last_page(self):
        self._make_human_proteins(55)

        response = self.client.get(reverse("human_target:human_protein_list"), {"page": 999})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["proteins"].number, 2)

    def test_list_is_the_shared_protein_table_with_evidence_columns(self):
        self._make_human_proteins(2)

        response = self.client.get(reverse("human_target:human_protein_list"))

        self.assertContains(response, 'class="table tp-table tp-table--compact protein-table"')
        self.assertContains(response, reverse("human_target:human_protein", args=["P00000"]))
        self.assertContains(response, "DrugBank")

    def test_filters_and_sorting_use_the_stored_summary(self):
        self._make_human_proteins(3)
        HumanProtein.objects.filter(uniprot_accession="P00001").update(
            drugbank_count=4, tissue_specificity=0.9
        )
        HumanProtein.objects.filter(uniprot_accession="P00002").update(drugbank_count=1)

        response = self.client.get(reverse("human_target:human_protein_list"), {"drugs": "1"})
        self.assertEqual(response.context["total_count"], 2)
        self.assertEqual(len(response.context["active_pills"]), 1)

        response = self.client.get(
            reverse("human_target:human_protein_list"), {"sort": "drugs", "dir": "desc"}
        )
        self.assertEqual(
            [hp.uniprot_accession for hp in response.context["proteins"]][:2],
            ["P00001", "P00002"],
        )

        response = self.client.get(
            reverse("human_target:human_protein_list"), {"tissue": "restricted"}
        )
        self.assertEqual([hp.uniprot_accession for hp in response.context["proteins"]], ["P00001"])

    def test_summary_refresh_counts_drugs_and_diseases(self):
        from human_target.services.human_target_summary import refresh_summaries

        self._make_human_proteins(1)
        HumanProtein.objects.filter(uniprot_accession="P00000").update(
            cross_references_raw=[
                {"database": "DrugBank", "id": "DB1"},
                {"database": "DrugBank", "id": "DB2"},
                {"database": "PDB", "id": "1ABC"},
            ],
            disease_comments=[{"name": "X"}],
            subcellular_locations=["Cell membrane"],
            expression_json=[
                {"tissue": "testis", "score": 90.0},
                {"tissue": "liver", "score": 10.0},
            ],
        )
        self.assertEqual(refresh_summaries(HumanProtein.objects.all()), 1)
        protein = HumanProtein.objects.get(uniprot_accession="P00000")
        self.assertEqual((protein.drugbank_count, protein.disease_count), (2, 1))
        self.assertTrue(protein.surface_accessible)
        self.assertEqual(protein.peak_tissue, "testis")
        self.assertAlmostEqual(protein.tissue_specificity, 0.975, places=3)
        self.assertIsNotNone(protein.summary_updated_at)
