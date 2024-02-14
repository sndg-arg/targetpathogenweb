from django.shortcuts import render
from django.views import View
from django.db.models import Q
from bioseq.models.Biodatabase import Biodatabase



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

            return render(request, self.template_name, {
                'message': f"You selected item {selected_biodatabase.name} {selected_biodatabase.description} and entered text: '{text_input}'.",
            })
        else:
            return render(request, self.template_name, {})