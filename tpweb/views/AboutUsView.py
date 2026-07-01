from django.shortcuts import render
from django.views import View


class AboutUsView(View):
    template_name = "about/about_us.html"

    def get(self, request, *args, **kwargs):
        return render(request, self.template_name)