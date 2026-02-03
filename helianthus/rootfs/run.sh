#!/usr/bin/with-contenv bashio

set -euo pipefail

transport=$(bashio::config 'transport')
network=$(bashio::config 'network')
address=$(bashio::config 'address')
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

http_addr="0.0.0.0:${http_port}"

bashio::log.info "Starting Helianthus gateway on ${http_addr}"

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
