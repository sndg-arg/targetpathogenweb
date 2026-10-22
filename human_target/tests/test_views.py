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

    def test_list_is_the_shared_protein_table_with_structure_and_ligand_columns(self):
        self._make_human_proteins(2)

        response = self.client.get(reverse("human_target:human_protein_list"))

        self.assertContains(response, 'class="table tp-table tp-table--compact protein-table"')
        self.assertContains(response, reverse("human_target:human_protein", args=["P00000"]))
        self.assertEqual([row["ligands"]["total"] for row in response.context["rows"]], [0, 0])
        self.assertFalse(response.context["rows"][0]["structure"]["has_structure"])
