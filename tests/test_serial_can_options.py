from __future__ import annotations

import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "helianthus/config.json"
BOM = ROOT / "helianthus/bom.json"
RUN = ROOT / "helianthus/rootfs/etc/services.d/helianthus-gateway/run"
HELPER = ROOT / "helianthus/rootfs/usr/share/helianthus/serial_can_options.py"

spec = importlib.util.spec_from_file_location("serial_can_options", HELPER)
assert spec is not None and spec.loader is not None
serial_can_options = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = serial_can_options
spec.loader.exec_module(serial_can_options)

CONFIG_JSON = json.loads(CONFIG.read_text(encoding="utf-8"))

GROWATT_IDENTITY = {
    "growatt_bms_rs485_enabled": True,
    "growatt_bms_rs485_asset_id": "storage-site-b",
    "growatt_bms_rs485_source_id": "growatt-bms-rs485-0",
    "growatt_bms_rs485_source_epoch": "epoch-1",
    "growatt_bms_rs485_driver_generation": 1,
    "growatt_bms_rs485_unit_id": 1,
    "growatt_bms_rs485_serial_path": "/dev/ttyUSB0",
}
TESLA_IDENTITY = {
    "tesla_gen3_hsc_retained_enabled": True,
    "tesla_gen3_hsc_endpoint_id": "wc3-endpoint",
    "tesla_gen3_hsc_asset_id": "wc3-asset",
    "tesla_gen3_hsc_source_id": "wc3-source",
    "tesla_gen3_hsc_source_epoch": "epoch-1",
    "tesla_gen3_hsc_clock_epoch": "clock-1",
    "tesla_gen3_hsc_evse_id": "evse-1",
    "tesla_gen3_hsc_connector_id": "connector-1",
    "tesla_gen3_hsc_driver_generation": 1,
    "tesla_gen3_hsc_node": 3,
}
SERIAL_KEYS = [key for key in CONFIG_JSON["options"] if key.startswith(("growatt_", "tesla_"))]
SERIAL_SCHEMA_KEYS = [key for key in CONFIG_JSON["schema"] if key.startswith(("growatt_", "tesla_"))]


def options_with_defaults(overrides: dict) -> dict:
    """Options as Supervisor would persist them: add-on defaults plus overrides."""
    merged = {key: CONFIG_JSON["options"][key] for key in SERIAL_KEYS}
    merged.update(overrides)
    return merged


def test_serial_device_access_and_both_families_disabled_by_default() -> None:
    assert CONFIG_JSON["uart"] is True
    assert "devices" not in CONFIG_JSON
    assert "privileged" not in CONFIG_JSON and "full_access" not in CONFIG_JSON
    assert CONFIG_JSON["options"]["growatt_bms_rs485_enabled"] is False
    assert CONFIG_JSON["options"]["tesla_gen3_hsc_retained_enabled"] is False
    assert CONFIG_JSON["schema"]["growatt_bms_rs485_enabled"] == "bool"
    assert CONFIG_JSON["schema"]["tesla_gen3_hsc_retained_enabled"] == "bool"


def test_every_option_has_a_schema_entry_and_every_schema_entry_is_used() -> None:
    schema_keys = set(SERIAL_SCHEMA_KEYS)
    emitted = {key for key, _, _ in serial_can_options.GROWATT_FIELDS + serial_can_options.TESLA_FIELDS}
    emitted |= {serial_can_options.GROWATT_ENABLED[0], serial_can_options.TESLA_ENABLED[0]}
    assert schema_keys == emitted
    assert set(SERIAL_KEYS) <= schema_keys
    # Options without a default must be optional in the schema.
    for key in schema_keys - set(SERIAL_KEYS):
        assert CONFIG_JSON["schema"][key].endswith("?"), key


def test_default_options_emit_no_gateway_flag() -> None:
    assert serial_can_options.build_args({}) == []
    assert serial_can_options.build_args(options_with_defaults({})) == []
    # A full options document with the shipped defaults, not just the new keys.
    assert serial_can_options.build_args(CONFIG_JSON["options"]) == []


def test_disabled_family_ignores_stale_active_fields() -> None:
    stale = options_with_defaults(
        {**GROWATT_IDENTITY, **TESLA_IDENTITY, "growatt_bms_rs485_enabled": False,
         "tesla_gen3_hsc_retained_enabled": False}
    )
    assert serial_can_options.build_args(stale) == []


