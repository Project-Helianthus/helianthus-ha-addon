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
- `adapter_direct_protocol`: explicit physical adapter protocol, `enh` or `ens` (default `enh`)
- `adapter_direct_address`: physical adapter endpoint for adapter-direct mode (`<host>:<port>`)
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
- `modbus_tcp_endpoint`: one visible `tcp://host:port` routing endpoint; embedded credentials are rejected
- `modbus_tcp_dial_timeout`: bounded `ms` or `s` dial timeout from 100 ms through 30 s

The add-on validates the closed option bundle, materializes the admitted
endpoint in a private runtime file, appends the three Modbus flags when enabled,
and directly `exec`s the packaged gateway. It does not supervise a separate
gateway child, post-process logs, probe listeners, retry the complete gateway,
or launch a previous binary. Modbus reconnect and availability remain
protocol-local; eBUS, eeBUS, HTTP, and MCP keep the normal gateway lifecycle.
Upgrade startup removes the retired Modbus health record. Any failure before
the final `exec` also removes the protected endpoint file.

Release `0.6.58` pins the gateway with separate eeBUS Pairing, SHIP and
connected-only read-only SPINE workspaces, deterministic canonical PV V1
projection, authenticated GraphQL M2M publication, and separate semantic and
bounded raw Portal surfaces. The rollout contract binds this image to the canonical PV
Home Assistant consumer while keeping Modbus read-only and disabled by default.
The semantic response preserves exact source and projection provenance without
endpoints or raw words. The 0.6.51 owner-atomic raw Modbus retry, option schema,
single-process wrapper, and disabled-by-default behavior remain unchanged.

The dedicated M2M listener is disabled by default. Enable it only after placing
`server-cert.pem` and `server-key.pem` under `/ssl/helianthus-pv-m2m`. It uses
server-only TLS regardless of whether `ca.pem` is present. The optional Portal
PV semantic view requires all three readable files: `ca.pem` as its trust root,
`portal-client-cert.pem`, and `portal-client-key.pem`; it stays disabled when
any is absent. The dedicated `/ssl` mount is read-only inside the add-on;
certificate bytes are never accepted as options.

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
`adapter_direct_protocol=enh|ens`, `adapter_direct_address=<adapter-endpoint>`,
and `proxy_listen_addr=<listen-host:port>`. ENH emits
`adapter-direct://HOST:PORT`; ENS emits `adapter-direct-ens://HOST:PORT`.
Keep `proxy_profile=disabled`: adapter-direct and an external proxy endpoint are
mutually exclusive configurations. The gateway-integrated proxy listener is
preserved for both adapter protocols.

For upgrade compatibility only, when persisted options do not yet contain
`adapter_direct_protocol`, the wrapper recognizes the exact old adapter-direct
shape `proxy_profile=enh|ens` with an empty `proxy_endpoint`, migrates it to the
matching adapter-direct protocol, and disables the effective proxy profile.
Once the typed key is persisted it remains authoritative even if the stale
profile remains. Save `adapter_direct_protocol` explicitly and reset
`proxy_profile=disabled` after upgrading. Adapter-direct plus a populated
external `proxy_endpoint` is rejected.

## Serial acquisition options (Growatt BMS RS-485, Tesla Gen3 HSC)

The add-on declares `uart: true`, which gives the container access to the host's
serial adapters (for example a USB RS-485 adapter) through the Supervisor. It
adds no `devices` entry, so no adapter has to exist for the add-on to start, and
it does not make the add-on privileged. Both families below are **disabled by
default**. While a family is disabled the wrapper passes none of its flags,
because the gateway refuses a disabled family that carries any other field.

Enabling a family requires every identity option of that family; the wrapper
fails startup with the rejected option named instead of guessing. Identity and
epoch values are operator-chosen, non-secret labels: no whitespace or control
characters, and asset and source identities must differ. They are never derived
from device data. The gateway remains the final validator.

### Growatt BMS RS-485 (exact read-only V2.02 observer)

