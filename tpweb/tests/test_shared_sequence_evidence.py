from types import SimpleNamespace
from unittest.mock import patch

from django.db.models import Q
from django.test import TestCase
from bioseq.models.Biodatabase import Biodatabase
from bioseq.models.Bioentry import Bioentry
from bioseq.models.Dbxref import Dbxref
from bioseq.models.BioentryDbxref import BioentryDbxref
from tpweb.models.IdenticalSequence import IdenticalSequenceGroup, IdenticalSequenceMember
from tpweb.models.BioentryStructure import BioentryStructure
from tpweb.models.ScoreParam import ScoreParam
from tpweb.models.ScoreParamValue import ScoreParamValue
from tpweb.models.pdb import PDB
from tpweb.models.Binders import Binders
from tpweb.services.shared_sequence_evidence import (
    _sequence,
    apply_shared_sequence_evidence,
    shared_structure_link,
    annotate_shared_score_values,
    inherited_score_param_ids,
)


class SharedSequenceEvidenceTests(TestCase):
    def test_colabfold_score_does_not_mix_in_automatic_pocket_id(self):
        for anchor, pocket in (
            ("colabfold_p2rank_probability", "colabfold_p2rank_pocket"),
            ("colabfold_druggability_score", "colabfold_fpocket_pocket"),
        ):
            param = ScoreParam.objects.create(
                name=anchor, category="Pocket", type="N", default_operation=">=", default_value="0"
            )
            reference = ScoreParam.objects.create(
                name=pocket, category="Pocket", type="C", default_operation="=", default_value=""
            )
            self.value(self.curated, 0.8, param=param)
            ScoreParamValue.objects.create(bioentry=self.target, score_param=reference, value="4")
            protein = self.fresh()
            apply_shared_sequence_evidence([protein], self.user)
            self.assertNotIn(pocket, [row.score_param.name for row in protein.score_params.all()])

    def test_column_coverage_reports_empty_columns_and_live_shared_values_in_order(self):
        import csv
        from io import StringIO
        from tpweb.management.commands.protein_column_coverage import Command

        self.user.username = "coverage-test"
        self.value(self.curated, 0)
        self.value(self.target, 0.2)
        ScoreParam.objects.create(
            name="empty_column",
            category="Test",
            type="N",
            default_operation=">=",
            default_value="0",
        )
        users = SimpleNamespace(objects=SimpleNamespace(filter=lambda *args: [self.user]))
        output = StringIO()
        with patch("django.contrib.auth.get_user_model", return_value=users):
            Command(stdout=output, stderr=StringIO()).handle(
                genome_name=self.target.biodatabase.name.removesuffix(Biodatabase.PROT_POSTFIX),
                user="coverage-test",
            )
        rows = list(csv.DictReader(StringIO(output.getvalue()), delimiter="\t"))
        counts = [int(row["Con_datos"]) for row in rows]
        self.assertEqual(counts, sorted(counts))
        by_name = {row["Columna"]: row for row in rows}
        self.assertEqual(by_name["empty_column"]["Con_datos"], "0")
        row = by_name[self.param.name]
        self.assertEqual((row["Con_datos"], row["Locales"], row["Compartidos"]), ("1", "1", "1"))
        self.assertEqual(row["Total"], "1")

    def setUp(self):
        self.user = SimpleNamespace()
        self.allowed = set()
        self.user.allowed = self.allowed
        self.private_ids = set()
        self.sequences = {}
        self.group = IdenticalSequenceGroup.objects.create(source_note="secuencias_unicas_ids.tsv")
        self.curated = self.protein("KP13", "KP13_1")
        self.target = self.protein("ST11_VA569", "MO417_1")
        self.param = ScoreParam.objects.create(
            name="p2rank_probability",
            category="Pocket",
            type="N",
            default_operation=">=",
            default_value="0",
        )
        self.start_patch(
            "tpweb.services.genome_workspace.user_can_access_genome_name",
            side_effect=lambda user, genome: genome in self.allowed,
        )
        self.start_patch(
            "tpweb.services.score_params.score_param_visibility_filter",
            side_effect=lambda user, genome: ~Q(pk__in=self.private_ids),
        )
        # Sequence storage belongs to the external bioseq package; keep these
        # ORM tests independent of its FASTA/sequence-loading machinery.
        self.start_patch(
            "tpweb.services.shared_sequence_evidence._sequence",
            side_effect=lambda p: self.sequences[p.pk],
        )

    def start_patch(self, target, **kwargs):
        patcher = patch(target, **kwargs)
        self.addCleanup(patcher.stop)
        return patcher.start()

    def protein(self, strain, locus):
        genome_name = f"public__test_{strain}"
        database, _ = Biodatabase.objects.get_or_create(name=genome_name + Biodatabase.PROT_POSTFIX)
        protein = Bioentry.objects.create(
            biodatabase=database, accession=locus, name=locus, identifier=locus
        )
        sequence_relation = Bioentry._meta.get_field("seq")
        sequence_model = sequence_relation.related_model
        available = {f.name for f in sequence_model._meta.fields}
        sequence_fields = {
            k: v
            for k, v in {"seq": "MAU", "length": 3, "version": 1, "alphabet": "protein"}.items()
            if k in available
        }
        if sequence_relation.auto_created:
            sequence_model.objects.create(bioentry=protein, **sequence_fields)
        else:
            protein.seq = sequence_model.objects.create(**sequence_fields)
            protein.save(update_fields=["seq"])
        IdenticalSequenceMember.objects.create(
            group=self.group,
            strain_label=strain,
            locus_tag=locus,
            bioentry=protein,
        )
        self.sequences[protein.pk] = "MAU"
        self.allowed.add(genome_name)
        return protein

    def value(self, protein, value, param=None):
        return ScoreParamValue.objects.create(
            bioentry=protein,
            score_param=param or self.param,
            value=str(value),
            numeric_value=float(value),
        )

    def fresh(self, protein=None):
        return Bioentry.objects.select_related("biodatabase").get(pk=(protein or self.target).pk)

    def test_identical_protein_shows_the_curated_product_name_without_saving_it(self):
        Bioentry.objects.filter(pk=self.curated.pk).update(
            description="Chromosomal replication initiator protein dnaA"
        )
        Bioentry.objects.filter(pk=self.target.pk).update(
            description="chromosomal replication initiator protein DnaA"
        )
        protein = self.fresh()
        apply_shared_sequence_evidence([protein], self.user)
        self.assertEqual(protein.description, "Chromosomal replication initiator protein dnaA")
        self.assertEqual(
            protein.shared_sequence_evidence.local_description,
            "chromosomal replication initiator protein DnaA",
        )
        self.assertEqual(
            Bioentry.objects.get(pk=self.target.pk).description,
            "chromosomal replication initiator protein DnaA",
        )

    def test_score_sources_name_the_strain_each_shared_value_came_from(self):
        self.value(self.curated, 0.9)
        protein = self.fresh()
        apply_shared_sequence_evidence([protein], self.user)
        self.assertEqual(protein.shared_sequence_evidence.score_sources, {self.param.name: "KP13"})

    def test_curated_value_overrides_pipeline_without_copying_rows(self):
        original = self.value(self.curated, 0.9)
        self.value(self.target, 0.2)
        protein = self.fresh()
        apply_shared_sequence_evidence([protein], self.user)
        selected = list(protein.score_params.all())
        self.assertEqual([row.pk for row in selected], [original.pk])
        self.assertEqual(
            ScoreParamValue.objects.filter(bioentry=self.target).get().numeric_value, 0.2
        )
        self.assertEqual(ScoreParamValue.objects.count(), 2)

    def test_source_update_is_visible_on_next_read(self):
        row = self.value(self.curated, 0.9)
        first = self.fresh()
        apply_shared_sequence_evidence([first], self.user)
        row.value, row.numeric_value = ".95", 0.95
        row.save()
        second = self.fresh()
        apply_shared_sequence_evidence([second], self.user)
        self.assertEqual(list(second.score_params.all())[0].numeric_value, 0.95)

    def test_conservation_is_shared_from_the_curated_strain(self):
        self.param.name = "soft_core_roary"
        self.param.category = "Conservation"
        self.param.save()
        curated = self.value(self.curated, 1)
        self.value(self.target, 0)
        protein = self.fresh()
        apply_shared_sequence_evidence([protein], self.user)
        self.assertEqual(list(protein.score_params.all())[0].pk, curated.pk)

    def test_ranking_pass_with_light_rows_picks_the_same_curated_value(self):
        from tpweb.services.shared_sequence_evidence import attach_score_rows

        original = self.value(self.curated, 0.9)
        self.value(self.target, 0.2)
        protein = self.fresh()
        attach_score_rows([protein], {self.param.name})
        apply_shared_sequence_evidence(
            [protein], self.user, details=False, score_param_names={self.param.name}
        )
        rows = list(protein.score_params.all())
        self.assertEqual([(row.pk, row.numeric_value) for row in rows], [(original.pk, 0.9)])
        self.assertEqual(rows[0].score_param.name, self.param.name)

    def test_zero_curated_value_does_not_fall_back_to_automatic(self):
        self.value(self.curated, 0)
        self.value(self.target, 0.8)
        protein = self.fresh()
        apply_shared_sequence_evidence([protein], self.user)
        self.assertEqual(list(protein.score_params.all())[0].numeric_value, 0)

    def test_curated_metabolic_priority_remains_local_in_display_filters_and_columns(self):
        self.param.name = "priority"
        self.param.category = "Metabolic priority (curated)"
        self.param.save()
        self.value(self.curated, 0.9)
        local = self.value(self.target, 0.2)
        protein = self.fresh()
        apply_shared_sequence_evidence([protein], self.user)
        self.assertEqual(list(protein.score_params.all())[0].pk, local.pk)
        query, shared_ids = annotate_shared_score_values(
            Bioentry.objects.filter(pk=protein.pk), [self.param.pk], self.user
        )
        self.assertEqual(shared_ids, set())
        self.assertEqual(query.get().pk, protein.pk)
        self.assertNotIn(
            self.param.pk,
            inherited_score_param_ids(
                self.target.biodatabase.name.removesuffix(Biodatabase.PROT_POSTFIX), self.user
            ),
        )

    def test_missing_metabolic_priority_is_not_filled_from_another_strain(self):
        self.param.name = "n_reactions"
        self.param.category = "Metabolic priority (curated)"
        self.param.save()
        self.value(self.curated, 4)
        protein = self.fresh()
        apply_shared_sequence_evidence([protein], self.user)
        self.assertEqual(list(protein.score_params.all()), [])

    def test_missing_curated_value_keeps_automatic_fallback(self):
        ScoreParamValue.objects.create(bioentry=self.curated, score_param=self.param, value="")
        local = self.value(self.target, 0.4)
        protein = self.fresh()
        apply_shared_sequence_evidence([protein], self.user)
        self.assertEqual(list(protein.score_params.all())[0].pk, local.pk)

    def test_mismatched_current_sequence_is_not_shared(self):
        self.sequences[self.curated.pk] = "MAX"
        self.value(self.curated, 0.9)
        local = self.value(self.target, 0.1)
        protein = self.fresh()
        apply_shared_sequence_evidence([protein], self.user)
        self.assertEqual(protein.shared_sequence_evidence.siblings, [])
        self.assertEqual(list(protein.score_params.all())[0].pk, local.pk)

    def test_inaccessible_strain_is_not_exposed(self):
        self.allowed.remove("public__test_KP13")
        self.value(self.curated, 0.9)
        protein = self.fresh()
        apply_shared_sequence_evidence([protein], self.user)
        self.assertEqual(protein.shared_sequence_evidence.sources, [])
        self.assertEqual(protein.shared_sequence_evidence.siblings, [])
        self.assertEqual(list(protein.score_params.all()), [])

    def test_private_source_column_is_not_inherited(self):
        self.private_ids.add(self.param.pk)
        self.value(self.curated, 0.9)
        protein = self.fresh()
        apply_shared_sequence_evidence([protein], self.user)
        self.assertEqual(list(protein.score_params.all()), [])

    def test_structure_is_the_original_shared_object(self):
        pdb = PDB.objects.create(code="TESTEX", experiment="EX")
        origin = BioentryStructure.objects.create(bioentry=self.curated, pdb=pdb, chain="AA")
        protein = self.fresh()
        apply_shared_sequence_evidence([protein], self.user)
        self.assertEqual(list(protein.structures.all())[0].pk, origin.pk)
        self.assertFalse(BioentryStructure.objects.filter(bioentry=self.target).exists())
        self.assertEqual(shared_structure_link(self.user, self.target.pk, pdb.pk).pk, origin.pk)

    def test_structure_uploaded_to_new_strain_is_visible_from_curated_strain(self):
        pdb = PDB.objects.create(code="new-strain-model", experiment="CF")
        origin = BioentryStructure.objects.create(bioentry=self.target, pdb=pdb)
        protein = self.fresh(self.curated)
        apply_shared_sequence_evidence([protein], self.user)
        self.assertIn(origin.pk, [s.pk for s in protein.structures.all()])
        self.assertEqual(shared_structure_link(self.user, protein.pk, pdb.pk).pk, origin.pk)

    def test_new_strain_score_fills_missing_curated_value_in_both_display_and_filter(self):
        original = self.value(self.target, 0.7)
        protein = self.fresh(self.curated)
        apply_shared_sequence_evidence([protein], self.user)
        self.assertEqual(list(protein.score_params.all())[0].pk, original.pk)
        query, _ = annotate_shared_score_values(
            Bioentry.objects.filter(pk=protein.pk), [self.param.pk], self.user
        )
        self.assertEqual(
            list(query.values_list(f"_shared_score_{self.param.pk}_numeric_value", flat=True)),
            [0.7],
        )

    def test_unrelated_structure_id_is_rejected(self):
        pdb = PDB.objects.create(code="UNRELATED", experiment="EX")
        self.assertIsNone(shared_structure_link(self.user, self.target.pk, pdb.pk))

    def test_conflicting_curated_values_have_stable_precedence_and_notice(self):
        other = self.protein("ATCC43816", "VK055_1")
        self.value(other, 0.7)
        kp13 = self.value(self.curated, 0.9)
        protein = self.fresh()
        apply_shared_sequence_evidence([protein], self.user)
        self.assertEqual(list(protein.score_params.all())[0].pk, kp13.pk)
        self.assertEqual(protein.shared_sequence_evidence.conflicts, [self.param.name])

    def test_actual_sequence_reader_preserves_selenocysteine(self):
        self.assertEqual(_sequence(SimpleNamespace(seq=SimpleNamespace(seq="mau*"))), "MAU")
        self.assertNotEqual(_sequence(SimpleNamespace(seq=SimpleNamespace(seq="MAX"))), "MAU")

    def test_sql_filter_uses_curated_value_instead_of_automatic(self):
        self.value(self.curated, 0.9)
        self.value(self.target, 0.2)
        queryset, fields = annotate_shared_score_values(
            Bioentry.objects.filter(pk=self.target.pk), {self.param.pk}, self.user
        )
        self.assertEqual(fields, {self.param.pk})
        lookup = f"_shared_score_{self.param.pk}_numeric_value__gte"
        self.assertTrue(queryset.filter(**{lookup: 0.8}).exists())
        self.assertFalse(queryset.filter(**{lookup: 0.95}).exists())

    def test_sql_filter_does_not_expose_inaccessible_donor(self):
        self.value(self.curated, 0.9)
        self.value(self.target, 0.2)
        self.allowed.remove("public__test_KP13")
        queryset, _ = annotate_shared_score_values(
            Bioentry.objects.filter(pk=self.target.pk), {self.param.pk}, self.user
        )
        self.assertFalse(
            queryset.filter(**{f"_shared_score_{self.param.pk}_numeric_value__gte": 0.8}).exists()
        )

    def test_sql_filter_rejects_changed_donor_sequence(self):
        self.value(self.curated, 0.9)
        self.value(self.target, 0.2)
        sequence = self.curated.seq
        sequence.seq = "MAX"
        sequence.save()
        queryset, _ = annotate_shared_score_values(
            Bioentry.objects.filter(pk=self.target.pk), {self.param.pk}, self.user
        )
        self.assertFalse(
            queryset.filter(**{f"_shared_score_{self.param.pk}_numeric_value__gte": 0.8}).exists()
        )

    def test_sql_filter_shares_conservation(self):
        self.param.category = "Conservation"
        self.param.save()
        _, fields = annotate_shared_score_values(Bioentry.objects.all(), {self.param.pk}, self.user)
        self.assertNotEqual(fields, set())

    def test_curated_pocket_score_does_not_inherit_automatic_pocket_reference(self):
        self.value(self.curated, 0.9)
        reference = ScoreParam.objects.create(
            name="best_p2rank_structure",
            category="Pocket",
            type="C",
            default_operation="=",
            default_value="",
        )
        ScoreParamValue.objects.create(
            bioentry=self.target, score_param=reference, value="AUTOMATIC_MODEL"
        )
        protein = self.fresh()
        apply_shared_sequence_evidence([protein], self.user)
        self.assertNotIn(
            "best_p2rank_structure", [r.score_param.name for r in protein.score_params.all()]
        )

    def test_numeric_filter_matches_the_displayed_shared_value(self):
        from tpweb.services.protein_list import apply_selected_parameter_filters

        self.value(self.curated, 0.9)
        self.value(self.target, 0.2)
        condition = {
            "type": "numeric",
            "score_param_id": self.param.pk,
            "operation": ">=",
            "value": 0.8,
        }
        queryset = apply_selected_parameter_filters(
            Bioentry.objects.filter(pk=self.target.pk), [condition], self.user
        )
        self.assertTrue(queryset.exists())

    def test_experimental_filter_includes_curated_pdb_and_predicted_model(self):
        from tpweb.services.protein_list import apply_selected_parameter_filters

        for code, experiment in (("TESTEX", "EX"), ("TESTCF", "CF")):
            pdb = PDB.objects.create(code=code, experiment=experiment)
            BioentryStructure.objects.create(bioentry=self.curated, pdb=pdb)
        condition = {
            "type": "special",
            "special_key": "structure_source",
            "special_value": "experimental",
        }
        queryset = apply_selected_parameter_filters(
            Bioentry.objects.filter(pk=self.target.pk), [condition], self.user
        )
        self.assertTrue(queryset.exists())

    def test_no_structure_filter_excludes_a_shared_structure(self):
        from tpweb.services.protein_list import apply_selected_parameter_filters

        pdb = PDB.objects.create(code="TESTEX", experiment="EX")
        BioentryStructure.objects.create(bioentry=self.curated, pdb=pdb)
        condition = {"type": "special", "special_key": "structure_source", "special_value": "none"}
        queryset = apply_selected_parameter_filters(
            Bioentry.objects.filter(pk=self.target.pk), [condition], self.user
        )
        self.assertFalse(queryset.exists())

    def test_structure_filter_does_not_reveal_inaccessible_donor(self):
        from tpweb.services.protein_list import apply_selected_parameter_filters

        pdb = PDB.objects.create(code="TESTEX", experiment="EX")
        BioentryStructure.objects.create(bioentry=self.curated, pdb=pdb)
        self.allowed.remove("public__test_KP13")
        condition = {
            "type": "special",
            "special_key": "structure_source",
            "special_value": "experimental",
        }
        queryset = apply_selected_parameter_filters(
            Bioentry.objects.filter(pk=self.target.pk), [condition], self.user
        )
        self.assertFalse(queryset.exists())

    def test_new_strain_joins_existing_table_group_by_exact_sequence(self):
        from tpweb.management.commands.backfill_identical_sequence_links import (
            _link_new_strain_sequences,
        )

        new = self.protein("NEW_STRAIN", "NEW_1")
        IdenticalSequenceMember.objects.filter(bioentry=new).delete()
        original = self.value(self.curated, 0.9)
        self.assertEqual(_link_new_strain_sequences(new.biodatabase, "NEW_STRAIN"), 1)
        self.assertEqual(IdenticalSequenceGroup.objects.count(), 1)
        member = IdenticalSequenceMember.objects.get(bioentry=new)
        self.assertEqual(member.group_id, self.group.pk)
        protein = self.fresh(new)
        apply_shared_sequence_evidence([protein], self.user)
        self.assertEqual(list(protein.score_params.all())[0].pk, original.pk)
        self.assertEqual(_link_new_strain_sequences(new.biodatabase, "NEW_STRAIN"), 0)

    def test_new_strain_starts_a_group_with_an_ungrouped_curated_protein(self):
        from tpweb.management.commands.backfill_identical_sequence_links import (
            _link_new_strain_sequences,
        )

        lone = self.protein("KP13", "KP13_2")
        IdenticalSequenceMember.objects.filter(bioentry=lone).delete()
        for protein in (self.curated, self.target):
            sequence = protein.seq
            sequence.seq = "MXX"
            sequence.save()
        new = self.protein("NEW_STRAIN", "NEW_1")
        IdenticalSequenceMember.objects.filter(bioentry=new).delete()
        self.assertEqual(_link_new_strain_sequences(new.biodatabase, "NEW_STRAIN"), 1)
        member = IdenticalSequenceMember.objects.get(bioentry=new)
        self.assertEqual(
            set(member.group.members.values_list("strain_label", "locus_tag")),
            {("KP13", "KP13_2"), ("NEW_STRAIN", "NEW_1")},
        )
        self.assertEqual(_link_new_strain_sequences(new.biodatabase, "NEW_STRAIN"), 0)

    def test_pipeline_reuses_only_evidence_the_curated_copy_has(self):
        from tpweb.services.shared_sequence_evidence import loci_covered_by_curated_copy

        genome = "public__test_ST11_VA569"
        self.assertEqual(loci_covered_by_curated_copy(genome, "structure"), set())
        BioentryStructure.objects.create(
            bioentry=self.curated, pdb=PDB.objects.create(code="AFTEST", experiment="AF")
        )
        self.assertEqual(loci_covered_by_curated_copy(genome, "structure"), {"MO417_1"})
        self.assertEqual(loci_covered_by_curated_copy(genome, "pockets"), set())
        self.value(self.curated, 0.7)
        self.assertEqual(loci_covered_by_curated_copy(genome, "pockets"), {"MO417_1"})
        self.allowed.remove("public__test_KP13")
        self.assertEqual(loci_covered_by_curated_copy(genome, "structure"), set())

    def test_new_strain_does_not_join_an_inconsistent_table_group(self):
        from tpweb.management.commands.backfill_identical_sequence_links import (
            _link_new_strain_sequences,
        )

        new = self.protein("NEW_STRAIN", "NEW_1")
        IdenticalSequenceMember.objects.filter(bioentry=new).delete()
        sequence = self.curated.seq
        sequence.seq = "MAX"
        sequence.save()
        self.assertEqual(_link_new_strain_sequences(new.biodatabase, "NEW_STRAIN"), 0)
        self.assertFalse(IdenticalSequenceMember.objects.filter(bioentry=new).exists())

    def annotation(self, protein, accession):
        kwargs = {"dbname": "ec", "accession": accession}
        if "version" in {field.name for field in Dbxref._meta.fields}:
            kwargs["version"] = 0
        xref = Dbxref.objects.create(**kwargs)
        return BioentryDbxref.objects.create(bioentry=protein, dbxref=xref)

    def test_curated_function_replaces_automatic_annotations_in_that_namespace(self):
        original = self.annotation(self.curated, "1.1.1.1")
        automatic = self.annotation(self.target, "2.2.2.2")
        protein = self.fresh()
        apply_shared_sequence_evidence([protein], self.user)
        self.assertEqual([r.pk for r in protein.dbxrefs.all()], [original.pk])
        self.assertTrue(BioentryDbxref.objects.filter(pk=automatic.pk).exists())

    def test_function_filter_matches_curated_annotation_and_not_replaced_automatic(self):
        from tpweb.services.protein_list import apply_selected_parameter_filters

        self.annotation(self.curated, "1.1.1.1")
        self.annotation(self.target, "2.2.2.2")
        for value, expected in (("1", True), ("2", False)):
            condition = {"type": "special", "special_key": "ec_filter", "special_value": value}
            queryset = apply_selected_parameter_filters(
                Bioentry.objects.filter(pk=self.target.pk), [condition], self.user
            )
            self.assertEqual(queryset.exists(), expected)

    def test_function_filter_keeps_automatic_fallback_when_no_curated_function(self):
        from tpweb.services.protein_list import apply_selected_parameter_filters

        self.annotation(self.target, "2.2.2.2")
        condition = {"type": "special", "special_key": "ec_filter", "special_value": "2"}
        queryset = apply_selected_parameter_filters(
            Bioentry.objects.filter(pk=self.target.pk), [condition], self.user
        )
        self.assertTrue(queryset.exists())

    def test_canonical_go_namespace_is_shared_counted_and_filtered_consistently(self):
        from bioseq.models.Ontology import Ontology
        from tpweb.management.commands.protein_column_coverage import fixed_presence
        from tpweb.services.protein_list import apply_selected_parameter_filters

        dbxref = Dbxref.objects.create(dbname=Ontology.GO, accession="GO:0016020", version=0)
        original = BioentryDbxref.objects.create(bioentry=self.curated, dbxref=dbxref, rank=0)
        automatic_ref = Dbxref.objects.create(dbname="go", accession="GO:0022857", version=0)
        BioentryDbxref.objects.create(bioentry=self.target, dbxref=automatic_ref, rank=0)
        protein = self.fresh()
        protein.metabolic_reaction_count = 0
        apply_shared_sequence_evidence([protein], self.user)
        self.assertEqual([r.pk for r in protein.dbxrefs.all()], [original.pk])
        self.assertTrue(fixed_presence(protein)["GO"])
        for value, expected in (("GO:0016020", True), ("GO:0022857", False)):
            condition = {"type": "special", "special_key": "go_filter", "special_value": value}
            query = apply_selected_parameter_filters(
                Bioentry.objects.filter(pk=protein.pk), [condition], self.user
            )
            self.assertEqual(query.exists(), expected)

    def ligand(self, protein, name, kind="pdb"):
        return Binders.objects.create(
            locustag=protein,
            ccd_id=name,
            source=kind,
            smiles="CCO",
            is_direct=True,
        )

    def ligand_summary(self, protein):
        from tpweb.services.binder_summary import create_binders_dict

        apply_shared_sequence_evidence([protein], self.user)
        with (
            patch(
                "tpweb.services.binder_summary._binder_to_dto",
                side_effect=lambda row, *args: {"id": row.pk, "score": row.score},
            ),
            patch("tpweb.services.binder_summary._build_binder_summary", return_value=None),
        ):
            return create_binders_dict(protein, structures=[])

    def test_ligands_use_both_curated_strains_instead_of_automatic_category(self):
        other = self.protein("ATCC43816", "VK055_1")
        first = self.ligand(self.curated, "AAA")
        second = self.ligand(other, "BBB")
        self.ligand(self.target, "AUTOMATIC")
        summary = self.ligand_summary(self.fresh())
        self.assertEqual({row["id"] for row in summary["pdb_direct"]}, {first.pk, second.pk})
        self.assertEqual(Binders.objects.count(), 3)

    def test_ligand_category_without_curation_keeps_automatic_fallback(self):
        self.ligand(self.curated, "AAA")
        automatic = self.ligand(self.target, "ZINC1", "proposed")
        summary = self.ligand_summary(self.fresh())
        self.assertEqual([row["id"] for row in summary["zinc"]], [automatic.pk])

    def test_ligand_uploaded_to_new_strain_is_available_to_curated_strain(self):
        original = self.ligand(self.target, "NEW")
        summary = self.ligand_summary(self.fresh(self.curated))
        self.assertEqual([row["id"] for row in summary["pdb_direct"]], [original.pk])

    def test_identical_curated_ligand_records_are_not_displayed_twice(self):
        other = self.protein("ATCC43816", "VK055_1")
        self.ligand(self.curated, "AAA")
        self.ligand(other, "AAA")
        summary = self.ligand_summary(self.fresh())
        self.assertEqual(len(summary["pdb_direct"]), 1)
        self.assertTrue(summary["pdb_direct"][0]["shared_from_accession"])

    def test_inaccessible_curated_ligands_are_not_exposed(self):
        self.ligand(self.curated, "AAA")
        automatic = self.ligand(self.target, "AUTOMATIC")
        self.allowed.remove("public__test_KP13")
        summary = self.ligand_summary(self.fresh())
        self.assertEqual([row["id"] for row in summary["pdb_direct"]], [automatic.pk])

    def test_shared_parameter_is_available_even_without_local_value(self):
        self.value(self.curated, 0.9)
        ids = inherited_score_param_ids("public__test_ST11_VA569", self.user)
        self.assertIn(self.param.pk, ids)

    def test_private_shared_parameter_is_not_offered_as_a_column(self):
        self.value(self.curated, 0.9)
        self.private_ids.add(self.param.pk)
        ids = inherited_score_param_ids("public__test_ST11_VA569", self.user)
        self.assertNotIn(self.param.pk, ids)
