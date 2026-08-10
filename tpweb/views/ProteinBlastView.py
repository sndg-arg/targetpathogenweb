import os
import subprocess as sp
import uuid
from pathlib import Path

from django.conf import settings
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import Http404
from django.shortcuts import render
from django.urls import reverse
from django.views import View

from bioseq.io.SeqStore import SeqStore
from bioseq.models.Biodatabase import Biodatabase
from bioseq.models.Bioentry import Bioentry
from tpweb.services.genome_workspace import display_genome_name, resolve_genome_from_slug


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

        query_id = uuid.uuid4()
        result_dir = Path(settings.MEDIA_ROOT) / "blast_results"
        result_dir.mkdir(parents=True, exist_ok=True)
        query_path = result_dir / f"{query_id}.faa"
        output_path = result_dir / f"{query_id}.tsv"
        db_location = SeqStore(settings.SEQS_DATA_DIR).faa(resolved)
        blast_bin = getattr(settings, "BLASTP_PATH", "blastp")
        timeout_seconds = int(os.environ.get("TPW_BLAST_TIMEOUT_SEC", "60"))

        try:
            query_text = sequence if sequence.startswith(">") else f">query_1\n{sequence}"
            query_path.write_text(query_text, encoding="utf-8")
            cmd = [
                blast_bin,
                "-query",
                str(query_path),
                "-db",
                db_location,
                "-evalue",
                "1e-5",
                "-num_threads",
                "2",
                "-max_target_seqs",
                "20",
                "-out",
                str(output_path),
                "-outfmt",
                "6 qseqid sseqid pident length mismatch evalue bitscore",
            ]
            sp.check_output(cmd, stderr=sp.STDOUT, timeout=timeout_seconds)
        except sp.TimeoutExpired:
            context["error_message"] = f"BLAST query timed out after {timeout_seconds} seconds."
            return render(request, self.form_template_name, context)
        except sp.CalledProcessError as exc:
            details = exc.output.decode("utf-8", errors="replace") if exc.output else str(exc)
            context["error_message"] = f"BLAST query failed. {details}"
            return render(request, self.form_template_name, context)
        except OSError as exc:
            context["error_message"] = f"BLAST executable is unavailable. {exc}"
            return render(request, self.form_template_name, context)
        finally:
            query_path.unlink(missing_ok=True)

        hits = []
        if output_path.is_file():
            raw = output_path.read_text(encoding="utf-8", errors="replace")
            output_path.unlink(missing_ok=True)
            for line in raw.splitlines():
                fields = line.split("\t")
                if len(fields) < 7:
                    continue
                qseqid, sseqid, pident, length, mismatch, evalue, bitscore = fields[:7]
                hits.append(
                    {
                        "query": qseqid,
                        "subject_id": sseqid,
                        "identity": pident,
                        "length": length,
                        "mismatch": mismatch,
                        "evalue": evalue,
                        "bitscore": bitscore,
                    }
                )

        # Best-effort mapping of the BLAST subject id back to a clickable protein --
        # the protein FASTA headers written by index_genome_seq_clean are keyed by
        # accession, matching what every other page in the app links proteins by.
        proteome_name = resolved + Biodatabase.PROT_POSTFIX
        subject_ids = {hit["subject_id"] for hit in hits}
        proteins_by_accession = {
            protein.accession: protein
            for protein in Bioentry.objects.filter(
                biodatabase__name=proteome_name, accession__in=subject_ids
            )
        }
        for hit in hits:
            hit["protein"] = proteins_by_accession.get(hit["subject_id"])

        context["hits"] = hits
        return render(request, self.result_template_name, context)
