from io import StringIO
from types import SimpleNamespace
from unittest.mock import patch
from pathlib import Path
from tempfile import TemporaryDirectory
import json

from django.test import TestCase, SimpleTestCase
from django.core.management.base import CommandError
from bioseq.models.Biodatabase import Biodatabase
from bioseq.models.Bioentry import Bioentry
from tpweb.models.BioentryStructure import BioentryStructure
from tpweb.models.ScoreParam import ScoreParam
from tpweb.models.ScoreParamValue import ScoreParamValue
from tpweb.models.pdb import (
    Atom,
    Residue,
    PDB,
    PDBResidueSet,
    ResidueSet,
    ResidueSetProperty,
    Property,
)
from tpweb.management.commands.index_colabfold_scores import Command as ColabFoldCommand
from tpweb.management.commands import index_pocket_consensus as consensus
from tpweb.management.commands import index_pocket_size_outlier as outlier
from tpweb.services.microbiome_counts import read_counts, read_normalization
from tpweb.management.commands.recover_microbiome_counts import Command as MicrobiomeCommand
from tpweb.management.commands.recover_cached_functional_annotations import matching_entries
from tpweb.management.commands.load_verified_colabfold_model import (
    model_sequence,
    Command as ModelCommand,
)


def write_model(path, names, chains=None):
    lines = []
    for index, name in enumerate(names):
        line = list(" " * 80)
        line[:6] = "ATOM  "
        line[12:16] = " CA "
        line[17:20] = name
        line[21] = chains[index] if chains else "A"
        line[22:26] = f"{index + 1:4d}"
        lines.append("".join(line))
    path.write_text("\n".join(lines), encoding="ascii")


class VerifiedModelParserTests(SimpleTestCase):
    def test_selenocysteine_is_preserved_in_model_sequence(self):
        with TemporaryDirectory() as temp:
            path = Path(temp) / "model.pdb"
            write_model(path, ["MET", "ALA", "SEC"])
            self.assertEqual(model_sequence(path), "MAU")

    def test_multichain_and_multimodel_inputs_are_rejected(self):
        with TemporaryDirectory() as temp:
            path = Path(temp) / "model.pdb"
            write_model(path, ["MET", "ALA"], chains=["A", "B"])
            with self.assertRaises(CommandError):
                model_sequence(path)
            path.write_text("MODEL        1\nMODEL        2\n", encoding="ascii")
            with self.assertRaises(CommandError):
                model_sequence(path)


def ensure_param(name):
    return ScoreParam.objects.get_or_create(
        name=name,
        category="Pocket",
        user=None,
        defaults={
            "type": "N" if name.startswith("colabfold_") else "C",
            "default_operation": "=",
            "default_value": "",
        },
    )[0]


