import uuid
from pathlib import Path

from django.conf import settings
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import Http404
from django.shortcuts import render
from django.urls import reverse
from django.views import View

from bioseq.models.Biodatabase import Biodatabase
from bioseq.models.Bioentry import Bioentry
from tpweb.services.genome_workspace import display_genome_name, resolve_genome_from_slug

# blastn runs with -outfmt 6: the 12 standard tabular columns.
_OUTFMT6_FIELDS = (
    "query",
    "subject_id",
    "identity",
    "length",
    "mismatch",
    "gapopen",
    "qstart",
    "qend",
    "sstart",
    "send",
    "evalue",
    "bitscore",
)


def parse_blast_tabular(raw):
    hits = []
    for line in (raw or "").splitlines():
        fields = line.split("\t")
        if len(fields) < len(_OUTFMT6_FIELDS):
            continue
        hits.append(dict(zip(_OUTFMT6_FIELDS, fields[: len(_OUTFMT6_FIELDS)], strict=True)))
    return hits


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
        hits = parse_blast_tabular(result)

        # ?genome= (set by FormView's redirect) lets each hit link to its
        # protein and "Run another search" keep the same genome selected.
        genome_slug = (request.GET.get("genome") or "").strip()
        genome_name = resolve_genome_from_slug(request.user, genome_slug) if genome_slug else None
        if genome_name:
            subject_ids = {hit["subject_id"] for hit in hits}
            proteins_by_accession = {
                protein.accession: protein
                for protein in Bioentry.objects.filter(
                    biodatabase__name=genome_name + Biodatabase.PROT_POSTFIX,
                    accession__in=subject_ids,
                )
            }
            for hit in hits:
                hit["protein"] = proteins_by_accession.get(hit["subject_id"])

        # Keep the genome for the next search: still locked to it when the
        # search came from a genome page, otherwise just preselected.
        new_search_url = reverse("tpwebapp:form")
        if genome_name:
            param = "genome" if request.GET.get("locked") else "select"
            new_search_url += f"?{param}={genome_slug}"
        return render(
            request,
            self.template_name,
            {
                "result": result,
                "hits": hits,
                "genome_label": display_genome_name(genome_name) if genome_name else "",
                "new_search_url": new_search_url,
            },
        )
