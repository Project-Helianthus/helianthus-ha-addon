import json
import os
import signal
import stat
import subprocess
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / "helianthus/rootfs/etc/services.d/helianthus-gateway/run"
GUARD = ROOT / "helianthus/rootfs/usr/share/helianthus/modbus_runtime_guard.py"
DOCKERFILE = ROOT / "helianthus/Dockerfile"
README = ROOT / "helianthus/README.md"
CHANGELOG = ROOT / "helianthus/CHANGELOG.md"
ROOT_README = ROOT / "README.md"
SMOKE_RUNBOOK = ROOT / "SMOKE_RUNBOOK.md"
CONFIG = ROOT / "helianthus/config.json"


def test_enabled_and_disabled_modbus_share_one_direct_exec_lifecycle() -> None:
    run = RUN.read_text(encoding="utf-8")

    assert run.count('exec "${gateway_bin}" "${gateway_args[@]}"') == 1
    assert 'gateway_args+=("${modbus_args[@]}")' in run
    assert run.index('gateway_args+=("${modbus_args[@]}")') < run.index(
        'exec "${gateway_bin}" "${gateway_args[@]}"'
    )

    for removed in (
        "modbus_child_pid",
        "modbus_redactor_pids",
        "modbus_write_health",
        "modbus_runtime_ready",
        "modbus_run_current",
        "modbus_run_fallback",
        "MODBUS_RECOVERY_MAX_ATTEMPTS",
        "helianthus-gateway-fallback",
        "FALLBACK_ACTIVE",
        "RECOVERY_RETRY",
        "probe-readiness",
    ):
        assert removed not in run


def test_guard_only_validates_runtime_configuration() -> None:
    guard = GUARD.read_text(encoding="utf-8")

    assert 'commands.add_parser("validate")' in guard
    assert "write_endpoint_file" not in guard
    assert "endpoint_file" not in guard
    for removed in (
        'commands.add_parser("health")',
        'commands.add_parser("probe-readiness")',
        'commands.add_parser("redact")',
        "helianthus.modbus-addon-health.v1",
        "FALLBACK_STARTING",
        "RECOVERY_RETRY",
    ):
        assert removed not in guard


def test_container_packages_only_the_current_gateway_binary() -> None:
    dockerfile = DOCKERFILE.read_text(encoding="utf-8")

    assert "/out/gateway ./cmd/gateway" in dockerfile
    assert "gateway-fallback" not in dockerfile
    assert "helianthus-gateway-fallback" not in dockerfile


def test_readme_matches_fail_closed_gateway_override_policy() -> None:
    readme = README.read_text(encoding="utf-8")
    normalized_readme = " ".join(readme.split())
    run = RUN.read_text(encoding="utf-8")

    assert "Persistent gateway executable overrides are not supported" in normalized_readme
    assert "remove that file or symlink before startup" in normalized_readme
    assert "Persistent gateway binary override is not supported" in run
    assert "/data/helianthus-gateway` overrides" not in readme


def test_release_history_keeps_0647_immutable_and_records_0648() -> None:
    changelog = CHANGELOG.read_text(encoding="utf-8")
    release_0648 = changelog.split("## 0.6.48", 1)[1].split("## 0.6.47", 1)[0]
    release_0647 = changelog.split("## 0.6.47", 1)[1].split("## 0.6.46", 1)[0]

    assert "7f1cbea90e0b189486febc656632e9e7430c8500" in release_0648
    assert "225f3d96fee3422bc565870f946af19fac42d471" in release_0647
    assert "7f1cbea90e0b189486febc656632e9e7430c8500" not in release_0647


def test_current_operator_docs_match_release_authority() -> None:
    version = json.loads(CONFIG.read_text(encoding="utf-8"))["version"]
    root_readme = ROOT_README.read_text(encoding="utf-8")
    smoke = SMOKE_RUNBOOK.read_text(encoding="utf-8")

    assert f"Release `{version}` packages" in root_readme
    assert f"For release `{version}`" in smoke
    assert "active Modbus runtime state" not in root_readme


