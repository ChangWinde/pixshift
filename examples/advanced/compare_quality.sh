#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 2 ]]; then
  echo "usage: $0 <image_a> <image_b>"
  exit 1
fi

pixshift compare "$1" "$2" --json | jq .

