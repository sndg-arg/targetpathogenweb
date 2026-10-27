import gzip
import tempfile
from pathlib import Path

from django.core.management import call_command
from django.test import SimpleTestCase, TestCase, override_settings

from tpweb.models.LigandReaction import LigandReaction, ligand_smiles_key
from tpweb.services.ligand_reactions import ligand_routes, patent_number, patent_url

LOCMEM = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
HEADER = (
    "ligand_smiles\tdb\tmatch\tsimilarity\treaction_id\treaction_class\treaction_name\t"
    "reactants\treagents\tproduct\n"
)
ROWS = [
    "CC(=O)Oc1ccccc1C(=O)O\tpar2\tsimilar\t0.576\tUS03932466;;1070\t\t\t"
    "CC(=O)OC(C)=O.O=C(O)c1cc(Cl)ccc1O\tO=S(=O)(O)O\tCC(=O)Oc1ccc(Cl)cc1C(=O)O\n",
    "CC(=O)Oc1ccccc1C(=O)O\tus50k\texact\t\tUS04927956\t2\tAcylation\t"
    "CC(=O)Cl.O=C(O)c1ccccc1O\t\tCC(=O)Oc1ccccc1C(=O)O\n",
    # Same reaction as the first row, reported in another patent.
    "CC(=O)Oc1ccccc1C(=O)O\tpar2\tsimilar\t0.576\tUS20020142971A1;0090;39985\t\t\t"
    "CC(=O)OC(C)=O.O=C(O)c1cc(Cl)ccc1O\tO=S(=O)(O)O\tCC(=O)Oc1ccc(Cl)cc1C(=O)O\n",
]


class PatentLinkTests(SimpleTestCase):
    def test_drops_paroutes_suffix_and_leading_zeros(self):
        self.assertEqual(patent_number("US06413981B1;;562059"), "US6413981B1")
        self.assertEqual(patent_number("US20040067202A1"), "US20040067202A1")
        self.assertEqual(patent_number("US20020142971A1;0090;39985"), "US20020142971A1")
        self.assertEqual(patent_url("US04551532"), "https://patents.google.com/patent/US4551532")
        self.assertEqual(patent_url(""), "")


@override_settings(CACHES=LOCMEM)
class LigandReactionLoadTests(TestCase):
    def _load(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "routes.tsv.gz"
            with gzip.open(path, "wt", encoding="utf-8") as handle:
                handle.write(HEADER + "".join(ROWS))
            call_command("load_ligand_reactions", str(path))

    def test_load_replaces_rows_and_routes_list_exact_first(self):
        self._load()
        self._load()
        self.assertEqual(LigandReaction.objects.count(), 3)
        self.assertEqual(
            set(LigandReaction.objects.values_list("smiles_key", flat=True)),
            {ligand_smiles_key("CC(=O)Oc1ccccc1C(=O)O")},
        )

        routes = ligand_routes("CC(=O)Oc1ccccc1C(=O)O")

        self.assertEqual([route["is_exact"] for route in routes], [True, False])
        self.assertEqual(routes[0]["class_label"], "Acylation")
        self.assertEqual(routes[0]["name"], "")
        self.assertEqual(routes[1]["similarity_pct"], 58)
        self.assertEqual(
            [patent["number"] for patent in routes[1]["patents"]],
            ["US3932466", "US20020142971A1"],
        )
        self.assertIn("<svg", routes[0]["svg"])
        self.assertEqual(ligand_routes("CCO"), [])
