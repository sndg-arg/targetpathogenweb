from django.shortcuts import render, redirect
from tpweb.forms.CustomParamForm import CustomParamForm
from tpweb.models import CustomParam 
import subprocess

def index_new_param(custom_param):
    # Construct the command string
    command = f"python ./manage.py load_score_values {custom_param.accession} ./data/{custom_param.tsv} --datadir ./data"
    # Execute the command
    try:
        subprocess.run(command, shell=True, check=True)
        print("Script executed successfully.")
    except subprocess.CalledProcessError as e:
        print(f"Failed to execute script: {e}")


def upload_form(request, assembly_name):
    if request.method == 'POST':
        print(f"post {request.POST}")
        #if request.POST.get('overwrite') != 'false':
        form = CustomParamForm(request.POST, request.FILES)
        if form.is_valid():
            custom_param = form.save(commit=False)  # Don't save yet
            custom_param.accession = assembly_name  # Assign the accession value
            existing_file = CustomParam.objects.filter(accession=assembly_name, tsv__endswith=form.cleaned_data['tsv'].name).exists()
            
            # Check if file exists and overwrite flag is set to true
            if existing_file and request.POST.get('overwrite') == 'true':
                # Overwrite is confirmed, proceed with saving
                CustomParam.objects.filter(accession=assembly_name, tsv__endswith=form.cleaned_data['tsv'].name).delete()
                custom_param.save()  # Save the model instance
                index_new_param(custom_param)
                return redirect(f'../../assembly/{assembly_name}/protein')
            elif not existing_file:
                # No existing file, proceed with saving
                custom_param.save()  # Save the model instance
                index_new_param(custom_param)
                return redirect(f'../../assembly/{assembly_name}/protein')
            else:
                # File exists but overwrite is not confirmed, do not save
                return render(request, 'genomic/customparam.html', {'form': form, 'file_exists': True})
        else:
            context = {'form': form}
            return render(request, 'genomic/customparam.html', context)
    else:
        
        print(f"get: {request.POST}")
        form = CustomParamForm()
        context = {'form': form}
        return render(request, 'genomic/customparam.html', context)
