from __future__ import annotations

import importlib.util
import json
import os
import signal
import socket
import stat
import subprocess
import sys
import time
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
GUARD_PATH = (
    ROOT
    / "helianthus/rootfs/usr/share/helianthus/modbus_runtime_guard.py"
)
RUN_PATH = ROOT / "helianthus/rootfs/etc/services.d/helianthus-gateway/run"
DOCKERFILE_PATH = ROOT / "helianthus/Dockerfile"
CONFIG_PATH = ROOT / "helianthus/config.json"
CURRENT_GATEWAY = "53fe86d1beb656c8453a6213127ddddef83c887b"
FALLBACK_GATEWAY = "035e2b5cf703d68f75b809c45d2b1342696c07ef"


BASHIO_PRELUDE = r'''
bashio::config() {
  case "$1" in
    transport) printf '%s\n' "enh" ;;
    network) printf '%s\n' "tcp" ;;
    address) printf '%s\n' "203.0.113.10:9999" ;;
    proxy_profile) printf '%s\n' "disabled" ;;
    host) printf '%s\n' "127.0.0.1" ;;
    port|http_port) printf '%s\n' "8080" ;;
    path|graphql_path) printf '%s\n' "/graphql" ;;
    subscription_path) printf '%s\n' "/graphql/subscriptions" ;;
    mcp_path) printf '%s\n' "/mcp" ;;
    mdns|broadcast|observe_first_enabled|passive_state_direct_apply) printf '%s\n' "true" ;;
    passive_config_direct_apply|enable_static_seed_table|eebus_enabled) printf '%s\n' "false" ;;
    adapter_direct_enabled) printf '%s\n' "${TEST_ADAPTER_DIRECT_ENABLED:-false}" ;;
    adapter_direct_address) printf '%s\n' "192.0.2.80:9999" ;;
    eebus_discovery_enabled) printf '%s\n' "true" ;;
    mdns_instance) printf '%s\n' "helianthus" ;;
    source_addr) printf '%s\n' "auto" ;;
    scan_request_timeout) printf '%s\n' "400ms" ;;
    read_timeout|write_timeout|dial_timeout) printf '%s\n' "5s" ;;
    proxy_listen_addr) printf '%s\n' "0.0.0.0:19001" ;;
    external_write_policy) printf '%s\n' "record_only" ;;
    v8_classifier_mode) printf '%s\n' "enforce" ;;
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


def load_guard():
    spec = importlib.util.spec_from_file_location("modbus_runtime_guard", GUARD_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def write_options(tmp_path: Path, payload: object) -> Path:
    path = tmp_path / "options.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def enabled_options(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "modbus_tcp_enabled": True,
        "modbus_tcp_endpoint": "tcp://192.0.2.40:502",
        "modbus_tcp_dial_timeout": "5s",
    }
    payload.update(overrides)
    return payload


def test_atomic_validation_accepts_one_complete_bounded_bundle(tmp_path: Path) -> None:
    guard = load_guard()
    config = guard.load_config(write_options(tmp_path, enabled_options()))

    assert config.enabled is True
    assert config.endpoint == "tcp://192.0.2.40:502"
    assert config.dial_timeout == "5s"
    assert 5 <= config.startup_window_seconds <= 40
    assert config.endpoint_ref.startswith("sha256:")
    assert "192.0.2.40" not in config.endpoint_ref


@pytest.mark.parametrize(
    "payload",
    [
        {"modbus_tcp_enabled": True},
        enabled_options(modbus_tcp_endpoint=""),
        enabled_options(modbus_tcp_dial_timeout="0s"),
        enabled_options(modbus_tcp_dial_timeout="31s"),
        enabled_options(modbus_tcp_enabled="true"),
        enabled_options(modbus_tcp_endpoint=502),
        enabled_options(modbus_tcp_endpoint="tcp://192.0.2.40"),
        enabled_options(modbus_tcp_endpoint="udp://192.0.2.40:502"),
        enabled_options(modbus_tcp_endpoint="tcp://user:secret@192.0.2.40:502"),
        enabled_options(modbus_tcp_endpoint="tcp://192.0.2.40:502/path"),
    ],
)
def test_invalid_or_partial_bundle_fails_before_gateway_start(
    tmp_path: Path, payload: object
) -> None:
    guard = load_guard()
    with pytest.raises(guard.ConfigError):
        guard.load_config(write_options(tmp_path, payload))


@pytest.mark.parametrize(
    ("endpoint", "dial_timeout"),
    [
        ("tcp://operator:retained@192.0.2.40:502", "stale-invalid-value"),
        (None, {"stale": "invalid"}),
    ],
)
def test_disabled_state_is_inert_even_with_retained_malformed_fields(
    tmp_path: Path, endpoint: object, dial_timeout: object
) -> None:
    guard = load_guard()
    config = guard.load_config(
        write_options(
            tmp_path,
            {
                "modbus_tcp_enabled": False,
                "modbus_tcp_endpoint": endpoint,
                "modbus_tcp_dial_timeout": dial_timeout,
            },
        )
    )
    assert config.enabled is False
    assert config.endpoint == ""
    assert config.endpoint_ref == ""


def test_cli_error_and_redactor_never_emit_endpoint_or_credentials(tmp_path: Path) -> None:
    endpoint = "tcp://operator:topsecret@192.0.2.40:502"
    options = write_options(tmp_path, enabled_options(modbus_tcp_endpoint=endpoint))
    endpoint_file = tmp_path / "run" / "modbus-endpoint"
    result = subprocess.run(
        [
            sys.executable,
            str(GUARD_PATH),
            "validate",
            "--options",
            str(options),
            "--endpoint-file",
            str(endpoint_file),
            "--health",
            str(tmp_path / "health.json"),
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode != 0
    assert endpoint not in result.stderr
    assert "topsecret" not in result.stderr
    assert not endpoint_file.exists()

    endpoint_file.parent.mkdir()
    endpoint_file.write_text("tcp://192.0.2.40:502", encoding="utf-8")
    endpoint_file.chmod(0o600)
    redacted = subprocess.run(
        [
            sys.executable,
            str(GUARD_PATH),
            "redact",
            "--endpoint-file",
            str(endpoint_file),
        ],
        input="dial tcp://192.0.2.40:502 and 192.0.2.40:502; lookup 192.0.2.40 failed\n",
        text=True,
        capture_output=True,
        check=True,
    )
    assert "192.0.2.40" not in redacted.stdout
    assert redacted.stdout == (
        "dial [REDACTED_MODBUS_ENDPOINT] and [REDACTED_MODBUS_ENDPOINT]; "
        "lookup [REDACTED_MODBUS_ENDPOINT] failed\n"
    )


def test_endpoint_file_is_atomic_private_and_cleared_before_invalid_update(
    tmp_path: Path,
) -> None:
    endpoint_file = tmp_path / "run" / "modbus-endpoint"
    valid_options = write_options(tmp_path, enabled_options())
    valid = subprocess.run(
        [
            sys.executable,
            str(GUARD_PATH),
            "validate",
            "--options",
            str(valid_options),
            "--endpoint-file",
            str(endpoint_file),
            "--health",
            str(tmp_path / "health.json"),
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    assert valid.returncode == 0, valid.stderr
    assert endpoint_file.read_text(encoding="utf-8") == "tcp://192.0.2.40:502"
    assert stat.S_IMODE(endpoint_file.stat().st_mode) == 0o600

    invalid_options = write_options(
        tmp_path, enabled_options(modbus_tcp_dial_timeout="invalid")
    )
    invalid = subprocess.run(
        [
            sys.executable,
            str(GUARD_PATH),
            "validate",
            "--options",
            str(invalid_options),
            "--endpoint-file",
            str(endpoint_file),
            "--health",
            str(tmp_path / "health.json"),
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    assert invalid.returncode != 0
    assert not endpoint_file.exists()


def test_health_cli_uses_validated_snapshot_not_mutable_options(tmp_path: Path) -> None:
    health = tmp_path / "health.json"
    result = subprocess.run(
        [
            sys.executable,
            str(GUARD_PATH),
            "health",
            "--health",
            str(health),
            "--enabled",
            "true",
            "--endpoint-ref",
            "sha256:0123456789abcdef",
            "--state",
            "CONFIG_VALIDATED",
            "--attempt",
            "1",
            "--max-attempts",
            "3",
            "--binary",
            "current",
            "--reason",
            "CONFIG_VALID",
        ],
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(health.read_text(encoding="utf-8"))
    assert payload["enabled"] is True
    assert payload["endpoint_ref"] == "sha256:0123456789abcdef"


def test_health_is_atomic_private_deterministic_and_redacted(tmp_path: Path) -> None:
    guard = load_guard()
    config = guard.load_config(write_options(tmp_path, enabled_options()))
    health = tmp_path / "modbus-runtime-health.json"

    guard.write_health(
        health,
        config,
        state="RECOVERY_RETRY",
        attempt=2,
        max_attempts=3,
        binary="current",
        reason="STARTUP_EXIT",
    )

    payload = json.loads(health.read_text(encoding="utf-8"))
    assert payload == {
        "attempt": 2,
        "binary": "current",
        "contract": "helianthus.modbus-addon-health.v1",
        "enabled": True,
        "endpoint_ref": config.endpoint_ref,
        "max_attempts": 3,
        "reason": "STARTUP_EXIT",
        "state": "RECOVERY_RETRY",
    }
    assert "192.0.2.40" not in health.read_text(encoding="utf-8")
    assert stat.S_IMODE(health.stat().st_mode) == 0o600
    assert not list(tmp_path.glob("*.tmp"))


def test_readiness_probe_requires_every_declared_local_listener() -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        ready_port = listener.getsockname()[1]

        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as unused:
            unused.bind(("127.0.0.1", 0))
            missing_port = unused.getsockname()[1]

        ready = subprocess.run(
            [
                sys.executable,
                str(GUARD_PATH),
                "probe-readiness",
                "--listener",
                f"0.0.0.0:{ready_port}",
                "--timeout-ms",
                "200",
            ],
            text=True,
            capture_output=True,
            check=False,
        )
        incomplete = subprocess.run(
            [
                sys.executable,
                str(GUARD_PATH),
                "probe-readiness",
                "--listener",
                f"0.0.0.0:{ready_port}",
                "--listener",
                f"127.0.0.1:{missing_port}",
                "--timeout-ms",
                "200",
            ],
            text=True,
            capture_output=True,
            check=False,
        )
        hostname = subprocess.run(
            [
                sys.executable,
                str(GUARD_PATH),
                "probe-readiness",
                "--listener",
                f"localhost:{ready_port}",
                "--timeout-ms",
                "200",
            ],
            text=True,
            capture_output=True,
            check=False,
        )

    assert ready.returncode == 0, ready.stderr
    assert ready.stdout == ""
    assert ready.stderr == ""
    assert incomplete.returncode != 0
    assert incomplete.stdout == ""
    assert incomplete.stderr == ""
    assert hostname.returncode != 0
    assert "localhost" not in hostname.stdout + hostname.stderr


def test_image_and_wrapper_wire_current_plus_fallback_without_modbus_leak() -> None:
    dockerfile = DOCKERFILE_PATH.read_text(encoding="utf-8")
    run = RUN_PATH.read_text(encoding="utf-8")
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))

    assert f"ARG EBUSGATEWAY_VERSION={CURRENT_GATEWAY}" in dockerfile
    assert f"ARG EBUSGATEWAY_FALLBACK_VERSION={FALLBACK_GATEWAY}" in dockerfile
    assert "/out/gateway-fallback" in dockerfile
    assert "helianthus-gateway-fallback" in dockerfile

    assert config["options"]["modbus_tcp_enabled"] is False
    assert config["options"]["modbus_tcp_endpoint"] == ""
    assert config["schema"]["modbus_tcp_endpoint"] == "password"
    assert "-modbus-tcp-enabled=true" in run
    assert '-modbus-tcp-endpoint-file "${modbus_endpoint_file}"' in run
    assert "MODBUS_TCP_ENDPOINT=" not in run
    assert "HELIANTHUS_MODBUS_REDACT_VALUE" not in run
    assert "modbus_runtime_guard.py" in run
    assert "MODBUS_RECOVERY_MAX_ATTEMPTS=3" in run
    assert "helianthus-gateway-fallback" in run
    assert "-modbus-tcp-enabled" not in run.split("modbus_fallback_args", 1)[-1]


def write_gateway_stub(
    path: Path,
    *,
    fallback: bool,
    unsupported_optional_flag: str | None = None,
    ignore_term: bool = False,
) -> None:
    if fallback:
        body = f'''
