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

    if isinstance(protein, LightBioentry):
        return protein.genome
    return protein.biodatabase.name.removesuffix(Biodatabase.PROT_POSTFIX)


def _normalized_sequence(text):
    return str(text).strip().upper().rstrip("*") if text else ""


def _sequence(protein):
    if isinstance(protein, LightBioentry):
        return protein.sequence
    return _normalized_sequence(protein.seq.seq)


class ScoreRow:
    """Read-only stand-in for a ScoreParamValue with the same attributes, built
    from values_list: ranking a whole genome otherwise spends most of its time
    creating ~100k model instances."""

    __slots__ = ("pk", "bioentry_id", "score_param_id", "score_param", "value", "numeric_value")

    def __init__(self, pk, bioentry_id, score_param, value, numeric_value):
        self.pk = pk
        self.bioentry_id = bioentry_id
        self.score_param_id = score_param.pk
        self.score_param = score_param
        self.value = value
        self.numeric_value = numeric_value


def attach_score_rows(proteins, score_param_names=None):
    """Cache each protein's score values as ScoreRow, read through
    protein.score_params.all() like a prefetch (nothing is saved)."""
    proteins = list(proteins)
    if not proteins:
        return
    by_protein = _score_rows_by_bioentry([p.pk for p in proteins], score_param_names)
    for protein in proteins:
        _cache_relation(protein, "score_params", by_protein.get(protein.pk, []))


_RELATION_MODELS = {}


def _score_rows_by_bioentry(bioentry_ids, score_param_names=None):
    from tpweb.models.ScoreParam import ScoreParam
    from tpweb.models.ScoreParamValue import ScoreParamValue

    rows = ScoreParamValue.objects.filter(bioentry_id__in=bioentry_ids)
    if score_param_names is not None:
        rows = rows.filter(score_param__name__in=score_param_names)
    rows = list(
        rows.order_by().values_list("pk", "bioentry_id", "score_param_id", "value", "numeric_value")
    )
    params = ScoreParam.objects.in_bulk({row[2] for row in rows})
    by_protein = {}
    for pk, bioentry_id, param_id, value, numeric_value in rows:
        by_protein.setdefault(bioentry_id, []).append(
            ScoreRow(pk, bioentry_id, params[param_id], value, numeric_value)
        )
    return by_protein


class LightBioentry:
    """Read-only stand-in for another strain's Bioentry in the ranking pass
    (details=False): just what the score merge reads, loaded with values_list
    instead of thousands of Bioentry + Biosequence + Biodatabase instances."""

    __slots__ = ("pk", "accession", "description", "genome", "sequence", "score_rows")

    def __init__(self, pk, accession, description, genome, sequence):
        self.pk = pk
        self.accession = accession
        self.description = description
        self.genome = genome
        self.sequence = sequence
        self.score_rows = []


def _light_bioentries(bioentry_ids, score_param_names=None):
    from bioseq.models.Biodatabase import Biodatabase
    from bioseq.models.Bioentry import Bioentry

    light = {
        pk: LightBioentry(
            pk,
            accession,
            description or "",
            (proteome or "").removesuffix(Biodatabase.PROT_POSTFIX),
            _normalized_sequence(sequence),
        )
        for pk, accession, description, proteome, sequence in Bioentry.objects.filter(
            pk__in=bioentry_ids
        ).values_list("pk", "accession", "description", "biodatabase__name", "seq__seq")
    }
    for bioentry_id, rows in _score_rows_by_bioentry(list(light), score_param_names).items():
        light[bioentry_id].score_rows = rows
    return light