class MicrobiomeCountParserTests(SimpleTestCase):
    def test_original_normalization_is_checked_against_counts(self):
        totals, fractions = read_normalization(
            {"A": 1469, "B": 0},
            StringIO("gene\ttotal\nA\t4744\nB\t4744\n"),
            StringIO("gene\tgut_microbiome_offtarget_norm\nA\t0.30965430016863404\nB\t0\n"),
        )
        self.assertEqual(totals, {"A": 4744, "B": 4744})
        self.assertEqual(fractions["B"], 0)

    def test_inconsistent_or_incomplete_normalization_is_rejected(self):
        for totals, fractions in (
            ("A\t4\n", "A\t0.3\n"),
            ("A\t0\n", "A\t0\n"),
            ("A\t4\n", "A\tnan\n"),
            ("A\t4\n", ""),
        ):
            with self.subTest(totals=totals, fractions=fractions), self.assertRaises(ValueError):
                read_normalization(
                    {"A": 1},
                    StringIO("gene\ttotal\n" + totals),
                    StringIO("gene\tgut_microbiome_offtarget_norm\n" + fractions),
                )

    def test_zero_and_integer_numeric_counts_are_retained(self):
        self.assertEqual(read_counts(StringIO("gene\tcounts\nA\t0\nB\t3.0\n")), {"A": 0, "B": 3})

    def test_invalid_counts_are_not_converted_to_no_hit(self):
        for value in ("", "nan", "inf", "-1", "0.5", "hit"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                read_counts(StringIO(f"gene\tcounts\nA\t{value}\n"))

    def test_unknown_loci_and_conflicting_duplicates_are_rejected(self):
        with self.assertRaises(ValueError):
            read_counts(StringIO("gene\tcounts\nOTHER\t1\n"), known_loci={"A"})
        with self.assertRaises(ValueError):
            read_counts(StringIO("gene\tcounts\nA\t1\nA\t2\n"))


class CachedAnnotationMatchingTests(SimpleTestCase):
    def test_only_active_exact_uniprot_sequences_are_reused(self):
        entry = {
            "primaryAccession": "TEST1",
            "entryType": "UniProtKB reviewed (Swiss-Prot)",
            "sequence": {"value": "MAU"},
        }
        with TemporaryDirectory() as temp:
            path = Path(temp) / "cache.json"
            path.write_text(
                json.dumps(
                    [
                        entry,
                        {**entry, "primaryAccession": "OTHER", "sequence": {"value": "MAX"}},
                        {**entry, "primaryAccession": "OLD", "inactiveReason": {"type": "DELETED"}},
                        {"uniParcId": "UPI_TEST", "sequence": {"value": "MAU"}},
                    ]
                ),
                encoding="utf-8",
            )
            self.assertEqual(matching_entries([path], {"MAU"}), [entry])

    def test_repeated_cached_entries_are_deduplicated(self):
        entry = {
            "primaryAccession": "TEST1",
            "entryType": "UniProtKB unreviewed (TrEMBL)",
            "sequence": {"value": "MAU"},
        }
        with TemporaryDirectory() as temp:
            path = Path(temp) / "cache.json"
            path.write_text(json.dumps([entry, entry]), encoding="utf-8")
            self.assertEqual(matching_entries([path, path], {"MAU"}), [entry])

    def test_unexpected_cache_shape_is_rejected(self):
        with TemporaryDirectory() as temp:
            path = Path(temp) / "cache.json"
            path.write_text("{}", encoding="utf-8")
            with self.assertRaises(ValueError):
                matching_entries([path], {"MAU"})


class ConsensusGeometryTests(SimpleTestCase):
    def verdict(self, fp=None, p2=None, chain="A"):
        fp = [SimpleNamespace(druggability=0.8, geometric_center=(0, 0, 0))] if fp is None else fp
        p2 = (
            [SimpleNamespace(name="1", probability=0.8, geometric_center=(1, 0, 0))]
            if p2 is None
            else p2
        )
        with patch.object(
            consensus, "pdb_structure", return_value={"pockets": fp, "p2_pockets": p2}
        ) as renderer:
            result = consensus._has_high_score_consensus(SimpleNamespace(), target_chain=chain)
        self.assertEqual(renderer.call_args.kwargs["target_chain"], chain)
        return result

    def test_high_scores_on_same_site_match(self):
        self.assertTrue(self.verdict())

    def test_missing_probability_is_unknown_not_zero(self):
        self.assertIsNone(
            self.verdict(
                p2=[SimpleNamespace(name="1", probability=None, geometric_center=(1, 0, 0))]
            )
        )

    def test_missing_method_or_geometry_is_unknown(self):
        self.assertIsNone(self.verdict(p2=[]))
        self.assertIsNone(self.verdict(fp=[]))
        self.assertIsNone(
            self.verdict(p2=[SimpleNamespace(name="1", probability=0.8, geometric_center=None)])
        )

    def test_complete_low_score_or_distant_pockets_are_negative(self):
        self.assertFalse(
            self.verdict(p2=[SimpleNamespace(name="1", probability=0.2, geometric_center=None)])
        )
        self.assertFalse(
            self.verdict(
                p2=[SimpleNamespace(name="1", probability=0.8, geometric_center=(100, 0, 0))]
            )
        )

    def test_valid_positive_wins_over_other_missing_geometry(self):
        self.assertTrue(
            self.verdict(
                p2=[
                    SimpleNamespace(name="1", probability=0.8, geometric_center=None),
                    SimpleNamespace(name="2", probability=0.8, geometric_center=(1, 0, 0)),
                ]
            )
        )


class StructureColumnRecoveryTests(TestCase):
    def test_nested_microbiome_companions_are_validated_and_recovered_atomically(self):
        with TemporaryDirectory() as temp:
            folder = Path(temp)
            source = folder / "fasttarget_remote/output/offtarget/species_blast_results"
            source.mkdir(parents=True)
            counts = source / "gut_microbiome_offtarget_counts.tsv"
            counts.write_text("gene\tcounts\nRECOVER_1\t1\n", encoding="utf-8")
            (source / "gut_microbiome_genomes_analyzed.tsv").write_text(
                "gene\ttotal\nRECOVER_1\t4\n", encoding="utf-8"
            )
            fraction = source / "gut_microbiome_offtarget_norm.tsv"
            fraction.write_text(
                "gene\tgut_microbiome_offtarget_norm\nRECOVER_1\t0.5\n", encoding="utf-8"
            )
            options = dict(
                genome_name=self.genome, datadir=temp, apply=True, include_normalization=True
            )
            with (
                patch(
                    "tpweb.management.commands.recover_microbiome_counts.compute_folder_path",
                    return_value=temp,
                ),
                patch(
                    "tpweb.services.score_params.ensure_system_score_param",
                    side_effect=ensure_param,
                ),
            ):
                with self.assertRaises(CommandError):
                    MicrobiomeCommand(stdout=StringIO()).handle(**options)
                self.assertEqual(ScoreParamValue.objects.count(), 0)
                fraction.write_text(
                    "gene\tgut_microbiome_offtarget_norm\nRECOVER_1\t0.25\n", encoding="utf-8"
                )
                MicrobiomeCommand(stdout=StringIO()).handle(**options)
                MicrobiomeCommand(stdout=StringIO()).handle(**options)
                values = self.values()
                self.assertEqual(len(values), 3)
                self.assertEqual(values["gut_microbiome_offtarget_counts"].numeric_value, 1)
                self.assertEqual(values["gut_microbiome_genomes_analyzed"].numeric_value, 4)
                self.assertEqual(values["gut_microbiome_offtarget_norm"].numeric_value, 0.25)
                ScoreParamValue.objects.all().delete()
                ScoreParamValue.objects.create(
                    bioentry=self.protein,
                    score_param=ensure_param("gut_microbiome_offtarget_counts"),
                    value="0",
                    numeric_value=0,
                )
                MicrobiomeCommand(stdout=StringIO()).handle(**options)
                self.assertEqual(ScoreParamValue.objects.count(), 1)
                self.assertEqual(self.values()["gut_microbiome_offtarget_counts"].numeric_value, 0)

    def test_microbiome_counts_recovery_preserves_zero_and_does_not_invent_normalization(self):
        with TemporaryDirectory() as temp:
            path = Path(temp) / "counts.tsv"
            path.write_text("gene\tcounts\nRECOVER_1\t0\n", encoding="utf-8")
            options = dict(genome_name=self.genome, counts_tsv=str(path), datadir=temp, apply=True)
            with patch(
                "tpweb.services.score_params.ensure_system_score_param", side_effect=ensure_param
            ):
                MicrobiomeCommand(stdout=StringIO()).handle(**options)
                path.write_text("gene\tcounts\nRECOVER_1\t3\n", encoding="utf-8")
                MicrobiomeCommand(stdout=StringIO()).handle(**options)
        values = self.values()
        self.assertEqual(set(values), {"gut_microbiome_offtarget_counts"})
        self.assertEqual(values["gut_microbiome_offtarget_counts"].numeric_value, 0)

    def test_microbiome_file_with_unknown_locus_does_not_write(self):
        with TemporaryDirectory() as temp:
            path = Path(temp) / "counts.tsv"
            path.write_text("gene\tcounts\nOTHER\t1\n", encoding="utf-8")
            with self.assertRaises(CommandError):
                MicrobiomeCommand(stdout=StringIO()).handle(
                    genome_name=self.genome, counts_tsv=str(path), datadir=temp, apply=True
                )
        self.assertEqual(ScoreParamValue.objects.count(), 0)

    def test_model_preview_and_wrong_sequence_do_not_modify_structures(self):
        relation = Bioentry._meta.get_field("seq")
        model = relation.related_model
        available = {field.name for field in model._meta.fields}
        values = {
            key: value
            for key, value in {
                "seq": "MAU",
                "length": 3,
                "version": 0,
                "alphabet": "protein",
            }.items()
            if key in available
        }
        if relation.auto_created:
            model.objects.create(bioentry=self.protein, **values)
        else:
            self.protein.seq = model.objects.create(**values)
            self.protein.save(update_fields=["seq"])
        self.link.delete()
        with TemporaryDirectory() as temp:
            path = Path(temp) / "model.pdb"
            write_model(path, ["MET", "ALA", "SEC"])
            options = dict(
                genome_name=self.genome,
                locus_tag=self.protein.accession,
                pdb_file=str(path),
                datadir=temp,
                apply=False,
            )
            ModelCommand(stdout=StringIO()).handle(**options)
            self.assertEqual(BioentryStructure.objects.count(), 0)
            self.assertEqual(list(Path(temp).iterdir()), [path])
            write_model(path, ["MET", "ALA", "GLY"])
            with self.assertRaises(CommandError):
                ModelCommand(stdout=StringIO()).handle(**{**options, "apply": True})
            self.assertEqual(BioentryStructure.objects.count(), 0)

    def setUp(self):
        self.genome = "public__structure_column_test"
        database = Biodatabase.objects.create(name=self.genome + Biodatabase.PROT_POSTFIX)
        self.protein = Bioentry.objects.create(
            biodatabase=database, accession="RECOVER_1", name="RECOVER_1", identifier="RECOVER_1"
        )
        self.pdb = PDB.objects.create(code="CF_RECOVER", experiment="CF")
        self.link = BioentryStructure.objects.create(bioentry=self.protein, pdb=self.pdb)

    def atom(self, value, chain="A", name="CA", resid=1):
        residue = Residue.objects.create(
            pdb=self.pdb, chain=chain, resid=resid, resname="ALA", type="R"
        )
        return Atom.objects.create(
            residue=residue,
            serial=resid,
            name=name,
            altLoc=" ",
            x=0,
            y=0,
            z=0,
            occupancy=1,
            bfactor=value,
            element="C",
        )

    def pocket(self, kind, name, prop, value):
        rs, _ = ResidueSet.objects.get_or_create(name=kind)
        property_obj, _ = Property.objects.get_or_create(name=prop)
        pocket = PDBResidueSet.objects.create(pdb=self.pdb, residue_set=rs, name=name)
        ResidueSetProperty.objects.create(pdbresidue_set=pocket, property=property_obj, value=value)
        return pocket

    def recover(self, apply=True):
        with patch(
            "tpweb.services.score_params.ensure_system_score_param",
            side_effect=ensure_param,
            create=True,
        ):
            ColabFoldCommand(stdout=StringIO()).handle(genome_name=self.genome, apply=apply)

    def values(self):
        return {
            row.score_param.name: row
            for row in ScoreParamValue.objects.filter(bioentry=self.protein).select_related(
                "score_param"
            )
        }

    def test_confidence_and_pocket_bundles_are_recovered_and_idempotent(self):
        self.atom(80)
        self.atom(60, resid=2)
        self.atom(99, name="CB", resid=3)
        self.pocket("FPocketPocket", "3", "druggability_score", 0.8)
        self.pocket("P2RankPocket", "4", "probability", 0.65)
        self.recover()
        values = self.values()
        self.assertEqual(values["colabfold_plddt"].numeric_value, 70)
        self.assertEqual(values["colabfold_druggability_score"].numeric_value, 0.8)
        self.assertEqual(values["colabfold_fpocket_pocket"].value, "3")
        self.assertEqual(values["colabfold_p2rank_probability"].numeric_value, 0.65)
        self.assertEqual(values["colabfold_p2rank_pocket"].value, "4")
        self.recover()
        self.assertEqual(ScoreParamValue.objects.count(), 5)

    def test_preview_and_ambiguous_models_do_not_write(self):
        self.atom(80)
        self.recover(apply=False)
        self.assertEqual(ScoreParam.objects.count(), 0)
        other = PDB.objects.create(code="CF_SECOND", experiment="CF")
        BioentryStructure.objects.create(bioentry=self.protein, pdb=other)
        self.recover()
        self.assertEqual(ScoreParamValue.objects.count(), 0)

    def test_existing_partial_pocket_bundle_and_zero_confidence_are_preserved(self):
        self.atom(80)
        self.pocket("P2RankPocket", "4", "probability", 0.65)
        for name, value in (("colabfold_plddt", 0), ("colabfold_p2rank_probability", 0.9)):
            ScoreParamValue.objects.create(
                bioentry=self.protein,
                score_param=ensure_param(name),
                value=str(value),
                numeric_value=value,
            )
        self.recover()
        values = self.values()
        self.assertEqual(values["colabfold_plddt"].numeric_value, 0)
        self.assertEqual(values["colabfold_p2rank_probability"].numeric_value, 0.9)
        self.assertNotIn("colabfold_p2rank_pocket", values)

    def test_chain_scope_and_invalid_confidence(self):
        self.link.chain = "A"
        self.link.save()
        self.atom(30, chain="A")
        self.atom(99, chain="B", resid=2)
        self.recover()
        self.assertEqual(self.values()["colabfold_plddt"].numeric_value, 30)
        ScoreParamValue.objects.all().delete()
        Atom.objects.filter(residue__chain="A").update(bfactor=101)
        self.recover()
        self.assertEqual(ScoreParamValue.objects.count(), 0)

    def test_consensus_does_not_write_a_negative_for_missing_data(self):
        with (
            patch.object(consensus, "ensure_system_score_param", side_effect=ensure_param),
            patch.object(consensus, "_has_high_score_consensus", return_value=None),
        ):
            consensus.Command(stdout=StringIO()).handle(accession=self.genome)
        self.assertEqual(ScoreParamValue.objects.count(), 0)

    def test_consensus_preserves_existing_curated_flag(self):
        param = ensure_param("pocket_consensus_high_score")
        ScoreParamValue.objects.create(bioentry=self.protein, score_param=param, value="Y")
        with (
            patch.object(consensus, "ensure_system_score_param", return_value=param),
            patch.object(consensus, "_has_high_score_consensus") as calculate,
        ):
            consensus.Command(stdout=StringIO()).handle(accession=self.genome)
        calculate.assert_not_called()
        self.assertEqual(self.values()[param.name].value, "Y")

    def test_consensus_cache_distinguishes_chains_of_the_same_structure(self):
        self.link.chain = "A"
        self.link.save()
        other = Bioentry.objects.create(
            biodatabase=self.protein.biodatabase,
            accession="RECOVER_2",
            name="RECOVER_2",
            identifier="RECOVER_2",
        )
        BioentryStructure.objects.create(bioentry=other, pdb=self.pdb, chain="B")
        self.pocket("FPocketPocket", "1", "druggability_score", 0.8)
        self.pocket("P2RankPocket", "2", "probability", 0.8)
        with (
            patch.object(consensus, "ensure_system_score_param", side_effect=ensure_param),
            patch.object(
                consensus,
                "_has_high_score_consensus",
                side_effect=lambda pdb, target_chain: target_chain == "A",
            ) as calculate,
        ):
            consensus.Command(stdout=StringIO()).handle(accession=self.genome)
        self.assertEqual(calculate.call_count, 2)
        flags = dict(ScoreParamValue.objects.values_list("bioentry_id", "value"))
        self.assertEqual(flags, {self.protein.pk: "Y", other.pk: "N"})

    def test_outlier_skips_missing_selected_volume(self):
        self.pocket("FPocketPocket", "1", "druggability_score", 0.8)
        Property.objects.create(name="volume")
        with patch.object(outlier, "ensure_system_score_param", side_effect=ensure_param):
            outlier.Command(stdout=StringIO()).handle(accession=self.genome)
        self.assertEqual(ScoreParamValue.objects.count(), 0)

    def test_outlier_resolver_excludes_wrong_chain(self):
        self.link.chain = "B"
        self.link.save()
        pocket = self.pocket("FPocketPocket", "1", "druggability_score", 0.8)
        score = Property.objects.get(name="druggability_score")
        self.assertIsNone(outlier._resolve_auto_pocket([self.link], pocket.residue_set, score))

    def test_outlier_skips_invalid_selected_volume(self):
        pocket = self.pocket("FPocketPocket", "1", "druggability_score", 0.8)
        volume = Property.objects.create(name="volume")
        ResidueSetProperty.objects.create(pdbresidue_set=pocket, property=volume, value=-1)
        with patch.object(outlier, "ensure_system_score_param", side_effect=ensure_param):
            outlier.Command(stdout=StringIO()).handle(accession=self.genome)
        self.assertEqual(ScoreParamValue.objects.count(), 0)
