from ckeditor_uploader.fields import RichTextUploadingField
from django.db import models
from django.db.models import SmallIntegerField, CharField, TextField


from tpweb.models import TPUser



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
        return self.name

    def to_dict(self):
        return {
            'id': self.pk,  # Primary Key
            'category': self.category,
            'name': self.name,
            'type': self.type,
            'default_operation': self.default_operation,
            'default_value': self.default_value,
            'description': self.description,
        }

    def to_dict(self):
        return {
            'id': self.pk,  # Primary Key
            'category': self.category,
            'name': self.name,
            'type': self.type,
            'default_operation': self.default_operation,
            'default_value': self.default_value,
            'description': self.description,
        }

    @staticmethod
    def initialize():

        from tpweb.models.ScoreFormula import ScoreFormula, ScoreFormulaParam

        ScoreFormula.objects.filter(name__startswith="GARDP").delete()
        ScoreParam.objects.all().delete()

        user = TPUser.objects.filter(username="gardpuser").get()
        sf_to = ScoreFormula(name="GARDP_Target_Overall",user=user,default=True)
        sf_vs = ScoreFormula(name="GARDP_Virtual_Screening",user=user)
        sf_to.save()
        sf_vs.save()



        sp = ScoreParam.objects.get_or_create(
            category="Pocket", name="druggable_pocket", type="CATEGORICAL",
            description="Protein druggable FPocket's count",
            default_operation="=", default_value="M")[0]

        ScoreParamOptions.objects.get_or_create(score_param=sp, name="M",description="more than one druggable pockets")
        ScoreParamOptions.objects.get_or_create(score_param=sp, name="1",description="only one druggable pocket")
        ScoreParamOptions.objects.get_or_create(score_param=sp, name="0",description="no druggable pockets")

        ScoreFormulaParam(formula=sf_to,operation="=",coefficient=2.5,value="M",score_param=sp).save()
        ScoreFormulaParam(formula=sf_to,operation="=",coefficient=2,value="1",score_param=sp).save()
        ScoreFormulaParam(formula=sf_vs,operation="=",coefficient=2.5,value="M",score_param=sp).save()
        ScoreFormulaParam(formula=sf_vs,operation="=",coefficient=2,value="1",score_param=sp).save()

        sp = ScoreParam.objects.get_or_create(
            category="Pocket", name="human_offtarget", type="CATEGORICAL",
            description="Sequence overlaps with human protein?",
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

        ScoreFormulaParam(formula=sf_to,operation="=",coefficient=1,value="None",score_param=sp).save()
        ScoreFormulaParam(formula=sf_to,operation="=",coefficient=-0.5,value="Partial",score_param=sp).save()
        ScoreFormulaParam(formula=sf_to,operation="=",coefficient=-1,value="High",score_param=sp).save()

        ScoreFormulaParam(formula=sf_vs,operation="=",coefficient=1,value="None",score_param=sp).save()
        ScoreFormulaParam(formula=sf_vs,operation="=",coefficient=-0.5,value="Partial",score_param=sp).save()
        ScoreFormulaParam(formula=sf_vs,operation="=",coefficient=-1,value="High",score_param=sp).save()

        sp = ScoreParam.objects.get_or_create(
            category="Pocket", name="Catalytic_residue_in_pocket", type="CATEGORICAL",
            description="Pocket(s) intersect(s) with a catalytic site?",
            default_operation="=", default_value="N")[0]
        ScoreParamOptions.objects.get_or_create(score_param=sp, name="Y")
        ScoreParamOptions.objects.get_or_create(score_param=sp, name="N")

        ScoreFormulaParam(formula=sf_to,operation="=",coefficient=1,value="Y",score_param=sp).save()
        ScoreFormulaParam(formula=sf_vs,operation="=",coefficient=2,value="Y",score_param=sp).save()

        sp = ScoreParam.objects.get_or_create(
            category="Pocket", name="PPI_residue_in_pocket", type="CATEGORICAL",
            description="Pocket(s) overlaps(s) with a protein-protein interaction (PPI) site?",
            default_operation="=", default_value="N")[0]
        ScoreParamOptions.objects.get_or_create(score_param=sp, name="Y")
        ScoreParamOptions.objects.get_or_create(score_param=sp, name="N")

        ScoreFormulaParam(formula=sf_to,operation="=",coefficient=0.5,value="Y",score_param=sp).save()
        ScoreFormulaParam(formula=sf_vs,operation="=",coefficient=0.5,value="Y",score_param=sp).save()

        sp = ScoreParam.objects.get_or_create(
            category="Protein", name="Virtual_Screening_precedence", type="CATEGORICAL",
            description="Pocket was used in previous virtual screen(s) reported in the literature",
            default_operation="=", default_value="N")[0]
        ScoreParamOptions.objects.get_or_create(score_param=sp, name="Y")
        ScoreParamOptions.objects.get_or_create(score_param=sp, name="N")

        #ScoreFormulaParam(formula=sf_to,operation="=",coefficient=1,value="Y",score_param=sp).save()
        ScoreFormulaParam(formula=sf_vs,operation="=",coefficient=1,value="Y",score_param=sp).save()

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

        ScoreFormulaParam(formula=sf_vs,operation="=",coefficient=-2,value="High",score_param=sp).save()
        ScoreFormulaParam(formula=sf_vs,operation="=",coefficient=-1,value="Medium",score_param=sp).save()
        ScoreFormulaParam(formula=sf_vs,operation="=",coefficient=2,value="Low",score_param=sp).save()


        sp = ScoreParam.objects.get_or_create(
            category="Pocket", name="Pocket_KpAb_overlap", type="CATEGORICAL",
            description="Pocket(s) conserved between the Kp and Ab orthologues?",
            default_operation="=", default_value="N")[0]
        ScoreParamOptions.objects.get_or_create(score_param=sp, name="Y",
                                                description="at least 60% of the residues for each pocket must overlap")
        ScoreParamOptions.objects.get_or_create(score_param=sp, name="N")
        ScoreFormulaParam(formula=sf_to,operation="=",coefficient=1,value="Y",score_param=sp).save()
        ScoreFormulaParam(formula=sf_vs,operation="=",coefficient=1,value="Y",score_param=sp).save()


        sp = ScoreParam.objects.get_or_create(
            category="Pocket", name="Ligand-target_crystal_precedence", type="CATEGORICAL",
            description="Pocket(s) overlap(s) with a crystallized binding site containing a drug-like compound ?",
            default_operation="=", default_value="N")[0]
        ScoreParamOptions.objects.get_or_create(score_param=sp, name="Y",
                                                description="at least 60% of the residues for each pocket must overlap")
        ScoreParamOptions.objects.get_or_create(score_param=sp, name="N")


        ScoreFormulaParam(formula=sf_to,operation="=",coefficient=1,value="Y",score_param=sp).save()
        ScoreFormulaParam(formula=sf_vs,operation="=",coefficient=1,value="Y",score_param=sp).save()

        sp = ScoreParam.objects.get_or_create(
            category="Pocket", name="pocket_accessibility", type="CATEGORICAL",
            description="Pocket(s) accessible from?",
            default_operation="=", default_value="N")[0]
        ScoreParamOptions.objects.get_or_create(score_param=sp, name="extracellular_space")
        ScoreParamOptions.objects.get_or_create(score_param=sp, name="periplasm")
        ScoreParamOptions.objects.get_or_create(score_param=sp, name="cytoplasm")
        ScoreParamOptions.objects.get_or_create(score_param=sp, name="inner_membrane")
        ScoreParamOptions.objects.get_or_create(score_param=sp, name="outer_membrane")

        ScoreFormulaParam(formula=sf_to,operation="=",coefficient=2,value="extracellular_space",score_param=sp).save()
        ScoreFormulaParam(formula=sf_to,operation="=",coefficient=1,value="periplasm",score_param=sp).save()
        ScoreFormulaParam(formula=sf_to,operation="=",coefficient=2,value="outer_membrane",score_param=sp).save()
    @staticmethod
    def Initialize_druggability():
        from tpweb.models.ScoreFormula import ScoreFormula, ScoreFormulaParam
        users = TPUser.objects.all()
        for user in users:
            drug_formula = ScoreFormula.objects.get_or_create(name="Druggability",user=user,default=True)
            
        sp = ScoreParam.objects.get_or_create(
            category="Pocket", name="Druggability", type="CATEGORICAL",
            description="Categorical representation of the druggability",
            default_operation="=", default_value="-")[0]
        
        ScoreParamOptions.objects.get_or_create(score_param=sp, name="High",description="Protein with high druggability")
        ScoreParamOptions.objects.get_or_create(score_param=sp, name="Medium",description="Protein with medium druggability")
        ScoreParamOptions.objects.get_or_create(score_param=sp, name="Low",description="Protein with low druggability")
   
        sp = ScoreParam.objects.get(name='Druggability')
        formulas = ScoreFormula.objects.filter(name='Druggability')
        for formula in formulas:
            low = ScoreFormulaParam.objects.get_or_create(formula=formula,operation="=",coefficient=1,value="Low",score_param=sp)
            med = ScoreFormulaParam.objects.get_or_create(formula=formula,operation="=",coefficient=2,value="Medium",score_param=sp)
            hig = ScoreFormulaParam.objects.get_or_create(formula=formula,operation="=",coefficient=3,value="High",score_param=sp)


    @staticmethod
    def Initialize_celular_localization():
        from tpweb.models.ScoreFormula import ScoreFormula, ScoreFormulaParam
        users = TPUser.objects.all()
        for user in users:
            drug_formula = ScoreFormula.objects.get_or_create(name="Localization",user=user,default=True)
            
        sp = ScoreParam.objects.get_or_create(
            category="Localization", name="Localization", type="CATEGORICAL",
            description="Celular localization of the protein",
            default_operation="=", default_value="Unknown")[0]
        
        ScoreParamOptions.objects.get_or_create(score_param=sp, name="Cellwall",description="Protein located in the cellwall")
        ScoreParamOptions.objects.get_or_create(score_param=sp, name="Cytoplasmic",description="Protein located in the citoplasm")
        ScoreParamOptions.objects.get_or_create(score_param=sp, name="CytoplasmicMembrane",description="Protein located in the citoplasmatic membrane")
        ScoreParamOptions.objects.get_or_create(score_param=sp, name="Extracellular",description="Protein located in the extracelular matrix")
        ScoreParamOptions.objects.get_or_create(score_param=sp, name="OuterMembrane",description="Protein located in the outer membrane")
        ScoreParamOptions.objects.get_or_create(score_param=sp, name="Periplasmic",description="Protein located in periplasmatic space")
        ScoreParamOptions.objects.get_or_create(score_param=sp, name="Unknown",description="Protein location not known")

        sp = ScoreParam.objects.get(name='Localization')
        formulas = ScoreFormula.objects.filter(name='Localization')
        for formula in formulas:
            cellwall = ScoreFormulaParam.objects.get_or_create(formula=formula,operation="=",coefficient=1,value="Cellwall",score_param=sp)
            cytoplams = ScoreFormulaParam.objects.get_or_create(formula=formula,operation="=",coefficient=-1,value="Cytoplasmic",score_param=sp)
            cytomembrane = ScoreFormulaParam.objects.get_or_create(formula=formula,operation="=",coefficient=1,value="CytoplasmicMembrane",score_param=sp)
            extracell = ScoreFormulaParam.objects.get_or_create(formula=formula,operation="=",coefficient=2,value="Extracellular",score_param=sp)
            outermembrane = ScoreFormulaParam.objects.get_or_create(formula=formula,operation="=",coefficient=2,value="OuterMembrane",score_param=sp)
            periplasmic = ScoreFormulaParam.objects.get_or_create(formula=formula,operation="=",coefficient=1,value="Periplasmic",score_param=sp)
            unknown = ScoreFormulaParam.objects.get_or_create(formula=formula,operation="=",coefficient=0,value="Unknown",score_param=sp)

    @staticmethod
    def initialize_custom_param(tsv):
        # Ensure the DataFrame has exactly two columns (excluding the index)
        if len(tsv.columns) != 2:
            raise ValueError("The DataFrame should contain exactly two columns.")
        duplicates = tsv[tsv.duplicated(subset='gene', keep=False)]
        sp_options = tsv.iloc[:, 1].unique().tolist()
        sp_name = tsv.columns[1]
        sp = ScoreParam.objects.get_or_create(category="Custom", name=sp_name, type="CATEGORICAL", description="", default_operation="=", default_value="")[0]
        for option in sp_options:
            ScoreParamOptions.objects.get_or_create(score_param=sp, name=option, description="")

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
        return self.name

    def to_dict(self):
        return {
            'id': self.pk,  # Primary Key
            'score_param_id': self.score_param_id,  # Foreign key ID
            'score_param_name': self.score_param.name,  # Related ScoreParam's name
            'name': self.name,
            'description': self.description,
        }
