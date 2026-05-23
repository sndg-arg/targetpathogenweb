#!/usr/bin/env python3
"""
Build a CSV index of human UniProt proteins mapped to representative PDB chains.

This script fetches UniProt entries in batch, collects PDB/AlphaFold structure
metadata, and selects one representative structure per protein based on method,
resolution, and coverage.
"""

import argparse
import logging
import os
import sys
import time
import xml.etree.ElementTree as ET
import requests
import pandas as pd
from tqdm import tqdm
from ftscripts import structures

UNIPROT_STREAM_URL = "https://rest.uniprot.org/uniprotkb/stream"
UNIPROT_NAMESPACE = {"up": "http://uniprot.org/uniprot"}
DEFAULT_ALL_CSV = os.path.join("databases", "human_pdb_index_all.csv")


def chunked(items, size):
    for i in range(0, len(items), size):
        yield items[i:i + size]


def fetch_uniprot_ids(proteome_id):
    query = f"(proteome:{proteome_id}) AND reviewed:true"

    params = {
        "format": "tsv",
        "query": query,
        "fields": "accession",
    }

    resp = requests.get(UNIPROT_STREAM_URL, params=params, timeout=60)
    resp.raise_for_status()
    release = (
        resp.headers.get("X-UniProt-Release")
        or resp.headers.get("X-UniProt-Release-Version")
    )

    lines = resp.text.strip().splitlines()
    if not lines:
        return [], release

    ids = []
    for line in lines[1:]:
        parts = line.split("\t")
        if parts and parts[0]:
            ids.append(parts[0].strip())
    return ids, release


def parse_batch_xml(xml_bytes):
    root = ET.fromstring(xml_bytes)
    entries = root.findall("up:entry", UNIPROT_NAMESPACE)
    parsed = {}
    for entry in entries:
        result = structures.parse_uniprot_entry_xml(entry)
        if not result:
            continue
        parsed.update(result)
    return parsed


def ensure_output_dirs(out_all_csv):
    out_dir = os.path.dirname(out_all_csv)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)


def load_existing_index(out_all_csv, proteome_id):
    if not os.path.exists(out_all_csv):
        return None, set()

    df_existing = pd.read_csv(out_all_csv)
    if "proteome_id" not in df_existing.columns:
        df_existing.insert(0, "proteome_id", proteome_id)
    if "uniprot_id" in df_existing.columns:
        processed_ids = set(df_existing["uniprot_id"].dropna().unique())
    else:
        processed_ids = set()

    return df_existing, processed_ids


def sanitize_release_tag(release):
    if not release:
        return None
    return (
        str(release)
        .strip()
        .replace(" ", "_")
        .replace("/", "-")
        .replace("\\", "-")
    )


def with_release_suffix(path, release_tag):
    base, ext = os.path.splitext(path)
    return f"{base}_{release_tag}{ext or '.csv'}"


def normalize_release_filename(path, release_tag):
    base, ext = os.path.splitext(path)
    if base.endswith(f"_{release_tag}"):
        return path

    marker = "_all_"
    if marker in base:
        prefix, _, _ = base.rpartition(marker)
        return f"{prefix}{marker}{release_tag}{ext or '.csv'}"

    return with_release_suffix(path, release_tag)


def write_checkpoint(df, out_all_csv, resolution_cutoff, coverage_cutoff):
    df_with_ref = select_reference_rows(
        df,
        resolution_cutoff=resolution_cutoff,
        coverage_cutoff=coverage_cutoff,
    )
    df_with_ref.to_csv(out_all_csv, index=False)


def select_reference_rows(df, resolution_cutoff, coverage_cutoff):
    df = df.copy()
    df["is_reference"] = False

    for uniprot_id, group in df.groupby("uniprot_id"):
        group_for_choice = group
        if coverage_cutoff is not None:
            filtered = group[group["coverage"].fillna(0) >= coverage_cutoff]
            if not filtered.empty:
                group_for_choice = filtered

        records = []
        for row_index, row in group_for_choice.iterrows():
            rec = row.to_dict()
            rec["_row_index"] = row_index
            records.append(rec)

        selected_idx = structures.select_reference_structure(
            records, resolution_cutoff=resolution_cutoff, 
            coverage_cutoff=coverage_cutoff
        )
        if selected_idx is None:
            continue

        row_index = records[selected_idx]["_row_index"]
        df.loc[row_index, "is_reference"] = True

    return df


