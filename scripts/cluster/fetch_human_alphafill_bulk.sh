#!/usr/bin/env bash
# Stage only requested human canonical models on the login node, never the
# entire multispecies bank. Source: https://alphafill.eu/download
# Usage: bash fetch_human_alphafill_bulk.sh ACCESSIONS.txt [DEST_DIR] [--dry-run]
# Input: one UniProt accession per line, exported from HumanProtein.
set -euo pipefail

if [[ $# -lt 1 || $# -gt 3 || ! -f "$1" ]]; then
    echo "Usage: $0 ACCESSIONS.txt [DEST_DIR] [--dry-run]" >&2
    exit 2
fi
destination="${2:-/storage/home/agutson/human_proteome_raw/alphafill}"
if [[ $# -eq 3 && "$3" != --dry-run ]]; then
    echo "Third argument must be --dry-run" >&2
    exit 2
fi
command -v rsync >/dev/null
filters=$(mktemp)
trap 'rm -f -- "$filters"' EXIT
declare -A shards=()
declare -A accessions=()
selected=0
printf '+ /LICENSE.txt\n' > "$filters"
while IFS= read -r accession || [[ -n "$accession" ]]; do
    accession=${accession%$'\r'}
    [[ -z "$accession" ]] && continue
    if [[ ! "$accession" =~ ^[A-Z0-9]{6}([A-Z0-9]{4})?$ ]]; then
        echo "Invalid UniProt accession: $accession" >&2
        exit 2
    fi
    [[ -n "${accessions[$accession]+present}" ]] && continue
    accessions["$accession"]=1
    selected=$((selected + 1))
    shard=${accession:0:2}
    if [[ -z "${shards[$shard]+present}" ]]; then
        printf '+ /%s/\n' "$shard" >> "$filters"
        shards["$shard"]=1
    fi
    printf '+ /%s/AF-%s-F1-filled_v*.cif.gz\n' "$shard" "$accession" >> "$filters"
    printf '+ /%s/AF-%s-F1-filled_v*.cif.json\n' "$shard" "$accession" >> "$filters"
done < "$1"
if [[ $selected -eq 0 ]]; then
    echo "No accessions supplied; refusing an empty selection" >&2
    exit 2
fi
printf '%s\n' '- *' >> "$filters"
mkdir -p -- "$destination"
options=(-a --prune-empty-dirs --timeout=120 --contimeout=30 --stats)
[[ "${3:-}" == --dry-run ]] && options+=(--dry-run)
echo "AlphaFill: selecting $selected accessions in ${#shards[@]} shards"
rsync "${options[@]}" --filter="merge $filters" \
    rsync://rsync.alphafill.eu/alphafill/ "$destination/"
