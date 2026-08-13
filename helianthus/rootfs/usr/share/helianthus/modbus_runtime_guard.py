#!/usr/bin/env python3
"""Validate and report the add-on's bounded Modbus TCP runtime configuration."""

from __future__ import annotations

import argparse
import hashlib
import ipaddress
import json
import math
import os
import re
import shlex
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit


CONTRACT = "helianthus.modbus-addon-health.v1"
MAX_DIAL_TIMEOUT_MS = 30_000
MIN_DIAL_TIMEOUT_MS = 100
_DURATION_RE = re.compile(r"^([1-9][0-9]*)(ms|s)$")
_HOST_LABEL_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?$")
_STATES = {
    "DISABLED",
    "CONFIG_VALIDATED",
    "RUNNING",
    "RECOVERY_RETRY",
    "FALLBACK_ACTIVE",
    "EXITED_AFTER_STARTUP_WINDOW",
}


class ConfigError(ValueError):
    pass


@dataclass(frozen=True)
class Config:
    enabled: bool
    endpoint: str
    dial_timeout: str
    startup_window_seconds: int
    endpoint_ref: str


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


def _validate_endpoint(endpoint: str) -> str:
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
    return parsed.netloc


def load_config(path: Path) -> Config:
    try:
        payload = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ConfigError("invalid options document") from error
    if not isinstance(payload, dict):
        raise ConfigError("options document must be an object")

    enabled = payload.get("modbus_tcp_enabled", False)
    endpoint = payload.get("modbus_tcp_endpoint", "")
    dial_timeout = payload.get("modbus_tcp_dial_timeout", "5s")
    if type(enabled) is not bool or not isinstance(endpoint, str) or not isinstance(dial_timeout, str):
        raise ConfigError("invalid option type")

    timeout_ms = _duration_milliseconds(dial_timeout)
    if not enabled:
        return Config(False, "", dial_timeout, 0, "")

    _validate_endpoint(endpoint)
    endpoint_ref = "sha256:" + hashlib.sha256(endpoint.encode("utf-8")).hexdigest()[:16]
    startup_window = max(5, min(40, math.ceil(timeout_ms / 1000) + 5))
    return Config(True, endpoint, dial_timeout, startup_window, endpoint_ref)


def write_health(
    path: Path,
    config: Config,
    *,
    state: str,
    attempt: int,
    max_attempts: int,
    binary: str,
    reason: str,
) -> None:
    if state not in _STATES or binary not in {"current", "fallback"}:
        raise ValueError("invalid health state")
    if not 0 <= attempt <= max_attempts or max_attempts <= 0:
        raise ValueError("invalid attempt counters")
    payload = {
        "attempt": attempt,
        "binary": binary,
        "contract": CONTRACT,
        "enabled": config.enabled,
        "endpoint_ref": config.endpoint_ref or None,
        "max_attempts": max_attempts,
        "reason": reason,
        "state": state,
    }
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, sort_keys=True, separators=(",", ":"))
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def _shell_assignment(name: str, value: str) -> str:
    return f"{name}={shlex.quote(value)}"


def _validate_command(args: argparse.Namespace) -> int:
    config = load_config(args.options)
    print(_shell_assignment("MODBUS_TCP_ENABLED", str(config.enabled).lower()))
    print(_shell_assignment("MODBUS_TCP_ENDPOINT", config.endpoint))
    print(_shell_assignment("MODBUS_TCP_DIAL_TIMEOUT", config.dial_timeout))
    print(_shell_assignment("MODBUS_STARTUP_WINDOW_SECONDS", str(config.startup_window_seconds)))
    print(_shell_assignment("MODBUS_ENDPOINT_REF", config.endpoint_ref))
    return 0


def _health_command(args: argparse.Namespace) -> int:
    write_health(
        args.health,
        load_config(args.options),
        state=args.state,
        attempt=args.attempt,
        max_attempts=args.max_attempts,
        binary=args.binary,
        reason=args.reason,
    )
    return 0


def _redact_command(_args: argparse.Namespace) -> int:
    endpoint = os.environ.get("HELIANTHUS_MODBUS_REDACT_VALUE", "")
    values: list[str] = []
    if endpoint:
        values.append(endpoint)
        try:
            netloc = urlsplit(endpoint).netloc
        except ValueError:
            netloc = ""
        if netloc:
            values.append(netloc)
    values = sorted(set(values), key=len, reverse=True)
    for line in sys.stdin:
        for value in values:
            line = line.replace(value, "[REDACTED_MODBUS_ENDPOINT]")
        sys.stdout.write(line)
        sys.stdout.flush()
    return 0


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser()
    commands = result.add_subparsers(dest="command", required=True)
    validate = commands.add_parser("validate")
    validate.add_argument("--options", type=Path, required=True)
    validate.set_defaults(handler=_validate_command)

    health = commands.add_parser("health")
    health.add_argument("--options", type=Path, required=True)
    health.add_argument("--health", type=Path, required=True)
    health.add_argument("--state", choices=sorted(_STATES), required=True)
    health.add_argument("--attempt", type=int, required=True)
    health.add_argument("--max-attempts", type=int, required=True)
    health.add_argument("--binary", choices=("current", "fallback"), required=True)
    health.add_argument("--reason", required=True)
    health.set_defaults(handler=_health_command)

    redact = commands.add_parser("redact")
    redact.set_defaults(handler=_redact_command)
    return result


def main() -> int:
    args = parser().parse_args()
    try:
        return args.handler(args)
    except (ConfigError, OSError, ValueError):
        print("invalid Modbus TCP configuration", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
