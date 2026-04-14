from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import tpweb.services.pipeline_status as pipeline_status_service

from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.db.utils import InterfaceError
from django.test import SimpleTestCase, TestCase

from bioseq.models.Bioentry import Bioentry
from bioseq.models.BioentryDbxref import BioentryDbxref
from bioseq.models.Biodatabase import Biodatabase
from tpweb.models.BioentryStructure import BioentryStructure
from tpweb.models.GenomeUpload import GenomeUpload
from tpweb.models.PipelineRun import PipelineRun
from tpweb.models.ScoreFormula import ScoreFormula
from tpweb.models.ScoreParam import ScoreParam
from tpweb.services.assembly_workspace import build_assembly_workspace_metrics
from tpweb.services.assembly_overview import build_assembly_overview
from tpweb.services.genome_uploads import (
    _finalize_upload,
    build_queue_position_map,
    clear_genome_upload_history,
    delete_genome_workspace,
    owner_has_active_uploads,
    workspace_has_active_upload,
)
from tpweb.services.genome_upload_status import reconcile_genome_uploads
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
from tpweb.services.protein_annotations import ANNOTATION_KIND_CONFIG, build_annotation_explorer
from tpweb.services.protein_formula import choose_formula, resolve_formulas_for_user
from tpweb.services.protein_serializer import build_protein_table_row
from tpweb.services.pipeline_status import (
    _status_from_last_run_marker,
    annotate_pipeline_status_for_genome,
    get_pipeline_status_dto,
    sanitize_pipeline_status_for_user,
)
from tpweb.services.structure_sources import summarize_structure_sources
from tpweb.services.genome_workspace import (
    build_workspace_genome_name,
    describe_genome_scope,
    display_genome_name,
    user_can_access_genome_name,
    user_can_delete_genome_name,
)
from tpweb.services.score_params import visible_score_params_queryset
from tpweb.services.workspace import (
    get_public_workspace_user,
    get_workspace_session_value,
    set_workspace_session_value,
)
from tpweb.views.FormulaForm import FormulaForm
from tpweb.views.ParameterForm import ParameterForm
from tpweb.services.workspace import PUBLIC_WORKSPACE_USERNAME


