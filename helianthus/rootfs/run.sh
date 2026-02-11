#!/usr/bin/with-contenv bashio

set -euo pipefail

transport=$(bashio::config 'transport')
network=$(bashio::config 'network')
address=$(bashio::config 'address')
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
bashio::log.info "Transport: ${transport} (${network} ${address})"
bashio::log.info "HTTP listen: ${http_addr}"
bashio::log.info "GraphQL endpoint: http://${host}:${http_port}${graphql_path}"
bashio::log.info "Subscriptions endpoint: http://${host}:${http_port}${subscription_path}"
bashio::log.info "MCP endpoint: http://${host}:${http_port}${mcp_path}"
bashio::log.info "mDNS: enabled=${mdns} instance=${mdns_instance}"

exec /usr/local/bin/helianthus-gateway \
  -transport "${transport}" \
  -network "${network}" \
  -address "${address}" \
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
