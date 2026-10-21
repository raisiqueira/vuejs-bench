#!/bin/bash
set -uo pipefail

LOG_DIR=/logs/verifier
mkdir -p "$LOG_DIR"
echo 0 > "$LOG_DIR/reward.txt"

# Restore the official tests and the trusted test configuration over the candidate.
cp -a /tests/files/. /testbed/

cd /testbed/packages/core
./node_modules/.bin/vitest run --config vite.config.ts \
  --reporter=default --reporter=json --outputFile.json="$LOG_DIR/vitest.json" \
  src/Autocomplete/Autocomplete.test.ts 2>&1 | tee "$LOG_DIR/vitest.log"

node /tests/grade.mjs /tests/config.json "$LOG_DIR/vitest.json" "$LOG_DIR"
