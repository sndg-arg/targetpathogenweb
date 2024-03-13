from django.shortcuts import render
from django.views import View
from django.http import HttpResponseRedirect
from bioseq.models.Biodatabase import Biodatabase
from django.core.exceptions import ObjectDoesNotExist
import uuid
import subprocess as sp
import os
import re
from bioseq.io.SeqStore import SeqStore

class FormView(View):
    template_name = 'blast/form.html'

    def get_context_data(self, **kwargs):
        biodatabases = Biodatabase.objects.all()
        db_options = [
            {'value': bd.biodatabase_id, 'label': f"{bd.name} - {bd.description}"}
            for bd in biodatabases if not bd.name.endswith(('_prots', '_rnas'))
        ]
        context = {
            'db_options': db_options,
        }
        if 'error_message' in kwargs:
            context['error_message'] = kwargs['error_message']
        if 'message' in kwargs:
            context['message'] = kwargs['message']
        if 'result_id' in kwargs:
            context['result_id'] = kwargs['result_id']
        return context

    def get(self, request, *args, **kwargs):
        context = self.get_context_data()
        return render(request, self.template_name, context)
    
    def post(self, request, *args, **kwargs):
        selected_item = request.POST.get('dropdown')
        text_input = request.POST.get('text_input').upper().strip()  # Convertimos a mayúsculas y quitamos espacios

        # Verificamos que la secuencia solo contenga los caracteres ACGT
        if not re.fullmatch(r'^[ACGT]+$', text_input.replace(" ", "")):  # Eliminamos los espacios para la validación
            error_message = 'Invalid sequence. Please enter a sequence using only ACGT characters.'
            context = self.get_context_data(error_message=error_message)
            return render(request, self.template_name, context)

        if not text_input:
            error_message = 'Please provide a valid query. The query is empty!'
            context = self.get_context_data(error_message=error_message)
            return render(request, self.template_name, context)

        with open('sequence.fna', 'w') as file:
            file.write(text_input)

        try:
            selected_biodatabase = Biodatabase.objects.get(pk=selected_item)
        except ObjectDoesNotExist:
            error_message = 'The selected genome does not exist in the database.'
            context = self.get_context_data(error_message=error_message)
            return render(request, self.template_name, context)
        uuid_1 = uuid.uuid1()
        db_location = SeqStore('./data').genes_fna(selected_biodatabase.name)

        cmd = f'blastn -query ./sequence.fna -db {db_location} -evalue 1e-6 -num_threads 4 -out {uuid_1}.csv -outfmt 6'
        sp.check_output(cmd, shell=True)

        os.remove('sequence.fna')

        message = f"You selected item {selected_biodatabase.name} {selected_biodatabase.description} and entered text: '{text_input}'. y el UUID es '{uuid_1}'"
        context = self.get_context_data(message=message, result_id=uuid_1, result_ready=True)

        # Check if the result should open in a new tab
        if 'newTabCheck' in request.POST:
            response = HttpResponseRedirect(f"{request.path}?result_id={uuid_1}")
            response['Target'] = '_blank'
            return response

        return render(request, self.template_name, context)
