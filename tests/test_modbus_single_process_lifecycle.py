import json
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


def test_guard_only_validates_and_materializes_runtime_configuration() -> None:
    guard = GUARD.read_text(encoding="utf-8")

    assert 'commands.add_parser("validate")' in guard
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
