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


class CustomParamSharingTests(TestCase):
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
