from ckeditor_uploader.fields import RichTextUploadingField
from django.db import models
from django.db.models import SmallIntegerField, CharField, TextField




class ScoreParam(models.Model):
    category = CharField(max_length=255, blank=False)
    name = CharField(max_length=255, unique=True)
    type = CharField(max_length=255, choices=(("C", "CATEGORICAL"), ("N", "NUMERIC")))
    default_operation = CharField(max_length=255)
    default_value = CharField(max_length=255)
    description = TextField(default="")

    class Meta:
        unique_together = ('category', 'name',)

    def __repr__(self):
        return f'ScoreParam({self.name} - {self.category})'

    def __str__(self):
        return self.__repr__()

    @staticmethod
    def initialize():
        """
        sp = ScoreParam.objects.get_or_create(
            category="Structure", name="druggability", type="NUMERIC",
            default_operation=">",default_value="Y")[0]


        sp = ScoreParam.objects.get_or_create(
            category="Structure", name="catalitic_site", type="CATEGORICAL",
            default_operation="=",default_value="Y")[0]
        ScoreParamOptions.objects.get_or_create(score_param=sp,name="Y")
        ScoreParamOptions.objects.get_or_create(score_param=sp,name="N")

        sp = ScoreParam.objects.get_or_create(
            category="Structure", name="ligand_aln", type="CATEGORICAL",
            default_operation="=",default_value="Y")[0]
        ScoreParamOptions.objects.get_or_create(score_param=sp,name="Y")
        ScoreParamOptions.objects.get_or_create(score_param=sp,name="N")

        sp = ScoreParam.objects.get_or_create(
            category="Pocket", name="pocket_conserv", type="CATEGORICAL",
            description="Pocket with sites of low conservation within the species",
            default_operation="=",default_value="N")[0]
        ScoreParamOptions.objects.get_or_create(score_param=sp,name="Y")
        ScoreParamOptions.objects.get_or_create(score_param=sp,name="Y")

        sp = ScoreParam.objects.get_or_create(
            category="Pocket", name="pocket_conserv_coli", type="CATEGORICAL",
            description="Pocket with sites of low conservation against Ecoli.",
            default_operation="=",default_value="N")[0]
        ScoreParamOptions.objects.get_or_create(score_param=sp,name="Y")
        ScoreParamOptions.objects.get_or_create(score_param=sp,name="Y")
        """
        from tpweb.models.ScoreFormula import ScoreFormula, ScoreFormulaParam
        ScoreFormula.objects.filter(name="GARDP").delete()
        sf = ScoreFormula(name="GARDP")
        sf.save()


        sp = ScoreParam.objects.get_or_create(
            category="Pocket", name="druggable_pocket", type="CATEGORICAL",
            description="Protein has at least one druggable pocket",
            default_operation="=", default_value="Y")[0]
        ScoreParamOptions.objects.get_or_create(score_param=sp, name="Y")
        ScoreParamOptions.objects.get_or_create(score_param=sp, name="N")

        ScoreFormulaParam(formula=sf,operation="=",coefficient=2,value="Y",score_param=sp).save()

        sp = ScoreParam.objects.get_or_create(
            category="Pocket", name="human_offtarget", type="CATEGORICAL",
            description="Protein has at least one druggable pocket",
            default_operation="=", default_value="L")[0]
        ScoreParamOptions.objects.get_or_create(score_param=sp, name="High",
                                                description="protein has a significant hit (evalue < 1e-5) against a human protein,"
                                                            "that spans to cover more than 80% of the protein"
                                                )
        ScoreParamOptions.objects.get_or_create(score_param=sp, name="Partial",
                                                description="protein has a significant hit (evalue < 1e-5) against a human protein,"
                                                            " with a length < 40% of the proteins length"
                                                )
        ScoreParamOptions.objects.get_or_create(score_param=sp, name="None",
                                                description="protein has no significant hits (evalue < 1e-5) against a human protein")
        ScoreFormulaParam(formula=sf,operation="=",coefficient=1,value="None",score_param=sp).save()
        ScoreFormulaParam(formula=sf,operation="=",coefficient=-0.5,value="Partial",score_param=sp).save()

        sp = ScoreParam.objects.get_or_create(
            category="Protein", name="resist_mutation", type="CATEGORICAL",
            description="Protein has reported resistance mutation in literature",
            default_operation="=", default_value="N")[0]
        ScoreParamOptions.objects.get_or_create(score_param=sp, name="Y")
        ScoreParamOptions.objects.get_or_create(score_param=sp, name="N")

        ScoreFormulaParam(formula=sf,operation="=",coefficient=1,value="N",score_param=sp).save()

        sp = ScoreParam.objects.get_or_create(
            category="Ligand", name="ligands_literature", type="CATEGORICAL",
            description="Presence of ligands in the literature",
            default_operation="=", default_value="Y")[0]
        ScoreParamOptions.objects.get_or_create(score_param=sp, name="Y")
        ScoreParamOptions.objects.get_or_create(score_param=sp, name="N")

        ScoreFormulaParam(formula=sf,operation="=",coefficient=1,value="Y",score_param=sp).save()

        sp = ScoreParam.objects.get_or_create(
            category="Pocket", name="pocket_with_csa", type="CATEGORICAL",
            description="Pocket intersects with a CSA site",
            default_operation="=", default_value="N")[0]
        ScoreParamOptions.objects.get_or_create(score_param=sp, name="Y")
        ScoreParamOptions.objects.get_or_create(score_param=sp, name="N")

        ScoreFormulaParam(formula=sf,operation="=",coefficient=1,value="Y",score_param=sp).save()

        sp = ScoreParam.objects.get_or_create(
            category="Pocket", name="pocket_with_ppi", type="CATEGORICAL",
            description="Pocket intersects with a PPI site (protein to protein interaction)",
            default_operation="=", default_value="N")[0]
        ScoreParamOptions.objects.get_or_create(score_param=sp, name="Y")
        ScoreParamOptions.objects.get_or_create(score_param=sp, name="N")

        ScoreFormulaParam(formula=sf,operation="=",coefficient=1,value="Y",score_param=sp).save()

        sp = ScoreParam.objects.get_or_create(
            category="Protein", name="vs_hts_in_literature", type="CATEGORICAL",
            description="Protein has a VS (virtual screening) or  "
                        "HTS (High-throughput screening) performed in literature",
            default_operation="=", default_value="N")[0]
        ScoreParamOptions.objects.get_or_create(score_param=sp, name="Y")
        ScoreParamOptions.objects.get_or_create(score_param=sp, name="N")

        ScoreFormulaParam(formula=sf,operation="=",coefficient=1,value="Y",score_param=sp).save()

        sp = ScoreParam.objects.get_or_create(
            category="Protein", name="insilico_simulation_complexity", type="CATEGORICAL",
            description="Soluble domains and small proteins are easier to simulate or perform docking assays than"
                        " membrane or bigger ones",
            default_operation="=", default_value="L")[0]
        ScoreParamOptions.objects.get_or_create(score_param=sp, name="High",
                                                description="Membrane protein (or has membrane domains) and/or"
                                                            " it's sequence is longer than 800aa")
        ScoreParamOptions.objects.get_or_create(score_param=sp, name="Medium",
                                                description="Membrane domain, but at least one soluble domain")
        ScoreParamOptions.objects.get_or_create(score_param=sp, name="Low",
                                                description="no membrane domains")

        ScoreFormulaParam(formula=sf,operation="=",coefficient=1,value="Low",score_param=sp).save()
        ScoreFormulaParam(formula=sf,operation="=",coefficient=-0.5,value="Medium",score_param=sp).save()

        sp = ScoreParam.objects.get_or_create(
            category="Pocket", name="pocket_interspecies_overlap", type="CATEGORICAL",
            description="Some pockets between orthologs overlaps. "
                        "Correspondence between positions is performed by structrual alignment using TM-align",
            default_operation="=", default_value="N")[0]
        ScoreParamOptions.objects.get_or_create(score_param=sp, name="Y",
                                                description="at leart 60% of the residues for each pocket must overlap")
        ScoreParamOptions.objects.get_or_create(score_param=sp, name="N")
        ScoreFormulaParam(formula=sf,operation="=",coefficient=1,value="Y",score_param=sp).save()


class ScoreParamOptions(models.Model):
    score_param = models.ForeignKey(ScoreParam, related_name='choices',
                                    on_delete=models.CASCADE)
    name = CharField(max_length=255)
    description = TextField(max_length=255, default="")

    class Meta:
        unique_together = ('score_param', 'name',)

    def __repr__(self):
        return f'ScoreParamOptions({self.name} - {self.score_param.name})'

    def __str__(self):
        return self.__repr__()
