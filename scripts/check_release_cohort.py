#!/usr/bin/env python3
"""Check declared packaging cohorts without resolving release tags or commits."""

from __future__ import annotations

import argparse
import csv
import io
import json
from pathlib import Path
import re
import shlex

import yaml


ROOT = Path(__file__).resolve().parents[1]
VERSION = re.compile(
    r"v?(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)"
    r"(?:-[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?"
    r"(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?"
)


def cohort(value: str) -> tuple[int, int]:
    match = VERSION.fullmatch(value)
    if not match:
        raise ValueError("expected a release version such as 0.7.0 or v0.7.0-rc.1")
    return int(match[1]), int(match[2])


def arg_default(dockerfile: str, name: str) -> str:
    """Require every declaration to agree, including defaults in later stages."""
    # Docker ignores comment/blank lines even within a continued instruction.
    instructions = "\n".join(
        line for line in dockerfile.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    )
    instructions = re.sub(r"\\[ \t]*\n", "", instructions)
    values = []
    for line in instructions.splitlines():
        if not re.match(r"^\s*ARG\s+" + re.escape(name) + r"(?:\s|=|$)", line, re.I):
            continue
        parts = shlex.split(line, comments=True)
        if len(parts) != 2 or not parts[1].startswith(name + "="):
            raise ValueError(f"{name} must have a literal default in every declaration")
        values.append(parts[1].split("=", 1)[1])
    if not values or len(set(values)) != 1 or not values[0]:
        raise ValueError(f"{name} must have one consistent nonempty default")
    return values[0]


def check(config: dict, dockerfile: str, gateway_release: str | None,
          test_image_workflow: dict) -> list[str]:
    version = config.get("version")
    if not isinstance(version, str):
        raise ValueError("add-on config must contain a release version string")
    addon_cohort = cohort(version)
    if addon_cohort != (0, 7):
        return ["NOT_APPLICABLE: add-on is outside 0.7; existing packaging is unchanged"]

    explorer = arg_default(dockerfile, "VRCEXPLORER_VERSION")
    if cohort(explorer) != addon_cohort:
        raise ValueError("Explorer release cohort differs from add-on 0.7")
    for job in test_image_workflow["jobs"].values():
        for step in job.get("steps", []):
            if not step.get("uses", "").startswith("docker/build-push-action@"):
                continue
            # The action reads CSV records with ignoreComma: true: unquote
            # fields, then rejoin each record so commas remain in the argument.
            build_args = step.get("with", {}).get("build-args", "").strip()
            for record in csv.reader(io.StringIO(build_args, newline=""), strict=True):
                name, separator, value = ",".join(record).strip().partition("=")
                if name.strip() == "VRCEXPLORER_VERSION":
                    if not separator or cohort(value.strip()) != addon_cohort:
                        raise ValueError("test-image Explorer override cohort differs from add-on 0.7")
    gateway_pin = arg_default(dockerfile, "EBUSGATEWAY_VERSION")
    try:
        pin_cohort = cohort(gateway_pin)
    except ValueError:
        pin_cohort = None
    if pin_cohort is not None and pin_cohort != addon_cohort:
        raise ValueError("gateway release pin cohort differs from add-on 0.7")
    if gateway_release is None:
        if pin_cohort is None:
            return [
                "CONSISTENT: add-on and Explorer declare the 0.7 cohort",
                "UNVERIFIED: gateway release metadata unavailable; an opaque pin does not establish a release cohort",
            ]
        gateway_release = gateway_pin
    if cohort(gateway_release) != addon_cohort:
        raise ValueError("declared gateway release cohort differs from add-on 0.7")
    return ["CONSISTENT: declared add-on, Explorer and gateway release cohorts are 0.7"]


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        epilog=(
            "Examples: python3 scripts/check_release_cohort.py; "
            "python3 scripts/check_release_cohort.py --addon-config path/config.json "
            "--dockerfile path/Dockerfile --gateway-release-version v0.7.0. "
            "Only 0.7 add-ons are enforced. Exit 0 means no declared cohort conflict "
            "(gateway metadata may remain UNVERIFIED); exit 1 means invalid or conflicting metadata. "
            "A supplied gateway release is a declaration, not proof that the pin belongs to it. "
            "This offline check establishes neither exact-BOM provenance, Pi success, "
            "hardware qualification nor release readiness. It never changes packaging."
        ),
    )
    parser.add_argument("--addon-config", type=Path, default=ROOT / "helianthus/config.json")
    parser.add_argument("--dockerfile", type=Path, default=ROOT / "helianthus/Dockerfile")
    parser.add_argument("--test-image-workflow", type=Path, default=ROOT / ".github/workflows/test-image.yml")
    parser.add_argument("--gateway-release-version", help="optional declared gateway release; never inferred from an opaque commit")
    args = parser.parse_args()
    try:
        config = json.loads(args.addon_config.read_text(encoding="utf-8"))
        if not isinstance(config, dict):
            raise ValueError("add-on config must be a JSON object")
        workflow = yaml.safe_load(args.test_image_workflow.read_text(encoding="utf-8"))
        messages = check(config, args.dockerfile.read_text(encoding="utf-8"),
                         args.gateway_release_version, workflow)
    except (OSError, ValueError, csv.Error, yaml.YAMLError) as exc:
        print(f"FAIL: {exc}")
        return 1
    print("\n".join(messages))
    print("Cohort consistency only; exact-BOM provenance, Pi success and release readiness remain unverified.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
