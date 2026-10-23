"""Portal Ingress declaration and minimal-start wrapper wiring (synthetic only).

The wrapper runs against stubbed bashio functions and a recording gateway
substitute whose help output is the pinned BOM flag set. No Supervisor, Home
Assistant, network or device is involved.
"""

from __future__ import annotations

import json
import os
import re
import stat
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "helianthus/config.json"
RUN = ROOT / "helianthus/rootfs/etc/services.d/helianthus-gateway/run"
SERVICES = ROOT / "helianthus/rootfs/etc/services.d"
SUPPORT = ROOT / "helianthus/rootfs/usr/share/helianthus"
BOM = ROOT / "helianthus/bom.json"
DOCKERFILE = ROOT / "helianthus/Dockerfile"
VERSION = "0.6.58"
GUID = "12345678-1234-4234-9234-123456789abc"
ADAPTER = "adapter.example.invalid:9999"
EBUSD = "ebusd.example.invalid:8888"
EXEC_LINE = 'exec "${gateway_bin}" "${gateway_args[@]}"'

BASHIO_PRELUDE = r'''
bashio::config() {
  jq -r --arg key "$1" \
    'if has($key) and .[$key] != null then .[$key] | tostring else "" end' \
    "${TEST_SUPERVISOR_OPTIONS}"
}
bashio::var.true() {
  case "$(printf '%s' "$1" | tr '[:upper:]' '[:lower:]')" in
    true|1|yes|on) return 0 ;;
    *) return 1 ;;
  esac
}
bashio::log.info() { printf 'INFO: %s\n' "$*" >> "${TEST_LOG}"; }
bashio::log.warning() { printf 'WARN: %s\n' "$*" >> "${TEST_LOG}"; }
bashio::log.error() { printf 'ERROR: %s\n' "$*" >> "${TEST_LOG}"; }
bashio::exit.nok() { printf 'NOK: %s\n' "$*" >&2; exit 1; }
'''

FAKE_GATEWAY = '''#!/usr/bin/env python3
import json, os, pathlib, sys
if sys.argv[1:] == ["--help"]:
    flags = json.loads(pathlib.Path(os.environ["TEST_BOM"]).read_text(encoding="utf-8"))["gateway_cli_flags"]
    hidden = set(json.loads(os.environ["TEST_HELP_HIDDEN"]))
    sys.stderr.write("Usage of gateway:\\n" + "".join(
        "  -" + flag + " string\\n" for flag in flags if flag not in hidden))
    raise SystemExit(0)
with pathlib.Path(os.environ["TEST_CALLS"]).open("a", encoding="utf-8") as calls:
    calls.write(json.dumps(sys.argv[1:]) + "\\n")
'''


def _config() -> dict:
    return json.loads(CONFIG.read_text(encoding="utf-8"))


def _wrapper_constant(name: str) -> str:
    match = re.search(rf'^{name}="?([^"\n]*)"?$', RUN.read_text(encoding="utf-8"), re.M)
    assert match, name
    return match.group(1)