def test_growatt_enabled_maps_every_option_to_its_flag() -> None:
    args = serial_can_options.build_args(options_with_defaults(GROWATT_IDENTITY))
    assert args == [
        "-growatt-bms-rs485-enabled=true",
        "-growatt-bms-rs485-asset-id", "storage-site-b",
        "-growatt-bms-rs485-source-id", "growatt-bms-rs485-0",
        "-growatt-bms-rs485-source-epoch", "epoch-1",
        "-growatt-bms-rs485-driver-generation", "1",
        "-growatt-bms-rs485-unit-id", "1",
        "-growatt-bms-rs485-serial-path", "/dev/ttyUSB0",
        "-growatt-bms-rs485-baud", "9600",
        "-growatt-bms-rs485-parity", "none",
        "-growatt-bms-rs485-stop-bits", "1",
        "-growatt-bms-rs485-response-timeout", "500ms",
        "-growatt-bms-rs485-max-response-delay", "250ms",
        "-growatt-bms-rs485-max-quiescence", "2s",
    ]
    assert not any(arg.startswith("-tesla") for arg in args)


def test_growatt_overrides_reach_the_gateway() -> None:
    args = serial_can_options.build_args(
        options_with_defaults(
            {**GROWATT_IDENTITY, "growatt_bms_rs485_baud": 19200, "growatt_bms_rs485_parity": "even",
             "growatt_bms_rs485_stop_bits": 2, "growatt_bms_rs485_unit_id": 247}
        )
    )
    pairs = dict(zip(args[1::2], args[2::2]))
    assert pairs["-growatt-bms-rs485-baud"] == "19200"
    assert pairs["-growatt-bms-rs485-parity"] == "even"
    assert pairs["-growatt-bms-rs485-stop-bits"] == "2"
    assert pairs["-growatt-bms-rs485-unit-id"] == "247"


def test_tesla_enabled_maps_identity_epochs_and_fixed_profile_only() -> None:
    args = serial_can_options.build_args(options_with_defaults(TESLA_IDENTITY))
    assert args == [
        "-tesla-gen3-hsc-retained-enabled=true",
        "-tesla-gen3-hsc-endpoint-id", "wc3-endpoint",
        "-tesla-gen3-hsc-asset-id", "wc3-asset",
        "-tesla-gen3-hsc-source-id", "wc3-source",
        "-tesla-gen3-hsc-source-epoch", "epoch-1",
        "-tesla-gen3-hsc-clock-epoch", "clock-1",
        "-tesla-gen3-hsc-evse-id", "evse-1",
        "-tesla-gen3-hsc-connector-id", "connector-1",
        "-tesla-gen3-hsc-driver-generation", "1",
        "-tesla-gen3-hsc-node", "3",
        "-tesla-gen3-hsc-profile", "wc3_24_44_3",
    ]
    # Non-send owner: no serial path, baud or other acquisition flag is mapped.
    assert not any("serial" in arg or "baud" in arg for arg in args)


def test_both_families_can_be_enabled_together() -> None:
    args = serial_can_options.build_args(options_with_defaults({**GROWATT_IDENTITY, **TESLA_IDENTITY}))
    assert args[0] == "-growatt-bms-rs485-enabled=true"
    assert "-tesla-gen3-hsc-retained-enabled=true" in args


@pytest.mark.parametrize(
    "override",
    [
        {"growatt_bms_rs485_enabled": "true"},
        {"growatt_bms_rs485_asset_id": ""},
        {"growatt_bms_rs485_asset_id": "has space"},
        {"growatt_bms_rs485_source_id": "storage-site-b"},
        {"growatt_bms_rs485_source_epoch": ""},
        {"growatt_bms_rs485_driver_generation": 0},
        {"growatt_bms_rs485_driver_generation": True},
        {"growatt_bms_rs485_unit_id": 0},
        {"growatt_bms_rs485_unit_id": 248},
        {"growatt_bms_rs485_serial_path": ""},
        {"growatt_bms_rs485_serial_path": "ttyUSB0"},
        {"growatt_bms_rs485_serial_path": "/dev/../etc/passwd"},
        {"growatt_bms_rs485_baud": 0},
        {"growatt_bms_rs485_parity": "mark"},
        {"growatt_bms_rs485_stop_bits": 3},
        {"growatt_bms_rs485_response_timeout": "0s"},
        {"growatt_bms_rs485_response_timeout": "fast"},
        {"growatt_bms_rs485_max_quiescence": "250ms"},
        {"growatt_bms_rs485_max_quiescence": "100ms"},
    ],
)
def test_invalid_enabled_growatt_options_are_rejected(override: dict) -> None:
    with pytest.raises(serial_can_options.ConfigError):
        serial_can_options.build_args(options_with_defaults({**GROWATT_IDENTITY, **override}))


