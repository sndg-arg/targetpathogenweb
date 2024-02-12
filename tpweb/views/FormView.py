from django.shortcuts import render
from django.views import View
from django.db.models import Q
from bioseq.models.Biodatabase import Biodatabase



class FormView(View):
    template_name = 'blast/form.html'

    def get(self, request, *args, **kwargs):

        return render(request, self.template_name)
