#!/usr/bin/env bash
set -euo pipefail

# Usage:
#   ./examples/automation/compress_report.sh ./images ./compressed

INPUT_DIR="${1:-./images}"
OUTPUT_DIR="${2:-./compressed}"

payload="$(pixshift compress "${INPUT_DIR}" -r -p medium --output "${OUTPUT_DIR}" --overwrite --json)"
input_bytes="$(echo "${payload}" | jq -r '.input_bytes // 0')"
output_bytes="$(echo "${payload}" | jq -r '.output_bytes // 0')"
success="$(echo "${payload}" | jq -r '.success // 0')"
failed="$(echo "${payload}" | jq -r '.failed // 0')"

ratio="0"
if [[ "${input_bytes}" -gt 0 ]]; then
  ratio="$(echo "${payload}" | jq -r 'if (.input_bytes // 0) > 0 then ((.output_bytes / .input_bytes) | tostring) else "0" end')"
fi

echo "Compression complete:"
echo "  success=${success}"
echo "  failed=${failed}"
echo "  input_bytes=${input_bytes}"
echo "  output_bytes=${output_bytes}"
echo "  ratio=${ratio}"

