from django import template
import re

register = template.Library()

@register.filter
def dictkey(diccionario, key):
    return diccionario.get(key)

@register.filter
def replace_char(value, old_char_coma_new_char):
    old_char,new_char = old_char_coma_new_char.split(",")
    return value.replace(old_char, new_char)


@register.filter
def humanize_identifier(value):
    text = str(value or "").strip()
    if not text:
        return ""

    exact_replacements = {
        "human_offtarget": "Human off-target",
        "gut_microbiome_offtarget": "Gut microbiome off-target",
        "hit_in_deg": "Hit in DEG",
        "no_hit": "No hit",
    }
    exact_replacement = exact_replacements.get(text.lower())
    if exact_replacement:
        return exact_replacement

    acronym_tokens = {
        "deg": "DEG",
        "ppi": "PPI",
        "dna": "DNA",
        "rna": "RNA",
        "p2rank": "P2RANK",
        "fpocket": "FPocket",
        "id": "ID",
    }
    token_replacements = {
        "offtarget": "Off-target",
    }
    lower_connectors = {"and", "or", "of", "in", "on", "to", "for", "with", "without", "by"}

    text = re.sub(r"[_-]+", " ", text)
    text = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    tokens = text.split(" ")
    human_tokens = []
    for idx, token in enumerate(tokens):
        token_l = token.lower()
        if token_l in acronym_tokens:
            human_tokens.append(acronym_tokens[token_l])
            continue
        if token_l in token_replacements:
            human_tokens.append(token_replacements[token_l])
            continue
        if idx > 0 and token_l in lower_connectors:
            human_tokens.append(token_l)
            continue
        human_tokens.append(token.capitalize())

    return " ".join(human_tokens)
