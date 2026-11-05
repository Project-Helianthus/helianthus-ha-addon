#!/usr/bin/env python3
"""Validate the add-on's Modbus TCP configuration.

Configuration v1 is the three scalar options. Configuration v2 is the list
option ``modbus_tcp_endpoints``: it is validated atomically and materialized as
one protected endpoints document. Nothing here ever prints an endpoint.
"""

from __future__ import annotations

import argparse
import ipaddress
import json
import os
import re
import shlex
import sys
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit


MAX_DIAL_TIMEOUT_MS = 30_000
MIN_DIAL_TIMEOUT_MS = 100
_DURATION_RE = re.compile(r"^([1-9][0-9]*)(ms|s)$")
_HOST_LABEL_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?$")

# Configuration v2: the members, bounds and categories below restate the docs-ebus
# page api/modbus-multi-endpoint-runtime.md for the options the add-on carries.
ENDPOINTS_CONTRACT = "helianthus.modbus-tcp-endpoints.v2"
MAX_ENTRIES = 8
MAX_ENDPOINT_BYTES = 288
MAX_UNITS = 32
MAX_UNIT = 247
MAX_DOCUMENT_BYTES = 16_384
V1_DIAL_TIMEOUT = "5s"
_LABEL_RE = re.compile(r"[a-z][a-z0-9]*(?:-[a-z0-9]+)*")
# Closed family table. Case, spacing and aliases are not normalized.
FAMILIES = ("sunspec", "huawei.smartlogger", "huawei.emma", "huawei.sdongle")
# Option key, document member, minimum, maximum. The pacing object of a document entry is flat
# in the options because the Supervisor schema cannot mark a nested object optional.
PACING_OPTIONS = (
    ("pacing_gap_ms", "gap_ms", 50, 2000),
    ("pacing_settle_ms", "settle_ms", 0, 10_000),
    ("pacing_cycle_s", "cycle_s", 15, 3600),
    ("pacing_backoff_floor_s", "backoff_floor_s", 1, 300),
    ("pacing_backoff_ceiling_s", "backoff_ceiling_s", 5, 3600),
)
ENTRY_REQUIRED = ("label", "family", "endpoint")
ENTRY_OPTIONAL = ("dial_timeout", "units") + tuple(option for option, *_ in PACING_OPTIONS)
ENTRY_KEYS = ENTRY_REQUIRED + ENTRY_OPTIONAL
CATEGORIES = (
    "MIXED_CONFIGURATION",
    "INVALID_DOCUMENT",
    "TOO_MANY_ENTRIES",
    "MISSING_FIELD",
    "UNKNOWN_MEMBER",
    "INVALID_LABEL",
    "UNKNOWN_FAMILY",
    "INVALID_ENDPOINT",
    "INVALID_TIMEOUT",
    "INVALID_UNITS",
    "INVALID_PACING",
    "DUPLICATE_LABEL",
    "DUPLICATE_ENDPOINT",
)  # EMPTY_LIST is the gateway's: an empty option list selects configuration v1.
_MAX_NESTING = 3


class ConfigError(ValueError):
    pass


class ConfigRejection(ConfigError):
    """A configuration v2 rejection: one static category and, when entry-local, the entry position."""

    def __init__(self, category: str, entry: int | None = None) -> None:
        super().__init__(category)
        self.category = category
        self.entry = entry

    def summary(self) -> str:
        return self.category if self.entry is None else f"{self.category} (entry {self.entry})"


@dataclass(frozen=True)
class Entry:
    label: str
    family: str
    endpoint: str = field(repr=False)
    dial_timeout: str | None = None
    units: tuple[int, ...] | None = None
    pacing: tuple[tuple[str, int], ...] = ()


@dataclass(frozen=True)
class Config:
    enabled: bool
    endpoint: str
    dial_timeout: str
    endpoints: tuple[Entry, ...] = ()


def _duration_milliseconds(value: str) -> int:
    match = _DURATION_RE.fullmatch(value)
    if match is None:
        raise ConfigError("invalid duration")
    amount = int(match.group(1), 10)
    milliseconds = amount if match.group(2) == "ms" else amount * 1000
    if not MIN_DIAL_TIMEOUT_MS <= milliseconds <= MAX_DIAL_TIMEOUT_MS:
        raise ConfigError("duration outside bounds")
    return milliseconds


