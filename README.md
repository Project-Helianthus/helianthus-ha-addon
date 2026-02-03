# Helianthus Home Assistant Add-on

Home Assistant add-on that runs the Helianthus eBUS gateway (GraphQL + MCP).

## Status

- Builds and runs `helianthus-ebusgateway`
- Exposes GraphQL + MCP over HTTP
- Advertises `_helianthus-graphql._tcp` via mDNS (optional)

## Defaults

- GraphQL: `http://<host>:8080/graphql`
- Subscriptions: `http://<host>:8080/graphql/subscriptions`
- MCP: `http://<host>:8080/mcp`

## Configuration

Key options are exposed in `config.json`:

- `transport`: `enh` or `ens`
- `network`: `tcp` or `unix`
- `address`: transport address (e.g. `192.168.100.2:9999`)
- `http_port`: HTTP listen port
- `mdns`: enable/disable mDNS advertisement
