from django.shortcuts import render
from django.views import View
from django.utils.html import strip_tags

from tpweb.models.TPPost import TPPost
from tpweb.services.genomes import build_genomes_dto, build_genomes_queryset, summarize_genomes
from tpweb.services.pipeline_status import get_pipeline_status, sanitize_pipeline_status_for_user, STAGE_LABELS


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
            {"number": num, "label": label}
            for num, label in sorted(STAGE_LABELS.items())
        ]

        context = {
            "post": post,
            "has_project_notes": has_project_notes,
            "total_genomes": genome_metrics["total_genomes"],
            "total_proteins": genome_metrics["total_proteins"],
            "featured_genomes": featured_genomes,
            "pipeline_status": sanitize_pipeline_status_for_user(
                get_pipeline_status(), request.user
            ),
            "pipeline_stages": pipeline_stages,
        }
        return render(request, self.template_name, context)
