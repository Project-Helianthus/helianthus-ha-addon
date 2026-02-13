# helianthus-ha-addon

Home Assistant add-on repository for Helianthus.
This add-on runs `helianthus-gateway` in a Supervisor container and exposes GraphQL/MCP endpoints to Home Assistant operators.

## What this add-on does

- Runs `helianthus-gateway` inside a Home Assistant add-on container
- Connects runtime to an external eBUS transport (`enh`, `ens`, or `ebusd-tcp`)
- Serves HTTP endpoints for GraphQL, GraphQL subscriptions, and MCP
- Optionally advertises GraphQL over mDNS (`_helianthus-graphql._tcp`)

Repository layout:

- `repository.json`: add-on repository metadata
- `helianthus/config.json`: add-on manifest, defaults, and options schema
- `helianthus/rootfs/run.sh`: config-to-runtime mapping and startup command
- `helianthus/Dockerfile`: image build (installs `github.com/d3vi1/helianthus-ebusgateway/cmd/gateway`)

## Install and start (operators)

```bash
ha addons repo add https://github.com/d3vi1/helianthus-ha-addon
```

Then in Home Assistant:

1. Open **Settings → Add-ons → Add-on Store**
2. Install **Helianthus**
3. Set configuration values (matrix below)
4. Start the add-on
5. Verify logs and endpoint health (flow below)

Common TCP baseline:

```yaml
transport: enh
network: tcp
address: 192.168.100.2:9999
http_port: 8080
graphql_path: /graphql
subscription_path: /graphql/subscriptions
mcp_path: /mcp
mdns: true
```

## Operator config matrix (source: `helianthus/config.json`)

| Option | Schema type | Default | Operator action | Runtime notes |
| --- | --- | --- | --- | --- |
| `transport` | `list(enh\|ens\|ebusd-tcp)` | `enh` | Set to your backend protocol | Passed to `-transport` |
| `network` | `list(tcp\|unix)` | `tcp` | Match your endpoint type | Passed to `-network` |
| `address` | `str` | `HOST:PORT` | **Required:** replace placeholder with real endpoint/socket | Passed to `-address`; placeholder is not operational |
| `host` | `str` | `127.0.0.1` | Optional | Used for startup endpoint log URLs only; does not change bind address |
| `port` | `int` | `8080` | Optional compatibility alias | Can override `http_port` (legacy key support) |
| `path` | `str` | `/graphql` | Optional compatibility alias | Can override `graphql_path` (legacy key support) |
| `http_port` | `int` | `8080` | Set API listen port | Gateway listens on `0.0.0.0:<http_port>` |
| `graphql_path` | `str` | `/graphql` | Set GraphQL route | Auto-normalized to include leading `/` |
| `subscription_path` | `str` | `/graphql/subscriptions` | Usually keep default unless custom route needed | Auto-normalized; auto-derived to `<graphql_path>/subscriptions` when still default and `graphql_path` changes |
| `mcp_path` | `str` | `/mcp` | Set MCP route | Auto-normalized to include leading `/` |
| `mdns` | `bool` | `true` | Disable if mDNS is not needed | Passed to `-mdns` |
| `mdns_instance` | `str` | `helianthus` | Set service instance label | Passed to `-mdns-instance` |
| `broadcast` | `bool` | `false` | Enable only when backend requires broadcast listener | Passed to `-broadcast` |
| `read_timeout` | `str` | `5s` | Optional tuning | Passed to `-read-timeout` |
| `write_timeout` | `str` | `5s` | Optional tuning | Passed to `-write-timeout` |
| `dial_timeout` | `str` | `5s` | Optional tuning | Passed to `-dial-timeout` |

Compatibility precedence from `run.sh`:

- `port` may override `http_port` for legacy configs
- `path` may override `graphql_path` for legacy configs
- if `graphql_path` changes and `subscription_path` stays default, runtime derives `<graphql_path>/subscriptions`

## Compatibility and runtime assumptions

- Home Assistant OS or Home Assistant Supervised with Supervisor add-on support
- Add-on runs with `host_network: true` and `startup: services` / `boot: auto`
- Supported add-on architectures: `aarch64`, `amd64`, `armhf`, `armv7`, `i386`
- Container must reach the configured transport endpoint (`tcp` host:port or `unix` socket path in-container)
- Runtime listens on `0.0.0.0:<http_port>`; startup logs print URLs using `host`
- `ports` metadata exposes `8080/tcp`; with host networking, effective reachability is host-network dependent

## Upgrade / rollback checklist

Before upgrade:

1. Copy current add-on configuration from the Home Assistant UI
2. Create a Home Assistant backup that includes the Helianthus add-on
3. Capture baseline logs (`ha addons logs helianthus`) for later diff if needed

Upgrade:

1. Update add-on from the Add-on Store
2. Start add-on and wait for startup markers in logs
3. Run the post-install health-check flow below

Rollback (if health-check fails):

1. Stop the add-on
2. Restore the pre-upgrade Home Assistant backup (preferred)
3. If backup restore is unavailable, reinstall the previous add-on version (if offered) and reapply saved config
4. Start add-on and rerun health-check flow

## Post-install smoke health-check flow

Use your configured host/port/path values in commands below.

1. Confirm startup markers:
   - `Starting Helianthus gateway`
   - `Transport: ...`
   - `GraphQL endpoint: ...`
   - `Subscriptions endpoint: ...`
   - `MCP endpoint: ...`
2. Check GraphQL:

```bash
curl -fsS -X POST "http://127.0.0.1:8080/graphql" \
  -H "content-type: application/json" \
  -d '{"query":"{ __typename }","variables":{}}'
```

3. Check MCP:

```bash
curl -fsS -X POST "http://127.0.0.1:8080/mcp" \
  -H "content-type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}'
```

4. Optional deterministic smoke checker:

```bash
ha addons logs helianthus > /tmp/helianthus-addon.log
python3 scripts/smoke_addon_checklist.py --log-file /tmp/helianthus-addon.log --address 192.168.100.2:9999
```

Expected result: `OVERALL PASS`

## Build/deploy flow (maintainers)

### Local image build

From repository root:

```bash
docker build -f helianthus/Dockerfile helianthus
```

For private module access, pass BuildKit secret `github_token` (same secret ID used in `helianthus/Dockerfile`).

### CI and published artifacts

Workflow: `.github/workflows/build.yml`

- Triggers on `main` pushes, `v*` tags, and `workflow_dispatch`
- Builds per-arch images (`latest-<arch>` and `<sha>-<arch>`)
- Publishes multi-arch manifests (`latest` and `<sha>`)

## Troubleshooting

- No data: verify `transport`, `network`, and `address` match your live backend
- Endpoint mismatch: verify `http_port`, `graphql_path`, `subscription_path`, `mcp_path`, and alias keys (`port`, `path`)
- mDNS missing: verify `mdns=true`, multicast availability, and startup log lines
- Connection errors: verify backend service health, routing, and firewall rules
- Build module fetch errors: verify token permissions for private `github.com/d3vi1/*` dependencies

## Related links

- Helianthus gateway runtime: https://github.com/d3vi1/helianthus-ebusgateway
- Helianthus eBUS docs: https://github.com/d3vi1/helianthus-docs-ebus
- Operator smoke runbook: `SMOKE_RUNBOOK.md`
- Issue tracking this README pass: https://github.com/d3vi1/helianthus-ha-addon/issues/28
