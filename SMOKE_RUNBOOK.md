# Helianthus HA Add-on Smoke Runbook

This runbook validates the Home Assistant add-on path with a local `ebusd-tcp` topology and
the embedded gateway adaptermux proxy topology, and produces deterministic pass/fail output.

## Local ebusd-tcp topology

- Home Assistant Supervisor runs the `helianthus` add-on.
- Add-on transport points to local/lan ebusd TCP endpoint.
- Example topology values used below:
  - ebusd endpoint: `203.0.113.10:9999`
  - proxy profile: `disabled`
  - proxy endpoint: `(none)`
  - add-on HTTP API: `127.0.0.1:8080`
  - GraphQL path: `/graphql`
  - Subscriptions path: `/graphql/subscriptions`
  - MCP path: `/mcp`

## Embedded adaptermux proxy topology

- Point the Helianthus add-on at the physical adapter with `adapter_direct_enabled=true`.
- Select the physical adapter protocol explicitly with `adapter_direct_protocol=enh|ens`.
- Use `proxy_listen_addr` to expose the gateway-embedded adaptermux proxy for other clients.
- Keep `proxy_profile=disabled`; the add-on no longer starts or wires a standalone adapter-proxy.
- Example values:
  - adapter direct protocol: `enh`
  - adapter direct address: `203.0.113.10:9999`
  - proxy listener: `0.0.0.0:19001`
  - effective transport marker: `Transport: adapter-direct (tcp adapter-direct://203.0.113.10:9999)`

For ENS, keep the same address and listener, set
`adapter_direct_protocol=ens`, and expect
`Transport: adapter-direct (tcp adapter-direct-ens://203.0.113.10:9999)`.

An upgraded pre-selector configuration whose persisted options do not yet
contain `adapter_direct_protocol` may still contain `proxy_profile=enh|ens`
with an empty `proxy_endpoint`. Startup must log the legacy migration, emit the
matching adapter-direct URI, report `Proxy profile: disabled`, and preserve
`-proxy-listen`. Once the typed key exists, verify that it wins over any stale
empty-endpoint profile. Save the explicit `adapter_direct_protocol` and
`proxy_profile=disabled` options afterward. If `proxy_endpoint` is populated,
startup must reject the mixed configuration.

## Install and start add-on

1) Add repository:

```bash
ha addons repo add https://github.com/Project-Helianthus/helianthus-ha-addon
```

2) Install and start the `helianthus` add-on from Home Assistant Add-on Store.

For release `0.6.54`, do not supply any eeBUS-specific credential options:
they remain removed. The consolidated runtime includes deterministic canonical
PV V1 retrieval for retained qualified SunSpec samples, endpoint-free Modbus
provider errors, and one owner-atomic raw MCP reconnect/retry. Modbus remains
opt-in and uses the same direct gateway process lifecycle as the disabled
configuration.

3) Open add-on **Configuration** and paste the configuration payload below.

## Add-on configuration (copy/paste)

<!-- smoke-config-json:start -->
```json
{
  "transport": "ebusd-tcp",
  "network": "tcp",
  "address": "203.0.113.10:9999",
  "proxy_profile": "disabled",
  "proxy_endpoint": "",
  "host": "127.0.0.1",
  "http_port": 8080,
  "graphql_path": "/graphql",
  "subscription_path": "/graphql/subscriptions",
  "mcp_path": "/mcp",
  "mdns": true,
  "mdns_instance": "helianthus",
  "broadcast": false,
  "read_timeout": "5s",
  "write_timeout": "5s",
  "dial_timeout": "5s",
  "modbus_tcp_enabled": false,
  "modbus_tcp_endpoint": "",
  "modbus_tcp_dial_timeout": "5s"
}
```
<!-- smoke-config-json:end -->

After saving config, restart the add-on.

On first start, the add-on also creates `/data/instance_guid` if it does not already exist.
Preserving `/data` across updates keeps the same Helianthus identity; reinstalling without `/data`
creates a new identity that Home Assistant should treat as a new instance.

## Deterministic smoke checklist

1) Export add-on logs:

```bash
ha addons logs helianthus > /tmp/helianthus-addon.log
```

2) Run checklist:

```bash
python3 scripts/smoke_addon_checklist.py \
  --log-file /tmp/helianthus-addon.log \
  --transport ebusd-tcp \
  --network tcp \
  --address 203.0.113.10:9999 \
  --proxy-profile disabled \
  --host 127.0.0.1 \
  --http-port 8080 \
  --graphql-path /graphql \
  --subscription-path /graphql/subscriptions \
  --mcp-path /mcp
```

3) Optional JSON output:

```bash
python3 scripts/smoke_addon_checklist.py \
  --log-file /tmp/helianthus-addon.log \
  --transport ebusd-tcp \
  --network tcp \
  --address 203.0.113.10:9999 \
  --proxy-profile disabled \
  --host 127.0.0.1 \
  --http-port 8080 \
  --graphql-path /graphql \
  --subscription-path /graphql/subscriptions \
  --mcp-path /mcp \
  --json
```

