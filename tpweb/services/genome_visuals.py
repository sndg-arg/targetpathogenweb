"""Drawings for the genome overview: the cell (PSORTb localization by
compartment), the target funnel (essential -> no human homolog -> druggable
pocket) and the genome ring (where the funnel's survivors sit). Built once
per genome and cached like the other overview aggregates."""

import math

from django.core.cache import cache
from django.db.models import Count

from bioseq.models.Bioentry import Bioentry
from bioseq.models.Biodatabase import Biodatabase
from bioseq.models.Seqfeature import Seqfeature
from tpweb.models.ScoreParam import ScoreParam, ScoreParamOptions
from tpweb.models.ScoreParamValue import ScoreParamValue
from tpweb.services.assembly_workspace import OVERVIEW_CACHE_TTL_SECONDS
from tpweb.services.protein_list import build_numeric_filter_payload, protein_list_filter_url

_EMPTY = ("", "nan", "None", "null")

# Outside in. Gram-positive genomes use the cell wall in place of the outer
# membrane and have no periplasm; regions without proteins are still drawn.
CELL_COMPARTMENTS = (
    ("Extracellular", "Extracellular"),
    ("OuterMembrane", "Outer membrane"),
    ("Cellwall", "Cell wall"),
    ("Periplasmic", "Periplasm"),
    ("CytoplasmicMembrane", "Inner membrane"),
    ("Cytoplasmic", "Cytoplasm"),
)

RING_BINS = 180
RING_SIZE = 320
_RING_CENTER = RING_SIZE / 2
_RING_INNER = 100
# Gene density ticks stay short and grey; candidate ticks grow over them.
_RING_GENE_TICK = (3, 7)
_RING_CANDIDATE_TICK = (7, 30)


def _cache_key(assembly_name):
    return f"genome-visuals:v2:{assembly_name}"


def _option_payload(param_name, option_name):
    option = (
        ScoreParamOptions.objects.filter(score_param__name=param_name, name=option_name)
        .select_related("score_param")
        .first()
    )
    return option.to_dict() if option else None


def _numeric_payload(param_name, minimum):
    param = ScoreParam.objects.filter(name=param_name).values_list("pk", flat=True).first()
    if param is None:
        return None
    return build_numeric_filter_payload(param, minimum, "", operation=">=")


def _ids(spv_qs, param_name, **lookup):
    return set(
        spv_qs.filter(score_param__name=param_name, **lookup).values_list("bioentry_id", flat=True)
    )


def _build_cell(spv_qs, total):
    counts = dict(
        spv_qs.filter(score_param__name="Localization")
        .exclude(value__in=_EMPTY)
        .values("value")
        .annotate(n=Count("bioentry_id", distinct=True))
        .values_list("value", "n")
    )
    known = sum(n for value, n in counts.items() if value.lower() != "unknown")
    if not known:
        return None
    gram_positive = counts.get("Cellwall", 0) > counts.get("OuterMembrane", 0)
    regions = []
    for key, label in CELL_COMPARTMENTS:
        if gram_positive and key in {"OuterMembrane", "Periplasmic"}:
            continue
        if not gram_positive and key == "Cellwall":
            continue
        count = counts.get(key, 0)
        regions.append(
            {
                "key": key,
                "label": label,
                "count": count,
                "share": round(100 * count / known, 1) if known else 0,
                "filter": _option_payload("Localization", key) if count else None,
            }
        )
    peak = max(region["count"] for region in regions) or 1
    for region in regions:
        # Fill strength 0.08-0.6 by count, so the busiest compartment reads first.
        region["level"] = round(0.08 + 0.52 * region["count"] / peak, 2)
    return {
        "regions": regions,
        "gram_positive": gram_positive,
        "known": known,
        "unknown": counts.get("Unknown", 0),
        "total": total,
    }


def _druggable(spv_qs):
    """(ids, filter payload, label): P2Rank >= 0.5 when the genome has P2Rank,
    else FPocket druggability >= 0.4 -- the thresholds the overview uses."""
    if spv_qs.filter(score_param__name="p2rank_probability", numeric_value__isnull=False).exists():
        return (
            _ids(spv_qs, "p2rank_probability", numeric_value__gte=0.5),
            _numeric_payload("p2rank_probability", 0.5),
            "Druggable pocket (P2Rank ≥ 0.5)",
        )
    return (
        _ids(spv_qs, "Druggability", numeric_value__gte=0.4),
        _numeric_payload("Druggability", 0.4),
        "Druggable pocket (FPocket ≥ 0.4)",
    )


def _build_funnel(spv_qs, all_ids):
    steps = [{"label": "All proteins", "ids": set(all_ids), "filter": None}]
    if spv_qs.filter(score_param__name="hit_in_deg").exists():
        steps.append(
            {
                "label": "Essential (DEG homolog)",
                "ids": _ids(spv_qs, "hit_in_deg", value__iregex=r"^\s*(y|yes|true|1)\s*$"),
                "filter": _option_payload("hit_in_deg", "Y"),
            }
        )
    if spv_qs.filter(score_param__name="human_offtarget").exists():
        steps.append(
            {
                "label": "No human homolog",
                "ids": _ids(spv_qs, "human_offtarget", value__iexact="no_hit"),
                "filter": _option_payload("human_offtarget", "no_hit"),
            }
        )
    druggable_ids, druggable_filter, druggable_label = _druggable(spv_qs)
    if druggable_ids:
        steps.append({"label": druggable_label, "ids": druggable_ids, "filter": druggable_filter})
    if len(steps) < 3:
        return None, set()

    remaining = set(all_ids)
    filters = []
    funnel = []
    total = len(all_ids) or 1
    for step in steps:
        remaining &= step["ids"]
        if step["filter"]:
            filters.append(step["filter"])
        funnel.append(
            {
                "label": step["label"],
                "count": len(remaining),
                "width": max(round(100 * len(remaining) / total, 1), 0.6),
                "filters": list(filters),
            }
        )
    return funnel, remaining


