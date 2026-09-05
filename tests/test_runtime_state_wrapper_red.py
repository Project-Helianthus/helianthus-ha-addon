"""M1_TDD_RED tests for the runtime-state wrapper.

These tests reference the contract that M6_HA_ADDON_MIGRATION must satisfy.
They are RED in M1: every public function in
scripts/check_runtime_state_wrapper.py raises NotImplementedError, so each
test fails when run via pytest.

CI does NOT invoke pytest (see .github/workflows/pr-ci.yml — only the
script's __main__ is invoked, which exits 0 with a skip message during M1).
The tests are committed as the executable design contract per
cruise-tdd-gate; M6_HA_ADDON_MIGRATION removes the NotImplementedError
stubs and these tests turn GREEN.

Run locally with:

    python3 -m pytest tests/test_runtime_state_wrapper_red.py -v

Plan: runtime-state-w19-26.locked. ADs referenced inline per case.
"""

from __future__ import annotations

import importlib.util
import builtins
import io
import json
import os
import re
import sys
import tempfile
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "check_runtime_state_wrapper.py"


def _wrapper_module():
    """Import scripts/check_runtime_state_wrapper.py as a module."""
    spec = importlib.util.spec_from_file_location(
        "check_runtime_state_wrapper", SCRIPT
    )
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


VALID_GUID_A = "8a3f2b9e-4d7c-4f1a-9b5e-2c1f3e7a9d5b"
VALID_GUID_B = "1234abcd-1234-4abc-9def-987654321abc"


def _write_runtime_state(path: Path, *, guid: str | None = VALID_GUID_A,
                         schema_version: int = 1) -> None:
    """Write a minimum-valid runtime_state.json fixture."""
    body: dict = {
        "schema_version": schema_version,
        "meta": {
            "written_at": "2026-05-10T19:42:11Z",
        },
    }
    if guid is not None:
        body["meta"]["instance_guid"] = guid
    path.write_text(json.dumps(body, indent=2))


# -----------------------------------------------------------------------------
# AD09b read precedence — 5 cases.
# -----------------------------------------------------------------------------


def test_ad09b_case1_runtime_state_valid_uses_it(tmp_path: Path) -> None:
    """Case 1: runtime_state valid + meta.instance_guid valid → use it."""
    module = _wrapper_module()
    rs_path = tmp_path / "runtime_state.json"
    legacy_path = tmp_path / "instance_guid"
    _write_runtime_state(rs_path, guid=VALID_GUID_A)

    result = module.resolve_instance_guid(
        runtime_state_path=str(rs_path), legacy_path=str(legacy_path)
    )
    assert result.guid == VALID_GUID_A
    assert result.source == module.IDENTITY_SOURCE_RUNTIME_STATE
    assert result.halt is False


def test_ad09b_case2_legacy_only_triggers_ad09a_halt(tmp_path: Path) -> None:
    """Case 2: legacy present + runtime_state absent → AD09a halt."""
    module = _wrapper_module()
    rs_path = tmp_path / "runtime_state.json"  # absent
    legacy_path = tmp_path / "instance_guid"
    legacy_path.write_text(VALID_GUID_A + "\n")

    result = module.resolve_instance_guid(
        runtime_state_path=str(rs_path), legacy_path=str(legacy_path)
    )
    assert result.halt is True, "AD09a halt MUST trip when legacy present + runtime_state absent"
    assert any(
        module.LOG_TOKEN_MIGRATION_REQUIRED in line for line in result.log_lines
    ), "AD09a halt must include HELIANTHUS_MIGRATION_REQUIRED log token"


def test_ad09b_case3_both_absent_generates_fresh(tmp_path: Path) -> None:
    """Case 3: both files absent → generate fresh uuid4 + AD25 warn token."""
    module = _wrapper_module()
    rs_path = tmp_path / "runtime_state.json"  # absent
    legacy_path = tmp_path / "instance_guid"  # absent

    result = module.resolve_instance_guid(
        runtime_state_path=str(rs_path), legacy_path=str(legacy_path)
    )
    assert result.halt is False
    assert result.source == module.IDENTITY_SOURCE_GENERATED
    assert re.match(module.INSTANCE_GUID_REGEX, result.guid), (
        f"generated GUID {result.guid!r} must match AD22 regex"
    )
    assert any(
        module.LOG_TOKEN_FRESH_IDENTITY in line for line in result.log_lines
    ), "AD25 fresh-identity token must be emitted"


