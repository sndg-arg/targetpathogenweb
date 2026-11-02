from django import template

from tpweb.services.genome_titles import genome_info as _genome_info

register = template.Library()


@register.filter
def genome_title(name):
    """{{ genome|genome_title }} -> "Klebsiella pneumoniae (Kp13)"."""
    return _genome_info(name)["title"]


@register.filter
def genome_info(name):
    """{% with g=genome|genome_info %}: title, organism, strain, accession."""
    return _genome_info(name)


@register.filter
def megabases(value):
    """5739888 -> "5.7 Mb", the unit genome sizes are quoted in; "—" if unknown."""
    try:
        length = int(float(str(value)))
    except (TypeError, ValueError):
        return "—"
    if length <= 0:
        return "—"
    if length < 1_000_000:
        return f"{length / 1000:.0f} kb"
    return f"{length / 1_000_000:.1f} Mb"
