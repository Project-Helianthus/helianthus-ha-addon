# Helianthus Home Assistant Add-on

Home Assistant add-on that runs the Helianthus eBUS gateway (GraphQL + MCP).

## Status

- Builds and runs `helianthus-ebusgateway`
- Optionally runs `helianthus-ebus-adapter-proxy` in the same container (s6 service)
- Exposes GraphQL + MCP over HTTP
- Advertises `_helianthus-graphql._tcp` via mDNS (optional)
- Bundles `helianthus_vrc_explorer` in `/usr/bin` for on-device debugging

## Defaults

- GraphQL: `http://<host>:8080/graphql`
- Subscriptions: `http://<host>:8080/graphql/subscriptions`
- MCP: `http://<host>:8080/mcp`

## Configuration

Key options are exposed in `config.json`:

- `adapter_proxy_enabled`: start the local adapter proxy service
- `adapter_proxy_upstream`: upstream endpoint for the proxy (e.g. `enh://<host>:<port>`)
- `adapter_proxy_port`: local proxy listen port
- `adapter_proxy_udp_plain_enabled`: enable a UDP-plain northbound listener for ebusd UDP mode
- `adapter_proxy_udp_plain_port`: UDP-plain listener port (default `19002`)
- `transport`: `enh`, `ens`, `udp-plain`, or `ebusd-tcp`
- `network`: `tcp`, `udp`, or `unix`
- `address`: transport address (e.g. `HOST:PORT`)
- `proxy_profile`: `disabled`, `enh`, or `ens` (transition mode profile marker)
- `proxy_endpoint`: proxy endpoint (`host:port` or URI) used when `proxy_profile` is enabled
- `host`: hostname used in startup endpoint logs
- `port`: simple GraphQL/MCP endpoint port alias
- `path`: simple GraphQL endpoint path alias
- `http_port`: HTTP listen port
- `graphql_path`: GraphQL endpoint path
- `subscription_path`: GraphQL subscriptions endpoint path
- `mcp_path`: MCP endpoint path
- `mdns`: enable/disable mDNS advertisement

For ebusd TCP mode, use `transport=ebusd-tcp`, `network=tcp`, and set `address=<ebusd-host>:<ebusd-port>`.

For direct UDP-plain adapters, use `transport=udp-plain`, `network=udp`, and set `address=<adapter-host>:<port>`.

Source-address persistence:

- `source_addr` defaults to `auto`.
- `source_addr_state_file` (default `/data/source_addr.last`) stores the last explicit source address used by the gateway.
- On restart with `source_addr=auto` (and non-`ebusd-tcp` transport), the add-on reuses the persisted address when present.

For transition mode via `helianthus-ebus-adapter-proxy`, set `proxy_profile=enh|ens` and
`proxy_endpoint=<host:port>` (or full endpoint URI); startup logs emit proxy profile/endpoint markers.

## Debugging tools

This add-on image includes `helianthus_vrc_explorer` at `/usr/bin/helianthus_vrc_explorer`.
CI builds resolve `helianthus-vrc-explorer` `main` to a concrete commit SHA at build time and install that pinned revision in the image.

It runs with:

```sh
helianthus_vrc_explorer --help
```

For local smoke/debug, executable overrides are supported from add-on data:

- `/data/helianthus-gateway` overrides `/usr/local/bin/helianthus-gateway`
- `/data/helianthus-ebus-adapter-proxy` overrides `/usr/local/bin/helianthus-ebus-adapter-proxy`
