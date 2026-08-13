from __future__ import annotations

import importlib.util
import json
import os
import stat
import subprocess
import sys
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
CURRENT_GATEWAY = "658a1380e3e3264eb02bec24dd909c1e093be271"
FALLBACK_GATEWAY = "2af7e9e0c1342e7ea2961c859dd73021879cbffa"


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


def test_disabled_state_is_inert_and_rejects_retained_endpoint(tmp_path: Path) -> None:
    guard = load_guard()
    config = guard.load_config(
        write_options(
            tmp_path,
            {
                "modbus_tcp_enabled": False,
                "modbus_tcp_endpoint": "",
                "modbus_tcp_dial_timeout": "5s",
            },
        )
    )
    assert config.enabled is False
    assert config.endpoint == ""
    assert config.endpoint_ref == ""

    with pytest.raises(guard.ConfigError):
        guard.load_config(
            write_options(
                tmp_path,
                {
                    "modbus_tcp_enabled": False,
                    "modbus_tcp_endpoint": "tcp://192.0.2.40:502",
                    "modbus_tcp_dial_timeout": "5s",
                },
            )
        )


def test_cli_error_and_redactor_never_emit_endpoint_or_credentials(tmp_path: Path) -> None:
    endpoint = "tcp://operator:topsecret@192.0.2.40:502"
    options = write_options(tmp_path, enabled_options(modbus_tcp_endpoint=endpoint))
    result = subprocess.run(
        [sys.executable, str(GUARD_PATH), "validate", "--options", str(options)],
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode != 0
    assert endpoint not in result.stderr
    assert "topsecret" not in result.stderr

    env = os.environ.copy()
    env["HELIANTHUS_MODBUS_REDACT_VALUE"] = "tcp://192.0.2.40:502"
    redacted = subprocess.run(
        [sys.executable, str(GUARD_PATH), "redact"],
        input="dial tcp://192.0.2.40:502 and 192.0.2.40:502 failed\n",
        text=True,
        capture_output=True,
        env=env,
        check=True,
    )
    assert "192.0.2.40" not in redacted.stdout
    assert redacted.stdout == "dial [REDACTED_MODBUS_ENDPOINT] and [REDACTED_MODBUS_ENDPOINT] failed\n"


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
    assert '"${modbus_tcp_endpoint}"' in run
    assert "modbus_runtime_guard.py" in run
    assert "MODBUS_RECOVERY_MAX_ATTEMPTS=3" in run
    assert "helianthus-gateway-fallback" in run
    assert "-modbus-tcp-enabled" not in run.split("modbus_fallback_args", 1)[-1]

