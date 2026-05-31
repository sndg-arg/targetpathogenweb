import os

from django.conf import settings
from django.http import JsonResponse
from django.utils.text import get_valid_filename
from django.views import View

ALLOWED_EXTENSIONS = {".tsv", ".csv", ".gz", ".tar", ".txt", ".json"}


def _uploads_dir():
    explicit_dir = os.environ.get("TPW_UPLOADS_DIR", "").strip()
    if explicit_dir:
        return explicit_dir
    data_dir = getattr(settings, "SEQS_DATA_DIR", None) or os.path.join(settings.BASE_DIR, "data")
    return os.path.join(str(data_dir), "uploads")


class DataFileUploadView(View):

    def post(self, request, *args, **kwargs):
        if not request.user.is_staff:
            return JsonResponse({"error": "Staff access required."}, status=403)

        uploaded = request.FILES.get("data_file")
        if not uploaded:
            return JsonResponse({"error": "No file provided."}, status=400)

        if not (uploaded.name.lower().endswith(".tar.gz") or
                os.path.splitext(uploaded.name.lower())[1] in ALLOWED_EXTENSIONS):
            return JsonResponse(
                {"error": f"File type not allowed. Accepted: .tsv, .csv, .tar.gz, .json, .txt"},
                status=400,
            )

        uploads_dir = _uploads_dir()
        os.makedirs(uploads_dir, exist_ok=True)
        dest = os.path.join(uploads_dir, get_valid_filename(os.path.basename(uploaded.name)))

        with open(dest, "wb") as f:
            for chunk in uploaded.chunks():
                f.write(chunk)

        return JsonResponse({"path": dest, "filename": uploaded.name})