def test_ad09b_case4_mismatch_runtime_wins(tmp_path: Path) -> None:
    """Case 4: runtime has GUID-A, legacy has GUID-B → runtime wins, log warning."""
    module = _wrapper_module()
    rs_path = tmp_path / "runtime_state.json"
    legacy_path = tmp_path / "instance_guid"
    _write_runtime_state(rs_path, guid=VALID_GUID_A)
    legacy_path.write_text(VALID_GUID_B + "\n")

    result = module.resolve_instance_guid(
        runtime_state_path=str(rs_path), legacy_path=str(legacy_path)
    )
    assert result.halt is False
    assert result.guid == VALID_GUID_A, (
        f"AD09b case 4: runtime_state must win on mismatch, got {result.guid!r}"
    )
    assert result.source == module.IDENTITY_SOURCE_RUNTIME_STATE
    # A mismatch warning is expected (operator decision: runtime authority,
    # legacy is audit artifact).
    assert any("mismatch" in line.lower() for line in result.log_lines), (
        "mismatch must produce a warning log line"
    )


def test_ad09b_case5_corrupt_runtime_with_valid_legacy_triggers_halt(
    tmp_path: Path,
) -> None:
    """Case 5: corrupt runtime + valid legacy → AD09a halt (no silent fallback)."""
    module = _wrapper_module()
    rs_path = tmp_path / "runtime_state.json"
    legacy_path = tmp_path / "instance_guid"
    rs_path.write_text("{not valid json")
    legacy_path.write_text(VALID_GUID_A + "\n")

    result = module.resolve_instance_guid(
        runtime_state_path=str(rs_path), legacy_path=str(legacy_path)
    )
    assert result.halt is True, (
        "AD09a halt MUST trip when runtime_state is corrupt + legacy valid (no silent fallback to legacy)"
    )
    assert any(
        module.LOG_TOKEN_MIGRATION_REQUIRED in line for line in result.log_lines
    )


@pytest.mark.parametrize(
    "legacy_body",
    [
        "12345678-1234-4234-9234",  # truncated
        "not-a-uuid-at-all\n",
        "ffffffff-ffff-ffff-ffff-ffffffffffff\n",  # not v4 (third group must start with 4)
        "",  # empty file (zero-byte write)
        "  \n\n",  # whitespace only
    ],
    ids=["truncated", "garbage", "non_v4", "empty", "whitespace"],
)
def test_ad09b_invalid_legacy_file_triggers_halt(
    tmp_path: Path, legacy_body: str
) -> None:
    """Codex P2 (PR #127): a legacy /data/instance_guid that is PRESENT but
    not a valid UUIDv4 (truncated write, partial write, garbage) MUST trip
    AD09a halt — falling through to fresh-id generation here would silently
    orphan an existing HA pairing whose original GUID was the one being
    truncated. Distinguish absent (legitimate fresh install → case 3)
    from present-but-invalid (operator must migrate → case 2 halt)."""
    module = _wrapper_module()
    rs_path = tmp_path / "runtime_state.json"  # absent
    legacy_path = tmp_path / "instance_guid"
    legacy_path.write_text(legacy_body)

    result = module.resolve_instance_guid(
        runtime_state_path=str(rs_path), legacy_path=str(legacy_path)
    )
    assert result.halt is True, (
        f"present-but-invalid legacy ({legacy_body!r}) must trip AD09a halt, "
        "not silently fall through to case 3 fresh-id generation"
    )
    assert result.source != module.IDENTITY_SOURCE_GENERATED, (
        "halt path must not return a freshly-generated identity"
    )
    assert any(
        module.LOG_TOKEN_MIGRATION_REQUIRED in line for line in result.log_lines
    )
    # The halt log must surface that the legacy file was the trigger.
    assert any("legacy_guid_detected" in line for line in result.log_lines), (
        "halt log must name the legacy file as the trigger"
    )


