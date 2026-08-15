# helianthus-ha-addon

`helianthus-ha-addon` is the Home Assistant add-on packaging layer for Helianthus gateway runtime. It runs `helianthus-gateway` in Supervisor and exposes GraphQL/MCP endpoints to Home Assistant operators.

The add-on also owns the stable Helianthus instance GUID used by the Home Assistant integration. It persists a lowercase UUIDv4 in `/data/instance_guid`, keeps it across normal restarts and updates, and passes it through to the gateway for GraphQL and mDNS discovery.

## Purpose and Scope

### What belongs in this repository

- Add-on metadata and options schema (`repository.json`, `helianthus/config.json`).
- Add-on runtime startup wiring (`helianthus/rootfs/run.sh`).
- Add-on image build definition (`helianthus/Dockerfile`).
- Add-on smoke docs/check tooling (`SMOKE_RUNBOOK.md`, `scripts/smoke_addon_checklist.py`).
- eeBUS HA runtime network proof tooling for raw-first feasibility
  (`EEBUS_HA_NETWORK_PROOF.md`, `scripts/check_eebus_ha_network_proof.py`).

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
git clone https://github.com/Project-Helianthus/helianthus-ha-addon.git
cd helianthus-ha-addon
./scripts/ci_local.sh
python3 scripts/smoke_addon_checklist.py --help
```

### 2) Add repository to Home Assistant and install

```bash
ha addons repo add https://github.com/Project-Helianthus/helianthus-ha-addon
```

Then install **Helianthus** from the Add-on Store and open add-on configuration.
Release `0.6.46` packages the consolidated gateway with the eeBUS retry-ready
reopen correction and `eebusreg v0.1.33`. It keeps eeBUS-specific credential
options removed, generic Portal and Home Assistant authentication unchanged,
and Modbus disabled by default.

### 3) Baseline add-on configuration example (local ebusd-tcp)

```yaml
transport: ebusd-tcp
network: tcp
address: 203.0.113.10:9999
source_addr: auto
proxy_profile: disabled
proxy_endpoint: ""
http_port: 8080
graphql_path: /graphql
subscription_path: /graphql/subscriptions
mcp_path: /mcp
mdns: true
modbus_tcp_enabled: false
modbus_tcp_endpoint: ""
modbus_tcp_dial_timeout: 5s
```

`source_addr=auto` delegates source selection to the gateway default policy and does not reuse `/data/source_addr.last`. The add-on no longer exposes `source_addr_state_file`; a leftover `/data/source_addr.last` is retained only as a rollback marker for older add-on versions and is never read as active source authority or rewritten during startup. For source-selection-capable direct transports, exact `source_addr` values are sent only as explicit validate-only gateway startup override input. If a gateway binary does not advertise that startup validation interface, startup fails closed instead of falling back to legacy active source configuration. For `transport=ebusd-tcp`, exact `source_addr` values are passed through the ebusd-compatible `-source-addr` gateway argument because startup source-selection admission is not used on that transport.

### 4) Adapter-direct configuration with embedded proxy listener

```yaml
adapter_direct_enabled: true
adapter_direct_address: enh://203.0.113.10:9999
proxy_listen_addr: 0.0.0.0:19001
transport: enh
network: tcp
address: 203.0.113.10:9999
proxy_profile: disabled
proxy_endpoint: ""
http_port: 8080
graphql_path: /graphql
subscription_path: /graphql/subscriptions
mcp_path: /mcp
mdns: true
modbus_tcp_enabled: false
modbus_tcp_endpoint: ""
modbus_tcp_dial_timeout: 5s
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

## Stable Instance GUID Lifecycle

- First start with empty `/data`: generate `/data/instance_guid`.
- Restart or add-on update with preserved `/data`: reuse the same GUID.
- Reinstall without restored `/data`: generate a new GUID and present as a new Helianthus instance to Home Assistant.

## Validation Commands

| Area | Command |
|---|---|
| JSON syntax | `python3 -m json.tool repository.json >/dev/null` |
| add-on config syntax | `python3 -m json.tool helianthus/config.json >/dev/null` |
| terminology gate (CI parity) | `if git grep -nIwiE 'm[a]ster|s[l]ave'; then echo "Found legacy terminology."; exit 1; fi` |
| smoke docs gate (CI parity) | `python3 scripts/validate_smoke_docs.py` |
| eeBUS HA network proof contract | `python3 scripts/check_eebus_ha_network_proof.py --self-test && python3 scripts/check_eebus_ha_network_proof.py --artifact scripts/fixtures/eebus_ha_network_proof_contract_pass.json --mode contract` |
| source address wrapper migration | `python3 scripts/check_source_addr_wrapper.py` |
| gateway parity gate readiness | `gateway_version="$(sed -n 's/^ARG EBUSGATEWAY_VERSION=//p' helianthus/Dockerfile)"; python3 scripts/check_gateway_parity_gate.py --artifact scripts/fixtures/gateway_parity_artifact_pass.json --source-ref "$gateway_version" --verify-github` |
| rollout guardrails | `gateway_version="$(sed -n 's/^ARG EBUSGATEWAY_VERSION=//p' helianthus/Dockerfile)"; python3 scripts/check_rollout_guardrails.py --guardrail helianthus/rollout_guardrails.json --artifact scripts/fixtures/gateway_parity_artifact_pass.json --source-ref "$gateway_version"` |
| post-parity enablement tasks | `gateway_version="$(sed -n 's/^ARG EBUSGATEWAY_VERSION=//p' helianthus/Dockerfile)"; python3 scripts/run_post_parity_enablement.py --guardrail helianthus/rollout_guardrails.json --artifact scripts/fixtures/gateway_parity_artifact_pass.json --source-ref "$gateway_version" --addon-config helianthus/config.json --smoke-runbook SMOKE_RUNBOOK.md` |
| Markdown private IPv4 gate | `python3 scripts/check_markdown_private_ips.py --self-test && python3 scripts/check_markdown_private_ips.py` |
| smoke checker CLI | `python3 scripts/smoke_addon_checklist.py --help` |

## Link Map

### Local docs

- Add-on folder docs: `helianthus/README.md`
- Operator smoke runbook: `SMOKE_RUNBOOK.md`
- eeBUS HA runtime networking proof: `EEBUS_HA_NETWORK_PROOF.md`
- Architecture baseline: `ARCHITECTURE.md`
- Repository conventions: `CONVENTIONS.md`
- Agent workflow notes: `AGENT.md`

### Related Helianthus repos/docs

- Gateway runtime: https://github.com/Project-Helianthus/helianthus-ebusgateway
- Registry/schema layer: https://github.com/Project-Helianthus/helianthus-ebusreg
- eBUS transport/protocol layer: https://github.com/Project-Helianthus/helianthus-ebusgo
- HA integration: https://github.com/Project-Helianthus/helianthus-ha-integration
- eBUS docs hub: https://github.com/Project-Helianthus/helianthus-docs-ebus

### Issue workflow conventions

- Use one issue-focused branch per change (example: `issue-32-readme-refresh`).
- Keep PR scope aligned to issue acceptance criteria.
- Include closing keyword in PR body (example: `Fixes #32`).
