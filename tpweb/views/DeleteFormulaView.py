from django.http import Http404
from django.shortcuts import redirect
from django.urls import reverse
from django.views.decorators.http import require_POST

from tpweb.models.ScoreFormula import ScoreFormula
from tpweb.services.genome_workspace import genome_url_slug, resolve_genome_from_slug
from tpweb.services.workspace import resolve_workspace_user


@require_POST
def delete_formula_view(request, genome, formula_pk):
    assembly_name = resolve_genome_from_slug(request.user, genome)
    if not assembly_name:
        raise Http404("Genome not found")

    user = resolve_workspace_user(request.user)
    try:
        formula = ScoreFormula.objects.get(pk=formula_pk, user=user)
        formula.delete()
    except ScoreFormula.DoesNotExist:
        pass  # already gone or doesn't belong to this user — ignore silently

    return redirect(reverse("tpwebapp:protein_list", kwargs={"genome": genome_url_slug(assembly_name)}))