@pytest.mark.parametrize(
    "json_body",
    ["[]", "null", '"raw-string"', "42"],
    ids=["array", "null", "string", "number"],
)
def test_ad09b_non_object_runtime_state_is_corrupt(
    tmp_path: Path, json_body: str
) -> None:
    """Codex P2 (PR #127): valid JSON that is not a top-level object must be
    treated as corrupt — previously `data.get("meta")` raised AttributeError
    on `[]` / `null`, killing the wrapper before it could write the migration
    marker. With a valid legacy file present we expect AD09a halt; without
    a legacy file we expect the AD09b "runtime_state_unusable" halt path
    (Codex R2 P2) — never a silent fall-through to fresh UUID generation."""
    module = _wrapper_module()
    rs_path = tmp_path / "runtime_state.json"
    legacy_path = tmp_path / "instance_guid"
    rs_path.write_text(json_body)
    # Case 5b: legacy present → AD09a halt with marker.
    legacy_path.write_text(VALID_GUID_A + "\n")
    result = module.resolve_instance_guid(
        runtime_state_path=str(rs_path), legacy_path=str(legacy_path)
    )
    assert result.halt is True, (
        f"non-object top-level JSON ({json_body!r}) must trip AD09a halt, "
        "not raise an unhandled exception"
    )
    # Case 5c: legacy absent → AD09b runtime_state_unusable halt (no fresh ID).
    legacy_path.unlink()
    result = module.resolve_instance_guid(
        runtime_state_path=str(rs_path), legacy_path=str(legacy_path)
    )
    assert result.halt is True, (
        f"non-object top-level JSON ({json_body!r}) without legacy must still "
        "halt rather than orphan a paired GUID with a freshly-generated one"
    )
    assert result.source != module.IDENTITY_SOURCE_GENERATED, (
        "non-object top-level JSON must not silently fall through to "
        "generated identity"
    )


# -----------------------------------------------------------------------------
# AD09a halt details — marker file content + exit code.
# -----------------------------------------------------------------------------


def test_ad09a_marker_file_contains_complete_template(tmp_path: Path) -> None:
    """AD09a marker file must contain a schema-valid v1 template."""
    module = _wrapper_module()
    marker = tmp_path / "marker"
    module.write_migration_marker(marker_path=str(marker))

    body = marker.read_text()
    parsed = json.loads(body)
    assert parsed["schema_version"] == 1
    assert "meta" in parsed
    assert "instance_guid" in parsed["meta"]
    assert "written_at" in parsed["meta"]
    # written_at should be the epoch sentinel — operator only fills in the GUID.
    assert parsed["meta"]["written_at"] == "1970-01-01T00:00:00Z"


def test_ad09a_exit_code_is_one_not_seventy_eight() -> None:
    """AD09a exit code MUST be 1 per consultant MF-1 (not sysexits-78)."""
    module = _wrapper_module()
    assert module.EXIT_MIGRATION_REQUIRED == 1, (
        "AD09a exit code must be 1, never sysexits-78 (collides with Docker conventions)"
    )


# -----------------------------------------------------------------------------
# AD27 -instance-guid-source flag — sources match precedence path.
# -----------------------------------------------------------------------------


def test_ad27_source_runtime_state(tmp_path: Path) -> None:
    """Case 1 path → source=runtime_state."""
    module = _wrapper_module()
    rs_path = tmp_path / "runtime_state.json"
    _write_runtime_state(rs_path, guid=VALID_GUID_A)
    result = module.resolve_instance_guid(
        runtime_state_path=str(rs_path), legacy_path=str(tmp_path / "absent")
    )
    assert result.source == "runtime_state"


def test_ad27_source_generated(tmp_path: Path) -> None:
    """Case 3 path → source=generated."""
    module = _wrapper_module()
    result = module.resolve_instance_guid(
        runtime_state_path=str(tmp_path / "absent_a"),
        legacy_path=str(tmp_path / "absent_b"),
    )
    assert result.source == "generated"


# -----------------------------------------------------------------------------
# AD26 bounded ENOENT retry — transient absence tolerated.
# -----------------------------------------------------------------------------


def test_ad26_enoent_retry_budget(tmp_path: Path) -> None:
    """ENOENT on runtime_state.json open is retried up to RUNTIME_STATE_ENOENT_RETRIES times."""
    module = _wrapper_module()
    assert module.RUNTIME_STATE_ENOENT_RETRIES == 3
    assert module.RUNTIME_STATE_ENOENT_BACKOFF_MS == 100


# -----------------------------------------------------------------------------
# Sole-writer boundary: the wrapper only reads runtime_state.json.
# -----------------------------------------------------------------------------


