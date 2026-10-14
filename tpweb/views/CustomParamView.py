import logging

from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.shortcuts import render, redirect
from django.http import Http404
from django.urls import reverse
from bioseq.models.Biodatabase import Biodatabase
from bioseq.models.Bioentry import Bioentry
from tpweb.forms.CustomParamForm import CustomParamForm
from tpweb.models import CustomParam
from tpweb.services.custom_param_import import run_custom_param_import
from tpweb.services.custom_param_sharing import (
    VISIBILITY_PRIVATE,
    VISIBILITY_PROJECT,
    VISIBILITY_PUBLIC,
    apply_upload_sharing,
    name_conflicts,
    uploaded_column_names,
    visibility_choices,
)
from tpweb.services.workspace import resolve_workspace_user
from tpweb.services.genome_workspace import (
    display_genome_name,
    genome_url_slug,
    resolve_genome_from_slug,
)

logger = logging.getLogger(__name__)

SHARED_NOTES = {
    VISIBILITY_PROJECT: " Project members can add it from Columns.",
    VISIBILITY_PUBLIC: " Others who can see this genome can add it from Columns.",
}


def _example_accessions(assembly_name, count=3):
    """Real accessions from this genome for the format example, so students
    copy the right identifier shape (e.g. a locus tag) instead of a made-up
    UniProt-looking one."""
    accessions = list(
        Bioentry.objects.filter(biodatabase__name=assembly_name + Biodatabase.PROT_POSTFIX)
        .order_by("accession")
        .values_list("accession", flat=True)[:count]
    )
    return accessions or ["A0A0000001", "A0A0000002", "A0A0000003"]


def _page_context(form, assembly_name, **extra):
    return {
        "form": form,
        "assembly_name": assembly_name,
        "assembly_label": display_genome_name(assembly_name),
        "genome": genome_url_slug(assembly_name),
        "example_accessions": _example_accessions(assembly_name),
        **extra,
    }


def _import_and_respond(request, form, custom_param, assembly_name, overwrite=False):
    try:
        custom_param.save()
    except OSError:
        logger.exception("Could not store custom evidence file for %s", assembly_name)
        return render(
            request,
            "genomic/customparam.html",
            _page_context(
                form,
                assembly_name,
                import_problems=[
                    "The server could not save the file. This is a server problem, "
                    "not a problem with your file — please contact the administrators."
                ],
            ),
        )
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

    visibility = form.cleaned_data.get("visibility") or VISIBILITY_PRIVATE
    apply_upload_sharing(
        custom_param.owner,
        assembly_name,
        result.loaded_columns,
        visibility,
        form.cleaned_data.get("description", ""),
    )
    columns = ", ".join(result.loaded_columns)
    shared_note = SHARED_NOTES.get(visibility, "")
    messages.success(
        request,
        f"Loaded {columns}. Find it under Filters (Custom) and in Make my own score." + shared_note,
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
    choices = visibility_choices(assembly_name)
    if request.method != "POST":
        return render(
            request,
            "genomic/customparam.html",
            _page_context(CustomParamForm(visibility_choices=choices), assembly_name),
        )

    form = CustomParamForm(request.POST, request.FILES, visibility_choices=choices)
    if not form.is_valid():
        return render(request, "genomic/customparam.html", _page_context(form, assembly_name))

    if form.cleaned_data["visibility"] != VISIBILITY_PRIVATE:
        taken = name_conflicts(
            workspace_user, assembly_name, uploaded_column_names(form.cleaned_data["tsv"])
        )
        if taken:
            problem = (
                "Someone else already shares a column with this name on this genome: "
                + ", ".join(taken)
                + ". Rename the column in your file, or keep it private."
            )
            return render(
                request,
                "genomic/customparam.html",
                _page_context(form, assembly_name, import_problems=[problem]),
            )

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
