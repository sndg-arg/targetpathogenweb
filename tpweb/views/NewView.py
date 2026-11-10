import uuid
from urllib.parse import urlencode

from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import Http404
from django.shortcuts import render
from django.urls import reverse
from django.views import View

from tpweb.services.blast_files import blast_results_dir
from tpweb.services.blast_search import annotate_blast_hits
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
        hit = dict(zip(_OUTFMT6_FIELDS, fields[: len(_OUTFMT6_FIELDS)], strict=True))
        # run_blast appends the genome each row came from.
        hit["genome"] = fields[len(_OUTFMT6_FIELDS)] if len(fields) > len(_OUTFMT6_FIELDS) else ""
        hits.append(hit)
    return hits


class NewView(LoginRequiredMixin, View):
    template_name = "blast/result.html"

    def get(self, request, result_id, *args, **kwargs):
        try:
            parsed_id = uuid.UUID(str(result_id))
        except (TypeError, ValueError) as exc:
            raise Http404("BLAST result not found") from exc

        try:
            result_path = blast_results_dir() / f"{parsed_id}.csv"
        except OSError as exc:
            raise Http404("BLAST result not found") from exc
        if not result_path.is_file():
            raise Http404("BLAST result not found")

        result = result_path.read_text(encoding="utf-8", errors="replace")
        hits = parse_blast_tabular(result)

        # ?genome= (one per genome searched, set by FormView's redirect) lets
        # each hit link to its protein and "Run another search" keep the same
        # genomes selected. Resolving them is also the access check.
        genomes = {}
        for slug in request.GET.getlist("genome"):
            slug = slug.strip()
            name = resolve_genome_from_slug(request.user, slug) if slug else None
            if name:
                genomes[name] = slug
        if len(genomes) == 1:
            # Results saved before rows carried their genome.
            only = next(iter(genomes))
            for hit in hits:
                hit["genome"] = hit["genome"] or only
        annotate_blast_hits(hits, list(genomes))

        # Keep the genomes for the next search: still locked to it when the
        # search came from a genome page, otherwise just preselected.
        new_search_url = reverse("tpwebapp:form")
        if genomes:
            param = "genome" if request.GET.get("locked") and len(genomes) == 1 else "select"
            new_search_url += "?" + urlencode([(param, slug) for slug in genomes.values()])
        return render(
            request,
            self.template_name,
            {
                "result": result,
                "hits": hits,
                "genome_label": display_genome_name(next(iter(genomes)))
                if len(genomes) == 1
                else "",
                "genome_count": len(genomes),
                "new_search_url": new_search_url,
            },
        )