def _valid_host(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        pass
    if len(host) > 253:
        return False
    labels = host[:-1].split(".") if host.endswith(".") else host.split(".")
    return bool(labels) and all(_HOST_LABEL_RE.fullmatch(label) for label in labels)


def _validate_endpoint(endpoint: str) -> None:
    if not endpoint or endpoint != endpoint.strip() or any(ord(char) < 32 for char in endpoint):
        raise ConfigError("invalid endpoint")
    try:
        parsed = urlsplit(endpoint)
        port = parsed.port
    except ValueError as error:
        raise ConfigError("invalid endpoint") from error
    if (
        parsed.scheme != "tcp"
        or parsed.username is not None
        or parsed.password is not None
        or not parsed.hostname
        or port is None
        or not 1 <= port <= 65535
        or parsed.path
        or parsed.query
        or parsed.fragment
        or not _valid_host(parsed.hostname)
    ):
        raise ConfigError("invalid endpoint")


def _scan_document(value: object, depth: int = 0) -> None:
    """Document stage: no null, fractional number or control character, and bounded nesting."""
    if depth > _MAX_NESTING or value is None or isinstance(value, float):
        raise ConfigRejection("INVALID_DOCUMENT")
    if isinstance(value, str):
        if any(unicodedata.category(char) == "Cc" for char in value):
            raise ConfigRejection("INVALID_DOCUMENT")
    elif isinstance(value, list):
        for item in value:
            _scan_document(item, depth + 1)
    elif isinstance(value, dict):
        for key, item in value.items():
            _scan_document(key, depth + 1)
            _scan_document(item, depth + 1)


def _endpoint_key(endpoint: object) -> tuple[str, int]:
    """Validate a v2 endpoint and return its normalized (host, port) identity."""
    if type(endpoint) is not str or not endpoint.isascii() or len(endpoint) > MAX_ENDPOINT_BYTES:
        raise ConfigError("invalid endpoint")
    _validate_endpoint(endpoint)
    parsed = urlsplit(endpoint)
    host = parsed.hostname or ""
    if host.endswith("."):
        host = host[:-1]
    try:
        host = str(ipaddress.ip_address(host))
    except ValueError:
        # Not an IP literal: a DNS name keeps its lowercase-insensitive text form as the identity.
        pass
    return host, int(parsed.port or 0)


def _entry(position: int, raw: object) -> tuple[Entry, tuple[str, int]]:
    """Entry stage, in contract order: required, unknown, label, family, endpoint, timeout, units, pacing."""

    def reject(category: str) -> ConfigRejection:
        return ConfigRejection(category, position)

    if type(raw) is not dict:
        raise reject("INVALID_DOCUMENT")
    if any(key not in raw for key in ENTRY_REQUIRED):
        raise reject("MISSING_FIELD")
    if any(key not in ENTRY_KEYS for key in raw):
        raise reject("UNKNOWN_MEMBER")

    label, family = raw["label"], raw["family"]
    if type(label) is not str or not _LABEL_RE.fullmatch(label) or len(label) > 32:
        raise reject("INVALID_LABEL")
    if type(family) is not str or family not in FAMILIES:
        raise reject("UNKNOWN_FAMILY")
    try:
        key = _endpoint_key(raw["endpoint"])
    except ConfigError:
        raise reject("INVALID_ENDPOINT") from None

    dial_timeout = None
    if "dial_timeout" in raw:
        dial_timeout = raw["dial_timeout"]
        try:
            if type(dial_timeout) is not str:
                raise ConfigError("invalid duration")
            _duration_milliseconds(dial_timeout)
        except ConfigError:
            raise reject("INVALID_TIMEOUT") from None

    units = None
    if "units" in raw:
        listed = raw["units"]
        if (
            type(listed) is not list
            or not 1 <= len(listed) <= MAX_UNITS
            or any(type(unit) is not int or not 1 <= unit <= MAX_UNIT for unit in listed)
            or len(set(listed)) != len(listed)
            or (family == "sunspec" and listed != [1])
        ):
            raise reject("INVALID_UNITS")
        units = tuple(listed)

    pacing = []
    for option, member, minimum, maximum in PACING_OPTIONS:
        if option in raw:
            value = raw[option]
            if type(value) is not int or not minimum <= value <= maximum:
                raise reject("INVALID_PACING")
            pacing.append((member, value))
    chosen = dict(pacing)
    if "backoff_floor_s" in chosen and "backoff_ceiling_s" in chosen and (
        chosen["backoff_floor_s"] > chosen["backoff_ceiling_s"]
    ):
        raise reject("INVALID_PACING")
    return Entry(label, family, raw["endpoint"], dial_timeout, units, tuple(pacing)), key


def _load_endpoint_list(payload: dict, listed: object) -> Config:
    """Configuration v2. The first failing check decides the single reported category."""
    if (
        payload.get("modbus_tcp_endpoint", "") != ""
        or payload.get("modbus_tcp_dial_timeout", V1_DIAL_TIMEOUT) != V1_DIAL_TIMEOUT
    ):
        raise ConfigRejection("MIXED_CONFIGURATION")
    _scan_document(listed)
    if type(listed) is not list:
        raise ConfigRejection("INVALID_DOCUMENT")
    if len(listed) > MAX_ENTRIES:
        raise ConfigRejection("TOO_MANY_ENTRIES")
    parsed = [_entry(position, raw) for position, raw in enumerate(listed)]
    entries = tuple(entry for entry, _ in parsed)
    keys = [key for _, key in parsed]
    for category, values in (
        ("DUPLICATE_LABEL", [entry.label for entry in entries]),
        ("DUPLICATE_ENDPOINT", keys),
    ):
        if len(set(values)) != len(values):
            raise ConfigRejection(category)
    return Config(True, "", V1_DIAL_TIMEOUT, entries)


def load_config(path: Path) -> Config:
    try:
        payload = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ConfigError("invalid options document") from error
    if not isinstance(payload, dict):
        raise ConfigError("options document must be an object")

    enabled = payload.get("modbus_tcp_enabled", False)
    if type(enabled) is not bool:
        raise ConfigError("invalid enabled option type")
    if not enabled:
        return Config(False, "", "")

    listed = payload.get("modbus_tcp_endpoints", [])
    if type(listed) is not list or listed:
        return _load_endpoint_list(payload, listed)

    endpoint = payload.get("modbus_tcp_endpoint", "")
    dial_timeout = payload.get("modbus_tcp_dial_timeout", "5s")
    if not isinstance(endpoint, str) or not isinstance(dial_timeout, str):
        raise ConfigError("invalid active option type")
    _duration_milliseconds(dial_timeout)
    _validate_endpoint(endpoint)
    return Config(True, endpoint, dial_timeout)


def _shell_assignment(name: str, value: str) -> str:
    return f"{name}={shlex.quote(value)}"


def endpoints_document(entries: tuple[Entry, ...]) -> bytes:
    """The closed endpoints document: compact ASCII JSON, members only when the operator set them."""
    members = []
    for entry in entries:
        item: dict[str, object] = {"label": entry.label, "family": entry.family, "endpoint": entry.endpoint}
        if entry.dial_timeout is not None:
            item["dial_timeout"] = entry.dial_timeout
        if entry.units is not None:
            item["units"] = list(entry.units)
        if entry.pacing:
            item["pacing"] = dict(entry.pacing)
        members.append(item)
    body = json.dumps({"contract": ENDPOINTS_CONTRACT, "endpoints": members}, separators=(",", ":")).encode("ascii")
    if len(body) > MAX_DOCUMENT_BYTES:
        raise ConfigRejection("INVALID_DOCUMENT")
    return body


def _remove(path: Path) -> None:
    try:
        os.unlink(path)
    except FileNotFoundError:
        # Nothing to remove: the target already being absent is the wanted end state.
        pass


def _staging(path: Path) -> Path:
    return path.with_name(path.name + ".tmp")


def materialize(config: Config, path: Path) -> None:
    """Write the endpoints document atomically: mode 0600 in a 0700 directory, staged then renamed."""
    if not config.endpoints:
        raise ConfigError("no endpoint list")
    body = endpoints_document(config.endpoints)
    directory = path.parent
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(directory, 0o700)
    staging = _staging(path)
    _remove(staging)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    try:
        with os.fdopen(os.open(staging, flags, 0o600), "wb") as handle:
            os.fchmod(handle.fileno(), 0o600)
            handle.write(body)
        os.replace(staging, path)
    except BaseException:
        _remove(staging)
        raise


def _validate_command(args: argparse.Namespace) -> int:
    config = load_config(args.options)
    print(_shell_assignment("MODBUS_TCP_ENABLED", str(config.enabled).lower()))
    print(_shell_assignment("MODBUS_TCP_ENDPOINT", config.endpoint))
    print(_shell_assignment("MODBUS_TCP_DIAL_TIMEOUT", config.dial_timeout))
    if config.endpoints:
        print(_shell_assignment("MODBUS_TCP_CONFIG", "v2"))
    return 0


def _materialize_command(args: argparse.Namespace) -> int:
    try:
        # Earlier material goes first, so a rejected list leaves no document behind.
        _remove(args.document)
        _remove(_staging(args.document))
        config = load_config(args.options)
        materialize(config, args.document)
    except OSError:
        print("unable to materialize the Modbus TCP endpoints document", file=sys.stderr)
        return 2
    return 0


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser()
    commands = result.add_subparsers(dest="command", required=True)
    validate = commands.add_parser("validate")
    validate.add_argument("--options", type=Path, required=True)
    validate.set_defaults(handler=_validate_command)
    document = commands.add_parser("materialize")
    document.add_argument("--options", type=Path, required=True)
    document.add_argument("--document", type=Path, required=True)
    document.set_defaults(handler=_materialize_command)
    return result


def main() -> int:
    args = parser().parse_args()
    try:
        return args.handler(args)
    except ConfigRejection as error:
        print(f"invalid Modbus TCP configuration: {error.summary()}", file=sys.stderr)
        return 2
    except (ConfigError, OSError, ValueError):
        print("invalid Modbus TCP configuration", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
