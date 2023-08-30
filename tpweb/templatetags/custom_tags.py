from django import template

register = template.Library()

@register.filter
def dictkey(diccionario, key):
    return diccionario.get(key)