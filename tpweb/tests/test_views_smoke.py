"""Cheap breadth-over-depth coverage: does the view render without a 500?

These are not behavioral tests -- they exist to catch the obvious stuff
(broken import, missing template, unhandled exception) across views that
otherwise have zero test coverage. Deeper behavioral tests belong next to
the service functions each view delegates to.
"""

import json
import os
import tempfile
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db.utils import InterfaceError
from django.test import TestCase
from django.urls import reverse

import tpweb.services.pipeline_status as pipeline_status_service
from bioseq.models.Biodatabase import Biodatabase
from bioseq.models.Bioentry import Bioentry
from bioseq.models.Biosequence import Biosequence
from tpweb.models.Binders import Binders
from tpweb.models.BioentryStructure import BioentryStructure
from tpweb.models.pdb import PDB
from tpweb.services.workspace import PUBLIC_WORKSPACE_USERNAME
from tpweb.views.AgentChatView import AgentChatView
from tpweb.views.ProteinListView import ProteinAdvancedFiltersView


class LoggedInTestCase(TestCase):
    """Base for smoke tests exercising routes the login-required middleware
    now gates. Anonymous requests get redirected before reaching the view, so
    every test here needs a real, logged-in user first.

    smoke_user is granted every tpweb custom permission -- these tests are
    about rendering/routing, not access control, so it stands in for a fully
    approved user. Permission *enforcement* is covered by its own dedicated
    tests elsewhere in this file (e.g. GenomeUploadViewTests, DeleteFormulaViewTests)."""

    def setUp(self):
        super().setUp()
        from django.contrib.auth.models import Permission

        self.smoke_user = get_user_model().objects.create_user(
            username="smoke-test-user", password="test-pass", is_staff=True
        )
        self.smoke_user.user_permissions.add(
            *Permission.objects.filter(content_type__app_label="tpweb", codename__startswith="can_")
        )
        self.client.force_login(self.smoke_user)


class HealthViewTests(TestCase):
    """A real TestCase, not SimpleTestCase -- ATOMIC_REQUESTS=True (settings.py)
    wraps every view in a DB transaction, so even /health/live (which itself
    touches no DB) needs a real connection to complete the request/response
    cycle."""

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


class RouteSmokeTests(LoggedInTestCase):
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


class AssemblyViewTests(LoggedInTestCase):
    def test_assembly_route_renders_for_incomplete_workspace_without_bioentries(self):
        Biodatabase.objects.create(
            name=f"{PUBLIC_WORKSPACE_USERNAME}__NZ_AP023069.1",
            description="Incomplete genome workspace",
        )

        response = self.client.get("/genome/NZ_AP023069.1")

        self.assertEqual(response.status_code, 200)


class StaticContentViewTests(LoggedInTestCase):
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
        self.assertIn("User-agent: *", response.content.decode())
        self.assertIn("Disallow: /", response.content.decode())

    def test_robots_txt_is_reachable_without_login(self):
        # The whole site sits behind LoginRequiredMiddleware -- robots.txt
        # is the one exception, so a crawler can actually read "stay out"
        # instead of getting redirected to the login page and never
        # learning the site is fully private.
        self.client.logout()

        response = self.client.get(reverse("tpwebapp:robots_txt"))

        self.assertEqual(response.status_code, 200)

    def test_molecule_renders(self):
        response = self.client.get(reverse("tpwebapp:molecules"))
        self.assertEqual(response.status_code, 200)


class HumanProteinListViewTests(LoggedInTestCase):
    def test_renders_with_empty_dataset(self):
        response = self.client.get(reverse("tpwebapp:human_protein_list"))
        self.assertEqual(response.status_code, 200)


class DownloadViewTests(LoggedInTestCase):
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

    def test_blast_post_without_permission_shows_error_instead_of_running(self):
        user = get_user_model().objects.create_user(username="blast-no-perm", password="test-pass")
        self.client.force_login(user)

        response = self.client.post(reverse("tpwebapp:form"), {"text_input": "ACGT"})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "You don&#x27;t have permission to run BLAST searches.")


class AnnotationExplorerViewTests(LoggedInTestCase):
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


