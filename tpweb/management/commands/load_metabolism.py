"""
load_metabolism - import a genome-scale metabolic network into Target.

Ingests three files produced by the BioCyc/Pathway Tools MetaFlux metabolism pipeline
(`fasttarget/ftscripts/pathways.py:run_metabolism_ptools`) for a single genome:

  --sbml PATH                  MetaFlux SBML export (reactions, EC/KEGG annotations,
                                gene-reaction associations).
  --metabolic-results-tsv PATH Per-gene results table with columns: gene,
                                PTOOLS_betweenness_centrality, PTOOLS_edges,
                                PTOOLS_producing_chokepoints, PTOOLS_consuming_chokepoints,
                                PTOOLS_both_chokepoints.
  --network-sif PATH           Reaction-reaction adjacency graph ("A <relation> B" lines).

Populates MetabolicReaction / GeneReactionLink / MetabolicReactionEdge / MetabolicSpecies /
ReactionParticipant, attaches KEGG MetabolicPathway membership (via the bundled
tpweb/data/kegg_reaction_pathways.json reference file - run `fetch_kegg_pathway_map` first to
(re)generate it), flags currency/ubiquitous metabolites (tpweb/data/currency_metabolites.json,
a generic fallback list - pass a real organism-specific one via fasttarget's ubiquitous-compounds
export when available), and feeds the per-gene scalar metrics into the generic
ScoreParam/ScoreParamValue system via `load_score_values` ("PTOOLS_betweenness_centrality",
"PTOOLS_edges", "metabolic_chokepoint").

Usage
-----
python manage.py load_metabolism public__KpATCC43816 \\
    --sbml KpATCC43816.sbml \\
    --metabolic-results-tsv KpATCC43816_results_table.tsv \\
    --network-sif network.sif \\
    [--dry-run]

Every non-dry-run import replaces the existing metabolic rows for the genome. `--overwrite`
is still accepted for compatibility with older scripts.
"""

import json
import os
import re
import sys
import tempfile
import xml.etree.ElementTree as ET

import pandas as pd
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from tqdm import tqdm

from django.contrib.auth import get_user_model

from bioseq.models.Biodatabase import Biodatabase
from bioseq.models.Bioentry import Bioentry
from tpweb.models.Metabolism import (
    GeneReactionLink,
    MetabolicImportRun,
    MetabolicPathway,
    MetabolicReaction,
    MetabolicReactionEdge,
    MetabolicSpecies,
    ReactionParticipant,
)

SBML_NS = {
    "sbml": "http://www.sbml.org/sbml/level3/version1/core",
    "fbc": "http://www.sbml.org/sbml/level3/version1/fbc/version2",
    "rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
    "bqbiol": "http://biomodels.net/biology-qualifiers/",
}

KEGG_PATHWAY_MAP_PATH = os.path.join("tpweb", "data", "kegg_reaction_pathways.json")
CURRENCY_METABOLITES_PATH = os.path.join("tpweb", "data", "currency_metabolites.json")

# KEGG's own "1.0 Global and overview maps" category (https://www.kegg.jp/kegg/pathway.html) --
# these are cross-cutting reference charts (nearly every metabolic reaction belongs to
# "Metabolic pathways" map01100), not specific biological pathways. Attaching them would let
# them dominate every reaction/protein's pathway list and any ranking by pathway size, drowning
# out the specific, actionable pathways (e.g. "Lysine biosynthesis") we actually want to surface.
KEGG_OVERVIEW_MAP_IDS = {
    "map01100",
    "map01110",
    "map01120",
    "map01200",
    "map01210",
    "map01212",
    "map01230",
    "map01232",
    "map01250",
    "map01240",
    "map01220",
}

CHOKEPOINT_COLUMNS = {
    "PTOOLS_producing_chokepoints": GeneReactionLink.CHOKEPOINT_PRODUCING,
    "PTOOLS_consuming_chokepoints": GeneReactionLink.CHOKEPOINT_CONSUMING,
    "PTOOLS_both_chokepoints": GeneReactionLink.CHOKEPOINT_BOTH,
}


def _tag(elem):
    return elem.tag.split("}")[-1]


