#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 2 ]]; then
  echo "usage: $0 <watch_dir> <output_dir>"
  exit 1
fi

pixshift watch "$1" --once -t webp -o "$2" --json | jq .

