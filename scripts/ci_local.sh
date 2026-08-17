#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

gateway_version="$(sed -n 's/^ARG EBUSGATEWAY_VERSION=//p' helianthus/Dockerfile)"
if [[ ! "$gateway_version" =~ ^[0-9a-f]{40}$ ]]; then
  echo "Invalid EBUSGATEWAY_VERSION in helianthus/Dockerfile: ${gateway_version:-<empty>}" >&2
  exit 1
fi

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
python3 -m pytest tests/test_eebus_admin_wrapper.py -q

echo "==> Modbus TCP add-on configuration and lifecycle"
python3 -m pytest \
  tests/test_modbus_runtime_guard.py \
  tests/test_modbus_single_process_lifecycle.py \
  -q

echo "==> gateway parity gate readiness"
python3 -m pytest tests/test_gateway_parity_gate.py -q
python3 scripts/check_gateway_parity_gate.py --artifact scripts/fixtures/gateway_parity_artifact_pass.json --source-ref "$gateway_version" --verify-github

echo "==> rollout guardrails"
python3 scripts/check_rollout_guardrails.py --guardrail helianthus/rollout_guardrails.json --artifact scripts/fixtures/gateway_parity_artifact_pass.json --source-ref "$gateway_version"

echo "==> post-parity enablement tasks"
python3 scripts/run_post_parity_enablement.py --guardrail helianthus/rollout_guardrails.json --artifact scripts/fixtures/gateway_parity_artifact_pass.json --source-ref "$gateway_version" --addon-config helianthus/config.json --smoke-runbook SMOKE_RUNBOOK.md

echo "==> private IPv4 address gate (docs must use placeholders)"
python3 scripts/check_markdown_private_ips.py --self-test
python3 scripts/check_markdown_private_ips.py
