from django.shortcuts import render
from django.views import View
from bioseq.models.Biodatabase import Biodatabase
import uuid
import subprocess as sp
import os
from bioseq.io.SeqStore import SeqStore
from tpweb.services.genome_workspace import display_genome_name, genome_url_slug
from django.urls import reverse

class FormView(View):

    def __init__(self):
        # Set the location of the HTML template
        self.template_name = 'blast/form.html'
        # Define db_options to fill the dropdown
        biodatabases = Biodatabase.objects.all()
        self.db_options = [
            {
                'value': bd.biodatabase_id,
                'label': display_genome_name(bd.name),
                'internal_name': bd.name,
            }
            for bd in biodatabases
            if not bd.name.endswith(('_prots', '_rnas'))
        ]

    def _build_context(self, selected_biodatabase=None, **extra):
        selected_genome_name = selected_biodatabase.name if selected_biodatabase else ""
        context = {
            'db_options': self.db_options,
            'selected_db_value': str(selected_biodatabase.biodatabase_id) if selected_biodatabase else "",
            'selected_genome_name': selected_genome_name,
            'selected_genome_label': display_genome_name(selected_genome_name) if selected_genome_name else "",
            'selected_genome_description': selected_biodatabase.description if selected_biodatabase else "",
            'blast_locked_to_genome': bool(selected_biodatabase),
            'selected_genome_workspace_url': (
                reverse("tpwebapp:assembly", kwargs={"genome": genome_url_slug(selected_biodatabase.name)})
                if selected_biodatabase
                else ""
            ),
        }
        context.update(extra)
        return context

    def _resolve_selected_biodatabase(self, request):
        genome_name = str(request.GET.get("genome") or request.POST.get("genome_name") or "").strip()
        if genome_name:
            return Biodatabase.objects.filter(name=genome_name).first()

        selected_item = str(request.POST.get('dropdown') or "").strip()
        if selected_item:
            return Biodatabase.objects.filter(pk=selected_item).first()

        return None

    def get(self, request, *args, **kwargs):
        selected_biodatabase = self._resolve_selected_biodatabase(request)
        return render(request, self.template_name, self._build_context(selected_biodatabase))

    def post(self, request, *args, **kwargs):
        if request.method == 'POST':
            selected_biodatabase = self._resolve_selected_biodatabase(request)
            text_input = request.POST.get('text_input')

            if not text_input:
                return render(request, self.template_name, self._build_context(
                    selected_biodatabase,
                    error_message='Please provide a valid query. The query is empty!',
                    text_input_value=text_input,
                ))

            if selected_biodatabase is None:
                return render(request, self.template_name, self._build_context(
                    None,
                    error_message='Please select a valid genome before running BLAST.',
                    text_input_value=text_input,
                ))

            uuid_1 = uuid.uuid1()
            db_location = SeqStore('./data').genes_fna(selected_biodatabase.name)
            query_path = f"{uuid_1}.fna"
            output_path = f"{uuid_1}.csv"
            blast_bin = "./opt/ncbi-blast-2.15.0+-x64-linux/ncbi-blast-2.15.0+/bin/blastn"

            try:
                with open(query_path, "w", encoding="utf-8") as file:
                    file.write(text_input)

                cmd = [
                    blast_bin,
                    "-query", query_path,
                    "-db", db_location,
                    "-evalue", "1e-6",
                    "-num_threads", "4",
                    "-out", output_path,
                    "-outfmt", "6",
                ]
                sp.check_output(cmd, stderr=sp.STDOUT)
            except sp.CalledProcessError as exc:
                details = exc.output.decode("utf-8", errors="replace") if exc.output else str(exc)
                return render(request, self.template_name, self._build_context(
                    selected_biodatabase,
                    error_message=f'BLAST query failed. {details}',
                    text_input_value=text_input,
                ))
            finally:
                if os.path.exists(query_path):
                    os.remove(query_path)

            return render(request, self.template_name, self._build_context(
                selected_biodatabase,
                message=(
                    f"You selected item {selected_biodatabase.name} "
                    f"{selected_biodatabase.description} and entered text: '{text_input}'. "
                    f"y el UUID es '{uuid_1}'"
                ),
                result_id=uuid_1,
                text_input_value=text_input,
            ))

        else:
            return render(request, self.template_name, self._build_context())
