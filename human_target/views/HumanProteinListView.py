from urllib.parse import urlencode

from django.core.paginator import EmptyPage, PageNotAnInteger, Paginator
from django.db.models import F, Q
from django.shortcuts import render
from django.views import View

from human_target.services.human_ligand_atlas import human_list_headline
from human_target.services.human_targets import human_proteins_queryset
from tpweb.views.ProteinListView import ProteinListView
from tpweb.views.mixins import PermissionLockedMixin

PAGE_SIZES = (10, 25, 50, 100)
DEFAULT_PAGE_SIZE = 25

# Toggle filters: GET key -> (label, queryset filter). Each is "1" when on.
TOGGLE_FILTERS = {
    "reviewed": ("Reviewed (Swiss-Prot)", Q(is_reviewed=True)),
    "structure": ("Any 3D structure", Q(structure_count__gt=0)),
    "experimental": ("Experimental (PDB)", Q(experimental_structure_count__gt=0)),
    "ligands": ("Any ligand evidence", Q(ligand_count__gt=0)),
    "direct": ("Measured on this protein", Q(direct_ligand_count__gt=0)),
    "drugs": ("DrugBank compounds", Q(drugbank_count__gt=0)),
    "disease": ("Disease-linked", Q(disease_count__gt=0)),
    "pathways": ("In KEGG pathways", Q(pathway_count__gt=0)),
    "surface": ("Cell surface or secreted", Q(surface_accessible=True)),
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
# Drawer categories, in the order the pathogen list uses where they overlap.
FILTER_CATEGORIES = [
    ("Structure", "3D structure", ["structure", "experimental"]),
    ("Ligands", "Ligand evidence", ["ligands", "direct"]),
    ("Pharmacology", "Known drugs", ["drugs"]),
    ("Disease", "Disease association", ["disease"]),
    ("Pathways", "Metabolic and signalling pathways", ["pathways"]),
    ("Localization", "Reachable by antibodies", ["surface"]),
    ("Expression", "Tissue specificity", None),
    ("Annotation", "UniProt curation", ["reviewed"]),
]
CATEGORY_OF = {key: category for category, _hint, keys in FILTER_CATEGORIES for key in keys or []}
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
# Optional table columns (Columns drawer); the rest are always shown.
COLUMNS = [
    ("length", "Length", "Sequence", False),
    ("structures", "Structures", "Structure", True),
    ("ligands", "Ligands", "Ligands", True),
    ("drugs", "DrugBank", "Pharmacology", True),
    ("diseases", "Diseases", "Disease", True),
    ("tissue", "Tissue specificity", "Expression", True),
    ("pathways", "Pathways", "Pathways", False),
    ("location", "Location", "Localization", True),
    ("uniprot", "UniProt status", "Annotation", False),
]
FIXED_COLUMNS = ["#", "Protein", "Description", "Gene"]


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
        try:
            size = int(request.GET.get("size", DEFAULT_PAGE_SIZE))
        except ValueError:
            size = DEFAULT_PAGE_SIZE
        if size not in PAGE_SIZES:
            size = DEFAULT_PAGE_SIZE

        # DB-side filter + pagination: the list has to scale to the full
        # proteome (~20,000 proteins), so every column it filters or sorts on
        # is a stored summary field (refresh_human_target_summary).
        proteins_qs = human_proteins_queryset(query).defer(
            "uniprot_raw", "features_raw", "publications", "expression_json", "sequence"
        )
        for key in active:
            proteins_qs = proteins_qs.filter(TOGGLE_FILTERS[key][1])
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

        paginator = Paginator(proteins_qs, size)
        try:
            page = paginator.page(request.GET.get("page"))
        except PageNotAnInteger:
            page = paginator.page(1)
        except EmptyPage:
            page = paginator.page(paginator.num_pages)

        params = {
            "q": query,
            "tissue": tissue,
            "sort": sort,
            "dir": direction if sort else "",
            "size": "" if size == DEFAULT_PAGE_SIZE else str(size),
        }
        params.update({key: "1" for key in active})

        filter_categories = []
        for category, hint, keys in FILTER_CATEGORIES:
            if keys is None:
                chips = [
                    {"name": "tissue", "value": key, "label": label, "active": tissue == key}
                    for key, (label, _q) in TISSUE_FILTERS.items()
                ]
                single = True
            else:
                chips = [
                    {
                        "name": key,
                        "value": "1",
                        "label": TOGGLE_FILTERS[key][0],
                        "active": key in active,
                    }
                    for key in keys
                ]
                single = False
            filter_categories.append(
                {
                    "category": category,
                    "hint": hint,
                    "single": single,
                    "chips": chips,
                    "active_count": sum(chip["active"] for chip in chips),
                }
            )

        active_pills = [
            {
                "category": CATEGORY_OF[key],
                "label": TOGGLE_FILTERS[key][0],
                "url": "?" + _query_string(params, **{key: "", "page": ""}),
            }
            for key in TOGGLE_FILTERS
            if key in active
        ]
        if tissue:
            active_pills.append(
                {
                    "category": "Expression",
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
        # Everything except the filters themselves, for the drawer's GET form.
        keep_params = {
            key: value
            for key, value in params.items()
            if value and key not in TOGGLE_FILTERS and key != "tissue"
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
                "page_size": size,
                "page_sizes": PAGE_SIZES,
                "filter_categories": filter_categories,
                "filter_option_count": len(TOGGLE_FILTERS) + len(TISSUE_FILTERS),
                "active_pills": active_pills,
                "keep_params": keep_params,
                "clear_filters_url": "?" + _query_string(keep_params),
                "sort": sort,
                "sort_dir": direction,
                "sort_urls": sort_urls,
                "columns": [
                    {"name": name, "label": label, "category": category, "default": default}
                    for name, label, category, default in COLUMNS
                ],
                "fixed_columns": FIXED_COLUMNS,
                "has_summary": human_proteins_queryset()
                .filter(summary_updated_at__isnull=False)
                .exists(),
                "dashboard": human_list_headline(),
            },
        )
