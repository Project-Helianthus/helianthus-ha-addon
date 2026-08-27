from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CHECKER = ROOT / "scripts" / "check_eebus_ha_network_proof.py"
FIXTURE = ROOT / "scripts" / "fixtures" / "eebus_ha_network_proof_contract_pass.json"


def run_checker(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(CHECKER), *args],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def test_cli_keeps_representative_output_and_exit_codes(tmp_path: Path) -> None:
    valid = run_checker("--artifact", str(FIXTURE), "--mode", "contract")
    assert valid.returncode == 0
    assert valid.stdout == "eeBUS HA network proof: PASS (contract)\n"
    assert valid.stderr == ""

    invalid_payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    invalid_payload["contract"] = "unexpected"
    invalid_path = tmp_path / "invalid.json"
    invalid_path.write_text(json.dumps(invalid_payload), encoding="utf-8")
    invalid = run_checker("--artifact", str(invalid_path), "--mode", "contract")
    assert invalid.returncode == 1
    assert invalid.stdout == (
        "eeBUS HA network proof: FAIL (contract mismatch: got='unexpected' "
        "expected=helianthus.eebus.ha-network-proof.v0)\n"
    )
    assert invalid.stderr == ""

    missing_path = tmp_path / "missing.json"
    missing = run_checker("--artifact", str(missing_path), "--mode", "contract")
    assert missing.returncode == 1
    assert missing.stdout == (
        f"eeBUS HA network proof: FAIL ([Errno 2] No such file or directory: '{missing_path}')\n"
    )
    assert missing.stderr == ""


def test_cli_keeps_self_test_output_and_exit_code() -> None:
    result = run_checker("--self-test")
    assert result.returncode == 0
    assert result.stdout == "eeBUS HA network proof self-test: PASS\n"
    assert result.stderr == ""
