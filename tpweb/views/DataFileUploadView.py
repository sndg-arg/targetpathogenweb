import os

from django.conf import settings
from django.contrib.auth.mixins import LoginRequiredMixin
from django.views import View
from django.shortcuts import render
from django.http import JsonResponse

UPLOADS_DIR = os.path.join(settings.BASE_DIR, "data", "uploads")
CONTAINER_UPLOADS_DIR = "/app/targetpathogenweb/data/uploads"
ALLOWED_EXTENSIONS = {".tsv", ".csv", ".gz", ".tar", ".txt", ".json"}


class DataFileUploadView(LoginRequiredMixin, View):
    template_name = "user/upload_data.html"

    def post(self, request, *args, **kwargs):
        uploaded = request.FILES.get("data_file")
        if not uploaded:
            return JsonResponse({"error": "No file provided."}, status=400)

        _, ext = os.path.splitext(uploaded.name.lower())
        # allow .tar.gz too (last two parts)
        if uploaded.name.lower().endswith(".tar.gz"):
            ext = ".tar.gz"

        if ext not in ALLOWED_EXTENSIONS and not uploaded.name.lower().endswith(".tar.gz"):
            return JsonResponse(
                {"error": f"File type not allowed. Accepted: {', '.join(sorted(ALLOWED_EXTENSIONS))}, .tar.gz"},
                status=400,
            )

        os.makedirs(UPLOADS_DIR, exist_ok=True)
        dest = os.path.join(UPLOADS_DIR, uploaded.name)

        with open(dest, "wb") as f:
            for chunk in uploaded.chunks():
                f.write(chunk)

        container_path = os.path.join(CONTAINER_UPLOADS_DIR, uploaded.name)
        return JsonResponse({"path": container_path, "filename": uploaded.name})
