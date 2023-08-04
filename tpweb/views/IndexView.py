from django.shortcuts import render
from django.views import View

from tpweb.models.TPPost import TPPost


class IndexView(View):
    template_name = 'search/index.html'

    def get(self, request, *args, **kwargs):
        #form = self.form_class(initial=self.initial)
        post = TPPost.objects.first()
        return render(request, self.template_name,{"post":post})#, {'form': form})