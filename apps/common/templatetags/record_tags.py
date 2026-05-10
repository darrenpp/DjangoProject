from django import template

register = template.Library()


@register.filter
def attr(obj, field_name):
    """Safely get attribute value from object"""
    try:
        value = getattr(obj, field_name)
        if hasattr(value, 'all'):
            return value.all().count()
        return value if value is not None else "-"
    except (AttributeError, TypeError):
        return "-"


@register.filter
def get_item(mapping, key):
    try:
        return mapping.get(key)
    except AttributeError:
        return None
