from django.shortcuts import render
from django.views import View
from django.db.models import Q
from bioseq.models.Biodatabase import Biodatabase
import uuid
import subprocess as sp

class NewView(View):
    template_name = 'blast/result.html'

    def get(self, request, result_id, *args, **kwargs):
        archivito = result_id + '.csv'
        result = open(archivito).read()
        
        # Render the form with context
        return render(request, self.template_name, {
            'result':result
        })