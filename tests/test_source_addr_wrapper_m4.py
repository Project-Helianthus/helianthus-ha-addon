"""M4 source-address wrapper cleanup gates."""

from __future__ import annotations

import importlib.util
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "check_source_addr_wrapper.py"


def _wrapper_module():
    spec = importlib.util.spec_from_file_location("check_source_addr_wrapper", SCRIPT)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_source_addr_auto_does_not_reuse_raw_state_file() -> None:
    module = _wrapper_module()
    argv, logs, state_exists, state_content, _stderr = module._run_wrapper_case(
        source_addr="auto",
        gateway_mode="old",
        existing_state="0xf7\n",
    )

    assert "-source-addr" in argv
    assert argv[argv.index("-source-addr") + 1] == "auto"
    assert "0xf7" not in argv
    assert state_exists
    assert state_content == "0xf7\n"
    assert "gateway default source-selection policy" in logs
    assert "rollback only" in logs


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
    assert "-source-addr" not in argv
    assert state_exists
    assert "rollback only" in logs