Path(os.environ["TEST_FALLBACK_ARGV_FILE"]).write_text("\\n".join(sys.argv[1:]) + "\\n", encoding="utf-8")
Path(os.environ["TEST_FALLBACK_PID_FILE"]).write_text(str(os.getpid()), encoding="utf-8")
unsupported_optional_flag = {unsupported_optional_flag!r}
if {ignore_term!r}:
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
if unsupported_optional_flag and any(
    arg == "-" + unsupported_optional_flag
    or arg.startswith("-" + unsupported_optional_flag + "=")
    for arg in sys.argv[1:]
):
    raise SystemExit(64)
time.sleep(float(os.environ.get("TEST_FALLBACK_SLEEP", "0")))
raise SystemExit(int(os.environ.get("TEST_FALLBACK_EXIT", "0")))
'''
    else:
        body = '''
counter = Path(os.environ["TEST_CURRENT_COUNTER"])
attempt = int(counter.read_text(encoding="utf-8")) + 1 if counter.exists() else 1
counter.write_text(str(attempt), encoding="utf-8")
with Path(os.environ["TEST_CURRENT_ARGV_FILE"]).open("a", encoding="utf-8") as handle:
    handle.write("ATTEMPT\\n" + "\\n".join(sys.argv[1:]) + "\\n")
