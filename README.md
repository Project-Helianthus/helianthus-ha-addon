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
./scripts/ci_local.sh   # creates .venv-ci from requirements-ci.txt on first run (needs network once)
python3 scripts/smoke_addon_checklist.py --help
```

To run individual tests, use the same environment: `.venv-ci/bin/python3 -m pytest tests -q`.

### 2) Add repository to Home Assistant and install

```bash
ha addons repo add https://github.com/Project-Helianthus/helianthus-ha-addon
```

Then install **Helianthus** from the Add-on Store and open add-on configuration.
Release `0.6.58` packages the separated eeBUS Pairing, SHIP and read-only SPINE
workspaces alongside the canonical PV MCP and authenticated GraphQL M2M
surfaces. Its rollout
contract binds the exact gateway image to the Home Assistant canonical PV
consumer and preserves source/projection provenance without endpoints or raw
words. The release preserves the owner-atomic raw Modbus retry, Supervisor
option compatibility, direct gateway `exec` lifecycle, and disabled-by-default
Modbus configuration.

The dedicated M2M listener is also disabled by default. When enabled, the only
Supervisor values are its server identity and opaque asset reference. Server
TLS requires readable `server-cert.pem` and `server-key.pem` in
`/ssl/helianthus-pv-m2m`; missing server files reject startup. The listener
uses server-only TLS regardless of whether `ca.pem` is present. The optional
`ca.pem` supplies the Portal PV trust root; `portal-client-cert.pem` and
`portal-client-key.pem` enable the Portal PV semantic view only when both are
readable alongside `ca.pem`; otherwise that
view stays disabled independently of listener startup. Authentication and
authorization frameworks arrive in a later release. Server identity and
asset admission remain required. SHIP pairing, SKI allow-lists, SPINE bindings, and Matter ACLs
are unchanged. See [the 0.7 transport decision](https://github.com/Project-Helianthus/helianthus-ebusgateway/issues/1127).

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
modbus_tcp_endpoints: []
```

