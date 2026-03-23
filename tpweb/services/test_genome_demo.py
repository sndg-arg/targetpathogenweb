from django.utils import timezone

from bioseq.models.Bioentry import Bioentry
from bioseq.models.BioentryDbxref import BioentryDbxref
from bioseq.models.Biodatabase import Biodatabase
from bioseq.models.Dbxref import Dbxref
from bioseq.models.Ontology import Ontology
from bioseq.models.Term import Term
from bioseq.models.TermDbxref import TermDbxref
from tpweb.models.BioentryStructure import BioentryStructure
from tpweb.models.pdb import PDB


TEST_GENOME_DEMO_EC_ASSIGNMENTS = (
    (0, "2.7.7.7", "DNA-directed DNA polymerase"),
    (1, "3.6.1.3", "DNA helicase"),
    (2, "1.1.1.100", "3-isopropylmalate dehydrogenase"),
    (3, "2.4.1.1", "Glycogen phosphorylase"),
    (4, "2.7.1.1", "Hexokinase"),
    (5, "2.7.1.69", "Pantothenate kinase"),
    (6, "2.7.11.1", "Protein serine/threonine kinase"),
    (7, "2.4.1.17", "Trehalose-phosphate synthase"),
    (8, "3.6.3.14", "H(+)-transporting ATP synthase"),
    (9, "1.2.1.3", "Glyceraldehyde-3-phosphate dehydrogenase"),
    (10, "4.2.1.11", "Phosphopyruvate hydratase"),
    (11, "6.3.5.5", "Carbamoyl-phosphate synthase"),
    (12, "5.4.2.2", "Phosphoglucomutase"),
    (13, "3.1.3.16", "Phosphoprotein phosphatase"),
    (14, "3.5.4.5", "Cytidine deaminase"),
    (15, "2.1.1.72", "S-adenosylmethionine-dependent methyltransferase"),
    (16, "2.3.1.117", "Glucosamine-1-phosphate N-acetyltransferase"),
    (17, "1.14.13.39", "Nitric-oxide synthase"),
)

TEST_GENOME_DEMO_GO_ASSIGNMENTS = (
    (0, "GO:0003677", "DNA binding"),
    (1, "GO:0005524", "ATP binding"),
    (2, "GO:0016787", "Hydrolase activity"),
    (3, "GO:0000166", "Nucleotide binding"),
    (4, "GO:0004672", "Protein kinase activity"),
    (5, "GO:0003824", "Catalytic activity"),
    (6, "GO:0016491", "Oxidoreductase activity"),
    (7, "GO:0008152", "Metabolic process"),
    (8, "GO:0006412", "Translation"),
    (9, "GO:0006351", "DNA-templated transcription"),
    (10, "GO:0005886", "Plasma membrane"),
    (11, "GO:0005737", "Cytoplasm"),
    (12, "GO:0005829", "Cytosol"),
    (13, "GO:0005576", "Extracellular region"),
    (14, "GO:0005215", "Transporter activity"),
    (15, "GO:0016020", "Membrane"),
    (16, "GO:0004674", "Protein serine/threonine kinase activity"),
    (17, "GO:0016301", "Kinase activity"),
    (18, "GO:0016779", "Nucleotidyltransferase activity"),
    (19, "GO:0004540", "Ribonuclease activity"),
    (20, "GO:0004386", "Helicase activity"),
    (21, "GO:0006260", "DNA replication"),
    (22, "GO:0006270", "DNA replication initiation"),
    (23, "GO:0006810", "Transport"),
    (24, "GO:0008643", "Carbohydrate transport"),
    (25, "GO:0009058", "Biosynthetic process"),
    (26, "GO:0044237", "Cellular metabolic process"),
    (27, "GO:0016740", "Transferase activity"),
    (28, "GO:0005975", "Carbohydrate metabolic process"),
    (29, "GO:0006417", "Regulation of translation"),
    (30, "GO:0005840", "Ribosome"),
    (31, "GO:0032991", "Protein-containing complex"),
)

TEST_GENOME_DEMO_STRUCTURES = (
    ("DEMONG1", "X-ray diffraction", 2.0),
    ("DEMONG2", "Electron microscopy", 3.0),
)


