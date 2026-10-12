from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.shortcuts import render, redirect
from django.http import Http404
from django.urls import reverse
from tpweb.forms.CustomParamForm import CustomParamForm
from tpweb.models import CustomParam
from tpweb.services.custom_param_import import run_custom_param_import
from tpweb.services.workspace import resolve_workspace_user
from tpweb.services.genome_workspace import (
    display_genome_name,
    genome_url_slug,
    resolve_genome_from_slug,
)


def _page_context(form, assembly_name, **extra):
    return {
        "form": form,
        "assembly_name": assembly_name,
        "assembly_label": display_genome_name(assembly_name),
        "genome": genome_url_slug(assembly_name),
        **extra,
    }


def _import_and_respond(request, form, custom_param, assembly_name, overwrite=False):
    custom_param.save()
    result = run_custom_param_import(custom_param, overwrite=overwrite)
    if not result.ok:
        # Nothing usable was loaded -- drop the stored file so a corrected
        # re-upload under the same name isn't blocked by "already exists".
        custom_param.tsv.delete(save=False)
        custom_param.delete()
        return render(
            request,
            "genomic/customparam.html",
            _page_context(form, assembly_name, import_problems=result.problems),
        )

    columns = ", ".join(result.loaded_columns)
    messages.success(
        request,
        f"Loaded {columns}. Find it under Filters (Custom) and in Make my own score.",
    )
    for problem in result.problems:
        messages.warning(request, problem)
    return redirect(
        reverse("tpwebapp:protein_list", kwargs={"genome": genome_url_slug(assembly_name)})
    )


@login_required
@permission_required("tpweb.can_manage_custom_params", raise_exception=True)
def upload_form(request, genome):
    assembly_name = resolve_genome_from_slug(request.user, genome)
    if not assembly_name:
        raise Http404("Genome not found")
    workspace_user = resolve_workspace_user(request.user)
    if request.method != "POST":
        return render(
            request, "genomic/customparam.html", _page_context(CustomParamForm(), assembly_name)
        )

    form = CustomParamForm(request.POST, request.FILES)
    if not form.is_valid():
        return render(request, "genomic/customparam.html", _page_context(form, assembly_name))

    custom_param = form.save(commit=False)
    custom_param.owner = workspace_user
    custom_param.accession = assembly_name
    existing_params = CustomParam.objects.filter(
        owner=workspace_user,
        accession=assembly_name,
        tsv__endswith=form.cleaned_data["tsv"].name,
    )
    if not existing_params.exists():
        return _import_and_respond(request, form, custom_param, assembly_name)
    if request.POST.get("overwrite") == "true":
        existing_params.delete()
        return _import_and_respond(request, form, custom_param, assembly_name, overwrite=True)
    # File exists but overwrite is not confirmed yet.
    return render(
        request, "genomic/customparam.html", _page_context(form, assembly_name, file_exists=True)
    )
