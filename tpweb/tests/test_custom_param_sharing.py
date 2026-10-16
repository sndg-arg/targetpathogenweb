from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, TestCase

from bioseq.models.Biodatabase import Biodatabase
from bioseq.models.Bioentry import Bioentry
from tpweb.forms.CustomParamForm import CustomParamForm
from tpweb.models.CustomParamShare import CustomParamShare
from tpweb.models.RestrictedGenome import RestrictedGenome
from tpweb.models.ScoreParam import ScoreParam
from tpweb.models.ScoreParamValue import ScoreParamValue
from tpweb.services.custom_param_sharing import (
    VISIBILITY_PRIVATE,
    VISIBILITY_PROJECT,
    VISIBILITY_PUBLIC,
    apply_upload_sharing,
    column_rows,
    delete_column,
    label_shared_columns,
    name_conflicts,
    uploaded_column_names,
    visibility_choices,
)
from tpweb.services.score_params import visible_score_params_queryset

GENOME = "SHARETEST"
OTHER_GENOME = "SHAREOTHER"


class UploadedColumnNamesTests(SimpleTestCase):
    def test_reads_header_after_gene_and_rewinds(self):
        upload = SimpleUploadedFile("data.tsv", b"gene\tscore_a\tscore_b\nP1\t1\t2\n")
        self.assertEqual(uploaded_column_names(upload), ["score_a", "score_b"])
        self.assertEqual(upload.read(4), b"gene")

    def test_csv_uses_comma(self):
        upload = SimpleUploadedFile("data.csv", b"gene,essential\nP1,yes\n")
        self.assertEqual(uploaded_column_names(upload), ["essential"])


class CustomParamFormSharingTests(SimpleTestCase):
    def _form(self, visibility, description=""):
        upload = SimpleUploadedFile("data.tsv", b"gene\tx\nP1\t1\n")
        return CustomParamForm(
            {"visibility": visibility, "description": description}, {"tsv": upload}
        )

    def test_sharing_requires_a_description(self):
        form = self._form(VISIBILITY_PUBLIC)
        self.assertFalse(form.is_valid())
        self.assertIn("description", form.errors)

    def test_private_upload_needs_no_description(self):
        self.assertTrue(self._form(VISIBILITY_PRIVATE).is_valid())


class SharingFixture:
    def setUp(self):
        user_model = get_user_model()
        self.owner = user_model.objects.create_user("owner", password="x")
        self.basic = user_model.objects.create_user("basic", password="x")
        self.member = user_model.objects.create_user("member", password="x")
        self.member.user_permissions.add(
            Permission.objects.get(
                content_type__app_label="tpweb", codename="can_view_restricted_genomes"
            )
        )
        self.member = user_model.objects.get(pk=self.member.pk)

        proteome = Biodatabase.objects.create(name=GENOME + "_prots")
        self.protein = Bioentry.objects.create(
            biodatabase=proteome, name="P1", accession="P1", identifier="P1"
        )
        other_proteome = Biodatabase.objects.create(name=OTHER_GENOME + "_prots")
        self.other_protein = Bioentry.objects.create(
            biodatabase=other_proteome, name="Q1", accession="Q1", identifier="Q1"
        )
        self.param = self._custom_param(self.owner, "lab_score", self.protein)

    def _custom_param(self, user, name, protein):
        param = ScoreParam.objects.create(
            category="Custom",
            name=name,
            type="N",
            default_operation=">=",
            default_value="0",
            user=user,
        )
        ScoreParamValue.objects.create(score_param=param, bioentry=protein, value="1")
        return param

    def _visible(self, user, genome_name=GENOME):
        return set(
            visible_score_params_queryset(user, genome_name=genome_name).values_list(
                "pk", flat=True
            )
        )


