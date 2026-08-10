"""Flag each protein's representative FPocket pocket as a size/geometry outlier.

For each protein in a genome, resolves the representative FPocket pocket the
same way ProteinView's "Selected pocket evidence" panel does: curated
Gates-Targets selection first (best_fpocket_structure/fpocket_pocket
ScoreParamValues -- what the biologists' pipeline picked), falling back to
this app's own max-druggability pick across ALL of the protein's linked
structures only when there's no curated value or it can't be resolved.
Then checks whether that one pocket's volume is a size/geometry outlier
relative to its own structure's other FPocket pockets
(tpweb.services.pocket_geometry), and stores the result as a
"pocket_size_outlier" ScoreParamValue (Y/N) for
tpweb.services.assembly_workspace._score_proteins and ProteinView's target
executive summary to read.
"""

import re

from django.core.management.base import BaseCommand, CommandError
from tqdm import tqdm

from bioseq.models.Biodatabase import Biodatabase
from bioseq.models.Bioentry import Bioentry
from tpweb.models.BioentryStructure import BioentryStructure
from tpweb.models.pdb import Property, PDBResidueSet, ResidueSet, ResidueSetProperty
from tpweb.models.ScoreParamValue import ScoreParamValue
from tpweb.services.pocket_geometry import volume_outlier_map
from tpweb.services.score_params import ensure_system_score_param
from tpweb.services.structure_sources import structure_matches_identifier

_POCKET_NUMBER_RE = re.compile(r"(\d+)")


def _raw_score_value(bioentry, score_param_name):
    spv = ScoreParamValue.objects.filter(
        bioentry=bioentry,
        score_param__name=score_param_name,
        score_param__user__isnull=True,
    ).first()
    return (spv.value if spv else "") or ""


def _resolve_curated_pocket(bioentry, links, fpocket_rs):
    """Return the curated PDBResidueSet for this protein's best FPocket pocket, if resolvable."""
    structure_identifier = _raw_score_value(bioentry, "best_fpocket_structure")
    pocket_label = _raw_score_value(bioentry, "fpocket_pocket")
    if not structure_identifier or not pocket_label or pocket_label.strip().lower() == "no_pockets":
        return None

    match = _POCKET_NUMBER_RE.search(pocket_label)
    if not match:
        return None
    pocket_number = match.group(1)

    matching_pdb_ids = [
        link.pdb_id for link in links if structure_matches_identifier(link, structure_identifier)
    ]
    if not matching_pdb_ids:
        return None

    return PDBResidueSet.objects.filter(
        pdb_id__in=matching_pdb_ids,
        residue_set=fpocket_rs,
        name=pocket_number,
    ).first()


def _resolve_auto_pocket(links, fpocket_rs, druggability_prop):
    """Max-druggability FPocket pocket across ALL of this protein's linked structures."""
    pdb_ids = [link.pdb_id for link in links]
    if not pdb_ids:
        return None
    return (
        PDBResidueSet.objects.filter(
            pdb_id__in=pdb_ids,
            residue_set=fpocket_rs,
            properties__property=druggability_prop,
        )
        .order_by("-properties__value")
        .first()
    )


class Command(BaseCommand):
    help = (
        "Flags each protein's representative FPocket pocket as a size/geometry outlier "
        "(unusually large/diffuse compared to that structure's other pockets), storing the "
        "result as a 'pocket_size_outlier' ScoreParamValue (Y/N) for genome-wide scoring."
    )

    def add_arguments(self, parser):
        parser.add_argument("accession")

    def handle(self, *args, **options):
        accession = options["accession"]
        genome = Biodatabase.objects.filter(name=accession + Biodatabase.PROT_POSTFIX).first()
        if genome is None:
            raise CommandError(f"genome '{accession}' does not exist")

        try:
            fpocket_rs = ResidueSet.objects.get(name="FPocketPocket")
            druggability_prop = Property.objects.get(name="druggability_score")
        except (ResidueSet.DoesNotExist, Property.DoesNotExist) as exc:
            raise CommandError(f"required pocket reference data missing: {exc}") from exc

        volume_prop = Property.objects.filter(name="volume").first()
        if volume_prop is None:
            raise CommandError(
                "the 'volume' Property row doesn't exist in this database -- "
                "nothing to compute pocket-size outliers from."
            )

        score_param = ensure_system_score_param("pocket_size_outlier")
        if score_param is None:
            raise CommandError(
                "pocket_size_outlier is not registered in SYSTEM_SCORE_PARAM_DEFINITIONS"
            )

        # Cache the volume-outlier verdict per structure -- many proteins share one.
        outlier_cache = {}

        def outlier_map_for(pdb_id):
            if pdb_id not in outlier_cache:
                volumes = ResidueSetProperty.objects.filter(
                    pdbresidue_set__pdb_id=pdb_id,
                    pdbresidue_set__residue_set=fpocket_rs,
                    property=volume_prop,
                ).values_list("pdbresidue_set_id", "value")
                outlier_cache[pdb_id] = volume_outlier_map(volumes)
            return outlier_cache[pdb_id]

        proteins = Bioentry.objects.filter(biodatabase=genome)
        flagged = 0
        skipped = 0
        for protein in tqdm(proteins, total=proteins.count()):
            links = list(BioentryStructure.objects.filter(bioentry=protein).select_related("pdb"))
            if not links:
                skipped += 1
                continue

            pocket = _resolve_curated_pocket(protein, links, fpocket_rs)
            if pocket is None:
                pocket = _resolve_auto_pocket(links, fpocket_rs, druggability_prop)
            if pocket is None:
                skipped += 1
                continue

            is_outlier, _median, _mad = outlier_map_for(pocket.pdb_id).get(
                pocket.id, (False, None, None)
            )
            ScoreParamValue.objects.update_or_create(
                bioentry=protein,
                score_param=score_param,
                defaults={"value": "Y" if is_outlier else "N"},
            )
            if is_outlier:
                flagged += 1

        self.stdout.write(
            f"Done. {flagged} proteins flagged as pocket-size outliers, "
            f"{skipped} skipped (no resolvable pocket)."
        )
