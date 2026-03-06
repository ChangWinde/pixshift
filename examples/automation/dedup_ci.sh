#!/usr/bin/env bash
set -euo pipefail

# Usage:
#   ./examples/automation/dedup_ci.sh ./assets

TARGET_DIR="${1:-./assets}"

payload="$(pixshift dedup "${TARGET_DIR}" -r --json)"
duplicate_files="$(echo "${payload}" | jq -r '.duplicate_files // 0')"

if [[ "${duplicate_files}" -gt 0 ]]; then
  echo "Duplicate files detected: ${duplicate_files}"
  echo "${payload}" | jq .
  exit 1
fi

echo "No duplicate files detected."
echo "${payload}" | jq .

