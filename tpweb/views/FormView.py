from django.shortcuts import render
from django.views import View
from django.db.models import Q
from bioseq.models.Biodatabase import Biodatabase
import uuid
import subprocess as sp

class FormView(View):
    template_name = 'blast/form.html'

    def get(self, request, *args, **kwargs):
        biodatabases = Biodatabase.objects.all()
        options = [{'value': bd.biodatabase_id, 'label': bd.name} for bd in biodatabases]

        # Render the form with context
        return render(request, self.template_name, {
            'options': options,
        })
    
    def post(self, request, *args, **kwargs):
        if request.method == 'POST':
            selected_item = request.POST.get('dropdown')
            text_input = request.POST.get('text_input')
        
            # Based on selected_item, you can access the corresponding Biodatabase object
            selected_biodatabase = Biodatabase.objects.get(pk=selected_item)
            # ... perform actions using selected_biodatabase and text_input
            uuid_1 = uuid.uuid1()
            # Warning hardcode next
            cmd = f'./opt/ncbi-blast-2.15.0+-x64-linux/ncbi-blast-2.15.0+/bin/blastn -query ./opt/ncbi-blast-2.15.0+-x64-linux/ncbi-blast-2.15.0+/sequence1.fna -db ./data/025/NC_002516.2/NC_002516.2.genes.fna.gz -evalue 1e-6 -num_threads 4 -out {uuid_1}.csv -outfmt 6'
            sp.check_output(cmd , shell = True)
            return render(request, self.template_name, {
                'message': f"You selected item {selected_biodatabase.name} {selected_biodatabase.description} and entered text: '{text_input}'. y el UUID es '{uuid_1}'",
                'result_id': uuid_1,
            })
        else:
            return render(request, self.template_name, {})