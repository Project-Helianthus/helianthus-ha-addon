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
- Portal: `http://<host>:8080/portal/`

## Portal and Home Assistant Ingress

The add-on declares Home Assistant Ingress on its existing HTTP listener
(port 8080) with an administrator-only **Helianthus** sidebar panel that opens
the Portal directory (`portal/`). Opening the Portal does not require the
Helianthus Home Assistant integration. The wrapper pins the gateway Portal
mount with `-portal-path /portal`, starts no second listener or process, and
keeps the adapter proxy, eeBUS and M2M listeners off Ingress.

- Ingress reaches the Portal only while the HTTP listener stays on port 8080.
  With another `http_port` (or `port`) the panel is unavailable, the startup log
  says so, and the direct Portal endpoint keeps working.
- The packaged gateway accepts no trusted external path prefix yet. The Portal
  shell, its assets, relative API routes and the live stream use relative URLs
  and stay under the Ingress path. Sections that use the GraphQL, Portal catalog
  or eeBUS admin endpoints advertised by the Portal bootstrap address root paths,
  so they work only on the direct endpoint until the gateway accepts that prefix.
- Ingress adds no authentication or authorization. The gateway does not trust
  forwarded identity headers, and the direct listener stays reachable as before.
- Gateway builds that persist Portal configuration keep it under their default
  root, the add-on's `/data` directory; the wrapper never reads, repairs or
  removes that record.

## Configuration

Key options are exposed in `config.json`:

