from django.shortcuts import render, redirect
from django.http import Http404
from django.urls import reverse
import sys
from tpweb.forms.CustomParamForm import CustomParamForm
from tpweb.models import CustomParam
from tpweb.services.workspace import resolve_workspace_user
from tpweb.services.genome_workspace import display_genome_name, genome_url_slug, resolve_genome_from_slug
import subprocess

def index_new_param(custom_param):
    command = [
        sys.executable,
        "./manage.py",
        "load_score_values",
        custom_param.accession,
        custom_param.tsv.path,
        "--datadir",
        "./data",
        "--username",
        custom_param.owner.username,
    ]
    try:
        subprocess.run(command, check=True)
        print("Script executed successfully.")
    except subprocess.CalledProcessError as e:
        print(f"Failed to execute script: {e}")


def upload_form(request, genome):
    assembly_name = resolve_genome_from_slug(request.user, genome)
    if not assembly_name:
        raise Http404("Genome not found")
    workspace_user = resolve_workspace_user(request.user)
    if request.method == 'POST':
        print(f"post {request.POST}")
        #if request.POST.get('overwrite') != 'false':
        form = CustomParamForm(request.POST, request.FILES)
        if form.is_valid():
            custom_param = form.save(commit=False)  # Don't save yet
            custom_param.owner = workspace_user
            custom_param.accession = assembly_name  # Assign the accession value
            existing_params = CustomParam.objects.filter(
                owner=workspace_user,
                accession=assembly_name,
                tsv__endswith=form.cleaned_data['tsv'].name,
            )
            existing_file = existing_params.exists()
            
            # Check if file exists and overwrite flag is set to true
            if existing_file and request.POST.get('overwrite') == 'true':
                # Overwrite is confirmed, proceed with saving
                existing_params.delete()
                custom_param.save()  # Save the model instance
                index_new_param(custom_param)
                return redirect(reverse("tpwebapp:protein_list", kwargs={"genome": genome_url_slug(assembly_name)}))
            elif not existing_file:
                # No existing file, proceed with saving
                custom_param.save()  # Save the model instance
                index_new_param(custom_param)
                return redirect(reverse("tpwebapp:protein_list", kwargs={"genome": genome_url_slug(assembly_name)}))
            else:
                # File exists but overwrite is not confirmed, do not save
                return render(request, 'genomic/customparam.html', {'form': form,
                                                                    'file_exists': True,
                                                                    'assembly_name': assembly_name,
                                                                    'assembly_label': display_genome_name(assembly_name),
                                                                    'genome': genome_url_slug(assembly_name)})
        else:
            context = {'form': form,
                       'assembly_name': assembly_name,
                       'assembly_label': display_genome_name(assembly_name)}
            return render(request, 'genomic/customparam.html', context)
    else:
        print(f"get: {request.POST}")
        form = CustomParamForm()
        context = {'form': form,
                   'assembly_name': assembly_name,
                   'assembly_label': display_genome_name(assembly_name),
                   'genome': genome_url_slug(assembly_name)}
        return render(request, 'genomic/customparam.html', context)