def _run(tmp_path: Path, overrides: dict, hidden: tuple[str, ...] = ()) -> dict:
    data = tmp_path / "data"
    data.mkdir()
    options = data / "options.json"
    options.write_text(json.dumps(_config()["options"] | overrides), encoding="utf-8")
    (data / "runtime_state.json").write_text(
        json.dumps({"schema_version": 1, "meta": {"instance_guid": GUID}}), encoding="utf-8"
    )
    # Gateway-owned Portal record and writer lock: corrupt on purpose, because
    # repair and fail-closed handling belong to the gateway, not the wrapper.
    record = {"portal-config.json": b'{"format": "helianthus.portal-config/v1", ', "portal-config.lock": b""}
    for name, body in record.items():
        (data / name).write_bytes(body)

    gateway = tmp_path / "gateway.py"
    gateway.write_text(FAKE_GATEWAY, encoding="utf-8")
    gateway.chmod(gateway.stat().st_mode | stat.S_IXUSR)
    text = RUN.read_text(encoding="utf-8")
    for old, new in (
        ("/usr/local/bin/helianthus-gateway", "${TEST_GATEWAY}"),
        ("mktemp /tmp/helianthus-modbus-validate.XXXXXX", 'mktemp "${TEST_DATA}/modbus-validate.XXXXXX"'),
        ("/data/", "${TEST_DATA}/"),
    ):
        assert old in text, old
        text = text.replace(old, new)
    wrapper = tmp_path / "run-under-test.sh"
    wrapper.write_text(BASHIO_PRELUDE + "\n" + text, encoding="utf-8")

    calls, log = tmp_path / "calls.jsonl", tmp_path / "wrapper.log"
    env = {key: value for key, value in os.environ.items() if not key.startswith(("TEST_", "HELIANTHUS_"))}
    env.update({
        "TEST_GATEWAY": str(gateway),
        "TEST_DATA": str(data),
        "TEST_SUPERVISOR_OPTIONS": str(options),
        "TEST_BOM": str(BOM),
        "TEST_CALLS": str(calls),
        "TEST_LOG": str(log),
        "TEST_HELP_HIDDEN": json.dumps(sorted(hidden)),
        "HELIANTHUS_RUNTIME_STATE_WRAPPER": str(SUPPORT / "check_runtime_state_wrapper.py"),
        "HELIANTHUS_RUNTIME_STATE_PATH": str(data / "runtime_state.json"),
        "HELIANTHUS_LEGACY_INSTANCE_GUID_PATH": str(data / "instance_guid"),
        "HELIANTHUS_MIGRATION_MARKER_PATH": str(data / ".helianthus_migration_required"),
        "HELIANTHUS_MODBUS_RUNTIME_GUARD": str(SUPPORT / "modbus_runtime_guard.py"),
        "HELIANTHUS_MODBUS_ENDPOINT_FILE": str(tmp_path / "run" / "modbus-endpoint"),
        "HELIANTHUS_SERIAL_CAN_GUARD": str(SUPPORT / "serial_can_options.py"),
        "HELIANTHUS_M2M_IDENTITY_VALIDATOR": str(SUPPORT / "m2m_tls_identity.py"),
    })
    result = subprocess.run(
        ["bash", str(wrapper)], env=env, capture_output=True, text=True, check=False, timeout=30
    )
    runtime = [json.loads(line) for line in calls.read_text(encoding="utf-8").splitlines()] if calls.exists() else []
    record_after = {
        path.name: path.read_bytes() for path in data.iterdir() if path.name.startswith("portal-config")
    }
    return {
        "result": result,
        "runtime": runtime,
        "log": log.read_text(encoding="utf-8") if log.exists() else "",
        "data": data,
        "record_intact": record_after == record,
    }


def _expected_argv(
    data: Path, transport: tuple[str, str, str], *, http_port: int = 8080,
    graphql: str = "/graphql", subscription: str = "/graphql/subscriptions",
    mcp: str = "/mcp", mdns_instance: str = "helianthus", portal: bool = True,
    proxy_listen: bool = True,
) -> list[str]:
    protocol, network, address = transport
    argv = [
        "-transport", protocol, "-network", network, "-address", address,
        "-source-addr", "auto", "-scan-request-timeout", "400ms",
        "-http-addr", f"0.0.0.0:{http_port}", "-graphql-path", graphql,
        "-subscription-path", subscription, "-mcp-path", mcp,
        "-mdns=true", "-mdns-instance", mdns_instance, "-instance-guid", GUID,
        "-instance-guid-source", "runtime_state", "-broadcast=true",
        "-read-timeout", "5s", "-write-timeout", "5s", "-dial-timeout", "5s",
        "-observe-first-enabled=true", "-passive-state-direct-apply=true",
        "-passive-config-direct-apply=false", "-external-write-policy", "record_only",
        "-enable-static-seed-table=false", "-semantic-cache-path", str(data / "semantic_cache.json"),
    ]
    if portal:
        argv += ["-portal-path", "/portal"]
    if proxy_listen:
        argv += ["-proxy-listen", "0.0.0.0:19001"]
    return argv


