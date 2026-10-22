"""Read live curated evidence through the groups in Sol's identity table.

Each Bioentry keeps its strain context. Shared evidence stays on its original
rows: updating a curated source is reflected on every linked occurrence.
"""

from dataclasses import dataclass, field


CURATED_STRAINS = {"KP13": 0, "ATCC43816": 1}
STRAIN_LABELS = {"KP13": "KP13", "ATCC43816": "KPATCC", "ST11_VA569": "VA569"}
# Identical proteins share every curated datum except metabolic context, which
# comes from each strain's own metabolic model. Conservation (core/soft core) is
# shared: identical proteins in these strains carry the curated call.
LOCAL_SCORE_CATEGORIES = {"metabolic network", "metabolism"}
LOCAL_SCORE_PREFIXES = ("ptools_", "metabolic_", "kp_score")
POCKET_SCORE_BUNDLES = {
    "p2rank_probability": {"p2rank_probability", "best_p2rank_structure", "p2rank_pocket"},
    "Druggability": {"Druggability", "best_fpocket_structure", "fpocket_pocket"},
    "colabfold_druggability_score": {"colabfold_druggability_score", "colabfold_fpocket_pocket"},
    "colabfold_p2rank_probability": {"colabfold_p2rank_probability", "colabfold_p2rank_pocket"},
}


def sequence_specific_score(param):
    category = str(param.category or "").strip().lower()
    return (
        category not in LOCAL_SCORE_CATEGORIES
        and not category.startswith(("metabolic", "metabolism"))
        and not str(param.name).lower().startswith(LOCAL_SCORE_PREFIXES)
    )


def _has_value(row):
    return row.numeric_value is not None or str(
        row.value if row.value is not None else ""
    ).strip().lower() not in {
        "",
        "none",
        "nan",
        "null",
    }


def choose_scores(local, donors, fallbacks=()):
    """Per-field precedence; False and zero are values, missing data is not."""
    selected = {row.score_param_id: row for row in local}
    curated = {}
    conflicts = set()
    for rows in donors:
        for row in rows:
            if not sequence_specific_score(row.score_param) or not _has_value(row):
                continue
            previous = curated.get(row.score_param_id)
            if previous is not None:
                if (previous.value, previous.numeric_value) != (row.value, row.numeric_value):
                    conflicts.add(row.score_param.name)
                continue
            curated[row.score_param_id] = row
    selected.update(curated)
    for rows in fallbacks:
        for row in rows:
            if sequence_specific_score(row.score_param) and _has_value(row):
                previous = selected.get(row.score_param_id)
                if previous is None or not _has_value(previous):
                    selected[row.score_param_id] = row
    for anchor, names in POCKET_SCORE_BUNDLES.items():
        source = next(
            (
                rows
                for rows in [*donors, local, *fallbacks]
                if any(row.score_param.name == anchor and _has_value(row) for row in rows)
            ),
            None,
        )
        # Pocket scores, pocket IDs and structure IDs must describe one
        # experiment; never overlay a curated score on an automatic pocket.
        selected = {key: row for key, row in selected.items() if row.score_param.name not in names}
        bundle = source if source is not None else local
        selected.update(
            {
                row.score_param_id: row
                for row in bundle
                if row.score_param.name in names and _has_value(row)
            }
        )
    return list(selected.values()), sorted(conflicts)


@dataclass
class SharedSequenceEvidence:
    siblings: list = field(default_factory=list)
    sources: list = field(default_factory=list)
    structures: list = field(default_factory=list)
    scores: list = field(default_factory=list)
    conflicts: list = field(default_factory=list)
    curated_structure_ids: set = field(default_factory=set)
    binder_accessions: list = field(default_factory=list)
    local_description: str = ""
    # score_param name -> strain label, for values read from another occurrence
    score_sources: dict = field(default_factory=dict)
    curated_binder_accessions: list = field(default_factory=list)


def _genome(protein):
    from bioseq.models.Biodatabase import Biodatabase

    return protein.biodatabase.name.removesuffix(Biodatabase.PROT_POSTFIX)


def _sequence(protein):
    return str(protein.seq.seq).strip().upper().rstrip("*")


def _cache_relation(protein, relation, rows):
    # Cache only this request's projection, using a QuerySet to preserve
    # related-manager .all(), .count(), and iteration. No model row is saved.
    manager = getattr(protein, relation)
    queryset = manager.model.objects.none()
    queryset._result_cache = list(rows)
    queryset._prefetch_done = True
    if not hasattr(protein, "_prefetched_objects_cache"):
        protein._prefetched_objects_cache = {}
    protein._prefetched_objects_cache[relation] = queryset


