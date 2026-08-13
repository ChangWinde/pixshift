#!/usr/bin/env bash
set -euo pipefail

# The agent loop end to end: discover -> plan -> preview -> apply -> verify.
# Nothing is written until the dry run reports a clean plan.
#
# Usage:
#   ./examples/automation/plan_apply_loop.sh ./photos ./optimized

INPUT_DIR="${1:-./photos}"
OUTPUT_DIR="${2:-./optimized}"

# 1. Plan. optimize samples images and probes videos; it never encodes here.
# Exit 1 only means some entries failed to analyse — the payload is still
# valid and the healthy entries are still worth applying. So judge the payload,
# not the exit code: anything without a results array is a real failure.
plan="$(pixshift optimize "${INPUT_DIR}" -r --json)" || true
# Note: `jq -e` exits 0 on *empty* input, so an unset command or a crashed
# process would slip through a parse-only check. Test for content first.
if [[ -z "${plan}" ]] || ! printf '%s' "${plan}" | jq -e '.command == "optimize"' >/dev/null 2>&1; then
  echo "optimize produced no usable plan: ${plan:-<no output>}" >&2
  exit 1
fi
total="$(echo "${plan}" | jq -r '.total // 0')"
if [[ "${total}" -eq 0 ]]; then
  echo "No media found under ${INPUT_DIR}."
  exit 0
fi

# A "keep" plan means re-encoding would not pay off; count it separately so the
# summary distinguishes "nothing to do" from "nothing happened".
actionable="$(echo "${plan}" | jq '[.results[] | select(.plan.command != null and .plan.command != "keep")] | length')"
keep="$(echo "${plan}" | jq '[.results[] | select(.plan.command == "keep")] | length')"
echo "Planned: ${actionable} actionable, ${keep} already optimal, ${total} analysed."

if [[ "${actionable}" -eq 0 ]]; then
  exit 0
fi

# 2. Preview. Validates the vocabulary, output paths and collisions; writes nothing.
preview="$(echo "${plan}" | pixshift apply --plan - --output "${OUTPUT_DIR}" --dry-run --json)"
if [[ "$(echo "${preview}" | jq -r '.ok')" != "true" ]]; then
  echo "Dry run rejected the plan:" >&2
  echo "${preview}" | jq -r '.steps[] | select(.ok == false) | "  \(.input): \(.error)"' >&2
  exit 1
fi

# 3. Apply.
result="$(echo "${plan}" | pixshift apply --plan - --output "${OUTPUT_DIR}" --json)"
echo "Applied: $(echo "${result}" | jq -r '.applied') written, $(echo "${result}" | jq -r '.skipped') skipped."

# 4. Verify. Content hashes make the delivery auditable after the fact.
pixshift hash "${OUTPUT_DIR}" -r --json | jq -r '.files[] | "\(.digest)  \(.path)"'
