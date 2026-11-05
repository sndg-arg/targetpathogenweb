"""Multi-step synthesis plans for a ligand, precomputed by expand_ligand_routes
on the cluster and loaded by load_ligand_routes.

ligand_reactions.py answers "what single reaction makes this compound?";
this answers "what sequence of reactions gets there from building blocks?".
"""

from __future__ import annotations

from django.core.cache import cache

from tpweb.models.LigandReaction import ligand_smiles_key
from tpweb.models.LigandRoutePlan import LigandRoutePlan
from tpweb.services.ligand_reactions import (
    REACTION_CLASSES,
    REACTION_SVG_CACHE_TTL_SECONDS,
    patent_number,
    patent_url,
    reaction_svg,
)


def _cached_svg(plan_id, position, reactants, product):
    key = f"Target:route_svg:{plan_id}:{position}"
    svg = cache.get(key)
    if svg is None:
        svg = reaction_svg(reactants, product)
        cache.set(key, svg, REACTION_SVG_CACHE_TTL_SECONDS)
    return svg


def _render(node, plan_id, counter):
    """One stored node -> the dict the template draws, precursors first so the
    step numbers run in the order a chemist would carry them out."""
    precursors = [_render(child, plan_id, counter) for child in node.get("precursors") or []]
    reaction = node.get("reaction")
    rendered = {
        "smiles": node.get("smiles", ""),
        "available": bool(node.get("available")),
        "precursors": precursors,
        "step": None,
        "class_label": "",
        "name": "",
        "reagents": "",
        "patent": None,
        "svg": "",
    }
    if not reaction:
        return rendered

    counter["n"] += 1
    position = counter["n"]
    class_label = REACTION_CLASSES.get(reaction.get("class"), "")
    name = reaction.get("name") or ""
    number = patent_number(reaction.get("id"))
    rendered.update(
        {
            "step": position,
            "class_label": class_label,
            "name": "" if name == class_label else name,
            "reagents": reaction.get("reagents") or "",
            "patent": (
                {"number": number, "url": patent_url(reaction.get("id"))} if number else None
            ),
            "svg": _cached_svg(
                plan_id, position, reaction.get("reactants", ""), node.get("smiles", "")
            ),
        }
    )
    return rendered


def route_plan(smiles):
    """The stored plan for one ligand, ready to draw; None when there is none."""
    if not smiles:
        return None
    plan = LigandRoutePlan.objects.filter(smiles_key=ligand_smiles_key(smiles)).first()
    if plan is None or not plan.tree:
        return None
    counter = {"n": 0}
    tree = _render(plan.tree, plan.id, counter)
    if tree["step"] is None:
        return None
    return {
        "solved": plan.solved,
        "depth": plan.depth,
        "steps": plan.steps,
        "leaves": plan.leaves,
        "available_leaves": plan.available_leaves,
        "open_leaves": max(plan.leaves - plan.available_leaves, 0),
        "tree": tree,
    }


def plan_summaries(smiles_keys):
    """{smiles_key: {"steps", "solved"}} for the keys that have a plan."""
    keys = list(smiles_keys)
    if not keys:
        return {}
    return {
        key: {"steps": steps, "solved": solved}
        for key, steps, solved in LigandRoutePlan.objects.filter(smiles_key__in=keys).values_list(
            "smiles_key", "steps", "solved"
        )
    }


def plans_loaded():
    return LigandRoutePlan.objects.exists()
