#!/usr/bin/env python3
"""Plan the tags of an opt-in add-on test image.

A test image is built by `.github/workflows/test-image.yml` (workflow_dispatch
only) at an explicit gateway commit. It is published only under
`test-<label>-<short sha>` (per architecture: `...-<arch>`) and never under
`latest` or a version tag. `helianthus/config.json` is never read for the tag.

  plan   print `key=value` lines (GITHUB_OUTPUT format) for the given inputs.
"""

from __future__ import annotations

import argparse
import re
import sys

SHA_RE = re.compile(r"^[0-9a-f]{40}$")
LABEL_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,30}$")
SHORT_LEN = 8
# Architectures the add-on declares in config.json; the test image builds only these.
ARCHES = ("amd64", "aarch64")
FORBIDDEN_TAGS = {"latest"}
SEMVER_TAG_RE = re.compile(r"^v?\d+\.\d+\.\d+")


def plan(gateway_sha: str, label: str) -> dict[str, object]:
    if not SHA_RE.match(gateway_sha):
        raise ValueError("gateway_sha must be a 40-character lowercase hex commit")
    if not LABEL_RE.match(label):
        raise ValueError("test_label must match [a-z0-9][a-z0-9-]{0,30}")
    short = gateway_sha[:SHORT_LEN]
    tag = f"test-{label}-{short}"
    arch_tags = [f"{tag}-{arch}" for arch in ARCHES]
    for candidate in [tag, *arch_tags]:
        if candidate in FORBIDDEN_TAGS or SEMVER_TAG_RE.match(candidate) or not candidate.startswith("test-"):
            raise ValueError(f"refusing non-test tag {candidate}")
    return {
        "tag": tag,
        "short": short,
        "arch_tags": arch_tags,
        "manifest_tags": [tag],
        "manifest_sources": arch_tags,
        "build_version": f"test-{label}-{short}",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("plan")
    p.add_argument("--gateway-sha", required=True)
    p.add_argument("--test-label", default="second-site")
    args = parser.parse_args()
    try:
        result = plan(args.gateway_sha, args.test_label)
    except ValueError as exc:
        print(f"test image plan: FAIL ({exc})", file=sys.stderr)
        return 1
    print(f"tag={result['tag']}")
    print(f"short={result['short']}")
    print(f"build_version={result['build_version']}")
    print("manifest_sources=" + " ".join(result["manifest_sources"]))  # type: ignore[arg-type]
    return 0


if __name__ == "__main__":
    sys.exit(main())
