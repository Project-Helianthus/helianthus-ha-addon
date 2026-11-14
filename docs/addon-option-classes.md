# Add-on option classes

Every add-on option is either a **bootstrap** option, which the host keeps
because the gateway needs it before the Portal opens or because no Portal
configuration member owns it, or a **portal** option, whose ordinary choice a
member of the gateway Portal configuration record owns. The
[option map](https://github.com/Project-Helianthus/helianthus-ha-addon/blob/main/scripts/addon-option-map.json)
records the class of each option, with a bootstrap reason or the owning Portal
key, and `scripts/check_addon_options.py` rejects an unclassified option, an
unknown reason, a Portal key that the gateway contract does not define and any
drift between the map and the table below.

This classification changes no option, default or startup behavior. Every option
keeps its current wiring; removing Portal-managed options from ordinary setup is
separate work. It establishes no protocol, hardware or installation
qualification.

## Portal options

Portal keys are members of the gateway
[Portal configuration record](https://github.com/Project-Helianthus/helianthus-ebusgateway/blob/main/docs/architecture/portal-config-sharing.md):
`drivers[<driver>].enabled` for each editable driver (`ebus.primary`,
`eebus.primary`, `growatt.bms.rs485` and `modbus.sunspec`), `sharing.graphql`,
`sharing.mcp`, `adapter_proxy` and `output_bindings.matter`. The guard keeps
this set closed; `--portal-docs <gateway docs directory>` rederives it from
that contract and fails on any difference.

A portal option's add-on value remains host eligibility. The gateway seeds its
initial record from it; after a saved Portal edit, an unselected driver is not
constructed at the next start, and a selected driver never widens a host-disabled
option. Saving in the Portal does not start, stop or restart a driver.

Record members without an add-on option: `drivers[ebus.primary].enabled` (the
eBUS driver is always host-enabled), `sharing.graphql` and `sharing.mcp` (the
host keeps the routes, see `paths`), `adapter_proxy` (the host keeps the
listener, see `proxy_listen_addr`) and `output_bindings.matter` (the add-on
builds no Matter output). The gateway reports these sharing, proxy and output
choices as desired only; they do not open or close a host listener.

## Bootstrap reasons

| Reason | Why the host keeps the option |
| --- | --- |
| `listener` | Binds, advertises or labels a host listener (HTTP, adapter proxy, eeBUS, dedicated TLS GraphQL, mDNS). The listener must exist before the Portal can open, and the Portal record selects exposure only within host-provisioned listeners. |
| `transport` | Bootstraps an adapter or device connection: adapter location, transport and protocol, serial or CAN wiring, Modbus TCP endpoints and their timeouts and pacing. The Portal record has no adapter member yet, so adapter selection stays with the host. |
| `identity` | Sets an identity the gateway carries across restarts: bus source address, advertised instance label, asset, source, endpoint, epoch and generation labels, routed unit numbers, TLS server identity and trust allowlists. |
| `paths` | Mounts an HTTP route (GraphQL, subscription, MCP). The Portal sharing choices apply only within routes the host provisions. |
| `native-policy` | Tunes native observation, write, cache or classifier policy, or selects a native profile, contract, family or freshness bound. The gateway keeps these as host settings and the Portal record rejects such members. |
| `unmanaged-driver` | Enables a driver outside the Portal record's editable driver set, so no Portal member can own its enablement. |

## Classification

| Option | Class | Reason or Portal key |
| --- | --- | --- |
| `adapter_direct_enabled` | bootstrap | `transport` |
| `adapter_direct_protocol` | bootstrap | `transport` |
| `adapter_direct_address` | bootstrap | `transport` |
| `proxy_listen_addr` | bootstrap | `listener` |
| `transport` | bootstrap | `transport` |
| `network` | bootstrap | `transport` |
| `address` | bootstrap | `transport` |
| `proxy_profile` | bootstrap | `transport` |
| `proxy_endpoint` | bootstrap | `transport` |
| `host` | bootstrap | `listener` |
| `http_port` | bootstrap | `listener` |
| `graphql_path` | bootstrap | `paths` |
| `subscription_path` | bootstrap | `paths` |
| `mcp_path` | bootstrap | `paths` |
| `mdns` | bootstrap | `listener` |
| `mdns_instance` | bootstrap | `identity` |
| `broadcast` | bootstrap | `native-policy` |
| `source_addr` | bootstrap | `identity` |
| `scan_request_timeout` | bootstrap | `transport` |
| `read_timeout` | bootstrap | `transport` |
| `write_timeout` | bootstrap | `transport` |
| `dial_timeout` | bootstrap | `transport` |
| `adapter_mux_idle_release_grace` | bootstrap | `transport` |
| `adapter_mux_max_ownership_duration` | bootstrap | `transport` |
| `adapter_mux_read_timeout` | bootstrap | `transport` |
| `observe_first_enabled` | bootstrap | `native-policy` |
| `passive_state_direct_apply` | bootstrap | `native-policy` |
| `passive_config_direct_apply` | bootstrap | `native-policy` |
| `external_write_policy` | bootstrap | `native-policy` |
| `enable_static_seed_table` | bootstrap | `native-policy` |
| `v8_classifier_mode` | bootstrap | `native-policy` |
| `eebus_enabled` | portal | `drivers[eebus.primary].enabled` |
| `eebus_listen_port` | bootstrap | `listener` |
| `eebus_interface` | bootstrap | `listener` |
| `eebus_subnets` | bootstrap | `listener` |
| `eebus_discovery_enabled` | bootstrap | `listener` |
| `eebus_remote_ski_allowlist` | bootstrap | `identity` |
| `modbus_tcp_enabled` | portal | `drivers[modbus.sunspec].enabled` |
| `modbus_tcp_endpoint` | bootstrap | `transport` |
| `modbus_tcp_dial_timeout` | bootstrap | `transport` |
| `modbus_tcp_endpoints` | bootstrap | `transport` |
| `m2m_graphql_enabled` | bootstrap | `listener` |
| `m2m_graphql_server_name` | bootstrap | `identity` |
| `m2m_graphql_asset_ref` | bootstrap | `identity` |
| `growatt_bms_rs485_enabled` | portal | `drivers[growatt.bms.rs485].enabled` |
| `growatt_bms_rs485_asset_id` | bootstrap | `identity` |
| `growatt_bms_rs485_source_id` | bootstrap | `identity` |
| `growatt_bms_rs485_source_epoch` | bootstrap | `identity` |
| `growatt_bms_rs485_driver_generation` | bootstrap | `identity` |
| `growatt_bms_rs485_unit_id` | bootstrap | `identity` |
| `growatt_bms_rs485_serial_path` | bootstrap | `transport` |
| `growatt_bms_rs485_baud` | bootstrap | `transport` |
| `growatt_bms_rs485_parity` | bootstrap | `transport` |
| `growatt_bms_rs485_stop_bits` | bootstrap | `transport` |
| `growatt_bms_rs485_response_timeout` | bootstrap | `transport` |
| `growatt_bms_rs485_max_response_delay` | bootstrap | `transport` |
| `growatt_bms_rs485_max_quiescence` | bootstrap | `transport` |
| `growatt_bms_can_enabled` | bootstrap | `unmanaged-driver` |
| `growatt_bms_can_interface` | bootstrap | `transport` |
| `growatt_bms_can_listen_only_confirmed` | bootstrap | `transport` |
| `growatt_bms_can_stale_after` | bootstrap | `native-policy` |
| `growatt_bms_pcs_can_enabled` | bootstrap | `unmanaged-driver` |
| `growatt_bms_pcs_can_interface` | bootstrap | `transport` |
| `growatt_bms_pcs_can_listen_only_confirmed` | bootstrap | `transport` |
| `growatt_bms_pcs_can_stale_after` | bootstrap | `native-policy` |
| `growatt_bms_pcs_can_project_code` | bootstrap | `native-policy` |
| `growatt_bms_pcs_can_release` | bootstrap | `native-policy` |
| `growatt_bms_pcs_can_native_profile` | bootstrap | `native-policy` |
| `growatt_bms_pcs_can_scope` | bootstrap | `native-policy` |
| `growatt_bms_pcs_can_bank` | bootstrap | `native-policy` |
| `growatt_bms_pcs_can_context` | bootstrap | `native-policy` |
| `growatt_bms_pcs_can_native_contract` | bootstrap | `native-policy` |
| `growatt_bms_link_can_enabled` | bootstrap | `unmanaged-driver` |
| `growatt_bms_link_can_interface` | bootstrap | `transport` |
| `growatt_bms_link_can_listen_only_confirmed` | bootstrap | `transport` |
| `growatt_bms_link_can_stale_after` | bootstrap | `native-policy` |
| `growatt_bms_link_can_project_code` | bootstrap | `native-policy` |
| `growatt_bms_link_can_release` | bootstrap | `native-policy` |
| `growatt_bms_link_can_native_profile` | bootstrap | `native-policy` |
| `growatt_bms_link_can_scope` | bootstrap | `native-policy` |
| `growatt_bms_link_can_bank` | bootstrap | `native-policy` |
| `growatt_bms_link_can_context` | bootstrap | `native-policy` |
| `growatt_bms_link_can_source_selectors` | bootstrap | `native-policy` |
| `tesla_gen3_hsc_retained_enabled` | bootstrap | `unmanaged-driver` |
| `tesla_gen3_hsc_endpoint_id` | bootstrap | `identity` |
| `tesla_gen3_hsc_asset_id` | bootstrap | `identity` |
| `tesla_gen3_hsc_source_id` | bootstrap | `identity` |
| `tesla_gen3_hsc_source_epoch` | bootstrap | `identity` |
| `tesla_gen3_hsc_clock_epoch` | bootstrap | `identity` |
| `tesla_gen3_hsc_evse_id` | bootstrap | `identity` |
| `tesla_gen3_hsc_connector_id` | bootstrap | `identity` |
| `tesla_gen3_hsc_driver_generation` | bootstrap | `identity` |
| `tesla_gen3_hsc_node` | bootstrap | `identity` |
| `modbus_tcp_endpoints[].label` | bootstrap | `identity` |
| `modbus_tcp_endpoints[].family` | bootstrap | `native-policy` |
| `modbus_tcp_endpoints[].endpoint` | bootstrap | `transport` |
| `modbus_tcp_endpoints[].dial_timeout` | bootstrap | `transport` |
| `modbus_tcp_endpoints[].units` | bootstrap | `transport` |
| `modbus_tcp_endpoints[].pacing_gap_ms` | bootstrap | `transport` |
| `modbus_tcp_endpoints[].pacing_settle_ms` | bootstrap | `transport` |
| `modbus_tcp_endpoints[].pacing_cycle_s` | bootstrap | `transport` |
| `modbus_tcp_endpoints[].pacing_backoff_floor_s` | bootstrap | `transport` |
| `modbus_tcp_endpoints[].pacing_backoff_ceiling_s` | bootstrap | `transport` |
