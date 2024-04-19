import csv
import ast
import json
from tpweb.models.Ligand import Ligand
from tpweb.models.Ligand import AccessionLigand
import pandas as pd
from django.db import IntegrityError
from django.core.exceptions import ObjectDoesNotExist
import requests
from json import JSONDecodeError




import os
import shutil
import sys
import traceback
import gzip
import tempfile
import csv
import ast
from Bio.PDB.PDBParser import PDBParser
from Bio.PDB.Polypeptide import is_aa
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from tqdm import tqdm

from bioseq.io.BioIO import BioIO
from bioseq.io.SeqStore import SeqStore
from bioseq.models.Bioentry import Bioentry
from tpweb.models.BioentryStructure import BioentryStructure
from tpweb.models.pdb import PDB, Residue, Atom
import subprocess as sp

import time

def time_decorator(func):
    def wrapper(*args, **kwargs):
        start_time = time.time()
        result = func(*args, **kwargs)
        end_time = time.time()
        print(f"Execution time for {func.__name__}: {end_time - start_time} seconds")
        return result
    return wrapper

def get_ligand_activities(ligand_id):
    tuber='Mycobacterium tuberculosis'
    refs = []
    comp_url = f"https://www.ebi.ac.uk/chembl/api/data/activity?molecule_chembl_id={ligand_id}&target_organism={tuber}&format=json"
    
    try:
        response = requests.get(comp_url)
        response.raise_for_status() # Raises an HTTPError if the response was unsuccessful
        data = response.json()
        for element in data['activities']:
            if element['document_chembl_id'] not in refs:
                refs.append(element['document_chembl_id'])
    except requests.HTTPError as http_err:
        print(f"HTTP error occurred: {http_err}")
    except JSONDecodeError as json_err:
        print(f"JSON decoding error occurred: {json_err}")
        print(f"Raw response: {response.text}")
    except Exception as err:
        print(f"An error occurred: {err}")
        print(f"Raw response: {response.text}")
    return refs


def get_ligand_mechanism(ligand_id):
    tuber='Mycobacterium tuberculosis'
    mec_url = f"https://www.ebi.ac.uk/chembl/api/data/mechanism?molecule_chembl_id={ligand_id}&format=json"
    
    try:
        response = requests.get(mec_url)
        response.raise_for_status() # Raises an HTTPError if the response was unsuccessful
        data = response.json()
        for mecha in data['mechanisms']:
            for refe in mecha['mechanism_refs']:
                print(refe['ref_url'])

    except requests.HTTPError as http_err:
        print(f"HTTP error occurred: {http_err}")
    except JSONDecodeError as json_err:
        print(f"JSON decoding error occurred: {json_err}")
        print(f"Raw response: {response.text}")
    except Exception as err:
        print(f"An error occurred: {err}")
        print(f"Raw response: {response.text}")


