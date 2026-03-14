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
        # Set the location of the HTML template
        self.template_name = 'blast/form.html'  
        # Define db_options to fill the dropdown
        biodatabases = Biodatabase.objects.all()
        self.db_options = [{'value': bd.biodatabase_id, 'label': bd.name} for bd in biodatabases if not bd.name.endswith(('_prots', '_rnas'))]

    def get(self, request, *args, **kwargs):
        # Render the form with context
        return render(request, self.template_name, {
            'db_options': self.db_options,
        })
    
    def post(self, request, *args, **kwargs):
        if request.method == 'POST':
            # Save the provided inputs in vars
            selected_item = request.POST.get('dropdown')
            text_input = request.POST.get('text_input')

            # Check if text_input is empty
            if not text_input:
                return render(request, self.template_name, {
                    'error_message': 'Please provide a valid query. The query is empty!',
                    'db_options': self.db_options,
                })

            # Based on selected_item, you can access the corresponding Biodatabase object
            selected_biodatabase = Biodatabase.objects.get(pk=selected_item)

            # Define the db location and the uuid name to store the results.
            uuid_1 = uuid.uuid1()
            db_location = SeqStore('./data').genes_fna(selected_biodatabase.name)
            query_path = f"{uuid_1}.fna"
            output_path = f"{uuid_1}.csv"
            blast_bin = "./opt/ncbi-blast-2.15.0+-x64-linux/ncbi-blast-2.15.0+/bin/blastn"

            try:
                with open(query_path, "w", encoding="utf-8") as file:
                    file.write(text_input)

                cmd = [
                    blast_bin,
                    "-query", query_path,
                    "-db", db_location,
                    "-evalue", "1e-6",
                    "-num_threads", "4",
                    "-out", output_path,
                    "-outfmt", "6",
                ]
                sp.check_output(cmd, stderr=sp.STDOUT)
            except sp.CalledProcessError as exc:
                details = exc.output.decode("utf-8", errors="replace") if exc.output else str(exc)
                return render(request, self.template_name, {
                    'error_message': f'BLAST query failed. {details}',
                    'db_options': self.db_options,
                })
            finally:
                if os.path.exists(query_path):
                    os.remove(query_path)

            # Render the page with the messages and passing the uuid as result_id
            return render(request, self.template_name, {
                'message': f"You selected item {selected_biodatabase.name} {selected_biodatabase.description} and entered text: '{text_input}'. y el UUID es '{uuid_1}'",
                'result_id': uuid_1,
                'db_options': self.db_options,
            })
      
        else:
            return render(request, self.template_name, {})
