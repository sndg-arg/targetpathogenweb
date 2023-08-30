import warnings
from Bio import BiopythonWarning, BiopythonParserWarning, BiopythonDeprecationWarning, BiopythonExperimentalWarning
from django.core.management.base import BaseCommand
from tqdm import tqdm

from bioseq.io.BioIO import BioIO
from bioseq.io.IndexerIO import IndexerIO
from bioseq.models.Biodatabase import Biodatabase
from bioseq.models.BiodatabaseQualifierValue import BiodatabaseQualifierValue
from bioseq.models.BioentryQualifierValue import BioentryQualifierValue
from bioseq.models.Bioentry import Bioentry
from bioseq.models.Ontology import Ontology
from bioseq.models.Term import Term
from tpweb.models.ScoreParam import ScoreParam

warnings.simplefilter('ignore', RuntimeWarning)
warnings.simplefilter('ignore', BiopythonWarning)
warnings.simplefilter('ignore', BiopythonParserWarning)
warnings.simplefilter('ignore', BiopythonDeprecationWarning)
warnings.simplefilter('ignore', BiopythonExperimentalWarning)


class Command(BaseCommand):
    help = 'Index genome'

    def add_arguments(self, parser):
        parser.add_argument('accession')

    def handle(self, *args, **options):
        accession = options['accession']

        biodb = Biodatabase.objects.get(name=accession)
        bioprotdb = accession + BioIO.GENOME_PROT_POSTFIX

        #BiodatabaseQualifierValue.objects.filter(biodatabase=biodb).delete()
        #BioentryQualifierValue.objects.filter(bioentry__biodatabase=biodb).delete()
        #BioentryQualifierValue.objects.filter(bioentry__biodatabase=bioprotdb).delete()
        # Term.objects.filter(ontology__name=Ontology.BIOINDEX).delete()

        ScoreParam.initialize()

        self.index_ontology = Ontology.objects.get_or_create(
            name=Ontology.BIOINDEX, definition="Pre calculated values")[0]

        with tqdm(Bioentry.objects.filter(
                biodatabase__name=bioprotdb,
                structures__isnull=False)) as pbar:
            for i, p in enumerate(pbar):
                pbar.set_description(p.name)
                structure = p.structures.prefetch_related("pdb__residue_sets__residue_set_residue",
                                                          "pdb__residue_sets__residue_set"
                                                          ).all()[0].pdb
                self.process_prot(p,structure)
        self.stderr.write("genome indexed!")

    def process_prot(self,bioentry,structure):
        #['FPocketPocket', 'csa', 'ligand']

        sp = ScoreParam.objects.filter(category="Structure", name="druggability").get()

        for rs in [x for x in structure.residue_sets.all()
                   if x.residue_set.name == "FPocketPocket"] :
            rstype = rs.residue_set.name
            rsname = rs.name
            residues = [x.residue.resid for x in rs.residue_set_residue.all()]



            #print([rstype,rsname,residues])
        """
        t = Term.objects.get_or_create(ontology=self.index_ontology,
                                       identifier="Length")[0]
        v = bioentry.seq.length
        bqv = BioentryQualifierValue(bioentry=bioentry, term=t, value=str(v))
        bqv.save()
        """