class GenomeServiceTests(SimpleTestCase):
    def test_safe_int_handles_invalid_values(self):
        self.assertEqual(safe_int(None), 0)
        self.assertEqual(safe_int("abc"), 0)
        self.assertEqual(safe_int("12.0"), 12)

    def test_summarize_genomes_returns_expected_metrics(self):
        genomes = [
            {"name": "G1", "COUNT_CDS": "5", "COUNT_EXPERIMENTAL": "2", "COUNT_EC": "4"},
            {"name": "G2", "COUNT_CDS": "7", "COUNT_EXPERIMENTAL": "1", "COUNT_EC": "0"},
        ]
        summary = summarize_genomes(genomes)
        self.assertEqual(summary["total_genomes"], 2)
        self.assertEqual(summary["total_proteins"], 12)
        self.assertEqual(summary["total_experimental"], 3)
        self.assertEqual(summary["total_ec_annotated"], 4)

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
            experimental_counts_by_genome={"NZ_AP023069.1": 7},
            ec_counts_by_genome={"NZ_AP023069.1": 31},
        )

        self.assertEqual(dto["COUNT_CDS"], 62)
        self.assertEqual(dto["COUNT_EXPERIMENTAL"], 7)
        self.assertEqual(dto["COUNT_EC"], 31)

    def test_build_genome_dto_prefers_live_counts_over_qualifiers(self):
        genome = type(
            "Genome",
            (),
            {
                "name": "NZ_AP023069.1",
                "description": "Example genome",
                "qualifiers_dict": lambda self: {
                    "COUNT_CDS": "73",
                    "COUNT_EXPERIMENTAL": "8",
                    "COUNT_EC": "12",
                },
            },
        )()

        dto = build_genome_dto(
            genome,
            protein_counts_by_genome={"NZ_AP023069.1": 62},
            experimental_counts_by_genome={"NZ_AP023069.1": 7},
            ec_counts_by_genome={"NZ_AP023069.1": 31},
        )

        self.assertEqual(dto["COUNT_CDS"], 62)
        self.assertEqual(dto["COUNT_EXPERIMENTAL"], 7)
        self.assertEqual(dto["COUNT_EC"], 31)

    def test_describe_genome_scope_returns_personal_for_current_user_workspace(self):
        user = type("User", (), {"is_authenticated": True, "pk": 7})()

        scope = describe_genome_scope(user, "user-7__NC_002516.2")

        self.assertEqual(scope["key"], "personal")
        self.assertEqual(scope["label"], "Private")

    def test_build_genome_dto_adds_workspace_scope_metadata(self):
        user = type("User", (), {"is_authenticated": True, "pk": 7})()
        genome = type(
            "Genome",
            (),
            {
                "name": "public__NZ_AP023069.1",
                "description": "Public genome",
                "qualifiers_dict": lambda self: {},
            },
        )()

        dto = build_genome_dto(genome, user=user)

        self.assertEqual(dto["workspace_scope_key"], "public")
        self.assertEqual(dto["workspace_scope_label"], "Public")

    def test_build_assembly_overview_prefers_live_protein_counts(self):
        overview = build_assembly_overview(
            user=AnonymousUser(),
            genome_name="NZ_AP023069.1",
            description="Neisseria gonorrhoeae strain TUM19854 chromosome, complete genome",
            props={"COUNT_CDS": "73", "COUNT_gene": "75", "COUNT_tRNA": "2"},
            workspace_metrics={"total_proteins": 62},
        )

        protein_coding_loaded = next(
            fact["value"]
            for fact in overview["loaded_feature_facts"]
            if fact["label"] == "Protein-coding loaded"
        )
        untranslated_cds = next(
            fact["value"]
            for fact in overview["composition_facts"]
            if fact["label"] == "CDS without protein sequence"
        )

        self.assertEqual(protein_coding_loaded, "62")
        self.assertEqual(untranslated_cds, "11")


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

    def test_grouped_selected_parameters_handles_numeric_filters(self):
        selected = [
            {
                "score_param_name": "druggability_score",
                "type": "numeric",
                "operation": ">=",
                "value": 0.75,
            }
        ]

        grouped = grouped_selected_parameters(selected, humanize=True)

        self.assertEqual(grouped["Druggability Score"], ">= 0.75")

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