Embedded adaptermux checklist example:

```bash
python3 scripts/smoke_addon_checklist.py \
  --log-file /tmp/helianthus-addon.log \
  --transport adapter-direct \
  --network tcp \
  --address adapter-direct://203.0.113.10:9999 \
  --proxy-profile disabled \
  --host 127.0.0.1 \
  --http-port 8080 \
  --graphql-path /graphql \
  --subscription-path /graphql/subscriptions \
  --mcp-path /mcp
```

Checklist IDs (stable order):

<!-- smoke-checklist:start -->
```text
- [ ] CHECK_CONNECTION_GRAPHQL
- [ ] CHECK_CONNECTION_MCP
- [ ] CHECK_LOG_STARTUP
- [ ] CHECK_LOG_TRANSPORT
- [ ] CHECK_LOG_PROXY_PROFILE
- [ ] CHECK_LOG_PROXY_ENDPOINT
- [ ] CHECK_LOG_GRAPHQL_ENDPOINT
- [ ] CHECK_LOG_SUBSCRIPTION_ENDPOINT
- [ ] CHECK_LOG_MCP_ENDPOINT
```
<!-- smoke-checklist:end -->

Expected final line:

```text
OVERALL PASS
```

## M5-08 Fronius-to-Home-Assistant rollout

Run these checks only against the exact add-on, gateway, and Home Assistant
integration revisions recorded by the rollout artifact. Keep every Modbus
operation read-only and keep endpoint values out of the public artifact.

Before enabling `m2m_graphql_enabled`, create the fixed TLS bundle below
`/config/helianthus/pv-m2m`. The add-on reads `ca.pem`, `server-cert.pem`,
`server-key.pem`, `portal-client-cert.pem`, and `portal-client-key.pem` through
the read-only `/config` mount. Home Assistant uses the same `ca.pem` plus its
own `ha-client-cert.pem` and `ha-client-key.pem`. Set the server identity option
to an exact DNS name or IP SAN in `server-cert.pem`, and use one opaque asset
reference consistently in the add-on and Home Assistant options.

```text
- [ ] M5_08_RAW_MCP: bounded raw FC03 read succeeds through the authenticated raw Portal/MCP boundary
- [ ] M5_08_SEMANTIC_MCP: canonical PV semantic MCP returns terminal-qualified facts and provenance
- [ ] M5_08_GRAPHQL_M2M: PUBLIC_GRAPHQL_M2M_V1 returns the same canonical fact identities and accounting
- [ ] M5_08_PORTAL_SEMANTIC: semantic Portal view consumes GraphQL and shows the canonical PV snapshot
- [ ] M5_08_PORTAL_RAW: separate raw Portal view remains bounded, audited, authenticated, and read-only
- [ ] M5_08_HOME_ASSISTANT: M5-07 entities are available with stable IDs, exact units, and freshness state
- [ ] M5_08_EXTERNAL_MTLS: external service polling uses mTLS, verified server identity, and a cadence of at least 5 seconds
- [ ] M5_08_RECOVERY: credential rotation, channel reconnect, and one restart recover without identity drift
- [ ] M5_08_INDEPENDENT_DISABLE: Modbus acquisition and the HA PV consumer disable independently
- [ ] M5_08_ROLLBACK: backup exists and rollback to 0.6.53 preserves schema compatibility and unavailable behavior
```

Record the sanitized result with `helianthus.fronius-ha-rollout/v1` and verify it:

```bash
python3 scripts/check_fronius_ha_rollout.py \
  --artifact /path/to/fronius-ha-rollout-live.json \
  --mode lab
```

Exit code:

- `0` when all checks pass
- `1` when any check fails

## Failure triage

| Check ID | Primary failure meaning | First action |
| --- | --- | --- |
| CHECK_CONNECTION_GRAPHQL | GraphQL endpoint not reachable or invalid response | Verify add-on is running and `graphql_path/http_port` settings, then restart |
| CHECK_CONNECTION_MCP | MCP endpoint not reachable or tools/list failed | Verify `mcp_path` and supervisor/network reachability |
| CHECK_LOG_STARTUP | Startup marker missing | Confirm add-on process starts and does not crash early |
| CHECK_LOG_TRANSPORT | Transport marker mismatch | Verify `transport/network/address` options for ebusd-tcp |
| CHECK_LOG_PROXY_PROFILE | Proxy profile marker mismatch | Verify `proxy_profile` is set to `disabled`, `enh`, or `ens` as intended |
| CHECK_LOG_PROXY_ENDPOINT | Proxy endpoint marker mismatch | Verify `proxy_endpoint` and transition mode endpoint normalization |
| CHECK_LOG_GRAPHQL_ENDPOINT | GraphQL endpoint marker mismatch | Verify `host/http_port/graphql_path` in add-on config |
| CHECK_LOG_SUBSCRIPTION_ENDPOINT | Subscriptions marker mismatch | Verify `subscription_path` and graphql path normalization |
| CHECK_LOG_MCP_ENDPOINT | MCP marker mismatch | Verify `mcp_path` normalization and startup options |