def _walk_gpr(elem, gene_products):
    """Return (set of locus tags, human-readable boolean expression string)."""
    tag = _tag(elem)
    if tag == "geneProductRef":
        gp_id = elem.get(f"{{{SBML_NS['fbc']}}}geneProduct")
        gp = gene_products.get(gp_id)
        locus = gp["locus_tag"] if gp else gp_id
        return {locus}, locus
    if tag in ("and", "or"):
        genes = set()
        parts = []
        for child in elem:
            child_genes, child_expr = _walk_gpr(child, gene_products)
            genes |= child_genes
            parts.append(child_expr)
        joiner = " and " if tag == "and" else " or "
        return genes, "(" + joiner.join(parts) + ")"
    return set(), ""


def _count_isoenzymes(root_elem):
    """Number of independent gene(s)/complex(es) that can catalyze this reaction on their
    own. A top-level "or" means true isoenzyme redundancy (any branch suffices); a bare
    gene ref or a top-level "and" (obligate complex) means there's exactly one way in."""
    if root_elem is None:
        return 0
    if _tag(root_elem) == "or":
        return len(root_elem)
    return 1


def _annotation_resources(elem):
    """Yield identifiers.org resource URIs referenced in a <bqbiol:is> annotation block."""
    for li in elem.findall(f".//{{{SBML_NS['rdf']}}}li"):
        resource = li.get(f"{{{SBML_NS['rdf']}}}resource")
        if resource:
            yield resource


def _decode_sbml_id(raw_id):
    """BioCyc encodes each non-alphanumeric byte in SBML ids as __<decimal-ascii>__
    (e.g. 45 -> '-', 95 -> '_'). Species ids/names are used as-is elsewhere (they already
    match speciesReference@species exactly), this is only needed to recover the plain
    BioCyc frame id for currency-metabolite matching."""
    return re.sub(r"__(\d+)__", lambda m: chr(int(m.group(1))), raw_id)


def _species_participants(elem):
    """Return list of (species_id, stoichiometry) from a <listOfReactants>/<listOfProducts>."""
    participants = []
    for ref in elem.findall(f"{{{SBML_NS['sbml']}}}speciesReference"):
        species_id = ref.get("species")
        if not species_id:
            continue
        try:
            stoichiometry = float(ref.get("stoichiometry") or 1.0)
        except (TypeError, ValueError):
            stoichiometry = 1.0
        participants.append((species_id, stoichiometry))
    return participants


def parse_sbml(sbml_path):
    """Return ({reaction_id: {name, ec_numbers, kegg_reaction_id, reversible, genes,
    gpr_expression, isoenzyme_count, reactants, products}}, {species_id: {display_name,
    compartment}})."""
    tree = ET.parse(sbml_path)
    root = tree.getroot()

    gene_products = {}
    for gp in root.iterfind(f".//{{{SBML_NS['fbc']}}}geneProduct"):
        gp_id = gp.get(f"{{{SBML_NS['fbc']}}}id") or gp.get("metaid")
        label = gp.get(f"{{{SBML_NS['fbc']}}}label") or ""
        if gp_id and label:
            gene_products[gp_id] = {
                "locus_tag": label,
                "gene_name": gp.get(f"{{{SBML_NS['fbc']}}}name") or "",
            }

    species = {}
    for sp in root.iterfind(f".//{{{SBML_NS['sbml']}}}species"):
        species_id = sp.get("id")
        if not species_id:
            continue
        species[species_id] = {
            "display_name": sp.get("name") or species_id,
            "compartment": sp.get("compartment") or "",
        }

    reactions = {}
    for rxn in root.iterfind(f".//{{{SBML_NS['sbml']}}}reaction"):
        reaction_id = rxn.get("name") or rxn.get("id")
        if not reaction_id:
            continue

        ec_numbers = []
        kegg_reaction_id = ""
        for resource in _annotation_resources(rxn):
            if "ec-code/" in resource:
                ec_numbers.append(resource.rsplit("/", 1)[-1])
            elif "kegg.reaction/" in resource:
                kegg_reaction_id = resource.rsplit("/", 1)[-1]

        genes = set()
        gpr_expression = ""
        isoenzyme_count = 0
        gpa = rxn.find(f"{{{SBML_NS['fbc']}}}geneProductAssociation")
        if gpa is not None and len(gpa) > 0:
            genes, gpr_expression = _walk_gpr(gpa[0], gene_products)
            isoenzyme_count = _count_isoenzymes(gpa[0])

        reactants = []
        list_of_reactants = rxn.find(f"{{{SBML_NS['sbml']}}}listOfReactants")
        if list_of_reactants is not None:
            reactants = _species_participants(list_of_reactants)

        products = []
        list_of_products = rxn.find(f"{{{SBML_NS['sbml']}}}listOfProducts")
        if list_of_products is not None:
            products = _species_participants(list_of_products)

        reactions[reaction_id] = {
            "name": reaction_id,
            "ec_numbers": ",".join(ec_numbers),
            "kegg_reaction_id": kegg_reaction_id,
            "reversible": (rxn.get("reversible") or "false").lower() == "true",
            "genes": genes,
            "gpr_expression": gpr_expression,
            "isoenzyme_count": isoenzyme_count,
            "reactants": reactants,
            "products": products,
        }

    return reactions, species


