from django.db.models import Count, Q

from bioseq.models.Bioentry import Bioentry
from bioseq.models.Biodatabase import Biodatabase
from bioseq.models.Ontology import Ontology
from tpweb.models.BioentryStructure import BioentryStructure
from tpweb.services.genome_workspace import (
    describe_genome_scope,
    display_genome_name,
    visible_genome_name_filter,
)


GENOME_TABLE_COLUMNS = {
    "EntryLength": "Length [bp]",
    "COUNT_CDS": "# Proteins",
    "COUNT_EXPERIMENTAL": "Experimental",
    "COUNT_EC": "EC annotated",
}

EC_DBNAMES = {str(Ontology.EC or "").strip(), "ec", "EC"}


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


def build_genomes_queryset(user=None, search_query=""):
    genomes = (
        Biodatabase.objects.exclude(
            Q(name__endswith="_rnas") | Q(name__endswith="_prots")
        ).filter(
            visible_genome_name_filter(user)
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


def _proteins_by_genome_queryset(genome_names):
    if not genome_names:
        return Bioentry.objects.none()
    proteome_names = [f"{name}{Biodatabase.PROT_POSTFIX}" for name in genome_names]
    return Bioentry.objects.filter(biodatabase__name__in=proteome_names)


def _protein_counts_by_genome(genome_names):
    proteins = _proteins_by_genome_queryset(genome_names)
    if not proteins.exists():
        return {}
    protein_counts = dict(
        proteins.values("biodatabase__name")
        .annotate(total=Count("bioentry_id"))
        .values_list("biodatabase__name", "total")
    )
    return _normalize_counts_by_genome(protein_counts)


def _experimental_counts_by_genome(genome_names):
    if not genome_names:
        return {}

    experimental_counts = dict(
        BioentryStructure.objects.filter(
            bioentry__biodatabase__name__in=[
                f"{name}{Biodatabase.PROT_POSTFIX}" for name in genome_names
            ]
        )
        .exclude(pdb__experiment="AF")
        .values("bioentry__biodatabase__name")
        .annotate(total=Count("bioentry_id", distinct=True))
        .values_list("bioentry__biodatabase__name", "total")
    )
    return _normalize_counts_by_genome(experimental_counts)


def _ec_counts_by_genome(genome_names):
    proteins = _proteins_by_genome_queryset(genome_names)
    if not proteins.exists():
        return {}

    ec_counts = dict(
        proteins.filter(dbxrefs__dbxref__dbname__in=EC_DBNAMES)
        .values("biodatabase__name")
        .annotate(total=Count("bioentry_id", distinct=True))
        .values_list("biodatabase__name", "total")
    )
    return _normalize_counts_by_genome(ec_counts)


def build_genome_dto(
    genome,
    user=None,
    columns=GENOME_TABLE_COLUMNS,
    protein_counts_by_genome=None,
    experimental_counts_by_genome=None,
    ec_counts_by_genome=None,
):
    protein_counts_by_genome = protein_counts_by_genome or {}
    experimental_counts_by_genome = experimental_counts_by_genome or {}
    ec_counts_by_genome = ec_counts_by_genome or {}

    workspace_scope = describe_genome_scope(user, genome.name)
    genome_dto = {
        "name": display_genome_name(genome.name),
        "internal_name": genome.name,
        "description": genome.description,
        "workspace_scope_key": workspace_scope["key"],
        "workspace_scope_label": workspace_scope["label"],
    }
    qualifiers = genome.qualifiers_dict()
    protein_count = safe_int(
        resolve_live_count(
            genome.name,
            protein_counts_by_genome,
            qualifiers.get("COUNT_CDS"),
        )
    )
    experimental_count = safe_int(
        resolve_live_count(
            genome.name,
            experimental_counts_by_genome,
            qualifiers.get("COUNT_EXPERIMENTAL"),
        )
    )
    ec_count = safe_int(
        resolve_live_count(
            genome.name,
            ec_counts_by_genome,
            qualifiers.get("COUNT_EC"),
        )
    )
    for column_name in columns:
        if column_name == "COUNT_CDS":
            genome_dto[column_name] = protein_count
            continue
        if column_name == "COUNT_EXPERIMENTAL":
            genome_dto[column_name] = experimental_count
            continue
        if column_name == "COUNT_EC":
            genome_dto[column_name] = ec_count
            continue
        genome_dto[column_name] = qualifiers.get(column_name)
    return genome_dto


def build_genomes_dto(genomes, user=None, columns=GENOME_TABLE_COLUMNS):
    genomes = list(genomes)
    genome_names = [genome.name for genome in genomes]
    protein_counts_by_genome = _protein_counts_by_genome(genome_names)
    experimental_counts_by_genome = _experimental_counts_by_genome(genome_names)
    ec_counts_by_genome = _ec_counts_by_genome(genome_names)

    return [
        build_genome_dto(
            genome,
            user=user,
            columns=columns,
            protein_counts_by_genome=protein_counts_by_genome,
            experimental_counts_by_genome=experimental_counts_by_genome,
            ec_counts_by_genome=ec_counts_by_genome,
        )
        for genome in genomes
    ]


def summarize_genomes(genomes_dto):
    total_genomes = len(genomes_dto)
    total_proteins = sum(safe_int(genome.get("COUNT_CDS")) for genome in genomes_dto)
    total_experimental = sum(
        safe_int(genome.get("COUNT_EXPERIMENTAL")) for genome in genomes_dto
    )
    total_ec_annotated = sum(safe_int(genome.get("COUNT_EC")) for genome in genomes_dto)
    return {
        "total_genomes": total_genomes,
        "total_proteins": total_proteins,
        "total_experimental": total_experimental,
        "total_ec_annotated": total_ec_annotated,
    }
