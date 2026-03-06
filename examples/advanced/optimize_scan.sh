#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "usage: $0 <input_dir_or_file>"
  exit 1
fi

pixshift optimize "$1" -r --json | jq .