def parse_network_sif(sif_path):
    edges = []
    with open(sif_path, encoding="utf-8") as f:
        for line in f:
            parts = line.strip().split("\t")
            if len(parts) != 3:
                parts = line.strip().split()
            if len(parts) != 3:
                continue
            source, _relation, target = parts
            edges.append((source, target))
    return edges


def load_kegg_pathway_map():
    if not os.path.isfile(KEGG_PATHWAY_MAP_PATH):
        return None
    with open(KEGG_PATHWAY_MAP_PATH, encoding="utf-8") as f:
        return json.load(f)


def load_currency_metabolite_set():
    """Bundled generic fallback (see tpweb/data/currency_metabolites.json). Returns a set of
    uppercase BioCyc frame ids; empty set (not None) if the file is missing, since this is a
    soft cosmetic default, not required data."""
    if not os.path.isfile(CURRENCY_METABOLITES_PATH):
        return set()
    with open(CURRENCY_METABOLITES_PATH, encoding="utf-8") as f:
        payload = json.load(f)
    return {frame_id.upper() for frame_id in payload.get("currency_frame_ids", [])}


def _is_currency_species(species_id, compartment, currency_set):
    if not currency_set:
        return False
    decoded = _decode_sbml_id(species_id)
    if compartment and decoded.upper().endswith("_" + compartment.upper()):
        decoded = decoded[: -(len(compartment) + 1)]
    return decoded.upper() in currency_set


def _clean(value):
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.lower() in {"none", "nan", "null"}:
        return None
    return text


