#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 2 ]]; then
  echo "usage: $0 <input_dir> <output_dir>"
  exit 1
fi

pixshift crop "$1" --aspect 1:1 -r -o "$2" --overwrite --json | jq .

