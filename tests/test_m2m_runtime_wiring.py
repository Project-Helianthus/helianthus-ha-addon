from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "helianthus/config.json"
RUN = ROOT / "helianthus/rootfs/etc/services.d/helianthus-gateway/run"
VERSION = "0.6.54"
TLS_ROOT = "/ssl/helianthus-pv-m2m"


def test_supervisor_exposes_only_non_secret_m2m_controls_and_read_only_config() -> None:
    config = json.loads(CONFIG.read_text(encoding="utf-8"))

    assert config["version"] == VERSION
    assert config["map"] == ["ssl:ro"]
    assert "config:ro" not in config["map"]
    assert config["ports"]["8443/tcp"] == 8443
    assert config["options"]["m2m_graphql_enabled"] is False
    assert config["options"]["m2m_graphql_server_name"] == ""
    assert config["options"]["m2m_graphql_asset_ref"] == ""
    assert config["schema"]["m2m_graphql_enabled"] == "bool"
    assert config["schema"]["m2m_graphql_server_name"] == "str"
    assert config["schema"]["m2m_graphql_asset_ref"] == "str"
    assert not any(
        token in key.lower()
        for key in config["options"] | config["schema"]
        for token in ("m2m_ca", "m2m_cert", "m2m_key", "m2m_secret")
    )


def test_wrapper_uses_fixed_tls_files_and_complete_m2m_flag_bundle() -> None:
    run = RUN.read_text(encoding="utf-8")

    fixed_files = (
        "ca.pem",
        "server-cert.pem",
        "server-key.pem",
        "portal-client-cert.pem",
        "portal-client-key.pem",
    )
    assert f'm2m_tls_root="{TLS_ROOT}"' in run
    for name in fixed_files:
        assert f'${{m2m_tls_root}}/{name}' in run
    required_flags = (
        "m2m-graphql-listen",
        "m2m-graphql-server-name",
        "m2m-graphql-client-ca",
        "m2m-graphql-server-cert",
        "m2m-graphql-server-key",
        "m2m-graphql-allowed-assets",
        "m2m-graphql-known-assets",
        "portal-pv-m2m-url",
        "portal-pv-m2m-server-name",
        "portal-pv-m2m-ca",
        "portal-pv-m2m-client-cert",
        "portal-pv-m2m-client-key",
        "portal-pv-asset-ref",
    )
    for flag in required_flags:
        assert f'gateway_supports_flag "{flag}"' in run or flag in run
        assert f'-{flag}' in run
    assert 'gateway_args+=("${m2m_args[@]}")' in run
    assert run.index('gateway_args+=("${m2m_args[@]}")') < run.index(
        'exec "${gateway_bin}" "${gateway_args[@]}"'
    )


def test_m2m_disabled_state_is_inert_and_wrapper_stays_single_process() -> None:
    run = RUN.read_text(encoding="utf-8")

    assert "m2m_graphql_enabled" in run
    assert 'm2m_args=()' in run
    assert 'if bashio::var.true "${m2m_graphql_enabled}"; then' in run
    assert 'bashio::log.info "M2M GraphQL runtime: disabled"' in run
    assert run.count('exec "${gateway_bin}" "${gateway_args[@]}"') == 1
    for forbidden in (
        "m2m_child_pid",
        "m2m_supervisor",
        "m2m_retry",
        "m2m_fallback",
        "m2m_certificate_generator",
    ):
        assert forbidden not in run


def test_m2m_enabled_values_are_type_checked_and_never_logged() -> None:
    run = RUN.read_text(encoding="utf-8")

    assert "m2m_graphql_enabled boolean" in run
    assert "m2m_graphql_server_name string" in run
    assert "m2m_graphql_asset_ref string" in run
    enabled_read = run.index("m2m_graphql_enabled=$(jq -r")
    enabled_gate = run.index('if [ "${m2m_graphql_enabled}" = "true" ]; then', enabled_read)
    string_validation = run.index(
        "m2m_validate_protected_option m2m_graphql_server_name string", enabled_gate
    )
    assert enabled_read < enabled_gate < string_validation
    assert "M2M GraphQL runtime: enabled" in run
    assert "${m2m_graphql_server_name}" not in {
        line for line in run.splitlines() if "bashio::log" in line
    }
    assert "${m2m_graphql_asset_ref}" not in {
        line for line in run.splitlines() if "bashio::log" in line
    }
