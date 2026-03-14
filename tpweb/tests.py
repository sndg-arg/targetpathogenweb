from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.test import SimpleTestCase, TestCase

from tpweb.models.GenomeUpload import GenomeUpload
from tpweb.models.ScoreFormula import ScoreFormula
from tpweb.models.ScoreParam import ScoreParam
from tpweb.services.genome_uploads import build_queue_position_map, owner_has_active_uploads
from tpweb.services.genomes import build_genome_dto, safe_int, summarize_genomes
from tpweb.services.protein_list import (
    add_selected_parameter,
    apply_protein_search,
    empty_pagination_payload,
    grouped_selected_parameters,
    normalize_selected_parameters,
    parse_page_size,
    remove_selected_parameter,
)
from tpweb.services.protein_formula import choose_formula, resolve_formulas_for_user
from tpweb.services.protein_serializer import build_protein_table_row
from tpweb.services.pipeline_status import annotate_pipeline_status_for_genome
from tpweb.services.genome_workspace import (
    build_workspace_genome_name,
    display_genome_name,
    user_can_access_genome_name,
)
from tpweb.services.score_params import visible_score_params_queryset
from tpweb.services.workspace import (
    get_public_workspace_user,
    get_workspace_session_value,
    set_workspace_session_value,
)
from tpweb.views.FormulaForm import FormulaForm
from tpweb.views.ParameterForm import ParameterForm


class GenomeServiceTests(SimpleTestCase):
    def test_safe_int_handles_invalid_values(self):
        self.assertEqual(safe_int(None), 0)
        self.assertEqual(safe_int("abc"), 0)
        self.assertEqual(safe_int("12.0"), 12)

    def test_summarize_genomes_returns_expected_metrics(self):
        genomes = [
            {"name": "G1", "COUNT_CDS": "5", "COUNT_STRUCTS": "2"},
            {"name": "G2", "COUNT_CDS": "7", "COUNT_STRUCTS": "0"},
        ]
        summary = summarize_genomes(genomes)
        self.assertEqual(summary["total_genomes"], 2)
        self.assertEqual(summary["total_proteins"], 12)
        self.assertEqual(summary["genomes_with_structures"], 1)

    def test_build_genome_dto_uses_db_fallback_counts_when_qualifiers_missing(self):
        genome = type(
            "Genome",
            (),
            {
                "name": "NZ_AP023069.1",
                "description": "Example genome",
                "qualifiers_dict": lambda self: {},
            },
        )()

        dto = build_genome_dto(
            genome,
            protein_counts_by_genome={"NZ_AP023069.1": 62},
            structure_counts_by_genome={"NZ_AP023069.1": 0},
        )

        self.assertEqual(dto["COUNT_CDS"], 62)
        self.assertEqual(dto["COUNT_STRUCTS"], 62)

    def test_build_genome_dto_prefers_live_counts_over_qualifiers(self):
        genome = type(
            "Genome",
            (),
            {
                "name": "NZ_AP023069.1",
                "description": "Example genome",
                "qualifiers_dict": lambda self: {
                    "COUNT_CDS": "73",
                    "COUNT_STRUCTS": "8",
                },
            },
        )()

        dto = build_genome_dto(
            genome,
            protein_counts_by_genome={"NZ_AP023069.1": 62},
            structure_counts_by_genome={"NZ_AP023069.1": 0},
        )

        self.assertEqual(dto["COUNT_CDS"], 62)
        self.assertEqual(dto["COUNT_STRUCTS"], 62)


class ProteinListServiceTests(SimpleTestCase):
    def test_normalize_selected_parameters(self):
        self.assertEqual(normalize_selected_parameters([]), [])
        self.assertEqual(normalize_selected_parameters("invalid"), [])

    def test_grouped_selected_parameters(self):
        selected = [
            {"score_param_name": "Druggability", "name": "High"},
            {"score_param_name": "Druggability", "name": "Medium"},
            {"score_param_name": "Localization", "name": "Cytoplasm"},
        ]
        grouped = grouped_selected_parameters(selected)
        self.assertEqual(grouped["Druggability"], "High, Medium")
        self.assertEqual(grouped["Localization"], "Cytoplasm")

    def test_add_and_remove_selected_parameter(self):
        selected = [{"id": 1, "name": "High"}]
        selected = add_selected_parameter(selected, {"id": 2, "name": "Medium"})
        self.assertEqual(len(selected), 2)
        selected = add_selected_parameter(selected, {"id": 2, "name": "Medium"})
        self.assertEqual(len(selected), 2)
        selected = remove_selected_parameter(selected, 1)
        self.assertEqual([x["id"] for x in selected], [2])

    def test_parse_page_size_bounds(self):
        self.assertEqual(parse_page_size("5"), 10)
        self.assertEqual(parse_page_size("25"), 25)
        self.assertEqual(parse_page_size("200"), 100)
        self.assertEqual(parse_page_size("invalid"), 25)

    def test_empty_pagination_payload(self):
        payload = empty_pagination_payload()
        self.assertEqual(payload["number"], 1)
        self.assertEqual(payload["num_pages"], 1)
        self.assertEqual(payload["proteins"].paginator.count, 0)

    def test_apply_protein_search_no_query_returns_same_queryset(self):
        class DummyQueryset:
            called = False

            def filter(self, *args, **kwargs):
                self.called = True
                return self

        queryset = DummyQueryset()
        result = apply_protein_search(queryset, "")
        self.assertIs(result, queryset)
        self.assertFalse(queryset.called)


