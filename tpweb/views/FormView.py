from django.shortcuts import render
from django.views import View
from django.db.models import Q
from bioseq.models.Biodatabase import Biodatabase



class FormView(View):
    template_name = 'blast/form.html'

    def get(self, request, *args, **kwargs):

        return render(request, self.template_name)
    
    def post(self, request, *args, **kwargs):
        if request.method == 'POST':
            selected_item = request.POST.get('dropdown')
            text_input = request.POST.get('text_input')
        # Process form data here (e.g., validate, save to database, etc.)
            return render(request, self.template_name, {
            'message': f"You selected item {selected_item} and entered text: '{text_input}'.",
})
        else:
            return render(request, 'form_template.html', {})
