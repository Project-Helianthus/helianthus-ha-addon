#!/usr/bin/env python3
"""Materialize eeBUS AdminV1 credentials without exposing their values."""

from __future__ import annotations

import argparse
import json
import os
import re
import stat
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit


SECRET_MIN = 32
SECRET_MAX = 256
TTL_RE = re.compile(r"^(\d+(?:\.\d+)?)(ms|s|m|h)$")
TTL_MULTIPLIER = {"ms": 0.001, "s": 1.0, "m": 60.0, "h": 3600.0}


class ConfigurationError(ValueError):
    pass


class RuntimeStoreError(OSError):
    pass


def _emit(status: str, **fields: str) -> None:
    print(json.dumps({"status": status, **fields}, sort_keys=True, separators=(",", ":")))


def _clear_files(runtime_dir: Path) -> bool:
    try:
        info = runtime_dir.lstat()
    except FileNotFoundError:
        return True
    except OSError:
        return False
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
        try:
            runtime_dir.unlink()
            return True
        except OSError:
            return False
    cleared = True
    for name in ("owner", "ha"):
        try:
            (runtime_dir / name).unlink(missing_ok=True)
        except OSError:
            cleared = False
    try:
        for entry in runtime_dir.iterdir():
            if entry.name.startswith(".credential-"):
                try:
                    entry.unlink(missing_ok=True)
                except OSError:
                    cleared = False
    except OSError:
        cleared = False
    return cleared


def _load_options(path: Path) -> dict[str, Any]:
    try:
        info = path.lstat()
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
            raise ConfigurationError("options")
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ConfigurationError("options") from exc
    if not isinstance(value, dict):
        raise ConfigurationError("options")
    return value


def _visible_ascii(value: object, *, minimum: int, maximum: int, reject_colon: bool = False) -> str:
    if not isinstance(value, str) or not minimum <= len(value) <= maximum:
        raise ConfigurationError("text")
    if any(ord(character) < 0x21 or ord(character) > 0x7E for character in value):
        raise ConfigurationError("text")
    if reject_colon and ":" in value:
        raise ConfigurationError("text")
    return value


def _origin(value: object) -> str:
    origin = _visible_ascii(value, minimum=1, maximum=512)
    if origin != origin.strip():
        raise ConfigurationError("origin")
    try:
        parsed = urlsplit(origin)
        _ = parsed.port
    except ValueError as exc:
        raise ConfigurationError("origin") from exc
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.netloc
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise ConfigurationError("origin")
    return origin[:-1] if origin.endswith("/") else origin


def _ttl(value: object) -> str:
    text = _visible_ascii(value, minimum=2, maximum=32)
    matched = TTL_RE.fullmatch(text)
    if matched is None:
        raise ConfigurationError("ttl")
    seconds = float(matched.group(1)) * TTL_MULTIPLIER[matched.group(2)]
    if seconds <= 0 or seconds > 24 * 3600:
        raise ConfigurationError("ttl")
    return text


def _validated_bundle(options: dict[str, Any]) -> tuple[str, str, str, bytes, bytes] | None:
    admin_enabled = options.get("eebus_admin_enabled", False)
    eebus_enabled = options.get("eebus_enabled", False)
    if not isinstance(admin_enabled, bool) or not isinstance(eebus_enabled, bool):
        raise ConfigurationError("enabled")
    if not admin_enabled or not eebus_enabled:
        return None
    username = _visible_ascii(
        options.get("eebus_admin_owner_username"),
        minimum=1,
        maximum=64,
        reject_colon=True,
    )
    origin = _origin(options.get("eebus_admin_origin"))
    session_ttl = _ttl(options.get("eebus_admin_session_ttl"))
    owner = _visible_ascii(
        options.get("eebus_admin_owner_secret"),
        minimum=SECRET_MIN,
        maximum=SECRET_MAX,
    ).encode("ascii")
    ha = _visible_ascii(
        options.get("eebus_admin_ha_secret"),
        minimum=SECRET_MIN,
        maximum=SECRET_MAX,
    ).encode("ascii")
    if owner == ha:
        raise ConfigurationError("credentials")
    return username, origin, session_ttl, owner, ha


def _prepare_runtime_dir(runtime_dir: Path) -> None:
    try:
        runtime_dir.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        parent_info = runtime_dir.parent.lstat()
        if stat.S_ISLNK(parent_info.st_mode) or not stat.S_ISDIR(parent_info.st_mode):
            raise RuntimeStoreError("runtime parent")
        info = runtime_dir.lstat() if runtime_dir.exists() or runtime_dir.is_symlink() else None
        if info is not None and (stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode)):
            raise RuntimeStoreError("runtime directory")
        runtime_dir.mkdir(mode=0o700, exist_ok=True)
        os.chmod(runtime_dir, 0o700, follow_symlinks=False)
    except OSError as exc:
        raise RuntimeStoreError("runtime directory") from exc


def _write_temp(runtime_dir: Path, name: str, value: bytes) -> Path:
    temp = runtime_dir / f".credential-{name}-{os.getpid()}"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(temp, flags, 0o600)
        with os.fdopen(descriptor, "wb", closefd=True) as handle:
            handle.write(value)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temp, 0o600, follow_symlinks=False)
        return temp
    except OSError as exc:
        temp.unlink(missing_ok=True)
        raise RuntimeStoreError("credential write") from exc


def _materialize(runtime_dir: Path, owner: bytes, ha: bytes) -> None:
    _prepare_runtime_dir(runtime_dir)
    for target in (runtime_dir / "owner", runtime_dir / "ha"):
        try:
            if stat.S_ISLNK(target.lstat().st_mode):
                raise RuntimeStoreError("credential target")
        except FileNotFoundError:
            pass
    owner_temp: Path | None = None
    ha_temp: Path | None = None
    try:
        owner_temp = _write_temp(runtime_dir, "owner", owner)
        ha_temp = _write_temp(runtime_dir, "ha", ha)
        os.replace(owner_temp, runtime_dir / "owner")
        owner_temp = None
        os.replace(ha_temp, runtime_dir / "ha")
        ha_temp = None
        directory_fd = os.open(runtime_dir, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except OSError as exc:
        raise RuntimeStoreError("credential commit") from exc
    finally:
        if owner_temp is not None:
            owner_temp.unlink(missing_ok=True)
        if ha_temp is not None:
            ha_temp.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--options", required=True)
    parser.add_argument("--runtime-dir", required=True)
    args = parser.parse_args()
    runtime_dir = Path(args.runtime_dir)
    try:
        options = _load_options(Path(args.options))
        bundle = _validated_bundle(options)
        if bundle is None:
            if _clear_files(runtime_dir):
                _emit("disabled")
            else:
                _emit("unavailable", reason="runtime_store")
            return 0
        username, origin, session_ttl, owner, ha = bundle
        _materialize(runtime_dir, owner, ha)
        _emit(
            "ready",
            owner_username=username,
            origin=origin,
            session_ttl=session_ttl,
        )
        return 0
    except ConfigurationError:
        if _clear_files(runtime_dir):
            _emit("unavailable", reason="configuration")
        else:
            _emit("unavailable", reason="runtime_store")
        return 0
    except (RuntimeStoreError, OSError):
        _clear_files(runtime_dir)
        _emit("unavailable", reason="runtime_store")
        return 0


if __name__ == "__main__":
    sys.exit(main())
