"""M4 source-address wrapper cleanup gates."""

from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "check_source_addr_wrapper.py"
DOCKERFILE = Path(__file__).resolve().parents[1] / "helianthus" / "Dockerfile"
SECRET_VERIFIER = (
    Path(__file__).resolve().parents[1]
    / "helianthus"
    / "build"
    / "verify-no-secret.sh"
)


def _wrapper_module():
    spec = importlib.util.spec_from_file_location("check_source_addr_wrapper", SCRIPT)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_build_credentials_are_process_scoped_and_fail_closed_on_persistence() -> None:
    dockerfile = DOCKERFILE.read_text(encoding="utf-8")

    assert "git config --global" not in dockerfile
    assert dockerfile.count("export GIT_CONFIG_COUNT=1;") == 2
    assert dockerfile.count(
        "url.https://x-access-token:${github_token_value}@github.com/.insteadOf"
    ) == 2
    assert dockerfile.count(
        "COPY build/verify-no-secret.sh /usr/local/bin/verify-no-secret"
    ) == 2
    assert '"${github_token_value}" /root /src /out /tmp /go' in dockerfile
    assert '"${github_token_value}" /root /out /tmp /usr/local' in dockerfile


def test_secret_persistence_verifier_distinguishes_all_scan_outcomes(tmp_path: Path) -> None:
    clean = tmp_path / "clean"
    clean.mkdir()
    (clean / "artifact").write_text("public data", encoding="utf-8")
    marker = tmp_path / "continued"

    no_match = subprocess.run(
        ["sh", str(SECRET_VERIFIER), "sentinel-token", str(clean)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert no_match.returncode == 0

    continued = subprocess.run(
        [
            "sh",
            "-c",
            'sh "$1" sentinel-token "$2" && : >"$3"',
            "sh",
            str(SECRET_VERIFIER),
            str(clean),
            str(marker),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert continued.returncode == 0
    assert marker.exists()

    (clean / "artifact").write_text("contains sentinel-token", encoding="utf-8")
    match = subprocess.run(
        ["sh", str(SECRET_VERIFIER), "sentinel-token", str(clean)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert match.returncode == 1
    assert "persisted" in match.stderr

    scanner_error = subprocess.run(
        ["sh", str(SECRET_VERIFIER), "sentinel-token", str(tmp_path / "missing")],
        capture_output=True,
        text=True,
        check=False,
    )
    assert scanner_error.returncode > 1
    assert "scan failed" in scanner_error.stderr

    empty = subprocess.run(
        ["sh", str(SECRET_VERIFIER), "", str(tmp_path / "missing")],
        capture_output=True,
        text=True,
        check=False,
    )
    assert empty.returncode == 0

    missing_arguments = subprocess.run(
        ["sh", str(SECRET_VERIFIER)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert missing_arguments.returncode == 2


def test_source_addr_auto_does_not_reuse_raw_state_file() -> None:
    module = _wrapper_module()
    argv, logs, state_exists, state_content, _stderr = module._run_wrapper_case(
        source_addr="auto",
        gateway_mode="old",
        existing_state="0xf7\n",
    )

    assert "-source-addr" in argv
    assert argv[argv.index("-source-addr") + 1] == "auto"
    assert "-semantic-cache-path" not in argv
    assert "0xf7" not in argv
    assert state_exists
    assert state_content == "0xf7\n"
    assert "gateway default source-selection policy" in logs
    assert "rollback only" in logs
    assert "does not support -semantic-cache-path" in logs


def test_source_addr_exact_maps_to_explicit_validate_only() -> None:
    module = _wrapper_module()
    argv, logs, state_exists, _state_content, _stderr = module._run_wrapper_case(
        source_addr="0x71",
        gateway_mode="new",
        existing_state="0xf7\n",
    )

    assert "-startup-source-override" in argv
    assert argv[argv.index("-startup-source-override") + 1] == "0x71"
    assert "-startup-source-override-validate=true" in argv
    assert "-semantic-cache-path" in argv
    assert argv[argv.index("-semantic-cache-path") + 1] == "/data/semantic_cache.json"
    assert "-source-addr" not in argv
    assert state_exists
    assert "rollback only" in logs


def test_source_addr_exact_preserved_for_ebusd_tcp() -> None:
    module = _wrapper_module()
    argv, logs, state_exists, state_content, _stderr = module._run_wrapper_case(
        source_addr="0x71",
        gateway_mode="new",
        existing_state="0xf7\n",
        transport="ebusd-tcp",
        adapter_direct_enabled=False,
    )

    assert "-source-addr" in argv
    assert argv[argv.index("-source-addr") + 1] == "0x71"
    assert "-startup-source-override" not in argv
    assert state_exists
    assert state_content == "0xf7\n"
    assert "ebusd-compatible gateway source input" in logs
