"""The protein page's Metabolic reactions section, from Recon3D
(see load_human_reactions_bulk)."""

from human_target.models.HumanReaction import HumanReaction

VISIBLE_REACTIONS = 25


def build_human_reaction_context(human_protein):
    reactions = list(
        HumanReaction.objects.filter(protein_links__human_protein=human_protein).order_by(
            "subsystem", "name", "bigg_id"
        )
    )
    subsystems = {}
    for reaction in reactions:
        key = reaction.subsystem or "Unassigned"
        subsystems[key] = subsystems.get(key, 0) + 1
    return {
        "has_reactions": bool(reactions),
        "reactions": reactions[:VISIBLE_REACTIONS],
        "more_reactions": reactions[VISIBLE_REACTIONS:],
        "total": len(reactions),
        # Largest subsystems first: they say what the protein does.
        "subsystems": sorted(subsystems.items(), key=lambda item: (-item[1], item[0])),
    }
