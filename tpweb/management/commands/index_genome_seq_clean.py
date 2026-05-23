import os
import sys
import warnings
import subprocess as sp
import gzip

from Bio.SeqFeature import CompoundLocation
from Bio.bgzf import BgzfWriter
from tqdm import tqdm
import Bio.SeqIO as bpio
from BCBio.GFF.GFFOutput import GFF3Writer, _IdHandler

from django.core.management.base import BaseCommand

from Bio import (
    BiopythonWarning,
    BiopythonParserWarning,
    BiopythonDeprecationWarning,
    BiopythonExperimentalWarning,
)

from SNDG.Annotation.GenebankUtils import GenebankUtils
from bioseq.io.SeqStore import SeqStore
from bioseq.io.GenebankIO import GenebankIO

warnings.simplefilter("ignore", RuntimeWarning)
warnings.simplefilter("ignore", BiopythonWarning)
warnings.simplefilter("ignore", BiopythonParserWarning)
warnings.simplefilter("ignore", BiopythonDeprecationWarning)
warnings.simplefilter("ignore", BiopythonExperimentalWarning)


class Command(BaseCommand):
    """
    Drop-in replacement for index_genome_seq that sanitizes fuzzy GFF bounds (<, >)
    before tabix to avoid TBX_GENERIC parse failures.
    """

    help = "Index genome (with GFF bounds cleaning)"

    def add_arguments(self, parser):
        parser.add_argument("--datadir", default=os.environ.get("BIOSEQDATADIR", "./data"))
        parser.add_argument("accession")

    def handle(self, *args, **options):
        acc = options["accession"]
        seqstore = SeqStore(options["datadir"])
        gbk = seqstore.gbk(acc)

        gbio = GenebankIO(gbk)
        utils = GenebankUtils()
        assert gbio.check(), f"'{gbk}' does not exists!"

        gbio.init(acc)
        genome_fna = seqstore.genome_fna(acc)
        genes_fna = seqstore.genes_fna(acc)
        faa = seqstore.faa(acc)
        gff = seqstore.gff(acc)

        with BgzfWriter(genome_fna) as hf, gzip.open(faa, "wt") as hp, gzip.open(
            genes_fna, "wt"
        ) as hge, BgzfWriter(gff) as hg:
            id_handler, writer = self.create_gff_writer(hg)
            for contig in tqdm(gbio.record_list(), total=gbio.total):
                bpio.write(utils.proteins_from_sequence(contig), hp, "fasta")
                bpio.write(utils.proteins_from_sequence(contig, otype="nucl"), hge, "fasta")
                bpio.write(contig, hf, "fasta")
                self.write_gff_contig(contig, hg, id_handler, writer)

        # Clean fuzzy bounds (<,>) before tabix
        gff_tmp = f"{gff}.tmp.gff"
        fix_cmd = (
            f"bgzip -d -c {gff} | "
            r"""awk 'BEGIN{OFS="\t"} /^#/ {print; next} {gsub(/[<>]/, "", $4); gsub(/[<>]/, "", $5); print}' """
            f"> {gff_tmp} && bgzip -f {gff_tmp} && mv {gff_tmp}.gz {gff}"
        )
        sp.check_call(fix_cmd, shell=True)

        for cmd in [
            f"tabix -p gff {gff}",
            f"samtools faidx {genome_fna}",
            f"zcat {genome_fna} | makeblastdb -dbtype nucl -in - -title {genome_fna} -out {genome_fna}",
            f"zcat {genes_fna} | makeblastdb -dbtype nucl -in - -title {genes_fna} -out {genes_fna}",
            f"zcat {faa} | makeblastdb -dbtype prot -in - -title {faa} -out {faa}",
        ]:
            sys.stderr.write(sp.check_output(cmd, shell=True).decode("utf-8"))

        self.stderr.write("genome sequences indexed (cleaned)!")

    def write_gff_contig(self, contig, hg, id_handler, writer):
        writer._write_rec(contig, hg)
        for sf in sorted(contig.features, key=lambda f: f.location.start):
            sf = writer._clean_feature(sf)
            if "note" in sf.qualifiers:
                sf.qualifiers["note"] = sf.qualifiers.get("gene", sf.qualifiers.get("locus_tag", [""]))[0]
            for ssf in sf.sub_features:
                if "note" in ssf.qualifiers:
                    ssf.qualifiers["note"] = ssf.qualifiers.get("gene", ssf.qualifiers.get("locus_tag", [""]))[0]
            if (
                isinstance(sf.location, CompoundLocation)
                and int(sf.location.start) == 0
                and int(sf.location.end) == len(contig)
                and "locus_tag" in sf.qualifiers
            ):
                continue
            if sf.type not in ["source", "remark"]:
                id_handler = writer._write_feature(sf, contig.id, hg, id_handler)

    def create_gff_writer(self, hg):
        writer = GFF3Writer()
        writer._write_header(hg)
        id_handler = _IdHandler()
        return id_handler, writer
