"""Cheap breadth-over-depth coverage: does the view render without a 500?

These are not behavioral tests -- they exist to catch the obvious stuff
(broken import, missing template, unhandled exception) across views that
otherwise have zero test coverage. Deeper behavioral tests belong next to
the service functions each view delegates to.
"""

from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db.utils import InterfaceError
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

import tpweb.services.pipeline_status as pipeline_status_service
from bioseq.models.Biodatabase import Biodatabase
from bioseq.models.Bioentry import Bioentry
from bioseq.models.Biosequence import Biosequence
from tpweb.models.Binders import Binders
from tpweb.services.workspace import PUBLIC_WORKSPACE_USERNAME


class HealthViewTests(SimpleTestCase):
    def test_live_health_endpoint(self):
        response = self.client.get("/health/live")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["service"], "tpweb")

    @patch("tpweb.views.HealthView.get_pipeline_status")
    @patch("tpweb.views.HealthView._database_ready")
    def test_ready_health_endpoint_ok(self, database_ready, get_pipeline_status):
        database_ready.return_value = True
        get_pipeline_status.return_value = {"available": True, "running": True}

        response = self.client.get("/health/ready")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "ready")
        self.assertEqual(payload["checks"]["database"], "ok")
        self.assertTrue(payload["pipeline_running"])

    @patch("tpweb.views.HealthView.get_pipeline_status")
    @patch("tpweb.views.HealthView._database_ready")
    def test_ready_health_endpoint_degraded(self, database_ready, get_pipeline_status):
        database_ready.return_value = False
        get_pipeline_status.return_value = {"available": False, "running": False}

        response = self.client.get("/health/ready")
        self.assertEqual(response.status_code, 503)
        payload = response.json()
        self.assertEqual(payload["status"], "degraded")
        self.assertEqual(payload["checks"]["database"], "error")
        self.assertFalse(payload["pipeline_running"])

    @patch("tpweb.views.HealthView.get_pipeline_status")
    def test_pipeline_health_endpoint(self, get_pipeline_status):
        get_pipeline_status.return_value = {"available": True, "running": True, "stage_current": 4}

        response = self.client.get("/health/pipeline")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["pipeline"]["stage_current"], 4)

    def test_request_timing_header_is_exposed(self):
        response = self.client.get("/health/live")
        self.assertIn("X-Request-Duration-Ms", response.headers)

    @patch("tpweb.services.pipeline_status.latest_active_pipeline_run")
    def test_get_pipeline_status_falls_back_to_idle_on_database_error(
        self, latest_active_pipeline_run
    ):
        latest_active_pipeline_run.side_effect = InterfaceError("connection already closed")

        payload = pipeline_status_service.get_pipeline_status()

        self.assertFalse(payload["available"])
        self.assertFalse(payload["running"])
        self.assertEqual(payload["state_class"], "idle")


class RouteSmokeTests(SimpleTestCase):
    @patch("tpweb.views.IndexView.TPPost.objects.first")
    @patch("tpweb.views.IndexView.get_pipeline_status")
    @patch("tpweb.views.IndexView.summarize_genomes")
    @patch("tpweb.views.IndexView.build_genomes_dto")
    @patch("tpweb.views.IndexView.build_genomes_queryset")
    def test_index_route_renders(
        self,
        build_genomes_queryset,
        build_genomes_dto,
        summarize_genomes,
        get_pipeline_status,
        post_first,
    ):
        build_genomes_queryset.return_value = []
        build_genomes_dto.return_value = []
        summarize_genomes.return_value = {
            "total_genomes": 0,
            "total_proteins": 0,
            "total_experimental": 0,
            "total_pdb_xrefs": 0,
            "total_ec_annotated": 0,
        }
        get_pipeline_status.return_value = {"available": False, "running": False}
        post_first.return_value = None

        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)

    @patch("tpweb.views.GenomesView.get_pipeline_status")
    @patch("tpweb.views.GenomesView.summarize_genomes")
    @patch("tpweb.views.GenomesView.build_genomes_dto")
    @patch("tpweb.views.GenomesView.build_genomes_queryset")
    def test_genomes_route_renders(
        self, build_genomes_queryset, build_genomes_dto, summarize_genomes, get_pipeline_status
    ):
        build_genomes_queryset.return_value = []
        build_genomes_dto.return_value = []
        summarize_genomes.return_value = {
            "total_genomes": 0,
            "total_proteins": 0,
            "total_experimental": 0,
            "total_pdb_xrefs": 0,
            "total_ec_annotated": 0,
        }
        get_pipeline_status.return_value = {"available": False, "running": False}

        response = self.client.get("/genomes")
        self.assertEqual(response.status_code, 200)