def _demo_proteome_name(assembly_name):
    return f"{assembly_name}{Biodatabase.PROT_POSTFIX}"


def _clear_demo_annotation_links(assembly_name):
    proteome_name = _demo_proteome_name(assembly_name)
    return BioentryDbxref.objects.filter(
        bioentry__biodatabase__name=proteome_name,
        dbxref__dbname__in=(Ontology.EC, "ec", Ontology.GO, "go"),
    ).delete()


def _seed_demo_annotation_assignments(proteins, assignments, dbname):
    links_created = 0
    ontology_name = Ontology.EC if dbname == "ec" else Ontology.GO
    ontology, _ = Ontology.objects.get_or_create(name=ontology_name, defaults={"definition": ""})

    for protein_index, accession, definition in assignments:
        if protein_index >= len(proteins):
            continue

        dbxref, _ = Dbxref.objects.get_or_create(
            dbname=dbname,
            accession=accession,
            defaults={"version": 0},
        )
        _, created = BioentryDbxref.objects.get_or_create(
            bioentry=proteins[protein_index],
            dbxref=dbxref,
            defaults={"rank": 0},
        )
        if created:
            links_created += 1

        term, _ = Term.objects.get_or_create(
            ontology=ontology,
            identifier=accession,
            defaults={
                "name": accession,
                "definition": definition,
                "version": 0,
                "is_obsolete": "N",
            },
        )
        if not term.definition and definition:
            term.definition = definition
            term.save(update_fields=["definition"])
        TermDbxref.objects.get_or_create(term=term, dbxref=dbxref, defaults={"rank": 0})

    return links_created


def seed_test_genome_demo_annotations(assembly_name):
    proteins = list(
        Bioentry.objects.filter(
            biodatabase__name=_demo_proteome_name(assembly_name)
        )
        .order_by("accession")
    )
    _clear_demo_annotation_links(assembly_name)

    demo_structure_codes = [code for code, _, _ in TEST_GENOME_DEMO_STRUCTURES]
    demo_pdbs = list(PDB.objects.filter(code__in=demo_structure_codes))
    if demo_pdbs:
        BioentryStructure.objects.filter(
            bioentry__biodatabase__name=_demo_proteome_name(assembly_name),
            pdb__in=demo_pdbs,
        ).delete()

    experimental_targets = list(
        Bioentry.objects.filter(
            biodatabase__name=_demo_proteome_name(assembly_name),
            structures__isnull=True,
        )
        .order_by("accession")
    )
    if len(experimental_targets) < len(TEST_GENOME_DEMO_STRUCTURES):
        experimental_targets = proteins

    ec_links_created = 0
    go_links_created = 0
    pdb_links_created = 0

    ec_links_created = _seed_demo_annotation_assignments(
        proteins, TEST_GENOME_DEMO_EC_ASSIGNMENTS, "ec"
    )
    go_links_created = _seed_demo_annotation_assignments(
        proteins, TEST_GENOME_DEMO_GO_ASSIGNMENTS, Ontology.GO
    )

    for protein, (code, experiment, resolution) in zip(
        experimental_targets, TEST_GENOME_DEMO_STRUCTURES
    ):
        pdb, _ = PDB.objects.get_or_create(
            code=code,
            deprecated=False,
            defaults={
                "resolution": resolution,
                "experiment": experiment,
                "date": timezone.now(),
                "text": "HEADER    TEST GENOME DEMO STRUCTURE\nEND",
            },
        )
        _, created = BioentryStructure.objects.get_or_create(bioentry=protein, pdb=pdb)
        if created:
            pdb_links_created += 1

    return {
        "assembly_name": assembly_name,
        "proteins_available": len(proteins),
        "ec_links_created": ec_links_created,
        "go_links_created": go_links_created,
        "experimental_structures_created": pdb_links_created,
        "ec_target_count": min(len(proteins), len(TEST_GENOME_DEMO_EC_ASSIGNMENTS)),
        "go_target_count": min(len(proteins), len(TEST_GENOME_DEMO_GO_ASSIGNMENTS)),
        "experimental_target_count": min(len(proteins), len(TEST_GENOME_DEMO_STRUCTURES)),
    }
