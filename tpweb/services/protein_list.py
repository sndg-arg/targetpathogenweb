from django.db.models import Q


MIN_PAGE_SIZE = 10
MAX_PAGE_SIZE = 100
DEFAULT_PAGE_SIZE = 25


def normalize_selected_parameters(raw_selected_parameters):
    if not isinstance(raw_selected_parameters, list):
        return []
    return raw_selected_parameters


def grouped_selected_parameters(selected_parameters):
    grouped_data = {}
    for item in selected_parameters:
        score_param_name = item["score_param_name"]
        option_name = item["name"]
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
        score_param = parameter.get("score_param_id")
        score_name = parameter.get("name")
        if score_param not in parameter_map:
            parameter_map[score_param] = [score_name]
        else:
            parameter_map[score_param].append(score_name)
    return parameter_map


def apply_selected_parameter_filters(queryset, selected_parameters):
    parameter_map = selected_parameters_to_filter_map(selected_parameters)
    filtered_queryset = queryset
    for param_id, values in parameter_map.items():
        filtered_queryset = filtered_queryset.filter(
            Q(score_params__score_param_id=param_id) & Q(score_params__value__in=values)
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

