from __future__ import annotations

import importlib.util
import json
import re
import shlex
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
CAN_IDENTITY = {
    "growatt_bms_can_enabled": True,
    "growatt_bms_can_interface": "can7",
    "growatt_bms_can_listen_only_confirmed": True,
    "growatt_bms_can_stale_after": "30s",
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
    assert CONFIG_JSON["options"]["growatt_bms_can_enabled"] is False
    assert CONFIG_JSON["options"]["growatt_bms_can_listen_only_confirmed"] is False
    assert CONFIG_JSON["schema"]["growatt_bms_can_enabled"] == "bool"
    assert CONFIG_JSON["schema"]["growatt_bms_can_listen_only_confirmed"] == "bool"
    assert CONFIG_JSON["schema"]["growatt_bms_rs485_enabled"] == "bool"
    assert CONFIG_JSON["schema"]["tesla_gen3_hsc_retained_enabled"] == "bool"


def test_every_option_has_a_schema_entry_and_every_schema_entry_is_used() -> None:
    schema_keys = set(SERIAL_SCHEMA_KEYS)
    emitted = {
        key
        for key, _, _ in serial_can_options.GROWATT_FIELDS
        + serial_can_options.TESLA_FIELDS
        + serial_can_options.CAN_FIELDS
    }
    emitted |= {
        serial_can_options.GROWATT_ENABLED[0],
        serial_can_options.TESLA_ENABLED[0],
        serial_can_options.GROWATT_CAN_ENABLED[0],
        serial_can_options.GROWATT_CAN_LISTEN_ONLY[0],
    }
    emitted |= {flag.replace("-", "_") for flag in serial_can_options.project_flags()}
    assert schema_keys == emitted
    assert set(SERIAL_KEYS) <= schema_keys
    # Options without a default must be optional in the schema.
    for key in schema_keys - set(SERIAL_KEYS):
        assert CONFIG_JSON["schema"][key].endswith("?"), key


def test_packaged_gateway_supports_every_can_flag() -> None:
    bom = json.loads(BOM.read_text(encoding="utf-8"))
    assert serial_can_options.can_flags() <= set(bom["gateway_cli_flags"])


def test_default_options_emit_no_gateway_flag() -> None:
    assert serial_can_options.build_args({}) == []
    assert serial_can_options.build_args(options_with_defaults({})) == []
    # A full options document with the shipped defaults, not just the new keys.
    assert serial_can_options.build_args(CONFIG_JSON["options"]) == []


def test_disabled_family_ignores_stale_active_fields() -> None:
    stale = options_with_defaults(
        {**GROWATT_IDENTITY, **TESLA_IDENTITY, **CAN_IDENTITY, "growatt_bms_rs485_enabled": False,
         "tesla_gen3_hsc_retained_enabled": False, "growatt_bms_can_enabled": False}
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


def test_can_enabled_maps_every_option_to_its_flag() -> None:
    args = serial_can_options.build_args(options_with_defaults(CAN_IDENTITY))
    assert args == [
        "-growatt-bms-can-enabled=true",
        "-growatt-bms-can-interface", "can7",
        "-growatt-bms-can-listen-only-confirmed=true",
        "-growatt-bms-can-stale-after", "30s",
    ]
    assert set(arg[1:].split("=")[0] for arg in args if arg.startswith("-")) == serial_can_options.can_flags()
    # Receive-only: nothing that configures, transmits or acknowledges is mapped.
    assert not any(word in arg for arg in args for word in ("bitrate", "baud", "transmit", "send", "ack"))
    assert not any(arg.startswith(("-growatt-bms-rs485", "-tesla")) for arg in args)


def test_can_defaults_carry_the_documented_stale_bound() -> None:
    enabled = options_with_defaults(
        {
            "growatt_bms_can_enabled": True,
            "growatt_bms_can_interface": "can7",
            "growatt_bms_can_listen_only_confirmed": True,
        }
    )
    assert CONFIG_JSON["options"]["growatt_bms_can_stale_after"] == "10s"
    assert serial_can_options.build_args(enabled)[-2:] == ["-growatt-bms-can-stale-after", "10s"]


def test_can_is_independent_of_the_other_families() -> None:
    args = serial_can_options.build_args(
        options_with_defaults({**GROWATT_IDENTITY, **TESLA_IDENTITY, **CAN_IDENTITY})
    )
    assert args[0] == "-growatt-bms-rs485-enabled=true"
    assert "-tesla-gen3-hsc-retained-enabled=true" in args
    assert args[-6:] == [
        "-growatt-bms-can-enabled=true",
        "-growatt-bms-can-interface", "can7",
        "-growatt-bms-can-listen-only-confirmed=true",
        "-growatt-bms-can-stale-after", "30s",
    ]
    only_can = serial_can_options.build_args(options_with_defaults(CAN_IDENTITY))
    assert not any(arg.startswith(("-growatt-bms-rs485", "-tesla")) for arg in only_can)


@pytest.mark.parametrize("interface", ["can0", "vcan12", "slcan0", "a", "123456789012345", "can-1.x"])
def test_can_interface_names_are_passed_through_verbatim(interface: str) -> None:
    args = serial_can_options.build_args(
        options_with_defaults({**CAN_IDENTITY, "growatt_bms_can_interface": interface})
    )
    assert args[args.index("-growatt-bms-can-interface") + 1] == interface


@pytest.mark.parametrize(
    "override",
    [
        {"growatt_bms_can_enabled": "true"},
        {"growatt_bms_can_enabled": 1},
        {"growatt_bms_can_interface": ""},
        {"growatt_bms_can_interface": None},
        {"growatt_bms_can_interface": 7},
        {"growatt_bms_can_interface": "1234567890123456"},
        {"growatt_bms_can_interface": "can 0"},
        {"growatt_bms_can_interface": "can\t0"},
        {"growatt_bms_can_interface": "can/0"},
        {"growatt_bms_can_interface": "can:0"},
        {"growatt_bms_can_interface": "can\x000"},
        {"growatt_bms_can_interface": "\u00e7an0"},
        {"growatt_bms_can_interface": "."},
        {"growatt_bms_can_interface": ".."},
        {"growatt_bms_can_listen_only_confirmed": False},
        {"growatt_bms_can_listen_only_confirmed": "true"},
        {"growatt_bms_can_listen_only_confirmed": 1},
        {"growatt_bms_can_stale_after": ""},
        {"growatt_bms_can_stale_after": "0s"},
        {"growatt_bms_can_stale_after": "-5s"},
        {"growatt_bms_can_stale_after": "soon"},
        {"growatt_bms_can_stale_after": "5"},
        {"growatt_bms_can_stale_after": 5},
    ],
)
def test_invalid_enabled_can_options_are_rejected(override: dict) -> None:
    with pytest.raises(serial_can_options.ConfigError):
        serial_can_options.build_args(options_with_defaults({**CAN_IDENTITY, **override}))


@pytest.mark.parametrize(
    "missing",
    [
        "growatt_bms_can_interface",
        "growatt_bms_can_stale_after",
    ],
)
def test_missing_can_option_is_rejected_when_enabled(missing: str) -> None:
    options = options_with_defaults(CAN_IDENTITY)
    del options[missing]
    with pytest.raises(serial_can_options.ConfigError, match=missing):
        serial_can_options.build_args(options)


def test_listen_only_precondition_is_named_when_unconfirmed() -> None:
    options = options_with_defaults({**CAN_IDENTITY, "growatt_bms_can_listen_only_confirmed": False})
    with pytest.raises(serial_can_options.ConfigError, match="growatt_bms_can_listen_only_confirmed"):
        serial_can_options.build_args(options)
    del options["growatt_bms_can_listen_only_confirmed"]
    with pytest.raises(serial_can_options.ConfigError, match="growatt_bms_can_listen_only_confirmed"):
        serial_can_options.build_args(options)


def test_a_rejected_can_family_emits_no_partial_argv_for_the_others(tmp_path: Path) -> None:
    options = options_with_defaults(
        {**GROWATT_IDENTITY, **CAN_IDENTITY, "growatt_bms_can_listen_only_confirmed": False}
    )
    result = run_helper(tmp_path, options)
    assert result.returncode == 2
    assert result.stdout == ""
    assert "growatt_bms_can_listen_only_confirmed" in result.stderr
    assert "can7" not in result.stderr


def test_wrapper_probes_emitted_can_flags_by_prefix_and_names_the_missing_ones() -> None:
    run = RUN.read_text(encoding="utf-8")
    assert "-growatt-bms-can-*|-growatt-bms-pcs-can-*|-growatt-bms-link-can-*)" in run
    probe = run.index("-growatt-bms-can-*|")
    assert run.index("missing_serial_can_flags=()") < probe
    assert probe < run.index('bashio::exit.nok "gateway does not support the serial acquisition flags')
    subprocess.run(["bash", "-n", str(RUN)], check=True, capture_output=True)


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


def test_docs_state_the_receive_only_scope_of_the_can_options() -> None:
    readme = (ROOT / "helianthus/README.md").read_text(encoding="utf-8")
    section = readme[readme.index("### Growatt BMS CAN") : readme.index("### Tesla Gen3 HSC")]
    for key in ("growatt_bms_can_enabled", "growatt_bms_can_interface",
                "growatt_bms_can_listen_only_confirmed", "growatt_bms_can_stale_after"):
        assert key in section
    for flag in sorted(serial_can_options.can_flags()):
        assert f"-{flag}" in section
    assert "receive-only" in section
    assert "listen-only" in section


def _wrapper_harness():
    """The real-wrapper harness of the lifecycle tests: stubbed bashio, a recording fake gateway."""
    path = ROOT / "tests/test_modbus_single_process_lifecycle.py"
    spec = importlib.util.spec_from_file_location("lifecycle_wrapper_harness", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


CAN_OPTIONS = {
    "growatt_bms_can_enabled": True,
    "growatt_bms_can_interface": "can7",
    "growatt_bms_can_listen_only_confirmed": True,
    "growatt_bms_can_stale_after": "30s",
}
CAN_ARGV = [
    "-growatt-bms-can-enabled=true", "-growatt-bms-can-interface", "can7",
    "-growatt-bms-can-listen-only-confirmed=true", "-growatt-bms-can-stale-after", "30s",
]


def test_wrapper_refuses_enabled_can_naming_every_flag_the_gateway_lacks(tmp_path: Path) -> None:
    harness = _wrapper_harness()
    run = harness._wrapper_run(tmp_path, CAN_OPTIONS, hidden=tuple(sorted(serial_can_options.can_flags())))
    assert run["result"].returncode == 1 and run["launches"] == []
    last = run["result"].stderr.strip().splitlines()[-1]
    assert last == (
        "NOK: gateway does not support the serial acquisition flags: growatt-bms-can-enabled "
        "growatt-bms-can-interface growatt-bms-can-listen-only-confirmed growatt-bms-can-stale-after"
    )
    assert "can7" not in run["result"].stderr and "can7" not in run["log"]


def test_wrapper_refuses_when_only_one_can_flag_is_missing(tmp_path: Path) -> None:
    harness = _wrapper_harness()
    for flag in sorted(serial_can_options.can_flags()):
        case = tmp_path / flag
        case.mkdir()
        run = harness._wrapper_run(case, CAN_OPTIONS, hidden=(flag,))
        assert run["launches"] == [], flag
        assert run["result"].stderr.strip().splitlines()[-1] == (
            f"NOK: gateway does not support the serial acquisition flags: {flag}"
        ), flag


def test_wrapper_passes_the_can_arguments_with_the_packaged_gateway_flags(tmp_path: Path) -> None:
    harness = _wrapper_harness()
    case = tmp_path / "case"
    case.mkdir()
    run = harness._wrapper_run(case, CAN_OPTIONS)
    argv = harness._argv(run)
    start = argv.index("-growatt-bms-can-enabled=true")
    assert argv[start : start + len(CAN_ARGV)] == CAN_ARGV
    assert not any(arg.startswith(("-growatt-bms-rs485", "-tesla")) for arg in argv)


@pytest.mark.parametrize("identity,key,prefix", [
    (GROWATT_IDENTITY, "growatt_bms_rs485_asset_id", "growatt-bms-rs485-"),
    (TESLA_IDENTITY, "tesla_gen3_hsc_endpoint_id", "tesla-gen3-hsc-"),
])
@pytest.mark.parametrize("value", ["-growatt-bms-can-foo", "-growatt-bms-can-enabled=true"])
@pytest.mark.parametrize("can_enabled", [False, True])
def test_capability_probe_skips_flag_shaped_identity_values(
    identity: dict, key: str, prefix: str, value: str, can_enabled: bool,
) -> None:
    options = options_with_defaults({**identity, key: value, **(CAN_IDENTITY if can_enabled else {})})
    argv = serial_can_options.build_args(options)
    assert argv[argv.index("-" + key.replace("_", "-")) + 1] == value
    hidden = {"growatt-bms-can-interface"} if can_enabled else serial_can_options.can_flags()
    supported = set(json.loads(BOM.read_text(encoding="utf-8"))["gateway_cli_flags"]) - hidden
    # Exercise the actual capability block without executing startup cleanup.
    run = RUN.read_text(encoding="utf-8")
    start = run.index('if [ "${#SERIAL_CAN_ARGS[@]}" -ne 0 ]; then')
    block = run[start:run.index("# Gate `-instance-guid-source`", start)]
    prelude = r'''set -euo pipefail
gateway_supports_flag() {
  printf 'PROBE:%s\n' "$1"
  for supported in "${SUPPORTED[@]}"; do
    if [ "$supported" = "$1" ]; then return 0; fi
  done
  return 1
}
bashio::log.info() { :; }
bashio::exit.nok() { printf '%s\n' "$*" >&2; exit 1; }
'''
    script = prelude + "SERIAL_CAN_ARGS=(" + shlex.join(argv) + ")\n"
    script += "SUPPORTED=(" + shlex.join(sorted(supported)) + ")\n" + block
    result = subprocess.run(["bash", "-c", script], capture_output=True, text=True, check=False)
    expected = {flag for flag in serial_can_options.all_flags() if flag.startswith(prefix)}
    if can_enabled:
        expected |= serial_can_options.can_flags()
        assert result.returncode == 1
        assert result.stderr.strip() == (
            "gateway does not support the serial acquisition flags: growatt-bms-can-interface"
        )
    else:
        assert result.returncode == 0, result.stderr
        assert result.stderr == ""
    probes = result.stdout.splitlines()
    assert set(probes) == {"PROBE:" + flag for flag in expected}
    assert len(probes) == len(expected)


@pytest.mark.parametrize("identity,key", [
    (GROWATT_IDENTITY, "growatt_bms_rs485_asset_id"),
    (TESLA_IDENTITY, "tesla_gen3_hsc_endpoint_id"),
])
@pytest.mark.parametrize("value", ["-growatt-bms-can-foo", "-growatt-bms-can-enabled=true"])
def test_wrapper_keeps_flag_shaped_identity_values_with_can_disabled(
    tmp_path: Path, identity: dict, key: str, value: str,
) -> None:
    harness = _wrapper_harness()
    run = harness._wrapper_run(
        tmp_path, {**identity, key: value}, hidden=tuple(sorted(serial_can_options.can_flags()))
    )
    argv = harness._argv(run)
    assert argv[argv.index("-" + key.replace("_", "-")) + 1] == value


def test_wrapper_passes_no_can_argument_by_default(tmp_path: Path) -> None:
    harness = _wrapper_harness()
    run = harness._wrapper_run(tmp_path, {})
    assert not any("growatt-bms-can" in arg for arg in harness._argv(run))
    assert "Serial acquisition options: disabled" in run["log"]
