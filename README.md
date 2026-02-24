# helianthus-ha-addon

`helianthus-ha-addon` is the Home Assistant add-on packaging layer for Helianthus gateway runtime. It runs `helianthus-gateway` in Supervisor and exposes GraphQL/MCP endpoints to Home Assistant operators.

## Purpose and Scope

### What belongs in this repository

- Add-on metadata and options schema (`repository.json`, `helianthus/config.json`).
- Add-on runtime startup wiring (`helianthus/rootfs/run.sh`).
- Add-on image build definition (`helianthus/Dockerfile`).
- Add-on smoke docs/check tooling (`SMOKE_RUNBOOK.md`, `scripts/smoke_addon_checklist.py`).

### What does not belong in this repository

- eBUS transport/protocol implementation (`helianthus-ebusgo`).
- Registry/schema/device semantics (`helianthus-ebusreg`).
- Gateway application logic (`helianthus-ebusgateway`).
- Home Assistant integration entity model (`helianthus-ha-integration`).

## Status and Maturity

- Active add-on packaging repo with CI syntax/docs checks.
- Suitable for practical onboarding and operator runbook usage.
- Runtime behavior is driven by add-on options and upstream gateway capabilities.

## Helianthus Dependency Chain

```text
helianthus-ebusgo -> helianthus-ebusreg -> helianthus-ebusgateway -> helianthus-ha-addon -> Home Assistant Supervisor
  (transport)        (registry/schema)     (runtime/API)             (addon packaging)
```

## Quickstart (copy/paste)

### 0) Prerequisites

- Home Assistant OS or Home Assistant Supervised (Supervisor add-ons enabled).
- Reachable eBUS backend endpoint (`enh` / `ens` / `udp-plain` / `ebusd-tcp`).
- `python3` and `bash` for local docs/check scripts.

### 1) Clone and run local validation checks

```bash
git clone https://github.com/d3vi1/helianthus-ha-addon.git
cd helianthus-ha-addon
./scripts/ci_local.sh
python3 scripts/smoke_addon_checklist.py --help
```

### 2) Add repository to Home Assistant and install

```bash
ha addons repo add https://github.com/d3vi1/helianthus-ha-addon
```

Then install **Helianthus** from the Add-on Store and open add-on configuration.

### 3) Baseline add-on configuration example (local ebusd-tcp)

```yaml
transport: ebusd-tcp
network: tcp
address: 203.0.113.10:9999
source_addr: auto
source_addr_state_file: /data/source_addr.last
proxy_profile: disabled
proxy_endpoint: ""
http_port: 8080
graphql_path: /graphql
subscription_path: /graphql/subscriptions
mcp_path: /mcp
mdns: true
```

### 4) Transition configuration example (adapter-proxy ENH profile)

```yaml
transport: enh
network: tcp
address: 203.0.113.10:9999
adapter_proxy_enabled: true
adapter_proxy_upstream: enh://203.0.113.10:9999
adapter_proxy_port: 19001
adapter_proxy_udp_plain_enabled: true
adapter_proxy_udp_plain_port: 19002
proxy_profile: enh
proxy_endpoint: 127.0.0.1:19001
http_port: 8080
graphql_path: /graphql
subscription_path: /graphql/subscriptions
mcp_path: /mcp
mdns: true
```

### 5) Post-start operator smoke checks

```bash
curl -fsS -X POST "http://127.0.0.1:8080/graphql" \
  -H "content-type: application/json" \
  -d '{"query":"{ __typename }","variables":{}}'

curl -fsS -X POST "http://127.0.0.1:8080/mcp" \
  -H "content-type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}'
```

Deterministic smoke checklist from add-on logs:

```bash
ha addons logs helianthus > /tmp/helianthus-addon.log
python3 scripts/smoke_addon_checklist.py --log-file /tmp/helianthus-addon.log --address 203.0.113.10:9999
```

For full operator sequence and checklist interpretation, use `SMOKE_RUNBOOK.md`.

## Validation Commands

| Area | Command |
|---|---|
| JSON syntax | `python3 -m json.tool repository.json >/dev/null` |
| add-on config syntax | `python3 -m json.tool helianthus/config.json >/dev/null` |
| terminology gate (CI parity) | `if git grep -nIwiE 'm[a]ster|s[l]ave'; then echo "Found legacy terminology."; exit 1; fi` |
| smoke docs gate (CI parity) | `python3 scripts/validate_smoke_docs.py` |
| gateway parity gate readiness | `python3 scripts/check_gateway_parity_gate.py --artifact scripts/fixtures/gateway_parity_artifact_pass.json` |
| rollout guardrails | `python3 scripts/check_rollout_guardrails.py --guardrail helianthus/rollout_guardrails.json --artifact scripts/fixtures/gateway_parity_artifact_pass.json` |
| smoke checker CLI | `python3 scripts/smoke_addon_checklist.py --help` |

## Link Map

### Local docs

- Add-on folder docs: `helianthus/README.md`
- Operator smoke runbook: `SMOKE_RUNBOOK.md`
- Architecture baseline: `ARCHITECTURE.md`
- Repository conventions: `CONVENTIONS.md`
- Agent workflow notes: `AGENT.md`

### Related Helianthus repos/docs

- Gateway runtime: https://github.com/d3vi1/helianthus-ebusgateway
- Registry/schema layer: https://github.com/d3vi1/helianthus-ebusreg
- eBUS transport/protocol layer: https://github.com/d3vi1/helianthus-ebusgo
- HA integration: https://github.com/d3vi1/helianthus-ha-integration
- eBUS docs hub: https://github.com/d3vi1/helianthus-docs-ebus

### Issue workflow conventions

- Use one issue-focused branch per change (example: `issue-32-readme-refresh`).
- Keep PR scope aligned to issue acceptance criteria.
- Include closing keyword in PR body (example: `Fixes #32`).
