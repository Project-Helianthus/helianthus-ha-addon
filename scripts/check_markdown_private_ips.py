#!/usr/bin/env python3
"""Reject private IPv4 addresses in Markdown docs."""

from __future__ import annotations

import ipaddress
from pathlib import Path
import re
import subprocess
import sys

IPV4_RE = re.compile(r"\b(?:(?:\d{1,3})\.){3}(?:\d{1,3})\b")

PRIVATE_NETS = [
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("100.64.0.0/10"),
    ipaddress.ip_network("169.254.0.0/16"),
]


def is_private_ipv4(value: str) -> bool:
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        return False
    return address.version == 4 and any(address in network for network in PRIVATE_NETS)


def validate_markdown_private_ips() -> list[str]:
    errors: list[str] = []
    md_files = subprocess.check_output(["git", "ls-files", "*.md"], text=True).splitlines()
    for file_path in md_files:
        text = Path(file_path).read_text(encoding="utf-8")
        for match in IPV4_RE.finditer(text):
            address = match.group(0)
            if not is_private_ipv4(address):
                continue
            line = text.count("\n", 0, match.start()) + 1
            errors.append(f"{file_path}:{line}: private IPv4 address found (use a placeholder)")
    return errors


def run_self_test() -> int:
    if not IPV4_RE.search("192.168.1.1"):
        print("self-test failed: IPv4 regex did not match private address")
        return 1
    if not is_private_ipv4("192.168.1.1"):
        print("self-test failed: private IPv4 not detected")
        return 1
    if not is_private_ipv4("100.64.1.1"):
        print("self-test failed: CGNAT IPv4 not detected")
        return 1
    if is_private_ipv4("203.0.113.10"):
        print("self-test failed: documentation IPv4 placeholder rejected")
        return 1
    print("Private IPv4 gate self-test passed.")
    return 0


def main() -> int:
    if len(sys.argv) > 1 and sys.argv[1] == "--self-test":
        return run_self_test()
    errors = validate_markdown_private_ips()
    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        return 1
    print("Private IPv4 gate passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
