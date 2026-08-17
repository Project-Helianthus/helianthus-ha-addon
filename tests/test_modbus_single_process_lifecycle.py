from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / "helianthus/rootfs/etc/services.d/helianthus-gateway/run"
GUARD = ROOT / "helianthus/rootfs/usr/share/helianthus/modbus_runtime_guard.py"
DOCKERFILE = ROOT / "helianthus/Dockerfile"


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
