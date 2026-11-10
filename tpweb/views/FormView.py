import logging
import os
import uuid
from urllib.parse import urlencode

from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views import View

from bioseq.models.Biodatabase import Biodatabase
from tpweb.services.blast_files import blast_results_dir
from tpweb.services.blast_search import (
    BlastError,
    annotate_blast_hits,
    max_genomes_per_search,
    run_blast,
)
from tpweb.services.genome_workspace import (
    display_genome_name,
    genome_url_slug,
    resolve_genome_from_slug,
)
from tpweb.services.genomes import build_genomes_queryset
from tpweb.views.ProteinBlastView import ProteinBlastView, parse_blastp_rows

logger = logging.getLogger(__name__)


class FormView(LoginRequiredMixin, View):
    template_name = "blast/form.html"

    def _db_options(self, request):
        return [
            {
                "value": bd.biodatabase_id,
                "label": display_genome_name(bd.name),
                "internal_name": bd.name,
            }
            for bd in build_genomes_queryset(user=request.user).order_by("name")
        ]

    def _build_context(self, request, locked_biodatabase=None, selected_ids=(), **extra):
        selected_genome_name = locked_biodatabase.name if locked_biodatabase else ""
        context = {
            "db_options": self._db_options(request),
            "selected_db_values": {str(value) for value in selected_ids},
            "max_genomes": max_genomes_per_search(),
            "selected_genome_name": selected_genome_name,
            "selected_genome_label": display_genome_name(selected_genome_name)
            if selected_genome_name
            else "",
            "selected_genome_description": locked_biodatabase.description
            if locked_biodatabase
            else "",
            "blast_locked_to_genome": bool(locked_biodatabase),
            "selected_genome_workspace_url": (
                reverse(
                    "tpwebapp:assembly",
                    kwargs={"genome": genome_url_slug(locked_biodatabase.name)},
                )
                if locked_biodatabase
                else ""
            ),
        }
        context.update(extra)
        return context

    def _locked_biodatabase(self, request):
        """?genome= / genome_name: the page was opened from a genome and only
        searches that one."""
        genome_name = str(
            request.GET.get("genome") or request.POST.get("genome_name") or ""
        ).strip()
        if not genome_name:
            return None
        resolved = resolve_genome_from_slug(request.user, genome_name)
        if not resolved:
            return None
        return Biodatabase.objects.filter(name=resolved).first()

    def get(self, request, *args, **kwargs):
        locked = self._locked_biodatabase(request)
        context = self._build_context(request, locked)
        # ?select=<genome> (from "Run another search", once per genome)
        # preselects genomes in the picker without locking the page to them.
        if not locked:
            preselected = {
                resolve_genome_from_slug(request.user, slug.strip())
                for slug in request.GET.getlist("select")
                if slug.strip()
            }
            context["selected_db_values"] = {
                str(option["value"])
                for option in context["db_options"]
                if option["internal_name"] in preselected
            }
        return render(request, self.template_name, context)

    def post(self, request, *args, **kwargs):
        locked = self._locked_biodatabase(request)
        text_input = (request.POST.get("text_input") or "").strip()
        blast_type = "protein" if request.POST.get("blast_type") == "protein" else "nucleotide"
        if locked:
            genomes = [locked]
        else:
            ids = [value for value in request.POST.getlist("genomes") if value.strip().isdigit()]
            genomes = (
                list(build_genomes_queryset(user=request.user).filter(pk__in=ids).order_by("name"))
                if ids
                else []
            )

        def form_error(message, sequence=text_input):
            return render(
                request,
                self.template_name,
                self._build_context(
                    request,
                    locked,
                    [genome.biodatabase_id for genome in genomes],
                    error_message=message,
                    text_input_value=sequence,
                    blast_type=blast_type,
                ),
            )

        if not request.user.has_perm("tpweb.can_run_blast"):
            return form_error("You don't have permission to run BLAST searches.")
        if not genomes:
            return form_error("Please select at least one genome before running BLAST.")
        max_genomes = max_genomes_per_search()
        if len(genomes) > max_genomes:
            return form_error(f"Select up to {max_genomes} genomes per search.")

        max_chars = int(os.environ.get("TPW_BLAST_MAX_QUERY_CHARS", "20000"))
        if not text_input:
            return form_error("Please provide a valid query. The query is empty!")
        if len(text_input) > max_chars:
            return form_error(
                f"BLAST query is too large. Limit: {max_chars} characters.",
                text_input[:max_chars],
            )

        genome_names = [genome.name for genome in genomes]
        try:
            result_dir = blast_results_dir()
        except OSError:
            logger.exception("BLAST setup failed for %s", genome_names)
            return form_error("BLAST is unavailable right now. Please try again later.")

        query_text = text_input
        if blast_type == "protein" and not text_input.startswith(">"):
            query_text = f">query_1\n{text_input}"
        try:
            rows = run_blast(blast_type, query_text, genome_names, result_dir)
        except BlastError as exc:
            return form_error(str(exc))

        genome_slugs = [genome_url_slug(name) for name in genome_names]
        if blast_type == "protein":
            # Single genome: the genome's own blastp result page, as before.
            if len(genomes) == 1:
                context = ProteinBlastView()._base_context(genome_names[0], genome_slugs[0])
            else:
                context = {
                    "genome_labels": [display_genome_name(name) for name in genome_names],
                    "new_search_url": reverse("tpwebapp:form")
                    + "?"
                    + urlencode([("select", slug) for slug in genome_slugs]),
                }
            context["hits"] = annotate_blast_hits(parse_blastp_rows(rows), genome_names)
            return render(request, ProteinBlastView.result_template_name, context)

        result_id = uuid.uuid4()
        try:
            (result_dir / f"{result_id}.csv").write_text(
                "".join(f"{row}\n" for row in rows), encoding="utf-8"
            )
        except OSError:
            logger.exception("Saving BLAST results failed for %s", genome_names)
            return form_error("BLAST is unavailable right now. Please try again later.")

        # Straight to the results. ?genome= (one per genome) lets the result
        # page link hits to proteins and keep the genomes for "Run another search".
        params = [("genome", slug) for slug in genome_slugs]
        if locked:
            params.append(("locked", "1"))
        return redirect(reverse("tpwebapp:blast_res", args=[result_id]) + "?" + urlencode(params))
