#!/usr/bin/env python3
"""Validate persistent eeBUS Home Assistant add-on wiring."""

from __future__ import annotations

import json
import os
from pathlib import Path
import stat
import subprocess
import tempfile


REPO_ROOT = Path(__file__).resolve().parents[1]
CONFIG = REPO_ROOT / "helianthus/config.json"
RUN_SCRIPT = REPO_ROOT / "helianthus/rootfs/etc/services.d/helianthus-gateway/run"
RUNTIME_STATE_WRAPPER = REPO_ROOT / "helianthus/rootfs/usr/share/helianthus/check_runtime_state_wrapper.py"

EXPECTED_OPTIONS = {
    "eebus_enabled": False,
    "eebus_listen_port": 4712,
    "eebus_interface": "",
    "eebus_subnets": "",
    "eebus_discovery_enabled": True,
    "eebus_remote_ski_allowlist": "",
}

EXPECTED_SCHEMA = {
    "eebus_enabled": "bool",
    "eebus_listen_port": "int",
    "eebus_interface": "str",
    "eebus_subnets": "str",
    "eebus_discovery_enabled": "bool",
    "eebus_remote_ski_allowlist": "str",
}

REQUIRED_FLAGS = (
    "eebus-enabled",
    "eebus-listen-port",
    "eebus-interfaces",
    "eebus-subnets",
    "eebus-state-root",
    "eebus-discovery-enabled",
    "eebus-remote-ski-allowlist",
    "eebus-pairing-window-mode",
)

VALID_GUID = "12345678-1234-4234-9234-123456789abc"
VALID_REMOTE_SKI = "a" * 40

BASHIO_PRELUDE = r'''
bashio::config() {
  case "$1" in
    transport) printf '%s\n' "enh" ;;
    network) printf '%s\n' "tcp" ;;
    address) printf '%s\n' "203.0.113.10:9999" ;;
    proxy_profile) printf '%s\n' "disabled" ;;
    proxy_endpoint) printf '\n' ;;
    host) printf '%s\n' "127.0.0.1" ;;
    port|http_port) printf '%s\n' "8080" ;;
    path|graphql_path) printf '%s\n' "/graphql" ;;
    subscription_path) printf '%s\n' "/graphql/subscriptions" ;;
    mcp_path) printf '%s\n' "/mcp" ;;
    mdns|broadcast|observe_first_enabled|passive_state_direct_apply) printf '%s\n' "true" ;;
    passive_config_direct_apply|enable_static_seed_table|adapter_direct_enabled) printf '%s\n' "false" ;;
    mdns_instance) printf '%s\n' "helianthus" ;;
    source_addr) printf '%s\n' "auto" ;;
    scan_request_timeout) printf '%s\n' "400ms" ;;
    read_timeout|write_timeout|dial_timeout) printf '%s\n' "5s" ;;
    adapter_direct_address) printf '\n' ;;
    proxy_listen_addr) printf '%s\n' "0.0.0.0:19001" ;;
    external_write_policy) printf '%s\n' "record_only" ;;
    v8_classifier_mode) printf '%s\n' "enforce" ;;
    eebus_enabled) printf '%s\n' "${TEST_EEBUS_ENABLED:-false}" ;;
    eebus_listen_port) printf '%s\n' "${TEST_EEBUS_LISTEN_PORT:-4712}" ;;
    eebus_interface) printf '%s\n' "${TEST_EEBUS_INTERFACE:-}" ;;
    eebus_subnets) printf '%s\n' "${TEST_EEBUS_SUBNETS:-}" ;;
    eebus_discovery_enabled) printf '%s\n' "${TEST_EEBUS_DISCOVERY_ENABLED:-true}" ;;
    eebus_remote_ski_allowlist) printf '%s\n' "${TEST_EEBUS_REMOTE_SKI_ALLOWLIST:-}" ;;
    *) printf '\n' ;;
  esac
}

bashio::var.true() {
  case "$(printf '%s' "$1" | tr '[:upper:]' '[:lower:]')" in
    true|1|yes|on) return 0 ;;
    *) return 1 ;;
  esac
}

bashio::log.info() { printf 'INFO: %s\n' "$*" >> "${TEST_LOG_FILE}"; }
bashio::log.warning() { printf 'WARN: %s\n' "$*" >> "${TEST_LOG_FILE}"; }
bashio::log.error() { printf 'ERROR: %s\n' "$*" >> "${TEST_LOG_FILE}"; }
bashio::exit.nok() { printf 'NOK: %s\n' "$*" >&2; exit 1; }
'''


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _write_executable(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def _write_gateway_stub(path: Path, *, omit_flag: str | None = None) -> None:
    flags = [flag for flag in REQUIRED_FLAGS if flag != omit_flag]
    help_text = "Usage of gateway:\n" + "".join(f"  -{flag}\n" for flag in flags)
    help_text += "  -instance-guid-source string\n  -semantic-cache-path string\n"
    script = f'''#!/usr/bin/env python3
from pathlib import Path
import os
import sys

if "--help" in sys.argv:
    sys.stderr.write({help_text!r})
    raise SystemExit(0)
Path(os.environ["TEST_ARGV_FILE"]).write_text("\\n".join(sys.argv[1:]) + "\\n", encoding="utf-8")
'''
    _write_executable(path, script)


def _write_test_wrapper(path: Path) -> None:
    text = RUN_SCRIPT.read_text(encoding="utf-8")
    text = text.replace("/usr/local/bin/helianthus-gateway", "${TEST_GATEWAY_BIN}")
    text = text.replace("/data/helianthus-gateway", "${TEST_GATEWAY_OVERRIDE_BIN}")
    text = text.replace("/data/source_addr.last", "${TEST_LEGACY_SOURCE_ADDR_STATE_FILE}")
    path.write_text(BASHIO_PRELUDE + "\n" + text, encoding="utf-8")


def _run_case(
    *,
    enabled: bool,
    interface: str = "end0",
    subnets: str = "192.0.2.0/24",
    listen_port: str = "4712",
    discovery: bool = True,
    allowlist: str = VALID_REMOTE_SKI,
    omit_flag: str | None = None,
    expect_success: bool = True,
) -> tuple[list[str], str]:
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        wrapper = tmp / "run-under-test.sh"
        gateway = tmp / "gateway-stub.py"
        argv_file = tmp / "argv.txt"
        log_file = tmp / "wrapper.log"
        runtime_state_file = tmp / "runtime_state.json"
        runtime_state_file.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "meta": {
                        "instance_guid": VALID_GUID,
                        "written_at": "2026-08-09T00:00:00Z",
                    },
                }
            ),
            encoding="utf-8",
        )
        _write_test_wrapper(wrapper)
        _write_gateway_stub(gateway, omit_flag=omit_flag)

        env = os.environ.copy()
        env.update(
            {
                "TEST_GATEWAY_BIN": str(gateway),
                "TEST_GATEWAY_OVERRIDE_BIN": str(tmp / "missing-override"),
                "TEST_ARGV_FILE": str(argv_file),
                "TEST_LOG_FILE": str(log_file),
                "TEST_LEGACY_SOURCE_ADDR_STATE_FILE": str(tmp / "source_addr.last"),
                "HELIANTHUS_RUNTIME_STATE_WRAPPER": str(RUNTIME_STATE_WRAPPER),
                "HELIANTHUS_RUNTIME_STATE_PATH": str(runtime_state_file),
                "HELIANTHUS_LEGACY_INSTANCE_GUID_PATH": str(tmp / "instance_guid"),
                "HELIANTHUS_MIGRATION_MARKER_PATH": str(tmp / "migration-required"),
                "TEST_EEBUS_ENABLED": "true" if enabled else "false",
                "TEST_EEBUS_LISTEN_PORT": listen_port,
                "TEST_EEBUS_INTERFACE": interface,
                "TEST_EEBUS_SUBNETS": subnets,
                "TEST_EEBUS_DISCOVERY_ENABLED": "true" if discovery else "false",
                "TEST_EEBUS_REMOTE_SKI_ALLOWLIST": allowlist,
            }
        )
        result = subprocess.run(
            ["bash", str(wrapper)],
            cwd=REPO_ROOT,
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )
        if expect_success:
            _assert(result.returncode == 0, f"wrapper failed:\n{result.stderr}")
        else:
            _assert(result.returncode != 0, "wrapper unexpectedly succeeded")
        argv = argv_file.read_text(encoding="utf-8").splitlines() if argv_file.exists() else []
        return argv, result.stderr


