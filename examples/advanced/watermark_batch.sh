#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 3 ]]; then
  echo "usage: $0 <input_dir> <output_dir> <text>"
  exit 1
fi

pixshift watermark text "$1" \
  --text "$3" \
  -r \
  -o "$2" \
  --dry-run \
  --json | jq .

