from unittest.mock import patch

from django.test import SimpleTestCase

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
from tpweb.services.protein_formula import choose_formula
from tpweb.services.protein_serializer import build_protein_table_row
from tpweb.services.pipeline_status import annotate_pipeline_status_for_genome


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
