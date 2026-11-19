"""Groups exported table columns into reading blocks (structure, metabolism,
...), so related columns sit next to each other in CSV/Excel exports.

ScoreParam.category is not consistent enough on its own (pocket columns are
"Pocket" or "Structure", curated metabolism has its own category, imported
columns may have none), so the block comes from the category and, failing
that, from the column name."""

BLOCK_PROTEIN = "Protein"
BLOCK_FUNCTION = "Function"
BLOCK_STRUCTURE = "Structure & pockets"
BLOCK_LIGANDS = "Ligands"
BLOCK_OFF_TARGET = "Off-target"
BLOCK_ESSENTIALITY = "Essentiality"
BLOCK_CONSERVATION = "Conservation"
BLOCK_LOCALIZATION = "Localization"
BLOCK_METABOLISM = "Metabolism"
BLOCK_CUSTOM = "Custom data"
BLOCK_OTHER = "Other"

EXPORT_BLOCK_ORDER = (
    BLOCK_PROTEIN,
    BLOCK_FUNCTION,
    BLOCK_STRUCTURE,
    BLOCK_LIGANDS,
    BLOCK_OFF_TARGET,
    BLOCK_ESSENTIALITY,
    BLOCK_CONSERVATION,
    BLOCK_LOCALIZATION,
    BLOCK_METABOLISM,
    BLOCK_CUSTOM,
    BLOCK_OTHER,
)

FIXED_COLUMN_BLOCKS = {
    "Rank": BLOCK_PROTEIN,
    "Protein": BLOCK_PROTEIN,
    "Description": BLOCK_PROTEIN,
    "Gene": BLOCK_PROTEIN,
    "Score": BLOCK_PROTEIN,
    "EC": BLOCK_FUNCTION,
    "GO": BLOCK_FUNCTION,
    "Structure": BLOCK_STRUCTURE,
    "Metabolism": BLOCK_METABOLISM,
}

_CATEGORY_BLOCKS = {
    "custom": BLOCK_CUSTOM,
    "shared by users": BLOCK_CUSTOM,
    "pocket": BLOCK_STRUCTURE,
    "structure": BLOCK_STRUCTURE,
    "ligands": BLOCK_LIGANDS,
    "chembl": BLOCK_LIGANDS,
    "zinc": BLOCK_LIGANDS,
    "pdb": BLOCK_LIGANDS,
    "pubchem": BLOCK_LIGANDS,
    "cheminformatics": BLOCK_LIGANDS,
    "off-target": BLOCK_OFF_TARGET,
    "essentiality": BLOCK_ESSENTIALITY,
    "conservation": BLOCK_CONSERVATION,
    "localization": BLOCK_LOCALIZATION,
    "function": BLOCK_FUNCTION,
    "protein": BLOCK_PROTEIN,
}

_METABOLISM_NAMES = {"s_gene", "reaction_support", "n_reactions", "quadrant", "priority"}

# (block, name prefixes, name substrings), checked in order.
_NAME_RULES = (
    (BLOCK_METABOLISM, ("ptools_", "metabolic_"), ()),
    (BLOCK_STRUCTURE, (), ("druggability", "p2rank", "plddt", "pocket", "structure")),
    (BLOCK_LIGANDS, (), ("binder", "ligand", "chembl", "zinc")),
    (BLOCK_OFF_TARGET, ("human_", "gut_microbiome"), ("offtarget", "off_target")),
    (BLOCK_ESSENTIALITY, ("deg_", "hit_in_deg"), ("essential",)),
    (BLOCK_CONSERVATION, ("core_",), ()),
    (BLOCK_LOCALIZATION, (), ("localization", "psort")),
)


def column_block(name, category=""):
    """Reading block for one exported column."""
    if name in FIXED_COLUMN_BLOCKS:
        return FIXED_COLUMN_BLOCKS[name]
    category = str(category or "").strip().lower()
    lowered = str(name or "").strip().lower()
    if category in ("custom", "shared by users"):
        return BLOCK_CUSTOM
    if "metabol" in category or lowered in _METABOLISM_NAMES:
        return BLOCK_METABOLISM
    for block, prefixes, substrings in _NAME_RULES:
        if lowered.startswith(prefixes) or any(token in lowered for token in substrings):
            return block
    return _CATEGORY_BLOCKS.get(category, BLOCK_OTHER)


def group_columns_by_block(headers, rows, categories=None):
    """Reorder columns block by block (EXPORT_BLOCK_ORDER), keeping the
    original order inside each block. `categories` maps column name to
    ScoreParam.category. Returns (headers, rows, blocks), where blocks[i] is
    the block label of headers[i]."""
    categories = categories or {}
    blocks = [column_block(h, categories.get(h, "")) for h in headers]
    order = sorted(range(len(headers)), key=lambda i: (EXPORT_BLOCK_ORDER.index(blocks[i]), i))
    return (
        [headers[i] for i in order],
        [[row[i] if i < len(row) else "" for i in order] for row in rows],
        [blocks[i] for i in order],
    )
