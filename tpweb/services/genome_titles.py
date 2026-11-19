"""One way to name a genome everywhere: "Klebsiella pneumoniae (Kp13)", with
its GenBank/RefSeq accession shown apart (genome_tags filters).

The title comes from the genome's GenBank definition line, so genomes loaded
under a short internal name (KpKP13) read the same as those loaded under an
accession (GCA_030061715.1).
"""

import re

from django.core.cache import cache

from bioseq.models.Biodatabase import Biodatabase
from bioseq.models.Bioentry import Bioentry
from tpweb.services.genome_workspace import display_genome_name

CACHE_KEY = "tpw:genome-titles:v1"
CACHE_SECONDS = 300

# GCA_/GCF_ assemblies, RefSeq (NC_/NZ_...) and plain INSDC (CP003200.1).
_ACCESSION = re.compile(r"^(GC[AF]_\d+\.\d+|[A-Z]{2}_[A-Z]*\d+(\.\d+)?|[A-Z]{1,2}\d{5,8}(\.\d+)?)$")
_TRAILER = re.compile(
    r",?\s*\b(chromosome|plasmid|complete (genome|sequence)|genome assembly|whole genome)\b.*$",
    re.IGNORECASE,
)
_BINOMIAL = re.compile(r"^[A-Z][a-z]+ [a-z]+$")
_SUBSPECIES = re.compile(r"^subsp\.\s+\S+\s*", re.IGNORECASE)
_STRAIN_WORD = re.compile(r"^(strain|str\.)\s+", re.IGNORECASE)


def parse_genome_title(description):
    """Organism and strain from a GenBank definition line, e.g.
    Klebsiella pneumoniae strain VA569 chromosome, complete genome
    -> ("Klebsiella pneumoniae", "VA569")."""
    words = str(description or "").split()
    # Only a GenBank-style line (Genus species ..., complete genome) is
    # trusted; anything else keeps the genome's own name as its title.
    if len(words) < 3 or not _BINOMIAL.match(" ".join(words[:2])):
        return "", ""
    rest = " ".join(words[2:])
    if not _TRAILER.search(rest):
        return "", ""
    organism = " ".join(words[:2])
    rest = _TRAILER.sub("", rest).strip(" ,")
    rest = _STRAIN_WORD.sub("", _SUBSPECIES.sub("", rest)).strip(" ,")
    return organism, rest


def is_accession(value):
    return bool(_ACCESSION.match(str(value or "").strip()))


def _reference_accessions(biodatabase_ids):
    """First sequence record of each genome (its chromosome), as accession.version."""
    accessions = {}
    rows = (
        Bioentry.objects.filter(biodatabase_id__in=biodatabase_ids)
        .order_by("biodatabase_id", "bioentry_id")
        .values_list("biodatabase_id", "accession", "version")
    )
    for biodatabase_id, accession, version in rows:
        if biodatabase_id in accessions:
            continue
        accession = str(accession or "").strip()
        if accession and version and "." not in accession:
            accession = f"{accession}.{version}"
        accessions[biodatabase_id] = accession
    return accessions


def _build_titles():
    genomes = list(
        Biodatabase.objects.exclude(name__endswith="_prots")
        .exclude(name__endswith="_rnas")
        .values_list("biodatabase_id", "name", "description")
    )
    references = _reference_accessions([row[0] for row in genomes])
    titles = {}
    for biodatabase_id, name, description in genomes:
        display = display_genome_name(name)
        organism, strain = parse_genome_title(description)
        if organism:
            title = f"{organism} ({strain})" if strain else organism
        else:
            title = display
        reference = references.get(biodatabase_id, "")
        accession = (
            display if is_accession(display) else (reference if is_accession(reference) else "")
        )
        entry = {
            "title": title,
            "organism": organism,
            "strain": strain,
            "accession": accession,
            "description": description or "",
        }
        titles[name] = entry
        titles.setdefault(display, entry)
    return titles


def genome_titles():
    titles = cache.get(CACHE_KEY)
    if titles is None:
        titles = _build_titles()
        cache.set(CACHE_KEY, titles, CACHE_SECONDS)
    return titles


def genome_info(name):
    """{"title", "organism", "strain", "accession", "description"} for a genome's
    internal or display name; the name itself as title when it isn't known."""
    key = str(name or "").strip()
    return genome_titles().get(key) or {
        "title": key,
        "organism": "",
        "strain": "",
        "accession": key if is_accession(key) else "",
        "description": "",
    }


def genome_title(name):
    return genome_info(name)["title"]
