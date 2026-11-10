import logging
import os

from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import Http404
from django.shortcuts import render
from django.urls import reverse
from django.views import View

from bioseq.models.Biodatabase import Biodatabase
from tpweb.services.blast_files import blast_results_dir
from tpweb.services.blast_search import BlastError, annotate_blast_hits, run_blast
from tpweb.services.genome_workspace import display_genome_name, resolve_genome_from_slug

logger = logging.getLogger(__name__)


class ProteinBlastView(LoginRequiredMixin, View):
    """blastp search against a single genome's protein set -- a standalone page
    reached from a button on the genome overview (assembly.html), the same pattern
    as FormView's genome-locked blastn page, just amino-acid and always locked to
    one genome (no genome picker). Reuses the protein BLAST db that
    index_genome_seq_clean already builds for every genome at pipeline stage 9
    (makeblastdb -dbtype prot over SeqStore.faa) -- no new indexing step needed."""

    form_template_name = "blast/protein_form.html"
    result_template_name = "blast/protein_result.html"

    def _base_context(self, resolved, genome_slug):
        return {
            "genome_name": resolved,
            "genome_label": display_genome_name(resolved),
            "assembly_url": reverse("tpwebapp:assembly", kwargs={"genome": genome_slug}),
            "proteins_url": reverse("tpwebapp:protein_list", kwargs={"genome": genome_slug}),
        }

    def _resolve_or_404(self, request, genome):
        resolved = resolve_genome_from_slug(request.user, genome)
        if not resolved or not Biodatabase.objects.filter(name=resolved).exists():
            raise Http404("Genome not found")
        return resolved

    def get(self, request, genome, *args, **kwargs):
        resolved = self._resolve_or_404(request, genome)
        context = self._base_context(resolved, genome)
        context["sequence_value"] = ""
        return render(request, self.form_template_name, context)

    def post(self, request, genome, *args, **kwargs):
        resolved = self._resolve_or_404(request, genome)
        context = self._base_context(resolved, genome)

        # Same permission the nucleotide BLAST page (FormView) checks; this
        # page didn't, so any signed-in account could run blastp.
        if not request.user.has_perm("tpweb.can_run_blast"):
            context["sequence_value"] = (request.POST.get("sequence") or "").strip()
            context["error_message"] = "You don't have permission to run BLAST searches."
            return render(request, self.form_template_name, context)

        sequence = (request.POST.get("sequence") or "").strip()
        max_chars = int(os.environ.get("TPW_BLAST_MAX_QUERY_CHARS", "20000"))
        context["sequence_value"] = sequence

        if not sequence:
            context["error_message"] = (
                "Please provide a valid amino acid sequence. The query is empty!"
            )
            return render(request, self.form_template_name, context)
        if len(sequence) > max_chars:
            context["error_message"] = f"Query is too large. Limit: {max_chars} characters."
            context["sequence_value"] = sequence[:max_chars]
            return render(request, self.form_template_name, context)

        try:
            result_dir = blast_results_dir()
        except Exception:
            logger.exception("Protein BLAST setup failed for %s", resolved)
            context["error_message"] = "BLAST is unavailable right now. Please try again later."
            return render(request, self.form_template_name, context)
        query_text = sequence if sequence.startswith(">") else f">query_1\n{sequence}"
        try:
            rows = run_blast("protein", query_text, [resolved], result_dir)
        except BlastError as exc:
            context["error_message"] = str(exc)
            return render(request, self.form_template_name, context)

        context["hits"] = annotate_blast_hits(parse_blastp_rows(rows), [resolved])
        return render(request, self.result_template_name, context)


def parse_blastp_rows(rows):
    """Rows from run_blast("protein", ...): the 7 requested columns + genome."""
    hits = []
    for line in rows:
        fields = line.split("\t")
        if len(fields) < 8:
            continue
        qseqid, sseqid, pident, length, mismatch, evalue, bitscore, genome = fields[:8]
        hits.append(
            {
                "query": qseqid,
                "subject_id": sseqid,
                "identity": pident,
                "length": length,
                "mismatch": mismatch,
                "evalue": evalue,
                "bitscore": bitscore,
                "genome": genome,
            }
        )
    return hits
