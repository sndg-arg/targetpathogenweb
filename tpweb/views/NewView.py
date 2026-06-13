import uuid
from pathlib import Path

from django.conf import settings
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import Http404
from django.shortcuts import render
from django.views import View


class NewView(LoginRequiredMixin, View):
    template_name = "blast/result.html"

    def get(self, request, result_id, *args, **kwargs):
        try:
            parsed_id = uuid.UUID(str(result_id))
        except (TypeError, ValueError) as exc:
            raise Http404("BLAST result not found") from exc

        result_path = Path(settings.MEDIA_ROOT) / "blast_results" / f"{parsed_id}.csv"
        if not result_path.is_file():
            raise Http404("BLAST result not found")

        result = result_path.read_text(encoding="utf-8", errors="replace")
        return render(request, self.template_name, {"result": result})