class StructureAndAnnotationServiceTests(SimpleTestCase):
    def test_summarize_structure_sources_handles_mixed_sources(self):
        experimental_structure = type(
            "Structure",
            (),
            {"pdb": type("PDB", (), {"experiment": "X-RAY"})()},
        )()
        alphafold_structure = type(
            "Structure",
            (),
            {"pdb": type("PDB", (), {"experiment": "AF"})()},
        )()

        summary = summarize_structure_sources([experimental_structure, alphafold_structure])

        self.assertEqual(summary["source"], "mixed")
        self.assertEqual(summary["label"], "Experimental + AlphaFold")
        self.assertEqual(summary["count"], 2)

    def test_build_annotation_explorer_builds_ec_hierarchy(self):
        dbxref_relation = lambda accession, name="": type(
            "BioentryDbxref",
            (),
            {
                "dbxref": type(
                    "Dbxref",
                    (),
                    {
                        "dbname": ANNOTATION_KIND_CONFIG["ec"]["dbnames"][0],
                        "accession": accession,
                        "terms": type(
                            "Terms",
                            (),
                            {
                                "all": lambda self: [
                                    type(
                                        "TermRelation",
                                        (),
                                        {"term": type("Term", (), {"definition": name})()},
                                    )()
                                ]
                            },
                        )(),
                    },
                )()
            },
        )()

        protein_a = type(
            "Protein",
            (),
            {
                "bioentry_id": 1,
                "dbxrefs": type("Manager", (), {"all": lambda self: [dbxref_relation("1.2.3.4", "Example enzyme")]})(),
            },
        )()
        protein_b = type(
            "Protein",
            (),
            {
                "bioentry_id": 2,
                "dbxrefs": type("Manager", (), {"all": lambda self: [dbxref_relation("1.2.3.5", "Sibling enzyme")]})(),
            },
        )()

        explorer = build_annotation_explorer([protein_a, protein_b], "ec")

        self.assertEqual(explorer["annotation_count"], 2)
        self.assertIn("ec:1.2", explorer["chart"]["ids"])
        self.assertIn("1.2 Acting on the aldehyde or oxo group of donors", explorer["chart"]["labels"])
        self.assertIn("1.2.3.4", explorer["chart"]["hover_labels"])
        self.assertEqual(explorer["rows"][0]["protein_count"], 1)

    def test_build_annotation_explorer_adds_hover_text_for_known_third_level_ec_prefix(self):
        dbxref_relation = lambda accession, name="": type(
            "BioentryDbxref",
            (),
            {
                "dbxref": type(
                    "Dbxref",
                    (),
                    {
                        "dbname": ANNOTATION_KIND_CONFIG["ec"]["dbnames"][0],
                        "accession": accession,
                        "terms": type("Terms", (), {"all": lambda self: []})(),
                    },
                )()
            },
        )()

        protein = type(
            "Protein",
            (),
            {
                "bioentry_id": 1,
                "dbxrefs": type("Manager", (), {"all": lambda self: [dbxref_relation("2.4.1.1")]})(),
            },
        )()

        explorer = build_annotation_explorer([protein], "ec")
        prefix_index = explorer["chart"]["ids"].index("ec:2.4.1")

        self.assertEqual(
            explorer["chart"]["hover_labels"][prefix_index],
            "2.4.1 — Hexosyltransferases",
        )


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
        public_internal = build_workspace_genome_name("NZ_AP023069.1", AnonymousUser())

        self.assertEqual(display_genome_name(alice_internal), "NZ_AP023069.1")
        self.assertTrue(user_can_access_genome_name(self.alice, alice_internal))
        self.assertFalse(user_can_access_genome_name(self.alice, bob_internal))
        self.assertFalse(user_can_access_genome_name(AnonymousUser(), alice_internal))
        self.assertTrue(user_can_delete_genome_name(self.alice, alice_internal))
        self.assertFalse(user_can_delete_genome_name(self.bob, alice_internal))
        self.assertFalse(user_can_delete_genome_name(self.alice, public_internal))


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

    @patch("tpweb.services.genome_uploads._delete_workspace_biodatabases")
    def test_clear_genome_upload_history_removes_failed_workspace_artifacts(self, delete_workspace):
        failed = self.create_upload(self.alice, "NZ_AP023069.1", GenomeUpload.STATUS_FAILED)
        self.create_upload(self.alice, "NC_002516.2", GenomeUpload.STATUS_FINISHED)

        deleted_count = clear_genome_upload_history(self.alice)

        self.assertEqual(deleted_count, 2)
        delete_workspace.assert_called_once_with(failed.internal_accession)

    def test_workspace_has_active_upload_is_scoped_by_internal_accession(self):
        upload = self.create_upload(self.alice, "NZ_AP023069.1", GenomeUpload.STATUS_SUBMITTED)

        self.assertTrue(workspace_has_active_upload(upload.internal_accession, owner=self.alice))
        self.assertFalse(workspace_has_active_upload("user-999__OTHER", owner=self.alice))

    @patch("tpweb.services.genome_uploads._delete_workspace_biodatabases")
    def test_delete_genome_workspace_removes_workspace_upload_records(self, delete_workspace):
        upload = self.create_upload(self.alice, "NZ_AP023069.1", GenomeUpload.STATUS_FINISHED)

        deleted_count = delete_genome_workspace(upload.internal_accession, owner=self.alice)

        self.assertEqual(deleted_count, 1)
        self.assertFalse(GenomeUpload.objects.filter(pk=upload.pk).exists())
        delete_workspace.assert_called_once_with(upload.internal_accession)

    @patch("tpweb.services.genome_uploads.clear_pipeline_activity_state")
    @patch("tpweb.services.genome_uploads._delete_workspace_biodatabases")
    @patch("tpweb.services.genome_uploads._delete_upload_artifacts")
    def test_finalize_upload_does_not_crash_when_upload_was_deleted(
        self,
        delete_upload_artifacts,
        delete_workspace_biodatabases,
        clear_pipeline_activity_state,
    ):
        upload = self.create_upload(self.alice, "NZ_AP023069.1", GenomeUpload.STATUS_RUNNING)
        upload.delete()

        status = _finalize_upload(upload, returncode=1)

        self.assertEqual(status, GenomeUpload.STATUS_FAILED)
        delete_upload_artifacts.assert_called_once_with(upload)
        delete_workspace_biodatabases.assert_called_once_with(upload.internal_accession)
        clear_pipeline_activity_state.assert_called_once()

    @patch("tpweb.services.genome_uploads._extract_error_message")
    @patch("tpweb.services.genome_uploads._delete_workspace_biodatabases")
    def test_finalize_upload_removes_partial_workspace_when_pipeline_fails(
        self,
        delete_workspace_biodatabases,
        extract_error_message,
    ):
        upload = self.create_upload(self.alice, "NZ_AP023069.1", GenomeUpload.STATUS_RUNNING)
        extract_error_message.return_value = "Pipeline failed."

        status = _finalize_upload(upload, returncode=1)

        upload.refresh_from_db()
        self.assertEqual(status, GenomeUpload.STATUS_FAILED)
        self.assertEqual(upload.status, GenomeUpload.STATUS_FAILED)
        self.assertEqual(upload.error_message, "Pipeline failed.")
        delete_workspace_biodatabases.assert_called_once_with(upload.internal_accession)

    @patch("tpweb.services.genome_upload_status._upload_has_matching_process")
    @patch("tpweb.services.genome_upload_status._process_exists")
    def test_reconcile_keeps_running_upload_when_matching_process_exists(
        self, process_exists, upload_has_matching_process
    ):
        upload = self.create_upload(self.alice, "NC_002516.2", GenomeUpload.STATUS_RUNNING)
        upload.launch_pid = None
        upload.save(update_fields=["launch_pid"])
        process_exists.return_value = False
        upload_has_matching_process.return_value = True

        reconcile_genome_uploads(
            {
                "running": True,
                "genome_accession": None,
                "state_label": "Pipeline running",
            },
            owner=self.alice,
        )

        upload.refresh_from_db()
        self.assertEqual(upload.status, GenomeUpload.STATUS_RUNNING)
        self.assertEqual(upload.error_message, "")

    @patch("tpweb.services.genome_upload_status._upload_has_matching_process")
    @patch("tpweb.services.genome_upload_status._process_exists")
    def test_reconcile_ignores_cancelled_legacy_run_for_new_upload(
        self, process_exists, upload_has_matching_process
    ):
        upload = self.create_upload(self.alice, "NZ_AP023069.1", GenomeUpload.STATUS_SUBMITTED)
        process_exists.return_value = False
        upload_has_matching_process.return_value = False

        PipelineRun.objects.create(
            genome_upload=None,
            internal_accession=upload.internal_accession,
            source_accession="NZ_AP023069.1",
            gram="n",
            status=PipelineRun.STATUS_CANCELLED,
            error_message="Old cancelled legacy run",
        )

        reconcile_genome_uploads(
            {
                "running": False,
                "genome_accession": None,
                "state_label": "No pipeline activity detected",
            },
            owner=self.alice,
        )

        upload.refresh_from_db()
        self.assertEqual(upload.status, GenomeUpload.STATUS_SUBMITTED)
        self.assertEqual(upload.error_message, "")

    def test_sanitize_pipeline_status_prefers_workspace_owner_for_private_run(self):
        status = sanitize_pipeline_status_for_user(
            {
                "available": True,
                "running": True,
                "state_label": "Pipeline running",
                "state_class": "running",
                "genome_accession": build_workspace_genome_name("NZ_AP023069.1", self.alice),
                "genome_display_accession": "NZ_AP023069.1",
                "workspace_slug": "user-999",
                "workspace_owner_id": self.alice.id,
                "stage_current": 10,
            },
            self.alice,
        )

        self.assertTrue(status["genome_visible_to_user"])
        self.assertFalse(status["running_for_other_workspace"])
        self.assertEqual(status["genome_accession"], build_workspace_genome_name("NZ_AP023069.1", self.alice))


