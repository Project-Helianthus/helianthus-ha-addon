#!/usr/bin/env python3
"""Validate persistent eeBUS Home Assistant add-on wiring."""

from __future__ import annotations

import hashlib
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
MODBUS_RUNTIME_GUARD = REPO_ROOT / "helianthus/rootfs/usr/share/helianthus/modbus_runtime_guard.py"

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
    eebus_enabled) printf '%s\n' "${TEST_EEBUS_ENABLED-false}" ;;
    eebus_listen_port) printf '%s\n' "${TEST_EEBUS_LISTEN_PORT-4712}" ;;
    eebus_interface) printf '%s\n' "${TEST_EEBUS_INTERFACE-}" ;;
    eebus_subnets) printf '%s\n' "${TEST_EEBUS_SUBNETS-}" ;;
    eebus_discovery_enabled) printf '%s\n' "${TEST_EEBUS_DISCOVERY_ENABLED-true}" ;;
    eebus_remote_ski_allowlist) printf '%s\n' "${TEST_EEBUS_REMOTE_SKI_ALLOWLIST-}" ;;
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
if "-eebus-discovery-enabled" in sys.argv:
    sys.stderr.write("bare Go boolean flag would stop parsing at its following value\\n")
    raise SystemExit(64)
for argument in sys.argv[1:]:
    if argument.startswith("-eebus-discovery-enabled="):
        if argument.split("=", 1)[1] not in ("true", "false"):
            sys.stderr.write("invalid Go boolean value\\n")
            raise SystemExit(64)
if any(argument.startswith("-eebus-") for argument in sys.argv[1:]) and "-instance-guid" not in sys.argv:
    sys.stderr.write("later gateway flags were not consumed\\n")
    raise SystemExit(64)
