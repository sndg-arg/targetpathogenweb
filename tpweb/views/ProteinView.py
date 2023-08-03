from django.shortcuts import render
from django.views import View


class ProteinView(View):
    template_name = 'genomic/protein.html'

    def get(self, request, *args, **kwargs):
        # form = self.form_class(initial=self.initial)
        protein = {"accession": "Q5QQ46",
                   "description": "Inositol-3-phosphate synthase",
                   "gene": "ino1",
                   "size": 528,
                   "assembly_id": 123,
                   "assembly_name": "H37Rv",
                   "status": "annotated"
                   }
        features = [
            {
                "start": 1,
                "end": 50,
                "db": "pfam",
                "fam": "",
                "term": "PF01551.21",
                "name": "Peptidase family M23"
            }
        ]
        annotations = [
            {
                "db": "GO",
                "fam": "BP",
                "term": "go:0016021",
                "name": "integral component of membrane"
            }
        ]
        return render(request, self.template_name, {"protein": protein,
                                                    "features": features,
                                                    "annotations": annotations})