Leave `modbus_tcp_endpoints` empty to use the single-endpoint options above, or list up to eight read-only Modbus TCP endpoints in it instead; the two cannot be mixed. See [Several Modbus TCP endpoints](https://github.com/Project-Helianthus/helianthus-ha-addon/blob/main/helianthus/README.md#several-modbus-tcp-endpoints).

`source_addr=auto` delegates source selection to the gateway default policy and does not reuse `/data/source_addr.last`. The add-on no longer exposes `source_addr_state_file`; a leftover `/data/source_addr.last` is retained only as a rollback marker for older add-on versions and is never read as active source authority or rewritten during startup. For source-selection-capable direct transports, exact `source_addr` values are sent only as explicit validate-only gateway startup override input. If a gateway binary does not advertise that startup validation interface, startup fails closed instead of falling back to legacy active source configuration. For `transport=ebusd-tcp`, exact `source_addr` values are passed through the ebusd-compatible `-source-addr` gateway argument because startup source-selection admission is not used on that transport.

### Independent Growatt PCS and LINK receive-only options

PCS and LINK are independently disabled by default. V1.04 retains its existing
four CAN options/defaults; RS-485 and Tesla options remain independent. Each
enabled CAN family needs a different explicit interface: enabling all three
requires three distinct interfaces. Missing required input, malformed selectors,
interface conflicts or unsupported gateway flags refuse startup. Disabled PCS
and LINK families emit no arguments, including stored stale-age defaults.

The native interpretation owners are
[PCS — Profile selection; Data validity and consumer obligations](https://github.com/Project-Helianthus/helianthus-docs-canbus/blob/main/protocols/growatt/growatt-low-voltage-bms-can-pcs-protocol-v1.md)
and
[LINK — Identify the peer before interpreting version-dependent fields; Transport, addressing and data validity](https://github.com/Project-Helianthus/helianthus-docs-canbus/blob/main/protocols/growatt/growatt-low-voltage-bms-can-link-protocol-v1.md).
The add-on validates option syntax and explicit completeness; the gateway admits
supported native project/release/profile/contract combinations before opening an
interface. Exact case is preserved. Matching IDs, wire identity or plausible
values cannot supply project, release, profile or physical association. No
revision, topology or controller mode is inferred. Proven and Hypothesis are
candidate protocol grades, distinct from physical qualification; Unknown
meanings remain raw. Nothing is stable before 1.0.

Configure the controller externally in listen-only mode before enabling either
family, then explicitly set its confirmation. This receive-only precondition
neither sets nor verifies controller mode, bitrate, interface state or physical
acknowledgement suppression. These options never transmit, acknowledge, probe or
configure a bus. Offline tests use synthetic options and mocked help/argv only:
`physical_qualified=false`. eBUS MCP compatibility and GraphQL parity are
unaffected; this packaging adds no decoding or publication semantics.

Every option below defaults to an empty string except the two booleans per
family, which default to false. Staleness must be a positive Go duration, for
example `2s`. Profiles, scope and bank have no implicit default. LINK uses the
peer PCS profile, requires local scope, and requires ordinary bank for
standard/extended19 or parallel bank for parallel, as does PCS.

| Option | Gateway flag | Enabled requirement |
| --- | --- | --- |
| `growatt_bms_pcs_can_enabled` | `-growatt-bms-pcs-can-enabled` | true |
| `growatt_bms_pcs_can_interface` | `-growatt-bms-pcs-can-interface` | Explicit distinct interface |
| `growatt_bms_pcs_can_listen_only_confirmed` | `-growatt-bms-pcs-can-listen-only-confirmed` | true; external precondition |
| `growatt_bms_pcs_can_stale_after` | `-growatt-bms-pcs-can-stale-after` | Positive Go duration |
| `growatt_bms_pcs_can_project_code` | `-growatt-bms-pcs-can-project-code` | Explicit exact-case project |
| `growatt_bms_pcs_can_release` | `-growatt-bms-pcs-can-release` | Explicit four-digit release |
| `growatt_bms_pcs_can_native_profile` | `-growatt-bms-pcs-can-native-profile` | standard, extended19 or parallel |
| `growatt_bms_pcs_can_scope` | `-growatt-bms-pcs-can-scope` | local or aggregate |
| `growatt_bms_pcs_can_bank` | `-growatt-bms-pcs-can-bank` | ordinary or parallel matching profile |
| `growatt_bms_pcs_can_context` | `-growatt-bms-pcs-can-context` | Strict explicit association JSON |
| `growatt_bms_pcs_can_native_contract` | `-growatt-bms-pcs-can-native-contract` | legacy19 or release11 when native selection needs disambiguation |
| `growatt_bms_link_can_enabled` | `-growatt-bms-link-can-enabled` | true |
| `growatt_bms_link_can_interface` | `-growatt-bms-link-can-interface` | Explicit distinct interface |
| `growatt_bms_link_can_listen_only_confirmed` | `-growatt-bms-link-can-listen-only-confirmed` | true; external precondition |
| `growatt_bms_link_can_stale_after` | `-growatt-bms-link-can-stale-after` | Positive Go duration |
| `growatt_bms_link_can_project_code` | `-growatt-bms-link-can-project-code` | Default only for use_default entries |
| `growatt_bms_link_can_release` | `-growatt-bms-link-can-release` | Default only for use_default entries |
| `growatt_bms_link_can_native_profile` | `-growatt-bms-link-can-native-profile` | standard, extended19 or parallel |
| `growatt_bms_link_can_scope` | `-growatt-bms-link-can-scope` | local |
| `growatt_bms_link_can_bank` | `-growatt-bms-link-can-bank` | ordinary or parallel matching profile |
| `growatt_bms_link_can_context` | `-growatt-bms-link-can-context` | Strict explicit association JSON |
| `growatt_bms_link_can_source_selectors` | `-growatt-bms-link-can-source-selectors` | Strict ordered JSON array; see below |

LINK source selectors are one JSON string containing an ordered array of 1..32
entries, bounded to 16 KiB. Each entry is exactly one of these forms:

```json
[{"source":1,"project_code":"QAAA","release":"0011","contract":"release11"}]
```

```json
[{"source":1,"use_default":true,"contract":"release11"}]
```

Only an explicit `use_default:true` entry opts into the family project/release;
those defaults are required for such entries. Explicit entries may be
heterogeneous and need no family default. An omitted source never inherits
anything. Contracts are exactly `legacy19` or `release11`. Source is a unique
integer from 1 through 254 except 244 and 245; 255 is unidentified and excluded.
These are conservative software admission bounds, not hardware-address claims.
Duplicate keys/sources, mixed default/explicit keys, unknown keys, noninteger
sources, nulls, malformed/trailing JSON and control characters in selections
are refused. JSON order and escaping reach the gateway unchanged through safely
quoted argv; JSON is never shell code.

Both context options contain one strict JSON array bounded to 128 KiB. PCS
requires one entry; LINK requires one per selector in the same order and with
matching source. Each entry requires all these case-sensitive keys:

- `source`, `destination`, `serial_slot`, `native_slot`, `native_group`: integer bytes.
- `interface_index`: positive explicit OS identity assertion; no lookup is performed.
- `endpoint`, `group`, `slot`: nonempty, nonsecret association labels without whitespace/control characters.
- `epoch`: positive integer.
- `serial_slot_valid`, `slot_valid`, `group_valid`, `publisher_resolved`,
  `measurement_valid`, `temperature_valid`, `topology_associated`: explicit booleans.
- `field_age`: nonnegative Go duration.
- `cells` and `sensors`: objects containing `count`, `count_valid` and `gates`.
  Count bounds are 0..16 and 0..8 respectively; a valid count is positive.
  Each gates array has four objects containing explicit booleans `configured`
  and `valid`, nonnegative duration `age`, and `status` equal to the empty
  string, `absent`, `invalid`, `unsupported`, `stale` or `conflict`.

LINK destination is 244 or 245. All LINK contexts share interface index,
destination, endpoint/group/slot and epoch. Required false validity and zero
unknown counts remain distinct from missing fields. The add-on forwards these
assertions without interpreting frames or filling evidence. Native caches own
raw payload, interface, IDE, DLC/raw DLC, endpoint/group/slot, epoch, sequence,
monotonic time, field age, grade and partial last-known-good state. Zero, absent,
invalid, unsupported, stale and conflict remain distinct; a rejected field
cannot erase an independent valid sibling.

### 4) Adapter-direct configuration with embedded proxy listener

```yaml
adapter_direct_enabled: true
adapter_direct_protocol: enh
adapter_direct_address: 203.0.113.10:9999
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
modbus_tcp_endpoints: []
```

`adapter_direct_protocol` is the sole ENH/ENS selector for the physical adapter:
`enh` emits `adapter-direct://HOST:PORT`, while `ens` emits
`adapter-direct-ens://HOST:PORT`. Keep `proxy_profile=disabled` in
adapter-direct mode; `proxy_profile` is reserved for an external proxy endpoint.
The integrated proxy listener remains available through `proxy_listen_addr` for
both adapter protocols.

For a serial adapter, set `adapter_direct_address` to a device path instead of
`<host>:<port>`, for example `/dev/serial/by-id/<device>` (replace `<device>`
with the identifier listed on your system; the stable `/dev/serial/by-id/` form
is recommended). The add-on already declares `uart` access. The link speed
follows `adapter_direct_protocol`: `ens` runs at 115200 Baud, `enh` at 9600
Baud. An `ens:` or `enh:` prefix on a device path (`ens:/dev/...` or
`ens:///dev/...`) must match `adapter_direct_protocol`; a mismatch stops the
add-on at startup with a message naming both values. On a `<host>:<port>`
address a scheme prefix is ignored as before and `adapter_direct_protocol`
decides.

Upgrade compatibility is deterministic: `adapter_direct_protocol` is optional
at the Supervisor schema boundary so persisted options created before 0.6.49
remain saveable. When persisted options do not yet
contain `adapter_direct_protocol`, a pre-selector adapter-direct configuration
with `proxy_profile=enh|ens` and an empty `proxy_endpoint` is migrated at
startup to the matching adapter-direct protocol, then treated as
`proxy_profile=disabled`. Once the typed key is persisted, it is authoritative
even if a stale empty-endpoint profile remains. Save the explicit
`adapter_direct_protocol` and `proxy_profile=disabled` values when selecting a
protocol explicitly.
A populated `proxy_endpoint` is a real external-proxy configuration and remains
invalid with adapter-direct.

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
| Fronius-to-HA rollout contract | `python3 scripts/check_fronius_ha_rollout.py --artifact scripts/fixtures/fronius_ha_rollout_contract_pass.json --mode contract` |
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
