"""Link every curated human protein to its KEGG pathways, at proteome scale.

Scale companion to `import_human_curated_proteins.py`'s per-protein
`_load_pathways` (which reads a local `kegg_kgml/*.kgml` tree the reference
app's own pipeline produced for the 10-protein pilot). At full-proteome
scale there is no such tree, so this command fetches live from KEGG's free
REST API -- but with exactly two classes of request, not one per protein:

  1. One bulk gene->pathway link table:
     https://rest.kegg.jp/link/pathway/hsa
     (every human Entrez GeneID's pathway membership, in one response)
  2. One KGML fetch per *distinct* pathway actually needed by our proteins
     (https://rest.kegg.jp/get/<kegg_id>/kgml) -- KEGG has ~350 human
     pathways total, shared across however many thousand proteins we have,
     so this is the expensive step, not a per-protein one.

`HumanPathway` rows are shared reference data (get_or_create by kegg_id, see
its own docstring); `HumanProteinPathway` is the per-protein link, carrying
which of the pathway's own graph nodes is *this* protein (matched via its
NCBI GeneID cross-reference, already stored in `cross_references_raw` by the
UniProt ingest -- no extra network call needed to resolve it).

Usage:
    python manage.py load_human_pathways_bulk \
        [--accession P10721 --accession O00116 ...] \
        [--accession-file PATH] [--dry-run] [--sleep 0.34]

Requires outbound internet access to rest.kegg.jp (same login-node-only
assumption the other remote stages make -- see CLAUDE.md).
"""

import time
import xml.etree.ElementTree as ET

import requests
from django.core.management.base import BaseCommand, CommandError

from human_target.models.HumanPathway import HumanPathway
from human_target.models.HumanProteinPathway import HumanProteinPathway
from human_target.services.human_targets import human_proteins_queryset
from human_target.services.kegg_kgml import parse_kgml_root

KEGG_LINK_URL = "https://rest.kegg.jp/link/pathway/hsa"
KEGG_KGML_URL = "https://rest.kegg.jp/get/{kegg_id}/kgml"

DEFAULT_SLEEP_SEC = 0.34
PROGRESS_EVERY = 25


def _parse_link_table(text):
    """Parse `rest.kegg.jp/link/pathway/hsa`'s tab-separated response into
    `{entrez_gene_id (bare, no "hsa:" prefix): {kegg_pathway_id (bare, no
    "path:" prefix), ...}}`. Pure function, no network/DB access -- one
    gene can belong to several pathways, hence the set."""
    mapping = {}
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        gene_ref, pathway_ref = line.split("\t")
        gene_id = gene_ref.replace("hsa:", "")
        kegg_id = pathway_ref.replace("path:", "")
        mapping.setdefault(gene_id, set()).add(kegg_id)
    return mapping


def _gene_ids_from_cross_references(cross_references_raw):
    """This protein's NCBI GeneID cross-reference(s), bare (no "hsa:"
    prefix) -- usually exactly one, kept as a list defensively since
    nothing guarantees uniqueness in the raw UniProt xref data."""
    return [
        (xref.get("id") or "").strip()
        for xref in cross_references_raw or []
        if xref.get("database") == "GeneID" and (xref.get("id") or "").strip()
    ]


