"""Shared constants/helpers for the Human Targets section.

Human proteins are a small, fixed, curated set -- not a genome upload/pipeline
entity (see CLAUDE.md "Human Targets"). `Biodatabase`/`Bioentry` (from the
external `bioseq` package) are still reused as the underlying storage
primitive since `Binders`, `BioentryStructure`, `PDB`, and the EC/GO dbxref
infra all already key off `Bioentry` -- but the one `Biodatabase` row created
here is purely an internal storage container, never surfaced via
`GenomesView`/the Genomes list/upload flow.
"""
from bioseq.models.Biodatabase import Biodatabase
from bioseq.models.Bioentry import Bioentry

# Not a real "genome" -- see module docstring. Named so the shared
# genome-slug helpers (BioIO.GENOME_PROT_POSTFIX / Biodatabase.PROT_POSTFIX
# stripping used by StructureRawView, ProteinView, etc.) keep working
# unmodified for structures loaded against this Biodatabase.
HUMAN_GENOME_SLUG = "human_curated"
HUMAN_BIODATABASE_NAME = HUMAN_GENOME_SLUG + Biodatabase.PROT_POSTFIX

# The 10 curated demo accessions target-human-web already ships data shapes
# for (see ../target-human-web/new_data/index.json).
DEMO_ACCESSIONS = [
    "A0A075B6I6",
    "O00116",
    "P10721",
    "P35318",
    "Q1AE95",
    "Q6UW68",
    "Q8NG11",
    "Q96AB6",
    "Q9H4H8",
    "Q9UBB6",
]


def get_or_create_human_biodatabase():
    biodatabase, _ = Biodatabase.objects.get_or_create(
        name=HUMAN_BIODATABASE_NAME,
        defaults={"description": "Human Targets — curated UniProt protein set"},
    )
    return biodatabase


def human_bioentries_queryset():
    """All curated human proteins, with their HumanProtein content preloaded."""
    return (
        Bioentry.objects.filter(biodatabase__name=HUMAN_BIODATABASE_NAME)
        .select_related("human_protein")
        .order_by("accession")
    )


def get_human_bioentry(accession):
    """A single curated human protein by UniProt accession, or None."""
    accession = (accession or "").strip()
    if not accession:
        return None
    return (
        Bioentry.objects.filter(
            biodatabase__name=HUMAN_BIODATABASE_NAME,
            accession=accession,
        )
        .select_related("human_protein", "biodatabase")
        .prefetch_related(
            "dbxrefs__dbxref__terms__term",
            "experimental_structure_xrefs",
            "structures__pdb",
        )
        .first()
    )
