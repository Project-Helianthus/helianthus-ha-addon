#!/usr/bin/env python3
"""Map the add-on's serial acquisition options to gateway argv.

Two independent, disabled-by-default families are handled here:

* Growatt BMS RS-485 observer (``growatt-bms-rs485-*`` gateway flags).
* Tesla Gen3 HSC retained owner (``tesla-gen3-hsc-*`` gateway flags). The owner
  is non-send on the pinned gateway: these options configure identity and epochs
  only and open no serial or network path.

The gateway rejects a disabled family that carries any active field, so a
disabled family contributes no flag at all (not even ``=false``). The result is
printed as a shell array assignment (``SERIAL_CAN_ARGS=(...)``) for ``eval``.
Validation is fail-fast only; the gateway remains the authority.
"""

from __future__ import annotations

import argparse
import json
import re
import shlex
import sys
from pathlib import Path


class ConfigError(ValueError):
    pass


TESLA_PROFILE = "wc3_24_44_3"
_DURATION_RE = re.compile(r"^[1-9][0-9]*(ms|s)$")
_PARITIES = ("none", "even", "odd")
MAX_LABEL_LENGTH = 256

# (option key, gateway flag, kind). Order is the emitted argv order.
GROWATT_FIELDS = (
    ("growatt_bms_rs485_asset_id", "growatt-bms-rs485-asset-id", "label"),
    ("growatt_bms_rs485_source_id", "growatt-bms-rs485-source-id", "label"),
    ("growatt_bms_rs485_source_epoch", "growatt-bms-rs485-source-epoch", "label"),
    ("growatt_bms_rs485_driver_generation", "growatt-bms-rs485-driver-generation", "uint"),
    ("growatt_bms_rs485_unit_id", "growatt-bms-rs485-unit-id", "unit"),
    ("growatt_bms_rs485_serial_path", "growatt-bms-rs485-serial-path", "path"),
    ("growatt_bms_rs485_baud", "growatt-bms-rs485-baud", "baud"),
    ("growatt_bms_rs485_parity", "growatt-bms-rs485-parity", "parity"),
    ("growatt_bms_rs485_stop_bits", "growatt-bms-rs485-stop-bits", "stop_bits"),
    ("growatt_bms_rs485_response_timeout", "growatt-bms-rs485-response-timeout", "duration"),
    ("growatt_bms_rs485_max_response_delay", "growatt-bms-rs485-max-response-delay", "duration"),
    ("growatt_bms_rs485_max_quiescence", "growatt-bms-rs485-max-quiescence", "duration"),
)
TESLA_FIELDS = (
    ("tesla_gen3_hsc_endpoint_id", "tesla-gen3-hsc-endpoint-id", "label"),
    ("tesla_gen3_hsc_asset_id", "tesla-gen3-hsc-asset-id", "label"),
    ("tesla_gen3_hsc_source_id", "tesla-gen3-hsc-source-id", "label"),
    ("tesla_gen3_hsc_source_epoch", "tesla-gen3-hsc-source-epoch", "label"),
    ("tesla_gen3_hsc_clock_epoch", "tesla-gen3-hsc-clock-epoch", "label"),
    ("tesla_gen3_hsc_evse_id", "tesla-gen3-hsc-evse-id", "label"),
    ("tesla_gen3_hsc_connector_id", "tesla-gen3-hsc-connector-id", "label"),
    ("tesla_gen3_hsc_driver_generation", "tesla-gen3-hsc-driver-generation", "uint"),
    ("tesla_gen3_hsc_node", "tesla-gen3-hsc-node", "unit"),
)
GROWATT_ENABLED = ("growatt_bms_rs485_enabled", "growatt-bms-rs485-enabled")
TESLA_ENABLED = ("tesla_gen3_hsc_retained_enabled", "tesla-gen3-hsc-retained-enabled")
# Fixed, not an option: the only profile the pinned gateway accepts.
TESLA_PROFILE_FLAG = "tesla-gen3-hsc-profile"


def all_flags() -> set[str]:
    """Every gateway flag this module can emit."""
    flags = {GROWATT_ENABLED[1], TESLA_ENABLED[1], TESLA_PROFILE_FLAG}
    flags.update(flag for _, flag, _ in GROWATT_FIELDS + TESLA_FIELDS)
    return flags


def _int(value: object, key: str, low: int, high: int) -> int:
    if type(value) is not int or not low <= value <= high:
        raise ConfigError(f"{key} must be an integer in {low}..{high}")
    return value


