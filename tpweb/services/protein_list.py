import base64
import json
import re

from django.db.models import Exists, OuterRef, Q

from tpweb.models.Binders import Binders

from tpweb.services.structure_sources import (
    PDB_EXPERIMENT_ALPHAFOLD,
    PDB_EXPERIMENT_COLABFOLD,
    PDB_MODEL_EXPERIMENTS,
)

CORE_GENOME_PARAM_NAMES = {"core_roary", "core_corecruncher"}

MIN_PAGE_SIZE = 10
MAX_PAGE_SIZE = 100
DEFAULT_PAGE_SIZE = 25

ACRONYM_TOKENS = {
    "deg": "DEG",
    "ppi": "PPI",
    "dna": "DNA",
    "rna": "RNA",
    "p2rank": "P2RANK",
    "fpocket": "FPocket",
    "alphafold": "AlphaFold DB",
    "colabfold": "ColabFold",
    "plddt": "pLDDT",
    "id": "ID",
    "ec": "EC",
}

TOKEN_REPLACEMENTS = {
    "offtarget": "Off-target",
}

LOWER_CONNECTORS = {"and", "or", "of", "in", "on", "to", "for", "with", "without", "by"}
EXACT_REPLACEMENTS = {
    "human_offtarget": "Human off-target",
    "gut_microbiome_offtarget": "Gut microbiome off-target",
    "human_identity": "Human identity (%)",
    "human_evalue": "Human E-value",
    "deg_identity": "DEG identity (%)",
    "deg_evalue": "DEG E-value",
    "hit_in_deg": "Hit in DEG",
    "no_hit": "No hit",
    "ec_number": "EC number",
    "go_term": "GO term",
    "druggability": "Druggability (FPocket)",
    "p2rank_probability": "Druggability (P2Rank)",
}


def _selected_parameter_kind(parameter):
    return str(parameter.get("type") or "categorical").strip().lower()


def _coerce_numeric_filter_value(value):
    if value in ("", None):
        return None
    try:
        return float(str(value).replace(",", "."))
    except (TypeError, ValueError):
        return None


