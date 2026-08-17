from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
GUARD_PATH = ROOT / "helianthus/rootfs/usr/share/helianthus/modbus_runtime_guard.py"
RUN_PATH = ROOT / "helianthus/rootfs/etc/services.d/helianthus-gateway/run"
DOCKERFILE_PATH = ROOT / "helianthus/Dockerfile"
CONFIG_PATH = ROOT / "helianthus/config.json"
CURRENT_GATEWAY = "7f1cbea90e0b189486febc656632e9e7430c8500"


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


def run_validate(options: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(GUARD_PATH),
            "validate",
            "--options",
            str(options),
        ],
        text=True,
        capture_output=True,
        check=False,
    )


def test_atomic_validation_accepts_one_complete_bounded_bundle(tmp_path: Path) -> None:
    guard = load_guard()
    config = guard.load_config(write_options(tmp_path, enabled_options()))

    assert config.enabled is True
    assert config.endpoint == "tcp://192.0.2.40:502"
    assert config.dial_timeout == "5s"


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
    assert config == guard.Config(False, "", "")


def test_cli_error_never_emits_endpoint_or_credentials(tmp_path: Path) -> None:
    endpoint = "tcp://operator:topsecret@192.0.2.40:502"
    options = write_options(tmp_path, enabled_options(modbus_tcp_endpoint=endpoint))
    endpoint_file = tmp_path / "run" / "modbus-endpoint"
    result = run_validate(options)

    assert result.returncode != 0
    assert endpoint not in result.stderr
    assert "topsecret" not in result.stderr
    assert not endpoint_file.exists()


def test_cli_returns_a_complete_validated_bundle_without_materializing_endpoint(
    tmp_path: Path,
) -> None:
    endpoint_file = tmp_path / "run" / "modbus-endpoint"
    endpoint_file.parent.mkdir(mode=0o755)
    enabled = run_validate(write_options(tmp_path, enabled_options()))

    assert enabled.returncode == 0, enabled.stderr
    assert enabled.stdout.splitlines() == [
        "MODBUS_TCP_ENABLED=true",
        "MODBUS_TCP_ENDPOINT=tcp://192.0.2.40:502",
        "MODBUS_TCP_DIAL_TIMEOUT=5s",
    ]
    assert not endpoint_file.exists()

    disabled = run_validate(write_options(tmp_path, {"modbus_tcp_enabled": False}))
    assert disabled.returncode == 0, disabled.stderr
    assert disabled.stdout.splitlines() == [
        "MODBUS_TCP_ENABLED=false",
        "MODBUS_TCP_ENDPOINT=''",
        "MODBUS_TCP_DIAL_TIMEOUT=''",
    ]
    assert not endpoint_file.exists()


def test_invalid_update_does_not_mutate_existing_endpoint(tmp_path: Path) -> None:
    endpoint_file = tmp_path / "run" / "modbus-endpoint"
    endpoint_file.parent.mkdir(parents=True)
    endpoint_file.write_text("stale", encoding="utf-8")

    invalid = run_validate(
        write_options(tmp_path, enabled_options(modbus_tcp_dial_timeout="invalid"))
    )
    assert invalid.returncode != 0
    assert endpoint_file.read_text(encoding="utf-8") == "stale"


def test_image_and_wrapper_use_only_current_gateway_and_one_exec() -> None:
    dockerfile = DOCKERFILE_PATH.read_text(encoding="utf-8")
    run = RUN_PATH.read_text(encoding="utf-8")
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))

    assert f"ARG EBUSGATEWAY_VERSION={CURRENT_GATEWAY}" in dockerfile
    assert "FALLBACK_VERSION" not in dockerfile
    assert "gateway-fallback" not in dockerfile
    assert config["options"]["modbus_tcp_enabled"] is False
    assert config["options"]["modbus_tcp_endpoint"] == ""
    assert config["schema"]["modbus_tcp_endpoint"] == "str"
    assert "-modbus-tcp-enabled=true" in run
    assert '-modbus-tcp-endpoint-file "${modbus_endpoint_file}"' in run
    assert run.count('exec "${gateway_bin}" "${gateway_args[@]}"') == 1
    assert 'gateway_args+=("${modbus_args[@]}")' in run
    assert "modbus_child_pid" not in run
    assert "modbus_write_health" not in run
    assert "probe-readiness" not in run


def test_supervisor_schema_accepts_legacy_options_and_shows_modbus_endpoint() -> None:
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))

    # Supervisor treats every schema entry with a default in options as
    # required. Upgraded pre-selector configurations must remain saveable.
    assert "adapter_direct_protocol" not in config["options"]
    assert config["schema"]["adapter_direct_protocol"] == "list(enh|ens)?"

    # A Modbus endpoint is routing configuration, not a credential. Runtime
    # validation separately rejects userinfo and keeps error output redacted.
    assert config["schema"]["modbus_tcp_endpoint"] == "str"
