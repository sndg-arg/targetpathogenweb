"""Flag each protein as having a high-confidence, cross-predictor consensus
binding pocket.

structure_summary.py's render-time "Likely same site as X" callout (the
pocket detail cards) only ever evaluates the top few pockets a page actually
displays (pocket_limit=4 for FPocket, p2rank_limit=5 for P2Rank) and isn't
persisted anywhere -- useful to look at, but not something you can filter or
rank proteins by. This command checks every pocket, not just the displayed
ones: does any FPocket pocket scored druggable (>= 0.7, this app's own
"high" threshold -- see pocket_cards.html's FPocket legend) sit within
POCKET_CONSENSUS_DISTANCE of a P2Rank pocket scored ligandable (>= 0.5, same
"high" threshold), on any of the protein's linked structures? Stores the
result as a "pocket_consensus_high_score" ScoreParamValue (Y/N) --
filterable like any other ScoreParam, and usable as a ScoreFormula term for
ranking.

Reuses tpweb.services.structure_summary.pdb_structure() (with the pocket
limits raised effectively to "all") rather than re-deriving pocket centers/
residues independently, so this reflects exactly the same geometry the page
itself would show -- not a second, potentially-diverging computation.
"""

import math
from collections import defaultdict

from django.core.management.base import BaseCommand, CommandError
from tqdm import tqdm

from bioseq.models.Biodatabase import Biodatabase
from bioseq.models.Bioentry import Bioentry
from tpweb.models.BioentryStructure import BioentryStructure
from tpweb.models.pdb import PDBResidueSet
from tpweb.models.ScoreParamValue import ScoreParamValue
from tpweb.services.pocket_consensus import POCKET_CONSENSUS_DISTANCE, nearest_named_center
from tpweb.services.score_params import ensure_system_score_param
from tpweb.services.structure_summary import pdb_structure

FPOCKET_HIGH_THRESHOLD = 0.7
P2RANK_HIGH_THRESHOLD = 0.5
# Effectively "no cap" -- this check needs every pocket on the structure,
# not the handful a page would ever display.
_ALL_POCKETS_LIMIT = 100000


def _valid_score(value):
    return value is not None and math.isfinite(value) and 0 <= value <= 1


def _has_high_score_consensus(pdbobj, target_chain=None):
    context = pdb_structure(
        pdbobj,
        [],
        pocket_limit=_ALL_POCKETS_LIMIT,
        p2rank_limit=_ALL_POCKETS_LIMIT,
        target_chain=target_chain,
    )
    if not context["pockets"] or not context["p2_pockets"]:
        return None
    missing_scores = any(not _valid_score(p.druggability) for p in context["pockets"]) or any(
        not _valid_score(p.probability) for p in context["p2_pockets"]
    )
    high_p2_centers = [
        (f"P2Rank {p2.name}", p2.geometric_center)
        for p2 in context["p2_pockets"]
        if _valid_score(p2.probability) and p2.probability >= P2RANK_HIGH_THRESHOLD
    ]
    if not high_p2_centers:
        return None if missing_scores else False
    missing_geometry = missing_scores or any(center is None for _, center in high_p2_centers)
    for p in context["pockets"]:
        if not _valid_score(p.druggability) or p.druggability < FPOCKET_HIGH_THRESHOLD:
            continue
        if p.geometric_center is None:
            missing_geometry = True
        nearest = nearest_named_center(p.geometric_center, high_p2_centers)
        if nearest and nearest[1] <= POCKET_CONSENSUS_DISTANCE:
            return True
    return None if missing_geometry else False


class Command(BaseCommand):
    help = (
        "Flags each protein with a high-score, same-site FPocket/P2Rank consensus pocket "
        "(checking every pocket, not just the top few shown on the page), storing the result "
        "as a 'pocket_consensus_high_score' ScoreParamValue (Y/N) for genome-wide "
        "filtering/scoring."
    )

    def add_arguments(self, parser):
        parser.add_argument("accession")

    def handle(self, *args, **options):
        accession = options["accession"]
        genome = Biodatabase.objects.filter(name=accession + Biodatabase.PROT_POSTFIX).first()
        if genome is None:
            raise CommandError(f"genome '{accession}' does not exist")

        score_param = ensure_system_score_param("pocket_consensus_high_score")
        if score_param is None:
            raise CommandError(
                "pocket_consensus_high_score is not registered in SYSTEM_SCORE_PARAM_DEFINITIONS"
            )

        # Many proteins can share a structure (a multi-chain complex linked
        # to more than one protein) -- cache the per-structure verdict so we
        # only run pdb_structure() once per distinct PDB row.
        consensus_cache = {}
        methods = defaultdict(set)
        pdb_ids = BioentryStructure.objects.filter(bioentry__biodatabase=genome).values("pdb_id")
        for pdb_id, method in (
            PDBResidueSet.objects.filter(
                pdb_id__in=pdb_ids,
                residue_set__name__in=["FPocketPocket", "P2RankPocket"],
            )
            .values_list("pdb_id", "residue_set__name")
            .distinct()
        ):
            methods[pdb_id].add(method)

        def consensus_for(link):
            key = (link.pdb_id, link.chain or "")
            if len(methods[link.pdb_id]) != 2:
                return None
            if key not in consensus_cache:
                consensus_cache[key] = _has_high_score_consensus(link.pdb, target_chain=link.chain)
            return consensus_cache[key]

        proteins = Bioentry.objects.filter(biodatabase=genome).prefetch_related("structures__pdb")
        existing = {
            row.bioentry_id: row
            for row in ScoreParamValue.objects.filter(
                bioentry__biodatabase=genome, score_param=score_param
            )
        }
        flagged = 0
        skipped = 0
        preserved = 0
        for protein in tqdm(proteins, total=proteins.count()):
            previous = existing.get(protein.pk)
            if previous and (
                str(previous.value or "").strip() or previous.numeric_value is not None
            ):
                preserved += 1
                continue
            links = list(protein.structures.all())
            if not links:
                skipped += 1
                continue

            results = [consensus_for(link) for link in links]
            has_consensus = any(result is True for result in results)
            if not has_consensus and any(result is None for result in results):
                skipped += 1
                continue
            ScoreParamValue.objects.update_or_create(
                bioentry=protein,
                score_param=score_param,
                defaults={"value": "Y" if has_consensus else "N"},
            )
            if has_consensus:
                flagged += 1

        self.stdout.write(
            f"Done. {flagged} proteins flagged with a high-score consensus pocket, "
            f"{skipped} skipped (missing structure, pockets or geometry), {preserved} existing values preserved."
        )