def _coerce_score_param_id(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _normalize_numeric_operation(value):
    operation = str(value or "").strip().lower()
    return {
        "gte": ">=",
        "min": ">=",
        ">=": ">=",
        "lte": "<=",
        "max": "<=",
        "<=": "<=",
        "between": "between",
        "range": "between",
    }.get(operation)


def normalize_selected_parameters(raw_selected_parameters):
    if not isinstance(raw_selected_parameters, list):
        return []

    selected_parameters = []
    numeric_index_by_param_id = {}
    for item in raw_selected_parameters:
        if not isinstance(item, dict):
            continue
        if _selected_parameter_kind(item) != "numeric":
            selected_parameters.append(item)
            continue

        param_id = _coerce_score_param_id(item.get("score_param_id"))
        operation = _normalize_numeric_operation(item.get("operation"))
        value = _coerce_numeric_filter_value(item.get("value"))
        value_max = _coerce_numeric_filter_value(item.get("value_max"))
        if param_id is None or operation is None:
            continue
        if operation == "between" and (value is None or value_max is None):
            continue
        if operation in {">=", "<="} and value is None:
            continue

        clean_item = {
            **item,
            "score_param_id": param_id,
            "operation": operation,
            "value": value,
            "value_max": value_max if operation == "between" else None,
            "name": item.get("name") or item.get("display_name") or "",
        }
        existing_index = numeric_index_by_param_id.get(param_id)
        if existing_index is None:
            numeric_index_by_param_id[param_id] = len(selected_parameters)
            selected_parameters.append(clean_item)
        else:
            selected_parameters[existing_index] = clean_item
    return selected_parameters


def encode_selected_parameters(selected_parameters):
    """Serialize a selected_parameters list into a URL-safe string, for a
    shareable link that reproduces the current filters for anyone who opens
    it (selected_parameters otherwise lives only in server-side session --
    see ProteinListView.get()'s ?filters= handling)."""
    raw = json.dumps(selected_parameters, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii")


def decode_selected_parameters_param(raw):
    """Inverse of encode_selected_parameters. Returns None (never raises) on
    any malformed/truncated/tampered value -- a broken shared link must fail
    to seed filters, not crash the page."""
    try:
        decoded = base64.urlsafe_b64decode(raw.encode("ascii"))
        parsed = json.loads(decoded)
    except (ValueError, TypeError, UnicodeDecodeError, UnicodeEncodeError):
        return None
    return parsed if isinstance(parsed, list) else None


def filter_visible_selected_parameters(selected_parameters, visible_score_param_ids):
    """Drop any categorical/numeric filter whose score_param_id isn't in
    visible_score_param_ids -- a shared link can reference a Custom column
    owned by a different user (or since deleted), and ScoreParam.objects.get
    would still succeed since the row exists; visibility must be checked
    against the requesting user explicitly. "special" filters (EC/GO/ligand/
    pathway) aren't tied to a real ScoreParam row, so they're always kept.
    Returns (kept_list, dropped_count)."""
    kept = []
    dropped = 0
    for item in selected_parameters:
        if _selected_parameter_kind(item) == "special":
            kept.append(item)
            continue
        if _coerce_score_param_id(item.get("score_param_id")) in visible_score_param_ids:
            kept.append(item)
        else:
            dropped += 1
    return kept, dropped


def _format_numeric_filter_value(value):
    coerced = _coerce_numeric_filter_value(value)
    if coerced is None:
        return ""
    return f"{coerced:g}"


def _selected_parameter_display_value(parameter, humanize=False):
    kind = _selected_parameter_kind(parameter)
    if kind == "special":
        special_value = parameter.get("display_name") or parameter.get("name", "")
        return humanize_identifier(special_value) if humanize else special_value
    if kind != "numeric":
        option_name = parameter.get("name", "")
        return humanize_identifier(option_name) if humanize else option_name

    operation = _normalize_numeric_operation(parameter.get("operation")) or ""
    value = _coerce_numeric_filter_value(parameter.get("value"))
    value_max = _coerce_numeric_filter_value(parameter.get("value_max"))
    if operation == "between":
        if value is None and value_max is None:
            return parameter.get("display_name") or "range"
        if value is None:
            return f"≤ {_format_numeric_filter_value(value_max)}"
        if value_max is None:
            return f"≥ {_format_numeric_filter_value(value)}"
        return f"between {_format_numeric_filter_value(value)} and {_format_numeric_filter_value(value_max)}"
    if value is None:
        return parameter.get("display_name") or operation
    return f"{operation} {_format_numeric_filter_value(value)}"


def humanize_identifier(value):
    text = str(value or "").strip()
    if not text:
        return ""
    exact_replacement = EXACT_REPLACEMENTS.get(text.lower())
    if exact_replacement:
        return exact_replacement
    text = re.sub(r"[_-]+", " ", text)
    text = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    tokens = text.split(" ")
    human_tokens = []
    for idx, token in enumerate(tokens):
        token_l = token.lower()
        if token_l in ACRONYM_TOKENS:
            human_tokens.append(ACRONYM_TOKENS[token_l])
            continue
        if token_l in TOKEN_REPLACEMENTS:
            human_tokens.append(TOKEN_REPLACEMENTS[token_l])
            continue
        if idx > 0 and token_l in LOWER_CONNECTORS:
            human_tokens.append(token_l)
            continue
        human_tokens.append(token.capitalize())
    return " ".join(human_tokens)


def grouped_selected_parameters(selected_parameters, humanize=False):
    grouped_data = {}
    for item in selected_parameters:
        score_param_name = item.get("score_param_name")
        if not score_param_name:
            continue
        option_name = _selected_parameter_display_value(item, humanize=humanize)
        if humanize:
            score_param_name = humanize_identifier(score_param_name) or score_param_name
        grouped_data.setdefault(score_param_name, []).append(option_name)
    return {k: ", ".join(v) for k, v in grouped_data.items()}


def _tag_grouped_option(option_dict, change):
    """Attach the advanced filter builder's group_id/group_mode (see
    apply_selected_parameter_filters) to a freshly built option dict, when
    the change dict that produced it carries one. Also makes the option's
    dedup id group-scoped, so an advanced-group condition can never collide
    with (and silently get removed together with, via remove_selected_parameter)
    an identical condition added from the plain filter panel."""
    group_id = change.get("group_id")
    if not group_id:
        return option_dict
    return {
        **option_dict,
        "group_id": group_id,
        "group_mode": "any" if str(change.get("group_mode") or "").lower() == "any" else "all",
        "id": f"{group_id}:{option_dict.get('id')}",
    }


def add_selected_parameter(selected_parameters, option_dict):
    if not option_dict:
        return selected_parameters
    option_kind = _selected_parameter_kind(option_dict)
    if option_kind == "numeric":
        option_param_id = _coerce_score_param_id(option_dict.get("score_param_id"))
        if option_param_id is None:
            return selected_parameters
        selected_parameters = [
            item
            for item in selected_parameters
            if _selected_parameter_kind(item) != "numeric"
            or _coerce_score_param_id(item.get("score_param_id")) != option_param_id
        ]
    elif option_kind == "special" and option_dict.get("special_key") == "ligand_filter":
        selected_parameters = [
            item
            for item in selected_parameters
            if _selected_parameter_kind(item) != "special"
            or item.get("special_key") != "ligand_filter"
        ]
    option_id = str(option_dict.get("id"))
    if any(str(item.get("id")) == option_id for item in selected_parameters):
        return selected_parameters
    return [*selected_parameters, option_dict]


def remove_selected_parameter(selected_parameters, option_id):
    option_id = str(option_id)
    return [item for item in selected_parameters if str(item.get("id")) != option_id]


def build_special_filter_payload(kind, value):
    value = (value or "").strip()
    if not value:
        return None
    if kind == "ec":
        return {
            "id": f"special:ec:{value}",
            "score_param_name": "ec_number",
            "name": value,
            "type": "special",
            "special_key": "ec_filter",
            "special_value": value,
            "display_name": value,
        }
    if kind == "go":
        normalized = value.upper() if not value.upper().startswith("GO:") else value.upper()
        if not normalized.startswith("GO:") and normalized.isdigit():
            normalized = f"GO:{normalized.zfill(7)}"
        return {
            "id": f"special:go:{normalized}",
            "score_param_name": "go_term",
            "name": normalized,
            "type": "special",
            "special_key": "go_filter",
            "special_value": normalized,
            "display_name": normalized,
        }
    if kind == "ligands":
        normalized = value.strip().lower()
        if normalized not in ("yes", "no"):
            return None
        display = "Has ligand evidence" if normalized == "yes" else "No ligand evidence"
        return {
            "id": f"special:ligands:{normalized}",
            "score_param_name": "ligand_evidence",
            "name": display,
            "type": "special",
            "special_key": "ligand_filter",
            "special_value": normalized,
            "display_name": display,
        }
    if kind == "pathway":
        from tpweb.models.Metabolism import MetabolicPathway

        if ":" not in value:
            return None
        source, external_id = value.split(":", 1)
        pathway = MetabolicPathway.objects.filter(source=source, external_id=external_id).first()
        if pathway is None:
            return None
        return {
            "id": f"special:pathway:{source}:{external_id}",
            "score_param_name": "metabolic_pathway",
            "name": pathway.name,
            "type": "special",
            "special_key": "pathway_filter",
            "special_value": value,
            "display_name": pathway.name,
        }
    return None


def build_numeric_filter_payload(score_param_id, raw_min, raw_max, operation=None):
    from tpweb.models.ScoreParam import ScoreParam

    try:
        param_pk = int(score_param_id)
    except (TypeError, ValueError):
        return None
    try:
        score_param = ScoreParam.objects.get(pk=param_pk)
    except ScoreParam.DoesNotExist:
        return None
    try:
        value_min = float(str(raw_min).replace(",", ".")) if raw_min not in ("", None) else None
    except (TypeError, ValueError):
        value_min = None
    try:
        value_max = float(str(raw_max).replace(",", ".")) if raw_max not in ("", None) else None
    except (TypeError, ValueError):
        value_max = None

    requested_operation = str(operation or "").strip().lower()
    operation_map = {
        "gte": ">=",
        ">=": ">=",
        "min": ">=",
        "lte": "<=",
        "<=": "<=",
        "max": "<=",
        "between": "between",
        "range": "between",
    }
    requested_operation = operation_map.get(requested_operation)

    if requested_operation == ">=":
        value_max = None
    elif requested_operation == "<=":
        if value_max is None:
            value_max = value_min
        value_min = None
    elif requested_operation == "between":
        if value_min is None or value_max is None:
            return None

    if value_min is None and value_max is None:
        return None
    if value_min is not None and value_max is not None:
        if value_min > value_max:
            value_min, value_max = value_max, value_min
        operation = "between"
        display_value = f"between {value_min:g} and {value_max:g}"
        filter_id = f"numeric:{score_param.pk}:between:{value_min:g}:{value_max:g}"
        primary_value = value_min
    elif value_min is not None:
        operation = ">="
        display_value = f"≥ {value_min:g}"
        filter_id = f"numeric:{score_param.pk}:>=:{value_min:g}"
        primary_value = value_min
    else:
        operation = "<="
        display_value = f"≤ {value_max:g}"
        filter_id = f"numeric:{score_param.pk}:<=:{value_max:g}"
        primary_value = value_max
        value_max = None
    return {
        "id": filter_id,
        "score_param_id": score_param.pk,
        "score_param_name": score_param.name,
        "type": "numeric",
        "operation": operation,
        "value": primary_value,
        "value_max": value_max if operation == "between" else None,
        "display_name": display_value,
    }


def apply_filter_change(selected_parameters, change):
    """Fold one change-dict ({"action": "add_filter"/"add_numeric_filter"/
    "add_special_filter"/"remove_filter", ...}) into selected_parameters.
    Shared by ProteinListView's own filter-change POST handling and the
    agent's apply_filters/search_proteins tools."""
    from tpweb.models.ScoreParam import ScoreParamOptions

    if not isinstance(change, dict):
        return selected_parameters
    action = (change.get("action") or "").strip()

    if action == "add_filter":
        option_id = change.get("filter_option_id")
        if option_id:
            try:
                option_dict = ScoreParamOptions.objects.get(id=option_id).to_dict()
                option_dict = _tag_grouped_option(option_dict, change)
                selected_parameters = add_selected_parameter(selected_parameters, option_dict)
            except (ScoreParamOptions.DoesNotExist, ValueError, TypeError):
                pass

    elif action == "add_special_filter":
        payload = build_special_filter_payload(
            (change.get("special_kind") or "").strip().lower(),
            (change.get("special_value") or "").strip(),
        )
        if payload:
            selected_parameters = add_selected_parameter(selected_parameters, payload)

    elif action == "add_numeric_filter":
        payload = build_numeric_filter_payload(
            (change.get("score_param_id") or "").strip(),
            (change.get("value") or "").strip(),
            (change.get("value_max") or "").strip(),
            operation=(change.get("numeric_operation") or "").strip(),
        )
        if payload:
            payload = _tag_grouped_option(payload, change)
            selected_parameters = add_selected_parameter(selected_parameters, payload)

    elif action == "remove_filter":
        option_id = change.get("filter_option_id")
        if option_id:
            selected_parameters = remove_selected_parameter(selected_parameters, option_id)

    return selected_parameters


def apply_filter_changes(selected_parameters, changes):
    """Apply an already-parsed list[dict] of change-dicts (see
    apply_filter_change) to selected_parameters, normalizing the result.
    Callers that receive a JSON string (e.g. ProteinListView's own POST
    handler) must json.loads it before calling this."""
    if not isinstance(changes, list):
        return selected_parameters
    for change in changes:
        selected_parameters = apply_filter_change(selected_parameters, change)
    return normalize_selected_parameters(selected_parameters)


def selected_parameters_to_filter_map(selected_parameters):
    parameter_map = {}
    for parameter in selected_parameters:
        if _selected_parameter_kind(parameter) in {"numeric", "special"}:
            continue
        score_param = _coerce_score_param_id(parameter.get("score_param_id"))
        score_name = parameter.get("name")
        if score_param is None or score_name in ("", None):
            continue
        if score_param not in parameter_map:
            parameter_map[score_param] = [score_name]
        else:
            parameter_map[score_param].append(score_name)
    return parameter_map


def _condition_q(parameter, param_name_by_id):
    """Build a single Q object for one selected_parameters condition, for use
    OR-combining conditions within an explicit "any" advanced-filter group
    (see apply_selected_parameter_filters). Only covers categorical and
    numeric score-param conditions -- the only condition types the advanced
    filter builder UI exposes -- and returns None for anything else
    (special/EC/GO/ligand/pathway filters stay AND-only for now)."""
    kind = _selected_parameter_kind(parameter)
    if kind == "special":
        return None
    param_id = _coerce_score_param_id(parameter.get("score_param_id"))
    if param_id is None:
        return None

    if kind == "numeric":
        operation = _normalize_numeric_operation(parameter.get("operation"))
        value = _coerce_numeric_filter_value(parameter.get("value"))
        value_max = _coerce_numeric_filter_value(parameter.get("value_max"))
        if operation == ">=":
            if value is None:
                return None
            return Q(score_params__score_param_id=param_id, score_params__numeric_value__gte=value)
        if operation == "<=":
            if value is None:
                return None
            return Q(score_params__score_param_id=param_id, score_params__numeric_value__lte=value)
        if operation == "between":
            if value is None and value_max is None:
                return None
            if value is None:
                return Q(
                    score_params__score_param_id=param_id,
                    score_params__numeric_value__lte=value_max,
                )
            if value_max is None:
                return Q(
                    score_params__score_param_id=param_id, score_params__numeric_value__gte=value
                )
            return Q(
                score_params__score_param_id=param_id,
                score_params__numeric_value__gte=value,
                score_params__numeric_value__lte=value_max,
            )
        return None

    value_name = parameter.get("name")
    if value_name in ("", None):
        return None
    param_name = param_name_by_id.get(param_id, "")
    if param_name in CORE_GENOME_PARAM_NAMES:
        if value_name == "Core":
            return Q(score_params__score_param_id=param_id, score_params__numeric_value__gte=0.5)
        if value_name == "Accessory":
            return Q(score_params__score_param_id=param_id, score_params__numeric_value__lt=0.5)
        return None
    return Q(score_params__score_param_id=param_id, score_params__value=value_name)


def apply_selected_parameter_filters(queryset, selected_parameters):
    """Apply every filter in selected_parameters to queryset.

    Each item optionally carries `group_id` / `group_mode` ("all" default /
    "any"), written by the advanced filter builder (see
    tpweb/views/ProteinListView.py's ProteinAdvancedFiltersView). Items without a
    real multi-condition "any" group go through the original AND-only path
    unchanged -- so every filter added from the simple panel keeps its exact
    prior query behavior. Only a group_mode="any" group with 2+ conditions
    gets OR-combined, via its own single .filter() call so it still ANDs
    correctly against every other group/condition (Django collapses multiple
    conditions on the same many-valued relation into one join per filter()
    call, so combining unrelated AND'd conditions into one call would wrongly
    require them to match the same related row -- each group therefore gets
    its own call, same as every ungrouped condition already does below)."""
    or_groups = {}
    and_items = []
    for parameter in selected_parameters:
        group_id = parameter.get("group_id")
        group_mode = str(parameter.get("group_mode") or "all").strip().lower()
        if group_id and group_mode == "any":
            or_groups.setdefault(group_id, []).append(parameter)
        else:
            and_items.append(parameter)

    # A singleton "any" group is just its one condition -- OR of one thing --
    # so fold it back into the plain AND path instead of paying for a
    # separate combined-Q filter() call.
    for group_id, items in list(or_groups.items()):
        if len(items) < 2:
            and_items.extend(items)
            del or_groups[group_id]

    filtered_queryset = _apply_and_selected_parameter_filters(queryset, and_items)

    if or_groups:
        param_name_by_id = {}
        for parameter in selected_parameters:
            pid = _coerce_score_param_id(parameter.get("score_param_id"))
            pname = str(parameter.get("score_param_name") or "").strip().lower()
            if pid is not None and pname:
                param_name_by_id[pid] = pname
        for items in or_groups.values():
            group_q = Q()
            has_condition = False
            for parameter in items:
                condition = _condition_q(parameter, param_name_by_id)
                if condition is None:
                    continue
                group_q |= condition
                has_condition = True
            if has_condition:
                filtered_queryset = filtered_queryset.filter(group_q)

    return filtered_queryset


def _apply_and_selected_parameter_filters(queryset, selected_parameters):
    filtered_queryset = queryset
    parameter_map = selected_parameters_to_filter_map(selected_parameters)
    param_name_by_id = {}
    for parameter in selected_parameters:
        pid = _coerce_score_param_id(parameter.get("score_param_id"))
        pname = str(parameter.get("score_param_name") or "").strip().lower()
        if pid is not None and pname:
            param_name_by_id[pid] = pname
    for param_id, values in parameter_map.items():
        param_name = param_name_by_id.get(param_id, "")
        if param_name in CORE_GENOME_PARAM_NAMES:
            core_q = Q()
            if "Core" in values:
                core_q |= Q(
                    score_params__score_param_id=param_id, score_params__numeric_value__gte=0.5
                )
            if "Accessory" in values:
                core_q |= Q(
                    score_params__score_param_id=param_id, score_params__numeric_value__lt=0.5
                )
            if core_q:
                filtered_queryset = filtered_queryset.filter(core_q)
            continue
        filtered_queryset = filtered_queryset.filter(
            Q(score_params__score_param_id=param_id) & Q(score_params__value__in=values)
        )
    special_groups = {}
    for parameter in selected_parameters:
        if _selected_parameter_kind(parameter) != "special":
            continue
        special_key = str(parameter.get("special_key") or "").strip()
        special_value = str(parameter.get("special_value") or "").strip()
        if not special_key or not special_value:
            continue
        special_groups.setdefault(special_key, []).append(special_value)

    structure_values = [value.lower() for value in special_groups.get("structure_source", [])]
    if structure_values:
        structure_query = Q()
        if "none" in structure_values:
            structure_query |= Q(structures__isnull=True)
        if "experimental" in structure_values:
            structure_query |= Q(structures__isnull=False) & ~Q(
                structures__pdb__experiment__in=PDB_MODEL_EXPERIMENTS
            )
        if "alphafold" in structure_values:
            structure_query |= Q(structures__pdb__experiment=PDB_EXPERIMENT_ALPHAFOLD)
        if "colabfold" in structure_values:
            structure_query |= Q(structures__pdb__experiment=PDB_EXPERIMENT_COLABFOLD)
        filtered_queryset = filtered_queryset.filter(structure_query)

    ligand_values = [value.lower() for value in special_groups.get("ligand_filter", [])]
    if ligand_values:
        wants_ligands = "yes" in ligand_values
        wants_no_ligands = "no" in ligand_values
        if wants_ligands != wants_no_ligands:
            filtered_queryset = filtered_queryset.annotate(
                has_ligand_evidence=Exists(
                    Binders.objects.filter(locustag_id=OuterRef("accession"))
                )
            ).filter(has_ligand_evidence=wants_ligands)

    ec_values = [value for value in special_groups.get("ec_filter", []) if value]
    if ec_values:
        ec_query = Q()
        for ec_value in ec_values:
            ec_query |= Q(
                dbxrefs__dbxref__dbname="ec",
                dbxrefs__dbxref__accession__istartswith=ec_value,
            )
        filtered_queryset = filtered_queryset.filter(ec_query)

    go_values = [value for value in special_groups.get("go_filter", []) if value]
    if go_values:
        go_query = Q()
        for go_value in go_values:
            go_query |= Q(
                dbxrefs__dbxref__dbname__in=["go", "GO"],
                dbxrefs__dbxref__accession__iexact=go_value,
            )
        filtered_queryset = filtered_queryset.filter(go_query)

    pathway_values = [
        value for value in special_groups.get("pathway_filter", []) if value and ":" in value
    ]
    if pathway_values:
        pathway_query = Q()
        for pathway_value in pathway_values:
            source, external_id = pathway_value.split(":", 1)
            pathway_query |= Q(
                metabolic_reactions__reaction__pathways__source=source,
                metabolic_reactions__reaction__pathways__external_id=external_id,
            )
        filtered_queryset = filtered_queryset.filter(pathway_query)

    for parameter in selected_parameters:
        if _selected_parameter_kind(parameter) != "numeric":
            continue
        param_id = _coerce_score_param_id(parameter.get("score_param_id"))
        if param_id is None:
            continue
        operation = _normalize_numeric_operation(parameter.get("operation"))
        if operation is None:
            continue
        value = _coerce_numeric_filter_value(parameter.get("value"))
        value_max = _coerce_numeric_filter_value(parameter.get("value_max"))
        if operation == ">=":
            if value is None:
                continue
            filtered_queryset = filtered_queryset.filter(
                score_params__score_param_id=param_id,
                score_params__numeric_value__gte=value,
            )
        elif operation == "<=":
            if value is None:
                continue
            filtered_queryset = filtered_queryset.filter(
                score_params__score_param_id=param_id,
                score_params__numeric_value__lte=value,
            )
        elif operation == "between":
            if value is None and value_max is None:
                continue
            if value is None:
                filtered_queryset = filtered_queryset.filter(
                    score_params__score_param_id=param_id,
                    score_params__numeric_value__lte=value_max,
                )
                continue
            if value_max is None:
                filtered_queryset = filtered_queryset.filter(
                    score_params__score_param_id=param_id,
                    score_params__numeric_value__gte=value,
                )
                continue
            filtered_queryset = filtered_queryset.filter(
                score_params__score_param_id=param_id,
                score_params__numeric_value__gte=value,
                score_params__numeric_value__lte=value_max,
            )
    return filtered_queryset


def apply_protein_search(queryset, search_query):
    cleaned_query = (search_query or "").strip()
    if not cleaned_query:
        return queryset

    return queryset.filter(
        Q(accession__icontains=cleaned_query)
        | Q(description__icontains=cleaned_query)
        | Q(accession__iexact=cleaned_query)
        | Q(qualifiers__value__icontains=cleaned_query, qualifiers__term__identifier="gene")
    )


def find_top_proteins(assembly_name, selected_parameters, search_text=None, limit=10):
    """Filter+search a genome's proteins and return up to `limit` compact
    dicts ({accession, description, druggability}), with no pagination/HTTP
    concerns. Used by the search_proteins agent tool. Ordering is by
    accession (deterministic), not a ranking -- ranking a specific protein's
    overall target quality is assembly_workspace.score_single_protein's job,
    not this function's."""
    from bioseq.models.Biodatabase import Biodatabase
    from bioseq.models.Bioentry import Bioentry
    from tpweb.services.protein_serializer import score_param_value_map

    proteins = Bioentry.objects.filter(biodatabase__name=assembly_name + Biodatabase.PROT_POSTFIX)
    if selected_parameters:
        proteins = apply_selected_parameter_filters(proteins, selected_parameters)
    proteins = apply_protein_search(proteins, search_text)
    proteins = (
        proteins.prefetch_related("score_params__score_param")
        .order_by("accession")
        .distinct()[: max(1, min(int(limit or 10), 25))]
    )

    results = []
    for protein in proteins:
        param_values = score_param_value_map(protein)
        results.append(
            {
                "accession": protein.accession,
                "description": protein.description or "",
                "druggability": param_values.get("Druggability"),
            }
        )
    return results


def parse_page_size(page_size_raw):
    try:
        parsed = int(page_size_raw)
    except (TypeError, ValueError):
        parsed = DEFAULT_PAGE_SIZE
    return max(MIN_PAGE_SIZE, min(parsed, MAX_PAGE_SIZE))


class _EmptyPaginator:
    count = 0


class _EmptyProteinPage:
    paginator = _EmptyPaginator()


def empty_pagination_payload():
    return {
        "number": 1,
        "num_pages": 1,
        "page_range": [1],
        "has_previous": False,
        "has_next": False,
        "proteins": _EmptyProteinPage(),
    }
