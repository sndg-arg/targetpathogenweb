from django.db.models import Q
import re

from tpweb.services.structure_sources import (
    PDB_EXPERIMENT_ALPHAFOLD,
    PDB_EXPERIMENT_COLABFOLD,
    PDB_MODEL_EXPERIMENTS,
)

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
    "id": "ID",
}

TOKEN_REPLACEMENTS = {
    "offtarget": "Off-target",
}

LOWER_CONNECTORS = {"and", "or", "of", "in", "on", "to", "for", "with", "without", "by"}
EXACT_REPLACEMENTS = {
    "human_offtarget": "Human off-target",
    "gut_microbiome_offtarget": "Gut microbiome off-target",
    "hit_in_deg": "Hit in DEG",
    "no_hit": "No hit",
    "ec_number": "EC number",
    "go_term": "GO term",
}


def normalize_selected_parameters(raw_selected_parameters):
    if not isinstance(raw_selected_parameters, list):
        return []
    return [item for item in raw_selected_parameters if isinstance(item, dict)]


def _selected_parameter_kind(parameter):
    return str(parameter.get("type") or "categorical").strip().lower()


def _selected_parameter_display_value(parameter, humanize=False):
    kind = _selected_parameter_kind(parameter)
    if kind == "special":
        special_value = parameter.get("display_name") or parameter.get("name", "")
        return humanize_identifier(special_value) if humanize else special_value
    if kind != "numeric":
        option_name = parameter.get("name", "")
        return humanize_identifier(option_name) if humanize else option_name

    operation = str(parameter.get("operation") or "").strip()
    value = parameter.get("value")
    value_max = parameter.get("value_max")
    if operation == "between":
        return f"{operation} {value:g} - {value_max:g}"
    return f"{operation} {value:g}"


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
        score_param_name = item["score_param_name"]
        option_name = _selected_parameter_display_value(item, humanize=humanize)
        if humanize:
            score_param_name = humanize_identifier(score_param_name) or score_param_name
        grouped_data.setdefault(score_param_name, []).append(option_name)
    return {k: ", ".join(v) for k, v in grouped_data.items()}


def add_selected_parameter(selected_parameters, option_dict):
    if not option_dict:
        return selected_parameters
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
        score_param = parameter.get("score_param_id")
        score_name = parameter.get("name")
        if score_param not in parameter_map:
            parameter_map[score_param] = [score_name]
        else:
            parameter_map[score_param].append(score_name)
    return parameter_map


def apply_selected_parameter_filters(queryset, selected_parameters):
    filtered_queryset = queryset
    parameter_map = selected_parameters_to_filter_map(selected_parameters)
    for param_id, values in parameter_map.items():
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
        param_id = parameter.get("score_param_id")
        operation = parameter.get("operation")
        value = parameter.get("value")
        value_max = parameter.get("value_max")
        if operation == ">=":
            filtered_queryset = filtered_queryset.filter(
                score_params__score_param_id=param_id,
                score_params__numeric_value__gte=value,
            )
        elif operation == "<=":
            filtered_queryset = filtered_queryset.filter(
                score_params__score_param_id=param_id,
                score_params__numeric_value__lte=value,
            )
        elif operation == "between":
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
