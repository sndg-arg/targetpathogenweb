from django.test import SimpleTestCase

from human_target.templatetags.human_prose import uniprot_prose


class UniprotProseTests(SimpleTestCase):
    def test_evidence_qualifiers_become_quiet_tags(self):
        html = uniprot_prose("Mediates fusion (By similarity). Binds <ATP> (Probable).\nSecond")
        self.assertIn('fusion <span class="h-evidence">by similarity</span>.', html)
        self.assertIn('<span class="h-evidence">probable</span>', html)
        self.assertIn("&lt;ATP&gt;", html)
        self.assertIn("<br>Second", html)

    def test_other_parentheticals_stay(self):
        self.assertEqual(uniprot_prose("Kinase (EC 2.7.10.1)"), "Kinase (EC 2.7.10.1)")
