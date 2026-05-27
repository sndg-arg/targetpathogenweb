import math
import os
from dataclasses import dataclass, field

import pandas as pd
from django.db.models import Count

from bioseq.models.Biodatabase import Biodatabase
from bioseq.models.Bioentry import Bioentry
from bioseq.models.BioentryDbxref import BioentryDbxref
from tpweb.models.Binders import Binders
from tpweb.models.BioentryStructure import BioentryStructure
from tpweb.models.ScoreParamValue import ScoreParamValue
from tpweb.models.pdb import PDBResidueSet
from tpweb.services.protein_annotations import annotation_dbnames


CURATED_SCORE_STAGE_SKIPS = {
    "gut_microbiome_offtarget": (6,),
    "Druggability": (18, 19),
    "Localization": (20, 21),
}

FASTTARGET_REQUIRED_SCORES = {
    "human_offtarget": (5,),
    "hit_in_deg": (7,),
}

REMOTE_STAGE_REQUIREMENTS = {
    4: ("TPW_FASTTARGET_USE_REMOTE", "TPW_FASTTARGET_REMOTE_COMMAND"),
    17: ("TPW_STRUCTURES_USE_REMOTE", "TPW_STRUCTURES_REMOTE_COMMAND"),
    22: ("TPW_BINDERS_USE_REMOTE", "TPW_BINDERS_REMOTE_COMMAND"),
}


@dataclass
class CuratedPipelinePlan:
    genome_name: str
    datadir: str
    folder_path: str
    protein_total: int
    tsv_columns: list[str] = field(default_factory=list)
    score_counts: dict[str, int] = field(default_factory=dict)
    protein_structures: int = 0
    pdb_count: int = 0
    fpocket_sets: int = 0
    p2rank_sets: int = 0
    interpro_output_exists: bool = False
    feature_proteins: int = 0
    uniprot_mapped_proteins: int = 0
    annotation_proteins: int = 0
    binder_count: int = 0
    ligq_binder_count: int = 0
    skip_stages: set[int] = field(default_factory=set)
    required_remote_stages: set[int] = field(default_factory=set)
    warnings: list[str] = field(default_factory=list)

    @property
    def skip_stages_text(self):
        return ",".join(str(stage) for stage in sorted(self.skip_stages))

    @property
    def required_remote_stages_text(self):
        return ",".join(str(stage) for stage in sorted(self.required_remote_stages))


def compute_folder_path(datadir, genome_name):
    acclen = len(genome_name)
    folder_name = genome_name[math.floor(acclen / 2 - 1):math.floor(acclen / 2 + 2)]
    return os.path.join(datadir, folder_name, genome_name)


def _score_counts(db, score_names):
    rows = (
        ScoreParamValue.objects.filter(
            bioentry__biodatabase=db,
            score_param__name__in=score_names,
        )
        .values("score_param__name")
        .annotate(count=Count("id"))
    )
    counts = {name: 0 for name in score_names}
    for row in rows:
        counts[row["score_param__name"]] = row["count"]
    return counts


def _remote_stage_ready(stage):
    requirement = REMOTE_STAGE_REQUIREMENTS.get(stage)
    if requirement is None:
        return True
    use_remote_var, command_var = requirement
    return os.getenv(use_remote_var, "").strip() == "1" and bool(os.getenv(command_var, "").strip())


def _read_tsv_columns(results_tsv):
    if not results_tsv:
        return []
    if not os.path.isfile(results_tsv):
        return []
    try:
        return list(pd.read_csv(results_tsv, sep="\t", nrows=0).columns)
    except Exception:
        return []