| Option | Gateway flag | Default |
| --- | --- | --- |
| `growatt_bms_rs485_enabled` | `-growatt-bms-rs485-enabled` | `false` |
| `growatt_bms_rs485_asset_id` | `-growatt-bms-rs485-asset-id` | required when enabled |
| `growatt_bms_rs485_source_id` | `-growatt-bms-rs485-source-id` | required when enabled |
| `growatt_bms_rs485_source_epoch` | `-growatt-bms-rs485-source-epoch` | required when enabled |
| `growatt_bms_rs485_driver_generation` | `-growatt-bms-rs485-driver-generation` | required, 1 or more |
| `growatt_bms_rs485_unit_id` | `-growatt-bms-rs485-unit-id` | required, 1-247 |
| `growatt_bms_rs485_serial_path` | `-growatt-bms-rs485-serial-path` | required, a `/dev/` path |
| `growatt_bms_rs485_baud` | `-growatt-bms-rs485-baud` | `9600` |
| `growatt_bms_rs485_parity` | `-growatt-bms-rs485-parity` | `none` (`none`, `even`, `odd`) |
| `growatt_bms_rs485_stop_bits` | `-growatt-bms-rs485-stop-bits` | `1` (`1` or `2`) |
| `growatt_bms_rs485_response_timeout` | `-growatt-bms-rs485-response-timeout` | `500ms` |
| `growatt_bms_rs485_max_response_delay` | `-growatt-bms-rs485-max-response-delay` | `250ms` |
| `growatt_bms_rs485_max_quiescence` | `-growatt-bms-rs485-max-quiescence` | `2s`, must exceed the response delay |

The serial format, baud and timing defaults are add-on starting values, not
values derived from the BMS specification; confirm them against the installed
battery before relying on them. Durations use the form `500ms` or `2s`. When the
M2M GraphQL listener is also enabled, the gateway additionally requires the
quiescence plus four reads to fit below the M2M deadline and refuses to start
otherwise.

### Tesla Gen3 HSC retained owner (identity only)

| Option | Gateway flag | Default |
| --- | --- | --- |
| `tesla_gen3_hsc_retained_enabled` | `-tesla-gen3-hsc-retained-enabled` | `false` |
| `tesla_gen3_hsc_endpoint_id` | `-tesla-gen3-hsc-endpoint-id` | required when enabled |
| `tesla_gen3_hsc_asset_id` | `-tesla-gen3-hsc-asset-id` | required when enabled |
| `tesla_gen3_hsc_source_id` | `-tesla-gen3-hsc-source-id` | required when enabled |
| `tesla_gen3_hsc_source_epoch` | `-tesla-gen3-hsc-source-epoch` | required when enabled |
| `tesla_gen3_hsc_clock_epoch` | `-tesla-gen3-hsc-clock-epoch` | required when enabled |
| `tesla_gen3_hsc_evse_id` | `-tesla-gen3-hsc-evse-id` | required when enabled |
| `tesla_gen3_hsc_connector_id` | `-tesla-gen3-hsc-connector-id` | required when enabled |
| `tesla_gen3_hsc_driver_generation` | `-tesla-gen3-hsc-driver-generation` | required, 1 or more |
| `tesla_gen3_hsc_node` | `-tesla-gen3-hsc-node` | required, 1-247 |
| (fixed, not an option) | `-tesla-gen3-hsc-profile wc3_24_44_3` | passed whenever enabled |

The Tesla owner is **non-send** on the pinned gateway. These options configure
identity, epochs and the unicast node label of a completed-outcome owner only.
They open no serial port, send no request and do no acquisition; enabling the
family does not make the Tesla charger observable. The pinned gateway also
requires the connector, driver generation, node and profile for an enabled
Tesla owner, so those are exposed or fixed here in addition to the identity and
epoch fields.

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

## Build BOM

`helianthus/bom.json` (format `helianthus-addon-bom/1`) records the exact inputs
of the image build: the gateway commit and tree, the `helianthus-vrc-explorer`
tag and commit, the gateway build's Go module pins (`go.mod` requires plus the
SHA-256 of `go.mod` and `go.sum`), the builder and base images, and the gateway
CLI flag set the wrapper was verified against.

- `python3 scripts/bom_manifest.py check` runs offline in `ci_local.sh` and in
  pull-request CI. It fails when the BOM disagrees with `helianthus/Dockerfile`,
  `.github/workflows/build.yml` or `helianthus/config.json`, or when the wrapper
  passes a flag the pinned gateway does not define.
- `python3 scripts/bom_manifest.py generate --gateway-help <file>` rebuilds the
  BOM online from the Dockerfile pins. `<file>` is the `--help` output of a
  gateway built from the pinned commit.
- Image digests are observed at generation time because the build references
  tags. INT-16 freezes the BOM for the 0.7 release: it replaces the observed
  digests with pinned digests and sets `freeze.status` to `frozen`. After the
  freeze, any pin change requires a new BOM.
- Pin changes also update the Dockerfile, the build workflow, the parity
  artifact fixture, `config.json` and the changelog in the same pull request.
