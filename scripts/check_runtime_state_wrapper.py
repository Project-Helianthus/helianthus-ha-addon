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

import sys
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


def resolve_instance_guid(
    runtime_state_path: str = RUNTIME_STATE_FILE,
    legacy_path: str = LEGACY_INSTANCE_GUID_FILE,
) -> ResolveResult:
    """AD09b read precedence + AD09a halt detection.

    Returns a ResolveResult. When result.halt is True, the caller MUST also
    write the migration marker file via write_migration_marker() and exit
    with EXIT_MIGRATION_REQUIRED.

    M1_TDD_RED: raises NotImplementedError. M6_HA_ADDON_MIGRATION provides the
    real body.
    """
    raise NotImplementedError("runtime-state wrapper: M6_HA_ADDON_MIGRATION will provide")


def write_migration_marker(
    marker_path: str = MIGRATION_MARKER_FILE,
    template: str = MIGRATION_TEMPLATE,
) -> None:
    """Write the AD09a migration marker file with the complete template.

    Atomic temp+rename within /data/. Idempotent; overwrites on each call.

    M1_TDD_RED: raises NotImplementedError.
    """
    raise NotImplementedError("runtime-state wrapper: M6_HA_ADDON_MIGRATION will provide")


def emit_log_lines(lines: list[str], stream=None) -> None:
    """Write the structured log lines to the Supervisor stdout stream.

    The default stream is sys.stderr (Supervisor captures both stdout and
    stderr; stderr ensures the banner survives stdout-only filters).
    """
    raise NotImplementedError("runtime-state wrapper: M6_HA_ADDON_MIGRATION will provide")


def main(argv: list[str] | None = None) -> int:
    """CLI entry point.

    During M1, this prints a skip message and exits 0 so pr-ci.yml's "Validate
    runtime-state wrapper migration" step can pass. During M6, this becomes
    the real entrypoint that the bash run script invokes via `eval`.
    """
    if argv is None:
        argv = sys.argv[1:]

    # M1_TDD_RED: skip cleanly so CI passes.
    print(
        "check_runtime_state_wrapper: M1_TDD_RED skeleton; M6_HA_ADDON_MIGRATION "
        "will replace this with the real wrapper. No-op for M1.",
        file=sys.stderr,
    )
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
