#!/bin/bash
# Gate for each task: the base commit (nop agent) scores 0 and the oracle scores 1
# on every one of RUNS attempts.
#
# Usage: v1.1/scripts/validate.sh [-k RUNS] [TASK_ID ...]
set -uo pipefail

V11_DIR="$(cd "$(dirname "$0")/.." && pwd)"
RUNS=5
if [ "${1:-}" = "-k" ]; then
  RUNS="$2"
  shift 2
fi

if [ "$#" -gt 0 ]; then
  TASK_IDS=("$@")
else
  TASK_IDS=()
  for dir in "$V11_DIR"/tasks/*/; do
    TASK_IDS+=("$(basename "$dir")")
  done
fi

STAMP="$(date +%Y%m%d-%H%M%S)"
JOBS_DIR="$V11_DIR/jobs/validate-$STAMP"
SUMMARY="$JOBS_DIR/summary.tsv"
mkdir -p "$JOBS_DIR"
printf 'task\tcheck\ttrials\terrors\trewards\tstatus\n' > "$SUMMARY"

# Prints "<trials> <errors> <comma-separated rewards>" for a finished job.
job_stats() {
  jq -r '
    .stats.evals | to_entries[0].value as $eval
    | [ $eval.reward_stats.reward // {} | to_entries[] | .key as $r | .value[] | $r ] as $rewards
    | "\($eval.n_trials) \($eval.n_errors) \($rewards | join(","))"
  ' "$1/result.json"
}

run_check() {
  local task_id="$1" check="$2" agent="$3" attempts="$4" expected="$5"
  local job_name="$task_id-$check"

  harbor run -p "$V11_DIR/tasks/$task_id" -a "$agent" -k "$attempts" \
    -o "$JOBS_DIR" --job-name "$job_name" -y -q > "$JOBS_DIR/$job_name.log" 2>&1

  local trials errors rewards status=PASS
  read -r trials errors rewards <<< "$(job_stats "$JOBS_DIR/$job_name" 2>/dev/null || echo "0 0 ")"
  if [ "$trials" != "$attempts" ] || [ "$errors" != "0" ]; then
    status=FAIL
  fi
  IFS=',' read -r -a values <<< "$rewards"
  if [ "${#values[@]}" != "$attempts" ]; then
    status=FAIL
  fi
  for value in "${values[@]}"; do
    [ "$value" = "$expected" ] || status=FAIL
  done

  printf '%s\t%s\t%s\t%s\t%s\t%s\n' \
    "$task_id" "$check" "$trials" "$errors" "${rewards:--}" "$status" | tee -a "$SUMMARY"
  [ "$status" = PASS ]
}

failed=0
for task_id in "${TASK_IDS[@]}"; do
  run_check "$task_id" base nop 1 0.0 || failed=1
  run_check "$task_id" oracle oracle "$RUNS" 1.0 || failed=1
done

echo
column -t -s $'\t' "$SUMMARY"
echo "Jobs: $JOBS_DIR"
exit "$failed"