def apply_shared_sequence_evidence(proteins, user, details=True, score_param_names=None):
    """Batch resolution with current-sequence validation and source access checks."""
    from django.db.models import Prefetch
    from bioseq.models.Bioentry import Bioentry
    from tpweb.models import IdenticalSequenceMember
    from tpweb.models.ScoreParam import ScoreParam
    from tpweb.models.ScoreParamValue import ScoreParamValue
    from tpweb.services.genome_workspace import user_can_access_genome_name
    from tpweb.services.score_params import score_param_visibility_filter
    from tpweb.services.protein_annotations import annotation_dbnames

    proteins = [p for p in proteins if not hasattr(p, "shared_sequence_evidence")]
    if not proteins:
        return
    memberships = list(
        IdenticalSequenceMember.objects.filter(
            bioentry_id__in=[p.pk for p in proteins],
        )
    )
    if not memberships:
        return
    group_by_protein = {m.bioentry_id: m.group_id for m in memberships}
    scores = ScoreParamValue.objects.select_related("score_param")
    if score_param_names is not None:
        scores = scores.filter(score_param__name__in=score_param_names)
    relations = [Prefetch("score_params", queryset=scores)]
    if details:
        relations += [
            "structures__pdb",
            "experimental_structure_xrefs",
            "dbxrefs__dbxref__terms__term",
        ]
    members = list(
        IdenticalSequenceMember.objects.filter(
            group_id__in=set(group_by_protein.values()),
            bioentry__isnull=False,
        ).order_by("strain_label", "locus_tag")
    )
    # Proteins already in hand (the whole genome when ranking) are reused as
    # members instead of being loaded a second time; their own score rows are
    # read before any of them is overwritten with merged evidence below.
    loaded = {p.pk: p for p in proteins}
    own_scores = {p.pk: list(p.score_params.all()) for p in proteins}
    others = {
        b.pk: b
        for b in Bioentry.objects.filter(pk__in={m.bioentry_id for m in members} - loaded.keys())
        .select_related("biodatabase", "seq")
        .prefetch_related(*relations)
    }
    for member in members:
        member.bioentry = loaded.get(member.bioentry_id) or others.get(member.bioentry_id)
    members = [m for m in members if m.bioentry is not None]

    def score_rows(source):
        if source.pk in own_scores:
            return own_scores[source.pk]
        return list(source.score_params.all())

    by_group = {}
    visibility = {}
    access = {}
    for member in members:
        genome = _genome(member.bioentry)
        if genome not in access:
            access[genome] = user_can_access_genome_name(user, genome)
        if access[genome]:
            by_group.setdefault(member.group_id, []).append(member)
    for protein in proteins:
        group = group_by_protein.get(protein.pk)
        if group is None:
            continue
        sequence = _sequence(protein)
        if not sequence:
            continue
        peers = [m for m in by_group.get(group, []) if _sequence(m.bioentry) == sequence]
        donors = sorted(
            [m for m in peers if m.strain_label in CURATED_STRAINS],
            key=lambda m: (CURATED_STRAINS[m.strain_label], m.locus_tag),
        )
        evidence = SharedSequenceEvidence()
        # Same protein, same name: the curated strain's product name is shown for
        # every identical occurrence (in memory only; the GenBank record is kept).
        curated_name = next(
            (
                (m.bioentry.description or "").strip()
                for m in donors
                if (m.bioentry.description or "").strip()
            ),
            "",
        )
        if curated_name and curated_name != (protein.description or "").strip():
            evidence.local_description = protein.description or ""
            protein.description = curated_name
        evidence.siblings = [
            {
                "strain_label": STRAIN_LABELS.get(m.strain_label, m.strain_label.split("__")[-1]),
                "locus_tag": m.locus_tag,
                "protein_accession": m.protein_accession,
                "bioentry_id": m.bioentry_id,
                "has_structure": bool(list(m.bioentry.structures.all())) if details else False,
                "curated": m.strain_label in CURATED_STRAINS,
            }
            for m in peers
            if m.bioentry_id != protein.pk
        ]
        evidence.sources = [
            {
                "strain_label": STRAIN_LABELS.get(m.strain_label, m.strain_label.split("__")[-1]),
                "locus_tag": m.locus_tag,
                "bioentry_id": m.bioentry_id,
            }
            for m in donors
            if m.bioentry_id != protein.pk
        ]
        sources = [m.bioentry for m in donors]
        fallback_sources = [
            m.bioentry
            for m in peers
            if m.strain_label not in CURATED_STRAINS and m.bioentry_id != protein.pk
        ]
        all_sources = [*sources, protein, *fallback_sources]
        structure_keys = set()
        for source in all_sources if details else []:
            for link in source.structures.all():
                key = (link.pdb_id, link.chain or "")
                if source in sources:
                    evidence.curated_structure_ids.add(link.pk)
                if key not in structure_keys:
                    evidence.structures.append(link)
                    structure_keys.add(key)
        donor_scores = []
        for source in [*sources, *fallback_sources]:
            genome = _genome(source)
            if genome not in visibility:
                visibility[genome] = set(
                    ScoreParam.objects.filter(
                        score_param_visibility_filter(user, genome),
                    ).values_list("pk", flat=True)
                )
            donor_scores.append(
                [r for r in score_rows(source) if r.score_param_id in visibility[genome]]
            )
        evidence.scores, evidence.conflicts = choose_scores(
            score_rows(protein),
            donor_scores[: len(sources)],
            donor_scores[len(sources) :],
        )
        strain_of = {
            m.bioentry_id: STRAIN_LABELS.get(m.strain_label, m.strain_label.split("__")[-1])
            for m in peers
        }
        evidence.score_sources = {
            row.score_param.name: strain_of.get(row.bioentry_id, "")
            for row in evidence.scores
            if row.bioentry_id != protein.pk
        }
        evidence.binder_accessions = list(dict.fromkeys(p.accession for p in all_sources))
        evidence.curated_binder_accessions = list(dict.fromkeys(p.accession for p in sources))
        relations_to_share = (
            (("experimental_structure_xrefs", "pdb_id"), ("dbxrefs", "dbxref_id"))
            if details
            else []
        )
        for relation, key in relations_to_share:
            rows = []
            seen = set()
            namespaces = {name: kind for kind in ("ec", "go") for name in annotation_dbnames(kind)}
            namespaces.update({"UnipSp": "uniprot", "UnipTr": "uniprot"})
            curated_namespaces = set()
            if relation == "dbxrefs":
                curated_namespaces = {
                    namespaces[row.dbxref.dbname]
                    for source in sources
                    for row in source.dbxrefs.all()
                    if row.dbxref.dbname in namespaces
                }
            for source in all_sources:
                for row in getattr(source, relation).all():
                    if (
                        relation == "dbxrefs"
                        and source not in sources
                        and namespaces.get(row.dbxref.dbname) in curated_namespaces
                    ):
                        continue
                    if (
                        relation == "dbxrefs"
                        and source is not protein
                        and row.dbxref.dbname not in {*namespaces, "PDB"}
                    ):
                        continue
                    identity = getattr(row, key)
                    if identity not in seen:
                        seen.add(identity)
                        rows.append(row)
            _cache_relation(protein, relation, rows)
        if details:
            _cache_relation(protein, "structures", evidence.structures)
        _cache_relation(protein, "score_params", evidence.scores)
        protein.shared_sequence_evidence = evidence


