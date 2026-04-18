#!/usr/bin/env python3
"""Validate smoke runbook structure and config/checklist syntax."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import re
import sys

RUNBOOK_PATH = Path("SMOKE_RUNBOOK.md")
SMOKE_CHECKLIST_PATH = Path(__file__).with_name("smoke_addon_checklist.py")

REQUIRED_HEADINGS = [
    "## Local ebusd-tcp topology",
    "## Embedded adaptermux proxy topology",
    "## Install and start add-on",
    "## Add-on configuration (copy/paste)",
    "## Deterministic smoke checklist",
    "## Failure triage",
]

REQUIRED_CONFIG_KEYS = [
    "transport",
    "network",
    "address",
    "proxy_profile",
    "proxy_endpoint",
    "host",
    "http_port",
    "graphql_path",
    "subscription_path",
    "mcp_path",
    "mdns",
]

REQUIRED_CHECKS = [
    "CHECK_CONNECTION_GRAPHQL",
    "CHECK_CONNECTION_MCP",
    "CHECK_LOG_STARTUP",
    "CHECK_LOG_TRANSPORT",
    "CHECK_LOG_PROXY_PROFILE",
    "CHECK_LOG_PROXY_ENDPOINT",
    "CHECK_LOG_GRAPHQL_ENDPOINT",
    "CHECK_LOG_SUBSCRIPTION_ENDPOINT",
    "CHECK_LOG_MCP_ENDPOINT",
]


def _load_smoke_checklist_module():
    module_name = "smoke_addon_checklist_runtime"
    spec = importlib.util.spec_from_file_location(module_name, SMOKE_CHECKLIST_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"failed to load {SMOKE_CHECKLIST_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def _extract_marker_block(text: str, marker: str) -> str:
    pattern = re.compile(
        rf"<!--\s*{re.escape(marker)}:start\s*-->\s*```[a-zA-Z0-9_-]*\s*(.*?)```[\r\n]+<!--\s*{re.escape(marker)}:end\s*-->",
        re.DOTALL,
    )
    match = pattern.search(text)
    if not match:
        raise ValueError(f"missing marker block for {marker}")
    return match.group(1).strip()


def main() -> int:
    if not RUNBOOK_PATH.exists():
        print(f"missing {RUNBOOK_PATH}")
        return 1

    text = RUNBOOK_PATH.read_text(encoding="utf-8")

    for heading in REQUIRED_HEADINGS:
        if heading not in text:
            print(f"missing heading: {heading}")
            return 1

    try:
        config_block = _extract_marker_block(text, "smoke-config-json")
        config_payload = json.loads(config_block)
    except (ValueError, json.JSONDecodeError) as exc:
        print(f"invalid smoke config block: {exc}")
        return 1

    if not isinstance(config_payload, dict):
        print("smoke config block must be a JSON object")
        return 1

    for key in REQUIRED_CONFIG_KEYS:
        if key not in config_payload:
            print(f"smoke config missing key: {key}")
            return 1

    if config_payload.get("transport") != "ebusd-tcp":
        print("smoke config transport must be ebusd-tcp")
        return 1
    if config_payload.get("network") != "tcp":
        print("smoke config network must be tcp")
        return 1
    if config_payload.get("proxy_profile") != "disabled":
        print("smoke config proxy_profile must be disabled")
        return 1

    checklist_section = _extract_marker_block(text, "smoke-checklist")
    lines = [line.strip() for line in checklist_section.splitlines() if line.strip()]
    check_ids = []
    for line in lines:
        prefix = "- [ ] "
        if not line.startswith(prefix):
            print(f"invalid checklist line format: {line}")
            return 1
        check_id = line[len(prefix) :].split(" ", 1)[0].strip()
        check_ids.append(check_id)

    if check_ids != REQUIRED_CHECKS:
        print(f"checklist ids mismatch: {check_ids}")
        return 1

    triage_rows = {
        match.group(1)
        for match in re.finditer(r"^\|\s*(CHECK_[A-Z_]+)\s*\|", text, flags=re.MULTILINE)
    }
    for check in REQUIRED_CHECKS:
        if check not in triage_rows:
            print(f"missing triage row for {check}")
            return 1

    smoke_addon_checklist = _load_smoke_checklist_module()

    derived_subscription = smoke_addon_checklist._derive_subscription_path(
        "/api/graphql",
        "/graphql/subscriptions",
    )
    if derived_subscription != "/api/graphql/subscriptions":
        print(
            "subscription marker derivation mismatch for customized graphql_path: "
            f"{derived_subscription}",
        )
        return 1

    explicit_subscription = smoke_addon_checklist._derive_subscription_path(
        "/api/graphql",
        "/custom/subscriptions",
    )
    if explicit_subscription != "/custom/subscriptions":
        print(
            "subscription marker derivation mismatch for explicit subscription_path: "
            f"{explicit_subscription}",
        )
        return 1

    normalized_proxy_endpoint = smoke_addon_checklist._derive_proxy_endpoint_marker(
        "enh",
        "127.0.0.1:19001",
    )
    if normalized_proxy_endpoint != "enh://127.0.0.1:19001":
        print(
            "proxy endpoint marker derivation mismatch for host:port endpoint: "
            f"{normalized_proxy_endpoint}",
        )
        return 1

    disabled_proxy_endpoint = smoke_addon_checklist._derive_proxy_endpoint_marker(
        "disabled",
        "",
    )
    if disabled_proxy_endpoint != "(none)":
        print(
            "proxy endpoint marker derivation mismatch for disabled profile: "
            f"{disabled_proxy_endpoint}",
        )
        return 1

    print("Smoke runbook validation passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
