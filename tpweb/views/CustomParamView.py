import logging

from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.shortcuts import render, redirect
from django.http import Http404, HttpResponse
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
    built_in_name_conflicts,
    column_values,
    genome_columns,
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

    column_names = uploaded_column_names(form.cleaned_data["tsv"])
    problems = []
    built_in = built_in_name_conflicts(column_names)
    if built_in:
        problems.append(
            "These names belong to built-in Target columns: "
            + ", ".join(built_in)
            + ". Rename them in your file so they don't overwrite the platform's data."
        )
    if form.cleaned_data["visibility"] != VISIBILITY_PRIVATE:
        taken = name_conflicts(workspace_user, assembly_name, column_names)
        if taken:
            problems.append(
                "Someone else already shares a column with this name on this genome: "
                + ", ".join(taken)
                + ". Rename the column in your file, or keep it private."
            )
    if problems:
        return render(
            request,
            "genomic/customparam.html",
            _page_context(form, assembly_name, import_problems=problems),
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


@login_required
def uploaded_data(request, genome):
    """Every uploaded column the user can see on this genome -- who loaded it,
    what it measures, how many proteins have a value -- with a TSV download."""
    assembly_name = resolve_genome_from_slug(request.user, genome)
    if not assembly_name:
        raise Http404("Genome not found")
    return render(
        request,
        "genomic/uploaded_data.html",
        {
            "assembly_name": assembly_name,
            "assembly_label": display_genome_name(assembly_name),
            "genome": genome_url_slug(assembly_name),
            "columns": genome_columns(request.user, assembly_name),
            "can_upload": request.user.has_perm("tpweb.can_manage_custom_params"),
        },
    )


@login_required
def uploaded_data_download(request, genome, param_id):
    assembly_name = resolve_genome_from_slug(request.user, genome)
    if not assembly_name:
        raise Http404("Genome not found")
    param, values = column_values(request.user, assembly_name, param_id)
    if param is None:
        raise Http404("Column not found")
    rows = [f"gene\t{param.name}"] + [f"{accession}\t{value}" for accession, value in values]
    response = HttpResponse("\n".join(rows) + "\n", content_type="text/tab-separated-values")
    filename = f"{genome_url_slug(assembly_name)}_{param.name}.tsv".replace("/", "_")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response
