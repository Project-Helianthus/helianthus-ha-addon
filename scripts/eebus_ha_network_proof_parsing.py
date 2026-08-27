"""Parse eeBUS HA network-proof validator command input."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any
def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate a redacted MSP-03C eebus-transport-gate-v0 artifact",
    )
    parser.add_argument(
        "--artifact",
        default="scripts/fixtures/eebus_ha_network_proof_contract_pass.json",
        help="Path to the proof artifact JSON",
    )
    parser.add_argument(
        "--mode",
        choices=("contract", "lab"),
        default="contract",
        help="contract validates the public fixture shape; lab also requires lab_run mode",
    )
    parser.add_argument(
        "--self-test",
        action="store_true",
        help="Run validator regression tests against known-bad mutations",
    )
    return parser.parse_args()


def load_artifact(path: str) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("artifact root must be a JSON object")
    return payload
