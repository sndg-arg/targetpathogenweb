#!/usr/bin/env bash
# Stage only requested human canonical models on the login node, never the
# entire multispecies bank. Source: https://alphafill.eu/download
# Usage: bash fetch_human_alphafill_bulk.sh ACCESSIONS.txt [DEST_DIR] [--dry-run]
# Input: one UniProt accession per line, exported from HumanProtein.
# TPW_ALPHAFILL_VERSIONS optionally overrides the candidate versions (space-separated).
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
selection=$(mktemp)
manifest=$(mktemp)
trap 'rm -f -- "$selection" "$manifest"' EXIT
read -r -a versions <<< "${TPW_ALPHAFILL_VERSIONS:-1 2 3 4 5 6}"
if [[ -z "${versions[*]}" ]]; then
    echo "No AlphaFill versions supplied" >&2
    exit 2
fi
for version in "${versions[@]}"; do
    if [[ ! "$version" =~ ^[1-9][0-9]*$ ]]; then
        echo "Invalid AlphaFill version: $version" >&2
        exit 2
    fi
done
declare -A accessions=()
selected=0
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
    printf '%s\n' "$accession" >> "$selection"
done < "$1"
if [[ $selected -eq 0 ]]; then
    echo "No accessions supplied; refusing an empty selection" >&2
    exit 2
fi
mkdir -p -- "$destination"
options=(-a --ignore-missing-args --timeout=600 --contimeout=30 --stats)
[[ "${3:-}" == --dry-run ]] && options+=(--dry-run)
echo "AlphaFill: selecting $selected accessions; candidate versions: ${versions[*]}"
# Explicit files-from paths avoid listing huge multispecies directories (A0 in
# particular). With --files-from, -a does NOT imply recursion. Batches bound the
# sender's stat work and report progress even when many accessions are absent.
run_batch() {
    LC_ALL=C sort -u -o "$manifest" "$manifest"
    echo "AlphaFill batch $batch/$batches ($processed/$selected accessions)"
    rsync "${options[@]}" --files-from="$manifest" \
        rsync://rsync.alphafill.eu/alphafill/ "$destination/"
    : > "$manifest"
}
batch=1
batches=$(((selected + 499) / 500))
processed=0
printf 'LICENSE.txt\n' > "$manifest"
while IFS= read -r accession; do
    for version in "${versions[@]}"; do
        printf '%s/AF-%s-F1-filled_v%s.cif.gz\n' "${accession:0:2}" "$accession" "$version" >> "$manifest"
        printf '%s/AF-%s-F1-filled_v%s.cif.json\n' "${accession:0:2}" "$accession" "$version" >> "$manifest"
    done
    processed=$((processed + 1))
    if (( processed % 500 == 0 || processed == selected )); then
        run_batch
        batch=$((batch + 1))
    fi
done < "$selection"
echo "AlphaFill: all $batches batches completed ($selected accessions checked)."