def shared_structure_link(user, protein_id, pdb_id):
    """Resolve a structure through an authorized occurrence, with strict ID scope."""
    from bioseq.models.Bioentry import Bioentry
    from tpweb.services.genome_workspace import user_can_access_genome_name

    protein = Bioentry.objects.select_related("biodatabase", "seq").filter(pk=protein_id).first()
    if protein is None or not user_can_access_genome_name(user, _genome(protein)):
        return None
    apply_shared_sequence_evidence([protein], user)
    return next((s for s in protein.structures.all() if s.pdb_id == pdb_id), None)


def annotate_shared_score_values(queryset, param_ids, user):
    """Use the same curated-first values in SQL filters as in the protein page."""
    from django.db.models import (
        Case,
        CharField,
        Exists,
        F,
        FloatField,
        Func,
        IntegerField,
        OuterRef,
        Q,
        Subquery,
        TextField,
        Value,
        When,
    )
    from django.db.models.functions import Trim, Upper
    from bioseq.models.Biodatabase import Biodatabase
    from tpweb.models import IdenticalSequenceMember
    from tpweb.models.ScoreParam import ScoreParam
    from tpweb.models.ScoreParamValue import ScoreParamValue
    from tpweb.services.genome_workspace import user_can_access_genome_name
    from tpweb.services.score_params import score_param_visibility_filter

    params = [p for p in ScoreParam.objects.filter(pk__in=param_ids) if sequence_specific_score(p)]
    if not params:
        return queryset, set()
    genomes = (
        IdenticalSequenceMember.objects.filter(
            bioentry__isnull=False,
        )
        .order_by()
        .values_list("bioentry__biodatabase__name", flat=True)
        .distinct()
    )
    scope = Q(pk__in=[])
    for proteome in genomes:
        genome = proteome.removesuffix(Biodatabase.PROT_POSTFIX)
        if user_can_access_genome_name(user, genome):
            readable = ScoreParam.objects.filter(
                score_param_visibility_filter(user, genome)
            ).values("pk")
            scope |= Q(bioentry__biodatabase__name=proteome, score_param_id__in=Subquery(readable))

    def normalized(field):
        return Func(Upper(Trim(F(field))), Value("*"), function="RTRIM", output_field=TextField())

    queryset = queryset.annotate(_shared_target_sequence=normalized("seq__seq"))
    groups = IdenticalSequenceMember.objects.filter(
        bioentry_id=OuterRef(OuterRef("pk")),
    ).values("group_id")
    annotations = {}
    for param in params:
        local_value = ScoreParamValue.objects.filter(
            bioentry_id=OuterRef(OuterRef("pk")), score_param_id=param.pk
        ).exclude(numeric_value__isnull=True, value__in=["", "None", "none", "nan", "null"])
        rows = (
            ScoreParamValue.objects.annotate(_donor_sequence=normalized("bioentry__seq__seq"))
            .filter(
                Q(bioentry_id=OuterRef("pk"))
                | (
                    scope
                    & Q(bioentry__identical_sequence_memberships__group_id__in=Subquery(groups))
                    & Q(_donor_sequence=OuterRef("_shared_target_sequence"))
                ),
                score_param_id=param.pk,
            )
            .filter(
                Q(bioentry_id=OuterRef("pk"))
                | Q(bioentry__identical_sequence_memberships__strain_label__in=CURATED_STRAINS)
                | ~Q(Exists(local_value))
            )
            .exclude(numeric_value__isnull=True, value__in=["", "None", "none", "nan", "null"])
            .annotate(
                _curated_priority=Case(
                    When(
                        bioentry__identical_sequence_memberships__strain_label="KP13", then=Value(0)
                    ),
                    When(
                        bioentry__identical_sequence_memberships__strain_label="ATCC43816",
                        then=Value(1),
                    ),
                    default=Value(2),
                    output_field=IntegerField(),
                ),
            )
            .order_by("_curated_priority", "bioentry__accession", "pk")
        )
        prefix = f"_shared_score_{param.pk}_"
        annotations[prefix + "value"] = Subquery(rows.values("value")[:1], output_field=CharField())
        annotations[prefix + "numeric_value"] = Subquery(
            rows.values("numeric_value")[:1], output_field=FloatField()
        )
    return queryset.annotate(**annotations), {p.pk for p in params}


