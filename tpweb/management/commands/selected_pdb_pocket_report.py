from collections import defaultdict

from django.core.management.base import BaseCommand, CommandError

from bioseq.models.Biodatabase import Biodatabase
from bioseq.models.Bioentry import Bioentry
from tpweb.models.BioentryStructure import BioentryStructure
from tpweb.models.ScoreParamValue import ScoreParamValue
from tpweb.models.pdb import PDBResidueSet


SELECTED_FIELDS = (
    ("FPocket", "best_fpocket_structure", "Druggability", "fpocket_pocket", "FPocketPocket"),
    ("P2Rank", "best_p2rank_structure", "p2rank_probability", "p2rank_pocket", "P2RankPocket"),
)


def _clean(value):
    if value is None:
        return ""
    value = str(value).strip()
    if value.lower() in {"", "nan", "none", "null"}:
        return ""
    return value


def _is_pdb_code(value):
    value = _clean(value).upper()
    return len(value) == 4 and value.isalnum()


def _is_expected_no_pockets(method, pocket):
    return method == "P2Rank" and _clean(pocket).lower() == "no_pockets"


class Command(BaseCommand):
    help = "Report pocket coverage for curated selected PDB structures."

    def add_arguments(self, parser):
        parser.add_argument("genome_name")
        parser.add_argument(
            "--examples",
            type=int,
            default=20,
            help="Maximum missing examples to print per method. Default: 20.",
        )

    def handle(self, *args, **options):
        genome_name = options["genome_name"]
        examples_limit = options["examples"]
        proteome_name = genome_name + Biodatabase.PROT_POSTFIX
        try:
            db = Biodatabase.objects.get(name=proteome_name)
        except Biodatabase.DoesNotExist as exc:
            raise CommandError(f"Protein database not found: {proteome_name}") from exc

        proteins = Bioentry.objects.filter(biodatabase=db).only("bioentry_id", "accession")
        protein_accessions = dict(proteins.values_list("bioentry_id", "accession"))
        protein_ids = set(protein_accessions)
        if not protein_ids:
            self.stdout.write("No proteins found.")
            return

        score_names = set()
        for _method, source_field, score_field, pocket_field, _residue_set in SELECTED_FIELDS:
            score_names.update([source_field, score_field, pocket_field])

        scores = defaultdict(dict)
        for spv in ScoreParamValue.objects.filter(
            bioentry_id__in=protein_ids,
            score_param__name__in=score_names,
        ).select_related("score_param"):
            value = spv.value if spv.value else (
                str(spv.numeric_value) if spv.numeric_value is not None else ""
            )
            scores[spv.bioentry_id][spv.score_param.name] = _clean(value)

        loaded = {}
        pdb_ids = set()
        for link in BioentryStructure.objects.filter(
            bioentry_id__in=protein_ids,
            pdb__experiment="EX",
        ).select_related("pdb"):
            code = _clean(link.pdb.code).upper()
            loaded[(link.bioentry_id, code)] = link.pdb_id
            pdb_ids.add(link.pdb_id)

        pockets_by_type = defaultdict(set)
        if pdb_ids:
            for row in PDBResidueSet.objects.filter(
                pdb_id__in=pdb_ids,
                residue_set__name__in=[field[-1] for field in SELECTED_FIELDS],
            ).values_list("pdb_id", "residue_set__name"):
                pdb_id, residue_set_name = row
                pockets_by_type[residue_set_name].add(pdb_id)

        self.stdout.write(self.style.MIGRATE_HEADING(f"Selected PDB pocket report for {genome_name}"))
        self.stdout.write(f"Proteins: {len(protein_ids)}")

        combined_missing = set()
        combined_pdbs = set()
        for method, source_field, score_field, pocket_field, residue_set_name in SELECTED_FIELDS:
            total = loaded_count = pocket_count = missing_structure = missing_pocket = expected_no_pockets = 0
            examples = []
            expected_examples = []
            selected_pdbs = set()

            for protein_id, accession in protein_accessions.items():
                source = scores.get(protein_id, {}).get(source_field, "")
                if not _is_pdb_code(source):
                    continue

                pdb_code = source.upper()
                total += 1
                selected_pdbs.add(pdb_code)
                combined_pdbs.add((protein_id, pdb_code))
                pdb_db_id = loaded.get((protein_id, pdb_code))
                if pdb_db_id is None:
                    missing_structure += 1
                    combined_missing.add((protein_id, pdb_code, method, "structure"))
                    if len(examples) < examples_limit:
                        examples.append((accession, pdb_code, "missing structure"))
                    continue

                loaded_count += 1
                if pdb_db_id in pockets_by_type[residue_set_name]:
                    pocket_count += 1
                else:
                    score = scores.get(protein_id, {}).get(score_field, "-") or "-"
                    pocket = scores.get(protein_id, {}).get(pocket_field, "-") or "-"
                    if _is_expected_no_pockets(method, pocket):
                        expected_no_pockets += 1
                        if len(expected_examples) < examples_limit:
                            expected_examples.append((accession, pdb_code, f"expected no pockets score={score} pocket={pocket}"))
                    else:
                        missing_pocket += 1
                        combined_missing.add((protein_id, pdb_code, method, "pockets"))
                        if len(examples) < examples_limit:
                            examples.append((accession, pdb_code, f"missing {method} pockets score={score} pocket={pocket}"))

            self.stdout.write("")
            self.stdout.write(self.style.HTTP_INFO(f"{method} selected PDB sources"))
            self.stdout.write(f"  selected rows: {total}")
            self.stdout.write(f"  unique selected PDB codes: {len(selected_pdbs)} across {total} rows")
            self.stdout.write(f"  loaded as EX: {loaded_count}/{total}")
            self.stdout.write(f"  with {method} pockets: {pocket_count}/{total}")
            self.stdout.write(f"  expected no-pockets: {expected_no_pockets}")
            self.stdout.write(f"  missing structures: {missing_structure}")
            self.stdout.write(f"  missing {method} pockets: {missing_pocket}")
            if expected_examples:
                self.stdout.write("  Expected no-pockets examples:")
                for accession, pdb_code, reason in expected_examples:
                    self.stdout.write(f"    {accession} {pdb_code}: {reason}")
            if examples:
                self.stdout.write("  Examples:")
                for accession, pdb_code, reason in examples:
                    self.stdout.write(f"    {accession} {pdb_code}: {reason}")

        self.stdout.write("")
        self.stdout.write(self.style.HTTP_INFO("Combined selected PDB status"))
        self.stdout.write(f"  unique selected protein/PDB links: {len(combined_pdbs)}")
        self.stdout.write(f"  missing structure/pocket checks: {len(combined_missing)}")