class Command(BaseCommand):
    help = "Import a genome-scale metabolic network (SBML + centrality/chokepoint TSV + network.sif) into Target."

    def add_arguments(self, parser):
        parser.add_argument(
            "genome_name", help="Internal genome name in Target (e.g. 'public__KpATCC43816')."
        )
        parser.add_argument("--sbml", required=True, metavar="PATH")
        parser.add_argument("--metabolic-results-tsv", required=True, metavar="PATH")
        parser.add_argument("--network-sif", required=True, metavar="PATH")
        parser.add_argument("--overwrite", action="store_true")
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument(
            "--username", default=None, help="Attribute this import to a user (provenance only)."
        )

    def handle(self, *args, **options):
        genome_name = options["genome_name"]
        sbml_path = options["sbml"]
        results_tsv = options["metabolic_results_tsv"]
        sif_path = options["network_sif"]
        overwrite = options["overwrite"]
        dry_run = options["dry_run"]

        proteome_name = genome_name + Biodatabase.PROT_POSTFIX
        proteome = Biodatabase.objects.filter(name=proteome_name).first()
        if proteome is None:
            raise CommandError(f"Genome '{genome_name}' not found. Load the GBK first.")

        for path in (sbml_path, results_tsv, sif_path):
            if not os.path.isfile(path):
                raise CommandError(f"File not found: {path}")

        # Bare accession (no owner/prot suffix) used to scope reaction rows for this genome.
        genome_accession = genome_name

        self.stdout.write(self.style.HTTP_INFO("Step 1/5 - Parsing SBML ..."))
        reactions_by_id, species_by_id = parse_sbml(sbml_path)
        self.stdout.write(
            f"  {len(reactions_by_id)} reactions, "
            f"{sum(1 for r in reactions_by_id.values() if r['genes'])} with gene associations, "
            f"{len(species_by_id)} species."
        )

        self.stdout.write(self.style.HTTP_INFO("Step 2/5 - Parsing network.sif ..."))
        sif_edges = parse_network_sif(sif_path)
        sif_nodes = {node for edge in sif_edges for node in edge}
        self.stdout.write(f"  {len(sif_edges)} edges across {len(sif_nodes)} nodes.")

        self.stdout.write(self.style.HTTP_INFO("Step 3/5 - Parsing results TSV ..."))
        results_df = pd.read_csv(results_tsv, sep="\t", index_col=False, low_memory=False)
        if "gene" not in results_df.columns:
            raise CommandError("Results TSV must have a 'gene' column with locus tags.")

        self._validate_inputs(proteome, reactions_by_id, sif_nodes, results_df)

        if dry_run:
            self.stdout.write(
                self.style.SUCCESS(
                    f"[dry-run] Would import {len(reactions_by_id)} reactions, "
                    f"{len(sif_edges)} edges, {len(results_df)} gene rows for {genome_accession}."
                )
            )
            return

        kegg_map = load_kegg_pathway_map()
        if kegg_map is None:
            self.stderr.write(
                self.style.WARNING(
                    "  tpweb/data/kegg_reaction_pathways.json not found - reactions will be imported "
                    "without KEGG pathway names. Run `python manage.py fetch_kegg_pathway_map` "
                    "(requires internet access) to enable pathway membership."
                )
            )
        currency_set = load_currency_metabolite_set()

        if overwrite:
            self.stdout.write(
                "--overwrite is accepted for compatibility; metabolism imports now replace "
                "the existing rows for this genome on every run."
            )
        self._clear_existing_metabolism(genome_accession)

        self.stdout.write(
            self.style.HTTP_INFO("Step 4/5 - Writing reactions/edges/chokepoints ...")
        )
        with transaction.atomic():
            reaction_objs = self._save_reactions(
                genome_accession, reactions_by_id, sif_nodes, kegg_map
            )
            self._save_gene_links(proteome, reaction_objs, reactions_by_id)
            self._save_edges(genome_accession, reaction_objs, sif_edges)
            self._apply_chokepoints(proteome, reaction_objs, results_df)

        self.stdout.write(self.style.HTTP_INFO("Step 5/5 - Writing metabolites/stoichiometry ..."))
        with transaction.atomic():
            species_objs = self._save_species(genome_accession, species_by_id, currency_set)
            self._save_participants(reaction_objs, species_objs, reactions_by_id)

        self._load_scalar_scores(genome_name, results_df, overwrite=True)

        imported_by = None
        if options["username"]:
            imported_by = get_user_model().objects.filter(username=options["username"]).first()
        MetabolicImportRun.objects.update_or_create(
            genome_accession=genome_accession,
            defaults={
                "sbml_filename": os.path.basename(sbml_path),
                "results_filename": os.path.basename(results_tsv),
                "sif_filename": os.path.basename(sif_path),
                "imported_by": imported_by,
            },
        )

        self.stdout.write(self.style.SUCCESS("Done."))

    # ------------------------------------------------------------------

    def _validate_inputs(self, proteome, reactions_by_id, sif_nodes, results_df):
        """Cross-file consistency checks the three inputs don't get for free just by
        parsing successfully -- each file can be individually well-formed and still not
        actually describe the same genome (wrong file picked, stale export, etc.). Warns
        (does not block import, since some mismatch is expected/harmless) except for the
        two cases where importing would be pointless or actively misleading."""
        if not reactions_by_id:
            raise CommandError("SBML has zero reactions - wrong file, or an empty MetaFlux export.")

        genome_locus_tags = set(
            Bioentry.objects.filter(biodatabase=proteome).values_list("accession", flat=True)
        )

        tsv_genes = {_clean(g) for g in results_df["gene"] if _clean(g)}
        if tsv_genes:
            unmatched = tsv_genes - genome_locus_tags
            if len(unmatched) == len(tsv_genes):
                raise CommandError(
                    "None of the results TSV's 'gene' values match a locus tag in this genome's "
                    f"proteome (checked {len(tsv_genes)} genes) - wrong genome, or wrong TSV file."
                )
            if unmatched:
                self.stderr.write(
                    self.style.WARNING(
                        f"  Results TSV: {len(unmatched)}/{len(tsv_genes)} genes have no matching locus "
                        f"tag in this genome, e.g. {sorted(unmatched)[:5]}"
                    )
                )

        if sif_nodes:
            sbml_reaction_ids = set(reactions_by_id)
            orphan_sif_nodes = sif_nodes - sbml_reaction_ids
            if orphan_sif_nodes:
                self.stderr.write(
                    self.style.WARNING(
                        f"  network.sif: {len(orphan_sif_nodes)}/{len(sif_nodes)} nodes have no matching "
                        f"reaction in the SBML, e.g. {sorted(orphan_sif_nodes)[:5]} - these will still be "
                        "created as bare MetabolicReaction rows with no SBML data (name/EC/genes/participants)."
                    )
                )

        if "PTOOLS_betweenness_centrality" not in results_df.columns:
            self.stderr.write(
                self.style.WARNING(
                    "  Results TSV has no 'PTOOLS_betweenness_centrality' column - network centrality "
                    "will not be loaded for this genome at all (silently skipped otherwise)."
                )
            )

    def _clear_existing_metabolism(self, genome_accession):
        existing_reactions = MetabolicReaction.objects.filter(genome_accession=genome_accession)
        existing_species = MetabolicSpecies.objects.filter(genome_accession=genome_accession)
        reaction_count = existing_reactions.count()
        species_count = existing_species.count()
        if reaction_count or species_count:
            self.stdout.write(
                f"Replacing existing metabolic rows for {genome_accession}: "
                f"{reaction_count} reactions, {species_count} species."
            )
            existing_reactions.delete()
            existing_species.delete()
        MetabolicImportRun.objects.filter(genome_accession=genome_accession).delete()

    def _save_reactions(self, genome_accession, reactions_by_id, sif_nodes, kegg_map):
        reaction_objs = {}

        all_ids = set(reactions_by_id) | sif_nodes
        for reaction_id in tqdm(sorted(all_ids), desc="reactions", file=sys.stderr):
            data = reactions_by_id.get(reaction_id, {})
            obj, _ = MetabolicReaction.objects.update_or_create(
                genome_accession=genome_accession,
                reaction_id=reaction_id,
                defaults={
                    "name": data.get("name", reaction_id),
                    "ec_numbers": data.get("ec_numbers", ""),
                    "kegg_reaction_id": data.get("kegg_reaction_id", ""),
                    "reversible": data.get("reversible", False),
                    "gpr_expression": data.get("gpr_expression", ""),
                    "isoenzyme_count": data.get("isoenzyme_count", 0),
                },
            )
            reaction_objs[reaction_id] = obj

            kegg_id = data.get("kegg_reaction_id")
            if kegg_id and kegg_map:
                for pathway_id in kegg_map.get("reaction_pathways", {}).get(kegg_id, []):
                    if pathway_id in KEGG_OVERVIEW_MAP_IDS:
                        continue
                    pathway_name = kegg_map.get("pathway_names", {}).get(pathway_id, pathway_id)
                    pathway_obj, _ = MetabolicPathway.objects.get_or_create(
                        source=MetabolicPathway.SOURCE_KEGG,
                        external_id=pathway_id,
                        defaults={"name": pathway_name},
                    )
                    obj.pathways.add(pathway_obj)

        return reaction_objs

    def _save_gene_links(self, proteome, reaction_objs, reactions_by_id):
        missing_genes = set()
        for reaction_id, data in tqdm(reactions_by_id.items(), desc="gene links", file=sys.stderr):
            genes = data.get("genes") or set()
            if not genes:
                continue
            reaction_obj = reaction_objs[reaction_id]
            for locus_tag in genes:
                bioentry = Bioentry.objects.filter(
                    biodatabase=proteome, accession=locus_tag
                ).first()
                if bioentry is None:
                    missing_genes.add(locus_tag)
                    continue
                GeneReactionLink.objects.get_or_create(bioentry=bioentry, reaction=reaction_obj)

        if missing_genes:
            self.stderr.write(
                self.style.WARNING(
                    f"  {len(missing_genes)} gene(s) referenced by the SBML were not found in this "
                    f"genome's proteome, e.g. {sorted(missing_genes)[:5]}"
                )
            )

    def _save_edges(self, genome_accession, reaction_objs, sif_edges):
        seen = set()
        edge_objs = []
        for source, target in tqdm(sif_edges, desc="edges", file=sys.stderr):
            source_obj = reaction_objs.get(source)
            target_obj = reaction_objs.get(target)
            if source_obj is None or target_obj is None or source_obj.pk == target_obj.pk:
                continue
            key = tuple(sorted((source_obj.pk, target_obj.pk)))
            if key in seen:
                continue
            seen.add(key)
            a_id, b_id = key
            reaction_a = source_obj if source_obj.pk == a_id else target_obj
            reaction_b = target_obj if reaction_a is source_obj else source_obj
            edge_objs.append(
                MetabolicReactionEdge(
                    genome_accession=genome_accession,
                    reaction_a=reaction_a,
                    reaction_b=reaction_b,
                )
            )

        MetabolicReactionEdge.objects.bulk_create(edge_objs, ignore_conflicts=True, batch_size=1000)

    def _save_species(self, genome_accession, species_by_id, currency_set):
        species_objs = {}
        for species_id, data in tqdm(species_by_id.items(), desc="species", file=sys.stderr):
            compartment = data.get("compartment", "")
            obj, _ = MetabolicSpecies.objects.update_or_create(
                genome_accession=genome_accession,
                species_id=species_id,
                defaults={
                    "display_name": data.get("display_name", species_id),
                    "compartment": compartment,
                    "is_currency": _is_currency_species(species_id, compartment, currency_set),
                },
            )
            species_objs[species_id] = obj
        return species_objs

    def _save_participants(self, reaction_objs, species_objs, reactions_by_id):
        missing_species = set()
        participant_objs = []
        for reaction_id, data in tqdm(
            reactions_by_id.items(), desc="participants", file=sys.stderr
        ):
            reaction_obj = reaction_objs.get(reaction_id)
            if reaction_obj is None:
                continue
            for role, participants in (
                (ReactionParticipant.ROLE_REACTANT, data.get("reactants") or []),
                (ReactionParticipant.ROLE_PRODUCT, data.get("products") or []),
            ):
                for species_id, stoichiometry in participants:
                    species_obj = species_objs.get(species_id)
                    if species_obj is None:
                        missing_species.add(species_id)
                        continue
                    participant_objs.append(
                        ReactionParticipant(
                            reaction=reaction_obj,
                            species=species_obj,
                            role=role,
                            stoichiometry=stoichiometry,
                        )
                    )

        ReactionParticipant.objects.bulk_create(
            participant_objs, ignore_conflicts=True, batch_size=1000
        )
        if missing_species:
            self.stderr.write(
                self.style.WARNING(
                    f"  {len(missing_species)} species referenced by reactions were not found in "
                    f"<listOfSpecies>, e.g. {sorted(missing_species)[:5]}"
                )
            )

    def _apply_chokepoints(self, proteome, reaction_objs, results_df):
        for column, role in CHOKEPOINT_COLUMNS.items():
            if column not in results_df.columns:
                continue
            for _, row in results_df[["gene", column]].dropna(subset=[column]).iterrows():
                reaction_id = _clean(row[column])
                locus_tag = _clean(row["gene"])
                if not reaction_id or not locus_tag:
                    continue
                reaction_obj = reaction_objs.get(reaction_id)
                if reaction_obj is None:
                    continue
                bioentry = Bioentry.objects.filter(
                    biodatabase=proteome, accession=locus_tag
                ).first()
                if bioentry is None:
                    continue
                GeneReactionLink.objects.update_or_create(
                    bioentry=bioentry,
                    reaction=reaction_obj,
                    defaults={"chokepoint_role": role},
                )

    def _load_scalar_scores(self, genome_name, results_df, overwrite):
        if "PTOOLS_betweenness_centrality" not in results_df.columns:
            return

        chokepoint_cols = [c for c in CHOKEPOINT_COLUMNS if c in results_df.columns]
        is_chokepoint = (
            results_df[chokepoint_cols].apply(
                lambda row: any(_clean(v) for v in row),
                axis=1,
            )
            if chokepoint_cols
            else pd.Series(False, index=results_df.index)
        )

        scores_df = pd.DataFrame(
            {
                "gene": results_df["gene"],
                "PTOOLS_betweenness_centrality": results_df["PTOOLS_betweenness_centrality"],
                "metabolic_chokepoint": is_chokepoint.map({True: "Y", False: "N"}),
            }
        )
        if "PTOOLS_edges" in results_df.columns:
            scores_df["PTOOLS_edges"] = results_df["PTOOLS_edges"]

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".tsv", delete=False, encoding="utf-8"
        ) as tmp:
            scores_df.to_csv(tmp, sep="\t", index=False)
            tmp_path = tmp.name

        try:
            call_command("load_score_values", genome_name, tmp_path, overwrite=overwrite)
        finally:
            os.unlink(tmp_path)
