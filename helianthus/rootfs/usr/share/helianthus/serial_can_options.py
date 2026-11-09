#!/usr/bin/env python3
"""Map the add-on's serial acquisition options to gateway argv.

Independent, disabled-by-default families are handled here:

* Growatt BMS RS-485 observer (``growatt-bms-rs485-*`` gateway flags).
* Tesla Gen3 HSC retained owner (``tesla-gen3-hsc-*`` gateway flags). The owner
  is non-send on the pinned gateway: these options configure identity and epochs
  only and open no serial or network path.
* Growatt BMS CAN receive-only observer (``growatt-bms-can-*`` gateway flags). The
  options name one SocketCAN interface and record the operator's precondition
  that the controller is already in listen-only mode; the add-on neither sets nor
  verifies controller mode, bit rate or interface state.
* Explicit Growatt PCS and LINK receive-only families. Native selection and
  evidence remain gateway responsibilities; no traffic can fill missing options.

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
from decimal import Decimal, localcontext
from pathlib import Path


class ConfigError(ValueError):
    pass


TESLA_PROFILE = "wc3_24_44_3"
_DURATION_RE = re.compile(r"^[1-9][0-9]*(ms|s)$")
_PARITIES = ("none", "even", "odd")
MAX_LABEL_LENGTH = 256
# IFNAMSIZ without the terminator.
MAX_CAN_INTERFACE_LENGTH = 15
PROJECT_SUFFIXES = (
    "enabled", "interface", "listen-only-confirmed", "stale-after",
    "project-code", "release", "native-profile", "scope", "bank", "context",
)
PROJECT_EXTRA = {"pcs": "native-contract", "link": "source-selectors"}
_GO_DURATION_PART = re.compile(r"([0-9]+(?:\.[0-9]*)?|\.[0-9]+)(ns|us|µs|μs|ms|s|m|h)")
_DURATION_SCALE = {"ns": 1, "us": 1000, "µs": 1000, "μs": 1000,
                   "ms": 1000000, "s": 1000000000, "m": 60000000000, "h": 3600000000000}


def project_flags() -> set[str]:
    return {f"growatt-bms-{family}-can-{suffix}"
            for family, extra in PROJECT_EXTRA.items() for suffix in (*PROJECT_SUFFIXES, extra)}


def _duration(value: object, key: str, *, positive: bool = True) -> str:
    if not isinstance(value, str) or not value or len(value) > 128:
        raise ConfigError(f"{key} requires a Go duration")
    text = value[1:] if value.startswith("+") else value
    parts = list(_GO_DURATION_PART.finditer(text))
    if text == "0" and not positive:
        return value
    if not parts or "".join(part.group() for part in parts) != text:
        raise ConfigError(f"{key} requires a Go duration")
    with localcontext() as precision:
        precision.prec = 256
        total = sum(int(Decimal(part[1]) * _DURATION_SCALE[part[2]]) for part in parts)
    if total < int(positive) or total > 2**63 - 1:
        raise ConfigError(f"{key} duration outside runtime bounds")
    return value


def _strict_json(value: object, key: str, limit: int) -> list:
    def pairs(items: list) -> dict:
        result = {}
        for name, item in items:
            if name in result:
                raise ConfigError(f"{key} contains duplicate JSON keys")
            result[name] = item
        return result

    def constant(_: str) -> None:
        raise ConfigError(f"{key} contains a non-JSON number")

    if not isinstance(value, str) or len(value.encode("utf-8")) > limit:
        raise ConfigError(f"{key} requires bounded JSON text")
    try:
        result = json.loads(value, object_pairs_hook=pairs, parse_constant=constant)
    except (ValueError, RecursionError) as error:
        raise ConfigError(f"{key} requires strict JSON") from error
    if not isinstance(result, list) or not 1 <= len(result) <= 32:
        raise ConfigError(f"{key} requires 1..32 entries")
    return result


def _keys(value: object, keys: set[str], key: str) -> dict:
    if not isinstance(value, dict) or set(value) != keys:
        raise ConfigError(f"{key} requires exactly the documented keys")
    return value


def _selection(project: object, release: object, key: str) -> None:
    # Syntax only. The native owner admits exact project/release combinations
    # before opening an interface; packaging never infers or normalizes them.
    if not isinstance(project, str) or not re.fullmatch(r"[A-Z][A-Za-z0-9]{3}", project):
        raise ConfigError(f"{key} requires an exact-case four-character project-code")
    if not isinstance(release, str) or not re.fullmatch(r"[0-9]{4}", release):
        raise ConfigError(f"{key} requires an explicit four-digit release")


def _selectors(value: object, project: object, release: object, key: str) -> list[dict]:
    entries = _strict_json(value, key, 16384)
    seen = set()
    for entry in entries:
        if not isinstance(entry, dict):
            raise ConfigError(f"{key} requires source objects")
        defaults = "use_default" in entry
        _keys(entry, {"source", "use_default", "contract"} if defaults else
              {"source", "project_code", "release", "contract"}, key)
        source = _int(entry["source"], key, 1, 254)
        if source in (244, 245) or source in seen:
            raise ConfigError(f"{key} contains a reserved or duplicate source")
        seen.add(source)
        if entry["contract"] not in ("legacy19", "release11"):
            raise ConfigError(f"{key} requires an exact native contract")
        if defaults:
            if entry["use_default"] is not True:
                raise ConfigError(f"{key} use_default must be true")
            _selection(project, release, key)
        else:
            _selection(entry["project_code"], entry["release"], key)
    return entries


_CONTEXT_BYTES = {"source", "destination", "serial_slot", "native_slot", "native_group"}
_CONTEXT_LABELS = {"endpoint", "group", "slot"}
_CONTEXT_BOOLS = {"serial_slot_valid", "slot_valid", "group_valid", "publisher_resolved",
                  "measurement_valid", "temperature_valid", "topology_associated"}


def _contexts(value: object, key: str, family: str, selectors: list[dict] | None) -> None:
    entries = _strict_json(value, key, 131072)
    if len(entries) != (len(selectors) if selectors is not None else 1):
        raise ConfigError(f"{key} requires one context per ordered selection")
    common = None
    for index, entry in enumerate(entries):
        _keys(entry, _CONTEXT_BYTES | _CONTEXT_LABELS | _CONTEXT_BOOLS |
              {"interface_index", "epoch", "field_age", "cells", "sensors"}, key)
        for name in _CONTEXT_BYTES:
            _int(entry[name], key, 0, 255)
        _int(entry["interface_index"], key, 1, 2**63 - 1)
        _int(entry["epoch"], key, 1, 2**64 - 1)
        for name in _CONTEXT_LABELS:
            label = _label(entry[name], key)
            if any(char.isspace() or not char.isprintable() for char in label):
                raise ConfigError(f"{key} requires labels without whitespace or controls")
        for name in _CONTEXT_BOOLS:
            if type(entry[name]) is not bool:
                raise ConfigError(f"{key} requires explicit boolean validity")
        _duration(entry["field_age"], key, positive=False)
        for name, maximum in (("cells", 16), ("sensors", 8)):
            vector = _keys(entry[name], {"count", "count_valid", "gates"}, key)
            count = _int(vector["count"], key, 0, maximum)
            if type(vector["count_valid"]) is not bool or (vector["count_valid"] and count == 0):
                raise ConfigError(f"{key} requires an explicit count and validity")
            if not isinstance(vector["gates"], list) or len(vector["gates"]) != 4:
                raise ConfigError(f"{key} requires four measurement gates")
            for gate in vector["gates"]:
                _keys(gate, {"configured", "valid", "status", "age"}, key)
                if type(gate["configured"]) is not bool or type(gate["valid"]) is not bool:
                    raise ConfigError(f"{key} requires boolean measurement gates")
                if gate["status"] not in ("", "absent", "invalid", "unsupported", "stale", "conflict"):
                    raise ConfigError(f"{key} has an unknown measurement status")
                _duration(gate["age"], key, positive=False)
        if family == "link":
            if entry["source"] != selectors[index]["source"] or entry["destination"] not in (244, 245):
                raise ConfigError(f"{key} requires a matching source and coordinator destination")
            identity = tuple(entry[name] for name in
                             ("interface_index", "destination", "endpoint", "group", "slot", "epoch"))
            if common is not None and common != identity:
                raise ConfigError(f"{key} requires one common route and association identity")
            common = identity


def _project_family(payload: dict, family: str) -> list[str]:
    prefix = f"growatt_bms_{family}_can_"
    flag_prefix = prefix.replace("_", "-")
    enabled = payload.get(prefix + "enabled", False)
    if type(enabled) is not bool:
        raise ConfigError(f"{prefix}enabled must be a boolean")
    if not enabled:
        return []
    values = {suffix: payload.get(prefix + suffix.replace("-", "_"), "")
              for suffix in (*PROJECT_SUFFIXES, PROJECT_EXTRA[family])}
    if values["listen-only-confirmed"] is not True:
        raise ConfigError(f"{prefix}listen_only_confirmed must record the external precondition")
    interface = _convert(values["interface"], prefix + "interface", "can_interface")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", interface):
        raise ConfigError(f"{prefix}interface contains unsafe characters")
    _duration(values["stale-after"], prefix + "stale_after")
    if values["native-profile"] not in ("standard", "extended19", "parallel"):
        raise ConfigError(f"{prefix}native_profile requires an explicit supported profile")
    if values["scope"] not in (("local",) if family == "link" else ("local", "aggregate")):
        raise ConfigError(f"{prefix}scope requires an explicit supported scope")
    bank = "parallel" if values["native-profile"] == "parallel" else "ordinary"
    if values["bank"] != bank:
        raise ConfigError(f"{prefix}bank must explicitly match the profile")
    selectors = None
    if family == "pcs":
        _selection(values["project-code"], values["release"], prefix)
        if values["native-contract"] not in ("", "legacy19", "release11"):
            raise ConfigError(f"{prefix}native_contract must be legacy19 or release11")
    else:
        if values["project-code"] or values["release"]:
            _selection(values["project-code"], values["release"], prefix)
        selectors = _selectors(values["source-selectors"], values["project-code"], values["release"],
                               prefix + "source_selectors")
    _contexts(values["context"], prefix + "context", family, selectors)
    argv = [f"-{flag_prefix}enabled=true"]
    for suffix in (*PROJECT_SUFFIXES[1:], PROJECT_EXTRA[family]):
        value = values[suffix]
        if suffix == "listen-only-confirmed":
            argv.append(f"-{flag_prefix}{suffix}=true")
        elif value != "":
            argv.extend((f"-{flag_prefix}{suffix}", value))
    return argv

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
CAN_FIELDS = (
    ("growatt_bms_can_interface", "growatt-bms-can-interface", "can_interface"),
    ("growatt_bms_can_stale_after", "growatt-bms-can-stale-after", "duration"),
)
GROWATT_CAN_ENABLED = ("growatt_bms_can_enabled", "growatt-bms-can-enabled")
# A precondition the operator records, never a capability the add-on provides.
GROWATT_CAN_LISTEN_ONLY = ("growatt_bms_can_listen_only_confirmed", "growatt-bms-can-listen-only-confirmed")
GROWATT_ENABLED = ("growatt_bms_rs485_enabled", "growatt-bms-rs485-enabled")
TESLA_ENABLED = ("tesla_gen3_hsc_retained_enabled", "tesla-gen3-hsc-retained-enabled")
# Fixed, not an option: the only profile the pinned gateway accepts.
TESLA_PROFILE_FLAG = "tesla-gen3-hsc-profile"


def all_flags() -> set[str]:
    """Every RS-485 and Tesla gateway flag this module can emit."""
    flags = {GROWATT_ENABLED[1], TESLA_ENABLED[1], TESLA_PROFILE_FLAG}
    flags.update(flag for _, flag, _ in GROWATT_FIELDS + TESLA_FIELDS)
    return flags


def can_flags() -> set[str]:
    """Every gateway flag the CAN family can emit."""
    flags = {GROWATT_CAN_ENABLED[1], GROWATT_CAN_LISTEN_ONLY[1]}
    flags.update(flag for _, flag, _ in CAN_FIELDS)
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
    if kind == "can_interface":
        if (
            not isinstance(value, str)
            or not value
            or len(value) > MAX_CAN_INTERFACE_LENGTH
            or value in (".", "..")
            or any(ord(char) <= 0x20 or ord(char) >= 0x7F or char in "/:" for char in value)
        ):
            raise ConfigError(
                f"{key} must be a CAN interface name of 1..{MAX_CAN_INTERFACE_LENGTH} "
                "printable ASCII characters without '/', ':' or whitespace"
            )
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
    """Return the gateway argv for ``payload``; empty when every family is off."""
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

    can = _family(payload, GROWATT_CAN_ENABLED, CAN_FIELDS)
    if can is not None:
        can_argv, _ = can
        confirmed = payload.get(GROWATT_CAN_LISTEN_ONLY[0], False)
        if type(confirmed) is not bool:
            raise ConfigError(f"{GROWATT_CAN_LISTEN_ONLY[0]} must be a boolean")
        if not confirmed:
            raise ConfigError(
                f"{GROWATT_CAN_LISTEN_ONLY[0]} must be true when {GROWATT_CAN_ENABLED[0]} is true: "
                "put the CAN controller in listen-only mode first"
            )
        # Flag order: enabled, interface, listen-only precondition, staleness bound.
        argv.extend(can_argv[:3])
        argv.append(f"-{GROWATT_CAN_LISTEN_ONLY[1]}=true")
        argv.extend(can_argv[3:])
    interfaces = [payload["growatt_bms_can_interface"]] if can is not None else []
    for family in PROJECT_EXTRA:
        project_argv = _project_family(payload, family)
        if project_argv:
            interface = payload[f"growatt_bms_{family}_can_interface"]
            if interface in interfaces:
                raise ConfigError("enabled CAN families require distinct interfaces")
            interfaces.append(interface)
            argv.extend(project_argv)
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
