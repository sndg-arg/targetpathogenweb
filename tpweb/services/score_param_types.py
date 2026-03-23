NUMERIC_SCORE_PARAM_TYPES = {"N", "NUMERIC"}
CATEGORICAL_SCORE_PARAM_TYPES = {"C", "CATEGORICAL", ""}


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
