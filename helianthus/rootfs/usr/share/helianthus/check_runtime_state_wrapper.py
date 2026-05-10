#!/usr/bin/env python3
"""Helianthus add-on runtime-state wrapper: instance_guid resolution + AD09a guardrail.

Plan: runtime-state-w19-26.locked. ADs implemented here:

- AD09b read precedence: choose meta.instance_guid from /data/runtime_state.json,
  fall through to legacy /data/instance_guid for halt detection only, generate a
  fresh UUIDv4 only when both files are absent.
- AD09a deploy-error guardrail: legacy file present + runtime_state.json absent
  or invalid -> emit HELIANTHUS_MIGRATION_REQUIRED token, write marker file
  /data/.helianthus_migration_required with the complete migration template,
  exit 1 (NOT sysexits-78 per consultant MF-1).
- AD25 fresh-identity diagnostics: when both files are absent, emit
  HELIANTHUS_FRESH_IDENTITY warn token and identity_source=generated.
- AD26 bounded ENOENT retry: tolerate transient absence of runtime_state.json
  with up to 3 attempts at 100ms apart before falling through to AD09b.
- AD27 -instance-guid-source flag: emit "runtime_state" / "legacy_migrated" /
  "generated" / "cli-override" tag based on which read precedence path resolved.

This is the M1_TDD_RED skeleton. Every public function below currently raises
NotImplementedError. The M6_HA_ADDON_MIGRATION PR replaces these with real
bodies; the corresponding pytest tests in tests/test_runtime_state_wrapper.py
turn from RED to GREEN at that point.

CLI surface (used by pr-ci.yml during M1 to avoid CI breakage; the M1 stub
exits 0 with a skip message):

    python3 scripts/check_runtime_state_wrapper.py
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path


RUNTIME_STATE_FILE = "/data/runtime_state.json"
LEGACY_INSTANCE_GUID_FILE = "/data/instance_guid"
MIGRATION_MARKER_FILE = "/data/.helianthus_migration_required"

LOG_TOKEN_MIGRATION_REQUIRED = "HELIANTHUS_MIGRATION_REQUIRED"
LOG_TOKEN_FRESH_IDENTITY = "HELIANTHUS_FRESH_IDENTITY"

EXIT_OK = 0
EXIT_MIGRATION_REQUIRED = 1  # AD09a; explicitly NOT sysexits-78 per consultant MF-1.

# AD22 lowercase UUIDv4 regex (must match the JSON Schema artifact in
# helianthus-docs-ebus runtime-state/runtime_state.schema.json).
INSTANCE_GUID_REGEX = (
    r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)

# AD27 IdentitySource values, mirrored from
# helianthus-ebusgateway/internal/runtimestate.IdentitySource.
IDENTITY_SOURCE_RUNTIME_STATE = "runtime_state"
IDENTITY_SOURCE_LEGACY_MIGRATED = "legacy_migrated"
IDENTITY_SOURCE_GENERATED = "generated"
IDENTITY_SOURCE_CLI_OVERRIDE = "cli-override"

# AD26 retry budget for transient ENOENT on runtime_state.json open.
RUNTIME_STATE_ENOENT_RETRIES = 3
RUNTIME_STATE_ENOENT_BACKOFF_MS = 100

# Migration template (AD09a): the complete schema-valid v1 file the operator
# fills in. written_at uses the epoch sentinel so the operator only has to
# replace the GUID placeholder; gateway will overwrite written_at on first
# eager-persist.
MIGRATION_TEMPLATE = """{
  "schema_version": 1,
  "meta": {
    "instance_guid": "PASTE-LEGACY-GUID-FROM-/data/instance_guid-HERE",
    "written_at": "1970-01-01T00:00:00Z"
  }
}
"""


class ResolveResult:
    """Outcome of resolve_instance_guid.

    Attributes:
        guid: chosen instance_guid (lowercase UUIDv4 string), or empty string
            when AD09a halt was triggered (caller should exit immediately).
        source: AD27 IdentitySource value.
        halt: True when AD09a guardrail tripped; caller MUST exit
            EXIT_MIGRATION_REQUIRED.
        log_lines: structured log lines to emit (each line has the stable token
            prefix per AD09a / AD25).
    """

    def __init__(self, guid: str, source: str, halt: bool, log_lines: list[str]):
        self.guid = guid
        self.source = source
        self.halt = halt
        self.log_lines = log_lines


def _read_runtime_state(path: str) -> tuple[str | None, str | None]:
    """Open and parse runtime_state.json with bounded ENOENT retries (AD26).

    Returns (instance_guid, error_kind). instance_guid is set when the file
    is present + parseable + meta.instance_guid matches the lowercase UUIDv4
    regex. error_kind is one of: None (success), "absent", "corrupt",
    "missing_field", "invalid_uuid".
    """
    last_err: str | None = None
    for attempt in range(RUNTIME_STATE_ENOENT_RETRIES):
        try:
            with open(path, "r", encoding="utf-8") as fp:
                data = json.load(fp)
            # Top-level must be a JSON object; `[]`, `null`, scalars are
            # treated as corrupt so the AD09a halt path runs (previously
            # data.get("meta") raised AttributeError, killing the wrapper
            # before it could write the migration marker — Codex P2).
            if not isinstance(data, dict):
                return None, "corrupt"
            meta = data.get("meta")
            if not isinstance(meta, dict):
                return None, "missing_field"
            guid = meta.get("instance_guid")
            if not isinstance(guid, str):
                return None, "missing_field"
            if not re.match(INSTANCE_GUID_REGEX, guid):
                return None, "invalid_uuid"
            return guid, None
        except FileNotFoundError:
            last_err = "absent"
            if attempt < RUNTIME_STATE_ENOENT_RETRIES - 1:
                time.sleep(RUNTIME_STATE_ENOENT_BACKOFF_MS / 1000.0)
        except (json.JSONDecodeError, OSError):
            return None, "corrupt"
    return None, last_err


def _read_legacy_guid(path: str) -> str | None:
    """Read the legacy /data/instance_guid file. Returns the validated UUIDv4
    or None if the file is absent / unreadable / not a valid UUIDv4."""
    try:
        with open(path, "r", encoding="utf-8") as fp:
            raw = fp.read().strip().lower()
    except (FileNotFoundError, OSError):
        return None
    if re.match(INSTANCE_GUID_REGEX, raw):
        return raw
    return None


def _generate_uuid4() -> str:
    """Generate a fresh lowercase UUIDv4 (AD09b case 3)."""
    return str(uuid.uuid4()).lower()


def resolve_instance_guid(
    runtime_state_path: str = RUNTIME_STATE_FILE,
    legacy_path: str = LEGACY_INSTANCE_GUID_FILE,
) -> ResolveResult:
    """AD09b read precedence + AD09a halt detection.

    Returns a ResolveResult. When result.halt is True, the caller MUST also
    write the migration marker file via write_migration_marker() and exit
    with EXIT_MIGRATION_REQUIRED.

    Precedence (AD09b):
      1. runtime_state.json valid + meta.instance_guid valid → use it.
      2. legacy /data/instance_guid present + runtime_state invalid/absent → AD09a halt.
      3. both absent → generate fresh uuid4 + AD25 warn.
      4. mismatch (runtime has GUID-A, legacy has GUID-B) → runtime wins, log warn.
      5. corrupt runtime + valid legacy → AD09a halt.
    """
    rs_guid, rs_err = _read_runtime_state(runtime_state_path)
    legacy_guid = _read_legacy_guid(legacy_path)

    if rs_guid is not None:
        # Case 1 / Case 4 — runtime is valid.
        if legacy_guid is not None and legacy_guid != rs_guid:
            return ResolveResult(
                guid=rs_guid,
                source=IDENTITY_SOURCE_RUNTIME_STATE,
                halt=False,
                log_lines=[
                    "WARN HELIANTHUS_INSTANCE_GUID_MISMATCH "
                    f"runtime={rs_guid} legacy={legacy_guid} runtime wins"
                ],
            )
        return ResolveResult(
            guid=rs_guid,
            source=IDENTITY_SOURCE_RUNTIME_STATE,
            halt=False,
            log_lines=[],
        )

    # rs_guid is None — runtime invalid / absent / corrupt / missing field.
    if legacy_guid is not None:
        # Case 2 / Case 5 — legacy present but runtime unusable → AD09a halt.
        reason = "absent" if rs_err == "absent" else (rs_err or "invalid")
        return ResolveResult(
            guid="",
            source="",
            halt=True,
            log_lines=[
                f"ERROR {LOG_TOKEN_MIGRATION_REQUIRED} "
                f"legacy_guid_detected runtime_state_status={reason}; "
                f"see {MIGRATION_MARKER_FILE} for the migration template, then restart"
            ],
        )

    # Both runtime_state and legacy unavailable. Distinguish "truly absent"
    # (case 3 — fresh install, generate UUIDv4) from "present but unusable"
    # (corrupt / missing required field / invalid UUID) — the latter must
    # halt rather than silently orphan an existing HA pairing whose original
    # GUID was in the now-broken runtime_state file (Codex R2 P2). The
    # operator must investigate the corrupt file before we generate a new
    # identity.
    if rs_err is not None and rs_err != "absent":
        return ResolveResult(
            guid="",
            source="",
            halt=True,
            log_lines=[
                f"ERROR {LOG_TOKEN_MIGRATION_REQUIRED} "
                f"runtime_state_unusable status={rs_err}; "
                "refusing to generate a new instance_guid because the "
                "existing file may carry an HA-paired GUID. Inspect "
                f"{RUNTIME_STATE_FILE} (or its quarantine sibling) to recover "
                "the original GUID, then restart."
            ],
        )

    # Case 3 — both truly absent (fresh install). Generate fresh.
    fresh = _generate_uuid4()
    return ResolveResult(
        guid=fresh,
        source=IDENTITY_SOURCE_GENERATED,
        halt=False,
        log_lines=[
            f"WARN {LOG_TOKEN_FRESH_IDENTITY} "
            f"generated={fresh}; if you have a prior HA integration entry "
            "for Helianthus, re-pair manually"
        ],
    )


def write_migration_marker(
    marker_path: str = MIGRATION_MARKER_FILE,
    template: str = MIGRATION_TEMPLATE,
) -> None:
    """Write the AD09a migration marker file with the complete template.

    Atomic temp+rename within the marker's directory. Idempotent; overwrites
    on each call.
    """
    marker_p = Path(marker_path)
    marker_p.parent.mkdir(parents=True, exist_ok=True)
    tmp = marker_p.with_suffix(marker_p.suffix + ".tmp")
    try:
        with open(tmp, "w", encoding="utf-8") as fp:
            fp.write(template)
            fp.flush()
            try:
                os.fsync(fp.fileno())
            except (OSError, AttributeError):
                pass  # best-effort
        os.replace(tmp, marker_p)
    finally:
        # Successful os.replace consumes the temp file, so the unlink is a
        # no-op in the happy path; we only land here to clean up after a
        # rename failure. FileNotFoundError is therefore the expected case
        # under success, not an error worth reporting.
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass


def persist_bootstrap_runtime_state(
    runtime_state_path: str,
    instance_guid: str,
    written_at: str,
) -> bool:
    """Write a minimal schema-valid runtime_state.json for case-3 bootstrap.

    Codex P2 follow-up on PR #127: a /data/helianthus-gateway override that
    predates M2_GATEWAY_LOADER will not write runtime_state.json itself, so
    a fresh install that hits case 3 (both files absent → generate UUIDv4)
    would re-enter case 3 on every restart and present a different HA
    identity. Persisting from the wrapper bootstraps the file once; the
    pinned (M2-aware) gateway then takes over via eager-persist and adds
    ebus.* sections. Older overrides simply leave the file alone, but
    identity is now stable across restarts because the wrapper itself
    reads its own bootstrap on the next boot.

    This is the ONLY non-gateway writer of runtime_state.json. It writes
    only the fields the schema requires (schema_version, meta) and never
    touches ebus.* — the gateway owns those.

    Atomic temp+rename within the target file's directory. Returns True on
    success, False on any I/O error (caller logs and continues — failing
    closed here would block fresh installs).
    """
    body = (
        json.dumps(
            {
                "schema_version": 1,
                "meta": {
                    "instance_guid": instance_guid,
                    "written_at": written_at,
                },
            },
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )
    target = Path(runtime_state_path)
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix(target.suffix + ".tmp")
        with open(tmp, "w", encoding="utf-8") as fp:
            fp.write(body)
            fp.flush()
            try:
                os.fsync(fp.fileno())
            except (OSError, AttributeError):
                pass  # best-effort fsync
        os.replace(tmp, target)
        return True
    except OSError:
        # Best-effort: the gateway will still receive -instance-guid for
        # this run; identity churn becomes an issue only across restarts,
        # and the operator will see HELIANTHUS_FRESH_IDENTITY each time
        # which is the established case-3 signal.
        try:
            tmp.unlink()
        except (FileNotFoundError, NameError, OSError):
            # Successful replace consumes tmp; unlink fails benignly here.
            pass
        return False


def emit_log_lines(lines: list[str], stream=None) -> None:
    """Write the structured log lines to the Supervisor stdout stream.

    The default stream is sys.stderr (Supervisor captures both stdout and
    stderr; stderr ensures the banner survives stdout-only filters).
    """
    if stream is None:
        stream = sys.stderr
    for line in lines:
        print(line, file=stream)
    try:
        stream.flush()
    except (OSError, AttributeError, ValueError):
        # Best-effort logging flush: closed/broken streams + non-flushable
        # custom streams should not abort the wrapper. The migration-marker
        # and resolved GUID have already been written via the print() calls
        # above; failing here would only hide the resolve outcome from the
        # operator, not corrupt anything.
        pass


def main(argv: list[str] | None = None) -> int:
    """CLI entry point invoked by the bash run script.

    Prints lines to stdout that the bash side `eval`s to set:
      HELIANTHUS_INSTANCE_GUID=<uuid4>
      HELIANTHUS_INSTANCE_GUID_SOURCE=<runtime_state|legacy_migrated|generated|cli-override>

    Side effects:
      - Reads /data/runtime_state.json (with AD26 ENOENT retries).
      - On AD09a halt: writes /data/.helianthus_migration_required marker file,
        emits HELIANTHUS_MIGRATION_REQUIRED log token, exits with code 1.
      - On case (3) fresh generation: emits HELIANTHUS_FRESH_IDENTITY warn
        and bootstrap-persists the generated GUID into runtime_state.json.

    Standalone invocation (no args) is also a CI smoke check: it runs the
    resolver against runtime defaults; if the system has no /data/ dir,
    falls through to "both absent → generate fresh" path.

    The `argv` parameter is accepted for interface compatibility with future
    flags (e.g. --print-eval) and to keep the function unit-testable; it is
    intentionally unused today.
    """
    del argv  # interface-compat placeholder; no flags consumed in M6.

    # Allow override via env for tests + alt deployments.
    runtime_state_path = os.environ.get("HELIANTHUS_RUNTIME_STATE_PATH", RUNTIME_STATE_FILE)
    legacy_path = os.environ.get("HELIANTHUS_LEGACY_INSTANCE_GUID_PATH", LEGACY_INSTANCE_GUID_FILE)
    marker_path = os.environ.get("HELIANTHUS_MIGRATION_MARKER_PATH", MIGRATION_MARKER_FILE)

    result = resolve_instance_guid(runtime_state_path=runtime_state_path, legacy_path=legacy_path)

    # AD09a halt path: write marker file with complete template + log + exit 1.
    if result.halt:
        try:
            write_migration_marker(marker_path=marker_path)
        except OSError as exc:
            print(
                f"WARN HELIANTHUS_MIGRATION_MARKER_WRITE_FAILED path={marker_path} error={exc}",
                file=sys.stderr,
            )
        emit_log_lines(result.log_lines)
        return EXIT_MIGRATION_REQUIRED

    # Case 3 (fresh generation): persist the bootstrap runtime_state.json
    # before handing identity to the gateway. Without this, an old
    # /data/helianthus-gateway override that predates M2_GATEWAY_LOADER
    # would never write the file, and every restart would generate a
    # different identity (Codex P2 on PR #127). The pinned gateway will
    # overwrite this file with the full schema during eager-persist.
    if result.source == IDENTITY_SOURCE_GENERATED:
        written_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        if not persist_bootstrap_runtime_state(
            runtime_state_path=runtime_state_path,
            instance_guid=result.guid,
            written_at=written_at,
        ):
            print(
                "WARN HELIANTHUS_BOOTSTRAP_PERSIST_FAILED "
                f"path={runtime_state_path}; identity may churn across restarts "
                "if the pinned gateway also fails to write runtime_state.json",
                file=sys.stderr,
            )

    # Case (1/3/4) success — emit log lines (warn on case 3 fresh-id;
    # warn on case 4 mismatch; silent on case 1).
    emit_log_lines(result.log_lines)

    # Print eval-able output for the bash run script.
    print(f"HELIANTHUS_INSTANCE_GUID={result.guid}")
    print(f"HELIANTHUS_INSTANCE_GUID_SOURCE={result.source}")
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