class CustomParamSharingTests(SharingFixture, TestCase):
    def test_private_column_is_only_visible_to_its_owner(self):
        self.assertIn(self.param.pk, self._visible(self.owner))
        self.assertNotIn(self.param.pk, self._visible(self.member))
        self.assertNotIn(self.param.pk, self._visible(self.basic))

    def test_public_column_reaches_every_user_on_that_genome_only(self):
        apply_upload_sharing(self.owner, GENOME, ["lab_score"], VISIBILITY_PUBLIC, "Lab assay")
        self.assertIn(self.param.pk, self._visible(self.basic))
        self.assertIn(self.param.pk, self._visible(self.member))
        self.assertNotIn(self.param.pk, self._visible(self.basic, OTHER_GENOME))
        self.param.refresh_from_db()
        self.assertEqual(self.param.description, "Lab assay")

    def test_project_column_is_hidden_from_basic_users(self):
        apply_upload_sharing(self.owner, GENOME, ["lab_score"], VISIBILITY_PROJECT, "Lab assay")
        self.assertIn(self.param.pk, self._visible(self.member))
        self.assertNotIn(self.param.pk, self._visible(self.basic))

    def test_public_on_a_restricted_genome_means_project_members(self):
        RestrictedGenome.objects.create(genome_name=GENOME)
        apply_upload_sharing(self.owner, GENOME, ["lab_score"], VISIBILITY_PUBLIC, "Lab assay")
        self.assertIn(self.param.pk, self._visible(self.member))
        self.assertNotIn(self.param.pk, self._visible(self.basic))
        self.assertEqual(len(visibility_choices(GENOME)), 2)

    def test_own_column_with_the_same_name_wins(self):
        apply_upload_sharing(self.owner, GENOME, ["lab_score"], VISIBILITY_PUBLIC, "Lab assay")
        own = self._custom_param(self.basic, "lab_score", self.protein)
        visible = self._visible(self.basic)
        self.assertIn(own.pk, visible)
        self.assertNotIn(self.param.pk, visible)

    def test_shared_name_conflicts_are_reported(self):
        apply_upload_sharing(self.owner, GENOME, ["lab_score"], VISIBILITY_PUBLIC, "Lab assay")
        self.assertEqual(name_conflicts(self.basic, GENOME, ["lab_score", "x"]), ["lab_score"])
        self.assertEqual(name_conflicts(self.owner, GENOME, ["lab_score"]), [])
        self.assertEqual(name_conflicts(self.basic, OTHER_GENOME, ["lab_score"]), [])

    def test_going_private_again_removes_the_share(self):
        apply_upload_sharing(self.owner, GENOME, ["lab_score"], VISIBILITY_PUBLIC, "Lab assay")
        apply_upload_sharing(self.owner, GENOME, ["lab_score"], VISIBILITY_PRIVATE)
        self.assertFalse(CustomParamShare.objects.exists())
        self.assertNotIn(self.param.pk, self._visible(self.basic))

    def test_deleting_the_column_removes_it_for_everyone(self):
        apply_upload_sharing(self.owner, GENOME, ["lab_score"], VISIBILITY_PUBLIC, "Lab assay")
        self.assertFalse(delete_column(self.param, GENOME, self.basic))
        self.assertTrue(delete_column(self.param, GENOME, self.owner))
        self.assertFalse(ScoreParam.objects.filter(pk=self.param.pk).exists())
        self.assertFalse(CustomParamShare.objects.exists())

    def test_delete_on_one_genome_keeps_the_others(self):
        ScoreParamValue.objects.create(
            score_param=self.param, bioentry=self.other_protein, value="2"
        )
        self.assertTrue(delete_column(self.param, GENOME, self.owner))
        self.assertTrue(ScoreParam.objects.filter(pk=self.param.pk).exists())
        rows = column_rows([self.param])
        self.assertEqual([row["genome_name"] for row in rows], [OTHER_GENOME])

    def test_shared_columns_are_labeled_with_their_owner(self):
        apply_upload_sharing(self.owner, GENOME, ["lab_score"], VISIBILITY_PUBLIC, "Lab assay")
        params = list(
            visible_score_params_queryset(self.basic, genome_name=GENOME)
            .filter(pk=self.param.pk)
            .select_related("user")
        )
        label_shared_columns(params, self.basic)
        self.assertEqual(params[0].category, "Shared by users")
        self.assertEqual(params[0].description, "Shared by owner. Lab assay")


class SettingsFormulaListTests(TestCase):
    def test_untouched_copies_of_the_built_in_formulas_are_left_out(self):
        from tpweb.models.ScoreFormula import ScoreFormula
        from tpweb.services.visibility_settings import formulas_owned_by
        from tpweb.services.workspace import get_public_workspace_user

        user = get_user_model().objects.create_user("student", password="x")
        ScoreFormula.objects.update_or_create(
            name="Druggability",
            user=get_public_workspace_user(),
            defaults={"expression": "Druggability"},
        )
        ScoreFormula.objects.get_or_create(name="Localization", user=get_public_workspace_user())
        ScoreFormula.objects.create(name="Druggability", user=user, expression="Druggability")
        ScoreFormula.objects.create(name="Localization", user=user, expression="")
        ScoreFormula.objects.create(name="My score", user=user, expression="Druggability * 2")

        self.assertEqual([f.name for f in formulas_owned_by(user)], ["My score"])


