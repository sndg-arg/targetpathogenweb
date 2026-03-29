from pathlib import Path

from django.http import Http404
from django.shortcuts import render
from django.urls import reverse
from django.views import View

from tpweb.models.CustomParamFile import CustomParam
from tpweb.services.genome_workspace import display_genome_name, genome_url_slug, resolve_genome_from_slug
from tpweb.services.pipeline_status import annotate_pipeline_status_for_genome, get_pipeline_status
from tpweb.services.protein_formula import choose_formula, resolve_formulas_for_user
from tpweb.services.workspace import resolve_workspace_user
from tpweb.services.csv_exports import xlsx_sections_response


class PrioritizationSetupView(View):
    template_name = "search/prioritization_setup.html"

    @staticmethod
    def _build_view_export_url(request):
        params = request.GET.copy()
        params["export"] = "view_csv"
        encoded = params.urlencode()
        return f"?{encoded}" if encoded else "?export=view_csv"

    @staticmethod
    def _formula_rows(formulas, selected_formula):
        rows = []
        selected_name = getattr(selected_formula, "name", None)
        for formula in formulas:
            rows.append(
                {
                    "name": formula.name,
                    "term_count": formula.terms.count(),
                    "expression": formula.get_current_formula(),
                    "is_selected": formula.name == selected_name,
                    "is_default": formula.default,
                    "source_label": "Workspace" if formula.user_id else "Shared",
                }
            )
        return rows

    @staticmethod
    def _custom_evidence_rows(custom_params):
        rows = []
        for custom_param in custom_params:
            rows.append(
                {
                    "file_name": Path(custom_param.tsv.name).name,
                    "relative_path": custom_param.tsv.name,
                }
            )
        return rows

    def get(self, request, genome, *args, **kwargs):
        assembly_name = resolve_genome_from_slug(request.user, genome)
        if not assembly_name:
            raise Http404("Genome not found")

        workspace_user = resolve_workspace_user(request.user)
        formulas = resolve_formulas_for_user(request.user)
        selected_formula = choose_formula(formulas, request.GET.get("scoreformula"))
        formula_rows = self._formula_rows(formulas, selected_formula)

        custom_params = list(
            CustomParam.objects.filter(
                owner=workspace_user,
                accession=assembly_name,
            ).order_by("tsv")
        )
        custom_evidence_rows = self._custom_evidence_rows(custom_params)
        pipeline_status = annotate_pipeline_status_for_genome(
            get_pipeline_status(), assembly_name
        )

        if request.GET.get("export") == "view_csv":
            sections = [
                {
                    "title": "Prioritization setup",
                    "headers": ["Field", "Value"],
                    "rows": [
                        ["Genome", display_genome_name(assembly_name)],
                        ["Scoring models", len(formula_rows)],
                        ["Evidence files", len(custom_evidence_rows)],
                        ["Active formula", getattr(selected_formula, "name", "")],
                        ["Active expression", selected_formula.get_current_formula() if selected_formula else ""],
                    ],
                },
                {
                    "title": "Available models",
                    "headers": ["Name", "Selected", "Default", "Source", "Terms", "Expression"],
                    "rows": [
                        [
                            row["name"],
                            "Yes" if row["is_selected"] else "No",
                            "Yes" if row["is_default"] else "No",
                            row["source_label"],
                            row["term_count"],
                            row["expression"],
                        ]
                        for row in formula_rows
                    ],
                },
                {
                    "title": "Custom evidence files",
                    "headers": ["File name", "Relative path"],
                    "rows": [
                        [row["file_name"], row["relative_path"]]
                        for row in custom_evidence_rows
                    ],
                },
            ]
            return xlsx_sections_response(f"{assembly_name}-prioritization-setup", sections)

        return render(
            request,
            self.template_name,
            {
                "assembly_name": assembly_name,
                "assembly_label": display_genome_name(assembly_name),
                "genome": genome_url_slug(assembly_name),
                "selected_formula": selected_formula,
                "formula_rows": formula_rows,
                "formula_count": len(formula_rows),
                "custom_evidence_rows": custom_evidence_rows,
                "custom_evidence_count": len(custom_evidence_rows),
                "pipeline_status": pipeline_status,
                "view_export_url": self._build_view_export_url(request),
                "proteins_url": reverse("tpwebapp:protein_list", kwargs={"genome": genome_url_slug(assembly_name)}),
                "formula_builder_url": reverse("tpwebapp:formula_form", kwargs={"genome": genome_url_slug(assembly_name)}),
                "custom_evidence_url": reverse("tpwebapp:customparam", kwargs={"genome": genome_url_slug(assembly_name)}),
                "ec_explorer_url": reverse(
                    "tpwebapp:annotation_explorer",
                    kwargs={"genome": genome_url_slug(assembly_name), "annotation_kind": "ec"},
                ),
            },
        )