def _cds_positions(assembly_name):
    """{locus tag: (contig id, start)} from the genome's CDS features."""
    positions = {}
    rows = Seqfeature.objects.filter(
        bioentry__biodatabase__name=assembly_name,
        type_term__identifier="CDS",
        qualifiers__term__identifier="locus_tag",
    ).values_list("qualifiers__value", "bioentry_id", "locations__start_pos")
    for locus_tag, contig_id, start in rows:
        if locus_tag and start is not None:
            current = positions.get(locus_tag)
            if current is None or start < current[1]:
                positions[locus_tag] = (contig_id, start)
    return positions


def _point(angle, radius):
    return (
        round(_RING_CENTER + radius * math.cos(angle), 1),
        round(_RING_CENTER + radius * math.sin(angle), 1),
    )


def _tick(index, length):
    angle = 2 * math.pi * (index + 0.5) / RING_BINS - math.pi / 2
    x1, y1 = _point(angle, _RING_INNER)
    x2, y2 = _point(angle, _RING_INNER + length)
    return f"M{x1} {y1}L{x2} {y2}"


def _build_ring(assembly_name, proteins, candidate_ids):
    """Proteins per 1/RING_BINS of the genome (grey) and, over them, how many
    pass the whole funnel there (accent): where the candidates cluster."""
    contigs = list(
        Bioentry.objects.filter(biodatabase__name=assembly_name, seq__length__gt=0)
        .order_by("-seq__length")
        .values_list("bioentry_id", "accession", "seq__length")
    )
    genome_length = sum(length for _, _, length in contigs)
    if not genome_length:
        return None
    positions = _cds_positions(assembly_name)
    if not positions:
        return None
    offsets = {}
    offset = 0
    for contig_id, _accession, length in contigs:
        offsets[contig_id] = offset
        offset += length

    genes = [0] * RING_BINS
    candidates = [0] * RING_BINS
    for protein_id, accession in proteins:
        position = positions.get(accession)
        if position is None or position[0] not in offsets:
            continue
        fraction = (offsets[position[0]] + position[1]) / genome_length
        index = min(int(fraction * RING_BINS), RING_BINS - 1)
        genes[index] += 1
        if protein_id in candidate_ids:
            candidates[index] += 1
    if not any(candidates):
        return None

    def scaled(count, peak, bounds):
        low, high = bounds
        return round(low + (high - low) * count / peak, 1)

    gene_peak = max(genes)
    candidate_peak = max(candidates)
    gene_path = "".join(
        _tick(i, scaled(n, gene_peak, _RING_GENE_TICK)) for i, n in enumerate(genes) if n
    )
    candidate_path = "".join(
        _tick(i, scaled(n, candidate_peak, _RING_CANDIDATE_TICK))
        for i, n in enumerate(candidates)
        if n
    )

    contig_marks = []
    for contig_id, accession, _length in contigs[1:]:
        angle = 2 * math.pi * offsets[contig_id] / genome_length - math.pi / 2
        x1, y1 = _point(angle, _RING_INNER - 6)
        x2, y2 = _point(angle, _RING_INNER + 34)
        contig_marks.append({"d": f"M{x1} {y1}L{x2} {y2}", "label": accession})

    return {
        "size": RING_SIZE,
        "center": _RING_CENTER,
        "inner": _RING_INNER,
        "genes": gene_path,
        "candidates": candidate_path,
        "candidate_count": sum(candidates),
        "contig_marks": contig_marks,
        "length_mb": round(genome_length / 1_000_000, 2),
        "contig_count": len(contigs),
    }


def _build(assembly_name):
    proteome_name = assembly_name + Biodatabase.PROT_POSTFIX
    proteins = list(
        Bioentry.objects.filter(biodatabase__name=proteome_name).values_list(
            "bioentry_id", "accession"
        )
    )
    spv_qs = ScoreParamValue.objects.filter(bioentry__biodatabase__name=proteome_name)
    funnel, survivors = _build_funnel(spv_qs, [protein_id for protein_id, _ in proteins])

    return {
        "cell": _build_cell(spv_qs, len(proteins)),
        "funnel": funnel,
        "ring": _build_ring(assembly_name, proteins, survivors) if survivors else None,
    }


def refresh_genome_visuals(assembly_name):
    data = _build(assembly_name)
    cache.set(_cache_key(assembly_name), data, OVERVIEW_CACHE_TTL_SECONDS)
    return data


def build_genome_visuals(assembly_name, proteins_url):
    """Cached drawing data plus the protein-table links for this genome."""
    data = cache.get(_cache_key(assembly_name))
    if data is None:
        data = refresh_genome_visuals(assembly_name)
    data = dict(data)
    if data.get("cell"):
        data["cell"] = {
            **data["cell"],
            "regions": [
                {
                    **region,
                    "url": protein_list_filter_url(proteins_url, [region["filter"]])
                    if region["filter"]
                    else "",
                }
                for region in data["cell"]["regions"]
            ],
        }
    if data.get("funnel"):
        data["funnel"] = [
            {**step, "url": protein_list_filter_url(proteins_url, step["filters"])}
            for step in data["funnel"]
        ]
    return data
