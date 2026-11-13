from django.test import TestCase

from tpweb.io.FPocket2SQL import FPocket2SQL
from tpweb.models.pdb import (
    PDB,
    Atom,
    AtomResidueSet,
    PDBResidueSet,
    Residue,
    ResidueSetProperty,
    ResidueSetResidue,
)


def _stp_line(serial, resid, x):
    # PDB-format HETATM line for one alpha-sphere centre (fixed columns).
    return (
        f"HETATM{serial:5d}    C STP A{resid:4d}    "
        f"{x:8.3f}{1.0:8.3f}{2.0:8.3f}{0.0:6.2f}{3.5:6.2f}"
    )


class FPocket2SQLLoadTests(TestCase):
    def setUp(self):
        self.pdb = PDB.objects.create(code="AF_TEST1", experiment="AF", text="")
        self.residues = []
        serial = 0
        for resid in (10, 11):
            residue = Residue.objects.create(
                pdb=self.pdb, chain="A", resname="ALA", resid=resid, type="R"
            )
            self.residues.append(residue)
            for name in ("N", "CA"):
                serial += 1
                Atom.objects.create(
                    residue=residue,
                    serial=serial,
                    name=name,
                    x=0,
                    y=0,
                    z=0,
                    occupancy=1,
                    bfactor=0,
                    element="C",
                )

    def test_load_pockets_links_atoms_residues_spheres_and_properties(self):
        loader = FPocket2SQL()
        loader.create_or_get_pocket_properties()
        loader.load_pdb("AF_TEST1")
        loader.res_pockets = [
            {
                "number": 1,
                "atoms": ["1", "2", "3"],
                "as_lines": [_stp_line(5, 1, 1.0), _stp_line(6, 1, 2.0), _stp_line(7, 2, 3.0)],
                "properties": {"Polar SASA": 12.5, "Charge score": 1.0},
            }
        ]

        loader.load_pockets()

        pocket = PDBResidueSet.objects.get(pdb=self.pdb, residue_set__name="FPocketPocket")
        self.assertEqual(pocket.name, "1")
        # Atoms 1-2 sit on residue 10, atom 3 on residue 11.
        self.assertEqual(
            set(
                ResidueSetResidue.objects.filter(pdbresidue_set=pocket).values_list(
                    "residue_id", flat=True
                )
            ),
            {self.residues[0].id, self.residues[1].id},
        )
        self.assertEqual(AtomResidueSet.objects.filter(pdb_set__pdbresidue_set=pocket).count(), 3)
        self.assertEqual(ResidueSetProperty.objects.filter(pdbresidue_set=pocket).count(), 2)
        # Three alpha spheres in two STP pseudo-residues, numbered after the protein atoms.
        spheres = Atom.objects.filter(residue__pdb=self.pdb, residue__resname="STP")
        self.assertEqual(
            Residue.objects.filter(pdb=self.pdb, resname="STP").count(),
            2,
        )
        self.assertEqual(sorted(spheres.values_list("serial", flat=True)), [5, 6, 7])
