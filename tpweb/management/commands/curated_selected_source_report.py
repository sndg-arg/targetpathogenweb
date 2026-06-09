from collections import Counter, defaultdict

from django.core.management.base import BaseCommand, CommandError

from bioseq.models.Biodatabase import Biodatabase
from bioseq.models.Bioentry import Bioentry
from tpweb.models.BioentryStructure import BioentryStructure, ExperimentalStructureXref
from tpweb.models.ScoreParamValue import ScoreParamValue


SOURCE_FIELDS = (
    ("FPocket", "best_fpocket_structure", "Druggability", "fpocket_pocket"),
    ("P2Rank", "best_p2rank_structure", "p2rank_probability", "p2rank_pocket"),
)


def raw_score(value):
    if value is None:
        return ""
    value = str(value).strip()
    if value.lower() in {"", "nan", "none", "null"}:
        return ""
    return value


def structure_kind(identifier):
    ident = raw_score(identifier).upper()
    if not ident:
        return "missing"
    if len(ident) == 4 and ident.isalnum():
        return "PDB"
    if ident.startswith("CB_"):
        return "ColabFold/curated"
    if ident.startswith("AF_") or ident.startswith("A0A"):
        return "AlphaFold/UniProt"
    return "Curated/model"


def identifier_candidates(identifier):
    ident = raw_score(identifier).upper()
    if not ident:
        return set()
    candidates = {ident}
    for prefix in ("AF_", "CB_"):
        if ident.startswith(prefix):
            candidates.add(ident[len(prefix):])
    candidates.add(f"AF_{ident}")
    candidates.add(f"CB_{ident}")
    return candidates


def code_matches(code, identifier):
    code = raw_score(code).upper()
    if not code:
        return False
    for candidate in identifier_candidates(identifier):
        if code == candidate or code.startswith(f"{candidate}_") or code.startswith(f"{candidate}-"):
            return True
    return False


def format_percent(part, total):
    if not total:
        return "0.0%"
    return f"{part / total * 100:.1f}%"