Path(os.environ["TEST_CURRENT_ENV_FILE"]).write_text(json.dumps(dict(os.environ), sort_keys=True), encoding="utf-8")
if "-modbus-tcp-endpoint-file" in sys.argv:
    endpoint_index = sys.argv.index("-modbus-tcp-endpoint-file") + 1
    raw_endpoint = Path(sys.argv[endpoint_index]).read_text(encoding="utf-8")
else:
    raw_endpoint = ""
Path(os.environ["TEST_CHILD_PID_FILE"]).write_text(str(os.getpid()), encoding="utf-8")
if os.environ.get("TEST_PARENT_SIGNAL"):
    os.kill(os.getppid(), int(os.environ["TEST_PARENT_SIGNAL"]))
time.sleep(float(os.environ.get("TEST_CURRENT_SLEEP", "0")))
if raw_endpoint:
    sys.stderr.write("dial " + raw_endpoint + " failed\\n")
raise SystemExit(int(os.environ.get("TEST_CURRENT_EXIT", "42")))
'''
    optional_help = {
        "enable-static-seed-table": "  -enable-static-seed-table boolean\\n",
        "instance-guid-source": "  -instance-guid-source string\\n",
        "semantic-cache-path": "  -semantic-cache-path string\\n",
    }
    optional_help.pop(unsupported_optional_flag, None)
    optional_help_text = "".join(optional_help.values())
    script = f'''#!/usr/bin/env python3
import json
import os
import signal
import sys
import time
from pathlib import Path