class BinderDetailViewTests(LoggedInTestCase):
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


class HtmxFragmentViewTests(LoggedInTestCase):
    def test_load_options_without_param_renders_empty_fragment(self):
        response = self.client.get(reverse("tpwebapp:load_options"))
        self.assertEqual(response.status_code, 200)

    def test_validate_expression_without_query_prompts_for_input(self):
        response = self.client.get(reverse("tpwebapp:validate_expression"))
        self.assertEqual(response.status_code, 200)
        self.assertIn("Type an expression above", response.content.decode())

    def test_validate_expression_accepts_valid_numeric_expression(self):
        response = self.client.get(reverse("tpwebapp:validate_expression"), {"expression": "1 + 1"})
        self.assertEqual(response.status_code, 200)
        self.assertIn("Valid expression", response.content.decode())

    def test_validate_expression_rejects_division_by_zero(self):
        response = self.client.get(reverse("tpwebapp:validate_expression"), {"expression": "1 / 0"})
        self.assertEqual(response.status_code, 200)
        self.assertIn("formula-valid-badge--err", response.content.decode())


class SitemapViewTests(LoggedInTestCase):
    def test_sitemap_lists_static_content_pages(self):
        response = self.client.get(reverse("tpwebapp:sitemap_xml"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/xml")
        body = response.content.decode()
        self.assertIn("<urlset", body)
        self.assertIn(reverse("tpwebapp:about_us"), body)
        self.assertIn(reverse("tpwebapp:genomes_list"), body)


class DeleteFormulaViewTests(LoggedInTestCase):
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

    def test_post_without_permission_is_forbidden(self):
        user = get_user_model().objects.create_user(
            username="delete-formula-no-perm", password="test-pass"
        )
        self.client.force_login(user)

        response = self.client.post(
            reverse("tpwebapp:delete_formula", kwargs={"genome": "does-not-exist", "formula_pk": 1})
        )

        self.assertEqual(response.status_code, 403)


class LoginRequiredRedirectTests(TestCase):
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


class ProteinBlastViewTests(TestCase):
    def test_get_renders_for_authenticated_user_with_existing_genome(self):
        Biodatabase.objects.create(name="TEST")
        user = get_user_model().objects.create_user(
            username="blast-genome-user", password="test-pass"
        )
        self.client.force_login(user)

        response = self.client.get(reverse("tpwebapp:protein_blast", kwargs={"genome": "TEST"}))

        self.assertEqual(response.status_code, 200)

    def test_get_for_unknown_genome_is_not_found(self):
        user = get_user_model().objects.create_user(
            username="blast-missing-genome-user", password="test-pass"
        )
        self.client.force_login(user)

        response = self.client.get(
            reverse("tpwebapp:protein_blast", kwargs={"genome": "does-not-exist"})
        )

        self.assertEqual(response.status_code, 404)


class StructureRawViewTests(LoggedInTestCase):
    def test_unknown_structure_id_is_not_found(self):
        response = self.client.get(reverse("tpwebapp:structure_raw", kwargs={"struct_id": 999999}))
        self.assertEqual(response.status_code, 404)


class StructureExportViewTests(LoggedInTestCase):
    def test_unknown_structure_id_is_not_found(self):
        response = self.client.get(
            reverse("tpwebapp:structure_export", kwargs={"struct_id": 999999})
        )
        self.assertEqual(response.status_code, 404)


class HumanProteinViewTests(LoggedInTestCase):
    def test_unknown_accession_is_not_found(self):
        response = self.client.get(
            reverse("tpwebapp:human_protein", kwargs={"accession": "DOES-NOT-EXIST"})
        )
        self.assertEqual(response.status_code, 404)


class DataFileUploadViewTests(TestCase):
    def test_post_requires_superuser(self):
        user = get_user_model().objects.create_user(
            username="upload-non-owner", password="test-pass"
        )
        self.client.force_login(user)

        response = self.client.post(reverse("tpwebapp:data_file_upload"))

        self.assertEqual(response.status_code, 403)

    def test_post_requires_superuser_not_just_staff(self):
        # Approval grants is_staff, not is_superuser -- an approved
        # collaborator must not be able to write raw files into the shared
        # server directory this view feeds.
        user = get_user_model().objects.create_user(
            username="upload-staff-only", password="test-pass", is_staff=True
        )
        self.client.force_login(user)

        response = self.client.post(reverse("tpwebapp:data_file_upload"))

        self.assertEqual(response.status_code, 403)

    def test_post_without_file_is_bad_request_for_owner(self):
        user = get_user_model().objects.create_user(
            username="upload-owner-nofile", password="test-pass", is_superuser=True
        )
        self.client.force_login(user)

        response = self.client.post(reverse("tpwebapp:data_file_upload"))

        self.assertEqual(response.status_code, 400)

    def test_post_allowed_for_staff_with_explicit_permission(self):
        from django.contrib.auth.models import Permission

        user = get_user_model().objects.create_user(
            username="upload-granted", password="test-pass", is_staff=True
        )
        user.user_permissions.add(
            Permission.objects.get(content_type__app_label="tpweb", codename="can_curated_import")
        )
        self.client.force_login(user)

        response = self.client.post(reverse("tpwebapp:data_file_upload"))

        self.assertEqual(response.status_code, 400)

    def test_post_rejects_disallowed_extension(self):
        user = get_user_model().objects.create_user(
            username="upload-owner-badext", password="test-pass", is_superuser=True
        )
        self.client.force_login(user)
        upload = SimpleUploadedFile("model.exe", b"binary", content_type="application/octet-stream")

        response = self.client.post(reverse("tpwebapp:data_file_upload"), {"data_file": upload})

        self.assertEqual(response.status_code, 400)

    def test_post_saves_allowed_file_and_returns_its_path(self):
        user = get_user_model().objects.create_user(
            username="upload-owner-ok", password="test-pass", is_superuser=True
        )
        self.client.force_login(user)

        with tempfile.TemporaryDirectory() as tmp:
            upload = SimpleUploadedFile(
                "results.tsv", b"col1\tcol2\n1\t2\n", content_type="text/tab-separated-values"
            )
            with patch.dict(os.environ, {"TPW_UPLOADS_DIR": tmp}):
                response = self.client.post(
                    reverse("tpwebapp:data_file_upload"), {"data_file": upload}
                )

            self.assertEqual(response.status_code, 200)
            payload = response.json()
            self.assertEqual(payload["filename"], "results.tsv")
            self.assertEqual(payload["path"], os.path.join(tmp, "results.tsv"))
            self.assertTrue(os.path.exists(payload["path"]))


class CustomParamViewTests(TestCase):
    def test_get_requires_login(self):
        response = self.client.get(
            reverse("tpwebapp:customparam", kwargs={"genome": "NZ_AP023069.1"})
        )
        self.assertEqual(response.status_code, 302)


class CustomParamViewRenderTests(TestCase):
    def test_get_renders_form_for_authenticated_user_with_existing_genome(self):
        from django.contrib.auth.models import Permission

        Biodatabase.objects.create(name="TEST")
        user = get_user_model().objects.create_user(
            username="customparam-user", password="test-pass"
        )
        user.user_permissions.add(
            Permission.objects.get(
                content_type__app_label="tpweb", codename="can_manage_custom_params"
            )
        )
        self.client.force_login(user)

        response = self.client.get(reverse("tpwebapp:customparam", kwargs={"genome": "TEST"}))

        self.assertEqual(response.status_code, 200)

    def test_get_without_permission_is_forbidden(self):
        Biodatabase.objects.create(name="TEST")
        user = get_user_model().objects.create_user(
            username="customparam-no-perm", password="test-pass"
        )
        self.client.force_login(user)

        response = self.client.get(reverse("tpwebapp:customparam", kwargs={"genome": "TEST"}))

        self.assertEqual(response.status_code, 403)


class FormulaFormViewTests(LoggedInTestCase):
    def test_get_for_unknown_genome_is_not_found(self):
        response = self.client.get(
            reverse("tpwebapp:formula_form", kwargs={"genome": "does-not-exist"})
        )
        self.assertEqual(response.status_code, 404)

    def test_get_renders_form_for_existing_genome(self):
        Biodatabase.objects.create(name="TEST")

        response = self.client.get(reverse("tpwebapp:formula_form", kwargs={"genome": "TEST"}))

        self.assertEqual(response.status_code, 200)

    def test_get_without_permission_is_forbidden(self):
        Biodatabase.objects.create(name="TEST")
        user = get_user_model().objects.create_user(
            username="formula-form-no-perm", password="test-pass"
        )
        self.client.force_login(user)

        response = self.client.get(reverse("tpwebapp:formula_form", kwargs={"genome": "TEST"}))

        self.assertEqual(response.status_code, 403)


class AgentChatViewTests(LoggedInTestCase):
    def test_get_returns_empty_history_for_new_session(self):
        response = self.client.get(reverse("tpwebapp:agent_chat"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"history": [], "conversation_id": None, "title": None})

    def test_get_without_permission_is_forbidden(self):
        user = get_user_model().objects.create_user(
            username="agent-chat-no-perm", password="test-pass"
        )
        self.client.force_login(user)

        response = self.client.get(reverse("tpwebapp:agent_chat"))

        self.assertEqual(response.status_code, 403)

    def test_anonymous_user_is_denied_not_served(self):
        # raise_exception=True on PermissionRequiredMixin means even an
        # anonymous request gets a flat 403, not a login redirect.
        self.client.logout()

        response = self.client.get(reverse("tpwebapp:agent_chat"))

        self.assertEqual(response.status_code, 403)


class AgentChatSessionsViewTests(LoggedInTestCase):
    def test_lists_no_sessions_for_a_brand_new_browser_session(self):
        response = self.client.get(reverse("tpwebapp:agent_chat_sessions"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"sessions": []})

    def test_get_without_permission_is_forbidden(self):
        user = get_user_model().objects.create_user(
            username="agent-sessions-no-perm", password="test-pass"
        )
        self.client.force_login(user)

        response = self.client.get(reverse("tpwebapp:agent_chat_sessions"))

        self.assertEqual(response.status_code, 403)

    def test_never_lists_another_browser_session_s_conversations(self):
        from django.test import Client

        from tpweb.models.AgentChatSession import AgentChatSession

        # Same shared login from a second browser -- session isolation must
        # still hold even though both clients are the same authenticated user.
        first_client = Client()
        first_client.force_login(self.smoke_user)
        first_client.get(reverse("tpwebapp:agent_chat"))  # mints a session_key
        first_session_key = first_client.session.session_key
        AgentChatSession.objects.create(
            session_key=first_session_key, title="First visitor's chat", history_json=[]
        )

        second_client = Client()
        second_client.force_login(self.smoke_user)
        response = second_client.get(reverse("tpwebapp:agent_chat_sessions"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"sessions": []})


class AgentChatSessionDetailViewTests(LoggedInTestCase):
    def _create_conversation(self, client, title=""):
        from tpweb.models.AgentChatSession import AgentChatSession

        client.get(reverse("tpwebapp:agent_chat"))  # mints a session_key
        session_key = client.session.session_key
        return AgentChatSession.objects.create(
            session_key=session_key, title=title, history_json=[]
        )

    def test_patch_renames_and_returns_the_new_title(self):
        row = self._create_conversation(self.client, title="Old title")

        response = self.client.patch(
            reverse("tpwebapp:agent_chat_session_detail", args=[row.pk]),
            data=json.dumps({"title": "New title"}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"id": row.pk, "title": "New title"})
        row.refresh_from_db()
        self.assertEqual(row.title, "New title")

    def test_patch_without_permission_is_forbidden(self):
        row = self._create_conversation(self.client, title="Old title")
        user = get_user_model().objects.create_user(
            username="agent-detail-no-perm", password="test-pass"
        )
        self.client.force_login(user)

        response = self.client.patch(
            reverse("tpwebapp:agent_chat_session_detail", args=[row.pk]),
            data=json.dumps({"title": "New title"}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 403)

    def test_patch_with_blank_title_is_bad_request(self):
        row = self._create_conversation(self.client, title="Keep me")

        response = self.client.patch(
            reverse("tpwebapp:agent_chat_session_detail", args=[row.pk]),
            data=json.dumps({"title": "   "}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)
        row.refresh_from_db()
        self.assertEqual(row.title, "Keep me")

    def test_patch_on_another_session_s_conversation_is_not_found(self):
        from django.test import Client

        other_client = Client()
        other_client.force_login(self.smoke_user)
        row = self._create_conversation(other_client, title="Not yours")

        response = self.client.patch(
            reverse("tpwebapp:agent_chat_session_detail", args=[row.pk]),
            data=json.dumps({"title": "Hijacked"}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 404)
        row.refresh_from_db()
        self.assertEqual(row.title, "Not yours")

    def test_patch_on_nonexistent_id_is_not_found(self):
        self.client.get(reverse("tpwebapp:agent_chat"))

        response = self.client.patch(
            reverse("tpwebapp:agent_chat_session_detail", args=[999999]),
            data=json.dumps({"title": "Anything"}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 404)

    def test_delete_removes_the_conversation(self):
        from tpweb.models.AgentChatSession import AgentChatSession

        row = self._create_conversation(self.client, title="Bye")

        response = self.client.delete(reverse("tpwebapp:agent_chat_session_detail", args=[row.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"deleted": True})
        self.assertFalse(AgentChatSession.objects.filter(pk=row.pk).exists())

    def test_delete_is_not_found_the_second_time(self):
        row = self._create_conversation(self.client, title="Bye")
        url = reverse("tpwebapp:agent_chat_session_detail", args=[row.pk])

        self.client.delete(url)
        response = self.client.delete(url)

        self.assertEqual(response.status_code, 404)

    def test_delete_on_another_session_s_conversation_is_not_found(self):
        from django.test import Client

        from tpweb.models.AgentChatSession import AgentChatSession

        other_client = Client()
        other_client.force_login(self.smoke_user)
        row = self._create_conversation(other_client, title="Not yours")

        response = self.client.delete(reverse("tpwebapp:agent_chat_session_detail", args=[row.pk]))

        self.assertEqual(response.status_code, 404)
        self.assertTrue(AgentChatSession.objects.filter(pk=row.pk).exists())


class AgentChatPageScopeTests(TestCase):
    """_resolve_page_scope/_is_protein_list_path -- the server-side re-derivation
    that decides which genome/protein (if any) the assistant is allowed to act
    on for a given page, independent of the client's own claims."""

    # Biodatabase.PROT_POSTFIX is "_prots" (see the warning comment in
    # ProteinViewTests below) -- assembly_name is whatever's left after
    # stripping that suffix from the proteome biodatabase's own name, so the
    # genome and proteome need two separate Biodatabase rows here, not one.

    def test_resolves_scope_for_a_protein_page(self):
        proteome = Biodatabase.objects.create(name="SCOPE_TEST_prots")
        protein = Bioentry.objects.create(
            biodatabase=proteome, name="protA", accession="LOCUS_A", identifier="LOCUS_A"
        )

        assembly_name, default_accession = AgentChatView._resolve_page_scope(
            AnonymousUser(), f"/protein/{protein.bioentry_id}"
        )

        self.assertEqual(assembly_name, "SCOPE_TEST")
        self.assertEqual(default_accession, "LOCUS_A")

    def test_resolves_scope_for_a_structure_page_via_its_single_linked_protein(self):
        proteome = Biodatabase.objects.create(name="STRUCT_TEST_prots")
        protein = Bioentry.objects.create(
            biodatabase=proteome, name="protB", accession="LOCUS_B", identifier="LOCUS_B"
        )
        pdb = PDB.objects.create(code="1ABC", text="")
        BioentryStructure.objects.create(bioentry=protein, pdb=pdb)

        assembly_name, default_accession = AgentChatView._resolve_page_scope(
            AnonymousUser(), f"/structure/{pdb.id}"
        )

        self.assertEqual(assembly_name, "STRUCT_TEST")
        self.assertEqual(default_accession, "LOCUS_B")

    def test_structure_page_disambiguates_by_requested_protein_id_across_genomes(self):
        # A widely-solved reference structure can legitimately be the "best PDB
        # xref" for orthologous proteins in more than one genome -- the same
        # pdb_id links to bioentries in two different biodatabases here.
        genome_one = Biodatabase.objects.create(name="GENOME_ONE_prots")
        protein_one = Bioentry.objects.create(
            biodatabase=genome_one, name="p1", accession="ACC_ONE", identifier="ACC_ONE"
        )
        genome_two = Biodatabase.objects.create(name="GENOME_TWO_prots")
        protein_two = Bioentry.objects.create(
            biodatabase=genome_two, name="p2", accession="ACC_TWO", identifier="ACC_TWO"
        )
        pdb = PDB.objects.create(code="1SHARED", text="")
        BioentryStructure.objects.create(bioentry=protein_one, pdb=pdb)
        BioentryStructure.objects.create(bioentry=protein_two, pdb=pdb)

        # Explicitly requesting protein_two's id must resolve to genome two, not
        # whichever link happens to be "first" in the table.
        assembly_name, default_accession = AgentChatView._resolve_page_scope(
            AnonymousUser(),
            f"/structure/{pdb.id}",
            requested_protein_id=str(protein_two.bioentry_id),
        )

        self.assertEqual(assembly_name, "GENOME_TWO")
        self.assertEqual(default_accession, "ACC_TWO")

    def test_resolves_scope_for_a_binder_page(self):
        proteome = Biodatabase.objects.create(name="BINDER_TEST_prots")
        protein = Bioentry.objects.create(
            biodatabase=proteome, name="protC", accession="LOCUS_C", identifier="LOCUS_C"
        )
        binder = Binders.objects.create(
            ccd_id="ATP", pdb_id="1XYZ", uniprot="P99999", locustag=protein, smiles=""
        )

        assembly_name, default_accession = AgentChatView._resolve_page_scope(
            AnonymousUser(), f"/binder/{binder.id}"
        )

        self.assertEqual(assembly_name, "BINDER_TEST")
        self.assertEqual(default_accession, "LOCUS_C")

    def test_is_protein_list_path_true_only_for_the_list_route(self):
        # Pure URL-pattern matching, no DB lookup involved -- resolve() alone
        # decides this, same mechanism _resolve_page_scope already trusts.
        self.assertTrue(AgentChatView._is_protein_list_path("/genome/NZ_AP023069.1/proteins"))
        self.assertFalse(AgentChatView._is_protein_list_path("/genome/NZ_AP023069.1"))
        self.assertFalse(AgentChatView._is_protein_list_path("/protein/1"))
        self.assertFalse(AgentChatView._is_protein_list_path(""))


class MetabolismPathwayViewTests(LoggedInTestCase):
    def test_get_for_unknown_genome_is_not_found(self):
        response = self.client.get(
            reverse("tpwebapp:genome_metabolism", kwargs={"genome": "does-not-exist"})
        )
        self.assertEqual(response.status_code, 404)

    def test_get_renders_for_genome_with_no_metabolic_reactions(self):
        Biodatabase.objects.create(name="TEST", description="Genome workspace")
        Biodatabase.objects.create(name="TEST_prots")

        response = self.client.get(reverse("tpwebapp:genome_metabolism", kwargs={"genome": "TEST"}))

        self.assertEqual(response.status_code, 200)


class MetabolismNetworkViewTests(LoggedInTestCase):
    def test_get_for_unknown_protein_is_not_found(self):
        response = self.client.get(
            reverse("tpwebapp:protein_metabolic_network", kwargs={"protein_id": 999999})
        )
        self.assertEqual(response.status_code, 404)

    def test_returns_empty_network_for_protein_with_no_reactions(self):
        proteome = Biodatabase.objects.create(name="TEST_prots")
        protein = Bioentry.objects.create(
            biodatabase=proteome, name="protA", accession="LOCUS_A", identifier="LOCUS_A"
        )

        response = self.client.get(
            reverse(
                "tpwebapp:protein_metabolic_network", kwargs={"protein_id": protein.bioentry_id}
            )
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"nodes": [], "edges": []})


class ProteinViewTests(LoggedInTestCase):
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

    def test_use_test_genome_without_permission_is_blocked(self):
        # Approval no longer implies can_upload_genome by itself once the
        # permission was made independently revocable.
        user = get_user_model().objects.create_user(
            username="upload-no-perm", password="test-pass", is_staff=True
        )
        self.client.force_login(user)

        response = self.client.post(
            reverse("tpwebapp:genome_upload"), {"action": "use_test_genome"}, follow=True
        )

        self.assertEqual(response.status_code, 200)
        messages = list(response.context["messages"])
        self.assertTrue(any("permission" in str(m) for m in messages))

    def test_curated_import_action_without_permission_is_blocked(self):
        user = get_user_model().objects.create_user(
            username="upload-no-curated-perm", password="test-pass", is_staff=True
        )
        self.client.force_login(user)

        response = self.client.post(
            reverse("tpwebapp:genome_upload"),
            {"action": "validate_external_import"},
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        messages = list(response.context["messages"])
        self.assertTrue(any("curated external imports" in str(m) for m in messages))

    def test_clear_history_does_not_require_upload_permission(self):
        # Clearing history is not "uploading" -- it must stay reachable
        # even for a user without can_upload_genome.
        user = get_user_model().objects.create_user(
            username="upload-clear-only", password="test-pass", is_staff=True
        )
        self.client.force_login(user)

        response = self.client.post(
            reverse("tpwebapp:genome_upload"), {"action": "clear_history"}, follow=True
        )

        self.assertEqual(response.status_code, 200)
        messages = list(response.context["messages"])
        self.assertFalse(any("permission" in str(m) for m in messages))


class ProteinListViewTests(LoggedInTestCase):
    def test_renders_for_genome_with_no_proteins(self):
        Biodatabase.objects.create(name="TEST", description="Genome workspace")
        Biodatabase.objects.create(name="TEST_prots")

        response = self.client.get(reverse("tpwebapp:protein_list", kwargs={"genome": "TEST"}))

        self.assertEqual(response.status_code, 200)


class ProteinAdvancedFiltersViewTests(LoggedInTestCase):
    def test_get_for_unknown_genome_is_not_found(self):
        response = self.client.get(
            reverse("tpwebapp:protein_advanced_filters", kwargs={"genome": "does-not-exist"})
        )
        self.assertEqual(response.status_code, 404)

    def test_get_renders_for_existing_genome(self):
        Biodatabase.objects.create(name="TEST", description="Genome workspace")
        Biodatabase.objects.create(name="TEST_prots")

        response = self.client.get(
            reverse("tpwebapp:protein_advanced_filters", kwargs={"genome": "TEST"})
        )

        self.assertEqual(response.status_code, 200)

    def test_get_drops_stale_condition_and_warns_when_column_no_longer_visible(self):
        from tpweb.models.ScoreParam import ScoreParam, ScoreParamOptions
        from tpweb.services.workspace import set_workspace_session_value

        Biodatabase.objects.create(name="TEST", description="Genome workspace")
        Biodatabase.objects.create(name="TEST_prots")
        other_user = get_user_model().objects.create_user(
            username="other-owner", password="test-pass"
        )
        # Custom column owned by a different user -- invisible to smoke_user,
        # simulating a column hidden/deleted since this group was built.
        hidden_param = ScoreParam.objects.create(
            category="Custom", name="hidden_custom", type="C", user=other_user
        )
        hidden_option = ScoreParamOptions.objects.create(score_param=hidden_param, name="X")

        session = self.client.session
        set_workspace_session_value(
            session,
            self.smoke_user,
            "selected_parameters",
            [
                {
                    "id": f"adv:0:{hidden_option.pk}",
                    "type": "categorical",
                    "score_param_id": hidden_param.pk,
                    "score_param_name": hidden_param.name,
                    "name": "X",
                    "group_id": "adv:0",
                    "group_mode": "all",
                }
            ],
        )
        session.save()

        response = self.client.get(
            reverse("tpwebapp:protein_advanced_filters", kwargs={"genome": "TEST"})
        )

        self.assertEqual(response.status_code, 200)
        messages = list(response.context["messages"])
        self.assertTrue(
            any("ya no están disponibles" in str(m) for m in messages),
            f"expected a stale-condition warning, got: {messages}",
        )
        self.assertEqual(response.context["existing_groups"], [])

    def test_post_writes_an_any_group_into_session_and_redirects(self):
        from tpweb.models.ScoreParam import ScoreParam
        from tpweb.services.workspace import get_workspace_session_value

        Biodatabase.objects.create(name="TEST", description="Genome workspace")
        Biodatabase.objects.create(name="TEST_prots")
        fpocket_param = ScoreParam.objects.create(category="Pocket", name="druggability", type="N")
        p2rank_param = ScoreParam.objects.create(
            category="Pocket", name="p2rank_probability", type="N"
        )

        response = self.client.post(
            reverse("tpwebapp:protein_advanced_filters", kwargs={"genome": "TEST"}),
            {
                "groups_json": json.dumps(
                    [
                        {
                            "mode": "any",
                            "conditions": [
                                {
                                    "kind": "numeric",
                                    "score_param_id": fpocket_param.pk,
                                    "operation": ">=",
                                    "value": "0.7",
                                },
                                {
                                    "kind": "numeric",
                                    "score_param_id": p2rank_param.pk,
                                    "operation": ">=",
                                    "value": "0.5",
                                },
                            ],
                        }
                    ]
                )
            },
        )

        self.assertRedirects(response, reverse("tpwebapp:protein_list", kwargs={"genome": "TEST"}))
        selected_parameters = get_workspace_session_value(
            self.client.session, self.smoke_user, "selected_parameters", []
        )
        grouped = [item for item in selected_parameters if item.get("group_id") == "adv:0"]
        self.assertEqual(len(grouped), 2)
        self.assertTrue(all(item.get("group_mode") == "any" for item in grouped))

    def test_post_with_two_values_of_the_same_categorical_param_in_one_condition(self):
        # The builder UI shows multiple values for one criterion as a single
        # row (e.g. "Core OR Accessory"), not two separate condition rows --
        # this is the only sensible reading since a protein can't be both at
        # once, and the pre-existing selected_parameters_to_filter_map merge
        # logic in protein_list.py already treats same-param values as "any
        # of these" regardless of the group's ALL/ANY label.
        from tpweb.models.ScoreParam import ScoreParam, ScoreParamOptions
        from tpweb.services.protein_list import normalize_selected_parameters
        from tpweb.services.workspace import get_workspace_session_value

        Biodatabase.objects.create(name="TEST", description="Genome workspace")
        Biodatabase.objects.create(name="TEST_prots")
        core_param = ScoreParam.objects.create(
            category="Conservation", name="core_corecruncher", type="C"
        )
        core_option = ScoreParamOptions.objects.create(score_param=core_param, name="Core")
        accessory_option = ScoreParamOptions.objects.create(
            score_param=core_param, name="Accessory"
        )

        response = self.client.post(
            reverse("tpwebapp:protein_advanced_filters", kwargs={"genome": "TEST"}),
            {
                "groups_json": json.dumps(
                    [
                        {
                            "mode": "all",
                            "conditions": [
                                {
                                    "kind": "categorical",
                                    "score_param_id": core_param.pk,
                                    "option_ids": [core_option.pk, accessory_option.pk],
                                }
                            ],
                        }
                    ]
                )
            },
        )

        self.assertRedirects(response, reverse("tpwebapp:protein_list", kwargs={"genome": "TEST"}))
        selected_parameters = get_workspace_session_value(
            self.client.session, self.smoke_user, "selected_parameters", []
        )
        grouped = [item for item in selected_parameters if item.get("group_id") == "adv:0"]
        self.assertEqual(len(grouped), 2)
        self.assertEqual({str(item.get("name")) for item in grouped}, {"Core", "Accessory"})

        # Reopening the builder merges them back into one condition, not two rows.
        existing_groups, dropped_count = ProteinAdvancedFiltersView._existing_groups(
            normalize_selected_parameters(selected_parameters)
        )
        self.assertEqual(dropped_count, 0)
        self.assertEqual(len(existing_groups), 1)
        self.assertEqual(len(existing_groups[0]["conditions"]), 1)
        self.assertEqual(
            {str(oid) for oid in existing_groups[0]["conditions"][0]["option_ids"]},
            {str(core_option.pk), str(accessory_option.pk)},
        )