class ProteinFormulaServiceTests(SimpleTestCase):
    def test_choose_formula_by_requested_name(self):
        formula_a = type("Formula", (), {"name": "A", "default": False})()
        formula_b = type("Formula", (), {"name": "B", "default": True})()
        selected = choose_formula([formula_a, formula_b], "A")
        self.assertIs(selected, formula_a)

    def test_choose_formula_falls_back_to_default(self):
        formula_a = type("Formula", (), {"name": "A", "default": False})()
        formula_b = type("Formula", (), {"name": "B", "default": True})()
        selected = choose_formula([formula_a, formula_b], "")
        self.assertIs(selected, formula_b)


class WorkspaceIsolationTests(TestCase):
    def setUp(self):
        self.user_model = get_user_model()
        self.alice = self.user_model.objects.create_user(
            username="alice",
            password="test-pass",
        )
        self.bob = self.user_model.objects.create_user(
            username="bob",
            password="test-pass",
        )
        self.public_user = get_public_workspace_user()

    def create_score_param(self, name, category, user=None):
        return ScoreParam.objects.create(
            category=category,
            name=name,
            type="C",
            default_operation="=",
            default_value="",
            description="",
            user=user,
        )

    def test_workspace_session_values_are_namespaced(self):
        session = {}

        set_workspace_session_value(session, AnonymousUser(), "selected_parameters", ["public"])
        set_workspace_session_value(session, self.alice, "selected_parameters", ["alice"])

        self.assertEqual(
            get_workspace_session_value(session, AnonymousUser(), "selected_parameters", []),
            ["public"],
        )
        self.assertEqual(
            get_workspace_session_value(session, self.alice, "selected_parameters", []),
            ["alice"],
        )

    def test_visible_score_params_queryset_isolated_by_workspace(self):
        self.create_score_param(name="GlobalBuiltin", category="Protein", user=None)
        self.create_score_param(name="PublicCustom", category="Custom", user=self.public_user)
        self.create_score_param(name="AliceCustom", category="Custom", user=self.alice)
        self.create_score_param(name="BobCustom", category="Custom", user=self.bob)

        anonymous_names = list(
            visible_score_params_queryset(AnonymousUser()).values_list("name", flat=True)
        )
        alice_names = list(
            visible_score_params_queryset(self.alice).values_list("name", flat=True)
        )

        self.assertIn("GlobalBuiltin", anonymous_names)
        self.assertIn("PublicCustom", anonymous_names)
        self.assertNotIn("AliceCustom", anonymous_names)
        self.assertNotIn("BobCustom", anonymous_names)

        self.assertIn("GlobalBuiltin", alice_names)
        self.assertIn("AliceCustom", alice_names)
        self.assertNotIn("PublicCustom", alice_names)
        self.assertNotIn("BobCustom", alice_names)

    def test_resolve_formulas_for_user_uses_current_workspace(self):
        ScoreFormula.objects.create(name="PublicFormula", user=self.public_user, default=True)
        ScoreFormula.objects.create(name="AliceFormula", user=self.alice, default=True)
        ScoreFormula.objects.create(name="BobFormula", user=self.bob, default=True)

        anonymous_formulas = [formula.name for formula in resolve_formulas_for_user(AnonymousUser())]
        alice_formulas = [formula.name for formula in resolve_formulas_for_user(self.alice)]

        self.assertEqual(anonymous_formulas, ["PublicFormula"])
        self.assertEqual(alice_formulas, ["AliceFormula"])

    def test_parameter_and_formula_forms_only_show_visible_params(self):
        self.create_score_param(name="GlobalBuiltin", category="Protein", user=None)
        self.create_score_param(name="AliceCustom", category="Custom", user=self.alice)
        self.create_score_param(name="BobCustom", category="Custom", user=self.bob)

        parameter_form = ParameterForm(user=self.alice)
        formula_form = FormulaForm(user=self.alice)

        visible_names = list(parameter_form.fields["param"].queryset.values_list("name", flat=True))
        formula_names = list(formula_form.fields["param"].queryset.values_list("name", flat=True))

        self.assertEqual(visible_names, formula_names)
        self.assertIn("GlobalBuiltin", visible_names)
        self.assertIn("AliceCustom", visible_names)
        self.assertNotIn("BobCustom", visible_names)

    def test_workspace_genome_names_are_hidden_from_other_users(self):
        alice_internal = build_workspace_genome_name("NZ_AP023069.1", self.alice)
        bob_internal = build_workspace_genome_name("NZ_AP023069.1", self.bob)

        self.assertEqual(display_genome_name(alice_internal), "NZ_AP023069.1")
        self.assertTrue(user_can_access_genome_name(self.alice, alice_internal))
        self.assertFalse(user_can_access_genome_name(self.alice, bob_internal))
        self.assertFalse(user_can_access_genome_name(AnonymousUser(), alice_internal))


