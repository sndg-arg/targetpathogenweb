from django.db.models import Q

from bioseq.models.Bioentry import Bioentry
from bioseq.models.Biodatabase import Biodatabase
from bioseq.models.Ontology import Ontology
from tpweb.models.BioentryStructure import BioentryStructure


EC_DBNAMES = {str(Ontology.EC or "").strip(), "ec", "EC"}

def build_assembly_workspace_metrics(assembly_name):
    proteins = Bioentry.objects.filter(
        biodatabase__name=assembly_name + Biodatabase.PROT_POSTFIX
    )

    total_proteins = proteins.count()
    proteins_with_structure = proteins.filter(structures__isnull=False).distinct().count()
    experimental_structures = BioentryStructure.objects.filter(
        bioentry__biodatabase__name=assembly_name + Biodatabase.PROT_POSTFIX
    ).exclude(pdb__experiment="AF").values("bioentry_id").distinct().count()
    alphafold_structures = (
        proteins.filter(structures__pdb__experiment="AF").distinct().count()
    )
    ec_annotated = proteins.filter(dbxrefs__dbxref__dbname__in=EC_DBNAMES).distinct().count()
    go_annotated = proteins.filter(dbxrefs__dbxref__dbname=Ontology.GO).distinct().count()
    functional_annotated = proteins.filter(
        Q(dbxrefs__dbxref__dbname__in=EC_DBNAMES) | Q(dbxrefs__dbxref__dbname=Ontology.GO)
    ).distinct().count()

    return {
        "total_proteins": total_proteins,
        "proteins_with_structure": proteins_with_structure,
        "experimental_structures": experimental_structures,
        "alphafold_structures": alphafold_structures,
        "functional_annotated": functional_annotated,
        "ec_annotated": ec_annotated,
        "go_annotated": go_annotated,
    }
