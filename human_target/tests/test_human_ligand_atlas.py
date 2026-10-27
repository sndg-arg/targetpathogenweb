from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse

from bioseq.models.Biodatabase import Biodatabase
from bioseq.models.Bioentry import Bioentry

from human_target.models.HumanProtein import HumanProtein
from human_target.services.human_ligand_atlas import (
    build_ligand_atlas_context,
    human_list_headline,
)
from human_target.services.human_targets import HUMAN_BIODATABASE_NAME
from tpweb.models.Binders import Binders


# Never the deployment's Redis: tests run inside the live web container.
@override_settings(CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}})
class LigandAtlasTests(TestCase):
    def setUp(self):
        cache.clear()
        self.biodatabase, _ = Biodatabase.objects.get_or_create(name=HUMAN_BIODATABASE_NAME)

    def _protein(self, accession, reviewed=True, experimental=0, ligands=0):
        bioentry = Bioentry.objects.create(
            biodatabase=self.biodatabase, name=accession, accession=accession, identifier=accession
        )
        HumanProtein.objects.create(
            bioentry=bioentry,
            uniprot_accession=accession,
            is_reviewed=reviewed,
            experimental_structure_count=experimental,
            ligand_count=ligands,
        )
        return bioentry

    def _binder(self, bioentry, ccd, source, direct=False, search="sequence", score=None):
        Binders.objects.create(
            ccd_id=ccd,
            locustag=bioentry,
            smiles="C",
            source=source,
            is_direct=direct,
            score=score,
            notes=f"LigQ {search}",
        )

    def test_categories_ladder_and_structure_split(self):
        a = self._protein("P00001", experimental=2)
        b = self._protein("P00002")
        c = self._protein("P00003")
        self._protein("P00004", experimental=1)
        unreviewed = self._protein("A0A000", reviewed=False)

        self._binder(a, "L1", Binders.SOURCE_PDB, direct=True)
        self._binder(a, "L2", Binders.SOURCE_CHEMBL, direct=True, score=7.5)
        self._binder(b, "L3", Binders.SOURCE_CHEMBL, search="domain", score=5.2)
        self._binder(c, "L4", Binders.SOURCE_PROPOSED, search="domain", score=0.8)
        self._binder(unreviewed, "L5", Binders.SOURCE_PDB, direct=True)

        atlas = build_ligand_atlas_context()

        self.assertEqual(atlas["total_proteins"], 4)
        self.assertEqual(atlas["proteins_with_ligands"], 3)
        self.assertEqual(atlas["proteins_direct"], 1)
        self.assertEqual(atlas["proteins_with_known"], 2)
        self.assertEqual(atlas["total_ligand_records"], 4)
        categories = {row["key"]: (row["count"], row["records"]) for row in atlas["categories"]}
        self.assertEqual(categories["direct_pdb"], (1, 1))
        self.assertEqual(categories["direct_chembl"], (1, 1))
        self.assertEqual(categories["domain_chembl"], (1, 1))
        self.assertEqual(categories["homolog_chembl"], (0, 0))
        self.assertEqual(categories["zinc"], (1, 1))
        self.assertEqual([row["count"] for row in atlas["ladder"]], [1, 0, 0, 1, 1, 1])
        self.assertEqual(sum(row["count"] for row in atlas["potency"]), 2)
        self.assertEqual([row["count"] for row in atlas["structure_matrix"]], [1, 1, 1, 1])
        self.assertEqual(atlas["richness"][1]["count"], 1)  # P00001: 2 known ligands

    def test_result_is_cached_until_refreshed(self):
        a = self._protein("P00001")
        self.assertEqual(build_ligand_atlas_context()["proteins_with_ligands"], 0)
        self._binder(a, "L1", Binders.SOURCE_PDB, direct=True)
        self.assertEqual(build_ligand_atlas_context()["proteins_with_ligands"], 0)
        self.assertEqual(build_ligand_atlas_context(refresh=True)["proteins_with_ligands"], 1)

    def test_list_headline_reads_summary_fields(self):
        self._protein("P00001", ligands=3)
        self._protein("A0A000", reviewed=False)
        self.assertEqual(
            human_list_headline(),
            {"total_proteins": 2, "proteins_with_ligands": 1, "total_ligand_records": 3},
        )

    def test_view_renders_for_permitted_user(self):
        user = get_user_model().objects.create_user(username="atlas-user", password="x")
        user.user_permissions.add(
            Permission.objects.get(
                content_type__app_label="tpweb", codename="can_view_human_targets"
            )
        )
        self.client.force_login(user)
        self._protein("P00001")
        response = self.client.get(reverse("human_target:human_ligand_atlas"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Strongest evidence")


class RetrosynthesisBenchmarkTests(TestCase):
    def test_best_models_skip_partial_runs_and_page_renders(self):
        from human_target.services.retrosynthesis_benchmark import build_benchmark_context

        context = build_benchmark_context()
        self.assertEqual(context["best_top1"]["name"], "Graph2SMILES")
        self.assertEqual(context["best_top10"]["top10"], 86.9)

        user = get_user_model().objects.create_user(username="bench-user", password="x")
        user.user_permissions.add(
            Permission.objects.get(
                content_type__app_label="tpweb", codename="can_view_human_targets"
            )
        )
        self.client.force_login(user)
        response = self.client.get(reverse("human_target:retrosynthesis_benchmark"))
        self.assertContains(response, "Graph2SMILES")