class GenomeUploadQueueTests(TestCase):
    def setUp(self):
        self.user_model = get_user_model()
        self.alice = self.user_model.objects.create_user(
            username="alice_queue",
            password="test-pass",
        )
        self.bob = self.user_model.objects.create_user(
            username="bob_queue",
            password="test-pass",
        )

    def create_upload(self, owner, accession, status):
        return GenomeUpload.objects.create(
            owner=owner,
            display_accession=accession,
            internal_accession=build_workspace_genome_name(accession, owner),
            gram="n",
            gbk_file="",
            status=status,
        )

    def test_build_queue_position_map_is_global_and_ordered(self):
        first = self.create_upload(self.alice, "NZ_AP023069.1", GenomeUpload.STATUS_SUBMITTED)
        second = self.create_upload(self.bob, "NC_002516.2", GenomeUpload.STATUS_SUBMITTED)
        self.create_upload(self.alice, "GCF_000001", GenomeUpload.STATUS_FAILED)

        positions = build_queue_position_map()

        self.assertEqual(positions[first.id], 1)
        self.assertEqual(positions[second.id], 2)
        self.assertEqual(len(positions), 2)

    def test_owner_has_active_uploads_only_for_queued_or_running(self):
        self.assertFalse(owner_has_active_uploads(self.alice))

        self.create_upload(self.alice, "NZ_AP023069.1", GenomeUpload.STATUS_SUBMITTED)
        self.assertTrue(owner_has_active_uploads(self.alice))

        GenomeUpload.objects.filter(owner=self.alice).update(status=GenomeUpload.STATUS_FAILED)
        self.assertFalse(owner_has_active_uploads(self.alice))


class ProteinSerializerServiceTests(SimpleTestCase):
    def test_build_protein_table_row(self):
        score_param_a = type("SP", (), {"name": "ParamA"})()
        score_param_b = type("SP", (), {"name": "ParamB"})()
        score_value_a = type("SV", (), {"score_param": score_param_a, "value": "High"})()
        score_value_b = type("SV", (), {"score_param": score_param_b, "value": "Low"})()
        score_params = type("ScoreParams", (), {"all": lambda self: [score_value_a, score_value_b]})()
        protein = type(
            "Protein",
            (),
            {
                "bioentry_id": 10,
                "accession": "ACC001",
                "name": "Prot1",
                "description": "Desc",
                "score_params": score_params,
                "genes": lambda self: ["abc", "longgenevalue"],
            },
        )()
        row, table_data, weights = build_protein_table_row(
            protein,
            visible_columns={"ParamA": "x", "ParamB": "y"},
            coefficient_by_param={"ParamA": {"High": 2.5}, "ParamB": {"Low": -1.0}},
        )
        self.assertEqual(row["score"], 1.5)
        self.assertEqual(row["genes"], ["abc"])
        self.assertEqual(table_data["Score"], 1.5)
        self.assertEqual(weights["ParamA"], 2.5)


class PipelineStatusTests(SimpleTestCase):
    def test_annotate_pipeline_status_for_genome_flags(self):
        status = {
            "running": True,
            "genome_accession": "NZ_AP023069.1",
        }
        current = annotate_pipeline_status_for_genome(status, "NZ_AP023069.1")
        self.assertTrue(current["running_for_current_genome"])
        self.assertFalse(current["running_for_other_genome"])
        self.assertIsNone(current["other_genome_accession"])

        other = annotate_pipeline_status_for_genome(status, "GCA_000001")
        self.assertFalse(other["running_for_current_genome"])
        self.assertTrue(other["running_for_other_genome"])
        self.assertEqual(other["other_genome_accession"], "NZ_AP023069.1")


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
            "genomes_with_structures": 0,
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
            "genomes_with_structures": 0,
        }
        get_pipeline_status.return_value = {"available": False, "running": False}

        response = self.client.get("/genomes")
        self.assertEqual(response.status_code, 200)