def test_pre_exec_cleanup_retires_health_and_removes_unconsumed_endpoint() -> None:
    run = RUN.read_text(encoding="utf-8")

    assert 'legacy_modbus_health_file="/data/modbus-runtime-health.json"' in run
    assert 'rm -f -- "${legacy_modbus_health_file}"' in run
    assert run.index('rm -f -- "${legacy_modbus_health_file}"') < run.index(
        "transport=$(bashio::config 'transport')"
    )
    assert "trap cleanup_modbus_pre_exec EXIT" in run
    assert 'rm -f -- "${modbus_endpoint_file}"' in run
    assert run.index("trap cleanup_modbus_pre_exec EXIT") < run.index(
        'exec "${gateway_bin}" "${gateway_args[@]}"'
    )


def test_validator_cannot_recreate_endpoint_after_wrapper_termination(
    tmp_path: Path,
) -> None:
    run = RUN.read_text(encoding="utf-8")
    assert "if modbus_eval=$(python3" not in run
    assert 'python3 "${modbus_guard}" validate' in run
    assert '> "${modbus_eval_file}"' in run
    assert run.index('python3 "${modbus_guard}" validate') < run.index(
        'mv -f -- "${modbus_endpoint_staging}" "${modbus_endpoint_file}"'
    )
    terminating_traps = run.split("trap 'exit 130' INT", 1)[1]
    assert terminating_traps.index("abort_modbus_pre_exec_on_signal") < (
        terminating_traps.index("unset MODBUS_TCP_ENDPOINT")
    )

    wrapper = tmp_path / "run-under-test.sh"
    guard = tmp_path / "delayed-guard.py"
    marker = tmp_path / "guard-started"
    endpoint = tmp_path / "modbus-endpoint"
    options = tmp_path / "options.json"
    options.write_text("{}", encoding="utf-8")

    guard.write_text(
        "#!/usr/bin/env python3\n"
        "import argparse, os, pathlib, time\n"
        "parser = argparse.ArgumentParser()\n"
        "parser.add_argument('command')\n"
        "parser.add_argument('--options')\n"
        "args = parser.parse_args()\n"
        "pathlib.Path(os.environ['TEST_GUARD_MARKER']).write_text('started', encoding='utf-8')\n"
        "time.sleep(1)\n"
        "pathlib.Path(os.environ['TEST_ENDPOINT']).write_text('tcp://192.0.2.40:502', encoding='utf-8')\n"
        "print(\"MODBUS_TCP_ENABLED='true'\")\n"
        "print(\"MODBUS_TCP_ENDPOINT='tcp://192.0.2.40:502'\")\n"
        "print(\"MODBUS_TCP_DIAL_TIMEOUT='5s'\")\n",
        encoding="utf-8",
    )
    guard.chmod(guard.stat().st_mode | stat.S_IXUSR)

    prelude = r'''
bashio::config() { printf '\n'; }
bashio::exit.nok() { exit 1; }
'''
    wrapper.write_text(prelude + "\n" + RUN.read_text(encoding="utf-8"), encoding="utf-8")

    env = os.environ | {
        "HELIANTHUS_MODBUS_RUNTIME_GUARD": str(guard),
        "HELIANTHUS_MODBUS_OPTIONS_PATH": str(options),
        "HELIANTHUS_MODBUS_ENDPOINT_FILE": str(endpoint),
        "TEST_GUARD_MARKER": str(marker),
        "TEST_ENDPOINT": str(endpoint),
    }
    process = subprocess.Popen(
        ["bash", str(wrapper)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
    )
    try:
        deadline = time.monotonic() + 2
        while not marker.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert marker.exists(), "validator did not start"
        process.send_signal(signal.SIGTERM)
        process.communicate(timeout=3)
        time.sleep(1.2)
        assert not endpoint.exists()
    finally:
        if process.poll() is None:
            process.kill()
            process.communicate(timeout=1)
