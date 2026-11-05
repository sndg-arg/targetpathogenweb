import warnings
from collections import defaultdict

from Bio import (
    BiopythonWarning,
    BiopythonParserWarning,
    BiopythonDeprecationWarning,
    BiopythonExperimentalWarning,
)
from django.db import transaction
from tqdm import tqdm

from tpweb.models.pdb import (
    PDB,
    Property,
    PDBResidueSet,
    ResidueSet,
    ResidueSetProperty,
    ResidueSetResidue,
    AtomResidueSet,
    Residue,
    Atom,
)

warnings.simplefilter("ignore", RuntimeWarning)
warnings.simplefilter("ignore", BiopythonWarning)
warnings.simplefilter("ignore", BiopythonParserWarning)
warnings.simplefilter("ignore", BiopythonDeprecationWarning)
warnings.simplefilter("ignore", BiopythonExperimentalWarning)

fpocket_properties_map = {
    "polar_sasa": "Polar SASA",
    "number_of_alpha_spheres": "Number of Alpha Spheres",
    "apolar_alpha_sphere_proportion": "Apolar alpha sphere proportion",
    "alpha_sphere_density": "Alpha sphere density",
    "charge_score": "Charge score",
    "mean_local_hydrophobic_density": "Mean local hydrophobic density",
    "total_sasa": "Total SASA",
    "volume": "Volume",
    "proportion_of_polar_atoms": "Proportion of polar atoms",
    "flexibility": "Flexibility",
    "score": "Score",
    "hydrophobicity_score": "Hydrophobicity score",
    "apolar_sasa": "Apolar SASA",
    "volume_score": "Volume score",
    "cent_of_mass___alpha_sphere_max_dist": "Cent of mass - Alpha Sphere max dist",
    "polarity_score": "Polarity score",
    "mean_alp_sph_solvent_access": "Mean alp sph solvent access",
    "druggability_score": "Druggability Score",
    "mean_alpha_sphere_radius": "Mean alpha sphere radius",
}
p2rank_properties_map = {"p2score": "P2Rank score", "probability": "P2Rrank probability"}
pocket_prop_map = {v: k for k, v in fpocket_properties_map.items()}
p2pocket_prop_map = {v: k for k, v in p2rank_properties_map.items()}


class Struct:
    def __init__(self, **entries):
        self.__dict__.update(entries)


class FPocket2SQL:
    def __init__(self):
        self.pocket_props = None
        self.rsfpocker = None
        self.res_pockets = None
        self.pdb = None

    def create_or_get_pocket_properties(self, p2rank=False):
        # Create or get pocket properties as before

        # Check if p2rank flag is True, otherwise use the default name
        rs_name = "FPocketPocket" if not p2rank else "P2RankPocket"
        property_map = fpocket_properties_map if not p2rank else p2rank_properties_map
        # Create or get the residue set with the determined name

        self.pocket_props = {
            name: Property.objects.get_or_create(name=name, description=desc)[0]
            for name, desc in property_map.items()
        }
        self.rsfpocker = ResidueSet.objects.get_or_create(name=rs_name, description="")[0]

    def load_pdb(self, code, p2rank=False):
        # No prefetch: nothing below reads the structure's atoms in memory, and
        # loading every atom of a large assembly made each pocket load slow.
        self.pdb = PDB.objects.get(code=code)
        rs_name = "FPocketPocket" if not p2rank else "P2RankPocket"
        res_name = "STP" if not p2rank else "STP2"
        PDBResidueSet.objects.filter(pdb=self.pdb, residue_set__name=rs_name).delete()
        Residue.objects.filter(pdb=self.pdb, resname=res_name).delete()

    def _process_pocket_alphas(self, pocket, nro_atm, p2=False):
        """Alpha-sphere centres as STP/STP2 pseudo-residues, bulk-inserted:
        one INSERT per table instead of one per sphere."""
        res_alpha = {}
        atom_rows = []
        for stp_line in pocket.as_lines:
            nro_atm += 1
            resid = int(stp_line[22:26])
            if resid not in res_alpha:
                res_alpha[resid] = Residue(
                    pdb=self.pdb,
                    chain=stp_line[22:23],
                    resid=resid,
                    type="",
                    resname="STP2" if p2 else "STP",
                    disordered=1,
                )
            atom_rows.append((resid, nro_atm, stp_line))
        Residue.objects.bulk_create(res_alpha.values())
        Atom.objects.bulk_create(
            Atom(
                residue=res_alpha[resid],
                serial=serial,
                name=stp_line[12:16],
                x=float(stp_line[30:38].strip()),
                y=float(stp_line[38:46].strip()),
                z=float(stp_line[46:54].strip()),
                occupancy=float(stp_line[54:60].strip()),
                bfactor=float(stp_line[60:66].strip()),
                element="",
            )
            for resid, serial, stp_line in atom_rows
        )
        return nro_atm

    def load_pockets(self, p2rank=False):
        rss = []
        # The structure's atoms, fetched once and looked up by serial per
        # pocket. A per-pocket "residue__pdb=... AND serial IN (...)" query took
        # 1-3 s on the shared atom table (human proteome included), dozens of
        # times per structure. Residue ids first, so the lookup uses the
        # atom.residue_id index.
        residue_ids = list(Residue.objects.filter(pdb=self.pdb).values_list("id", flat=True))
        atoms_by_serial = defaultdict(list)
        for atom in Atom.objects.filter(residue_id__in=residue_ids).only(
            "id", "serial", "residue_id"
        ):
            atoms_by_serial[atom.serial].append(atom)
        nro_atm = max(atoms_by_serial, default=0)
        with transaction.atomic():
            for pocket in tqdm(self.res_pockets):
                pocket = Struct(**pocket)
                rs = PDBResidueSet(
                    name=f"{pocket.number}", pdb=self.pdb, residue_set=self.rsfpocker
                )
                rss.append(rs)
                rs.save()
                if not p2rank:
                    nro_atm = self._process_pocket_alphas(pocket, nro_atm, p2=p2rank)

                atoms = [
                    atom
                    for serial in {int(x) for x in pocket.atoms}
                    for atom in atoms_by_serial.get(serial, ())
                ]
                # Bulk inserts (Postgres returns the new ids, which the atom
                # links below need): one query per table, not one per row.
                rs_dict = {
                    residue_id: ResidueSetResidue(residue_id=residue_id, pdbresidue_set=rs)
                    for residue_id in {atom.residue_id for atom in atoms}
                }
                ResidueSetResidue.objects.bulk_create(rs_dict.values())
                AtomResidueSet.objects.bulk_create(
                    AtomResidueSet(atom=atom, pdb_set=rs_dict[atom.residue_id]) for atom in atoms
                )
                prop_map = pocket_prop_map if not p2rank else p2pocket_prop_map
                ResidueSetProperty.objects.bulk_create(
                    ResidueSetProperty(
                        pdbresidue_set=rs, property=self.pocket_props[prop_map[k]], value=v
                    )
                    for k, v in pocket.properties.items()
                )
