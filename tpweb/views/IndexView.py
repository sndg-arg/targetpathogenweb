from django.shortcuts import render
from django.views import View
from django.utils.html import strip_tags

from tpweb.models.TPPost import TPPost
from tpweb.services.genomes import build_genomes_dto, build_genomes_queryset, summarize_genomes
from tpweb.services.pipeline_status import get_pipeline_status


class IndexView(View):
    template_name = "index.html"

    def get(self, request, *args, **kwargs):
        post = TPPost.objects.first()
        genomes = build_genomes_queryset()
        genome_metrics = summarize_genomes(build_genomes_dto(genomes))

        has_project_notes = False
        if post and post.content:
            has_project_notes = bool(strip_tags(post.content).strip())

        context = {
            "post": post,
            "has_project_notes": has_project_notes,
            "total_genomes": genome_metrics["total_genomes"],
            "total_proteins": genome_metrics["total_proteins"],
            "total_structures": genome_metrics.get(
                "total_structures", genome_metrics.get("genomes_with_structures", 0)
            ),
            "pipeline_status": get_pipeline_status(),
        }
        return render(request, self.template_name, context)
