#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

echo "==> validate JSON syntax"
found=0
while IFS= read -r file; do
  [ -z "${file}" ] && continue
  found=1
  python3 -m json.tool "${file}" >/dev/null
  echo "OK: ${file}"
done < <(git ls-files '*.json')
if [ "${found}" -eq 0 ]; then
  echo "No JSON files found."
fi

echo "==> validate shell syntax"
found=0
while IFS= read -r file; do
  [ -z "${file}" ] && continue
  found=1
  bash -n "${file}"
  echo "OK: ${file}"
done < <(git ls-files '*.sh')
if [ "${found}" -eq 0 ]; then
  echo "No shell files found."
fi

echo "==> terminology gate"
if git grep -nIwiE 'm[a]ster|s[l]ave'; then
  echo "Found legacy terminology in tracked files."
  exit 1
fi

echo "==> validate smoke runbook structure"
python3 scripts/validate_smoke_docs.py

echo "==> eeBUS HA network proof contract"
python3 scripts/check_eebus_ha_network_proof.py --self-test
python3 scripts/check_eebus_ha_network_proof.py --artifact scripts/fixtures/eebus_ha_network_proof_contract_pass.json --mode contract

echo "==> source address wrapper migration"
python3 scripts/check_source_addr_wrapper.py

echo "==> persistent eeBUS wrapper wiring"
python3 scripts/check_eebus_wrapper.py

echo "==> gateway parity gate readiness"
python3 scripts/check_gateway_parity_gate.py --artifact scripts/fixtures/gateway_parity_artifact_pass.json

echo "==> rollout guardrails"
python3 scripts/check_rollout_guardrails.py --guardrail helianthus/rollout_guardrails.json --artifact scripts/fixtures/gateway_parity_artifact_pass.json

echo "==> post-parity enablement tasks"
python3 scripts/run_post_parity_enablement.py --guardrail helianthus/rollout_guardrails.json --artifact scripts/fixtures/gateway_parity_artifact_pass.json --addon-config helianthus/config.json --smoke-runbook SMOKE_RUNBOOK.md

echo "==> private IPv4 address gate (docs must use placeholders)"
python3 scripts/check_markdown_private_ips.py --self-test
python3 scripts/check_markdown_private_ips.py
