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
- Use `proxy_listen_addr` to expose the gateway-embedded adaptermux proxy for other clients.
- Keep `proxy_profile=disabled`; the add-on no longer starts or wires a standalone adapter-proxy.
- Example values:
  - adapter direct address: `enh://203.0.113.10:9999`
  - proxy listener: `0.0.0.0:19001`
  - effective transport marker: `Transport: adapter-direct (tcp adapter-direct://203.0.113.10:9999)`

## Install and start add-on

1) Add repository:

```bash
ha addons repo add https://github.com/Project-Helianthus/helianthus-ha-addon
```

2) Install and start the `helianthus` add-on from Home Assistant Add-on Store.

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
