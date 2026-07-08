"""
fetch_kegg_pathway_map - one-off refresh of the bundled KEGG reaction->pathway reference file.

KEGG reaction<->pathway membership is global reference chemistry, not organism-specific, so this
is fetched once (via KEGG's free REST API) and committed to the repo as
tpweb/data/kegg_reaction_pathways.json. `load_metabolism` reads that file at import time instead
of hitting the network per genome.

Usage
-----
python manage.py fetch_kegg_pathway_map [--out tpweb/data/kegg_reaction_pathways.json]

Requires outbound internet access to rest.kegg.jp (not available in every environment -
run this from a machine that has it, then commit the resulting JSON file).
"""

import json
import os

import requests
from django.core.management.base import BaseCommand, CommandError

KEGG_LINK_URL = "https://rest.kegg.jp/link/pathway/reaction"
KEGG_PATHWAY_LIST_URL = "https://rest.kegg.jp/list/pathway"

DEFAULT_OUT = os.path.join("tpweb", "data", "kegg_reaction_pathways.json")


class Command(BaseCommand):
    help = "Fetch the KEGG reaction->pathway mapping and write it to a bundled JSON reference file."

    def add_arguments(self, parser):
        parser.add_argument("--out", default=DEFAULT_OUT, metavar="PATH")

    def handle(self, *args, **options):
        out_path = options["out"]

        self.stdout.write("Fetching KEGG pathway names ...")
        try:
            pathway_resp = requests.get(KEGG_PATHWAY_LIST_URL, timeout=60)
            pathway_resp.raise_for_status()
        except requests.RequestException as exc:
            raise CommandError(f"Could not reach KEGG ({KEGG_PATHWAY_LIST_URL}): {exc}")

        pathway_names = {}
        for line in pathway_resp.text.splitlines():
            if not line.strip():
                continue
            kegg_id, name = line.split("\t", 1)
            pathway_names[kegg_id.replace("path:", "")] = name

        self.stdout.write(f"  {len(pathway_names)} pathways.")

        self.stdout.write("Fetching KEGG reaction->pathway links ...")
        try:
            link_resp = requests.get(KEGG_LINK_URL, timeout=120)
            link_resp.raise_for_status()
        except requests.RequestException as exc:
            raise CommandError(f"Could not reach KEGG ({KEGG_LINK_URL}): {exc}")

        reaction_pathways = {}
        for line in link_resp.text.splitlines():
            if not line.strip():
                continue
            reaction_ref, pathway_ref = line.split("\t")
            reaction_id = reaction_ref.replace("rn:", "")
            pathway_id = pathway_ref.replace("path:", "")
            # Skip the organism-specific "rn" reference maps (rn01100 etc. are fine to keep,
            # they're still generic reference pathways, not organism-scoped).
            reaction_pathways.setdefault(reaction_id, []).append(pathway_id)

        self.stdout.write(f"  {len(reaction_pathways)} reactions with pathway membership.")

        payload = {
            "pathway_names": pathway_names,
            "reaction_pathways": reaction_pathways,
        }

        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, sort_keys=True)

        self.stdout.write(self.style.SUCCESS(f"Wrote {out_path}"))