def _cache_relation(protein, relation, rows):
    # Cache only this request's projection, using a QuerySet to preserve
    # related-manager .all(), .count(), and iteration. No model row is saved.
    # The related model is looked up once per relation: building a related
    # manager per protein was most of the cost when ranking a genome.
    from django.db.models import QuerySet

    key = (type(protein), relation)
    if key not in _RELATION_MODELS:
        _RELATION_MODELS[key] = getattr(protein, relation).model
    queryset = QuerySet(model=_RELATION_MODELS[key])
    queryset.query.set_empty()
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
    # The ranking pass (details=False) reads scores as light rows, see attach_score_rows.
    relations = [Prefetch("score_params", queryset=scores)] if details else []
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
    other_ids = {m.bioentry_id for m in members} - loaded.keys()
    if details:
        others = {
            b.pk: b
            for b in Bioentry.objects.filter(pk__in=other_ids)
            .select_related("biodatabase", "seq")
            .prefetch_related(*relations)
        }
    else:
        others = _light_bioentries(other_ids, score_param_names)
    # .source, not .bioentry: a LightBioentry can't be assigned to the FK.
    for member in members:
        member.source = loaded.get(member.bioentry_id) or others.get(member.bioentry_id)
    members = [m for m in members if m.source is not None]

    def score_rows(source):
        if source.pk in own_scores:
            return own_scores[source.pk]
        if isinstance(source, LightBioentry):
            return source.score_rows
        return list(source.score_params.all())

    by_group = {}
    visibility = {}
    access = {}
    for member in members:
        genome = _genome(member.source)
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
        peers = [m for m in by_group.get(group, []) if _sequence(m.source) == sequence]
        donors = sorted(
            [m for m in peers if m.strain_label in CURATED_STRAINS],
            key=lambda m: (CURATED_STRAINS[m.strain_label], m.locus_tag),
        )
        evidence = SharedSequenceEvidence()
        # Same protein, same name: the curated strain's product name is shown for
        # every identical occurrence (in memory only; the GenBank record is kept).
        curated_name = next(
            (
                (m.source.description or "").strip()
                for m in donors
                if (m.source.description or "").strip()
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
                "has_structure": bool(list(m.source.structures.all())) if details else False,
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
        sources = [m.source for m in donors]
        fallback_sources = [
            m.source
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
    from django.db.models.functions import Coalesce, Trim, Upper
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
    empty = ["", "None", "none", "nan", "null"]
    for param in params:
        # Same answer as "curated copy first, then this protein's own value,
        # then any other identical copy", written as three separate lookups
        # joined by Coalesce. One subquery with an OR across them (own row OR
        # a donor row) could not use the score-value indexes and, after the
        # bulk structure load, ran for minutes per page.
        own = ScoreParamValue.objects.filter(
            bioentry_id=OuterRef("pk"), score_param_id=param.pk
        ).exclude(numeric_value__isnull=True, value__in=empty)
        donors = (
            ScoreParamValue.objects.annotate(_donor_sequence=normalized("bioentry__seq__seq"))
            .filter(
                scope,
                bioentry__identical_sequence_memberships__group_id__in=Subquery(groups),
                _donor_sequence=OuterRef("_shared_target_sequence"),
                score_param_id=param.pk,
            )
            .exclude(numeric_value__isnull=True, value__in=empty)
        )
        curated = (
            donors.filter(
                bioentry__identical_sequence_memberships__strain_label__in=CURATED_STRAINS
            )
            .annotate(
                _curated_priority=Case(
                    When(
                        bioentry__identical_sequence_memberships__strain_label="KP13", then=Value(0)
                    ),
                    default=Value(1),
                    output_field=IntegerField(),
                ),
            )
            .order_by("_curated_priority", "bioentry__accession", "pk")
        )
        others = donors.order_by("bioentry__accession", "pk")
        prefix = f"_shared_score_{param.pk}_"
        for column, output in (("value", CharField()), ("numeric_value", FloatField())):
            annotations[prefix + column] = Coalesce(
                Subquery(curated.values(column)[:1], output_field=output),
                Subquery(own.values(column)[:1], output_field=output),
                Subquery(others.values(column)[:1], output_field=output),
                output_field=output,
            )
    return queryset.annotate(**annotations), {p.pk for p in params}


INHERITED_PARAMS_CACHE_TTL_SECONDS = 900


def inherited_score_param_ids(genome_name, user):
    """Parameters available from accessible curated sources for this genome.
    Cached per genome and user like the other genome-scoped aggregates: the
    protein list asks for it twice per request."""
    from django.core.cache import cache
    from django.db.models import Max
    from tpweb.models import IdenticalSequenceMember
    from tpweb.models.ScoreParam import ScoreParam
    from tpweb.models.ScoreParamValue import ScoreParamValue

    # New values, parameters or identity links change the key right away
    # (max primary keys are index lookups); the TTL covers edits in place.
    stamp = ":".join(
        str(model.objects.aggregate(Max("pk"))["pk__max"])
        for model in (ScoreParamValue, ScoreParam, IdenticalSequenceMember)
    )
    cache_key = (
        f"Target:inherited_score_param_ids:{genome_name}:{getattr(user, 'pk', None)}:{stamp}"
    )
    cached = cache.get(cache_key)
    if cached is not None:
        return cached
    result = _inherited_score_param_ids(genome_name, user)
    cache.set(cache_key, result, INHERITED_PARAMS_CACHE_TTL_SECONDS)
    return result


def _inherited_score_param_ids(genome_name, user):
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
    proteomes = sources.order_by().values_list("bioentry__biodatabase__name", flat=True).distinct()
    result = set()
    for proteome in proteomes:
        source_genome = proteome.removesuffix(Biodatabase.PROT_POSTFIX)
        if not user_can_access_genome_name(user, source_genome):
            continue
        # A subquery, not a Python list of thousands of ids to bind.
        ids = sources.filter(bioentry__biodatabase__name=proteome).values("bioentry_id")
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