def test_config_declares_admin_ingress_on_the_existing_http_listener() -> None:
    config = _config()
    options = config["options"]

    assert config["ingress"] is True
    assert config["ingress_port"] == options["http_port"] == options["port"] == 8080
    assert config["ports"]["8080/tcp"] == 8080
    # Relative entry with a trailing slash: the panel opens the Portal
    # directory itself, never the bare mount whose redirect is root-absolute.
    assert config["ingress_entry"] == "portal/"
    assert config["panel_admin"] is True
    assert config["panel_title"] == "Helianthus"
    assert config["panel_icon"].startswith("mdi:")
    assert config["host_network"] is True
    # Ingress carries only the HTTP listener; native TCP listeners stay off it.
    native_ports = {8443, options["eebus_listen_port"], int(options["proxy_listen_addr"].rsplit(":", 1)[1])}
    assert config["ingress_port"] not in native_ports
    # Opening the Portal needs no Home Assistant integration or API grant.
    for key in ("homeassistant_api", "hassio_api", "auth_api", "discovery", "services"):
        assert key not in config
    # The wrapper's Portal constants and the declared Ingress settings agree.
    assert int(_wrapper_constant("portal_ingress_port")) == config["ingress_port"]
    assert _wrapper_constant("portal_mount") == "/" + config["ingress_entry"].rstrip("/")


def test_native_transport_options_release_and_pins_are_unchanged() -> None:
    config = _config()
    bom = json.loads(BOM.read_text(encoding="utf-8"))
    pin = re.search(r"^ARG EBUSGATEWAY_VERSION=(\S+)$", DOCKERFILE.read_text(encoding="utf-8"), re.M)

    assert config["version"] == bom["addon"]["version"] == VERSION
    assert pin and pin.group(1) == bom["gateway"]["commit"]
    assert {key: config["options"][key] for key in (
        "adapter_direct_enabled", "adapter_direct_address", "proxy_listen_addr", "transport",
        "network", "address", "proxy_profile", "proxy_endpoint", "source_addr",
        "scan_request_timeout", "read_timeout", "write_timeout", "dial_timeout",
    )} == {
        "adapter_direct_enabled": True, "adapter_direct_address": "",
        "proxy_listen_addr": "0.0.0.0:19001", "transport": "enh", "network": "tcp",
        "address": "HOST:PORT", "proxy_profile": "disabled", "proxy_endpoint": "",
        "source_addr": "auto", "scan_request_timeout": "400ms", "read_timeout": "5s",
        "write_timeout": "5s", "dial_timeout": "5s",
    }
    assert {key: config["schema"][key] for key in (
        "adapter_direct_enabled", "adapter_direct_protocol", "adapter_direct_address",
        "transport", "network", "address", "proxy_profile", "proxy_endpoint",
    )} == {
        "adapter_direct_enabled": "bool", "adapter_direct_protocol": "list(enh|ens)?",
        "adapter_direct_address": "str", "transport": "list(enh|ens|udp-plain|ebusd-tcp)",
        "network": "list(tcp|unix|udp)", "address": "str",
        "proxy_profile": "list(disabled|enh|ens)", "proxy_endpoint": "str",
    }


def test_wrapper_stays_one_service_without_supervisor_calls_or_record_access() -> None:
    run = RUN.read_text(encoding="utf-8")

    assert sorted(path.name for path in SERVICES.iterdir()) == ["helianthus-gateway"]
    assert run.count(EXEC_LINE) == 1
    assert run.rstrip().splitlines()[-1] == EXEC_LINE
    for forbidden in ("bashio::api", "bashio::addon", "bashio::core", "bashio::discovery",
                      "bashio::services", "SUPERVISOR_TOKEN", "portal-config"):
        assert forbidden not in run, forbidden


