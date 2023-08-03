from django.shortcuts import render
from django.views import View


class IndexView(View):
    template_name = 'search/index.html'

    def get(self, request, *args, **kwargs):
        #form = self.form_class(initial=self.initial)
        return render(request, self.template_name)#, {'form': form})