class Command(BaseCommand):
    help = 'Loads SMILES data into the database'

    def add_arguments(self, parser):
        parser.add_argument('accession')
        parser.add_argument('ligq_folder')
        parser.add_argument('--comp', action='store_true', help='Skip parsing comp files')
        parser.add_argument('--assay', action='store_true', help='Skip parsing assay files')
        parser.add_argument('--mec', action='store_true', help='Skip parsing mec files')
        parser.add_argument('--pdb', action='store_true', help='Skip parsing pdb files')
        parser.add_argument('--dn', action='store_true', help='Skip parsing dn files')
        parser.add_argument('--tmp', default="/tmp/load_pdb")
        parser.add_argument('--overwrite', action="store_true")
        parser.add_argument('--datadir', default="./data")

    @time_decorator
    @transaction.atomic
    def handle(self, *args, **options):


        # Assignation of parameter and directory pointers.
        seqstore = SeqStore(options['datadir'])
        accession = options['accession']
        ligq_folder = options['ligq_folder']
        json_dict = seqstore.ligand_json(accession, ligq_folder)
        ligand_res_folders = seqstore.ligand_res_folders(accession, ligq_folder)

        # Imports the UniprotID:LocusTag dictionary
        with open(json_dict, 'r') as file:
            data = json.load(file)
        data_list = [{'UniprotID': key, 'LocusTag': value} for key, value in data.items()]
        df = pd.DataFrame(data_list)

        read_files_comp = []
        missing_objects_comp = []
        read_files_assay = []
        missing_objects_assay = []
        read_files_mec = []
        missing_objects_mec = []
        read_files_pdb = []
        missing_objects_pdb = []
        read_files_dn = []
        missing_objects_dn = []
        bioentry_cache = {}
        ligand_cache = {}

        # Iterates over all the results folders
        for index, row in tqdm(df.iterrows(), total=len(df)):
            ligq_protein_folder = os.path.join(ligand_res_folders, row['UniprotID'])

            # Imports data from the chembl_comp.tbl
            if not options['comp']:
                chembl_comp = os.path.join(ligq_protein_folder, 'chembl_comp.tbl')
                with open(chembl_comp, 'r') as comp:
                        comp_lines = comp.readlines()
                        if len(comp_lines) >= 2:
                            for line in tqdm(comp_lines[1:], total=len(comp_lines[1:])):
                                columns = line.split()
                                try:
                                    if row['LocusTag'] not in bioentry_cache:
                                        bioentry_cache[row['LocusTag']] = Bioentry.objects.get(accession=row['LocusTag'])
                                    if columns[1] not in ligand_cache:
                                        ligand_cache[columns[1]] = Ligand.objects.get(ligand_from_key=columns[1])
                                    refe = get_ligand_activities(columns[1])

                                    AccessionLigand.objects.get_or_create(
                                        locus_tag=bioentry_cache[row['LocusTag']], 
                                        reference_type='Chembl_comp', 
                                        ligand= ligand_cache[columns[1]],
                                        reference=refe
                                    )
                                except Exception as e:
                                    missing_objects_comp.append(columns[1])

            # Imports data from the dn_chembl_assay_trusted.lst
            if not options['assay']:
                chembl_assay = os.path.join(ligq_protein_folder, 'dn_chembl_assay_trusted.lst')
                with open(chembl_assay, 'r') as assay:
                    assay_lines = assay.readlines()
                    if assay_lines:
                        for assay_line in tqdm(assay_lines, total=len(assay_lines)):
                            try:
                                if row['LocusTag'] not in bioentry_cache:
                                    bioentry_cache[row['LocusTag']] = Bioentry.objects.get(accession=row['LocusTag'])
                                if assay_line not in ligand_cache:
                                    ligand_cache[assay_line] = Ligand.objects.get(ligand_from_key=assay_line)

                                AccessionLigand.objects.get_or_create(
                                        locus_tag=bioentry_cache[row['LocusTag']], 
                                        reference_type='Chembl_assay', 
                                        ligand=ligand_cache[assay_line],
                                        reference ='Fufa'
                                )

                            except Exception as e:
                                    missing_objects_assay.append(assay_line)

            # Imports data from the dn_chembl_mec_trusted.lst
            if not options['mec']:
                mec_assay = os.path.join(ligq_protein_folder, 'dn_chembl_mec_trusted.lst')
                with open(mec_assay, 'r') as mec:
                    mec_lines = mec.readlines()
                    if mec_lines:
                        for mec_line in tqdm(mec_lines, total=len(mec_lines)):
                            try:
                                if row['LocusTag'] not in bioentry_cache:
                                    bioentry_cache[row['LocusTag']] = Bioentry.objects.get(accession=row['LocusTag'])
                                if mec_line not in ligand_cache:
                                    ligand_cache[mec_line] = Ligand.objects.get(ligand_from_key=mec_line)

                                AccessionLigand.objects.get_or_create(
                                        locus_tag=bioentry_cache[row['LocusTag']], 
                                        reference_type='Chembl_mec', 
                                        ligand=ligand_cache[assay_line],
                                        reference='fifa'
                                )

                            except Exception as e:
                                    missing_objects_mec.append(mec_lines)

            # Imports data from the pdb_ligands.lst
            if not options['pdb']:
                pdb_cristal = os.path.join(ligq_protein_folder, 'pdb_ligands_valid.tbl')
                with open(pdb_cristal, 'r') as pdb:
                    pdb_lines = pdb.readlines()
                    if pdb_lines:
                        for pdb_line in pdb_lines:
                           pdb_ligand = pdb_line.split(" ")[0]                           
                           pdb_reference = pdb_line.split(" ")[4]
                           pdb_reference = pdb_reference.strip()
                           try:
                               read_files_pdb.append(row['UniprotID'])
                               bioentry_instance = Bioentry.objects.get(accession=row['LocusTag'])
                               ligand_instance = Ligand.objects.get(ligand_from_key=pdb_ligand)
                           
                               AccessionLigand.objects.get_or_create(
                                   locus_tag=bioentry_instance, 
                                   reference_type='pdb_cristal', 
                                   ligand=ligand_instance,
                                   reference=pdb_reference
                                   )
                           
                           except Exception as e:
                               missing_objects_pdb.append(pdb_ligand)
            

            # Imports data from the dn_ligands_valid.lst
            if not options['dn']:
                dn = os.path.join(ligq_protein_folder, 'dn_ligands_valid.lst')
                with open(dn, 'r') as dn:
                    dn_lines = dn.readlines()
                    if dn_lines:
                        for dn_line in dn_lines:
                            elements = dn_line.split()
                            if len(elements) == 2:
                                try:
                                    if row['LocusTag'] not in bioentry_cache:
                                        bioentry_cache[row['LocusTag']] = Bioentry.objects.get(accession=row['LocusTag'])
                                    if elements[0] not in ligand_cache:
                                        ligand_cache[elements[0]] = Ligand.objects.get(ligand_from_key=elements[0])

                                    AccessionLigand.objects.get_or_create(
                                            locus_tag=bioentry_cache[row['LocusTag']], 
                                            reference_type='pdb_dn', 
                                            ligand=elements[0],
                                            reference=elements[1]
                                    )

                                except Exception as e:
                                        missing_objects_dn.append(elements[0])

        #self.stdout.write(self.style.SUCCESS(f"Readed Chembl comp files: {read_files_comp}"))
        #if missing_objects_comp:
        #    self.stdout.write(self.style.ERROR(f"Objects not found: {missing_objects_comp}"))

        #self.stdout.write(self.style.SUCCESS(f"Readed Chembl assay files: {read_files_assay}"))
        #if missing_objects_assay:
        #    self.stdout.write(self.style.ERROR(f"Objects not found: {missing_objects_assay}"))

        #self.stdout.write(self.style.SUCCESS(f"Readed Chembl mec files: {read_files_mec}"))
        #if missing_objects_mec:
        #    self.stdout.write(self.style.ERROR(f"Objects not found: {missing_objects_mec}"))