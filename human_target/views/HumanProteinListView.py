from urllib.parse import urlencode

from django.core.paginator import EmptyPage, PageNotAnInteger, Paginator
from django.db.models import F, Q
from django.shortcuts import render
from django.views import View

from human_target.services.human_dashboard_summary import build_human_dashboard_context
from human_target.services.human_targets import human_proteins_queryset
from tpweb.views.ProteinListView import ProteinListView
from tpweb.views.mixins import PermissionLockedMixin

PAGE_SIZE = 40

# Toggle filters: GET key -> (label, group, queryset filter). Each is "1" when on.
TOGGLE_FILTERS = {
    "reviewed": ("Reviewed (Swiss-Prot)", "Evidence", Q(is_reviewed=True)),
    "structure": ("3D structure", "Evidence", Q(structure_count__gt=0)),
    "experimental": ("Experimental structure", "Evidence", Q(experimental_structure_count__gt=0)),
    "ligands": ("Ligand evidence", "Evidence", Q(ligand_count__gt=0)),
    "direct": ("Ligands on this protein", "Evidence", Q(direct_ligand_count__gt=0)),
    "drugs": ("DrugBank compounds", "Evidence", Q(drugbank_count__gt=0)),
    "disease": ("Disease-linked", "Evidence", Q(disease_count__gt=0)),
    "pathways": ("In KEGG pathways", "Evidence", Q(pathway_count__gt=0)),
    "surface": ("Cell surface or secreted", "Location", Q(surface_accessible=True)),
}
# Tissue specificity (tau), one at a time.
TISSUE_FILTERS = {
    "restricted": ("Tissue-restricted (τ ≥ 0.8)", Q(tissue_specificity__gte=0.8)),
    "intermediate": (
        "Intermediate (0.3–0.8)",
        Q(tissue_specificity__gte=0.3, tissue_specificity__lt=0.8),
    ),
    "broad": ("Broadly expressed (τ < 0.3)", Q(tissue_specificity__lt=0.3)),
}
SORTS = {
    "protein": "uniprot_accession",
    "gene": "gene_symbol",
    "length": "sequence_length",
    "structures": "structure_count",
    "ligands": "ligand_count",
    "drugs": "drugbank_count",
    "diseases": "disease_count",
    "tissue": "tissue_specificity",
    "pathways": "pathway_count",
}
DEFAULT_SORT = ("-is_reviewed", "uniprot_accession")


def _query_string(params, **changes):
    merged = {**params, **changes}
    return urlencode({key: value for key, value in merged.items() if value})


class HumanProteinListView(PermissionLockedMixin, View):
    template_name = "human/human_protein_list.html"
    page_title = "Human Targets"
    locked_message = "Human Targets is available to project collaborators."

    def test_func(self):
        return self.request.user.has_perm("tpweb.can_view_human_targets")

    def get(self, request, *args, **kwargs):
        query = request.GET.get("q", "").strip()
        active = {key for key in TOGGLE_FILTERS if request.GET.get(key) == "1"}
        tissue = request.GET.get("tissue", "")
        if tissue not in TISSUE_FILTERS:
            tissue = ""
        sort = request.GET.get("sort", "")
        direction = "asc" if request.GET.get("dir") == "asc" else "desc"
        if sort not in SORTS:
            sort = ""

        # DB-side filter + pagination: the list has to scale to the full
        # proteome (~20,000 proteins), so every column it filters or sorts on
        # is a stored summary field (refresh_human_target_summary).
        proteins_qs = human_proteins_queryset(query).defer(
            "uniprot_raw", "features_raw", "publications", "expression_json", "sequence"
        )
        for key in active:
            proteins_qs = proteins_qs.filter(TOGGLE_FILTERS[key][2])
        if tissue:
            proteins_qs = proteins_qs.filter(TISSUE_FILTERS[tissue][1])
        if sort:
            field = SORTS[sort]
            # Proteins without the value sort last either way.
            order = (
                F(field).asc(nulls_last=True)
                if direction == "asc"
                else F(field).desc(nulls_last=True)
            )
            proteins_qs = proteins_qs.order_by(order, "uniprot_accession")
        else:
            proteins_qs = proteins_qs.order_by(*DEFAULT_SORT)
        total_count = proteins_qs.count()

        paginator = Paginator(proteins_qs, PAGE_SIZE)
        try:
            page = paginator.page(request.GET.get("page"))
        except PageNotAnInteger:
            page = paginator.page(1)
        except EmptyPage:
            page = paginator.page(paginator.num_pages)

        params = {"q": query, "tissue": tissue, "sort": sort, "dir": direction if sort else ""}
        params.update({key: "1" for key in active})
        filter_groups = {}
        for key, (label, group, _q) in TOGGLE_FILTERS.items():
            on = key in active
            filter_groups.setdefault(group, []).append(
                {
                    "label": label,
                    "active": on,
                    "url": "?" + _query_string(params, **{key: "" if on else "1", "page": ""}),
                }
            )
        filter_groups["Tissue specificity"] = [
            {
                "label": label,
                "active": tissue == key,
                "url": "?" + _query_string(params, tissue="" if tissue == key else key, page=""),
            }
            for key, (label, _q) in TISSUE_FILTERS.items()
        ]
        active_pills = [
            {
                "label": TOGGLE_FILTERS[key][0],
                "url": "?" + _query_string(params, **{key: "", "page": ""}),
            }
            for key in TOGGLE_FILTERS
            if key in active
        ]
        if tissue:
            active_pills.append(
                {
                    "label": TISSUE_FILTERS[tissue][0],
                    "url": "?" + _query_string(params, tissue="", page=""),
                }
            )
        sort_urls = {
            key: "?"
            + _query_string(
                params,
                sort=key,
                dir="asc" if (sort == key and direction == "desc") else "desc",
                page="",
            )
            for key in SORTS
        }

        return render(
            request,
            self.template_name,
            {
                "proteins": page,
                "page_numbers": ProteinListView._build_page_numbers(
                    page.number, paginator.num_pages
                ),
                "query_string": _query_string(params),
                "total_count": total_count,
                "all_count": human_proteins_queryset().count()
                if (query or active or tissue)
                else total_count,
                "query": query,
                "filter_groups": filter_groups,
                "active_pills": active_pills,
                "clear_filters_url": "?" + _query_string({"q": query}),
                "sort": sort,
                "sort_dir": direction,
                "sort_urls": sort_urls,
                "has_summary": human_proteins_queryset()
                .filter(summary_updated_at__isnull=False)
                .exists(),
                "dashboard": build_human_dashboard_context(),
            },
        )
