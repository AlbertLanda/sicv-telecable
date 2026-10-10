from django import template
from apps.reports.accounting_review import review_available

register = template.Library()


@register.simple_tag(takes_context=True)
def accounting_review_available(context):
    return review_available(context["request"].user)
