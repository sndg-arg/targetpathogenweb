from django.http import HttpResponse

from tpweb.services.formula_evaluator import validate_expression_syntax
from tpweb.services.workspace import resolve_workspace_user


def validate_expression_view(request):
    expr = request.GET.get("expression", "").strip()
    if not expr:
        return HttpResponse(
            '<span class="formula-valid-badge formula-valid-badge--empty">'
            'Type an expression above</span>'
        )

    user = resolve_workspace_user(request.user)
    result = validate_expression_syntax(expr, user=user)
    if result["valid"]:
        return HttpResponse(
            '<span class="formula-valid-badge formula-valid-badge--ok">'
            '<svg width="13" height="13" viewBox="0 0 13 13" fill="none" aria-hidden="true">'
            '<circle cx="6.5" cy="6.5" r="6.5" fill="currentColor" opacity=".15"/>'
            '<path d="M3.5 6.5l2 2 4-4" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/>'
            '</svg>'
            'Valid expression</span>'
        )
    else:
        error = result.get("error") or "Invalid expression"
        safe_error = error.replace("<", "&lt;").replace(">", "&gt;")
        return HttpResponse(
            f'<span class="formula-valid-badge formula-valid-badge--err">'
            f'<svg width="13" height="13" viewBox="0 0 13 13" fill="none" aria-hidden="true">'
            f'<circle cx="6.5" cy="6.5" r="6.5" fill="currentColor" opacity=".15"/>'
            f'<path d="M4 4l5 5M9 4l-5 5" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/>'
            f'</svg>'
            f'{safe_error}</span>'
        )
