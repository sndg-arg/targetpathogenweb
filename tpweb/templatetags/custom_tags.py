from django import template

from tpweb.services.protein_list import humanize_identifier as _humanize_identifier
from tpweb.services.protein_summary import druggability_label

register = template.Library()

register.filter("humanize_identifier", _humanize_identifier)


@register.filter
def dictkey(diccionario, key):
    return diccionario.get(key)


@register.filter
def replace_char(value, old_char_coma_new_char):
    old_char, new_char = old_char_coma_new_char.split(",")
    return value.replace(old_char, new_char)


@register.filter
def score_metric_display(value, column_name):
    text = str(value if value is not None else "").strip()
    if not text or text in {"-", "—"} or text.lower() in {"none", "nan", "null"}:
        return "—"

    column_key = str(column_name or "").strip().lower()
    try:
        numeric = float(text.replace(",", "."))
    except (TypeError, ValueError):
        if column_key in {"core_roary", "core_corecruncher"}:
            if text.lower() in {"true", "1", "yes", "y", "core"}:
                return "Core"
            if text.lower() in {"false", "0", "no", "n", "accessory"}:
                return "Accessory"
            return text
        if column_key.endswith("_structure"):
            return text
        if column_key.endswith("_pocket"):
            if text == "No_pockets":
                return "No pockets"
            if text.lower().startswith("pocket pocket"):
                suffix = text[len("Pocket pocket") :].strip()
                return f"Pocket {suffix}" if suffix else "Pocket"
            return text
        return _humanize_identifier(text) or text

    if column_key.endswith("_evalue"):
        return f"{numeric:.2e}"
    if column_key.endswith("_identity"):
        return f"{numeric:.1f}%"
    if column_key in {"core_roary", "core_corecruncher"}:
        return "Core" if numeric >= 0.5 else "Accessory"
    if (
        column_key.endswith("_probability")
        or column_key.endswith("_score")
        or column_key.endswith("_norm")
    ):
        return f"{numeric:.3f}"
    return f"{numeric:g}"


@register.filter
def druggability_display(value):
    try:
        numeric = float(str(value).replace(",", "."))
    except (TypeError, ValueError):
        return value
    return f"{numeric:.3f}".rstrip("0").rstrip(".")


@register.filter
def druggability_tone(value):
    """Return the high/mid/low tone for a druggability score.

    Reuses protein_summary.druggability_label (the same threshold logic the
    protein detail page's metric-pill uses) so the proteins list table's
    per-cell tone doesn't drift out of sync with a second, hand-copied set
    of thresholds.
    """
    result = druggability_label(value)
    return result[1] if result else ""


@register.filter
def score_metric_tone(value, column_name):
    text = str(value if value is not None else "").strip().lower()
    column_key = str(column_name or "").strip().lower()

    if column_key in {"human_offtarget", "gut_microbiome_offtarget"}:
        if text == "hit":
            return "risk"
        if text in {"no_hit", "no hit"}:
            return "favorable"
        return ""

    if column_key in {"core_roary", "core_corecruncher"}:
        try:
            return "favorable" if float(text) >= 0.5 else "secondary"
        except (ValueError, TypeError):
            if text in {"core", "true", "1", "y", "yes"}:
                return "favorable"
            if text in {"accessory", "false", "0", "n", "no"}:
                return "secondary"
        return ""

    if column_key == "hit_in_deg":
        if text == "y":
            return "favorable"
        if text == "n":
            return "secondary"
        return ""

    if column_key == "localization":
        if text in {
            "extracellular",
            "outer membrane",
            "cellwall",
            "periplasmic",
            "cytoplasmic membrane",
        }:
            return "favorable"
        if text == "cytoplasmic":
            return "risk"
        return ""

    return ""
