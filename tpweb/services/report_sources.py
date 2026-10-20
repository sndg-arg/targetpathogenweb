"""Where each protein-table column comes from, for exported reports.

Kept in sync by hand with the "Data sources" page (about/data_sources.html),
which is the long-form version of the same information. Each source maps to
a reference key in REFERENCES, so a report lists only the citations for the
columns it actually contains.
"""

from tpweb.models.ScoreParam import ScoreParam
from tpweb.services.protein_list import humanize_identifier

REFERENCES = {
    "genbank": "NCBI GenBank — genome annotation as submitted (PGAP, Prokka, RAST, …).",
    "pdb": "Berman H.M. et al. The Protein Data Bank. Nucleic Acids Res. 28:235–242 (2000).",
    "alphafold_db": (
        "Varadi M. et al. AlphaFold Protein Structure Database. Nucleic Acids Res. 50:D439–D444 "
        "(2022)."
    ),
    "colabfold": (
        "Mirdita M. et al. ColabFold: making protein folding accessible to all. Nat. Methods "
        "19:679–682 (2022)."
    ),
    "interproscan": (
        "Jones P. et al. InterProScan 5: genome-scale protein function classification. "
        "Bioinformatics 30:1236–1240 (2014)."
    ),
    "uniprot": "The UniProt Consortium. UniProt: the Universal Protein Knowledgebase.",
    "fpocket": (
        "Le Guilloux V., Schmidtke P., Tuffery P. Fpocket: an open source platform for ligand "
        "pocket detection. BMC Bioinformatics 10:168 (2009)."
    ),
    "p2rank": (
        "Krivák R., Hoksza D. P2Rank: machine learning based tool for rapid and accurate "
        "prediction of ligand binding sites from protein structure. J. Cheminform. 10:39 (2018)."
    ),
    "diamond": (
        "Buchfink B., Xie C., Huson D.H. Fast and sensitive protein alignment using DIAMOND. "
        "Nat. Methods 12:59–60 (2015)."
    ),
    "deg": (
        "Luo H. et al. DEG 15, an update of the Database of Essential Genes. Nucleic Acids Res. "
        "49:D677–D686 (2021)."
    ),
    "psortb": (
        "Yu N.Y. et al. PSORTb 3.0: improved protein subcellular localization prediction. "
        "Bioinformatics 26:1608–1615 (2010)."
    ),
    "metabolism": (
        "Ramos P.I.P. et al. An integrative, multi-omics approach towards the prioritization of "
        "Klebsiella pneumoniae drug targets. Sci. Rep. 8:10755 (2018). "
        "https://doi.org/10.1038/s41598-018-28916-7"
    ),
}

FIXED_COLUMN_SOURCES = {
    "Rank": (
        "Target Pathogen",
        "Position in this export, after the active filters, sorting and scoring formula.",
        (),
    ),
    "Protein": (
        "NCBI GenBank",
        "locus_tag of each CDS in the genome's GenBank file.",
        ("genbank",),
    ),
    "Description": (
        "NCBI GenBank",
        "product qualifier as originally annotated; Target Pathogen does not modify it.",
        ("genbank",),
    ),
    "Gene": ("NCBI GenBank", "gene qualifier, when the annotation has one.", ("genbank",)),
    "Structure": (
        "PDB · AlphaFold DB · ColabFold",
        "Preferred structure in priority order: experimental (PDB), then AlphaFold DB model, "
        "then ColabFold prediction.",
        ("pdb", "alphafold_db", "colabfold"),
    ),
    "EC": (
        "InterProScan v5 + UniProt",
        "EC numbers merged from InterProScan output and UniProt curated annotations.",
        ("interproscan", "uniprot"),
    ),
    "GO": (
        "InterProScan v5 + UniProt",
        "Gene Ontology terms merged from InterProScan output and UniProt curated annotations.",
        ("interproscan", "uniprot"),
    ),
    "Metabolism": (
        "Pathway Tools / MetaFlux",
        "Genome-scale metabolic network built externally and imported per genome.",
        ("metabolism",),
    ),
    "Score": (
        "Target Pathogen",
        "Value of the active scoring formula (see the formula in the report header).",
        (),
    ),
}

# Matched against the score parameter name (lowercase), first prefix wins.
_PARAM_NAME_SOURCES = [
    ("colabfold_plddt", "ColabFold", ("colabfold",)),
    ("colabfold_druggability", "FPocket on the ColabFold model", ("fpocket", "colabfold")),
    ("colabfold_p2rank", "P2Rank on the ColabFold model", ("p2rank", "colabfold")),
    ("druggability", "FPocket", ("fpocket",)),
    ("p2rank", "P2Rank", ("p2rank",)),
    ("pocket_", "FPocket + P2Rank (derived)", ("fpocket", "p2rank")),
    ("human_", "DIAMOND/BLASTP vs. human proteome (UniProt)", ("diamond", "uniprot")),
    ("gut_microbiome", "DIAMOND vs. curated gut microbiome genomes", ("diamond",)),
    ("deg_", "DIAMOND/BLASTP vs. Database of Essential Genes", ("diamond", "deg")),
    ("hit_in_deg", "DIAMOND/BLASTP vs. Database of Essential Genes", ("diamond", "deg")),
    ("localization", "PSORTb v3", ("psortb",)),
    ("core_roary", "Roary pan-genome analysis", ()),
    ("core_corecruncher", "CoreCruncher pan-genome analysis", ()),
    ("ptools_", "Pathway Tools / MetaFlux", ("metabolism",)),
    ("metabolic_chokepoint", "Pathway Tools / MetaFlux", ("metabolism",)),
]

_CATEGORY_SOURCES = {
    "metabolism (gates)": ("Gates-project curated metabolic analysis", ()),
    "metabolism (automatic)": ("Pathway Tools / MetaFlux", ("metabolism",)),
    "custom": ("Data uploaded by the user (Add my own data)", ()),
}


def _score_param_source(name, score_param):
    lower = name.lower()
    for prefix, source, refs in _PARAM_NAME_SOURCES:
        if lower.startswith(prefix):
            return source, refs
    category = (getattr(score_param, "category", "") or "").strip().lower()
    if category in _CATEGORY_SOURCES:
        return _CATEGORY_SOURCES[category]
    return "Target Pathogen pipeline", ()


def build_report_sources(columns):
    """Return (source_rows, reference_rows) for the given exported columns:
    source_rows = [column label, source/tool, what it is], reference_rows =
    [citation] for every reference those sources use, in first-use order."""
    params = {
        sp.name: sp for sp in ScoreParam.objects.filter(name__in=list(columns)).order_by("id")
    }
    source_rows = []
    reference_keys = ["genbank"]
    for column in columns:
        if column in FIXED_COLUMN_SOURCES:
            source, description, refs = FIXED_COLUMN_SOURCES[column]
            label = column
        else:
            score_param = params.get(column)
            source, refs = _score_param_source(column, score_param)
            description = getattr(score_param, "description", "") or "-"
            label = humanize_identifier(column) or column
        source_rows.append([label, source, description])
        for key in refs:
            if key not in reference_keys:
                reference_keys.append(key)
    reference_rows = [[REFERENCES[key]] for key in reference_keys]
    return source_rows, reference_rows
