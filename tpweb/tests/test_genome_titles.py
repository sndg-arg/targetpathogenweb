from django.core.cache import cache
from django.test import SimpleTestCase, TestCase

from bioseq.models.Biodatabase import Biodatabase
from tpweb.services.genome_titles import CACHE_KEY, genome_info, parse_genome_title


class ParseGenomeTitleTests(SimpleTestCase):
    def test_organism_and_strain_from_the_genbank_definition(self):
        cases = {
            "Klebsiella pneumoniae subsp. pneumoniae Kp13, complete sequence": (
                "Klebsiella pneumoniae",
                "Kp13",
            ),
            "Klebsiella pneumoniae strain VA569 chromosome, complete genome": (
                "Klebsiella pneumoniae",
                "VA569",
            ),
            "Pseudomonas aeruginosa PAO1, complete genome": ("Pseudomonas aeruginosa", "PAO1"),
            "Neisseria gonorrhoeae strain TUM19854 chromosome, complete genome": (
                "Neisseria gonorrhoeae",
                "TUM19854",
            ),
            "": ("", ""),
            "Incomplete genome workspace": ("", ""),
        }
        for description, expected in cases.items():
            self.assertEqual(parse_genome_title(description), expected, description)


class GenomeInfoTests(TestCase):
    def setUp(self):
        cache.delete(CACHE_KEY)
        self.addCleanup(cache.delete, CACHE_KEY)

    def test_internal_name_gets_title_and_accession_stays_apart(self):
        Biodatabase.objects.create(
            name="public__GCA_030061715.1",
            description="Klebsiella pneumoniae strain VA569 chromosome, complete genome",
        )
        Biodatabase.objects.create(
            name="KpKP13",
            description="Klebsiella pneumoniae subsp. pneumoniae Kp13, complete sequence",
        )

        accession_named = genome_info("GCA_030061715.1")
        self.assertEqual(accession_named["title"], "Klebsiella pneumoniae (VA569)")
        self.assertEqual(accession_named["accession"], "GCA_030061715.1")

        short_named = genome_info("KpKP13")
        self.assertEqual(short_named["title"], "Klebsiella pneumoniae (Kp13)")
        self.assertEqual(short_named["accession"], "")

    def test_unknown_genome_falls_back_to_its_name(self):
        self.assertEqual(genome_info("missing")["title"], "missing")
