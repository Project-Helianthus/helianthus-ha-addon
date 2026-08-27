#!/usr/bin/env python3
"""Validate MSP-03C eeBUS HA runtime networking proof artifacts."""

from __future__ import annotations

import sys

from eebus_ha_network_proof_checks import run_self_tests, validate_artifact
from eebus_ha_network_proof_parsing import load_artifact, parse_args
from eebus_ha_network_proof_reporting import report_load_failure, report_validation


def main() -> int:
    args = parse_args()
    if args.self_test:
        return run_self_tests()

    try:
        payload = load_artifact(args.artifact)
    except (FileNotFoundError, ValueError) as exc:
        return report_load_failure(exc)

    return report_validation(validate_artifact(payload, mode=args.mode), args.mode)


if __name__ == "__main__":
    sys.exit(main())
