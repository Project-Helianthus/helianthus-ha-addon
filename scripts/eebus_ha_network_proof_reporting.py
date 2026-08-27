"""Render stable eeBUS HA network-proof validator outcomes."""

from __future__ import annotations


def report_load_failure(error: Exception) -> int:
    print(f"eeBUS HA network proof: FAIL ({error})")
    return 1


def report_validation(errors: list[str], mode: str) -> int:
    if errors:
        print(f"eeBUS HA network proof: FAIL ({'; '.join(errors)})")
        return 1

    print(f"eeBUS HA network proof: PASS ({mode})")
    return 0