Path(os.environ["TEST_ARGV_FILE"]).write_text("\\n".join(sys.argv[1:]) + "\\n", encoding="utf-8")
'''
    _write_executable(path, script)


def _write_test_wrapper(path: Path) -> None:
    text = RUN_SCRIPT.read_text(encoding="utf-8")
    text = text.replace("/usr/local/bin/helianthus-gateway", "${TEST_GATEWAY_BIN}")
    text = text.replace("/data/helianthus-gateway", "${TEST_GATEWAY_OVERRIDE_BIN}")
    text = text.replace("/data/source_addr.last", "${TEST_LEGACY_SOURCE_ADDR_STATE_FILE}")
    text = text.replace(
        'eebus_options_path="/data/options.json"',
        'eebus_options_path="${TEST_EEBUS_OPTIONS_PATH}"',
    )
    text = text.replace(
        'interface_id_path="/sys/class/net/${eebus_interface}/address"',
        'interface_id_path="${TEST_EEBUS_INTERFACE_ID_PATH}"',
    )
    text = text.replace("> /etc/machine-id", '> "${TEST_EEBUS_MACHINE_ID_PATH}"')
    text = text.replace("chmod 0444 /etc/machine-id", 'chmod 0444 "${TEST_EEBUS_MACHINE_ID_PATH}"')
    path.write_text(BASHIO_PRELUDE + "\n" + text, encoding="utf-8")


def _run_case(
    *,
    enabled: bool,
    interface: str = "end0",
    subnets: str = "192.0.2.0/24",
    listen_port: str = "4712",
    discovery: bool = True,
    allowlist: str = VALID_REMOTE_SKI,
    raw_enabled: str | None = None,
    stale_schema: bool = False,
    stale_fields: tuple[str, ...] = (),
    options_override: dict[str, object] | None = None,
    omit_flag: str | None = None,
    expect_success: bool = True,
) -> tuple[list[str], str, str]:
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        wrapper = tmp / "run-under-test.sh"
        gateway = tmp / "gateway-stub.py"
        argv_file = tmp / "argv.txt"
        log_file = tmp / "wrapper.log"
        runtime_state_file = tmp / "runtime_state.json"
        interface_id_file = tmp / "interface-address"
        machine_id_file = tmp / "machine-id"
        options_file = tmp / "options.json"
        interface_id_file.write_text("02:00:00:00:00:01\n", encoding="utf-8")
        options = {
            "eebus_enabled": enabled,
            "eebus_listen_port": int(listen_port) if listen_port.isdigit() else listen_port,
            "eebus_interface": interface,
            "eebus_subnets": subnets,
            "eebus_discovery_enabled": discovery,
            "eebus_remote_ski_allowlist": allowlist,
        }
        if options_override:
            options.update(options_override)
        options_file.write_text(json.dumps(options), encoding="utf-8")
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
                "TEST_EEBUS_ENABLED": raw_enabled if raw_enabled is not None else ("true" if enabled else "false"),
                "TEST_EEBUS_LISTEN_PORT": listen_port,
                "TEST_EEBUS_INTERFACE": interface,
                "TEST_EEBUS_SUBNETS": subnets,
                "TEST_EEBUS_DISCOVERY_ENABLED": "true" if discovery else "false",
                "TEST_EEBUS_REMOTE_SKI_ALLOWLIST": allowlist,
                "TEST_EEBUS_INTERFACE_ID_PATH": str(interface_id_file),
                "TEST_EEBUS_MACHINE_ID_PATH": str(machine_id_file),
                "TEST_EEBUS_OPTIONS_PATH": str(options_file),
                "HELIANTHUS_MODBUS_RUNTIME_GUARD": str(MODBUS_RUNTIME_GUARD),
                "HELIANTHUS_MODBUS_OPTIONS_PATH": str(options_file),
                "HELIANTHUS_MODBUS_HEALTH_FILE": str(tmp / "modbus-health.json"),
                "HELIANTHUS_MODBUS_ENDPOINT_FILE": str(tmp / "modbus-endpoint"),
            }
        )
        stale_env_keys = {
            "eebus_enabled": "TEST_EEBUS_ENABLED",
            "eebus_listen_port": "TEST_EEBUS_LISTEN_PORT",
            "eebus_interface": "TEST_EEBUS_INTERFACE",
            "eebus_subnets": "TEST_EEBUS_SUBNETS",
            "eebus_discovery_enabled": "TEST_EEBUS_DISCOVERY_ENABLED",
            "eebus_remote_ski_allowlist": "TEST_EEBUS_REMOTE_SKI_ALLOWLIST",
        }
        if stale_schema:
            for key in stale_env_keys.values():
                env[key] = ""
        else:
            for key in stale_fields:
                env[stale_env_keys[key]] = ""
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
        log = log_file.read_text(encoding="utf-8") if log_file.exists() else ""
        machine_id = machine_id_file.read_text(encoding="utf-8").strip() if machine_id_file.exists() else ""
        return argv, result.stderr + log, machine_id


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
    argv, diagnostics, machine_id = _run_case(enabled=False)
    _assert(not any(arg.startswith("-eebus-") for arg in argv), "disabled config emitted eeBUS flags")
    _assert(machine_id == "", "disabled config changed the container machine id")
    _assert(
        "recovered missing fields" not in diagnostics,
        "valid empty options emitted a stale-schema fallback warning",
    )

    argv, _, machine_id = _run_case(enabled=True)
    _assert("-eebus-enabled=true" in argv, "enabled config omitted activation flag")
    _assert(_value(argv, "-eebus-listen-port") == "4712", "listen port changed")
    _assert(_value(argv, "-eebus-interfaces") == "end0", "interface changed")
    _assert(_value(argv, "-eebus-subnets") == "192.0.2.0/24", "subnets changed")
    _assert(_value(argv, "-eebus-state-root") == "/data/eebus", "state root is not fixed")
    _assert("-eebus-discovery-enabled=true" in argv, "discovery changed")
    _assert(_value(argv, "-eebus-remote-ski-allowlist") == VALID_REMOTE_SKI, "allowlist changed")
    _assert(_value(argv, "-eebus-pairing-window-mode") == "closed", "pairing policy widened")
    expected_machine_id = "8a4c331847003c7bacbfa7f2f383cc8b49126d9b1ad071cf97a4ab39c6d12f7c"
    _assert(
        hashlib.sha256(b"helianthus-eebusreg-ha-v1:020000000001").hexdigest()
        == expected_machine_id,
        "synthetic host-bound machine id vector is internally inconsistent",
    )
    _assert(machine_id == expected_machine_id, "host-bound machine id derivation changed")

    stale_argv, _, stale_machine_id = _run_case(enabled=True, stale_schema=True)
    _assert(stale_argv == argv, "cached Supervisor schema changed recovered eeBUS arguments")
    _assert(stale_machine_id == machine_id, "cached Supervisor schema changed host-bound identity")

    stale_argv, stale_stderr, _ = _run_case(
        enabled=True,
        interface="../end0",
        stale_schema=True,
        expect_success=False,
    )
    _assert(stale_argv == [], "invalid cached-schema interface reached gateway")
    _assert("eeBUS" in stale_stderr, "invalid cached-schema fallback did not fail visibly")

    mixed_argv, _, _ = _run_case(
        enabled=True,
        stale_fields=("eebus_remote_ski_allowlist",),
    )
    _assert(mixed_argv == argv, "mixed live/fallback eeBUS fields changed arguments")

    null_argv, _, _ = _run_case(
        enabled=True,
        stale_schema=True,
        options_override={"eebus_remote_ski_allowlist": None},
    )
    _assert(
        _value(null_argv, "-eebus-remote-ski-allowlist") == "",
        "JSON null did not retain absent/default semantics",
    )

    false_argv, _, _ = _run_case(enabled=True, discovery=False)
    _assert("-eebus-discovery-enabled=false" in false_argv, "Go boolean serialization lost false")
    _assert("-instance-guid" in false_argv, "flag parsing did not reach later gateway arguments")

    for description, kwargs in (
        ("normal boolean", {"raw_enabled": "on"}),
        ("normal enablement JSON type", {"options_override": {"eebus_enabled": "true"}}),
        ("normal discovery JSON type", {"options_override": {"eebus_discovery_enabled": "false"}}),
        ("normal listen-port JSON type", {"options_override": {"eebus_listen_port": "4712"}}),
        ("fallback boolean type", {"stale_schema": True, "options_override": {"eebus_enabled": "on"}}),
        ("normal literal null allowlist", {"allowlist": "null"}),
        (
            "fallback literal null allowlist",
            {"stale_schema": True, "options_override": {"eebus_remote_ski_allowlist": "null"}},
        ),
    ):
        invalid_argv, invalid_stderr, _ = _run_case(enabled=True, expect_success=False, **kwargs)
        _assert(invalid_argv == [], f"invalid {description} reached gateway")
        _assert("eeBUS" in invalid_stderr, f"invalid {description} error is not operator-visible")

    for stale_schema in (False, True):
        path = "fallback" if stale_schema else "normal"
        for field, value in (
            ("eebus_interface", "end\x000"),
            ("eebus_subnets", "192.0.2.0/2\x004"),
            ("eebus_remote_ski_allowlist", ("a" * 20) + "\x00" + ("a" * 20)),
        ):
            nul_argv, nul_stderr, _ = _run_case(
                enabled=True,
                stale_schema=stale_schema,
                options_override={field: value},
                expect_success=False,
            )
            _assert(nul_argv == [], f"NUL-bearing {path} {field} reached gateway")
            _assert("invalid protected JSON value or type" in nul_stderr, f"NUL-bearing {field} error is unclear")

    for field, overrides in (
        ("interface", {"interface": ""}),
        ("subnets", {"subnets": ""}),
        ("listen port", {"listen_port": "0"}),
        ("multiple interfaces", {"interface": "end0,end1"}),
        ("unsafe interface", {"interface": "../end0"}),
    ):
        argv, stderr, _ = _run_case(enabled=True, expect_success=False, **overrides)
        _assert(argv == [], f"invalid {field} reached gateway")
        _assert("eeBUS" in stderr, f"invalid {field} error is not operator-visible")

    for missing_flag in REQUIRED_FLAGS:
        argv, stderr, _ = _run_case(enabled=True, omit_flag=missing_flag, expect_success=False)
        _assert(argv == [], f"gateway missing {missing_flag} reached execution")
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
