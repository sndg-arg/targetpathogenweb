from django.shortcuts import render
from django.views import View

from tpweb.services.human_targets import human_bioentries_queryset


class HumanProteinListView(View):
    template_name = "human/human_protein_list.html"

    def get(self, request, *args, **kwargs):
        query = request.GET.get("q", "").strip()
        bioentries = human_bioentries_queryset()

        proteins = []
        for bioentry in bioentries:
            hp = getattr(bioentry, "human_protein", None)
            if hp is None:
                continue
            proteins.append(hp)

        if query:
            needle = query.lower()
            proteins = [
                hp for hp in proteins
                if needle in hp.uniprot_accession.lower()
                or needle in (hp.gene_symbol or "").lower()
                or needle in (hp.protein_name or "").lower()
            ]

        return render(request, self.template_name, {
            "proteins": proteins,
            "total_count": len(proteins),
            "query": query,
        })
