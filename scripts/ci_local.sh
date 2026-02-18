#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

echo "==> validate JSON syntax"
found=0
while IFS= read -r file; do
  [ -z "${file}" ] && continue
  found=1
  python3 -m json.tool "${file}" >/dev/null
  echo "OK: ${file}"
done < <(git ls-files '*.json')
if [ "${found}" -eq 0 ]; then
  echo "No JSON files found."
fi

echo "==> validate shell syntax"
found=0
while IFS= read -r file; do
  [ -z "${file}" ] && continue
  found=1
  bash -n "${file}"
  echo "OK: ${file}"
done < <(git ls-files '*.sh')
if [ "${found}" -eq 0 ]; then
  echo "No shell files found."
fi

echo "==> terminology gate"
if git grep -nIwiE 'm[a]ster|s[l]ave'; then
  echo "Found legacy terminology in tracked files."
  exit 1
fi

echo "==> validate smoke runbook structure"
python3 scripts/validate_smoke_docs.py

echo "==> private IPv4 address gate (docs must use placeholders)"
python3 - <<'PY'
from __future__ import annotations

import ipaddress
import pathlib
import re
import subprocess
import sys

md_files = subprocess.check_output(["git", "ls-files", "*.md"], text=True).splitlines()
ipv4_re = re.compile(r"\\b(?:(?:\\d{1,3})\\.){3}(?:\\d{1,3})\\b")

def is_private(ip: str) -> bool:
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return addr.version == 4 and (addr.is_private or addr.is_link_local)

failed = False

for file_path in md_files:
    text = pathlib.Path(file_path).read_text(encoding="utf-8")
    for match in ipv4_re.finditer(text):
        ip = match.group(0)
        if not is_private(ip):
            continue
        line = text.count("\n", 0, match.start()) + 1
        print(f"{file_path}:{line}: private IPv4 address found (use a placeholder)", file=sys.stderr)
        failed = True

if failed:
    sys.exit(1)
print("Private IPv4 gate passed.")
PY