def _label(value: object, key: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > MAX_LABEL_LENGTH
        or any(ord(char) <= 0x20 or ord(char) == 0x7F for char in value)
    ):
        raise ConfigError(f"{key} must be a non-empty string without whitespace or control characters")
    return value


def _convert(value: object, key: str, kind: str) -> str:
    if kind == "label":
        return _label(value, key)
    if kind == "uint":
        return str(_int(value, key, 1, 2**63 - 1))
    if kind == "unit":
        return str(_int(value, key, 1, 247))
    if kind == "baud":
        return str(_int(value, key, 1, 4_000_000))
    if kind == "stop_bits":
        return str(_int(value, key, 1, 2))
    if kind == "parity":
        if value not in _PARITIES:
            raise ConfigError(f"{key} must be one of {', '.join(_PARITIES)}")
        return str(value)
    if kind == "duration":
        if not isinstance(value, str) or not _DURATION_RE.fullmatch(value):
            raise ConfigError(f"{key} must be a positive duration such as 500ms or 2s")
        return value
    if kind == "path":
        if (
            not isinstance(value, str)
            or not value.startswith("/dev/")
            or len(value) == len("/dev/")
            or ".." in value.split("/")
            or any(ord(char) <= 0x20 or ord(char) == 0x7F for char in value)
        ):
            raise ConfigError(f"{key} must be a /dev/ device path")
        return value
    raise AssertionError(kind)


def _milliseconds(value: str) -> int:
    return int(value[:-2]) if value.endswith("ms") else int(value[:-1]) * 1000


def _family(
    payload: dict, enabled: tuple[str, str], fields: tuple[tuple[str, str, str], ...]
) -> tuple[list[str], dict[str, str]] | None:
    value = payload.get(enabled[0], False)
    if type(value) is not bool:
        raise ConfigError(f"{enabled[0]} must be a boolean")
    if not value:
        return None
    argv = [f"-{enabled[1]}=true"]
    converted: dict[str, str] = {}
    for key, flag, kind in fields:
        if key not in payload:
            raise ConfigError(f"{key} is required when {enabled[0]} is true")
        converted[key] = _convert(payload[key], key, kind)
        argv.extend((f"-{flag}", converted[key]))
    return argv, converted


def build_args(payload: dict) -> list[str]:
    """Return the gateway argv for ``payload``; empty when both families are off."""
    argv: list[str] = []

    growatt = _family(payload, GROWATT_ENABLED, GROWATT_FIELDS)
    if growatt is not None:
        growatt_argv, values = growatt
        if values["growatt_bms_rs485_asset_id"] == values["growatt_bms_rs485_source_id"]:
            raise ConfigError("growatt_bms_rs485_asset_id and growatt_bms_rs485_source_id must differ")
        if _milliseconds(values["growatt_bms_rs485_max_quiescence"]) <= _milliseconds(
            values["growatt_bms_rs485_max_response_delay"]
        ):
            raise ConfigError("growatt_bms_rs485_max_quiescence must exceed growatt_bms_rs485_max_response_delay")
        argv.extend(growatt_argv)

    tesla = _family(payload, TESLA_ENABLED, TESLA_FIELDS)
    if tesla is not None:
        tesla_argv, values = tesla
        if values["tesla_gen3_hsc_asset_id"] == values["tesla_gen3_hsc_source_id"]:
            raise ConfigError("tesla_gen3_hsc_asset_id and tesla_gen3_hsc_source_id must differ")
        argv.extend(tesla_argv)
        argv.extend((f"-{TESLA_PROFILE_FLAG}", TESLA_PROFILE))
    return argv


def load_options(path: Path) -> dict:
    try:
        payload = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ConfigError("invalid options document") from error
    if not isinstance(payload, dict):
        raise ConfigError("options document must be an object")
    return payload


def _argv_command(args: argparse.Namespace) -> int:
    argv = build_args(load_options(args.options))
    print("SERIAL_CAN_ARGS=(" + " ".join(shlex.quote(item) for item in argv) + ")")
    return 0


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser()
    commands = result.add_subparsers(dest="command", required=True)
    argv = commands.add_parser("argv")
    argv.add_argument("--options", type=Path, required=True)
    argv.set_defaults(handler=_argv_command)
    return result


def main() -> int:
    args = parser().parse_args()
    try:
        return args.handler(args)
    except (ConfigError, OSError, ValueError) as error:
        print(f"invalid serial acquisition configuration: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
