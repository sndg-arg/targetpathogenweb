import os.path
import tempfile
import time
import warnings
from io import StringIO

import pandas as pd
import requests
from Bio import (
    BiopythonDeprecationWarning,
    BiopythonExperimentalWarning,
    BiopythonParserWarning,
    BiopythonWarning,
)
from bioseq.io.BioIO import BioIO
from bioseq.io.SeqStore import SeqStore
from bioseq.models.BioentryDbxref import BioentryDbxref
from bioseq.models.BioentryQualifierValue import BioentryQualifierValue
from bioseq.models.Dbxref import Dbxref
from bioseq.models.Ontology import Ontology
from bioseq.models.Term import Term
from django.core.management.base import BaseCommand
from django.db import transaction
from tqdm import tqdm

warnings.simplefilter("ignore", RuntimeWarning)
warnings.simplefilter("ignore", BiopythonWarning)
warnings.simplefilter("ignore", BiopythonParserWarning)
warnings.simplefilter("ignore", BiopythonDeprecationWarning)
warnings.simplefilter("ignore", BiopythonExperimentalWarning)


class Command(BaseCommand):
    help = "Map RefSeq proteins to UniProt with a resilient tpweb override."

    def add_arguments(self, parser):
        parser.add_argument("accession")
        parser.add_argument("--batch_size", type=int, default=10)
        parser.add_argument("--polling_interval", type=int, default=10)
        parser.add_argument("--mapping_tmp", type=str)
        parser.add_argument("--not_mapped", type=str, default="not_mapped.lst")
        parser.add_argument("--datadir", default="./data")

    def _http(self):
        return requests.Session()

    def _submit_job(self, session, ids):
        resp = session.post(
            "https://rest.uniprot.org/idmapping/run",
            data={
                "ids": ",".join(ids),
                "from": "RefSeq_Protein",
                "to": "UniProtKB",
            },
            headers={"User-Agent": "TargetPathogenWeb/1.0"},
            timeout=60,
        )
        resp.raise_for_status()
        payload = resp.json()
        job_id = payload.get("jobId")
        if not job_id:
            raise RuntimeError(f"UniProt idmapping did not return jobId: {payload}")
        return job_id

    def _fetch_results(self, session, job_id):
        resp = session.get(
            f"https://rest.uniprot.org/idmapping/uniprotkb/results/stream/{job_id}",
            params={"format": "tsv"},
            headers={"User-Agent": "TargetPathogenWeb/1.0"},
            timeout=120,
        )
        resp.raise_for_status()
        return resp.text

    def _wait_for_results(self, session, job_id, polling_interval, progress):
        last_status = None
        for _ in range(90):
            resp = session.get(
                f"https://rest.uniprot.org/idmapping/status/{job_id}",
                headers={"User-Agent": "TargetPathogenWeb/1.0"},
                timeout=60,
            )
            resp.raise_for_status()
            payload = resp.json()
            last_status = payload
            job_status = payload.get("jobStatus")
            if job_status in {"RUNNING", "NEW"}:
                progress.set_description(f"Retrying in {polling_interval}s")
                time.sleep(polling_interval)
                continue
            if job_status == "ERROR":
                return None, payload
            # Some API variants stop returning jobStatus once data is ready.
            return self._fetch_results(session, job_id), payload
        return None, last_status or {"jobStatus": "TIMEOUT"}

    def handle(self, *args, **options):
        accession = options["accession"] + BioIO.GENOME_PROT_POSTFIX
        batch_size = max(1, options["batch_size"])
        polling_interval = max(1, options["polling_interval"])

        ss = SeqStore(options["datadir"])
        protein_ids_qs = list(
            BioentryQualifierValue.objects.filter(
                bioentry__biodatabase__name=accession,
                term__identifier="protein_id",
            ).values_list("bioentry__bioentry_id", "value")
        )
        protein_ids_loc = list(
            BioentryQualifierValue.objects.filter(
                bioentry__biodatabase__name=accession,
                term__identifier="protein_id",
            ).values_list("bioentry__accession", "value")
        )

        prot_id_to_bioentry = {protein_id: bioentry_id for bioentry_id, protein_id in protein_ids_qs}
        prot_id_to_locus_tag = {protein_id: locus_tag for locus_tag, protein_id in protein_ids_loc}

        if not options["mapping_tmp"]:
            options["mapping_tmp"] = ss.db_dir(options["accession"]) + "/unips_mapping.csv"

        merged_df = None
        if os.path.exists(options["mapping_tmp"]):
            merged_df = pd.read_csv(options["mapping_tmp"])
        else:
            fd, err_path = tempfile.mkstemp()
            os.close(fd)
            mapping_frames = []
            failed_ids = set()
            session = self._http()
            batch_ranges = range(0, len(protein_ids_qs), batch_size)

            with tqdm(batch_ranges) as progress:
                for i in progress:
                    batch = protein_ids_qs[i:i + batch_size]
                    batch_ids = [protein_id for _, protein_id in batch if protein_id]
                    if not batch_ids:
                        continue
                    try:
                        job_id = self._submit_job(session, batch_ids)
                        tsv_text, status_payload = self._wait_for_results(
                            session, job_id, polling_interval, progress
                        )
                    except Exception as exc:
                        failed_ids.update(batch_ids)
                        self.stderr.write(
                            self.style.WARNING(
                                f"UniProt mapping request failed for batch starting at {i}: {exc}"
                            )
                        )
                        if not mapping_frames:
                            self.stderr.write(
                                self.style.WARNING(
                                    "Stopping UniProt mapping early because the first batch failed and no mappings "
                                    "were recovered. The pipeline will continue with an empty mapping table."
                                )
                            )
                            break
                        continue

                    if not tsv_text:
                        failed_ids.update(batch_ids)
                        self.stderr.write(
                            self.style.WARNING(
                                f"UniProt mapping returned no results for batch starting at {i}: {status_payload}"
                            )
                        )
                        if not mapping_frames:
                            self.stderr.write(
                                self.style.WARNING(
                                    "Stopping UniProt mapping early because the first batch returned no usable data. "
                                    "The pipeline will continue with an empty mapping table."
                                )
                            )
                            break
                        continue

                    batch_df = pd.read_csv(StringIO(tsv_text), sep="\t")
                    if batch_df.empty or "From" not in batch_df.columns:
                        failed_ids.update(batch_ids)
                        self.stderr.write(
                            self.style.WARNING(
                                f"UniProt mapping produced an empty/invalid table for batch starting at {i}."
                            )
                        )
                        if not mapping_frames:
                            self.stderr.write(
                                self.style.WARNING(
                                    "Stopping UniProt mapping early because the first batch produced an empty table. "
                                    "The pipeline will continue with an empty mapping table."
                                )
                            )
                            break
                        continue
                    mapping_frames.append(batch_df)

            if mapping_frames:
                df = pd.concat(mapping_frames, ignore_index=True)
            else:
                df = pd.DataFrame(
                    columns=[
                        "From",
                        "Entry",
                        "Entry Name",
                        "Reviewed",
                        "Protein names",
                        "Gene Names",
                        "Organism",
                        "Length",
                    ]
                )

            merge_df = pd.DataFrame(
                list(prot_id_to_locus_tag.items()),
                columns=["From", "LocusTag"],
            )
            if df.empty:
                merged_df = merge_df.iloc[0:0].copy()
            else:
                merged_df = pd.merge(df, merge_df, on="From", how="left")
            with open(options["mapping_tmp"], "w") as handle:
                merged_df.to_csv(handle, index=False)

            if failed_ids:
                self.stderr.write(
                    self.style.WARNING(
                        f"UniProt mapping skipped {len(failed_ids)} protein ids due to API failures."
                    )
                )

        with transaction.atomic():
            qs = BioentryDbxref.objects.filter(
                bioentry__biodatabase__name=accession,
                dbxref__dbname__in=["UnipSp", "UnipTr", "UnipGene"],
            )
            qs.delete()
            BioentryQualifierValue.objects.filter(
                bioentry__biodatabase__name=accession,
                term__identifier="UnipProtName",
            ).delete()

        unip_list = []
        if merged_df is not None and not merged_df.empty:
            for protein_id, df_prot in tqdm(merged_df.fillna("").groupby("From")):
                bioentry_id = prot_id_to_bioentry.get(protein_id)
                if bioentry_id is None:
                    continue
                df_prot = df_prot.sort_values("Reviewed")
                first = df_prot.iloc[0]
                if first.get("Entry"):
                    unip_list.append(f"{first['Entry']} {first.get('LocusTag', '')}".strip())
                with transaction.atomic():
                    genes = []
                    unips = []
                    for idx, row in df_prot.iterrows():
                        entry = row.get("Entry")
                        if not entry:
                            continue
                        db = "UnipSp" if row.get("Reviewed") == "reviewed" else "UnipTr"
                        unips.append((db, entry))
                        gene_names = str(row.get("Gene Names", "")).split()
                        if gene_names:
                            genes.extend(gene_names)
                        unip_protein_name = Term.objects.get_or_create(
                            identifier="UnipProtName",
                            ontology=Ontology.objects.get_or_create(name=Ontology.ANNTAGS)[0],
                        )[0]
                        BioentryQualifierValue.objects.create(
                            term=unip_protein_name,
                            bioentry_id=bioentry_id,
                            value=row.get("Protein names", ""),
                            rank=idx,
                        )
                    seen_unips = set()
                    for db, unip in unips:
                        if unip in seen_unips:
                            continue
                        dbxrefdb = Dbxref.objects.get_or_create(dbname=db, accession=unip)[0]
                        BioentryDbxref.objects.create(dbxref=dbxrefdb, bioentry_id=bioentry_id)
                        seen_unips.add(unip)

                    for genename in set(genes):
                        dbxrefdb = Dbxref.objects.get_or_create(
                            dbname=Dbxref.UnipGene,
                            accession=genename,
                        )[0]
                        BioentryDbxref.objects.create(dbxref=dbxrefdb, bioentry_id=bioentry_id)

        self.stdout.write("\n".join(unip_list) + ("\n" if unip_list else ""))

        mapped_ids = set(merged_df["From"]) if merged_df is not None and "From" in merged_df.columns else set()
        not_mapped = set(prot_id_to_bioentry) - mapped_ids
        if not_mapped:
            if not options["not_mapped"]:
                options["not_mapped"] = ss.db_dir(options["accession"]) + "/unips_not_mapped.csv"
            self.stderr.write(f"({len(not_mapped)}) ids were not found: {options['not_mapped']}\n")
            with open(options["not_mapped"], "w") as handle:
                handle.write("\n".join(sorted(not_mapped)))
        self.stderr.write("\nuniprot data imported!\n")
