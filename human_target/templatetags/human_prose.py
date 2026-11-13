"""UniProt prose for the human protein page."""

import re

from django import template
from django.utils.html import escape
from django.utils.safestring import mark_safe

register = template.Library()

_EVIDENCE = re.compile(r"\s*\((By similarity|Probable|Potential)\)", re.IGNORECASE)


@register.filter
def uniprot_prose(text):
    """Escaped UniProt text with line breaks, its "(By similarity)" /
    "(Probable)" qualifiers set as quiet tags instead of parentheticals."""
    html = escape(text or "").replace("\n", "<br>")
    html = _EVIDENCE.sub(lambda m: f' <span class="h-evidence">{m.group(1).lower()}</span>', html)
    return mark_safe(html)