if "--help" in sys.argv:
    sys.stderr.write("Usage of gateway:\\n  -modbus-tcp-enabled\\n  -modbus-tcp-endpoint-file string\\n  -modbus-tcp-dial-timeout duration\\n  -proxy-listen string\\n{optional_help_text}")
    raise SystemExit(0)
{body}
'''
    path.write_text(script, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def run_wrapper(
    tmp_path: Path,
    payload: dict[str, object],
    *,
    current_exit: int = 42,
    current_sleep: float = 0,
    signal_parent: signal.Signals | None = None,
    fallback_unsupported_optional_flag: str | None = None,
    fallback_exit: int = 0,
    fallback_sleep: float = 0,
    fallback_ignore_term: bool = False,
    preexisting_health_state: str | None = None,
    redactor_delay: float = 0,
    validator_delay: float = 0,
    fail_health_state: str | None = None,
    wrapper_timeout: float | None = None,
    signal_wrapper_after: float | None = None,
    signal_wrapper: signal.Signals = signal.SIGTERM,
    signal_wait_for: str = "redactor_setup",
    hang_redactor_after_drain: bool = False,
    redactor_exit_after_ready: float | None = None,
    startup_delay_before_disabled_launch: float = 0,
    startup_delay_after_disabled_health: float = 0,
    startup_delay_before_gateway_launch: float = 0,
    record_health_calls: bool = False,
    registration_delay_target: str | None = None,
    readiness_result: bool | None = True,
    startup_window_seconds_override: int | None = None,
    adapter_direct_enabled: bool = False,
) -> subprocess.CompletedProcess[str]:
    current = tmp_path / "gateway-current"
    fallback = tmp_path / "gateway-fallback"
    wrapper = tmp_path / "run"
    options = write_options(tmp_path, payload)
    write_gateway_stub(current, fallback=False)
    write_gateway_stub(
        fallback,
        fallback=True,
        unsupported_optional_flag=fallback_unsupported_optional_flag,
        ignore_term=fallback_ignore_term,
    )

    run = RUN_PATH.read_text(encoding="utf-8")
    run = run.replace("/usr/local/bin/helianthus-gateway-fallback", "${TEST_FALLBACK_GATEWAY_BIN}")
    run = run.replace("/usr/local/bin/helianthus-gateway", "${TEST_CURRENT_GATEWAY_BIN}")
    run = run.replace("/data/helianthus-gateway", "${TEST_OVERRIDE_GATEWAY_BIN}")
    run = run.replace("/data/source_addr.last", "${TEST_SOURCE_STATE_FILE}")
    if startup_window_seconds_override is not None:
        run = run.replace(
            'modbus_startup_window_seconds="${MODBUS_STARTUP_WINDOW_SECONDS}"',
            f"modbus_startup_window_seconds={startup_window_seconds_override}",
            1,
        )
    if startup_delay_before_disabled_launch:
        run = run.replace(
            'if ! bashio::var.true "${modbus_tcp_enabled}"; then',
            f"sleep {startup_delay_before_disabled_launch!r} || true\n"
            'if ! bashio::var.true "${modbus_tcp_enabled}"; then',
            1,
        )
    if startup_delay_after_disabled_health:
        run = run.replace(
            "  modbus_write_health DISABLED 0 current EXPLICIT_DISABLE\n",
            "  modbus_write_health DISABLED 0 current EXPLICIT_DISABLE\n"
            '  : > "${TEST_DISABLED_HEALTH_BOUNDARY_FILE}"\n'
            f"  sleep {startup_delay_after_disabled_health!r} || true\n",
            1,
        )
    if startup_delay_before_gateway_launch:
        run = run.replace(
            '  "${gateway_bin}" "${modbus_current_args[@]}" \\\n',
            '  : > "${TEST_SIGNAL_BOUNDARY_FILE}"\n'
            f"  sleep {startup_delay_before_gateway_launch!r} || true\n"
            '  "${gateway_bin}" "${modbus_current_args[@]}" \\\n',
            1,
        )
    if registration_delay_target is not None:
        boundary = (
            '  : > "${TEST_REGISTRATION_BOUNDARY_FILE}"\n'
            "  sleep 2 || true\n"
        )
        registration_needles = {
            "validator": "modbus_validator_pid=$!\n",
            "redactor_stdout": '  modbus_redactor_pids+=("$!")\n',
            "redactor_stderr": '  modbus_redactor_pids+=("$!")\n',
            "current": "  modbus_child_pid=$!\n",
            "fallback": "  modbus_child_pid=$!\n",
        }
        needle = registration_needles[registration_delay_target]
        occurrence = 2 if registration_delay_target in {"redactor_stderr", "fallback"} else 1
        start = -1
        for _ in range(occurrence):
            start = run.find(needle, start + 1)
            assert start >= 0
        run = run[:start] + boundary + run[start:]
    wrapper.write_text(BASHIO_PRELUDE + "\n" + run, encoding="utf-8")

    runtime_state = tmp_path / "runtime_state.json"
    runtime_state.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "meta": {
                    "instance_guid": "12345678-1234-4234-9234-123456789abc",
                    "written_at": "2026-08-13T00:00:00Z",
                },
            }
        ),
        encoding="utf-8",
    )
    health_path = tmp_path / "health.json"
    if preexisting_health_state is not None:
        health_path.write_text(
            json.dumps({"state": preexisting_health_state, "endpoint_ref": "sha256:stale"}),
            encoding="utf-8",
        )
    guard_path = GUARD_PATH
    if (
        redactor_delay
        or validator_delay
        or fail_health_state is not None
        or hang_redactor_after_drain
        or redactor_exit_after_ready is not None
        or record_health_calls
        or registration_delay_target is not None
        or readiness_result is not None
    ):
        guard_path = tmp_path / "guard-proxy.py"
        guard_path.write_text(
            f'''import os
import runpy
import sys
import threading
import time
from pathlib import Path

is_redactor = len(sys.argv) > 1 and sys.argv[1] == "redact"
is_validator = len(sys.argv) > 1 and sys.argv[1] == "validate"
is_readiness_probe = len(sys.argv) > 1 and sys.argv[1] == "probe-readiness"
if is_readiness_probe and {readiness_result is not None!r}:
    with Path({str(tmp_path / "readiness-calls")!r}).open("a", encoding="utf-8") as handle:
        handle.write("\\n".join(sys.argv[2:]) + "\\nCALL\\n")
    raise SystemExit(0 if {readiness_result!r} else 1)
if is_validator:
    Path({str(tmp_path / "validator-pid")!r}).write_text(str(os.getpid()), encoding="utf-8")
    time.sleep({validator_delay!r})
if is_redactor:
    Path({str(tmp_path)!r}, f"redactor-pid-{{os.getpid()}}").write_text(
        str(os.getpid()), encoding="utf-8"
    )
    time.sleep({redactor_delay!r})
if is_redactor and {redactor_exit_after_ready is not None!r}:
    ready_file = Path(sys.argv[sys.argv.index("--ready-file") + 1])
    def exit_after_ready():
        while not ready_file.exists():
            time.sleep(0.01)
        time.sleep({redactor_exit_after_ready!r})
        os._exit(23)
    threading.Thread(target=exit_after_ready, daemon=True).start()
if len(sys.argv) > 1 and sys.argv[1] == "health" and "--state" in sys.argv:
    state = sys.argv[sys.argv.index("--state") + 1]
    if {record_health_calls!r}:
        with Path({str(tmp_path / "health-calls")!r}).open("a", encoding="utf-8") as handle:
            handle.write(state + "\\n")
    if state == {fail_health_state!r}:
        raise SystemExit(2)
try:
    runpy.run_path({str(GUARD_PATH)!r}, run_name="__main__")
except SystemExit as error:
    if is_redactor and {hang_redactor_after_drain!r} and error.code == 0:
        Path({str(tmp_path)!r}, f"redactor-draining-{{os.getpid()}}").write_text(
            str(os.getpid()), encoding="utf-8"
        )
        time.sleep(30)
    raise
