#!/usr/bin/env bash
set -euo pipefail

# Usage:
#   ./examples/automation/pdf_info_export.sh ./report.pdf

PDF_FILE="${1:-./report.pdf}"

payload="$(pixshift pdf info "${PDF_FILE}" --json)"
page_count="$(echo "${payload}" | jq -r '.page_count // 0')"
version="$(echo "${payload}" | jq -r '.pdf_version // ""')"
encrypted="$(echo "${payload}" | jq -r '.encrypted // false')"

echo "PDF info:"
echo "  file=${PDF_FILE}"
echo "  page_count=${page_count}"
echo "  pdf_version=${version}"
echo "  encrypted=${encrypted}"
echo
echo "${payload}" | jq .