@pytest.mark.parametrize(
    ("overrides", "transport", "proxy_listen"),
    (
        ({"adapter_direct_address": ADAPTER}, ("adapter-direct", "tcp", f"adapter-direct://{ADAPTER}"), True),
        ({"adapter_direct_address": ADAPTER, "adapter_direct_protocol": "ens"},
         ("adapter-direct", "tcp", f"adapter-direct-ens://{ADAPTER}"), True),
        ({"adapter_direct_enabled": False, "transport": "ebusd-tcp", "address": EBUSD},
         ("ebusd-tcp", "tcp", EBUSD), False),
    ),
    ids=("adapter-direct-enh", "adapter-direct-ens", "ebusd-tcp"),
)
def test_minimal_configuration_execs_the_gateway_once_with_the_portal_mount(
    tmp_path: Path, overrides: dict, transport: tuple[str, str, str], proxy_listen: bool,
) -> None:
    run = _run(tmp_path, overrides)

    assert run["result"].returncode == 0, run["result"].stderr
    expected = _expected_argv(run["data"], transport, proxy_listen=proxy_listen)
    assert run["runtime"] == [expected]
    argv = run["runtime"][0]
    assert argv[argv.index("-portal-path") + 1] == "/" + _config()["ingress_entry"].rstrip("/")
    flags = set(json.loads(BOM.read_text(encoding="utf-8"))["gateway_cli_flags"])
    assert {arg[1:].split("=", 1)[0] for arg in argv if arg.startswith("-")} <= flags
    assert "INFO: Portal endpoint: http://127.0.0.1:8080/portal/" in run["log"]
    assert "INFO: Portal Ingress: Home Assistant panel entry portal/ on HTTP port 8080" in run["log"]
    assert "Portal Ingress unavailable" not in run["log"]
    assert run["record_intact"]


def test_shipped_defaults_without_an_adapter_endpoint_stop_before_launch(tmp_path: Path) -> None:
    run = _run(tmp_path, {})

    assert run["result"].returncode != 0
    assert "adapter_direct_address is required when adapter_direct_enabled=true" in run["result"].stderr
    assert run["runtime"] == []
    assert run["record_intact"]


@pytest.mark.parametrize("option", ("http_port", "port"))
def test_moved_http_listener_keeps_the_direct_portal_and_reports_ingress_unavailable(
    tmp_path: Path, option: str,
) -> None:
    run = _run(tmp_path, {"adapter_direct_address": ADAPTER, option: 8181})

    assert run["result"].returncode == 0, run["result"].stderr
    assert run["runtime"] == [_expected_argv(
        run["data"], ("adapter-direct", "tcp", f"adapter-direct://{ADAPTER}"), http_port=8181,
    )]
    assert "INFO: Portal endpoint: http://127.0.0.1:8181/portal/" in run["log"]
    assert (
        "WARN: Portal Ingress unavailable: Ingress targets HTTP port 8080 but the HTTP "
        "listener uses port 8181; the direct Portal endpoint is unaffected"
    ) in run["log"]
    assert "Portal Ingress: Home Assistant panel entry" not in run["log"]


def test_gateway_without_the_portal_mount_option_still_starts_once(tmp_path: Path) -> None:
    run = _run(tmp_path, {"adapter_direct_address": ADAPTER}, hidden=("portal-path",))

    assert run["result"].returncode == 0, run["result"].stderr
    assert run["runtime"] == [_expected_argv(
        run["data"], ("adapter-direct", "tcp", f"adapter-direct://{ADAPTER}"), portal=False,
    )]
    assert (
        "WARN: Packaged gateway binary does not support -portal-path; the Ingress entry "
        "relies on the gateway default Portal mount /portal"
    ) in run["log"]


def test_configured_paths_keep_argument_boundaries_and_graphql_prefix(tmp_path: Path) -> None:
    run = _run(tmp_path, {
        "adapter_direct_address": ADAPTER,
        "graphql_path": "custom/gql",
        "mcp_path": "agents/mcp",
        "mdns_instance": "Helianthus Home",
    })

    assert run["result"].returncode == 0, run["result"].stderr
    assert run["runtime"] == [_expected_argv(
        run["data"], ("adapter-direct", "tcp", f"adapter-direct://{ADAPTER}"),
        graphql="/custom/gql", subscription="/custom/gql/subscriptions",
        mcp="/agents/mcp", mdns_instance="Helianthus Home",
    )]
