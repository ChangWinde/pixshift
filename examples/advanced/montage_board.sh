#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 2 ]]; then
  echo "usage: $0 <input_dir> <output_png>"
  exit 1
fi

pixshift montage "$1" -o "$2" --cols 4 --json | jq .