class PrivateColumnLeakTests(SharingFixture, TestCase):
    def test_a_formula_naming_someone_elses_private_column_does_not_read_it(self):
        from tpweb.services.formula_evaluator import (
            build_all_options_zero,
            build_expression_variables,
        )

        protein = Bioentry.objects.prefetch_related("score_params__score_param").get(
            pk=self.protein.pk
        )
        variables = build_expression_variables(protein, build_all_options_zero(self.basic))
        self.assertNotIn("lab_score", variables)
        owner_variables = build_expression_variables(protein, build_all_options_zero(self.owner))
        self.assertEqual(owner_variables["lab_score"], 1.0)

    def test_upload_names_matching_built_in_columns_are_reported(self):
        from tpweb.services.custom_param_sharing import built_in_name_conflicts

        ScoreParam.objects.get_or_create(
            category="Pocket",
            name="Druggability",
            user=None,
            defaults={"type": "N", "default_operation": ">=", "default_value": "0"},
        )
        self.assertEqual(built_in_name_conflicts(["Druggability", "lab_score"]), ["Druggability"])


class OwnerOnlySharingTests(SharingFixture, TestCase):
    def test_a_superuser_cannot_change_or_delete_someone_elses_column(self):
        from tpweb.services.custom_param_sharing import update_column_visibility

        admin = get_user_model().objects.create_superuser("boss", password="x")
        self.assertFalse(update_column_visibility(self.param, GENOME, admin, VISIBILITY_PUBLIC))
        self.assertFalse(delete_column(self.param, GENOME, admin))
        self.assertTrue(update_column_visibility(self.param, GENOME, self.owner, VISIBILITY_PUBLIC))

    def test_a_superuser_cannot_change_someone_elses_formula(self):
        from tpweb.models.ScoreFormula import ScoreFormula
        from tpweb.services.visibility_settings import set_formula_visibility

        admin = get_user_model().objects.create_superuser("boss", password="x")
        formula = ScoreFormula.objects.create(name="Mine", user=self.owner, expression="1")
        self.assertFalse(set_formula_visibility(formula, admin, "public"))
        formula.refresh_from_db()
        self.assertFalse(formula.public)


class IdentifierLabelTests(SimpleTestCase):
    def test_locus_tags_and_accessions_are_not_humanized(self):
        from tpweb.services.protein_list import humanize_identifier

        self.assertEqual(humanize_identifier("KPN_00002"), "KPN_00002")
        self.assertEqual(humanize_identifier("MGH78578_locus_tag"), "MGH78578_locus_tag")
        self.assertEqual(humanize_identifier("no_hit"), "No hit")


class FilterValuesTests(SharingFixture, TestCase):
    def test_typed_values_resolve_to_options_ignoring_case(self):
        from tpweb.models.ScoreParam import ScoreParamOptions
        from tpweb.services.protein_list import resolve_filter_values

        tag_param = ScoreParam.objects.create(
            category="Custom",
            name="locus_map",
            type="C",
            default_operation="=",
            default_value="",
            user=self.owner,
        )
        first = ScoreParamOptions.objects.create(score_param=tag_param, name="KPN_00002")
        second = ScoreParamOptions.objects.create(score_param=tag_param, name="KPN_00003")

        option_ids, missing = resolve_filter_values(
            self.owner, str(tag_param.pk), "kpn_00002, KPN_00003\nKPN_99999"
        )
        self.assertEqual(option_ids, [first.pk, second.pk])
        self.assertEqual(missing, ["KPN_99999"])

        option_ids, missing = resolve_filter_values(self.basic, str(tag_param.pk), "KPN_00002")
        self.assertEqual(option_ids, [])

    def test_suggestions_match_prefix_first_then_contains(self):
        from tpweb.models.ScoreParam import ScoreParamOptions
        from tpweb.services.protein_list import suggest_filter_values

        tag_param = ScoreParam.objects.create(
            category="Custom",
            name="locus_map_suggest",
            type="C",
            default_operation="=",
            default_value="",
            user=self.owner,
        )
        for name in ["KPN_00002", "KPN_00020", "ABC_KPN_0002", "XYZ_1"]:
            ScoreParamOptions.objects.create(score_param=tag_param, name=name)

        # Prefix matches first (alphabetical), then values that only contain it.
        self.assertEqual(
            suggest_filter_values(self.owner, str(tag_param.pk), "kpn_0002"),
            ["KPN_00020", "ABC_KPN_0002"],
        )
        self.assertEqual(
            suggest_filter_values(self.owner, str(tag_param.pk), "kpn_000"),
            ["KPN_00002", "KPN_00020", "ABC_KPN_0002"],
        )
        # Someone who can't read the column gets nothing.
        self.assertEqual(suggest_filter_values(self.basic, str(tag_param.pk), "kpn"), [])


