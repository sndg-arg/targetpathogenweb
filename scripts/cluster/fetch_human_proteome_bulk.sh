#!/usr/bin/env bash
# One-time bulk download of full-human-proteome source data, run by hand over
# SSH on the cluster's LOGIN node (neocranex), never on nodo0 or a SLURM
# compute node -- mirrors FastTarget's "one-time cluster setup" pattern in
# CLAUDE.md. Not a Django management command: nothing here touches Postgres,
# it just stages raw files on the 2TB IT assigned for this project.
#
# Usage:
#   ssh agutson@cluster.qb.fcen.uba.ar
#   bash fetch_human_proteome_bulk.sh [DEST_DIR]
#
# DEST_DIR defaults to /storage/home/agutson/human_proteome_raw -- kept
# separate from nodo0's /data/targetpathogen/ RAID (shared with every
# bacterial genome, documented "never delete volumes"; this is a disposable
# bulk-download cache, don't mix the two).
#
# After this script finishes, only the per-accession subset Django actually
# needs gets rsync'd down to nodo0 -- see docs/CLUSTER_DEPLOY.md and the
# human_target/management/commands/import_human_proteome_bulk.py docstring.

set -euo pipefail

DEST_DIR="${1:-/storage/home/agutson/human_proteome_raw}"
UNIPROT_PROTEOME_ID="UP000005640"
ALPHAFOLD_ARCHIVE="UP000005640_9606_HUMAN_v6.tar"

mkdir -p "$DEST_DIR/uniprot" "$DEST_DIR/alphafold" "$DEST_DIR/kegg" "$DEST_DIR/bgee"

echo "== UniProt: full reference-proteome bulk JSON (confirmed shape matches" \
     "the single-accession/fixture shape this session) =="
curl -L --fail \
  "https://rest.uniprot.org/uniprotkb/stream?query=proteome:${UNIPROT_PROTEOME_ID}&format=json&compressed=true" \
  -o "$DEST_DIR/uniprot/uniprot_human_proteome.json.gz"
ls -lh "$DEST_DIR/uniprot/uniprot_human_proteome.json.gz"

echo "== AlphaFold DB: bulk per-organism archive (confirmed real this session," \
     "4.8GB, 23,586 structures -- some isoforms/fragments beyond the canonical" \
     "~20,400 accessions, filtered down once the UniProt JSON above is parsed) =="
curl -L --fail \
  "https://ftp.ebi.ac.uk/pub/databases/alphafold/latest/${ALPHAFOLD_ARCHIVE}" \
  -o "$DEST_DIR/alphafold/${ALPHAFOLD_ARCHIVE}"
ls -lh "$DEST_DIR/alphafold/${ALPHAFOLD_ARCHIVE}"
echo "Extracting (this is the slow part -- 23,586 files)..."
mkdir -p "$DEST_DIR/alphafold/extracted"
tar -xf "$DEST_DIR/alphafold/${ALPHAFOLD_ARCHIVE}" -C "$DEST_DIR/alphafold/extracted"

echo "== KEGG: bulk human gene-to-pathway link table (confirmed real this" \
     "session -- one call, every hsa:<gene> -> path:hsa<id> line) =="
curl -L --fail "https://rest.kegg.jp/link/pathway/hsa" \
  -o "$DEST_DIR/kegg/hsa_pathway_links.tsv"
wc -l "$DEST_DIR/kegg/hsa_pathway_links.tsv"

echo "== Bgee: bulk per-species gene-expression-calls TSV =="
echo "NOT AUTOMATED YET -- the exact current download link for Homo sapiens"
echo "was not confirmed this session (the download page returned 403 to an"
echo "automated fetch). Open https://www.bgee.org/download/gene-expression-calls"
echo "by hand, find the Homo sapiens row, and either:"
echo "  (a) add the real URL to this script's Bgee section and re-run, or"
echo "  (b) download it locally and scp it to $DEST_DIR/bgee/ yourself."
echo "Do NOT guess/hardcode a Bgee URL here until confirmed by hand."

echo "== Done. Raw bulk data staged under $DEST_DIR =="
du -sh "$DEST_DIR"/* 2>/dev/null || true
