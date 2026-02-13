#!/usr/bin/with-contenv bashio

set -euo pipefail

transport=$(bashio::config 'transport')
network=$(bashio::config 'network')
address=$(bashio::config 'address')
proxy_profile=$(bashio::config 'proxy_profile')
proxy_endpoint=$(bashio::config 'proxy_endpoint')
host=$(bashio::config 'host')
port=$(bashio::config 'port')
path=$(bashio::config 'path')
http_port=$(bashio::config 'http_port')
graphql_path=$(bashio::config 'graphql_path')
subscription_path=$(bashio::config 'subscription_path')
mcp_path=$(bashio::config 'mcp_path')
mdns=$(bashio::config 'mdns')
mdns_instance=$(bashio::config 'mdns_instance')
broadcast=$(bashio::config 'broadcast')
read_timeout=$(bashio::config 'read_timeout')
write_timeout=$(bashio::config 'write_timeout')
dial_timeout=$(bashio::config 'dial_timeout')

effective_transport="${transport}"
effective_network="${network}"
effective_address="${address}"

proxy_profile=$(printf '%s' "${proxy_profile}" | tr '[:upper:]' '[:lower:]')
proxy_endpoint_trimmed=$(printf '%s' "${proxy_endpoint}" | sed -E 's/^[[:space:]]+//; s/[[:space:]]+$//')

case "${proxy_profile}" in
  "" | disabled)
    proxy_profile="disabled"
    ;;
  enh | ens)
    if [ -z "${proxy_endpoint_trimmed}" ]; then
      bashio::exit.nok "proxy_endpoint is required when proxy_profile=${proxy_profile}"
    fi
    if [[ "${proxy_endpoint_trimmed}" == *"://"* ]]; then
      effective_address="${proxy_endpoint_trimmed}"
    else
      effective_address="${proxy_profile}://${proxy_endpoint_trimmed}"
    fi
    effective_transport="${proxy_profile}"
    effective_network="tcp"
    ;;
  *)
    bashio::exit.nok "proxy_profile must be one of: disabled, enh, ens"
    ;;
esac

proxy_endpoint_marker="(none)"
if [ -n "${proxy_endpoint_trimmed}" ]; then
  proxy_endpoint_marker="${proxy_endpoint_trimmed}"
fi
if [ "${proxy_profile}" = "enh" ] || [ "${proxy_profile}" = "ens" ]; then
  proxy_endpoint_marker="${effective_address}"
fi

if [ -z "${http_port}" ]; then
  http_port=8080
fi

if [ -n "${port}" ] && { [ "${http_port}" = "8080" ] || [ "${port}" != "8080" ]; }; then
  http_port="${port}"
fi

if [ -z "${path}" ]; then
  path="${graphql_path}"
fi

if [ -n "${path}" ] && { [ "${graphql_path}" = "/graphql" ] || [ "${path}" != "/graphql" ]; }; then
  graphql_path="${path}"
fi

if [ -z "${host}" ]; then
  host="127.0.0.1"
fi

if [ "${graphql_path#/}" = "${graphql_path}" ]; then
  graphql_path="/${graphql_path}"
fi

if [ "${subscription_path#/}" = "${subscription_path}" ]; then
  subscription_path="/${subscription_path}"
fi

if [ "${mcp_path#/}" = "${mcp_path}" ]; then
  mcp_path="/${mcp_path}"
fi

if [ "${subscription_path}" = "/graphql/subscriptions" ] && [ "${graphql_path}" != "/graphql" ]; then
  subscription_path="${graphql_path%/}/subscriptions"
fi

http_addr="0.0.0.0:${http_port}"

bashio::log.info "Starting Helianthus gateway"
bashio::log.info "Transport: ${effective_transport} (${effective_network} ${effective_address})"
bashio::log.info "Proxy profile: ${proxy_profile}"
bashio::log.info "Proxy endpoint: ${proxy_endpoint_marker}"
bashio::log.info "HTTP listen: ${http_addr}"
bashio::log.info "GraphQL endpoint: http://${host}:${http_port}${graphql_path}"
bashio::log.info "Subscriptions endpoint: http://${host}:${http_port}${subscription_path}"
bashio::log.info "MCP endpoint: http://${host}:${http_port}${mcp_path}"
bashio::log.info "mDNS: enabled=${mdns} instance=${mdns_instance}"

exec /usr/local/bin/helianthus-gateway \
  -transport "${effective_transport}" \
  -network "${effective_network}" \
  -address "${effective_address}" \
  -http-addr "${http_addr}" \
  -graphql-path "${graphql_path}" \
  -subscription-path "${subscription_path}" \
  -mcp-path "${mcp_path}" \
  -mdns="${mdns}" \
  -mdns-instance "${mdns_instance}" \
  -broadcast="${broadcast}" \
  -read-timeout "${read_timeout}" \
  -write-timeout "${write_timeout}" \
  -dial-timeout "${dial_timeout}"