def _value(argv: list[str], flag: str) -> str:
    index = argv.index(flag)
    return argv[index + 1]


def _check_schema() -> None:
    config = json.loads(CONFIG.read_text(encoding="utf-8"))
    options = config["options"]
    schema = config["schema"]
    for key, value in EXPECTED_OPTIONS.items():
        _assert(options.get(key) == value, f"config option {key} = {options.get(key)!r}; want {value!r}")
    for key, value in EXPECTED_SCHEMA.items():
        _assert(schema.get(key) == value, f"config schema {key} = {schema.get(key)!r}; want {value!r}")


def _check_runtime_cases() -> None:
    argv, _ = _run_case(enabled=False)
    _assert(not any(arg.startswith("-eebus-") for arg in argv), "disabled config emitted eeBUS flags")

    argv, _ = _run_case(enabled=True)
    _assert("-eebus-enabled=true" in argv, "enabled config omitted activation flag")
    _assert(_value(argv, "-eebus-listen-port") == "4712", "listen port changed")
    _assert(_value(argv, "-eebus-interfaces") == "end0", "interface changed")
    _assert(_value(argv, "-eebus-subnets") == "192.0.2.0/24", "subnets changed")
    _assert(_value(argv, "-eebus-state-root") == "/data/eebus", "state root is not fixed")
    _assert(_value(argv, "-eebus-discovery-enabled") == "true", "discovery changed")
    _assert(_value(argv, "-eebus-remote-ski-allowlist") == VALID_REMOTE_SKI, "allowlist changed")
    _assert(_value(argv, "-eebus-pairing-window-mode") == "closed", "pairing policy widened")

    for field, overrides in (
        ("interface", {"interface": ""}),
        ("subnets", {"subnets": ""}),
        ("listen port", {"listen_port": "0"}),
        ("multiple interfaces", {"interface": "end0,end1"}),
    ):
        argv, stderr = _run_case(enabled=True, expect_success=False, **overrides)
        _assert(argv == [], f"invalid {field} reached gateway")
        _assert("eeBUS" in stderr, f"invalid {field} error is not operator-visible")

    argv, stderr = _run_case(enabled=True, omit_flag="eebus-state-root", expect_success=False)
    _assert(argv == [], "unsupported gateway reached execution")
    _assert("does not support the complete eeBUS runtime flag set" in stderr, "unsupported gateway error is unclear")


def main() -> int:
    try:
        _check_schema()
        _check_runtime_cases()
    except AssertionError as exc:
        print(f"eeBUS wrapper check: FAIL ({exc})")
        return 1
    print("eeBUS wrapper check passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
