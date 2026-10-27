"""Synthesis routes for a ligand: patent reactions (USPTO-50K, PaRoutes) whose
product is the ligand or a close analog, loaded by predict_ligand_reactions."""

from __future__ import annotations

import re

from django.core.cache import cache
from rdkit.Chem import rdChemReactions
from rdkit.Chem.Draw import rdMolDraw2D

from tpweb.models.LigandReaction import LigandReaction, ligand_smiles_key

MAX_ROUTES = 12
REACTION_SVG_CACHE_TTL_SECONDS = 7 * 24 * 3600
# NameRxn / Schneider superclasses.
REACTION_CLASSES = {
    1: "Heteroatom alkylation and arylation",
    2: "Acylation",
    3: "C–C bond formation",
    4: "Heterocycle formation",
    5: "Protection",
    6: "Deprotection",
    7: "Reduction",
    8: "Oxidation",
    9: "Functional group interconversion",
    10: "Functional group addition",
    11: "Resolution",
    12: "Miscellaneous",
}
DB_LABELS = dict(LigandReaction.DB_CHOICES)


def patent_number(reaction_id):
    """'US06413981B1;;562059' or 'US20020142971A1;0090;39985' -> the patent number."""
    number = (reaction_id or "").split(";")[0].strip()
    return re.sub(r"^US0+", "US", number)


def patent_url(reaction_id):
    number = patent_number(reaction_id)
    return f"https://patents.google.com/patent/{number}" if number.startswith("US") else ""


def reaction_svg(reactants, product):
    try:
        rxn = rdChemReactions.ReactionFromSmarts(f"{reactants}>>{product}", useSmiles=True)
    except ValueError:
        return ""
    molecules = rxn.GetNumReactantTemplates() + rxn.GetNumProductTemplates()
    drawer = rdMolDraw2D.MolDraw2DSVG(min(200 * molecules + 60, 1100), 200)
    drawer.DrawReaction(rxn)
    drawer.FinishDrawing()
    return drawer.GetDrawingText()


def _cached_svg(reaction):
    key = f"Target:reaction_svg:{reaction.pk}"
    svg = cache.get(key)
    if svg is None:
        svg = reaction_svg(reaction.reactants, reaction.product)
        cache.set(key, svg, REACTION_SVG_CACHE_TTL_SECONDS)
    return svg


def ligand_routes(smiles):
    """Routes for one ligand, exact matches first; [] when none were found."""
    if not smiles:
        return []
    routes = []
    by_reaction = {}
    for reaction in LigandReaction.objects.filter(smiles_key=ligand_smiles_key(smiles))[
        :MAX_ROUTES
    ]:
        patent = {
            "number": patent_number(reaction.reaction_id),
            "url": patent_url(reaction.reaction_id),
        }
        # The same reaction reported in several patents is one route.
        same = by_reaction.get((reaction.reactants, reaction.product))
        if same is not None:
            if patent["number"] not in {p["number"] for p in same["patents"]}:
                same["patents"].append(patent)
            continue
        class_label = REACTION_CLASSES.get(reaction.reaction_class, "")
        name = reaction.reaction_name if reaction.reaction_name != class_label else ""
        route = {
            "db": reaction.db,
            "db_label": DB_LABELS.get(reaction.db, reaction.db),
            "is_exact": reaction.is_exact,
            "similarity_pct": (
                round(reaction.similarity * 100) if reaction.similarity is not None else None
            ),
            "class_label": class_label,
            "name": name,
            "patents": [patent],
            "reagents": reaction.reagents,
            "svg": _cached_svg(reaction),
        }
        by_reaction[(reaction.reactants, reaction.product)] = route
        routes.append(route)
    return routes


def reactions_loaded():
    return LigandReaction.objects.exists()
