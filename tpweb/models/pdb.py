from datetime import datetime

from bioseq.models.Taxon import Taxon
from django.db import models


class PDB(models.Model):
    id = models.AutoField(primary_key=True)
    code = models.CharField(max_length=100)
    resolution = models.FloatField(default=20)
    experiment = models.CharField(max_length=100, null=True)
    taxon = models.ForeignKey(Taxon, models.SET_NULL, related_name="structures", null=True)
    deprecated = models.BooleanField(default=False)
    date = models.DateTimeField(default=datetime.now)
    text = models.TextField()

    class Meta:
        unique_together = (('code', 'deprecated'),)

    def __str__(self):
        return self.code

    def lines(self):
        # http://www.wwpdb.org/documentation/file-format-content/format33/sect9.html#ATOM
        # http://www.wwpdb.org/documentation/file-format-content/format33/sect9.html#HETATM
        lines = []
        for r in self.residues.all():
            lines += r.lines()
        return lines


class Residue(models.Model):
    HETATOM = 'H'
    ATOM = 'A'

    id = models.AutoField(primary_key=True)
    pdb = models.ForeignKey(PDB, related_name='residues',
                            db_column="pdb_id", on_delete=models.CASCADE)
    # chain = CustomBinaryCharField(max_length=20)
    chain = models.CharField(max_length=20)
    resname = models.CharField(max_length=4)
    resid = models.IntegerField()
    icode = models.CharField(max_length=2, default="")

    type = models.CharField(max_length=10)
    disordered = models.BooleanField(default=False)

    modelable = models.BooleanField(default=True)
    seq_order = models.IntegerField(null=True)

    def lines(self):
        return [a.line(self) for a in self.atoms.all()]

    def __str__(self):
        return self.pdb.code + "_" + self.chain + ":" + str(self.resid) + "-" + self.resname

    class Meta:
        unique_together = (('pdb', "chain", "resid", "icode", "type", "resname"),)


class Atom(models.Model):
    id = models.AutoField(primary_key=True)

    serial = models.IntegerField()
    name = models.CharField(max_length=50)
    altLoc = models.CharField(max_length=1, default=" ")

    residue = models.ForeignKey(Residue, related_name='atoms',
                                db_column="residue_id", on_delete=models.CASCADE)
    x = models.FloatField()
    y = models.FloatField()
    z = models.FloatField()
    occupancy = models.FloatField()
    bfactor = models.FloatField()
    anisou = models.FloatField(null=True)
    element = models.CharField(max_length=10)

    def __str__(self):
        return str(self.serial) + "-" + self.name + "-" + str(self.residue)

    def line(self, r):
        if r.type == "R":
            line = "ATOM  "  # 1 -  6        Record name   "ATOM  "
        else:
            line = "HETATM"  # 1 -  6        Record name   "ATOM  "

        line += str(self.serial).rjust(5)  # 7 - 11        Integer       serial       Atom  serial number.
        if r.resname == "STP":
            line += " "
            line += self.name.strip().ljust(4)  # 13 - 16        Atom          name         Atom name.
        else:
            line += "  "
            line += self.name.ljust(3)  # 13 - 16        Atom          name         Atom name.
        line += self.altLoc  # 17             Character     altLoc       Alternate location indicator.

        line += r.resname.rjust(3)  # 18 - 20        Residue name  resName      Residue name.
        line += " "
        line += r.chain  # 22             Character     chainID      Chain identifier.
        line += str(r.resid).rjust(4)  # 23 - 26        Integer       resSeq       Residue sequence number.
        line += r.icode.rjust(
            4)  # 27             AChar         iCode        Code for insertion of residues.
        line += ("%.3f" % self.x).rjust(
            8)  # 31 - 38        Real(8.3)     x            Orthogonal coordinates for X in Angstroms.
        line += ("%.3f" % self.y).rjust(
            8)  # 39 - 46        Real(8.3)     y            Orthogonal coordinates for Y in Angstroms.
        line += ("%.3f" % self.z).rjust(
            8)  # 47 - 54        Real(8.3)     z            Orthogonal coordinates for Z in Angstroms.
        line += ("%.2f" % self.occupancy).rjust(6)  # 55 - 60        Real(6.2)     occupancy    Occupancy.
        line += ("%.2f" % self.bfactor).rjust(
            6)  # 61 - 66        Real(6.2)     tempFactor   Temperature  factor.
        line += "".rjust(10)
        line += self.element.rjust(2)  # 77 - 78        LString(2)    element      Element symbol, right-justified.
        line += "  "  # 79 - 80        LString(2)    charge       Charge  on the atom.
        return line

    # class Meta:
    #     unique_together = (('residue', "serial"),)


class ResidueSet(models.Model):
    id = models.AutoField(primary_key=True)
    name = models.CharField(max_length=255)  # Pocket / CSA
    description = models.TextField(blank=True, default="")

    class Meta:
        unique_together = (("name"),)

    def __repr__(self):
        return f'ResidueSet({self.name})'

    def __str__(self):
        return self.__repr__()