def inherited_score_param_ids(genome_name, user):
    """Parameters available from accessible curated sources for this genome."""
    from bioseq.models.Biodatabase import Biodatabase
    from tpweb.models import IdenticalSequenceMember
    from tpweb.models.ScoreParam import ScoreParam
    from tpweb.models.ScoreParamValue import ScoreParamValue
    from tpweb.services.genome_workspace import user_can_access_genome_name
    from tpweb.services.score_params import score_param_visibility_filter

    groups = IdenticalSequenceMember.objects.filter(
        bioentry__biodatabase__name=genome_name + Biodatabase.PROT_POSTFIX,
    ).values("group_id")
    sources = IdenticalSequenceMember.objects.filter(
        group_id__in=groups,
        bioentry__isnull=False,
    )
    by_genome = {}
    for proteome, bioentry_id in sources.values_list("bioentry__biodatabase__name", "bioentry_id"):
        source_genome = proteome.removesuffix(Biodatabase.PROT_POSTFIX)
        by_genome.setdefault(source_genome, []).append(bioentry_id)
    result = set()
    for source_genome, ids in by_genome.items():
        if not user_can_access_genome_name(user, source_genome):
            continue
        used = ScoreParamValue.objects.filter(bioentry_id__in=ids).values("score_param_id")
        params = ScoreParam.objects.filter(
            score_param_visibility_filter(user, source_genome),
            pk__in=used,
        )
        result.update(p.pk for p in params if sequence_specific_score(p))
    return result


REUSABLE_EVIDENCE = ("structure", "pockets", "ligands")


