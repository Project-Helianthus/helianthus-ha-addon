#!/usr/bin/env python3
"""Validate and materialize the add-on's Modbus TCP configuration."""

from __future__ import annotations

import argparse
import contextlib
import ipaddress
import json
import os
import re
import shlex
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit


MAX_DIAL_TIMEOUT_MS = 30_000
MIN_DIAL_TIMEOUT_MS = 100
_DURATION_RE = re.compile(r"^([1-9][0-9]*)(ms|s)$")
_HOST_LABEL_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?$")


class ConfigError(ValueError):
    pass


@dataclass(frozen=True)
class Config:
    enabled: bool
    endpoint: str
    dial_timeout: str


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

    endpoint = payload.get("modbus_tcp_endpoint", "")
    dial_timeout = payload.get("modbus_tcp_dial_timeout", "5s")
    if not isinstance(endpoint, str) or not isinstance(dial_timeout, str):
        raise ConfigError("invalid active option type")
    _duration_milliseconds(dial_timeout)
    _validate_endpoint(endpoint)
    return Config(True, endpoint, dial_timeout)


def write_endpoint_file(path: Path, config: Config) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    path.parent.chmod(0o700)
    if not config.enabled:
        with contextlib.suppress(FileNotFoundError):
            path.unlink()
        return
    descriptor, temporary = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(config.endpoint)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(temporary)


def _shell_assignment(name: str, value: str) -> str:
    return f"{name}={shlex.quote(value)}"


def _validate_command(args: argparse.Namespace) -> int:
    with contextlib.suppress(FileNotFoundError):
        args.endpoint_file.unlink()
    config = load_config(args.options)
    write_endpoint_file(args.endpoint_file, config)
    print(_shell_assignment("MODBUS_TCP_ENABLED", str(config.enabled).lower()))
    print(_shell_assignment("MODBUS_TCP_DIAL_TIMEOUT", config.dial_timeout))
    return 0


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser()
    commands = result.add_subparsers(dest="command", required=True)
    validate = commands.add_parser("validate")
    validate.add_argument("--options", type=Path, required=True)
    validate.add_argument("--endpoint-file", type=Path, required=True)
    validate.set_defaults(handler=_validate_command)
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
