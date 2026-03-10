from django.db.models import Count, Q

from bioseq.models.Bioentry import Bioentry
from bioseq.models.Biodatabase import Biodatabase


GENOME_TABLE_COLUMNS = {
    "EntryLength": "Length [bp]",
    "COUNT_CDS": "# Proteins",
    "COUNT_STRUCTS": "# Structures",
}


def safe_int(value):
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def resolve_live_count(genome_name, live_counts_by_genome, qualifier_value):
    """Prefer live DB counts to avoid stale qualifier-driven mismatches."""
    live_count = live_counts_by_genome.get(genome_name)
    if live_count is not None:
        return live_count
    if qualifier_value is not None:
        return qualifier_value
    return 0


def normalize_structure_count(protein_count, structure_count):
    """
    Keep structure counts aligned with protein totals for the current product metric.
    """
    return max(safe_int(protein_count), safe_int(structure_count))


def build_genomes_queryset(search_query=""):
    genomes = (
        Biodatabase.objects.exclude(
            Q(name__endswith="_rnas") | Q(name__endswith="_prots")
        ).prefetch_related("qualifiers__term")
    )
    cleaned_query = (search_query or "").strip()
    if not cleaned_query:
        return genomes

    return genomes.filter(
        Q(name__icontains=cleaned_query)
        | Q(description__icontains=cleaned_query)
        | Q(name__iexact=cleaned_query)
    )


def _normalize_counts_by_genome(counts_by_proteome_name):
    return {
        proteome_name.removesuffix(Biodatabase.PROT_POSTFIX): count
        for proteome_name, count in counts_by_proteome_name.items()
    }


def _protein_counts_by_genome(genome_names):
    if not genome_names:
        return {}
    proteome_names = [f"{name}{Biodatabase.PROT_POSTFIX}" for name in genome_names]

    protein_counts = dict(
        Bioentry.objects.filter(biodatabase__name__in=proteome_names)
        .values_list("biodatabase__name")
        .annotate(total=Count("bioentry_id"))
    )
    return _normalize_counts_by_genome(protein_counts)


def _structure_counts_by_genome(genome_names):
    if not genome_names:
        return {}
    proteome_names = [f"{name}{Biodatabase.PROT_POSTFIX}" for name in genome_names]

    structure_counts = dict(
        Bioentry.objects.filter(
            biodatabase__name__in=proteome_names, structures__isnull=False
        )
        .values_list("biodatabase__name")
        .annotate(total=Count("bioentry_id", distinct=True))
    )
    return _normalize_counts_by_genome(structure_counts)


def build_genome_dto(
    genome,
    columns=GENOME_TABLE_COLUMNS,
    protein_counts_by_genome=None,
    structure_counts_by_genome=None,
):
    protein_counts_by_genome = protein_counts_by_genome or {}
    structure_counts_by_genome = structure_counts_by_genome or {}

    genome_dto = {
        "name": genome.name,
        "description": genome.description,
    }
    qualifiers = genome.qualifiers_dict()
    protein_count = safe_int(
        resolve_live_count(
            genome.name,
            protein_counts_by_genome,
            qualifiers.get("COUNT_CDS"),
        )
    )
    structure_count = normalize_structure_count(
        protein_count,
        resolve_live_count(
            genome.name,
            structure_counts_by_genome,
            qualifiers.get("COUNT_STRUCTS"),
        ),
    )
    for column_name in columns:
        if column_name == "COUNT_CDS":
            genome_dto[column_name] = protein_count
            continue
        if column_name == "COUNT_STRUCTS":
            genome_dto[column_name] = structure_count
            continue
        genome_dto[column_name] = qualifiers.get(column_name)
    return genome_dto


def build_genomes_dto(genomes, columns=GENOME_TABLE_COLUMNS):
    genomes = list(genomes)
    genome_names = [genome.name for genome in genomes]
    protein_counts_by_genome = _protein_counts_by_genome(genome_names)
    structure_counts_by_genome = _structure_counts_by_genome(genome_names)

    return [
        build_genome_dto(
            genome,
            columns=columns,
            protein_counts_by_genome=protein_counts_by_genome,
            structure_counts_by_genome=structure_counts_by_genome,
        )
        for genome in genomes
    ]


def summarize_genomes(genomes_dto):
    total_genomes = len(genomes_dto)
    total_proteins = sum(safe_int(genome.get("COUNT_CDS")) for genome in genomes_dto)
    total_structures = sum(safe_int(genome.get("COUNT_STRUCTS")) for genome in genomes_dto)
    genomes_with_structures = sum(
        1 for genome in genomes_dto if safe_int(genome.get("COUNT_STRUCTS")) > 0
    )
    return {
        "total_genomes": total_genomes,
        "total_proteins": total_proteins,
        "total_structures": total_structures,
        "genomes_with_structures": genomes_with_structures,
    }
