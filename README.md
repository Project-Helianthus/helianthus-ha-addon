# helianthus-ha-addon

Home Assistant add-on repository for Helianthus.  
This repo packages and runs `helianthus-ebusgateway` inside a Supervisor add-on container and exposes GraphQL/MCP endpoints to your HA environment.

## What this add-on does

- Runs the Helianthus gateway binary (`helianthus-gateway`) in an HA add-on container
- Connects gateway runtime to an external eBUS transport (`enh`, `ens`, or `ebusd-tcp`)
- Exposes HTTP API endpoints:
  - GraphQL
  - GraphQL subscriptions
  - MCP
- Optionally advertises GraphQL via mDNS (`_helianthus-graphql._tcp`)

Repository layout:

- `repository.json`: add-on repository metadata for HA
- `helianthus/config.json`: add-on manifest, defaults, option schema
- `helianthus/rootfs/run.sh`: runtime option mapping + gateway startup command
- `helianthus/Dockerfile`: image build (installs `github.com/d3vi1/helianthus-ebusgateway/cmd/gateway`)

## Prerequisites

- Home Assistant OS/Supervised with add-on support
- Network reachability from HA host/add-on container to your transport endpoint:
  - TCP adapter/service endpoint (typical)
  - or unix socket path available in container namespace (advanced)
- For maintainers building images from source: GitHub token access to private `github.com/d3vi1/*` modules

## Install and run (operators)

Add repository:

```bash
ha addons repo add https://github.com/d3vi1/helianthus-ha-addon
```

Then in Home Assistant:

1. Open **Settings → Add-ons → Add-on Store**
2. Install **Helianthus**
3. Configure options (see below)
4. Start the add-on
5. Check logs for computed endpoints and transport details

Minimal TCP example (common):

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

## Configuration reference

Runtime transport options:

- `transport`: `enh` | `ens` | `ebusd-tcp`
- `network`: `tcp` | `unix`
- `address`: transport address (`HOST:PORT` for TCP or socket path for unix)
- `read_timeout`, `write_timeout`, `dial_timeout`: transport timeout strings (for example `5s`)
- `broadcast`: enables gateway broadcast listener on a second connection

HTTP/API options:

- `http_port`: HTTP listen port (gateway binds `0.0.0.0:<http_port>`)
- `graphql_path`: GraphQL path
- `subscription_path`: subscription path
- `mcp_path`: MCP path

Compatibility aliases (still supported in options):

- `port`: alias for `http_port`
- `path`: alias for `graphql_path`
- `host`: used for startup endpoint log messages (does not change bind address)

mDNS options:

- `mdns`: enable/disable advertisement
- `mdns_instance`: instance name for `_helianthus-graphql._tcp`

## Runtime endpoints and path behavior

The startup script normalizes endpoint paths to include a leading `/` and prints resolved URLs in logs:

- GraphQL: `http://<host>:<http_port><graphql_path>`
- Subscriptions: `http://<host>:<http_port><subscription_path>`
- MCP: `http://<host>:<http_port><mcp_path>`

Operational mapping notes from `run.sh`:

- `port` can override `http_port` for compatibility with older configs
- `path` can override `graphql_path` for compatibility with older configs
- If `graphql_path` is changed and `subscription_path` is still default (`/graphql/subscriptions`), it auto-derives to `<graphql_path>/subscriptions`

## Build/deploy flow (maintainers)

### Local image build

From repo root:

```bash
docker build -f helianthus/Dockerfile helianthus
```

If private module auth is needed, pass BuildKit secret `github_token` (same secret ID used in Dockerfile).

### CI and published artifacts

GitHub Actions workflow: `.github/workflows/build.yml`

- Triggered on:
  - push to `main`
  - tag push `v*`
  - manual `workflow_dispatch`
- Builds and pushes per-arch images:
  - `ghcr.io/d3vi1/helianthus-ha-addon:latest-<arch>`
  - `ghcr.io/d3vi1/helianthus-ha-addon:<sha>-<arch>`
- Creates multi-arch manifests:
  - `ghcr.io/d3vi1/helianthus-ha-addon:latest`
  - `ghcr.io/d3vi1/helianthus-ha-addon:<sha>`

## Operational notes

- Add-on uses `host_network: true` in `helianthus/config.json`.
- Default exposed port is `8080/tcp`.
- This repository is packaging/runtime glue only; gateway feature behavior lives in `helianthus-ebusgateway`.

## Troubleshooting

- Add-on starts but no data: verify `transport`/`network`/`address` match your real backend endpoint.
- Connection errors in logs: check reachability, firewall, and endpoint availability.
- Endpoints differ from expected: verify `http_port`, `graphql_path`, `subscription_path`, `mcp_path` and compatibility alias values (`port`, `path`).
- mDNS discovery not visible: ensure `mdns=true`, multicast is allowed on network, and check container logs.
- Build failures on CI/local with module fetch errors: verify token permissions for private `github.com/d3vi1/*` dependencies.

## Related links

- Helianthus gateway runtime: https://github.com/d3vi1/helianthus-ebusgateway
- Helianthus eBUS docs: https://github.com/d3vi1/helianthus-docs-ebus
- Issue tracking this README pass: https://github.com/d3vi1/helianthus-ha-addon/issues/18