''',
            encoding="utf-8",
        )
    env = os.environ.copy()
    env.update(
        {
            "TEST_CURRENT_GATEWAY_BIN": str(current),
            "TEST_FALLBACK_GATEWAY_BIN": str(fallback),
            "TEST_OVERRIDE_GATEWAY_BIN": str(tmp_path / "missing-override"),
            "TEST_SOURCE_STATE_FILE": str(tmp_path / "source-state"),
            "TEST_LOG_FILE": str(tmp_path / "wrapper.log"),
            "TEST_CURRENT_COUNTER": str(tmp_path / "current-count"),
            "TEST_CURRENT_ARGV_FILE": str(tmp_path / "current-argv"),
            "TEST_CURRENT_ENV_FILE": str(tmp_path / "current-env.json"),
            "TEST_FALLBACK_ARGV_FILE": str(tmp_path / "fallback-argv"),
            "TEST_FALLBACK_PID_FILE": str(tmp_path / "fallback-pid"),
            "TEST_CHILD_PID_FILE": str(tmp_path / "child-pid"),
            "TEST_SIGNAL_BOUNDARY_FILE": str(tmp_path / "signal-boundary"),
            "TEST_DISABLED_HEALTH_BOUNDARY_FILE": str(
                tmp_path / "disabled-health-boundary"
            ),
            "TEST_REGISTRATION_BOUNDARY_FILE": str(
                tmp_path / "registration-boundary"
            ),
            "TEST_CURRENT_EXIT": str(current_exit),
            "TEST_CURRENT_SLEEP": str(current_sleep),
            "TEST_FALLBACK_EXIT": str(fallback_exit),
            "TEST_FALLBACK_SLEEP": str(fallback_sleep),
            "TEST_PARENT_SIGNAL": str(signal_parent.value) if signal_parent else "",
            "TEST_ADAPTER_DIRECT_ENABLED": "true" if adapter_direct_enabled else "false",
            "HELIANTHUS_RUNTIME_STATE_WRAPPER": str(
                ROOT
                / "helianthus/rootfs/usr/share/helianthus/check_runtime_state_wrapper.py"
            ),
            "HELIANTHUS_RUNTIME_STATE_PATH": str(runtime_state),
            "HELIANTHUS_LEGACY_INSTANCE_GUID_PATH": str(tmp_path / "instance-guid"),
            "HELIANTHUS_MIGRATION_MARKER_PATH": str(tmp_path / "migration-marker"),
            "HELIANTHUS_MODBUS_RUNTIME_GUARD": str(guard_path),
            "HELIANTHUS_MODBUS_OPTIONS_PATH": str(options),
            "HELIANTHUS_MODBUS_HEALTH_FILE": str(health_path),
            "HELIANTHUS_MODBUS_ENDPOINT_FILE": str(tmp_path / "modbus-endpoint"),
            "HELIANTHUS_MODBUS_REDACTOR_DRAIN_SECONDS": "1",
        }
    )
    command = ["bash", str(wrapper)]
    if signal_wrapper_after is None:
        return subprocess.run(
            command,
            cwd=ROOT,
            env=env,
            text=True,
            capture_output=True,
            check=False,
            timeout=wrapper_timeout,
        )
    process = subprocess.Popen(
        command,
        cwd=ROOT,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    readiness_deadline = time.monotonic() + 8
    while True:
        if signal_wait_for == "redactor_setup":
            ready = bool(list(tmp_path.glob(".modbus-redact.*")))
        elif signal_wait_for == "redactor_drain":
            ready = len(list(tmp_path.glob("redactor-draining-*"))) == 2
        elif signal_wait_for == "startup_delay":
            ready = True
        elif signal_wait_for == "disabled_health_boundary":
            ready = (tmp_path / "disabled-health-boundary").exists()
        elif signal_wait_for == "gateway_launch_boundary":
            ready = (tmp_path / "signal-boundary").exists()
        elif signal_wait_for == "retry_backoff":
            log_path = tmp_path / "wrapper.log"
            ready = log_path.exists() and "bounded retry" in log_path.read_text(
                encoding="utf-8"
            )
        elif signal_wait_for == "fallback_running":
            ready = (tmp_path / "fallback-argv").exists()
        elif signal_wait_for == "validator_running":
            ready = (tmp_path / "validator-pid").exists()
        elif signal_wait_for == "registration_boundary":
            ready = (tmp_path / "registration-boundary").exists()
        else:
            raise ValueError(f"unknown signal wait target: {signal_wait_for}")
        if ready:
            break
        if process.poll() is not None or time.monotonic() >= readiness_deadline:
            break
        time.sleep(0.01)
    time.sleep(signal_wrapper_after)
    process.send_signal(signal_wrapper)
    stdout, stderr = process.communicate(timeout=wrapper_timeout)
    return subprocess.CompletedProcess(command, process.returncode, stdout, stderr)


def test_wrapper_retries_three_times_then_runs_previous_binary_without_modbus(
    tmp_path: Path,
) -> None:
    endpoint = "tcp://192.0.2.40:502"
    result = run_wrapper(tmp_path, enabled_options(modbus_tcp_endpoint=endpoint))

    assert result.returncode == 0, result.stderr
    assert (tmp_path / "current-count").read_text(encoding="utf-8") == "3"
    current_argv = (tmp_path / "current-argv").read_text(encoding="utf-8")
    current_env = (tmp_path / "current-env.json").read_text(encoding="utf-8")
    assert endpoint not in current_argv
    assert endpoint not in current_env
    assert "-modbus-tcp-endpoint-file" in current_argv
    assert not (tmp_path / "modbus-endpoint").exists()
    fallback_argv = (tmp_path / "fallback-argv").read_text(encoding="utf-8")
    assert "modbus-tcp" not in fallback_argv
    assert endpoint not in result.stdout + result.stderr
    assert "192.0.2.40" not in result.stdout + result.stderr
    health = json.loads((tmp_path / "health.json").read_text(encoding="utf-8"))
    assert health["state"] == "FALLBACK_EXITED"
    assert health["binary"] == "fallback"
    assert health["attempt"] == 3
    assert health["reason"] == "FALLBACK_STARTUP_EXIT"


def test_listener_readiness_failure_never_publishes_running_and_reaps_binaries(
    tmp_path: Path,
) -> None:
    result = run_wrapper(
        tmp_path,
        enabled_options(modbus_tcp_dial_timeout="100ms"),
        current_sleep=3,
        fallback_sleep=3,
        readiness_result=False,
        startup_window_seconds_override=1,
        record_health_calls=True,
        wrapper_timeout=15,
    )

    assert result.returncode != 0
    assert (tmp_path / "current-count").read_text(encoding="utf-8") == "3"
    health_calls = (tmp_path / "health-calls").read_text(encoding="utf-8").splitlines()
    assert "RUNNING" not in health_calls
    assert "FALLBACK_ACTIVE" not in health_calls
    health = json.loads((tmp_path / "health.json").read_text(encoding="utf-8"))
    assert health["state"] == "FALLBACK_EXITED"
    assert health["reason"] == "FALLBACK_RUNTIME_NOT_READY"
    assert not (tmp_path / "modbus-endpoint").exists()
    for pid_file in (tmp_path / "child-pid", tmp_path / "fallback-pid"):
        pid = int(pid_file.read_text(encoding="utf-8"))
        with pytest.raises(ProcessLookupError):
            os.kill(pid, 0)


def test_adapter_direct_requires_http_and_proxy_listener_readiness(tmp_path: Path) -> None:
    result = run_wrapper(
        tmp_path,
        enabled_options(modbus_tcp_dial_timeout="100ms"),
        current_exit=0,
        current_sleep=2,
        startup_window_seconds_override=1,
        adapter_direct_enabled=True,
        wrapper_timeout=10,
    )

    assert result.returncode == 0, result.stderr
    readiness_calls = (tmp_path / "readiness-calls").read_text(encoding="utf-8")
    assert readiness_calls.splitlines() == [
        "--listener",
        "0.0.0.0:8080",
        "--timeout-ms",
        "250",
        "--listener",
        "0.0.0.0:19001",
        "CALL",
    ]


def test_wrapper_disabled_path_runs_current_once_without_modbus_or_fallback(
    tmp_path: Path,
) -> None:
    result = run_wrapper(
        tmp_path,
        {
            "modbus_tcp_enabled": False,
            "modbus_tcp_endpoint": "tcp://operator:retained@192.0.2.40:502",
            "modbus_tcp_dial_timeout": "stale-invalid-value",
        },
    )

    assert result.returncode == 42
    assert (tmp_path / "current-count").read_text(encoding="utf-8") == "1"
    assert not (tmp_path / "fallback-argv").exists()
    current_argv = (tmp_path / "current-argv").read_text(encoding="utf-8")
    assert "modbus-tcp" not in current_argv
    assert not (tmp_path / "modbus-endpoint").exists()
    health = json.loads((tmp_path / "health.json").read_text(encoding="utf-8"))
    assert health["state"] == "DISABLED"
    assert health["enabled"] is False


@pytest.mark.parametrize("wrapper_signal", [signal.SIGTERM, signal.SIGINT])
def test_signal_during_validation_reaps_validator_and_clears_runtime(
    tmp_path: Path, wrapper_signal: signal.Signals
) -> None:
    result = run_wrapper(
        tmp_path,
        enabled_options(),
        validator_delay=30,
        signal_wrapper_after=0,
        signal_wrapper=wrapper_signal,
        signal_wait_for="validator_running",
        wrapper_timeout=10,
    )

    assert result.returncode != 0
    validator_pid = int((tmp_path / "validator-pid").read_text(encoding="utf-8"))
    with pytest.raises(ProcessLookupError):
        os.kill(validator_pid, 0)
    assert not (tmp_path / "modbus-endpoint").exists()
    assert not (tmp_path / "health.json").exists()
    assert not (tmp_path / "child-pid").exists()
    assert not (tmp_path / "fallback-argv").exists()


@pytest.mark.parametrize("wrapper_signal", [signal.SIGTERM, signal.SIGINT])
@pytest.mark.parametrize(
    "registration_target",
    ["validator", "redactor_stdout", "redactor_stderr", "current", "fallback"],
)
def test_signal_during_pid_registration_reaps_spawned_process(
    tmp_path: Path,
    wrapper_signal: signal.Signals,
    registration_target: str,
) -> None:
    result = run_wrapper(
        tmp_path,
        enabled_options(),
        current_sleep=30 if registration_target == "current" else 0,
        fallback_sleep=30 if registration_target == "fallback" else 0,
        validator_delay=30 if registration_target == "validator" else 0,
        registration_delay_target=registration_target,
        signal_wrapper_after=0,
        signal_wrapper=wrapper_signal,
        signal_wait_for="registration_boundary",
        wrapper_timeout=15,
    )

    assert result.returncode != 0
    pid_paths: list[Path]
    if registration_target == "validator":
        pid_paths = [tmp_path / "validator-pid"]
    elif registration_target.startswith("redactor_"):
        pid_paths = list(tmp_path.glob("redactor-pid-*"))
    elif registration_target == "current":
        pid_paths = [tmp_path / "child-pid"]
    else:
        pid_paths = [tmp_path / "fallback-pid"]
    assert pid_paths
    for path in pid_paths:
        pid = int(path.read_text(encoding="utf-8"))
        with pytest.raises(ProcessLookupError):
            os.kill(pid, 0)
    assert not (tmp_path / "modbus-endpoint").exists()
    if registration_target == "validator":
        assert not (tmp_path / "health.json").exists()
    else:
        health = json.loads((tmp_path / "health.json").read_text(encoding="utf-8"))
        assert health["state"] == "STOPPED"
        assert health["reason"] == "SIGNAL"


@pytest.mark.parametrize("wrapper_signal", [signal.SIGTERM, signal.SIGINT])
def test_signal_before_disabled_launch_never_execs_gateway(
    tmp_path: Path, wrapper_signal: signal.Signals
) -> None:
    result = run_wrapper(
        tmp_path,
        {"modbus_tcp_enabled": False},
        startup_delay_before_disabled_launch=2,
        signal_wrapper_after=0.2,
        signal_wrapper=wrapper_signal,
        signal_wait_for="startup_delay",
        wrapper_timeout=10,
    )

    assert result.returncode != 0
    assert not (tmp_path / "child-pid").exists()
    assert not (tmp_path / "fallback-argv").exists()
    assert not (tmp_path / "modbus-endpoint").exists()
    health = json.loads((tmp_path / "health.json").read_text(encoding="utf-8"))
    assert health["state"] == "STOPPED"
    assert health["reason"] == "SIGNAL"


@pytest.mark.parametrize("wrapper_signal", [signal.SIGTERM, signal.SIGINT])
def test_signal_after_disabled_health_write_is_terminal(
    tmp_path: Path, wrapper_signal: signal.Signals
) -> None:
    result = run_wrapper(
        tmp_path,
        {"modbus_tcp_enabled": False},
        startup_delay_after_disabled_health=2,
        signal_wrapper_after=0,
        signal_wrapper=wrapper_signal,
        signal_wait_for="disabled_health_boundary",
        wrapper_timeout=10,
    )

    assert result.returncode != 0
    assert not (tmp_path / "child-pid").exists()
    assert not (tmp_path / "fallback-argv").exists()
    assert not (tmp_path / "modbus-endpoint").exists()
    health = json.loads((tmp_path / "health.json").read_text(encoding="utf-8"))
    assert health["state"] == "STOPPED"
    assert health["reason"] == "SIGNAL"


@pytest.mark.parametrize("wrapper_signal", [signal.SIGTERM, signal.SIGINT])
def test_signal_at_enabled_launch_boundary_is_terminal(
    tmp_path: Path, wrapper_signal: signal.Signals
) -> None:
    result = run_wrapper(
        tmp_path,
        enabled_options(),
        startup_delay_before_gateway_launch=2,
        signal_wrapper_after=0,
        signal_wrapper=wrapper_signal,
        signal_wait_for="gateway_launch_boundary",
        record_health_calls=True,
        wrapper_timeout=10,
    )

    assert result.returncode != 0
    assert not (tmp_path / "child-pid").exists()
    assert not (tmp_path / "fallback-argv").exists()
    assert not (tmp_path / "modbus-endpoint").exists()
    assert (tmp_path / "health-calls").read_text(encoding="utf-8").splitlines() == [
        "CONFIG_VALIDATED",
        "STOPPED",
    ]


@pytest.mark.parametrize("wrapper_signal", [signal.SIGTERM, signal.SIGINT])
def test_signal_during_retry_backoff_cannot_start_another_attempt(
    tmp_path: Path, wrapper_signal: signal.Signals
) -> None:
    result = run_wrapper(
        tmp_path,
        enabled_options(),
        signal_wrapper_after=0,
        signal_wrapper=wrapper_signal,
        signal_wait_for="retry_backoff",
        record_health_calls=True,
        wrapper_timeout=10,
    )

    assert result.returncode != 0
    assert (tmp_path / "current-count").read_text(encoding="utf-8") == "1"
    assert not (tmp_path / "fallback-argv").exists()
    assert not (tmp_path / "modbus-endpoint").exists()
    assert (tmp_path / "health-calls").read_text(encoding="utf-8").splitlines() == [
        "CONFIG_VALIDATED",
        "RECOVERY_RETRY",
        "STOPPED",
    ]


def test_signal_boundedly_kills_and_reaps_term_ignoring_fallback(
    tmp_path: Path,
) -> None:
    result = run_wrapper(
        tmp_path,
        enabled_options(),
        fallback_sleep=30,
        fallback_ignore_term=True,
        signal_wrapper_after=0.2,
        signal_wait_for="fallback_running",
        wrapper_timeout=15,
    )

    assert result.returncode != 0
    assert time.time() - (tmp_path / "fallback-argv").stat().st_mtime < 8
    health = json.loads((tmp_path / "health.json").read_text(encoding="utf-8"))
    assert health["state"] == "STOPPED"
    assert health["binary"] == "fallback"
    assert health["reason"] == "SIGNAL"
    assert not (tmp_path / "modbus-endpoint").exists()


@pytest.mark.parametrize("parent_signal", [signal.SIGTERM, signal.SIGINT])
def test_wrapper_signal_during_child_launch_stops_child_without_fallback(
    tmp_path: Path, parent_signal: signal.Signals
) -> None:
    result = run_wrapper(
        tmp_path,
        enabled_options(),
        current_sleep=5,
        signal_parent=parent_signal,
    )

    assert result.returncode != 0
    child_pid = int((tmp_path / "child-pid").read_text(encoding="utf-8"))
    for _ in range(20):
        try:
            os.kill(child_pid, 0)
        except ProcessLookupError:
            break
        time.sleep(0.05)
    else:
        pytest.fail(f"gateway child {child_pid} survived wrapper termination")
    assert not (tmp_path / "fallback-argv").exists()
    health = json.loads((tmp_path / "health.json").read_text(encoding="utf-8"))
    assert health["state"] == "STOPPED"
    assert health["reason"] == "SIGNAL"


@pytest.mark.parametrize("stale_state", ["RUNNING", "FALLBACK_ACTIVE"])
def test_wrapper_invalid_config_clears_stale_health(
    tmp_path: Path, stale_state: str
) -> None:
    result = run_wrapper(
        tmp_path,
        enabled_options(modbus_tcp_dial_timeout="invalid"),
        preexisting_health_state=stale_state,
    )

    assert result.returncode != 0
    assert not (tmp_path / "health.json").exists()
    assert not (tmp_path / "current-count").exists()
    assert not (tmp_path / "fallback-argv").exists()


@pytest.mark.parametrize(
    "unsupported_flag",
    ["enable-static-seed-table", "instance-guid-source", "semantic-cache-path"],
)
def test_fallback_omits_optional_flag_unsupported_by_fallback_binary(
    tmp_path: Path, unsupported_flag: str
) -> None:
    result = run_wrapper(
        tmp_path,
        enabled_options(),
        fallback_unsupported_optional_flag=unsupported_flag,
    )

    assert result.returncode == 0, result.stderr
    current_argv = (tmp_path / "current-argv").read_text(encoding="utf-8")
    fallback_argv = (tmp_path / "fallback-argv").read_text(encoding="utf-8")
    expected = "-" + unsupported_flag
    assert any(
        arg == expected or arg.startswith(expected + "=")
        for arg in current_argv.splitlines()
    )
    assert not any(
        arg == expected or arg.startswith(expected + "=")
        for arg in fallback_argv.splitlines()
    )


def test_wrapper_clean_early_exit_still_reaches_bounded_fallback(
    tmp_path: Path,
) -> None:
    result = run_wrapper(tmp_path, enabled_options(), current_exit=0)

    assert result.returncode == 0
    assert (tmp_path / "current-count").read_text(encoding="utf-8") == "3"
    assert (tmp_path / "fallback-argv").exists()
    health = json.loads((tmp_path / "health.json").read_text(encoding="utf-8"))
    assert health["state"] == "FALLBACK_EXITED"
    assert health["reason"] == "FALLBACK_STARTUP_EXIT"


def test_fallback_exit_after_startup_window_is_recorded_truthfully(
    tmp_path: Path,
) -> None:
    result = run_wrapper(
        tmp_path,
        enabled_options(modbus_tcp_dial_timeout="100ms"),
        fallback_exit=23,
        fallback_sleep=7,
    )

    assert result.returncode == 23
    health = json.loads((tmp_path / "health.json").read_text(encoding="utf-8"))
    assert health["state"] == "FALLBACK_EXITED"
    assert health["binary"] == "fallback"
    assert health["reason"] == "FALLBACK_RUNTIME_EXIT"


def test_delayed_redactor_keeps_endpoint_secret_until_stream_is_drained(
    tmp_path: Path,
) -> None:
    endpoint = "tcp://secret-host.example:502"
    result = run_wrapper(
        tmp_path,
        enabled_options(modbus_tcp_endpoint=endpoint),
        redactor_delay=4,
    )

    assert result.returncode == 0, result.stderr
    assert endpoint not in result.stdout + result.stderr
    assert "secret-host.example" not in result.stdout + result.stderr
    assert not (tmp_path / "modbus-endpoint").exists()


def test_health_failure_after_child_launch_reaps_child_and_clears_endpoint(
    tmp_path: Path,
) -> None:
    result = run_wrapper(
        tmp_path,
        enabled_options(modbus_tcp_dial_timeout="100ms"),
        current_sleep=30,
        fail_health_state="RUNNING",
        wrapper_timeout=15,
    )

    assert result.returncode != 0
    child_pid = int((tmp_path / "child-pid").read_text(encoding="utf-8"))
    with pytest.raises(ProcessLookupError):
        os.kill(child_pid, 0)
    assert not (tmp_path / "modbus-endpoint").exists()
    assert not (tmp_path / "fallback-argv").exists()


def test_signal_during_redactor_handshake_never_launches_gateway(
    tmp_path: Path,
) -> None:
    result = run_wrapper(
        tmp_path,
        enabled_options(),
        redactor_delay=4,
        signal_wrapper_after=0.5,
        wrapper_timeout=10,
    )

    assert result.returncode != 0
    assert not (tmp_path / "child-pid").exists()
    assert not (tmp_path / "fallback-argv").exists()
    assert not (tmp_path / "modbus-endpoint").exists()


def test_hanging_redactor_is_bounded_and_cannot_block_recovery(
    tmp_path: Path,
) -> None:
    started = time.monotonic()
    result = run_wrapper(
        tmp_path,
        enabled_options(),
        hang_redactor_after_drain=True,
        wrapper_timeout=20,
    )

    assert result.returncode == 0, result.stderr
    assert time.monotonic() - started < 17
    assert (tmp_path / "fallback-argv").exists()
    assert not (tmp_path / "modbus-endpoint").exists()


def test_signal_during_redactor_drain_reaps_every_redactor(tmp_path: Path) -> None:
    result = run_wrapper(
        tmp_path,
        enabled_options(),
        hang_redactor_after_drain=True,
        signal_wrapper_after=0,
        signal_wait_for="redactor_drain",
        wrapper_timeout=10,
    )

    assert result.returncode != 0
    redactor_pids = [
        int(path.read_text(encoding="utf-8"))
        for path in tmp_path.glob("redactor-draining-*")
    ]
    assert len(redactor_pids) == 2
    for pid in redactor_pids:
        with pytest.raises(ProcessLookupError):
            os.kill(pid, 0)
    assert not (tmp_path / "fallback-argv").exists()
    assert not (tmp_path / "modbus-endpoint").exists()


def test_redactor_exit_after_readiness_terminates_gateway_and_recovers(
    tmp_path: Path,
) -> None:
    result = run_wrapper(
        tmp_path,
        enabled_options(),
        current_sleep=30,
        redactor_exit_after_ready=0.2,
        wrapper_timeout=15,
    )

    assert result.returncode == 0, result.stderr
    assert (tmp_path / "current-count").read_text(encoding="utf-8") == "3"
    assert (tmp_path / "fallback-argv").exists()
    child_pid = int((tmp_path / "child-pid").read_text(encoding="utf-8"))
    with pytest.raises(ProcessLookupError):
        os.kill(child_pid, 0)
    assert not (tmp_path / "modbus-endpoint").exists()


def test_redactor_exit_after_startup_window_records_truthful_terminal_reason(
    tmp_path: Path,
) -> None:
    result = run_wrapper(
        tmp_path,
        enabled_options(modbus_tcp_dial_timeout="100ms"),
        current_sleep=30,
        redactor_exit_after_ready=7,
        wrapper_timeout=15,
    )

    assert result.returncode != 0
    assert not (tmp_path / "fallback-argv").exists()
    health = json.loads((tmp_path / "health.json").read_text(encoding="utf-8"))
    assert health["state"] == "EXITED_AFTER_STARTUP_WINDOW"
    assert health["reason"] == "REDACTOR_EXIT"
    assert not (tmp_path / "modbus-endpoint").exists()


def test_wrapper_marks_exit_after_bounded_running_window(tmp_path: Path) -> None:
    result = run_wrapper(
        tmp_path,
        enabled_options(modbus_tcp_dial_timeout="100ms"),
        current_exit=0,
        current_sleep=7,
    )

    assert result.returncode == 0
    health = json.loads((tmp_path / "health.json").read_text(encoding="utf-8"))
    assert health["state"] == "EXITED_AFTER_STARTUP_WINDOW"
    assert health["reason"] == "RUNTIME_EXIT"
    assert health["attempt"] == 1
    assert not (tmp_path / "fallback-argv").exists()
