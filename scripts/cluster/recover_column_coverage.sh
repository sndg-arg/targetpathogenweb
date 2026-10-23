#!/usr/bin/env bash
# Reuse loaded evidence only; run on nodo0 from the repository checkout.
set -euo pipefail

genome=${1:?Usage: recover_column_coverage.sh INTERNAL_GENOME USER_EMAIL}
account=${2:?Pass the account whose columns should be audited}
repo=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)
python_bin=/opt/conda/envs/tpv2/bin/python
queue=target2_nodo0_queue
web=target2_nodo0_web
cd "$repo"

# One recovery at a time for this genome. No existing processes are stopped.
lock_name=${genome//[^a-zA-Z0-9_.-]/_}
exec 9>"/tmp/tpw-column-recovery-${lock_name}.lock"
flock -n 9 || { echo "A recovery for this genome is already running." >&2; exit 1; }

for file in \
  tpweb/management/commands/index_p2rank_scores.py \
  tpweb/management/commands/index_colabfold_scores.py \
  tpweb/management/commands/load_verified_colabfold_model.py \
  tpweb/management/commands/recover_microbiome_counts.py \
  tpweb/management/commands/recover_cached_functional_annotations.py \
  tpweb/management/commands/fast_command.py \
  tpweb/management/commands/index_pocket_size_outlier.py \
  tpweb/management/commands/index_pocket_consensus.py \
  tpweb/management/commands/druggability_2_csv.py \
  tpweb/management/commands/protein_column_coverage.py \
  tpweb/services/score_params.py \
  tpweb/services/microbiome_counts.py \
  tpweb/services/shared_sequence_evidence.py \
  tpweb/services/protein_annotations.py \
  tpweb/services/protein_list.py
do
  for container in "$queue" "$web"; do
    docker cp "$file" "$container:/app/targetpathogenweb/$file"
  done
done
docker restart "$web"

failures=0
# Known background jobs: fetch only completed original rank-001 models.
# Do not submit or cancel predictions.
if [ "$genome" = public__GCA_030061715.1 ]; then
  ssh_options=(-F /tmp/fakehome/.ssh/config -i /tmp/fakehome/.ssh/id_ed25519_agutson_cluster agutson@cluster.qb.fcen.uba.ar)
  while read -r locus job remote_pdb; do
    printf '\n[%s] Checking completed ColabFold %s (job %s)\n' "$(date -Is)" "$locus" "$job"
    if ! state=$(docker exec "$queue" ssh "${ssh_options[@]}" sacct -n -X -j "$job" -P --format=State); then
      failures=$((failures + 1))
      continue
    fi
    state=$(printf '%s\n' "$state" | head -1 | tr -d '[:space:]|')
    if [ "$state" != COMPLETED ]; then
      printf 'Skipping %s: remote state is %s\n' "$locus" "$state"
      continue
    fi
    download=$(mktemp "/tmp/tpw-colabfold-${locus}.XXXXXX")
    if docker exec "$queue" ssh "${ssh_options[@]}" "cat '$remote_pdb'" >"$download"; then
      target="/tmp/tpw-completed-${locus}.pdb"
      if docker cp "$download" "$queue:$target" && docker exec "$queue" "$python_bin" manage.py load_verified_colabfold_model "$genome" "$locus" "$target" --apply; then
        printf 'Completed model processed: %s\n' "$locus"
      else
        failures=$((failures + 1))
      fi
    else
      failures=$((failures + 1))
    fi
    rm -- "$download"
  done <<'MODELS'
MO417_07015 38094 /home/agutson/tpw_colabfold/public__GCA_030061715_1_MO417_07015_cpu_20261020_135223/output/MO417_07015_unrelaxed_rank_001_alphafold2_ptm_model_1_seed_000.pdb
MO417_17415 38095 /home/agutson/tpw_colabfold/public__GCA_030061715_1_MO417_17415_cpu_20261020_135223/output/MO417_17415_unrelaxed_rank_001_alphafold2_ptm_model_1_seed_000.pdb
MO417_09365 38091 /home/agutson/tpw_colabfold/public__GCA_030061715_1_MO417_09365_cpu_20261020_135222/output/MO417_09365_unrelaxed_rank_001_alphafold2_ptm_model_1_seed_000.pdb
MODELS
fi

for command in recover_cached_functional_annotations recover_microbiome_counts index_p2rank_scores index_colabfold_scores index_pocket_size_outlier index_pocket_consensus
do
  printf '\n[%s] Starting %s\n' "$(date -Is)" "$command"
  extra=()
  case "$command" in
    recover_cached_functional_annotations|recover_microbiome_counts|index_p2rank_scores|index_colabfold_scores) extra=(--apply) ;;
  esac
  if docker exec "$queue" nice -n 10 "$python_bin" manage.py "$command" "$genome" "${extra[@]}"; then
    printf '[%s] Completed %s\n' "$(date -Is)" "$command"
  else
    rc=$?
    failures=$((failures + 1))
    printf '[%s] FAILED %s (exit %s); continuing other independent steps\n' "$(date -Is)" "$command" "$rc" >&2
  fi
done

printf '\nRecovery input inventory (read-only)\n'
if ! docker exec -i "$queue" "$python_bin" - "$genome" <<'PY'
import os, sys
from pathlib import Path

genome = sys.argv[1]
base = Path("/app/targetpathogenweb/data/A_0") / genome
roots = [base, Path("/app/fasttarget/organism") / genome]
blocked = {"alphafold", "structures_remote", "pdb_sequence_recovery", "colabfold", "ligq_remote", "search_results"}
tokens = ("micro", "offtarget", "metabol", "metacyc", "core", "conserv", "results_table", "network", "presence_absence", "roary")
found = 0
for root in roots:
    if not root.is_dir():
        continue
    for current, dirs, files in os.walk(root):
        dirs[:] = [name for name in dirs if name not in blocked and len(Path(current).relative_to(root).parts) < 4]
        for filename in sorted(files):
            path = Path(current) / filename
            if path.suffix.lower() not in {".tsv", ".csv", ".sbml", ".xml", ".sif"} or not (path.suffix.lower() in {".sbml", ".sif"} or any(token in filename.lower() for token in tokens)):
                continue
            print(f"FILE {path} ({path.stat().st_size} bytes)")
            with path.open(encoding="utf-8", errors="replace") as handle:
                print("HEADER", handle.readline(1200).strip())
            found += 1
            if found >= 50:
                print("Inventory capped at 50 files; inspect remaining files separately.")
                raise SystemExit(0)
if not found:
    print("No additional matching recovery inputs found in the scoped genome directories.")
PY
then
  failures=$((failures + 1))
fi

printf '\n[%s] Final coverage report\n' "$(date -Is)"
if ! docker exec "$queue" "$python_bin" manage.py protein_column_coverage "$genome" --user "$account"; then
  failures=$((failures + 1))
fi
if [ "$failures" -ne 0 ]; then
  printf '\nRecovery finished with %s failed steps; review the errors above.\n' "$failures" >&2
  exit 1
fi
printf '\nRecovery complete. Existing values were preserved; unavailable evidence remains empty.\n'
