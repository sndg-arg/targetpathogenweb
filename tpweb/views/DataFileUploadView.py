import os

from django.views import View
from django.http import JsonResponse

UPLOADS_DIR = "/tmp/tpw_uploads"
ALLOWED_EXTENSIONS = {".tsv", ".csv", ".gz", ".tar", ".txt", ".json"}


class DataFileUploadView(View):

    def post(self, request, *args, **kwargs):
        uploaded = request.FILES.get("data_file")
        if not uploaded:
            return JsonResponse({"error": "No file provided."}, status=400)

        if not (uploaded.name.lower().endswith(".tar.gz") or
                os.path.splitext(uploaded.name.lower())[1] in ALLOWED_EXTENSIONS):
            return JsonResponse(
                {"error": f"File type not allowed. Accepted: .tsv, .csv, .tar.gz, .json, .txt"},
                status=400,
            )

        os.makedirs(UPLOADS_DIR, exist_ok=True)
        dest = os.path.join(UPLOADS_DIR, uploaded.name)

        with open(dest, "wb") as f:
            for chunk in uploaded.chunks():
                f.write(chunk)

        return JsonResponse({"path": dest, "filename": uploaded.name})