class PDBResidueSet(models.Model):
    id = models.AutoField(primary_key=True)
    pdb = models.ForeignKey(PDB, related_name='residue_sets',
                            db_column="pdb_id", on_delete=models.CASCADE)
    residue_set = models.ForeignKey(ResidueSet, related_name='residuesets',
                                    db_column="residueset_id", on_delete=models.CASCADE)
    name = models.CharField(max_length=100, default="")
    description = models.TextField(blank=True, default="")

    class Meta:
        unique_together = (('pdb', "residue_set", "name"),)


class ResidueSetResidue(models.Model):
    id = models.AutoField(primary_key=True)
    residue = models.ForeignKey(Residue, related_name='residue_sets',
                                db_column="residue_id", on_delete=models.CASCADE)
    pdbresidue_set = models.ForeignKey(PDBResidueSet, related_name='residue_set_residue',
                                       db_column="pdbresidueset_id", on_delete=models.CASCADE)

    class Meta:
        unique_together = (('residue', "pdbresidue_set"),)


class AtomResidueSet(models.Model):
    id = models.AutoField(primary_key=True)
    atom = models.ForeignKey(Atom, db_column="atom_id", on_delete=models.CASCADE)
    pdb_set = models.ForeignKey(ResidueSetResidue, related_name='atoms',
                                db_column="residuesetresidue_id", on_delete=models.CASCADE)

    class Meta:
        unique_together = (('pdb_set', "atom"),)


class Property(models.Model):
    id = models.AutoField(primary_key=True)
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True, default="")

    class Meta:
        unique_together = (('name'),)


class PropertyTag(models.Model):
    id = models.AutoField(primary_key=True)
    property = models.ForeignKey(Property, related_name='tags',
                                 db_column="residue_id", on_delete=models.DO_NOTHING)
    tag = models.CharField(max_length=50)
    description = models.TextField(blank=True, default="")

    class Meta:
        unique_together = (('property', 'tag'),)


class PDBProperty(models.Model):
    id = models.AutoField(primary_key=True)
    pdb = models.ForeignKey(PDB, related_name='properties',
                            db_column="pdb_id", on_delete=models.CASCADE)
    property = models.ForeignKey(PDB, db_column="property_id", on_delete=models.DO_NOTHING)

    value = models.FloatField(null=True)
    tag = models.ForeignKey(PropertyTag, related_name='pdbs',
                            db_column="propertytag_id", null=True, on_delete=models.DO_NOTHING)

    class Meta:
        unique_together = (('pdb', "property", "tag"),)


class ResidueProperty(models.Model):
    id = models.AutoField(primary_key=True)
    residue = models.ForeignKey(Residue, related_name='properties',
                                db_column="residue_id", on_delete=models.CASCADE)
    property = models.ForeignKey(PDB, db_column="property_id", on_delete=models.DO_NOTHING)
    value = models.FloatField(null=True)
    tag = models.ForeignKey(PropertyTag, related_name='residues',
                            db_column="propertytag_id", null=True, on_delete=models.DO_NOTHING)

    class Meta:
        unique_together = (('residue', "property", "tag"),)


class ResidueSetProperty(models.Model):
    id = models.AutoField(primary_key=True)
    pdbresidue_set = models.ForeignKey(PDBResidueSet, related_name='properties',
                                       db_column="pdbresidueset_id", on_delete=models.CASCADE)
    property = models.ForeignKey(Property, related_name='residuesets', db_column="property_id",
                                 on_delete=models.DO_NOTHING)
    value = models.FloatField(null=True)
    tag = models.ForeignKey(PropertyTag, related_name='residue_sets',
                            db_column="propertytag_id", null=True, on_delete=models.DO_NOTHING)

    class Meta:
        unique_together = (('pdbresidue_set', "property", "tag"),)


class ChainProperty(models.Model):
    id = models.AutoField(primary_key=True)
    pdb = models.ForeignKey(PDB, related_name='chain_props',
                            db_column="pdb_id", on_delete=models.CASCADE)
    chain = models.CharField(max_length=10)
    property = models.ForeignKey(Property, related_name="chains", db_column="property_id", on_delete=models.DO_NOTHING)
    value = models.FloatField(null=True)
    tag = models.ForeignKey(PropertyTag, related_name='chains',
                            db_column="propertytag_id", null=True, on_delete=models.DO_NOTHING)

    class Meta:
        unique_together = (('pdb', "chain", "property", "tag"),)


class AtomProperty(models.Model):
    id = models.AutoField(primary_key=True)
    atom = models.ForeignKey(Atom, related_name='properties',
                             db_column="atom_id", on_delete=models.CASCADE)
    property = models.ForeignKey(Property, db_column="property_id", on_delete=models.DO_NOTHING, related_name="atoms")
    value = models.FloatField(null=True)
    tag = models.ForeignKey(PropertyTag, related_name='atoms',
                            db_column="propertytag_id", null=True, on_delete=models.DO_NOTHING)

    class Meta:
        unique_together = (('atom', "property", "tag"),)
