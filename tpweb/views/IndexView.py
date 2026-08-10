from datetime import datetime, timedelta, timezone as datetime_timezone

from django.shortcuts import render
from django.views import View
from django.utils import timezone as django_timezone
from django.utils.html import strip_tags

from tpweb.models.TPPost import TPPost
from tpweb.services.genomes import build_genomes_dto, build_genomes_queryset, summarize_genomes
from tpweb.services.pipeline_status import (
    get_pipeline_status,
    sanitize_pipeline_status_for_user,
    STAGE_LABELS,
)

PIPELINE_HOME_RECENT_WINDOW = timedelta(days=1)
PIPELINE_STATUS_DISPLAY_TZ = datetime_timezone(timedelta(hours=-3))
PIPELINE_STATUS_DISPLAY_FORMAT = "%Y-%m-%d %H:%M (UTC-3)"


def _parse_pipeline_home_timestamp(value):
    if not value:
        return None
    value = str(value).strip()
    try:
        return datetime.strptime(value, PIPELINE_STATUS_DISPLAY_FORMAT).replace(
            tzinfo=PIPELINE_STATUS_DISPLAY_TZ
        )
    except (TypeError, ValueError):
        pass
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=datetime_timezone.utc)
    return parsed


def should_show_home_pipeline_panel(pipeline_status, now=None):
    status = dict(pipeline_status or {})
    if status.get("running") or status.get("running_for_other_workspace"):
        return True
    if not status.get("available"):
        return False

    last_updated = _parse_pipeline_home_timestamp(status.get("last_updated"))
    if last_updated is None:
        return False

    now = now or django_timezone.now()
    if now.tzinfo is None:
        now = now.replace(tzinfo=datetime_timezone.utc)
    return now - last_updated <= PIPELINE_HOME_RECENT_WINDOW


class IndexView(View):
    template_name = "index.html"

    def get(self, request, *args, **kwargs):
        post = TPPost.objects.first()
        genomes = build_genomes_queryset(user=request.user)
        genomes_dto = build_genomes_dto(genomes, user=request.user)
        genome_metrics = summarize_genomes(genomes_dto)
        featured_genomes = sorted(
            genomes_dto,
            key=lambda genome: (
                -int(genome.get("COUNT_CDS") or 0),
                str(genome.get("name") or ""),
            ),
        )[:4]

        has_project_notes = False
        if post and post.content:
            has_project_notes = bool(strip_tags(post.content).strip())

        pipeline_stages = [
            {"number": num, "label": label} for num, label in sorted(STAGE_LABELS.items())
        ]

        pipeline_status = sanitize_pipeline_status_for_user(get_pipeline_status(), request.user)

        context = {
            "post": post,
            "has_project_notes": has_project_notes,
            "total_genomes": genome_metrics["total_genomes"],
            "total_proteins": genome_metrics["total_proteins"],
            "featured_genomes": featured_genomes,
            "pipeline_status": pipeline_status,
            "show_pipeline_panel": should_show_home_pipeline_panel(pipeline_status),
            "pipeline_stages": pipeline_stages,
        }
        return render(request, self.template_name, context)
