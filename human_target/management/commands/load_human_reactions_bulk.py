"""Load Recon3D metabolic reactions and link them to human proteins.

Recon3D (BiGG, https://bigg.ucsd.edu/models/Recon3D) names genes by NCBI
GeneID plus a transcript suffix ("5313_AT1"). Our proteins already carry
their GeneID cross-reference from the UniProt ingest, so the match needs no
extra lookup -- the same join load_human_pathways_bulk uses for KEGG.

Usage:
    python manage.py load_human_reactions_bulk [--file Recon3D.json] [--dry-run]

Without --file it downloads the model JSON (~8 MB) from BiGG. Re-running
replaces every reaction and link.
"""

import json
import re
from pathlib import Path

import requests
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from human_target.models.HumanProteinReaction import HumanProteinReaction
from human_target.models.HumanReaction import HumanReaction
from human_target.services.human_targets import human_proteins_queryset

RECON3D_URL = "https://bigg.ucsd.edu/static/models/Recon3D.json"
_GENE_RE = re.compile(r"\b(\d+)_AT\d+\b")


def _coefficient(value):
    value = abs(value)
    if value == 1:
        return ""
    return f"{int(value) if float(value).is_integer() else value:g} "


def _side(items, names, compartments, show_compartment):
    parts = []
    for met_id, coefficient in items:
        label = names.get(met_id) or met_id
        if show_compartment and met_id in compartments:
            label += f" [{compartments[met_id]}]"
        parts.append(_coefficient(coefficient) + label)
    return " + ".join(parts) or "∅"


def render_equation(reaction, names, met_compartments):
    """'2 ATP + ... → ...' with metabolite names; compartments shown only
    when the reaction crosses them (a transport would read 'X → X')."""
    mets = reaction.get("metabolites") or {}
    spanned = {met_compartments.get(met_id) for met_id in mets} - {None}
    show = len(spanned) > 1
    lower = reaction.get("lower_bound", 0)
    upper = reaction.get("upper_bound", 0)
    left = [(m, c) for m, c in mets.items() if c < 0]
    right = [(m, c) for m, c in mets.items() if c > 0]
    if upper <= 0 < -lower:
        # Only runs backwards: write it the way it runs.
        left, right = right, left
    arrow = "⇌" if lower < 0 < upper else "→"
    return (
        f"{_side(left, names, met_compartments, show)} {arrow} "
        f"{_side(right, names, met_compartments, show)}"
    ), arrow == "⇌"


def parse_recon3d(model):
    """Recon3D JSON -> (reactions, {gene_id: {bigg_id}}). Pure."""
    names = {met["id"]: met.get("name") or met["id"] for met in model.get("metabolites", [])}
    met_compartments = {met["id"]: met.get("compartment") for met in model.get("metabolites", [])}
    compartment_names = model.get("compartments") or {}
    reactions = []
    genes = {}
    for reaction in model.get("reactions", []):
        rule = reaction.get("gene_reaction_rule") or ""
        gene_ids = set(_GENE_RE.findall(rule))
        if not gene_ids:
            continue
        equation, reversible = render_equation(reaction, names, met_compartments)
        spanned = sorted(
            {met_compartments.get(m) for m in reaction.get("metabolites") or {}} - {None}
        )
        reactions.append(
            {
                "bigg_id": reaction["id"][:64],
                "name": (reaction.get("name") or "")[:512],
                "equation": equation,
                "subsystem": (reaction.get("subsystem") or "")[:255],
                "compartments": ", ".join(compartment_names.get(c, c) for c in spanned)[:255],
                "reversible": reversible,
                "gene_rule": rule,
            }
        )
        for gene_id in gene_ids:
            genes.setdefault(gene_id, set()).add(reaction["id"][:64])
    return reactions, genes


class Command(BaseCommand):
    help = "Load Recon3D reactions and link them to human proteins by GeneID."

    def add_arguments(self, parser):
        parser.add_argument("--file", help="Local Recon3D.json (default: download from BiGG)")
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        if options["file"]:
            model = json.loads(Path(options["file"]).read_text(encoding="utf-8"))
        else:
            try:
                response = requests.get(RECON3D_URL, timeout=180)
                response.raise_for_status()
            except requests.RequestException as exc:
                raise CommandError(f"Could not download Recon3D: {exc}") from exc
            model = response.json()
        reactions, genes = parse_recon3d(model)
        if not reactions:
            raise CommandError("No gene-associated reactions found; is this Recon3D JSON?")

        links = set()
        for protein_id, cross_refs in human_proteins_queryset().values_list(
            "id", "cross_references_raw"
        ):
            for xref in cross_refs or []:
                if xref.get("database") == "GeneID":
                    for bigg_id in genes.get((xref.get("id") or "").strip(), ()):
                        links.add((protein_id, bigg_id))
        self.stdout.write(
            f"Recon3D: {len(reactions)} gene-associated reactions; {len(links)} links "
            f"to {len({protein for protein, _ in links})} human proteins."
        )
        if options["dry_run"]:
            return

        with transaction.atomic():
            HumanProteinReaction.objects.all().delete()
            HumanReaction.objects.all().delete()
            created = HumanReaction.objects.bulk_create(
                [HumanReaction(**row) for row in reactions], batch_size=1000
            )
            by_bigg = {item.bigg_id: item.id for item in created}
            HumanProteinReaction.objects.bulk_create(
                [
                    HumanProteinReaction(human_protein_id=protein, reaction_id=by_bigg[bigg])
                    for protein, bigg in links
                ],
                batch_size=5000,
            )
        self.stdout.write(self.style.SUCCESS("Recon3D reactions loaded."))