def build_curated_pipeline_plan(
    genome_name,
    *,
    results_tsv=None,
    datadir="./data",
    structure_completion_ratio=0.95,
):
    db = Biodatabase.objects.get(name=genome_name + Biodatabase.PROT_POSTFIX)
    proteins = Bioentry.objects.filter(biodatabase=db)
    protein_total = proteins.count()
    folder_path = compute_folder_path(datadir, genome_name)

    score_names = set(CURATED_SCORE_STAGE_SKIPS) | set(FASTTARGET_REQUIRED_SCORES)
    score_names.update(
        {
            "gut_microbiome_offtarget_norm",
            "gut_microbiome_offtarget_counts",
            "colabfold_plddt",
            "core_roary",
            "core_corecruncher",
            "human_identity",
            "human_evalue",
            "deg_identity",
            "deg_evalue",
        }
    )
    score_counts = _score_counts(db, sorted(score_names))

    structures_qs = BioentryStructure.objects.filter(bioentry__biodatabase=db)
    pdb_ids = list(structures_qs.values_list("pdb_id", flat=True).distinct())
    fpocket_sets = PDBResidueSet.objects.filter(
        pdb_id__in=pdb_ids,
        residue_set__name="FPocketPocket",
    ).count()
    p2rank_sets = PDBResidueSet.objects.filter(
        pdb_id__in=pdb_ids,
        residue_set__name="P2RankPocket",
    ).count()

    interpro_output = os.path.join(folder_path, f"{genome_name}.faa.tsv")
    uniprot_dbnames = ["UnipSp", "UnipTr"]
    annotation_dbname_set = set(annotation_dbnames("go")) | set(annotation_dbnames("ec"))

    plan = CuratedPipelinePlan(
        genome_name=genome_name,
        datadir=datadir,
        folder_path=folder_path,
        protein_total=protein_total,
        tsv_columns=_read_tsv_columns(results_tsv),
        score_counts=score_counts,
        protein_structures=structures_qs.values("bioentry_id").distinct().count(),
        pdb_count=len(pdb_ids),
        fpocket_sets=fpocket_sets,
        p2rank_sets=p2rank_sets,
        interpro_output_exists=os.path.exists(interpro_output),
        feature_proteins=proteins.filter(features__isnull=False).distinct().count(),
        uniprot_mapped_proteins=BioentryDbxref.objects.filter(
            bioentry__biodatabase=db,
            dbxref__dbname__in=uniprot_dbnames,
        ).values("bioentry_id").distinct().count(),
        annotation_proteins=BioentryDbxref.objects.filter(
            bioentry__biodatabase=db,
            dbxref__dbname__in=annotation_dbname_set,
        ).values("bioentry_id").distinct().count(),
        binder_count=Binders.objects.filter(locustag__biodatabase=db).count(),
        ligq_binder_count=Binders.objects.filter(
            locustag__biodatabase=db,
            source=Binders.SOURCE_PROPOSED,
        ).count(),
    )

    if protein_total <= 0:
        plan.warnings.append("No proteins found in TPW for this genome.")
        return plan

    for score_name, stages in CURATED_SCORE_STAGE_SKIPS.items():
        if score_counts.get(score_name, 0) >= protein_total:
            plan.skip_stages.update(stages)

    for score_name, stages in FASTTARGET_REQUIRED_SCORES.items():
        if score_counts.get(score_name, 0) >= protein_total:
            plan.skip_stages.update(stages)

    if all(score_counts.get(name, 0) >= protein_total for name in FASTTARGET_REQUIRED_SCORES):
        plan.skip_stages.add(4)
    else:
        plan.required_remote_stages.add(4)

    min_structures = max(1, math.floor(protein_total * structure_completion_ratio))
    if plan.protein_structures >= min_structures:
        plan.skip_stages.update({15, 16})
        if plan.protein_structures < protein_total:
            plan.warnings.append(
                f"Curated structures cover {plan.protein_structures}/{protein_total} proteins; "
                "stages 15/16 are still skipped to preserve curated structures."
            )
    else:
        plan.required_remote_stages.update({15, 16})

    if plan.fpocket_sets == 0 or plan.p2rank_sets == 0:
        plan.required_remote_stages.add(17)
    else:
        plan.skip_stages.add(17)

    if plan.feature_proteins > 0 and plan.interpro_output_exists:
        plan.skip_stages.update({10, 11})
    else:
        plan.required_remote_stages.add(10)

    if plan.binder_count > 0:
        plan.skip_stages.update({22, 23})
    else:
        plan.required_remote_stages.add(22)

    if plan.ligq_binder_count > 0:
        plan.skip_stages.add(24)
    else:
        plan.required_remote_stages.add(24)

    for stage in sorted(plan.required_remote_stages):
        if stage in REMOTE_STAGE_REQUIREMENTS and not _remote_stage_ready(stage):
            use_remote_var, command_var = REMOTE_STAGE_REQUIREMENTS[stage]
            plan.warnings.append(
                f"Stage {stage} requires SLURM but {use_remote_var}=1 and {command_var} are not both configured."
            )

    if 10 in plan.required_remote_stages and os.getenv("TPW_INTERPRO_USE_REMOTE", "1").strip() == "0":
        plan.warnings.append("Stage 10 requires SLURM but TPW_INTERPRO_USE_REMOTE=0 is configured.")
    if 15 in plan.required_remote_stages:
        plan.warnings.append(
            "Stage 15 has no dedicated SLURM wrapper. Provide curated structures or add a remote AlphaFold hook."
        )
    if 16 in plan.required_remote_stages and os.getenv("TPW_COLABFOLD_USE_REMOTE", "").strip() != "1":
        plan.warnings.append("Stage 16 requires SLURM but TPW_COLABFOLD_USE_REMOTE=1 is not configured.")
    if 24 in plan.required_remote_stages and os.getenv("TPW_LIGQ_USE_REMOTE", "").strip() != "1":
        plan.warnings.append("Stage 24 requires SLURM but TPW_LIGQ_USE_REMOTE=1 is not configured.")

    return plan
