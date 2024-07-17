from django.shortcuts import render, redirect
from tpweb.forms.CustomParamForm import CustomParamForm
from tpweb.models import CustomParam 


def upload_form(request, assembly_name):
    if request.method == 'POST':
        form = CustomParamForm(request.POST, request.FILES)
        if form.is_valid():
            custom_param = form.save(commit=False)  # Don't save yet
            custom_param.accession = assembly_name  # Assign the accession value
            custom_param.save()  # Now save the model instance
            return redirect(f'../../assembly/{assembly_name}/protein')
        else:
            context = {'form': form}
            return render(request, 'genomic/customparam.html', context)
    else:
        form = CustomParamForm()
        context = {'form': form}
        return render(request, 'genomic/customparam.html', context)

