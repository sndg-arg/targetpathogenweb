"""Shared helpers for form widgets and label humanisation.

Originally housed the legacy ParameterForm used by the standalone advanced-filters
page. That page was folded into the protein list filters drawer; this module now
keeps only the bits other forms still depend on (FormulaForm uses
HumanizedModelChoiceField, several views call humanize_identifier).
"""

import re

from django import forms


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
    "ec": "EC",
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


class HumanizedModelChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, obj):
        if hasattr(obj, "name"):
            return humanize_identifier(obj.name)
        return super().label_from_instance(obj)
