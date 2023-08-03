from django.views import View


class ProteinListView(View):
    def get(self, request, *args, **kwargs):
        return None