class AssemblyViewTests(TestCase):
    def test_assembly_route_renders_for_incomplete_workspace_without_bioentries(self):
        Biodatabase.objects.create(
            name=f"{PUBLIC_WORKSPACE_USERNAME}__NZ_AP023069.1",
            description="Incomplete genome workspace",
        )

        response = self.client.get("/genome/NZ_AP023069.1")

        self.assertEqual(response.status_code, 200)


class StaticContentViewTests(SimpleTestCase):
    """Zero-fixture pages: no DB objects needed to render them."""

    def test_about_us_renders(self):
        response = self.client.get(reverse("tpwebapp:about_us"))
        self.assertEqual(response.status_code, 200)

    def test_data_sources_renders(self):
        response = self.client.get(reverse("tpwebapp:data_sources"))
        self.assertEqual(response.status_code, 200)

    def test_robots_txt_renders(self):
        response = self.client.get(reverse("tpwebapp:robots_txt"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "text/plain")
        self.assertIn("User-agent: GPTBot", response.content.decode())

    def test_molecule_renders(self):
        response = self.client.get(reverse("tpwebapp:molecules"))
        self.assertEqual(response.status_code, 200)


class HumanProteinListViewTests(TestCase):
    def test_renders_with_empty_dataset(self):
        response = self.client.get(reverse("tpwebapp:human_protein_list"))
        self.assertEqual(response.status_code, 200)


class DownloadViewTests(SimpleTestCase):
    def test_download_without_query_params_is_bad_request(self):
        response = self.client.get(reverse("tpwebapp:download"))
        self.assertEqual(response.status_code, 400)

    def test_download_with_invalid_format_is_bad_request(self):
        response = self.client.get(
            reverse("tpwebapp:download"), {"accession": "NZ_AP023069.1", "format": "not-a-format"}
        )
        self.assertEqual(response.status_code, 400)


class FormViewAuthTests(TestCase):
    def test_blast_form_requires_login(self):
        response = self.client.get(reverse("tpwebapp:form"))
        self.assertEqual(response.status_code, 302)

    def test_blast_form_renders_for_authenticated_user_with_no_genomes(self):
        user = get_user_model().objects.create_user(username="blast-user", password="test-pass")
        self.client.force_login(user)

        response = self.client.get(reverse("tpwebapp:form"))

        self.assertEqual(response.status_code, 200)


class AnnotationExplorerViewTests(TestCase):
    def test_renders_for_genome_with_no_annotations(self):
        Biodatabase.objects.create(
            name=f"{PUBLIC_WORKSPACE_USERNAME}__NZ_AP023069.1",
            description="Genome workspace",
        )

        response = self.client.get(
            reverse(
                "tpwebapp:annotation_explorer",
                kwargs={"genome": "NZ_AP023069.1", "annotation_kind": "ec"},
            )
        )

        self.assertEqual(response.status_code, 200)


class BinderDetailViewTests(TestCase):
    def test_renders_for_pdb_binder_with_no_smiles(self):
        proteome = Biodatabase.objects.create(name="TEST_protein")
        protein = Bioentry.objects.create(
            biodatabase=proteome,
            name="protA",
            accession="LOCUS_A",
            identifier="LOCUS_A",
        )
        binder = Binders.objects.create(
            ccd_id="ATP",
            pdb_id="1ABC",
            uniprot="P12345",
            locustag=protein,
            smiles="",
        )

        response = self.client.get(
            reverse("tpwebapp:binder_detail", kwargs={"binder_id": binder.id})
        )

        self.assertEqual(response.status_code, 200)


class HtmxFragmentViewTests(TestCase):
    def test_load_options_without_param_renders_empty_fragment(self):
        response = self.client.get(reverse("tpwebapp:load_options"))
        self.assertEqual(response.status_code, 200)

    def test_validate_expression_without_query_prompts_for_input(self):
        response = self.client.get(reverse("tpwebapp:validate_expression"))
        self.assertEqual(response.status_code, 200)
        self.assertIn("Type an expression above", response.content.decode())


class SitemapViewTests(SimpleTestCase):
    def test_sitemap_lists_static_content_pages(self):
        response = self.client.get(reverse("tpwebapp:sitemap_xml"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/xml")
        body = response.content.decode()
        self.assertIn("<urlset", body)
        self.assertIn(reverse("tpwebapp:about_us"), body)
        self.assertIn(reverse("tpwebapp:genomes_list"), body)


class DeleteFormulaViewTests(TestCase):
    def test_get_is_not_allowed(self):
        response = self.client.get(
            reverse("tpwebapp:delete_formula", kwargs={"genome": "NZ_AP023069.1", "formula_pk": 1})
        )
        self.assertEqual(response.status_code, 405)

    def test_post_for_unknown_genome_is_not_found(self):
        response = self.client.post(
            reverse("tpwebapp:delete_formula", kwargs={"genome": "does-not-exist", "formula_pk": 1})
        )
        self.assertEqual(response.status_code, 404)


class LoginRequiredRedirectTests(SimpleTestCase):
    """These views are gated by LoginRequiredMixin -- an anonymous GET must
    redirect to login rather than reach any DB/fixture-dependent code."""

    def test_blast_result_view_requires_login(self):
        response = self.client.get(
            reverse("tpwebapp:blast_res", kwargs={"result_id": "not-a-uuid"})
        )
        self.assertEqual(response.status_code, 302)

    def test_protein_blast_view_requires_login(self):
        response = self.client.get(
            reverse("tpwebapp:protein_blast", kwargs={"genome": "NZ_AP023069.1"})
        )
        self.assertEqual(response.status_code, 302)

    def test_genome_upload_view_requires_login(self):
        response = self.client.get(reverse("tpwebapp:genome_upload"))
        self.assertEqual(response.status_code, 302)


class StructureRawViewTests(TestCase):
    def test_unknown_structure_id_is_not_found(self):
        response = self.client.get(reverse("tpwebapp:structure_raw", kwargs={"struct_id": 999999}))
        self.assertEqual(response.status_code, 404)


class StructureExportViewTests(TestCase):
    def test_unknown_structure_id_is_not_found(self):
        response = self.client.get(
            reverse("tpwebapp:structure_export", kwargs={"struct_id": 999999})
        )
        self.assertEqual(response.status_code, 404)


class HumanProteinViewTests(TestCase):
    def test_unknown_accession_is_not_found(self):
        response = self.client.get(
            reverse("tpwebapp:human_protein", kwargs={"accession": "DOES-NOT-EXIST"})
        )
        self.assertEqual(response.status_code, 404)


class DataFileUploadViewTests(TestCase):
    def test_post_requires_staff(self):
        response = self.client.post(reverse("tpwebapp:data_file_upload"))
        self.assertEqual(response.status_code, 403)


class CustomParamViewTests(SimpleTestCase):
    def test_get_requires_login(self):
        response = self.client.get(
            reverse("tpwebapp:customparam", kwargs={"genome": "NZ_AP023069.1"})
        )
        self.assertEqual(response.status_code, 302)


class FormulaFormViewTests(TestCase):
    def test_get_for_unknown_genome_is_not_found(self):
        response = self.client.get(
            reverse("tpwebapp:formula_form", kwargs={"genome": "does-not-exist"})
        )
        self.assertEqual(response.status_code, 404)


class AgentChatViewTests(TestCase):
    def test_get_returns_empty_history_for_new_session(self):
        response = self.client.get(reverse("tpwebapp:agent_chat"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"history": []})


class MetabolismPathwayViewTests(TestCase):
    def test_get_for_unknown_genome_is_not_found(self):
        response = self.client.get(
            reverse("tpwebapp:genome_metabolism", kwargs={"genome": "does-not-exist"})
        )
        self.assertEqual(response.status_code, 404)


class MetabolismNetworkViewTests(TestCase):
    def test_get_for_unknown_protein_is_not_found(self):
        response = self.client.get(
            reverse("tpwebapp:protein_metabolic_network", kwargs={"protein_id": 999999})
        )
        self.assertEqual(response.status_code, 404)


class ProteinViewTests(TestCase):
    def test_renders_for_protein_with_no_structures_or_annotations(self):
        # ProteinView checks biodatabase.name against the real
        # bioseq.models.Biodatabase.PROT_POSTFIX ("_prots") -- not "_protein"
        # like a couple of older fixtures in this test suite assume. Those
        # older tests happen to pass anyway because the views they exercise
        # never check the suffix; ProteinView does, so getting it wrong here
        # would 404 instead of rendering.
        Biodatabase.objects.create(name="TEST", description="Genome workspace")
        proteome = Biodatabase.objects.create(name="TEST_prots")
        protein = Bioentry.objects.create(
            biodatabase=proteome,
            name="protA",
            accession="LOCUS_A",
            identifier="LOCUS_A",
        )
        Biosequence.objects.create(bioentry=protein, length=10, seq="MKTAYIAKQR")

        response = self.client.get(
            reverse("tpwebapp:protein", kwargs={"protein_id": protein.bioentry_id})
        )

        self.assertEqual(response.status_code, 200)


class GenomeUploadViewTests(TestCase):
    def test_get_renders_for_authenticated_user_with_no_uploads(self):
        user = get_user_model().objects.create_user(username="upload-user", password="test-pass")
        self.client.force_login(user)

        response = self.client.get(reverse("tpwebapp:genome_upload"))

        self.assertEqual(response.status_code, 200)


class ProteinListViewTests(TestCase):
    def test_renders_for_genome_with_no_proteins(self):
        Biodatabase.objects.create(name="TEST", description="Genome workspace")
        Biodatabase.objects.create(name="TEST_prots")

        response = self.client.get(reverse("tpwebapp:protein_list", kwargs={"genome": "TEST"}))

        self.assertEqual(response.status_code, 200)
