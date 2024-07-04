from django.views import View
from django.shortcuts import render

from bioseq.models.Biodatabase import Biodatabase
from bioseq.models.Bioentry import Bioentry
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.db.models import Q

from tpweb.models.ScoreFormula import ScoreFormula
from tpweb.models.ScoreParam import ScoreParam


class ProteinListView(View):
    template_name = 'search/proteins.html'

    # score_dict = ["Length", "PW", "Druggability"]

    def get(self, request, assembly_name, *args, **kwargs):
        formula = None
        formulas = list(request.user.formulas.all())
        sf = request.GET.get('scoreformula','')
        if sf and [x for x in formulas if x.name==sf]:
            formula = [x for x in formulas if x.name==sf][0]
        if not formula:
            formula = [x for x in formulas if x.default][0]


        bdb = Biodatabase.objects.filter(name=assembly_name).get()
        #ScoreParam.initialize()
        #formula = ScoreFormula.objects.filter(name="GARDP_Target_Overall").get()
        #formula = ScoreFormula.objects.filter(name="GARDP_Virtual_Screening").get()



        col_descriptions = {t.score_param.name: t.score_param.description + ". Possible values: " +
                                                "-".join(
                                                    [x.name for x in t.score_param.choices.all()]) + ". " + ". ".join(
            [x.name + ": " + x.description for x in t.score_param.choices.all() if x.description])

                            for t in formula.terms.all()}


        formuladto = self.create_formuladto(formula, col_descriptions)
        weights = {}  # x.score_param.name:x.coefficient for x in  formula.terms.all()

        score_params = set(x.score_param for x in formula.terms.all())
        tcolumns = ["Score"]
        score_dict = {}
        for sp in score_params:
            score_dict[sp.name] = sp
            tcolumns.append(sp.name)

        tdatas = {}
        page = request.GET.get('page', 1)
        pageSize = request.GET.get('pageSize', 10)

        search_query = request.GET.get('search', '').strip()
        proteins = Bioentry.objects.filter(
            biodatabase__name=assembly_name + Biodatabase.PROT_POSTFIX,
            #structures__isnull=False
        ).prefetch_related("qualifiers__term", "dbxrefs__dbxref", "score_params__score_param")

        selected_parameters = request.session.get('selected_parameters', {})
        print(selected_parameters)
        if selected_parameters:
            parameter_dict = {}
            for parameter in selected_parameters:
                score_param = parameter.get('score_param_id')
                score_name = parameter.get('name')
                if score_param not in parameter_dict.keys():
                    parameter_dict[score_param] = [score_name]
                else:
                    parameter_dict[score_param].append(score_name)
            for p in parameter_dict:
                proteins = proteins.filter(
                        Q(score_params__id=p) |
                        Q(score_params__value__in=parameter_dict[p])
                        )
            print(parameter_dict)
        if search_query:
            proteins = proteins.filter(
                Q(accession__icontains=search_query) |
                Q(description__icontains=search_query) |
                Q(accession__iexact=search_query)
                )
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
                "genes": [x for x in protein.genes() if len(x) <=6 ] ,
                "name": protein.name,
                "description": protein.description
            }
            """
            qvs = genome.qualifiers_dict()
            for qname in GenomesView.score_dict:
                if qname in qvs:
                    genome_dto[qname] = qvs[qname]
            
            """
            tdata = {spv.score_param.name: spv.value for spv in protein.score_params.all()
                     if spv.score_param.name in col_descriptions}
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
        filter_applied = '?' in request.build_absolute_uri()
        print(filter_applied)
        #Pagination info
        pagination_info = {
            'proteins': proteins,
            'has_previous': proteins.has_previous(),
            'has_next': proteins.has_next(),
            'previous_page_number': proteins.previous_page_number() if proteins.has_previous() else None,
            'next_page_number': proteins.next_page_number() if proteins.has_next() else None,
            'number': proteins.number,
            'num_pages': proteins.paginator.num_pages,
            'page_range': proteins.paginator.page_range
        }

        return render(request, self.template_name, {
            "biodb__name": bdb.description if bdb.description else bdb.name,
            "proteins": proteins_dto,
            "score_dict": score_dict,
            "tcolumns": tcolumns,
            "weights": weights,
            "tdata": tdatas,
            "formula": formuladto,
            "col_descriptions":col_descriptions,
            "formulas":formulas,
            'base_url': request.build_absolute_uri(),
            'filter_applied': filter_applied,
            "assembly_name":assembly_name,
            "pagination":pagination_info

        })  # , {'form': form})

    def create_formuladto(self, formula: ScoreFormula, desc_dict):


        terms = {}

        for t in formula.terms.all():
            if t.score_param.name in terms:
                terms[t.score_param.name].append(t)
            else:
                terms[t.score_param.name] = [t]


        terms2 = []
        for param_name,ts in terms.items():
            if len(ts) == 1:
                t = ts[0]
                terms2.append({"coefficient": t.coefficient,
                               "param": t.score_param.name,
                               "desc": desc_dict[t.score_param.name]
                               })
            else:
                desc = " ".join( [ f'{t.coefficient} if {t.value} ' for t in ts  ])
                terms2.append({"coefficient": 1,
                               "param": t.score_param.name,
                               "desc": desc
                               })

        formuladto = {
            "name": formula.name,
            "terms": terms2,

        }

        return formuladto
