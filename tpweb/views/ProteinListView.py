from django.views import View
from django.shortcuts import render

from bioseq.models.Biodatabase import Biodatabase
from bioseq.models.Bioentry import Bioentry
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger

from tpweb.models.ScoreFormula import ScoreFormula
from tpweb.models.ScoreParam import ScoreParam


class ProteinListView(View):
    template_name = 'search/proteins.html'

    # score_dict = ["Length", "PW", "Druggability"]

    def get(self, request, assembly_name, *args, **kwargs):

        bdb = Biodatabase.objects.filter(name=assembly_name).get()
        # ScoreParam.initialize()
        formula = ScoreFormula.objects.filter(name="GARDP").get()
        formuladto = self.create_formuladto(formula)
        weights = {}  # x.score_param.name:x.coefficient for x in  formula.terms.all()

        score_params = list(ScoreParam.objects.all())
        tcolumns = ["Score"]
        score_dict = {}
        for sp in score_params:
            score_dict[sp.name] = sp
            tcolumns.append(sp.name)

        tdatas = {}
        page = request.GET.get('page', 1)
        pageSize = request.GET.get('pageSize', 10)

        proteins = Bioentry.objects.filter(
            biodatabase__name=assembly_name + Biodatabase.PROT_POSTFIX,
            structures__isnull=False
        ).prefetch_related("qualifiers__term", "dbxrefs__dbxref", "score_params__score_param")

        paginator = Paginator(proteins, pageSize)

        try:
            proteins = paginator.page(page)
        except PageNotAnInteger:
            proteins = paginator.page(1)
        except EmptyPage:
            proteins = paginator.page(paginator.num_pages)

        proteins_dto = []
        for protein in proteins:
            protein_dto = {
                "id": protein.bioentry_id,
                "accession": protein.accession,
                "genes": protein.genes(),
                "name": protein.name,
                "description": protein.description
            }
            """
            qvs = genome.qualifiers_dict()
            for qname in GenomesView.score_dict:
                if qname in qvs:
                    genome_dto[qname] = qvs[qname]
            
            """
            tdata = {spv.score_param.name: spv.value for spv in protein.score_params.all()}
            weight = {}

            for term in formula.terms.all():
                if term.score_param.name in tdata:
                    val = round(term.score(tdata[term.score_param.name]), 2)
                    if term.score_param.name in weight:
                        weight[term.score_param.name] += val
                    else:
                        weight[term.score_param.name] = val

            tdata["Score"] = formula.score(protein)
            protein_dto["score"] = tdata["Score"]
            # "Length":protein.seq.length,

            tdatas[protein.bioentry_id] = tdata
            weights[protein.bioentry_id] = weight

            proteins_dto.append(protein_dto)
        proteins_dto = sorted(proteins_dto, key=lambda x: x["score"], reverse=True)

        return render(request, self.template_name, {
            "biodb__name": bdb.description if bdb.description else bdb.name,
            "formula": formula,
            "proteins": proteins_dto,
            "score_dict": score_dict,
            "tcolumns": tcolumns,
            "weights": weights,
            "tdata": tdatas,
            "formula": formuladto
        })  # , {'form': form})

    def create_formuladto(self, formula: ScoreFormula):
        formuladto = {
            "name": formula.name,
            "terms": [{"coefficient": t.coefficient,
                       "param": t.score_param.name,
                       "desc": t.score_param.description + "Possible values: " +
                               "-".join([x.name for x in t.score_param.choices.all()]) + ". " +  ". ".join(
                           [x.name + ": " + x.description for x in t.score_param.choices.all() if x.description])
                       }
                      for t in formula.terms.all()]
        }
        return formuladto
