import json
import os
import sys
import warnings

from Bio import BiopythonWarning, BiopythonParserWarning, BiopythonDeprecationWarning, BiopythonExperimentalWarning
from django.db import transaction
from django.db.models import Max

from tpweb.models.pdb import PDB, Property, PDBResidueSet, ResidueSet, ResidueSetProperty, ResidueSetResidue, \
    AtomResidueSet, Residue, Atom

warnings.simplefilter('ignore', RuntimeWarning)
warnings.simplefilter('ignore', BiopythonWarning)
warnings.simplefilter('ignore', BiopythonParserWarning)
warnings.simplefilter('ignore', BiopythonDeprecationWarning)
warnings.simplefilter('ignore', BiopythonExperimentalWarning)

from tqdm import tqdm

fpocket_properties_map = {'polar_sasa': 'Polar SASA', 'number_of_alpha_spheres': 'Number of Alpha Spheres',
                          'apolar_alpha_sphere_proportion': 'Apolar alpha sphere proportion',
                          'alpha_sphere_density': 'Alpha sphere density',
                          'charge_score': 'Charge score',
                          'mean_local_hydrophobic_density': 'Mean local hydrophobic density',
                          'total_sasa': 'Total SASA', 'volume': 'Volume',
                          'proportion_of_polar_atoms': 'Proportion of polar atoms',
                          'flexibility': 'Flexibility', 'score': 'Score',
                          'hydrophobicity_score': 'Hydrophobicity score',
                          'apolar_sasa': 'Apolar SASA', 'volume_score': 'Volume score',
                          'cent_of_mass___alpha_sphere_max_dist': 'Cent of mass - Alpha Sphere max dist',
                          'polarity_score': 'Polarity score',
                          'mean_alp_sph_solvent_access': 'Mean alp sph solvent access',
                          'druggability_score': 'Druggability Score',
                          'mean_alpha_sphere_radius': 'Mean alpha sphere radius'}

pocket_prop_map = {v: k for k, v in fpocket_properties_map.items()}


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
        self.pocket_props = {name: Property.objects.get_or_create(name=name, description=desc)[0]
                             for name, desc in fpocket_properties_map.items()}

        # Check if p2rank flag is True, otherwise use the default name
        rs_name = "FPocketPocket" if not p2rank else "P2RankPocket"

        # Create or get the residue set with the determined name
        self.rsfpocker = ResidueSet.objects.get_or_create(name=rs_name, description="")[0]

    def load_pdb(self, code, p2rank=False):
        self.pdb = PDB.objects.prefetch_related("residues__atoms").get(code=code)
        rs_name = "FPocketPocket" if not p2rank else "P2RankPocket"
        res_name = "STP" if not p2rank else "STP2"
        PDBResidueSet.objects.filter(pdb=self.pdb, residue_set__name=rs_name).delete()
        Residue.objects.filter(pdb=self.pdb, resname=res_name).delete()
    def _process_pocket_alphas(self, pocket, nro_atm, p2 = False):
        res_alpha = {}
        for stp_line in pocket.as_lines:
            print(stp_line)
            nro_atm += 1
            resid = int(stp_line[22:26])
            if resid in res_alpha:
                r = res_alpha[resid]
            else:
                if p2 == False:
                    r = Residue(pdb=self.pdb, chain=stp_line[22:23], resid=resid,
                                type="",
                                resname="STP", disordered=1)
                else:
                     r = Residue(pdb=self.pdb, chain=stp_line[22:23], resid=resid,
                                type="",
                                resname="STP2", disordered=1)                   
                r.save()
                res_alpha[resid] = r
            Atom(residue=r, serial=nro_atm, name=stp_line[12:16],
                 x=float(stp_line[30:38].strip()), y=float(stp_line[38:46].strip()),
                 z=float(stp_line[46:54].strip()),
                 occupancy=float(stp_line[54:60].strip()), bfactor=float(stp_line[60:66].strip()),
                 element="").save()
        return nro_atm

    def load_pockets(self, p2rank = False):
        rss = []
        nro_atm = Atom.objects.filter(residue__pdb=self.pdb).aggregate(Max("serial"))["serial__max"]
        with transaction.atomic():
            for pocket in tqdm(self.res_pockets):
                pocket = Struct(**pocket)
                rs = PDBResidueSet(name="%i" % pocket.number, pdb=self.pdb, residue_set=self.rsfpocker)
                rss.append(rs)
                rs.save()
                nro_atm = self._process_pocket_alphas(pocket, nro_atm, p2 = p2rank)

                atoms = Atom.objects.select_related("residue").filter(residue__pdb=self.pdb,
                                                                      serial__in=[int(x) for x in pocket.atoms])
                residues = set([x.residue for x in atoms])
                rs_dict = {}
                for r in residues:
                    rsr = ResidueSetResidue(residue=r, pdbresidue_set=rs)
                    rsr.save()
                    rs_dict[r.id] = rsr

                for atom in atoms:
                    AtomResidueSet(atom=atom, pdb_set=rs_dict[atom.residue.id]).save()

                for k, v in pocket.properties.items():
                    prop = pocket_prop_map[k]
                    prop_model = self.pocket_props[prop]
                    ResidueSetProperty(pdbresidue_set=rs, property=prop_model, value=v).save()
