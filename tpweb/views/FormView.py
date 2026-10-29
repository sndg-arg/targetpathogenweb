import os
import subprocess as sp
import uuid
from pathlib import Path

from django.conf import settings
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views import View

from bioseq.io.SeqStore import SeqStore
from bioseq.models.Biodatabase import Biodatabase
from tpweb.services.genome_workspace import (
    display_genome_name,
    genome_url_slug,
    resolve_genome_from_slug,
)
from tpweb.services.genomes import build_genomes_queryset
from tpweb.views.ProteinBlastView import ProteinBlastView


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

    def _build_context(self, request, selected_biodatabase=None, **extra):
        selected_genome_name = selected_biodatabase.name if selected_biodatabase else ""
        context = {
            "db_options": self._db_options(request),
            "selected_db_value": str(selected_biodatabase.biodatabase_id)
            if selected_biodatabase
            else "",
            "selected_genome_name": selected_genome_name,
            "selected_genome_label": display_genome_name(selected_genome_name)
            if selected_genome_name
            else "",
            "selected_genome_description": selected_biodatabase.description
            if selected_biodatabase
            else "",
            "blast_locked_to_genome": bool(selected_biodatabase),
            "selected_genome_workspace_url": (
                reverse(
                    "tpwebapp:assembly",
                    kwargs={"genome": genome_url_slug(selected_biodatabase.name)},
                )
                if selected_biodatabase
                else ""
            ),
        }
        context.update(extra)
        return context

    def _resolve_selected_biodatabase(self, request):
        genome_name = str(
            request.GET.get("genome") or request.POST.get("genome_name") or ""
        ).strip()
        if genome_name:
            resolved = resolve_genome_from_slug(request.user, genome_name)
            if not resolved:
                return None
            return Biodatabase.objects.filter(name=resolved).first()

        selected_item = str(request.POST.get("dropdown") or "").strip()
        if selected_item:
            return build_genomes_queryset(user=request.user).filter(pk=selected_item).first()

        return None

    def get(self, request, *args, **kwargs):
        selected_biodatabase = self._resolve_selected_biodatabase(request)
        context = self._build_context(request, selected_biodatabase)
        # ?select=<genome> (from "Run another search") preselects the genome in
        # the picker without locking the page to it.
        preselect = (request.GET.get("select") or "").strip()
        if preselect and not selected_biodatabase:
            resolved = resolve_genome_from_slug(request.user, preselect)
            match = next(
                (option for option in context["db_options"] if option["internal_name"] == resolved),
                None,
            )
            if match:
                context["selected_db_value"] = str(match["value"])
        return render(request, self.template_name, context)

    def post(self, request, *args, **kwargs):
        if not request.user.has_perm("tpweb.can_run_blast"):
            return render(
                request,
                self.template_name,
                self._build_context(
                    request,
                    self._resolve_selected_biodatabase(request),
                    error_message="You don't have permission to run BLAST searches.",
                ),
            )

        selected_biodatabase = self._resolve_selected_biodatabase(request)
        text_input = (request.POST.get("text_input") or "").strip()

        # One BLAST page for both sequence types: a protein query goes to the
        # genome's blastp search (ProteinBlastView), which renders its own
        # form/result pages, instead of students having to find it on the
        # genome page.
        if request.POST.get("blast_type") == "protein":
            if selected_biodatabase is None:
                return render(
                    request,
                    self.template_name,
                    self._build_context(
                        request,
                        None,
                        error_message="Please select a valid genome before running BLAST.",
                        text_input_value=text_input,
                        blast_type="protein",
                    ),
                )
            post = request.POST.copy()
            post["sequence"] = text_input
            request.POST = post
            return ProteinBlastView.as_view()(
                request, genome=genome_url_slug(selected_biodatabase.name)
            )
        max_chars = int(os.environ.get("TPW_BLAST_MAX_QUERY_CHARS", "20000"))

        if not text_input:
            return render(
                request,
                self.template_name,
                self._build_context(
                    request,
                    selected_biodatabase,
                    error_message="Please provide a valid query. The query is empty!",
                    text_input_value=text_input,
                ),
            )

        if len(text_input) > max_chars:
            return render(
                request,
                self.template_name,
                self._build_context(
                    request,
                    selected_biodatabase,
                    error_message=f"BLAST query is too large. Limit: {max_chars} characters.",
                    text_input_value=text_input[:max_chars],
                ),
            )

        if selected_biodatabase is None:
            return render(
                request,
                self.template_name,
                self._build_context(
                    request,
                    None,
                    error_message="Please select a valid genome before running BLAST.",
                    text_input_value=text_input,
                ),
            )

        result_id = uuid.uuid4()
        result_dir = Path(settings.MEDIA_ROOT) / "blast_results"
        result_dir.mkdir(parents=True, exist_ok=True)
        query_path = result_dir / f"{result_id}.fna"
        output_path = result_dir / f"{result_id}.csv"
        db_location = SeqStore(settings.SEQS_DATA_DIR).genes_fna(selected_biodatabase.name)
        blast_bin = getattr(settings, "BLASTN_PATH", "blastn")
        timeout_seconds = int(os.environ.get("TPW_BLAST_TIMEOUT_SEC", "60"))

        try:
            query_path.write_text(text_input, encoding="utf-8")
            cmd = [
                blast_bin,
                "-query",
                str(query_path),
                "-db",
                db_location,
                "-evalue",
                "1e-6",
                "-num_threads",
                "2",
                "-out",
                str(output_path),
                "-outfmt",
                "6",
            ]
            sp.check_output(cmd, stderr=sp.STDOUT, timeout=timeout_seconds)
        except sp.TimeoutExpired:
            return render(
                request,
                self.template_name,
                self._build_context(
                    request,
                    selected_biodatabase,
                    error_message=f"BLAST query timed out after {timeout_seconds} seconds.",
                    text_input_value=text_input,
                ),
            )
        except sp.CalledProcessError as exc:
            details = exc.output.decode("utf-8", errors="replace") if exc.output else str(exc)
            return render(
                request,
                self.template_name,
                self._build_context(
                    request,
                    selected_biodatabase,
                    error_message=f"BLAST query failed. {details}",
                    text_input_value=text_input,
                ),
            )
        except OSError as exc:
            return render(
                request,
                self.template_name,
                self._build_context(
                    request,
                    selected_biodatabase,
                    error_message=f"BLAST executable is unavailable. {exc}",
                    text_input_value=text_input,
                ),
            )
        finally:
            query_path.unlink(missing_ok=True)

        # Straight to the results (they used to sit behind a "BLAST completed.
        # Open results ->" link). ?genome= lets the result page link hits to
        # proteins and keep the genome for "Run another search".
        result_url = reverse("tpwebapp:blast_res", args=[result_id])
        query = f"?genome={genome_url_slug(selected_biodatabase.name)}"
        if request.POST.get("genome_name"):
            query += "&locked=1"
        return redirect(result_url + query)
