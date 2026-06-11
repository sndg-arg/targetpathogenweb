from django.db.models import Q
import re

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
    "alphafold": "AlphaFold",
    "colabfold": "ColabFold",
    "plddt": "pLDDT",
    "id": "ID",
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


def add_selected_parameter(selected_parameters, option_dict):
    if not option_dict:
        return selected_parameters
    option_kind = _selected_parameter_kind(option_dict)
    if option_kind == "numeric":
        option_param_id = _coerce_score_param_id(option_dict.get("score_param_id"))
        if option_param_id is None:
            return selected_parameters
        selected_parameters = [
            item for item in selected_parameters
            if _selected_parameter_kind(item) != "numeric"
            or _coerce_score_param_id(item.get("score_param_id")) != option_param_id
        ]
    option_id = str(option_dict.get("id"))
    if any(str(item.get("id")) == option_id for item in selected_parameters):
        return selected_parameters
    return [*selected_parameters, option_dict]


def remove_selected_parameter(selected_parameters, option_id):
    option_id = str(option_id)
    return [item for item in selected_parameters if str(item.get("id")) != option_id]


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


def apply_selected_parameter_filters(queryset, selected_parameters):
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
                core_q |= Q(score_params__score_param_id=param_id, score_params__numeric_value__gte=0.5)
            if "Accessory" in values:
                core_q |= Q(score_params__score_param_id=param_id, score_params__numeric_value__lt=0.5)
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
            structure_query |= (
                Q(structures__isnull=False)
                & ~Q(structures__pdb__experiment__in=PDB_MODEL_EXPERIMENTS)
            )
        if "alphafold" in structure_values:
            structure_query |= Q(structures__pdb__experiment=PDB_EXPERIMENT_ALPHAFOLD)
        if "colabfold" in structure_values:
            structure_query |= Q(structures__pdb__experiment=PDB_EXPERIMENT_COLABFOLD)
        filtered_queryset = filtered_queryset.filter(structure_query)

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
