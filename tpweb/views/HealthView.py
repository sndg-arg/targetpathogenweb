from django.db import connections
from django.http import JsonResponse
from django.utils import timezone
from django.views import View

from tpweb.services.pipeline_status import get_pipeline_status


def _database_ready():
    try:
        connections["default"].cursor().execute("SELECT 1")
    except Exception:
        return False
    return True


class HealthLiveView(View):
    def get(self, request, *args, **kwargs):
        return JsonResponse(
            {
                "status": "ok",
                "service": "tpweb",
                "time": timezone.now().isoformat(),
            }
        )


class HealthReadyView(View):
    def get(self, request, *args, **kwargs):
        db_ready = _database_ready()
        pipeline_status = get_pipeline_status()
        status_code = 200 if db_ready else 503

        return JsonResponse(
            {
                "status": "ready" if db_ready else "degraded",
                "checks": {
                    "database": "ok" if db_ready else "error",
                    "pipeline_status_source": (
                        "ok" if pipeline_status.get("available") else "not_available"
                    ),
                },
                "pipeline_running": bool(pipeline_status.get("running")),
                "time": timezone.now().isoformat(),
            },
            status=status_code,
        )


class HealthPipelineView(View):
    def get(self, request, *args, **kwargs):
        pipeline_status = get_pipeline_status()
        return JsonResponse(
            {
                "status": "ok",
                "pipeline": pipeline_status,
                "time": timezone.now().isoformat(),
            }
        )