def loci_covered_by_curated_copy(genome_name, evidence):
    """Locus tags of this genome whose identical copy in a curated strain already
    has `evidence`, so the pipeline can skip recomputing it: apply_shared_sequence_evidence
    reads the copy's data live. Only public curated copies count, since the new
    genome's viewers must be able to see what is reused.

    structure: the copy has a 3D structure. pockets: it has a pocket score.
    ligands: its genome went through ligand search (a copy without ligands then
    truly has none)."""
    from django.contrib.auth.models import AnonymousUser
    from bioseq.models.Biodatabase import Biodatabase
    from tpweb.models import IdenticalSequenceMember
    from tpweb.models.Binders import Binders
    from tpweb.services.genome_workspace import user_can_access_genome_name

    if evidence not in REUSABLE_EVIDENCE:
        raise ValueError(f"Unknown evidence {evidence!r}")
    proteome = genome_name + Biodatabase.PROT_POSTFIX
    local = list(
        IdenticalSequenceMember.objects.filter(bioentry__biodatabase__name=proteome).values_list(
            "group_id", "bioentry__accession", "bioentry__seq__seq"
        )
    )
    if not local:
        return set()
    donors = (
        IdenticalSequenceMember.objects.filter(
            group_id__in={group for group, _, _ in local},
            strain_label__in=CURATED_STRAINS,
            bioentry__isnull=False,
        )
        .exclude(bioentry__biodatabase__name=proteome)
        .order_by()
    )
    if evidence == "structure":
        donors = donors.filter(bioentry__structures__isnull=False)
    elif evidence == "pockets":
        donors = donors.filter(
            bioentry__score_params__score_param__name__in=["p2rank_probability", "Druggability"]
        )
    anonymous = AnonymousUser()
    allowed = {}
    ligand_genomes = {}
    sequences = {}
    for group, database_id, database, sequence in donors.values_list(
        "group_id", "bioentry__biodatabase_id", "bioentry__biodatabase__name", "bioentry__seq__seq"
    ).distinct():
        if database not in allowed:
            allowed[database] = user_can_access_genome_name(
                anonymous, database.removesuffix(Biodatabase.PROT_POSTFIX)
            )
        if not allowed[database]:
            continue
        if evidence == "ligands":
            if database_id not in ligand_genomes:
                ligand_genomes[database_id] = Binders.objects.filter(
                    locustag__biodatabase_id=database_id
                ).exists()
            if not ligand_genomes[database_id]:
                continue
        sequences.setdefault(group, set()).add(str(sequence or "").strip().upper().rstrip("*"))
    covered = set()
    for group, accession, sequence in local:
        sequence = str(sequence or "").strip().upper().rstrip("*")
        if sequence and sequence in sequences.get(group, ()):
            covered.add(accession)
    return covered


def shared_relation_condition(queryset, condition, user, override_condition=None):
    """Include live shared structures/annotations in the corresponding filters."""
    from django.db.models import Exists, F, Func, OuterRef, Q, Subquery, TextField, Value
    from django.db.models.functions import Trim, Upper
    from bioseq.models.Bioentry import Bioentry
    from bioseq.models.Biodatabase import Biodatabase
    from tpweb.models import IdenticalSequenceMember
    from tpweb.services.genome_workspace import user_can_access_genome_name

    def normalized(field):
        return Func(Upper(Trim(F(field))), Value("*"), function="RTRIM", output_field=TextField())

    queryset = queryset.annotate(_shared_target_sequence=normalized("seq__seq"))
    groups = IdenticalSequenceMember.objects.filter(
        bioentry_id=OuterRef(OuterRef("pk")),
    ).values("group_id")
    proteomes = (
        IdenticalSequenceMember.objects.filter(
            bioentry__isnull=False,
        )
        .order_by()
        .values_list("bioentry__biodatabase__name", flat=True)
        .distinct()
    )
    allowed = [
        name
        for name in proteomes
        if user_can_access_genome_name(
            user,
            name.removesuffix(Biodatabase.PROT_POSTFIX),
        )
    ]
    donors = Bioentry.objects.annotate(_donor_sequence=normalized("seq__seq")).filter(
        identical_sequence_memberships__group_id__in=Subquery(groups),
        _donor_sequence=OuterRef("_shared_target_sequence"),
        biodatabase__name__in=allowed,
    )
    own_condition = condition
    if override_condition is not None:
        curated = donors.filter(identical_sequence_memberships__strain_label__in=CURATED_STRAINS)
        has_curated = Q(Exists(curated.filter(override_condition)))
        return queryset, (Q(Exists(curated.filter(condition)))) | (
            ~has_curated & (own_condition | Q(Exists(donors.filter(condition))))
        )
    return queryset, own_condition | Q(Exists(donors.filter(condition)))
