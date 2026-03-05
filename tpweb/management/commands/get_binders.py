import gzip
import os
import shlex
import subprocess as sp
import time

import pandas as pd
from django.core.management.base import BaseCommand

from bioseq.io.SeqStore import SeqStore

class Command(BaseCommand):

    def add_arguments(self, parser):
        parser.add_argument('genome')
        parser.add_argument('--datadir', default="./")

    def handle(self, *args, **options):
        ubiquitous = {'ZN', 'ATP', 'LEU', 'CA', 'PO4', 'MN', 'PEPTIDE', 'DNA', 'MG', 'FE', 'FE2', 'HG'}

        def download_if_missing(url, output_filename, label):
            if os.path.exists(output_filename):
                return
            curl_command = ["curl", "-L", "-o", output_filename, url]
            print(f"Downloading {label}...")
            result = sp.run(curl_command, capture_output=True, text=True)
            if result.returncode != 0:
                raise RuntimeError(f"Failed to download {label}: {result.stderr}")
            print(f"File '{output_filename}' downloaded.")

        def ensure_databases(datadir):
            biolip_dir = os.path.join(datadir, "biolip")
            os.makedirs(biolip_dir, exist_ok=True)
            download_if_missing(
                "https://zhanggroup.org/BioLiP/download/BioLiP.txt.gz",
                os.path.join(biolip_dir, "BioLiP.txt.gz"),
                "BioLiP",
            )
            download_if_missing(
                "https://files.wwpdb.org/pub/pdb/data/monomers/components.cif",
                os.path.join(biolip_dir, "components.cif"),
                "Chemical Component Dictionary",
            )

        def load_uniprot_to_locus(folder_path, genome):
            path = os.path.join(folder_path, f"{genome}_unips.lst")
            mapping = {}
            with open(path, "r") as handle:
                for raw in handle:
                    parts = raw.strip().split()
                    if len(parts) >= 2:
                        mapping[parts[0]] = parts[1]
            return mapping

        def create_locustag_dataframe(datadir, folder_path, genome):
            bio_lip_path = os.path.join(datadir, "biolip", "BioLiP.txt.gz")
            uniprot_to_locus = load_uniprot_to_locus(folder_path, genome)
            seen_ligands = set()
            rows = []
            with gzip.open(bio_lip_path, "rt") as biolip_file:
                for line in biolip_file:
                    fields = line.rstrip("\n").split("\t")
                    if len(fields) < 18:
                        continue
                    uniprot = fields[17].strip()
                    ligand = fields[4].strip()
                    if uniprot not in uniprot_to_locus:
                        continue
                    if not ligand:
                        continue
                    if ligand.upper() in ubiquitous:
                        continue
                    if ligand in seen_ligands:
                        continue
                    seen_ligands.add(ligand)
                    rows.append(
                        {
                            "Uniprot": uniprot,
                            "Locustag": uniprot_to_locus[uniprot],
                            "PDB ID": fields[0].strip(),
                            "Ligand ID": ligand,
                        }
                    )
            return pd.DataFrame(rows, columns=["Uniprot", "Locustag", "PDB ID", "Ligand ID"])

        def _parse_block_smiles(block_lines):
            name = None
            canonical_smiles = None
            fallback_smiles = None
            i = 0
            while i < len(block_lines):
                line = block_lines[i].strip()
                if line.startswith("_chem_comp.name"):
                    parts = shlex.split(line)
                    if len(parts) >= 2:
                        name = parts[1]
                    i += 1
                    continue
                if line == "loop_":
                    j = i + 1
                    headers = []
                    while j < len(block_lines):
                        header_line = block_lines[j].strip()
                        if header_line.startswith("_"):
                            headers.append(header_line)
                            j += 1
                            continue
                        break
                    if headers and headers[0].startswith("_pdbx_chem_comp_descriptor."):
                        while j < len(block_lines):
                            row = block_lines[j].strip()
                            if not row or row == "#":
                                j += 1
                                continue
                            if row.startswith("loop_") or row.startswith("_"):
                                break
                            values = shlex.split(row)
                            if len(values) >= 5:
                                row_type = values[1]
                                program = values[2].strip('"')
                                descriptor = values[4]
                                if row_type == "SMILES_CANONICAL":
                                    if program == "OpenEye OEToolkits" and canonical_smiles is None:
                                        canonical_smiles = descriptor
                                    elif fallback_smiles is None:
                                        fallback_smiles = descriptor
                            j += 1
                        i = j
                        continue
                    i = j
                    continue
                i += 1
            return name, canonical_smiles or fallback_smiles

        def parse_components_for_ligands(ccd_cif_path, ligands):
            ligands = set(ligands)
            result = {}
            current_block = None
            block_lines = []
            with open(ccd_cif_path, "r", errors="replace") as handle:
                for raw in handle:
                    if raw.startswith("data_"):
                        if current_block in ligands and current_block not in result:
                            name, smiles = _parse_block_smiles(block_lines)
                            result[current_block] = {"Name": name, "Smiles": smiles}
                        current_block = raw.strip()[5:]
                        block_lines = []
                        continue
                    if current_block in ligands:
                        block_lines.append(raw)
                if current_block in ligands and current_block not in result:
                    name, smiles = _parse_block_smiles(block_lines)
                    result[current_block] = {"Name": name, "Smiles": smiles}
            return result

        def get_binders(df, ccd_cif_path):
            if df.empty:
                return pd.DataFrame(columns=["Uniprot", "Locustag", "PDB ID", "Ligand ID", "Name", "Smiles"])
            ligands = set(df["Ligand ID"].dropna().astype(str))
            smiles_map = parse_components_for_ligands(ccd_cif_path, ligands)
            smiles_rows = []
            for ligand in ligands:
                meta = smiles_map.get(ligand, {})
                smiles_rows.append(
                    {
                        "Ligand ID": ligand,
                        "Name": meta.get("Name"),
                        "Smiles": meta.get("Smiles"),
                    }
                )
            smiles_df = pd.DataFrame(smiles_rows, columns=["Ligand ID", "Name", "Smiles"])
            return df.merge(smiles_df, how="left", on="Ligand ID")

        datadir = options["datadir"]
        genome = options["genome"]
        ss = SeqStore(datadir)
        folder_path = ss.db_dir(genome)
        ccd_cif = os.path.abspath(os.path.join(datadir, "biolip", "components.cif"))
        start_time = time.time()

        ensure_databases(datadir)
        locustag = create_locustag_dataframe(datadir, folder_path, genome)
        binders = get_binders(locustag, ccd_cif)
        binders.to_csv(f"{folder_path}/binders.csv", index=False)
        execution_time = time.time() - start_time
        print(f"Execution time: {execution_time:.2f} seconds")




    