class UploadedDataPageTests(SharingFixture, TestCase):
    def setUp(self):
        super().setUp()
        Biodatabase.objects.create(name=GENOME, description="Genome workspace")

    def test_lists_own_column_and_downloads_it(self):
        from django.urls import reverse

        self.client.force_login(self.owner)
        response = self.client.get(reverse("tpwebapp:uploaded_data", kwargs={"genome": GENOME}))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "lab_score")

        response = self.client.get(
            reverse(
                "tpwebapp:uploaded_data_download",
                kwargs={"genome": GENOME, "param_id": self.param.pk},
            )
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content.decode(), "gene\tlab_score\nP1\t1\n")

    def test_private_column_is_not_downloadable_by_others(self):
        from django.urls import reverse

        self.client.force_login(self.basic)
        response = self.client.get(
            reverse(
                "tpwebapp:uploaded_data_download",
                kwargs={"genome": GENOME, "param_id": self.param.pk},
            )
        )
        self.assertEqual(response.status_code, 404)


class BlastTabularTests(SimpleTestCase):
    def test_parses_outfmt6_rows(self):
        from tpweb.views.NewView import parse_blast_tabular

        raw = "q1\tPA0001\t99.5\t300\t1\t0\t1\t300\t10\t309\t1e-150\t540\nbad line\n"
        hits = parse_blast_tabular(raw)
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0]["subject_id"], "PA0001")
        self.assertEqual(hits[0]["evalue"], "1e-150")


class FormulaReadabilityTests(SimpleTestCase):
    def test_formula_reads_in_words(self):
        from tpweb.services.protein_formula import readable_formula

        text = readable_formula(
            "druggability + 2 * hit_in_deg_y - human_offtarget_hit",
            ["druggability", "hit_in_deg", "human_offtarget"],
        )
        self.assertEqual(
            text,
            "Druggability (FPocket, 0–1) + 2 × (Essential homolog (DEG) is Yes)"
            " − (Human off-target is Hit)",
        )

    def test_numeric_variables_name_their_scale(self):
        from tpweb.services.formula_evaluator import numeric_variable_scale

        self.assertEqual(numeric_variable_scale("human_identity"), "%")
        self.assertEqual(numeric_variable_scale("p2rank_probability"), "0–1")
        self.assertEqual(numeric_variable_scale("colabfold_plddt"), "0–100")
        self.assertEqual(numeric_variable_scale("human_evalue"), "e-value")
        self.assertEqual(numeric_variable_scale("n_reactions"), "count")
        self.assertEqual(numeric_variable_scale("lab_score"), "")


class BindersPanelsViewTests(TestCase):
    def test_renders_the_ligand_panels_for_a_visible_protein(self):
        from django.urls import reverse

        proteome = Biodatabase.objects.create(name="LAZYTEST_prots")
        protein = Bioentry.objects.create(
            biodatabase=proteome, name="P1", accession="P1", identifier="P1"
        )
        self.client.force_login(get_user_model().objects.create_user("viewer", password="x"))
        response = self.client.get(
            reverse("tpwebapp:protein_binders_panels", kwargs={"protein_id": protein.pk})
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'data-binders-panel="pdb_direct"')

    def test_non_protein_bioentry_is_not_found(self):
        from django.urls import reverse

        genome = Biodatabase.objects.create(name="LAZYTEST")
        record = Bioentry.objects.create(
            biodatabase=genome, name="chr", accession="chr", identifier="chr"
        )
        self.client.force_login(get_user_model().objects.create_user("viewer2", password="x"))
        response = self.client.get(
            reverse("tpwebapp:protein_binders_panels", kwargs={"protein_id": record.pk})
        )
        self.assertEqual(response.status_code, 404)
