NUMERIC_SCORE_PARAM_TYPES = {"N", "NUMERIC"}
CATEGORICAL_SCORE_PARAM_TYPES = {"C", "CATEGORICAL", ""}
SOFTCORE_COLUMN_ALIASES = {
    "softcore_roary": "soft_core_roary",
    "softcore_corecruncher": "soft_core_corecruncher",
}


def canonical_score_column_name(name):
    return SOFTCORE_COLUMN_ALIASES.get(name, name)


def is_boolean_score_series(values):
    """Detect explicit True/False values before numeric coercion turns them into 1/0."""
    tokens = {str(value).strip().lower() for value in values}
    tokens -= {"", "none", "nan", "null", "<na>"}
    return bool(tokens) and tokens <= {"true", "false"}


def score_param_kind(score_param_or_type):
    raw_type = getattr(score_param_or_type, "type", score_param_or_type)
    normalized = str(raw_type or "").strip().upper()
    if normalized in NUMERIC_SCORE_PARAM_TYPES:
        return "numeric"
    return "categorical"


def is_numeric_score_param(score_param_or_type):
    return score_param_kind(score_param_or_type) == "numeric"


def is_categorical_score_param(score_param_or_type):
    return score_param_kind(score_param_or_type) == "categorical"
