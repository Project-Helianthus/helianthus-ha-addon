# Helianthus Home Assistant Add-on

Home Assistant add-on that runs the Helianthus eBUS gateway (GraphQL + MCP).

## Status

- Builds and runs `helianthus-ebusgateway`
- Can expose the gateway-embedded adaptermux proxy listener for other eBUS clients
- Exposes GraphQL + MCP over HTTP
- Advertises `_helianthus-graphql._tcp` via mDNS (optional)
- Bundles `helianthus_vrc_explorer` in `/usr/bin` for on-device debugging

## Defaults

- GraphQL: `http://<host>:8080/graphql`
- Subscriptions: `http://<host>:8080/graphql/subscriptions`
- MCP: `http://<host>:8080/mcp`

## Configuration

Key options are exposed in `config.json`:

- `adapter_direct_enabled`: connect through the gateway adapter-direct path
- `adapter_direct_address`: physical adapter endpoint for adapter-direct mode (e.g. `enh://<host>:<port>`)
- `proxy_listen_addr`: gateway-embedded adaptermux proxy listener address (default `0.0.0.0:19001`)
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
- `eebus_enabled`: enable raw eeBUS runtime; pairing remains closed by default
- `eebus_listen_port`, `eebus_interface`, `eebus_subnets`, `eebus_discovery_enabled`, and `eebus_remote_ski_allowlist`: raw eeBUS runtime network controls
- `modbus_tcp_enabled`: opt in to the read-only Modbus TCP sidecar (default `false`)
- `modbus_tcp_endpoint`: one `tcp://host:port` endpoint; Supervisor treats it as a password field and embedded credentials are rejected
- `modbus_tcp_dial_timeout`: bounded `ms` or `s` dial timeout from 100 ms through 30 s

The add-on validates the closed option bundle, materializes the admitted
endpoint in a private runtime file, appends the three Modbus flags when enabled,
and directly `exec`s the packaged gateway. It does not supervise a separate
gateway child, post-process logs, probe listeners, retry the complete gateway,
or launch a previous binary. Modbus reconnect and availability remain
protocol-local; eBUS, eeBUS, HTTP, and MCP keep the normal gateway lifecycle.

Release `0.6.48` packages the consolidated gateway with bounded FM5 startup
convergence, source-owned endpoint sanitization, and protocol-local Modbus
startup failure. All
eeBUS-specific credential provisioning remains removed, and the read-only
Modbus runtime remains disabled unless explicitly enabled.

For ebusd TCP mode, use `transport=ebusd-tcp`, `network=tcp`, and set `address=<ebusd-host>:<ebusd-port>`.

For direct UDP-plain adapters, use `transport=udp-plain`, `network=udp`, and set `address=<adapter-host>:<port>`.

Source address selection:

- `source_addr` defaults to `auto`.
- `source_addr=auto` delegates to the gateway default source-selection policy and ignores any legacy `/data/source_addr.last` value.
- For source-selection-capable direct transports, exact `source_addr` values are passed only as explicit validate-only gateway startup override input. Gateway binaries that do not advertise startup override validation fail closed instead of receiving legacy active source configuration.
- For `transport=ebusd-tcp`, exact `source_addr` values are passed through the ebusd-compatible `-source-addr` gateway argument because startup source-selection admission is not used on that transport.
- The legacy `/data/source_addr.last` file is retained only as a migration/rollback marker for older add-on versions. The wrapper no longer exposes a state-file option, writes this file, or promotes it into active source configuration.
- Rollback to an older add-on may still read the leftover file. To prevent that older behavior, remove `/data/source_addr.last` before rolling back.

Stable instance GUID persistence:

- The add-on stores the Helianthus instance GUID at `/data/instance_guid`.
- If the file is missing or invalid, startup generates a new lowercase UUIDv4 and persists it atomically.
- The persisted GUID survives normal restarts and updates as long as `/data` is preserved.
- Removing `/data/instance_guid` or reinstalling without restoring `/data` creates a new Helianthus instance identity.

For embedded adaptermux proxy mode, set `adapter_direct_enabled=true`,
`adapter_direct_address=<adapter-endpoint>`, and `proxy_listen_addr=<listen-host:port>`.
Leave `proxy_profile=disabled` unless intentionally connecting the gateway to an external proxy endpoint.

## Debugging tools

This add-on image includes `helianthus_vrc_explorer` at `/usr/bin/helianthus_vrc_explorer`.
CI builds install the pinned `helianthus-vrc-explorer` release tag declared in the image build args.

It runs with:

```sh
helianthus_vrc_explorer --help
```

Persistent gateway executable overrides are not supported. If an earlier
installation left `/data/helianthus-gateway` behind, remove that file or
symlink before startup. The wrapper fails closed until the packaged,
version-pinned gateway is authoritative.