@pytest.mark.parametrize(
    "override",
    [
        {"tesla_gen3_hsc_retained_enabled": 1},
        {"tesla_gen3_hsc_endpoint_id": ""},
        {"tesla_gen3_hsc_source_id": "wc3-asset"},
        {"tesla_gen3_hsc_clock_epoch": "bad epoch"},
        {"tesla_gen3_hsc_driver_generation": 0},
        {"tesla_gen3_hsc_node": 0},
        {"tesla_gen3_hsc_node": 248},
    ],
)
def test_invalid_enabled_tesla_options_are_rejected(override: dict) -> None:
    with pytest.raises(serial_can_options.ConfigError):
        serial_can_options.build_args(options_with_defaults({**TESLA_IDENTITY, **override}))


def test_missing_required_option_is_rejected_when_enabled() -> None:
    options = options_with_defaults(GROWATT_IDENTITY)
    del options["growatt_bms_rs485_driver_generation"]
    with pytest.raises(serial_can_options.ConfigError, match="driver_generation"):
        serial_can_options.build_args(options)


def run_helper(tmp_path: Path, options: dict) -> subprocess.CompletedProcess[str]:
    path = tmp_path / "options.json"
    path.write_text(json.dumps(options), encoding="utf-8")
    return subprocess.run(
        [sys.executable, "-I", str(HELPER), "argv", "--options", str(path)],
        capture_output=True,
        text=True,
        check=False,
    )


def test_cli_emits_an_empty_array_for_the_disabled_default(tmp_path: Path) -> None:
    result = run_helper(tmp_path, CONFIG_JSON["options"])
    assert result.returncode == 0
    assert result.stdout == "SERIAL_CAN_ARGS=()\n"
    assert run_helper(tmp_path, {}).stdout == "SERIAL_CAN_ARGS=()\n"


def test_cli_output_evaluates_to_the_exact_argv_in_bash(tmp_path: Path) -> None:
    options = options_with_defaults({**GROWATT_IDENTITY, "growatt_bms_rs485_asset_id": "a'b$c"})
    result = run_helper(tmp_path, options)
    assert result.returncode == 0
    script = result.stdout + 'printf "%s\\n" "${SERIAL_CAN_ARGS[@]}"\n'
    evaluated = subprocess.run(["bash", "-c", script], capture_output=True, text=True, check=True)
    assert evaluated.stdout.splitlines() == serial_can_options.build_args(options)


def test_cli_rejects_invalid_options_without_output(tmp_path: Path) -> None:
    result = run_helper(tmp_path, options_with_defaults({**GROWATT_IDENTITY, "growatt_bms_rs485_unit_id": 0}))
    assert result.returncode == 2
    assert result.stdout == ""
    assert "growatt_bms_rs485_unit_id" in result.stderr


def test_wrapper_flag_probe_list_matches_helper_and_pinned_gateway_flags() -> None:
    run = RUN.read_text(encoding="utf-8")
    start = run.index("missing_serial_can_flags=()")
    block = run[start : run.index("done\n", start)]
    listed = set(re.findall(r"^\s+((?:growatt-bms-rs485|tesla-gen3-hsc)-[a-z0-9-]+?)(?: \\|;)", block, re.M))
    assert listed == serial_can_options.all_flags()
    bom_flags = set(json.loads(BOM.read_text(encoding="utf-8"))["gateway_cli_flags"])
    assert listed <= bom_flags


def test_wrapper_appends_serial_args_before_the_single_exec() -> None:
    run = RUN.read_text(encoding="utf-8")
    append = 'gateway_args+=("${SERIAL_CAN_ARGS[@]}")'
    exec_line = 'exec "${gateway_bin}" "${gateway_args[@]}"'
    assert run.count(exec_line) == 1
    assert run.count(append) == 1
    assert run.index(append) < run.index(exec_line)
    assert 'SERIAL_CAN_ARGS=()' in run
    # The disabled default must stay a no-op: nothing is appended unconditionally.
    assert 'if [ "${#SERIAL_CAN_ARGS[@]}" -ne 0 ]; then gateway_args+=' in run


def test_docs_state_the_non_send_scope_of_the_tesla_options() -> None:
    readme = (ROOT / "helianthus/README.md").read_text(encoding="utf-8")
    assert "tesla_gen3_hsc_retained_enabled" in readme
    assert "non-send" in readme
    assert "growatt_bms_rs485_enabled" in readme