def build_index(
    proteome_id,
    out_all_csv,
    ids_file=None,
    batch_size=200,
    resolution_cutoff=3.5,
    coverage_cutoff=40.0,
    max_ids=None,
    sleep_seconds=0,
    checkpoint_every=5,
):
    if ids_file:
        with open(ids_file, "r") as fh:
            uniprot_ids = [line.strip() for line in fh if line.strip()]
        uniprot_release = None
        swissprot_flag = None
    else:
        uniprot_ids, uniprot_release = fetch_uniprot_ids(proteome_id)
        swissprot_flag = True

    if max_ids:
        uniprot_ids = uniprot_ids[:max_ids]

    if not uniprot_ids:
        raise RuntimeError("No UniProt IDs found to process.")

    release_tag = sanitize_release_tag(uniprot_release)
    if release_tag:
        out_all_csv = normalize_release_filename(out_all_csv, release_tag)

    existing_df, processed_ids = load_existing_index(out_all_csv, proteome_id)
    if existing_df is not None and (existing_df.empty or existing_df.dropna(how="all").empty):
        existing_df = None
        processed_ids = set()

    ensure_output_dirs(out_all_csv)
    if existing_df is not None and swissprot_flag is not None:
        if "is_swissprot" not in existing_df.columns:
            existing_df.insert(1, "is_swissprot", swissprot_flag)
        else:
            existing_df["is_swissprot"] = existing_df["is_swissprot"].fillna(swissprot_flag)

    if processed_ids:
        uniprot_ids = [uid for uid in uniprot_ids if uid not in processed_ids]
        logging.info("Resuming from %s (%d UniProt IDs already processed).", out_all_csv, len(processed_ids))

    if not uniprot_ids:
        if existing_df is None:
            raise RuntimeError("No UniProt IDs left to process.")
        write_checkpoint(existing_df, out_all_csv, resolution_cutoff, coverage_cutoff)
        logging.info("No pending IDs; refreshed output CSV.")
        return

    logging.info("Processing %d UniProt IDs", len(uniprot_ids))
    if uniprot_release:
        logging.info("UniProt release: %s", uniprot_release)

    df = existing_df
    total_batches = (len(uniprot_ids) + batch_size - 1) // batch_size
    for batch_idx, batch in enumerate(
        tqdm(
            chunked(uniprot_ids, batch_size),
            total=total_batches,
            desc="UniProt batches",
            unit="batch",
        ),
        start=1,
    ):
        xml_bytes = structures.fetch_uniprot_batch_xml(batch)
        batch_info = parse_batch_xml(xml_bytes)

        batch_rows = []
        for uniprot_id in batch:
            info = batch_info.get(uniprot_id)
            if not info:
                logging.warning("No UniProt entry parsed for %s", uniprot_id)
                continue
            batch_rows.extend(
                structures.collect_structures_for_uniprot(
                    uniprot_id, info, resolution_cutoff=resolution_cutoff,
                    coverage_cutoff=coverage_cutoff,
                )
            )

        if batch_rows:
            batch_df = pd.DataFrame(batch_rows)
            batch_df.insert(0, "proteome_id", proteome_id)
            if swissprot_flag is not None:
                batch_df.insert(1, "is_swissprot", swissprot_flag)
            if df is None or df.empty or df.dropna(how="all").empty:
                df = batch_df
            elif not batch_df.empty and not batch_df.dropna(how="all").empty:
                df = pd.concat([df, batch_df], ignore_index=True)

        if batch_idx % checkpoint_every == 0:
            write_checkpoint(df, out_all_csv, resolution_cutoff, coverage_cutoff)
            logging.info("Checkpoint saved at batch %d/%d.", batch_idx, total_batches)

        if sleep_seconds:
            time.sleep(sleep_seconds)

    if df is None or df.empty:
        raise RuntimeError("No structure rows collected. Check network/API status.")

    write_checkpoint(df, out_all_csv, resolution_cutoff, coverage_cutoff)
    logging.info("Wrote full index to %s", out_all_csv)


def main():
    parser = argparse.ArgumentParser(
        description="Build human UniProt → PDB chain index CSVs",
    )
    parser.add_argument(
        "--proteome-id",
        default="UP000005640",
        help="UniProt proteome ID (default: UP000005640)",
    )
    parser.add_argument(
        "--ids-file",
        default=None,
        help="Optional file with UniProt IDs (one per line)",
    )
    parser.add_argument(
        "--out-all-csv",
        default=DEFAULT_ALL_CSV,
        help="Output CSV with all structures",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=200,
        help="UniProt batch size (max 500 recommended)",
    )
    parser.add_argument(
        "--resolution-cutoff",
        type=float,
        default=3.5,
        help="Resolution cutoff for preferring PDB over AlphaFold",
    )
    parser.add_argument(
        "--coverage-cutoff",
        type=float,
        default=40.0,
        help="Minimum coverage percent to keep PDB candidates",
    )
    parser.add_argument(
        "--max-ids",
        type=int,
        default=None,
        help="Process only first N UniProt IDs (debug)",
    )
    parser.add_argument(
        "--sleep-seconds",
        type=float,
        default=5,
        help="Sleep between batches (polite to UniProt)",
    )
    parser.add_argument(
        "--checkpoint-every",
        type=int,
        default=5,
        help="Write CSV checkpoints every N batches",
    )

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s: %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
    )

    build_index(
        proteome_id=args.proteome_id,
        out_all_csv=args.out_all_csv,
        ids_file=args.ids_file,
        batch_size=args.batch_size,
        resolution_cutoff=args.resolution_cutoff,
        coverage_cutoff=args.coverage_cutoff,
        max_ids=args.max_ids,
        sleep_seconds=args.sleep_seconds,
        checkpoint_every=args.checkpoint_every,
    )


if __name__ == "__main__":
    main()