def test_case3_passes_one_generated_guid_without_runtime_state_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Fresh startup leaves durable runtime-state ownership to the gateway."""
    module = _wrapper_module()
    rs_path = tmp_path / "runtime_state.json"
    legacy_path = tmp_path / "instance_guid"
    marker_path = tmp_path / "marker"
    monkeypatch.setenv("HELIANTHUS_RUNTIME_STATE_PATH", str(rs_path))
    monkeypatch.setenv("HELIANTHUS_LEGACY_INSTANCE_GUID_PATH", str(legacy_path))
    monkeypatch.setenv("HELIANTHUS_MIGRATION_MARKER_PATH", str(marker_path))
    original_open = builtins.open
    runtime_modes: list[str] = []

    def spy_open(file, mode="r", *args, **kwargs):
        if str(file).startswith(str(rs_path)):
            runtime_modes.append(mode)
        return original_open(file, mode, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", spy_open)
    rc = module.main([])
    assert rc == module.EXIT_OK
    output = capsys.readouterr().out.splitlines()
    emitted = [line.split("=", 1)[1] for line in output if line.startswith("HELIANTHUS_INSTANCE_GUID=")]
    assert len(emitted) == 1 and re.match(module.INSTANCE_GUID_REGEX, emitted[0])
    assert not rs_path.exists(), "the wrapper must not create runtime_state.json"
    assert runtime_modes and all(mode == "r" for mode in runtime_modes)


def test_gateway_persisted_runtime_state_is_reused_without_regeneration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Restart identity is supplied by gateway-persisted state, not fallback state."""
    module = _wrapper_module()
    rs_path = tmp_path / "runtime_state.json"
    legacy_path = tmp_path / "instance_guid"
    marker_path = tmp_path / "marker"
    _write_runtime_state(rs_path, guid=VALID_GUID_A)
    original_body = rs_path.read_text()
    monkeypatch.setenv("HELIANTHUS_RUNTIME_STATE_PATH", str(rs_path))
    monkeypatch.setenv("HELIANTHUS_LEGACY_INSTANCE_GUID_PATH", str(legacy_path))
    monkeypatch.setenv("HELIANTHUS_MIGRATION_MARKER_PATH", str(marker_path))
    rc = module.main([])
    assert rc == module.EXIT_OK
    assert rs_path.read_text() == original_body
    output = capsys.readouterr().out
    assert f"HELIANTHUS_INSTANCE_GUID={VALID_GUID_A}" in output
    assert "HELIANTHUS_INSTANCE_GUID_SOURCE=runtime_state" in output


def test_migration_halt_never_mutates_runtime_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Legacy-only failure may write its marker, never runtime state."""
    module = _wrapper_module()
    rs_path = tmp_path / "runtime_state.json"
    legacy_path = tmp_path / "instance_guid"
    marker_path = tmp_path / "marker"
    legacy_path.write_text(VALID_GUID_A + "\n")
    monkeypatch.setenv("HELIANTHUS_RUNTIME_STATE_PATH", str(rs_path))
    monkeypatch.setenv("HELIANTHUS_LEGACY_INSTANCE_GUID_PATH", str(legacy_path))
    monkeypatch.setenv("HELIANTHUS_MIGRATION_MARKER_PATH", str(marker_path))
    original_open = builtins.open
    runtime_modes: list[str] = []

    def spy_open(file, mode="r", *args, **kwargs):
        if str(file).startswith(str(rs_path)):
            runtime_modes.append(mode)
        return original_open(file, mode, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", spy_open)
    assert module.main([]) == module.EXIT_MIGRATION_REQUIRED
    assert not rs_path.exists()
    assert runtime_modes and all(mode == "r" for mode in runtime_modes)
    assert marker_path.exists(), "the separate migration marker remains required"


# -----------------------------------------------------------------------------
# CLI smoke — main() must accept argv and return an int.
# -----------------------------------------------------------------------------


def test_main_returns_int_zero_during_m1(tmp_path: Path) -> None:
    """main() returns EXIT_OK on a fresh-install case."""
    module = _wrapper_module()
    rs_path = tmp_path / "runtime_state.json"
    legacy_path = tmp_path / "instance_guid"
    marker_path = tmp_path / "marker"
    monkey_env = {
        "HELIANTHUS_RUNTIME_STATE_PATH": str(rs_path),
        "HELIANTHUS_LEGACY_INSTANCE_GUID_PATH": str(legacy_path),
        "HELIANTHUS_MIGRATION_MARKER_PATH": str(marker_path),
    }
    saved = {k: os.environ.get(k) for k in monkey_env}
    os.environ.update(monkey_env)
    try:
        rc = module.main([])
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
    assert rc == module.EXIT_OK
