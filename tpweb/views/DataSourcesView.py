from django.shortcuts import render
from django.views import View


class DataSourcesView(View):
    template_name = "about/data_sources.html"

    def get(self, request, *args, **kwargs):
        return render(request, self.template_name)