- `adapter_direct_enabled`: connect through the gateway adapter-direct path
- `adapter_direct_protocol`: explicit physical adapter protocol, `enh` or `ens` (default `enh`)
- `adapter_direct_address`: physical adapter endpoint for adapter-direct mode (`<host>:<port>`, or a serial device path such as `/dev/serial/by-id/<device>`)
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
- `modbus_tcp_endpoints`: optional list of up to eight Modbus TCP endpoints, one read-only driver instance each (default empty; see [Several Modbus TCP endpoints](#several-modbus-tcp-endpoints))

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

A serial adapter is configured by device path instead of `<host>:<port>`, for
example `adapter_direct_address=/dev/serial/by-id/<device>` (replace `<device>`
with the identifier listed on your system). The stable `/dev/serial/by-id/`
form is recommended because it survives re-enumeration. The add-on already
declares `uart` access. The link speed follows `adapter_direct_protocol`: `ens`
runs at 115200 Baud, `enh` at 9600 Baud. An `ens:` or `enh:` prefix on a
device path (`ens:/dev/...` or `ens:///dev/...`) must match
`adapter_direct_protocol`; a mismatch stops the add-on at startup naming both
values. On a `<host>:<port>` address a scheme prefix is ignored as before and
`adapter_direct_protocol` decides.

For upgrade compatibility only, when persisted options do not yet contain
`adapter_direct_protocol`, the wrapper recognizes the exact old adapter-direct
shape `proxy_profile=enh|ens` with an empty `proxy_endpoint`, migrates it to the
matching adapter-direct protocol, and disables the effective proxy profile.
Once the typed key is persisted it remains authoritative even if the stale
profile remains. Save `adapter_direct_protocol` explicitly and reset
`proxy_profile=disabled` after upgrading. Adapter-direct plus a populated
external `proxy_endpoint` is rejected.

## Several Modbus TCP endpoints

`modbus_tcp_endpoints` replaces the three scalar options when the gateway should
read several Modbus TCP endpoints (up to eight entries), each as its own read-only
driver instance with its own connection, pacing and failure isolation. The contract is the
[multi-endpoint runtime page](https://github.com/Project-Helianthus/helianthus-docs-ebus/blob/main/api/modbus-multi-endpoint-runtime.md)
of the public eBUS documentation; this add-on only validates the list, writes it
and passes the gateway one path.

Each entry has these members (a bold name is required):

| Member | Rule | Default when omitted |
| --- | --- | --- |
| **`label`** | 1 to 32 characters: lowercase letters and digits, single hyphens between them, starting with a letter; unique in the list. `default` keeps the driver identity of the single endpoint. The label becomes part of the driver ID that every gateway surface shows, so never encode an address, serial number or site detail in it. | |
| **`family`** | `sunspec`, `huawei.smartlogger`, `huawei.emma` or `huawei.sdongle`. The declared family is the only family tried. | |
| **`endpoint`** | `tcp://host:port` with an IP literal or DNS name, port 1 to 65535, at most 288 characters, no credentials, path or query; unique after lowercasing the host, dropping one trailing dot and normalizing the IP spelling and port. Rendered as a password field. | |
| `dial_timeout` | `ms` or `s` duration from 100 ms through 30 s. | `5s` |
| `units` | Allowlist of 1 to 32 distinct routed unit numbers from 1 to 247. It narrows what a family reports and never widens it. For `sunspec` leave it out or use exactly `[1]`. | the family's own routing |
| `pacing_gap_ms` | Idle time between two transactions on the connection, 50 to 2000. | 200 |
| `pacing_settle_ms` | Wait after each connect before the first request, 0 to 10000. | 1000 |
| `pacing_cycle_s` | Interval between acquisition cycles, 15 to 3600. | 30 (15 for `sunspec`) |
| `pacing_backoff_floor_s` | First reconnect delay, 1 to 300; each further failure doubles it. | 5 |
| `pacing_backoff_ceiling_s` | Largest reconnect delay, 5 to 3600, not below the floor. | 300 |

The defaults are applied by the gateway, not written by the add-on; they are the
contract's recommendation for production sites, not measured guarantees. The
pacing members are flat options because the Supervisor option schema cannot mark
a nested object optional; the add-on writes them as the `pacing` object of the
endpoints document.

```yaml
modbus_tcp_enabled: true
modbus_tcp_endpoint: ""
modbus_tcp_dial_timeout: 5s
modbus_tcp_endpoints:
  - label: default
    family: sunspec
    endpoint: tcp://sunspec-a.example.invalid:502
  - label: roof
    family: sunspec
    endpoint: tcp://sunspec-b.example.invalid:1502
    pacing_gap_ms: 300
```

Selection and refusal:

- `modbus_tcp_enabled: false` ignores the list and the scalars and validates
  neither. An empty list keeps the single-endpoint configuration exactly as it
  was: the same three flags and the same private endpoint file.
- A non-empty list needs `modbus_tcp_endpoint` empty and `modbus_tcp_dial_timeout`
  at `5s`. Otherwise startup stops with `MIXED_CONFIGURATION` before the gateway
  starts. To move from the single endpoint to the list, copy it into an entry
  labelled `default` with family `sunspec`, then clear the scalar endpoint. The
  driver identity, source, stored state and tools stay the same, but pacing does
  not: an entry allows one request in flight instead of up to four, adds a gap
  between requests and a settle wait after each connect, and reconnects with a
  backoff of 5 s to 300 s instead of 1 s to 30 s (the 15 s `sunspec` cycle is
  kept). Moving back to the scalar options restores the single-endpoint limits and
  drops every pacing value; none is translated.
- The whole list is validated before anything is written, in the contract's
  order, and the first failing check stops startup with one category and, for an
  entry-local case, its zero-based position (for example
  `INVALID_ENDPOINT (entry 1)`). The categories are `MIXED_CONFIGURATION`,
  `INVALID_DOCUMENT`, `TOO_MANY_ENTRIES`, `MISSING_FIELD`, `UNKNOWN_MEMBER`,
  `INVALID_LABEL`, `UNKNOWN_FAMILY`, `INVALID_ENDPOINT`, `INVALID_TIMEOUT`,
  `INVALID_UNITS`, `INVALID_PACING`, `DUPLICATE_LABEL` and `DUPLICATE_ENDPOINT`.
  Messages never carry an endpoint, label or other value.
- The valid list becomes one JSON document in the private runtime directory (file
  mode `0600` in a `0700` directory), staged and renamed atomically. Earlier
  material is removed before validation, so a rejected list leaves no document.
  The gateway receives only `-modbus-tcp-endpoints-file` with that path: the
  endpoints appear in no argument, environment variable or log line.
- A gateway that does not advertise `-modbus-tcp-endpoints-file` cannot read the
  list. Startup then stops with a message naming the option instead of ignoring
  it; the single-endpoint configuration and the disabled default are unaffected.
- A change to the list takes effect at the next add-on start. An entry that is
  removed is not registered at that start.
- A Huawei family is accepted as configuration only. The gateway lists its
  instance as withheld and sends nothing until that family's own native contract
  admits a qualification, and the physical acceptance rows for those families
  stay unverified in the [offline acceptance index](https://github.com/Project-Helianthus/helianthus-ha-addon/blob/main/docs/offline-acceptance-index.md)
  until reviewed operator evidence exists.

## Serial acquisition options (Growatt BMS RS-485, Growatt BMS CAN, Tesla Gen3 HSC)

The add-on declares `uart: true`, which gives the container access to the host's
serial adapters (for example a USB RS-485 adapter) through the Supervisor. It
adds no `devices` entry, so no adapter has to exist for the add-on to start, and
it does not make the add-on privileged. Every family below is **disabled by
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

### Growatt BMS CAN (receive-only V1.04 observer)

| Option | Gateway flag | Default |
| --- | --- | --- |
| `growatt_bms_can_enabled` | `-growatt-bms-can-enabled` | `false` |
| `growatt_bms_can_interface` | `-growatt-bms-can-interface` | required when enabled; one SocketCAN interface name of 1-15 characters, without `/`, `:` or whitespace |
| `growatt_bms_can_listen_only_confirmed` | `-growatt-bms-can-listen-only-confirmed` | `false`; must be `true` when enabled |
| `growatt_bms_can_stale_after` | `-growatt-bms-can-stale-after` | `10s`, a positive duration |

The driver is **receive-only**: it reads frames from the named interface and has
no transmit, acknowledge, probe or interface-configuration path. These options
therefore do not set the CAN bit rate or controller mode and do not bring the
interface up. `growatt_bms_can_listen_only_confirmed` records your statement that
the controller is already in physical listen-only mode before the add-on opens
the interface; the add-on cannot verify it, and startup is refused while it is
`false`. The public [receive-only SocketCAN contract](https://github.com/Project-Helianthus/helianthus-docs-canbus/blob/main/contracts/socketcan-receive-only.md)
owns that precondition and the frame handling. The interface must already be
visible in the add-on's host network namespace (`host_network` is on).

`growatt_bms_can_stale_after` bounds the age of the oldest source frame of the
published tuple; an older tuple is withheld rather than served as current. The
`10s` value is an add-on starting value, not a value taken from the BMS
specification. Durations use the form `500ms` or `2s`.

The packaged gateway defines all four `-growatt-bms-can-*` flags, and the BOM
records them from that gateway build. Startup still probes each emitted flag and
stops with the missing flags named if the packaged binary lacks support; it never
starts without the CAN driver while reporting it enabled. Enabling the options
does not by itself establish that a particular battery is supported: that stays with the V1.04
qualification card, and the add-on makes no hardware claim.

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

## Complete option inventory

The schema is authoritative, including optional keys with no add-on default and
the legacy aliases retained pending their separate removal. This inventory maps
packaging reads and consumers; it establishes no protocol or hardware qualification.
Gateway capability probing and native admission remain authoritative. GraphQL
and MCP routing are preserved. The maintained [option map](../scripts/addon-option-map.json)
records exact source excerpts; the offline guard rejects inventory and source drift.
For endpoint fields, `[]` denotes each list entry. Defaults below are add-on
defaults only; “not set” means the schema has no default.

| Option | Add-on default | Startup consumer and behavior |
| --- | --- | --- |
| `adapter_direct_enabled` | true | Enable adapter-direct routing; rejects an external proxy endpoint and overrides transport, network and address. Consumer: `-transport`, `-network`, `-address`. |
| `adapter_direct_protocol` | not set | Select ENH or ENS for adapter-direct routing. Omitted values use ENH; an old proxy profile can supply the selector until explicitly persisted. Consumer: `-transport`, `-network`, `-address`. |
| `adapter_direct_address` | "" | Adapter endpoint or serial device path. Trim whitespace and the scheme; a serial protocol prefix must agree with the selector. Consumer: `-transport`, `-network`, `-address`. |
| `proxy_listen_addr` | "0.0.0.0:19001" | Gateway-integrated proxy listener address. Empty disables it; a configured listener requires gateway flag support. Consumer: `-proxy-listen`. |
| `transport` | "enh" | Transport input before adapter-direct or proxy overrides. Consumer: `-transport`, `-network`, `-address`. |
| `network` | "tcp" | Network input before adapter-direct or proxy overrides. Consumer: `-transport`, `-network`, `-address`. |
| `address` | "HOST:PORT" | Address input before adapter-direct or proxy overrides. Consumer: `-transport`, `-network`, `-address`. |
| `proxy_profile` | "disabled" | External proxy profile, disabled, ENH or ENS. Selects effective transport and address; legacy adapter-direct configuration is migrated in memory. Consumer: `-transport`, `-network`, `-address`. |
| `proxy_endpoint` | "" | External proxy endpoint, required for an active external proxy profile and forbidden with adapter-direct mode. Consumer: `-transport`, `-network`, `-address`. |
| `host` | "127.0.0.1" | Host label used only in logged HTTP URLs. Does not select the listener bind address. Consumer: Wrapper logging only. |
| `port` | 8080 | Legacy HTTP port alias. Overrides http_port when http_port is the default or this alias differs from its default. Consumer: `-http-addr`. |
| `path` | "/graphql" | Legacy GraphQL path alias. Overrides graphql_path when graphql_path is the default or this alias differs from its default. Consumer: `-graphql-path`. |
| `http_port` | 8080 | HTTP listener port, subject to the legacy port alias. Ingress is available on the declared Ingress port only. Consumer: `-http-addr`. |
| `graphql_path` | "/graphql" | GraphQL route, subject to the legacy path alias. Adds a leading slash and derives the default subscription route from it. Consumer: `-graphql-path`. |
| `subscription_path` | "/graphql/subscriptions" | Subscription route. Adds a leading slash; the default route follows a changed GraphQL route. Consumer: `-subscription-path`. |
| `mcp_path` | "/mcp" | MCP HTTP route; the wrapper adds a leading slash when absent. Consumer: `-mcp-path`. |
| `mdns` | true | Enable or disable gateway mDNS advertisement. Consumer: `-mdns`. |
| `mdns_instance` | "helianthus" | Gateway mDNS instance label. Consumer: `-mdns-instance`. |
| `broadcast` | true | Enable or disable gateway broadcast handling. Consumer: `-broadcast`. |
| `source_addr` | "auto" | Auto delegates source selection to the gateway. Explicit values use the ebusd-compatible source flag for that transport, otherwise require validate-only startup override support. Consumer: `-source-addr`, `-startup-source-override`, `-startup-source-override-validate`. |
| `scan_request_timeout` | "400ms" | Gateway scan request timeout; empty values use 400ms. Consumer: `-scan-request-timeout`. |
| `read_timeout` | "5s" | Gateway read timeout. Consumer: `-read-timeout`. |
| `write_timeout` | "5s" | Gateway write timeout. Consumer: `-write-timeout`. |
| `dial_timeout` | "5s" | Gateway dial timeout. Consumer: `-dial-timeout`. |
| `observe_first_enabled` | true | Gateway observe-first switch; missing values use true. Consumer: `-observe-first-enabled`. |
| `passive_state_direct_apply` | true | Gateway passive state direct-apply switch; missing values use true. Consumer: `-passive-state-direct-apply`. |
| `passive_config_direct_apply` | false | Gateway passive configuration direct-apply switch; missing values use false. Consumer: `-passive-config-direct-apply`. |
| `external_write_policy` | "record_only" | Gateway external write policy; missing values use record_only. Consumer: `-external-write-policy`. |
| `enable_static_seed_table` | false | Request the static seed table. Passed only when supported; an unsupported enabled request logs a warning. Consumer: `-enable-static-seed-table`. |
| `v8_classifier_mode` | "enforce" | Classifier mode, off, shadow or enforce; exported through the gateway environment. Missing values use enforce. Consumer: `HELIANTHUS_V8_CLASSIFIER_MODE`. |
| `eebus_enabled` | false | Enable the eeBUS argument bundle after validation and gateway support checks; pairing remains closed. Consumer: `-eebus-enabled`, `-eebus-listen-port`, `-eebus-interfaces`, `-eebus-subnets`, `-eebus-state-root`, `-eebus-discovery-enabled`, `-eebus-remote-ski-allowlist`, `-eebus-pairing-window-mode`. |
| `eebus_listen_port` | 4712 | eeBUS listener port, validated from 1 through 65535 when enabled. Consumer: `-eebus-listen-port`. |
| `eebus_interface` | "" | One explicit interface; validated and used for the gateway interface argument and stable machine identity derivation. Consumer: `-eebus-interfaces`. |
| `eebus_subnets` | "" | Nonempty prefix list, trimmed before the enabled eeBUS bundle is emitted. Consumer: `-eebus-subnets`. |
| `eebus_discovery_enabled` | true | Boolean discovery control emitted with the enabled eeBUS bundle. Consumer: `-eebus-discovery-enabled`. |
| `eebus_remote_ski_allowlist` | "" | Optional comma-separated remote SKI allowlist; every entry must be 40 hexadecimal characters. Consumer: `-eebus-remote-ski-allowlist`. |
| `modbus_tcp_enabled` | false | Enable validated Modbus TCP configuration. Select the scalar endpoint file or the endpoints document; disabled configuration emits no Modbus arguments. Consumer: `-modbus-tcp-enabled`, `-modbus-tcp-endpoint-file`, `-modbus-tcp-dial-timeout`, `-modbus-tcp-endpoints-file`. |
| `modbus_tcp_endpoint` | "" | Scalar Modbus TCP endpoint. Validated and written to a protected endpoint file; the gateway receives the file path only. Consumer: `-modbus-tcp-endpoint-file`. |
| `modbus_tcp_dial_timeout` | "5s" | Scalar Modbus dial timeout. Validated in the helper; a nonempty endpoint list requires this scalar to retain its default. Consumer: `-modbus-tcp-dial-timeout`. |
| `modbus_tcp_endpoints` | [] | Optional endpoint list. The helper validates and materializes one protected document; the gateway receives only its path. Consumer: `-modbus-tcp-endpoints-file`. |
| `m2m_graphql_enabled` | false | Enable the dedicated TLS GraphQL listener and validate its fixed TLS files. The optional Portal client bundle enables additional Portal arguments only when complete. Consumer: `-m2m-graphql-listen`, `-m2m-graphql-server-name`, `-m2m-graphql-server-cert`, `-m2m-graphql-server-key`, `-m2m-graphql-allowed-assets`, `-portal-pv-semantic-enabled`, `-portal-pv-m2m-url`, `-portal-pv-m2m-server-name`, `-portal-pv-m2m-ca`, `-portal-pv-m2m-client-cert`, `-portal-pv-m2m-client-key`, `-portal-pv-asset-ref`. |
| `m2m_graphql_server_name` | "" | TLS server identity, validated before startup; also supplied to the optional Portal client. Consumer: `-m2m-graphql-server-name`, `-portal-pv-m2m-server-name`. |
| `m2m_graphql_asset_ref` | "" | Opaque allowed asset reference; also supplied to the optional Portal client. Consumer: `-m2m-graphql-allowed-assets`, `-portal-pv-asset-ref`. |
| `growatt_bms_rs485_enabled` | false | Enable this family; disabled families emit no arguments. Consumer: `-growatt-bms-rs485-enabled`. |
| `growatt_bms_rs485_asset_id` | "" | Required opaque asset identity, distinct from source identity. Consumer: `-growatt-bms-rs485-asset-id`. |
| `growatt_bms_rs485_source_id` | "" | Required opaque source identity, distinct from asset identity. Consumer: `-growatt-bms-rs485-source-id`. |
| `growatt_bms_rs485_source_epoch` | "" | Required opaque source epoch label when the family is enabled. Consumer: `-growatt-bms-rs485-source-epoch`. |
| `growatt_bms_rs485_driver_generation` | not set | Required positive driver generation. Consumer: `-growatt-bms-rs485-driver-generation`. |
| `growatt_bms_rs485_unit_id` | not set | Required routed unit number from 1 through 247. Consumer: `-growatt-bms-rs485-unit-id`. |
| `growatt_bms_rs485_serial_path` | "" | Required serial device path under /dev/, without traversal or whitespace. Consumer: `-growatt-bms-rs485-serial-path`. |
| `growatt_bms_rs485_baud` | 9600 | Serial baud setting validated by the helper. Consumer: `-growatt-bms-rs485-baud`. |
| `growatt_bms_rs485_parity` | "none" | Serial parity: none, even or odd. Consumer: `-growatt-bms-rs485-parity`. |
| `growatt_bms_rs485_stop_bits` | 1 | Serial stop bits, 1 or 2. Consumer: `-growatt-bms-rs485-stop-bits`. |
| `growatt_bms_rs485_response_timeout` | "500ms" | Positive response timeout in milliseconds or seconds. Consumer: `-growatt-bms-rs485-response-timeout`. |
| `growatt_bms_rs485_max_response_delay` | "250ms" | Positive maximum response delay in milliseconds or seconds. Consumer: `-growatt-bms-rs485-max-response-delay`. |
| `growatt_bms_rs485_max_quiescence` | "2s" | Positive quiescence duration, greater than the response delay. Consumer: `-growatt-bms-rs485-max-quiescence`. |
| `growatt_bms_can_enabled` | false | Enable this family; disabled families emit no arguments. Consumer: `-growatt-bms-can-enabled`. |
| `growatt_bms_can_interface` | "" | One interface name validated by the helper; enabled CAN families require distinct interfaces. Consumer: `-growatt-bms-can-interface`. |
| `growatt_bms_can_listen_only_confirmed` | false | Record the external listen-only precondition; must be true when enabled. The helper does not configure or verify controller mode. Consumer: `-growatt-bms-can-listen-only-confirmed`. |
| `growatt_bms_can_stale_after` | "10s" | Positive staleness duration, validated by the helper. Consumer: `-growatt-bms-can-stale-after`. |
| `growatt_bms_pcs_can_enabled` | false | Enable this family; disabled families emit no arguments. Consumer: `-growatt-bms-pcs-can-enabled`. |
| `growatt_bms_pcs_can_interface` | "" | One interface name validated by the helper; enabled CAN families require distinct interfaces. Consumer: `-growatt-bms-pcs-can-interface`. |
| `growatt_bms_pcs_can_listen_only_confirmed` | false | Record the external listen-only precondition; must be true when enabled. The helper does not configure or verify controller mode. Consumer: `-growatt-bms-pcs-can-listen-only-confirmed`. |
| `growatt_bms_pcs_can_stale_after` | "" | Positive staleness duration, validated by the helper. Consumer: `-growatt-bms-pcs-can-stale-after`. |
| `growatt_bms_pcs_can_project_code` | "" | Explicit project selection, syntax-checked without inferring native support. Consumer: `-growatt-bms-pcs-can-project-code`. |
| `growatt_bms_pcs_can_release` | "" | Explicit release selection, syntax-checked without inferring native support. Consumer: `-growatt-bms-pcs-can-release`. |
| `growatt_bms_pcs_can_native_profile` | "" | Explicit native profile selection, validated by the helper; native admission remains with the gateway. Consumer: `-growatt-bms-pcs-can-native-profile`. |
| `growatt_bms_pcs_can_scope` | "" | Explicit scope, checked against the family selections. Consumer: `-growatt-bms-pcs-can-scope`. |
| `growatt_bms_pcs_can_bank` | "" | Explicit bank selection; must agree with the selected profile. Consumer: `-growatt-bms-pcs-can-bank`. |
| `growatt_bms_pcs_can_context` | "" | Explicit bounded JSON context, validated by the helper and passed unchanged for native admission. Consumer: `-growatt-bms-pcs-can-context`. |
| `growatt_bms_pcs_can_native_contract` | "" | Optional exact native contract selection; native admission remains with the gateway. Consumer: `-growatt-bms-pcs-can-native-contract`. |
| `growatt_bms_link_can_enabled` | false | Enable this family; disabled families emit no arguments. Consumer: `-growatt-bms-link-can-enabled`. |
| `growatt_bms_link_can_interface` | "" | One interface name validated by the helper; enabled CAN families require distinct interfaces. Consumer: `-growatt-bms-link-can-interface`. |
| `growatt_bms_link_can_listen_only_confirmed` | false | Record the external listen-only precondition; must be true when enabled. The helper does not configure or verify controller mode. Consumer: `-growatt-bms-link-can-listen-only-confirmed`. |
| `growatt_bms_link_can_stale_after` | "" | Positive staleness duration, validated by the helper. Consumer: `-growatt-bms-link-can-stale-after`. |
| `growatt_bms_link_can_project_code` | "" | Explicit project selection, syntax-checked without inferring native support. Consumer: `-growatt-bms-link-can-project-code`. |
| `growatt_bms_link_can_release` | "" | Explicit release selection, syntax-checked without inferring native support. Consumer: `-growatt-bms-link-can-release`. |
| `growatt_bms_link_can_native_profile` | "" | Explicit native profile selection, validated by the helper; native admission remains with the gateway. Consumer: `-growatt-bms-link-can-native-profile`. |
| `growatt_bms_link_can_scope` | "" | Explicit scope, checked against the family selections. Consumer: `-growatt-bms-link-can-scope`. |
| `growatt_bms_link_can_bank` | "" | Explicit bank selection; must agree with the selected profile. Consumer: `-growatt-bms-link-can-bank`. |
| `growatt_bms_link_can_context` | "" | Explicit bounded JSON context, validated by the helper and passed unchanged for native admission. Consumer: `-growatt-bms-link-can-context`. |
| `growatt_bms_link_can_source_selectors` | "" | Explicit bounded JSON source selections, validated by the helper and passed unchanged for native admission. Consumer: `-growatt-bms-link-can-source-selectors`. |
| `tesla_gen3_hsc_retained_enabled` | false | Enable the retained identity owner; disabled emits no arguments. Consumer: `-tesla-gen3-hsc-retained-enabled`. |
| `tesla_gen3_hsc_endpoint_id` | "" | Required opaque endpoint id label when the family is enabled. Consumer: `-tesla-gen3-hsc-endpoint-id`. |
| `tesla_gen3_hsc_asset_id` | "" | Required opaque asset identity, distinct from source identity. Consumer: `-tesla-gen3-hsc-asset-id`. |
| `tesla_gen3_hsc_source_id` | "" | Required opaque source identity, distinct from asset identity. Consumer: `-tesla-gen3-hsc-source-id`. |
| `tesla_gen3_hsc_source_epoch` | "" | Required opaque source epoch label when the family is enabled. Consumer: `-tesla-gen3-hsc-source-epoch`. |
| `tesla_gen3_hsc_clock_epoch` | "" | Required opaque clock epoch label when the family is enabled. Consumer: `-tesla-gen3-hsc-clock-epoch`. |
| `tesla_gen3_hsc_evse_id` | "" | Required opaque evse id label when the family is enabled. Consumer: `-tesla-gen3-hsc-evse-id`. |
| `tesla_gen3_hsc_connector_id` | "" | Required opaque connector id label when the family is enabled. Consumer: `-tesla-gen3-hsc-connector-id`. |
| `tesla_gen3_hsc_driver_generation` | not set | Required positive driver generation. Consumer: `-tesla-gen3-hsc-driver-generation`. |
| `tesla_gen3_hsc_node` | not set | Required node label from 1 through 247. Consumer: `-tesla-gen3-hsc-node`. |
| `modbus_tcp_endpoints[].label` | not set | Public identifier, unique in the list; validated before becoming the driver identity. Consumer: `-modbus-tcp-endpoints-file`. |
| `modbus_tcp_endpoints[].family` | not set | Exact declared family; no other family is tried. Configuration acceptance does not establish qualification. Consumer: `-modbus-tcp-endpoints-file`. |
| `modbus_tcp_endpoints[].endpoint` | not set | Validated endpoint, kept in the protected document and excluded from process arguments. Consumer: `-modbus-tcp-endpoints-file`. |
| `modbus_tcp_endpoints[].dial_timeout` | not set | Optional validated timeout; retained in the endpoints document. Consumer: `-modbus-tcp-endpoints-file`. |
| `modbus_tcp_endpoints[].units` | not set | Optional distinct routed-unit allowlist; narrows family routing. Consumer: `-modbus-tcp-endpoints-file`. |
| `modbus_tcp_endpoints[].pacing_gap_ms` | not set | Optional validated pacing gap ms value, written under pacing in the endpoints document. Consumer: `-modbus-tcp-endpoints-file`. |
| `modbus_tcp_endpoints[].pacing_settle_ms` | not set | Optional validated pacing settle ms value, written under pacing in the endpoints document. Consumer: `-modbus-tcp-endpoints-file`. |
| `modbus_tcp_endpoints[].pacing_cycle_s` | not set | Optional validated pacing cycle s value, written under pacing in the endpoints document. Consumer: `-modbus-tcp-endpoints-file`. |
| `modbus_tcp_endpoints[].pacing_backoff_floor_s` | not set | Optional validated pacing backoff floor s value, written under pacing in the endpoints document. Consumer: `-modbus-tcp-endpoints-file`. |
| `modbus_tcp_endpoints[].pacing_backoff_ceiling_s` | not set | Optional validated pacing backoff ceiling s value, written under pacing in the endpoints document. Consumer: `-modbus-tcp-endpoints-file`. |