class Command(BaseCommand):
    help = "Report whether curated selected FPocket/P2Rank score sources are loaded as TPW structures."

    def add_arguments(self, parser):
        parser.add_argument("genome_name")
        parser.add_argument(
            "--examples",
            type=int,
            default=12,
            help="Maximum missing examples to print per method/kind. Default: 12.",
        )

    def handle(self, *args, **options):
        genome_name = options["genome_name"]
        examples_limit = options["examples"]
        db_name = genome_name + Biodatabase.PROT_POSTFIX
        try:
            db = Biodatabase.objects.get(name=db_name)
        except Biodatabase.DoesNotExist as exc:
            raise CommandError(f"Protein database not found: {db_name}") from exc

        proteins = Bioentry.objects.filter(biodatabase=db).only("bioentry_id", "accession")
        protein_accessions = dict(proteins.values_list("bioentry_id", "accession"))
        protein_ids = set(protein_accessions)

        score_names = {field for _, field, _, _ in SOURCE_FIELDS}
        score_names.update(score for _, _, score, _ in SOURCE_FIELDS)
        score_names.update(pocket for _, _, _, pocket in SOURCE_FIELDS)
        scores = defaultdict(dict)
        for spv in ScoreParamValue.objects.filter(
            bioentry_id__in=protein_ids,
            score_param__name__in=score_names,
        ).select_related("score_param"):
            value = spv.value if spv.value else (
                str(spv.numeric_value) if spv.numeric_value is not None else ""
            )
            scores[spv.bioentry_id][spv.score_param.name] = raw_score(value)

        loaded_codes = defaultdict(set)
        loaded_count = Counter()
        for link in BioentryStructure.objects.filter(bioentry_id__in=protein_ids).select_related("pdb"):
            code = raw_score(getattr(link.pdb, "code", "")).upper()
            if code:
                loaded_codes[link.bioentry_id].add(code)
                loaded_count[link.bioentry_id] += 1

        xref_codes = defaultdict(set)
        for xref in ExperimentalStructureXref.objects.filter(bioentry_id__in=protein_ids):
            code = raw_score(xref.pdb_id).upper()
            if code:
                xref_codes[xref.bioentry_id].add(code)

        self.stdout.write(self.style.MIGRATE_HEADING(f"Selected structure source report for {genome_name}"))
        self.stdout.write(f"Proteins: {len(protein_ids)}")
        self.stdout.write(f"Proteins with loaded structures: {sum(1 for pid in protein_ids if loaded_codes.get(pid))}")

        combined_total = 0
        combined_loaded = 0
        combined_missing_by_kind = Counter()

        for method, source_field, score_field, pocket_field in SOURCE_FIELDS:
            total = loaded = missing = xref_only = 0
            by_kind = Counter()
            loaded_by_kind = Counter()
            missing_by_kind = Counter()
            xref_only_by_kind = Counter()
            missing_examples = defaultdict(list)

            for protein_id, accession in protein_accessions.items():
                source = scores.get(protein_id, {}).get(source_field, "")
                if not source:
                    continue
                total += 1
                combined_total += 1
                kind = structure_kind(source)
                by_kind[kind] += 1
                is_loaded = any(code_matches(code, source) for code in loaded_codes.get(protein_id, set()))
                if is_loaded:
                    loaded += 1
                    combined_loaded += 1
                    loaded_by_kind[kind] += 1
                    continue

                missing += 1
                missing_by_kind[kind] += 1
                combined_missing_by_kind[kind] += 1
                is_xref_only = any(code_matches(code, source) for code in xref_codes.get(protein_id, set()))
                if is_xref_only:
                    xref_only += 1
                    xref_only_by_kind[kind] += 1
                if len(missing_examples[kind]) < examples_limit:
                    missing_examples[kind].append({
                        "accession": accession,
                        "source": source,
                        "score": scores.get(protein_id, {}).get(score_field, ""),
                        "pocket": scores.get(protein_id, {}).get(pocket_field, ""),
                        "loaded_n": loaded_count.get(protein_id, 0),
                        "xref_only": is_xref_only,
                    })

            self.stdout.write("")
            self.stdout.write(self.style.HTTP_INFO(f"{method} selected source"))
            self.stdout.write(f"  with selected source: {total}")
            self.stdout.write(f"  loaded in TPW: {loaded}/{total} ({format_percent(loaded, total)})")
            self.stdout.write(f"  missing from loaded structures: {missing}/{total} ({format_percent(missing, total)})")
            if xref_only:
                self.stdout.write(f"  missing but present as experimental xref: {xref_only}")

            for kind in sorted(by_kind):
                self.stdout.write(
                    f"  {kind}: total={by_kind[kind]} loaded={loaded_by_kind[kind]} "
                    f"missing={missing_by_kind[kind]} xref_only={xref_only_by_kind[kind]}"
                )

            for kind in sorted(missing_examples):
                self.stdout.write(f"  Missing examples ({kind}):")
                for row in missing_examples[kind]:
                    flag = " xref_only" if row["xref_only"] else ""
                    self.stdout.write(
                        f"    {row['accession']} source={row['source']} score={row['score'] or '-'} "
                        f"pocket={row['pocket'] or '-'} loaded_structures={row['loaded_n']}{flag}"
                    )

        self.stdout.write("")
        self.stdout.write(self.style.HTTP_INFO("Combined selected source rows"))
        self.stdout.write(
            f"  loaded: {combined_loaded}/{combined_total} ({format_percent(combined_loaded, combined_total)})"
        )
        if combined_missing_by_kind:
            self.stdout.write("  missing by kind:")
            for kind in sorted(combined_missing_by_kind):
                self.stdout.write(f"    {kind}: {combined_missing_by_kind[kind]}")
