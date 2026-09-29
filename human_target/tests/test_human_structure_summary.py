from django.test import TestCase

from bioseq.models.Biodatabase import Biodatabase
from bioseq.models.Bioentry import Bioentry

from human_target.services.human_structure_summary import build_human_structure_context
from tpweb.models.BioentryStructure import BioentryStructure
from tpweb.models.pdb import PDB, Atom, Residue


class BuildHumanStructureContextTests(TestCase):
    def _make_bioentry(self, accession):
        biodatabase = Biodatabase.objects.create(name="human_curated_prots")
        return Bioentry.objects.create(
            biodatabase=biodatabase, name=accession, accession=accession, identifier=accession
        )

    def _add_residue_with_atoms(self, pdb, chain, resid, resname, restype, atoms):
        residue = Residue.objects.create(
            pdb=pdb, chain=chain, resid=resid, icode="", type=restype, resname=resname
        )
        for index, (name, bfactor) in enumerate(atoms):
            Atom.objects.create(
                residue=residue,
                serial=index + 1,
                name=name,
                x=0.0,
                y=0.0,
                z=0.0,
                occupancy=1.0,
                bfactor=bfactor,
                element="C",
            )
        return residue

    def test_alphafold_entry_gets_mean_plddt_and_ligand_summary(self):
        bioentry = self._make_bioentry("P10721")
        pdb = PDB.objects.create(code="AF_P10721", experiment="AF", text="")
        self._add_residue_with_atoms(pdb, "A", 1, "MET", "R", [("CA", 90.0), ("N", 10.0)])
        self._add_residue_with_atoms(pdb, "A", 2, "LYS", "R", [("CA", 70.0)])
        self._add_residue_with_atoms(pdb, "A", 3, "HOH", "W", [("O", 0.0)])
        self._add_residue_with_atoms(pdb, "A", 4, "ATP", "H_ATP", [("PA", 0.0)])
        BioentryStructure.objects.create(bioentry=bioentry, pdb=pdb, chain="A")

        context = build_human_structure_context(bioentry)

        alphafold_tab = next(tab for tab in context["sub_tabs"] if tab["key"] == "alphafold")
        entry = alphafold_tab["entries"][0]
        self.assertEqual(entry["mean_plddt"], 80.0)
        self.assertEqual(entry["ligands"], [{"comp": "ATP", "chains": ["A"]}])

    def test_alphafill_entry_has_ligands_but_no_plddt(self):
        bioentry = self._make_bioentry("P10721")
        pdb = PDB.objects.create(code="AFILL_P10721", experiment="AFILL", text="")
        self._add_residue_with_atoms(pdb, "A", 1, "MET", "R", [("CA", 50.0)])
        self._add_residue_with_atoms(pdb, "A", 2, "HEM", "H_HEM", [("FE", 0.0)])
        BioentryStructure.objects.create(bioentry=bioentry, pdb=pdb, chain="A")

        context = build_human_structure_context(bioentry)

        alphafill_tab = next(tab for tab in context["sub_tabs"] if tab["key"] == "alphafill")
        entry = alphafill_tab["entries"][0]
        self.assertNotIn("mean_plddt", entry)
        self.assertEqual(entry["ligands"], [{"comp": "HEM", "chains": ["A"]}])
