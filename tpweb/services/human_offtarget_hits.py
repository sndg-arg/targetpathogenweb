"""Which human proteins a pathogen protein hits in FastTarget's BLASTP
off-target screen (offtarget/human_offtarget_blast.tsv, outfmt
"6 std qcovhsp qcovs", e-value <= 1e-5), stored as HumanOfftargetHit rows."""

import csv

from django.core.exceptions import ObjectDoesNotExist
from django.db import transaction
from django.urls import reverse

from bioseq.models.Biodatabase import Biodatabase
from bioseq.models.Bioentry import Bioentry
from tpweb.models.HumanOfftargetHit import HumanOfftargetHit

# Shown on the protein page: a single hit is always named; with several,
# only those above MIN_IDENTITY, best MAX_SHOWN by bit score.
MIN_IDENTITY = 10.0
MAX_SHOWN = 5
# Kept per protein, so the display rule can change without a reload.
MAX_STORED = 20

_COLUMNS = (
    "qseqid sseqid pident length mismatch gapopen qstart qend sstart send "
    "evalue bitscore qcovhsp qcovs"
).split()


def _float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _int(value):
    number = _float(value)
    return int(number) if number is not None else None


def parse_subject_id(sseqid):
    """sp|P12345|ABC_HUMAN -> (P12345, ABC_HUMAN); a bare id stays as is."""
    parts = str(sseqid or "").strip().split("|")
    if len(parts) >= 3 and parts[0] in {"sp", "tr"}:
        return parts[1], parts[2]
    return parts[0], ""


def parse_blast_hits(path):
    """{query id: [hit dicts]}, best HSP per human protein, best bit score first."""
    best = {}
    with open(path, newline="", encoding="utf-8") as handle:
        for row in csv.reader(handle, delimiter="\t"):
            if not row or row[0].strip().lower() == "qseqid":
                continue
            record = dict(zip(_COLUMNS, row, strict=False))
            identity = _float(record.get("pident"))
            evalue = _float(record.get("evalue"))
            gene = (record.get("qseqid") or "").strip()
            accession, entry_name = parse_subject_id(record.get("sseqid"))
            if not gene or not accession or identity is None or evalue is None:
                continue
            hit = {
                "human_accession": accession[:32],
                "human_entry_name": entry_name[:64],
                "identity": identity,
                "evalue": evalue,
                "bitscore": _float(record.get("bitscore")),
                "alignment_length": _int(record.get("length")),
                "query_start": _int(record.get("qstart")),
                "query_end": _int(record.get("qend")),
                "subject_start": _int(record.get("sstart")),
                "subject_end": _int(record.get("send")),
                "query_coverage": _float(record.get("qcovhsp")),
            }
            key = (gene, accession)
            current = best.get(key)
            if current is None or (hit["bitscore"] or 0) > (current["bitscore"] or 0):
                best[key] = hit
    by_gene = {}
    for (gene, _accession), hit in best.items():
        by_gene.setdefault(gene, []).append(hit)
    for gene, hits in by_gene.items():
        hits.sort(key=lambda h: (-(h["bitscore"] or 0), h["evalue"], -h["identity"]))
        by_gene[gene] = hits[:MAX_STORED]
    return by_gene


def store_human_offtarget_hits(genome_name, path):
    """Replace the genome's stored hits with those in `path`; returns the row count."""
    hits_by_gene = parse_blast_hits(path)
    bioentry_ids = dict(
        Bioentry.objects.filter(
            biodatabase__name=genome_name + Biodatabase.PROT_POSTFIX,
            accession__in=list(hits_by_gene),
        ).values_list("accession", "bioentry_id")
    )
    rows = [
        HumanOfftargetHit(bioentry_id=bioentry_ids[gene], **hit)
        for gene, hits in hits_by_gene.items()
        if gene in bioentry_ids
        for hit in hits
    ]
    with transaction.atomic():
        HumanOfftargetHit.objects.filter(
            bioentry__biodatabase__name=genome_name + Biodatabase.PROT_POSTFIX
        ).delete()
        HumanOfftargetHit.objects.bulk_create(rows, batch_size=2000)
    return len(rows)


def _span(start, end, length):
    """left/width percentages of start..end on a 1..length track."""
    if not (start and end and length):
        return None
    start, end = sorted((start, end))
    start, end = max(1, start), min(end, length)
    if end < start:
        return None
    return {
        "left": round((start - 1) / length * 100, 2),
        "width": max(round((end - start + 1) / length * 100, 2), 1),
    }


def _sequence_length(bioentry):
    try:
        return bioentry.seq.length
    except ObjectDoesNotExist:
        return None


def shown_human_hits(bioentry):
    """The hits the protein page names, with the human protein's name and link."""
    hits = list(
        HumanOfftargetHit.objects.filter(bioentry=bioentry).order_by(
            "-bitscore", "evalue", "-identity"
        )[:MAX_STORED]
    )
    if len(hits) > 1:
        hits = [hit for hit in hits if hit.identity > MIN_IDENTITY]
    hits = hits[:MAX_SHOWN]
    if not hits:
        return []

    from human_target.models import HumanProtein  # local: avoids an app import cycle

    known = {
        protein.uniprot_accession: protein
        for protein in HumanProtein.objects.filter(
            uniprot_accession__in=[hit.human_accession for hit in hits]
        ).only("uniprot_accession", "gene_symbol", "protein_name", "sequence_length")
    }

    query_length = _sequence_length(bioentry)
    shown = []
    for hit in hits:
        protein = known.get(hit.human_accession)
        if protein is not None:
            url = reverse("human_target:human_protein", kwargs={"accession": hit.human_accession})
        else:
            url = f"https://www.uniprot.org/uniprotkb/{hit.human_accession}/entry"
        shown.append(
            {
                "accession": hit.human_accession,
                "gene": (protein.gene_symbol if protein else "")
                or hit.human_entry_name.replace("_HUMAN", ""),
                "name": protein.protein_name if protein else "",
                "url": url,
                "external": protein is None,
                "identity": f"{hit.identity:.1f}%",
                "coverage": f"{hit.query_coverage:.0f}%" if hit.query_coverage is not None else "",
                "evalue": f"{hit.evalue:.1e}",
                "bitscore": f"{hit.bitscore:.0f}" if hit.bitscore is not None else "",
                "query_range": f"{hit.query_start}–{hit.query_end}"
                if hit.query_start and hit.query_end
                else "",
                "subject_range": f"{hit.subject_start}–{hit.subject_end}"
                if hit.subject_start and hit.subject_end
                else "",
                "query_start": hit.query_start,
                "query_end": hit.query_end,
                # Where the match sits on this protein and on the human one.
                "query_span": _span(hit.query_start, hit.query_end, query_length),
                "subject_span": _span(
                    hit.subject_start,
                    hit.subject_end,
                    protein.sequence_length if protein else None,
                ),
            }
        )
    return shown


def human_homolog_row(hits):
    """Architecture-map row (segments) marking where the human matches sit."""
    items = [
        {
            **hit["query_span"],
            "start": hit["query_start"],
            "end": hit["query_end"],
            "label": hit["gene"] or hit["accession"],
            "description": f"{hit['identity']} identity",
        }
        for hit in hits
        if hit.get("query_span")
    ]
    if not items:
        return None
    return {"key": "human", "label": "Human homologs", "items": items, "kind": "segments"}
