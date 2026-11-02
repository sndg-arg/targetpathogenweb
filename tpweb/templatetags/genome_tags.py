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