class ProteinSerializerServiceTests(SimpleTestCase):
    def test_build_protein_table_row(self):
        score_param_a = type("SP", (), {"name": "ParamA"})()
        score_param_b = type("SP", (), {"name": "ParamB"})()
        score_value_a = type("SV", (), {"score_param": score_param_a, "value": "High"})()
        score_value_b = type("SV", (), {"score_param": score_param_b, "value": "Low"})()
        score_params = type("ScoreParams", (), {"all": lambda self: [score_value_a, score_value_b]})()
        empty_manager = type("EmptyManager", (), {"all": lambda self: []})()
        protein = type(
            "Protein",
            (),
            {
                "bioentry_id": 10,
                "accession": "ACC001",
                "name": "Prot1",
                "description": "Desc",
                "score_params": score_params,
                "structures": empty_manager,
                "dbxrefs": empty_manager,
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

    def test_annotate_pipeline_status_for_genome_marks_failed_workspace_as_incomplete(self):
        status = {
            "running": False,
            "genome_accession": "NZ_AP023069.1",
            "state_label": "Last pipeline run failed",
        }

        current = annotate_pipeline_status_for_genome(status, "NZ_AP023069.1")

        self.assertTrue(current["failed_for_current_genome"])
        self.assertTrue(current["incomplete_for_current_genome"])
        self.assertIn("incomplete", current["current_genome_status_note"].lower())
        self.assertIn("failed", current["current_genome_status_note"].lower())

    def test_annotate_pipeline_status_for_genome_marks_stopped_workspace_as_incomplete(self):
        status = {
            "running": False,
            "genome_accession": "NZ_AP023069.1",
            "state_label": "Last pipeline run stopped before completion",
        }

        current = annotate_pipeline_status_for_genome(status, "NZ_AP023069.1")

        self.assertFalse(current["failed_for_current_genome"])
        self.assertTrue(current["incomplete_for_current_genome"])
        self.assertIn("stopped before completion", current["current_genome_status_note"])

    def test_status_from_last_run_marker_reads_shared_data_marker(self):
        with TemporaryDirectory() as tmpdir:
            base_dir = Path(tmpdir)
            marker_path = base_dir / "data" / "pipeline" / "last_pipeline_run.json"
            marker_path.parent.mkdir(parents=True, exist_ok=True)
            marker_path.write_text(
                """
{
  "status": "finished",
  "genomes": ["user-2__NZ_AP023069.1"],
  "finished_at_utc": "2026-03-28T21:00:00+00:00"
}
                """.strip(),
                encoding="utf-8",
            )

            status = _status_from_last_run_marker(base_dir)

        self.assertIsNotNone(status)
        self.assertTrue(status.available)
        self.assertEqual(status.state_label, "Last pipeline run finished")
        self.assertEqual(status.genome_accession, "USER-2__NZ_AP023069.1")
        self.assertEqual(status.genome_display_accession, "NZ_AP023069.1")

    @patch("tpweb.services.pipeline_status.Biodatabase")
    def test_sanitize_pipeline_status_for_user_hides_deleted_workspace_status(self, biodatabase_model):
        biodatabase_model.objects.filter.return_value.exists.return_value = False

        status = sanitize_pipeline_status_for_user(
            {
                "available": True,
                "running": False,
                "state_label": "Last pipeline run failed",
                "state_class": "failed",
                "genome_accession": "user-2__NC_002516.2",
                "genome_display_accession": "NC_002516.2",
                "stage_current": 4,
                "progress_percent": 19,
            },
            AnonymousUser(),
        )

        self.assertFalse(status["available"])
        self.assertFalse(status["running"])

    def test_sanitize_pipeline_status_for_user_keeps_public_run_visible_for_anonymous_user(self):
        status = sanitize_pipeline_status_for_user(
            {
                "available": True,
                "running": True,
                "state_label": "Pipeline running",
                "state_class": "running",
                "genome_accession": "public__NZ_AP023069.1",
                "genome_display_accession": "NZ_AP023069.1",
                "workspace_slug": "public",
                "workspace_owner_id": 1,
                "stage_current": 9,
            },
            AnonymousUser(),
        )

        self.assertTrue(status["genome_visible_to_user"])
        self.assertFalse(status["running_for_other_workspace"])
        self.assertEqual(status["genome_accession"], "public__NZ_AP023069.1")
        self.assertEqual(status["state_class"], "running")


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
    def test_get_pipeline_status_falls_back_to_idle_on_database_error(self, latest_active_pipeline_run):
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
