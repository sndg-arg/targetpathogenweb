from django import template

register = template.Library()

@register.filter
def dictkey(diccionario, key):
    return diccionario.get(key)

@register.filter
def replace_char(value, old_char_coma_new_char):
    old_char,new_char = old_char_coma_new_char.split(",")
    return value.replace(old_char, new_char)
