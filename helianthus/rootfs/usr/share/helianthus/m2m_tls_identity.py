from __future__ import annotations

import ipaddress
import re
import sys


DNS_IDENTITY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.-]{0,252}$")


def is_valid(value: str) -> bool:
    try:
        ipaddress.ip_address(value)
    except ValueError:
        return DNS_IDENTITY.fullmatch(value) is not None
    return True


def main(argv: list[str]) -> int:
    return 0 if len(argv) == 2 and is_valid(argv[1]) else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
