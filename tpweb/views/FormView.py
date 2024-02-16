from django.shortcuts import render
from django.views import View
from django.db.models import Q
from bioseq.models.Biodatabase import Biodatabase
import uuid
import subprocess as sp
import os
from bioseq.io.SeqStore import SeqStore

class FormView(View):
    
    def __init__(self):
        self.template_name = 'blast/form.html'  
        biodatabases = Biodatabase.objects.all()
        self.db_options = [{'value': bd.biodatabase_id, 'label': bd.name} for bd in biodatabases if not bd.name.endswith(('_prots', '_rnas'))]

    def get(self, request, *args, **kwargs):
        # Render the form with context
        return render(request, self.template_name, {
            'db_options': self.db_options,
        })
    
    def post(self, request, *args, **kwargs):
        if request.method == 'POST':
            selected_item = request.POST.get('dropdown')
            text_input = request.POST.get('text_input')

            # Check if text_input is empty
            if not text_input:
                return render(request, self.template_name, {
                    'error_message': 'Please provide a valid query. The query is empty!',
                    'db_options': self.db_options,
                })

            # Write the content of text_input to a file named sequence.faa
            with open('sequence.fna', 'w') as file:
                file.write(text_input)
        
            # Based on selected_item, you can access the corresponding Biodatabase object
            selected_biodatabase = Biodatabase.objects.get(pk=selected_item)
            # ... perform actions using selected_biodatabase and text_input
            uuid_1 = uuid.uuid1()
            # Warning hardcode next

            db_location = SeqStore('./data').genes_fna(selected_biodatabase.name)

            cmd = f'./opt/ncbi-blast-2.15.0+-x64-linux/ncbi-blast-2.15.0+/bin/blastn -query ./sequence.fna -db {db_location} -evalue 1e-6 -num_threads 4 -out {uuid_1}.csv -outfmt 6'
            sp.check_output(cmd , shell = True)
            
            os.remove('sequence.fna')


            return render(request, self.template_name, {
                'message': f"You selected item {selected_biodatabase.name} {selected_biodatabase.description} and entered text: '{text_input}'. y el UUID es '{uuid_1}'",
                'result_id': uuid_1,
                'db_options': self.db_options,
            })


            
        else:
            return render(request, self.template_name, {})