class Command(BaseCommand):
    help = (
        "Link every curated human protein to its KEGG pathways via one bulk "
        "gene->pathway link table plus one KGML fetch per distinct pathway "
        "(rest.kegg.jp) -- not one fetch per protein."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--accession",
            action="append",
            default=None,
            help="Restrict to this accession. Repeatable. Default: every curated human protein.",
        )
        parser.add_argument(
            "--accession-file",
            default=None,
            metavar="PATH",
            help="Newline-separated file of accessions, added to --accession (for a small trial batch).",
        )
        parser.add_argument(
            "--dry-run", action="store_true", help="Fetch and parse, but write nothing."
        )
        parser.add_argument(
            "--sleep",
            type=float,
            default=DEFAULT_SLEEP_SEC,
            help=f"Seconds to sleep between per-pathway KGML fetches (default {DEFAULT_SLEEP_SEC}).",
        )

    def handle(self, *args, **options):
        accessions = list(options["accession"] or [])
        if options["accession_file"]:
            with open(options["accession_file"], encoding="utf-8") as f:
                accessions.extend(line.strip() for line in f if line.strip())

        proteins_qs = human_proteins_queryset()
        if accessions:
            proteins_qs = proteins_qs.filter(uniprot_accession__in=accessions)
        proteins = list(proteins_qs)
        if not proteins:
            raise CommandError("No matching human proteins found.")

        gene_to_proteins = {}
        for protein in proteins:
            for gene_id in _gene_ids_from_cross_references(protein.cross_references_raw):
                gene_to_proteins.setdefault(gene_id, []).append(protein)

        if not gene_to_proteins:
            self.stdout.write(
                self.style.WARNING(
                    "None of the selected proteins have a GeneID cross-reference -- nothing to link."
                )
            )
            return

        self.stdout.write(
            f"{len(proteins)} proteins, {len(gene_to_proteins)} distinct GeneIDs. "
            "Fetching KEGG gene->pathway links ..."
        )
        try:
            link_resp = requests.get(KEGG_LINK_URL, timeout=120)
            link_resp.raise_for_status()
        except requests.RequestException as exc:
            raise CommandError(f"Could not reach KEGG ({KEGG_LINK_URL}): {exc}") from exc
        gene_to_kegg_ids = _parse_link_table(link_resp.text)

        kegg_to_genes = {}
        for gene_id in gene_to_proteins:
            for kegg_id in gene_to_kegg_ids.get(gene_id, ()):
                kegg_to_genes.setdefault(kegg_id, set()).add(gene_id)

        if not kegg_to_genes:
            self.stdout.write(
                self.style.WARNING("No KEGG pathway membership found for the selected proteins.")
            )
            return

        self.stdout.write(
            f"{len(kegg_to_genes)} distinct pathways to fetch (vs. {len(proteins)} proteins)."
        )

        linked = 0
        failed = 0
        total = len(kegg_to_genes)
        for i, kegg_id in enumerate(sorted(kegg_to_genes), start=1):
            if i > 1:
                time.sleep(options["sleep"])

            try:
                kgml_resp = requests.get(KEGG_KGML_URL.format(kegg_id=kegg_id), timeout=60)
                kgml_resp.raise_for_status()
                root = ET.fromstring(kgml_resp.text)
                graph = parse_kgml_root(root)
            except (requests.RequestException, ET.ParseError) as exc:
                self.stderr.write(f"  {kegg_id}: failed to fetch/parse ({exc}), skipping")
                failed += 1
                continue

            title = root.get("title", "")
            entry_count = len(root.findall("entry"))
            relation_count = len(root.findall("relation"))
            member_genes = kegg_to_genes[kegg_id]

            if options["dry_run"]:
                self.stdout.write(
                    f"  [dry-run] {kegg_id} ({title}): would link {len(member_genes)} gene(s)"
                )
                continue

            pathway, _ = HumanPathway.objects.update_or_create(
                kegg_id=kegg_id,
                defaults={
                    "title": title,
                    "entry_count": entry_count,
                    "relation_count": relation_count,
                    "graph_json": graph,
                },
            )

            for gene_id in member_genes:
                target_kegg_gene = f"hsa:{gene_id}"
                highlighted_node_id = ""
                for node in graph["nodes"]:
                    if target_kegg_gene in node["kegg_ids"]:
                        highlighted_node_id = node["id"]
                        break
                for protein in gene_to_proteins[gene_id]:
                    HumanProteinPathway.objects.update_or_create(
                        human_protein=protein,
                        pathway=pathway,
                        defaults={"highlighted_node_id": highlighted_node_id},
                    )
                    linked += 1

            if i % PROGRESS_EVERY == 0 or i == total:
                self.stdout.write(f"  ... {i}/{total} pathways processed")

        self.stdout.write(
            self.style.SUCCESS(f"pathways={total - failed} failed={failed} links={linked}")
        )
