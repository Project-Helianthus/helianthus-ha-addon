#!/usr/bin/env python3
"""Plan the tags of an opt-in add-on test image.

A test image is built by `.github/workflows/test-image.yml` (workflow_dispatch
only) at an explicit gateway commit. It is published only under
`test-<label>-<short sha>` (per-architecture sources: `...-<arch>-r<run id>`, used only to assemble that run's manifest) and never under
`latest` or a version tag. `helianthus/config.json` is never read for the tag.
With `--include-matter true` the image builds the gateway's default profile,
which includes Matter, and every tag starts with `test-matter-` instead; only
such an image may carry that prefix.

  plan   print `key=value` lines (GITHUB_OUTPUT format) for the given inputs.
"""

from __future__ import annotations

import argparse
import re
import sys

SHA_RE = re.compile(r"[0-9a-f]{40}")
LABEL_RE = re.compile(r"[a-z0-9][a-z0-9-]{0,30}")
SHORT_LEN = 8
# Architectures the add-on declares in config.json; the test image builds only these.
ARCHES = ("amd64", "aarch64")
FORBIDDEN_TAGS = {"latest"}
TEST_TAG_PREFIX = "test-"
MATTER_TAG_PREFIX = "test-matter-"
SEMVER_TAG_RE = re.compile(r"^v?\d+\.\d+\.\d+")


RUN_ID_RE = re.compile(r"[0-9]{1,20}")


def check_tags(tags: list[str], include_matter: bool) -> None:
    """Refuse a tag that is not a test tag of the requested gateway profile."""
    for candidate in tags:
        if candidate in FORBIDDEN_TAGS or SEMVER_TAG_RE.match(candidate) or not candidate.startswith(TEST_TAG_PREFIX):
            raise ValueError(f"refusing non-test tag {candidate}")
        if include_matter and not candidate.startswith(MATTER_TAG_PREFIX):
            raise ValueError(f"refusing Matter test image tag {candidate}: it must start with {MATTER_TAG_PREFIX}")
        if not include_matter and candidate.startswith(MATTER_TAG_PREFIX):
            raise ValueError(f"refusing tag {candidate}: {MATTER_TAG_PREFIX} marks only an image that includes Matter")


def plan(gateway_sha: str, label: str, run_id: str, include_matter: bool = False) -> dict[str, object]:
    if not SHA_RE.fullmatch(gateway_sha):
        raise ValueError("gateway_sha must be a 40-character lowercase hex commit")
    if not LABEL_RE.fullmatch(label):
        raise ValueError("test_label must match [a-z0-9][a-z0-9-]{0,30}")
    if not RUN_ID_RE.fullmatch(run_id):
        raise ValueError("run_id must be decimal digits")
    short = gateway_sha[:SHORT_LEN]
    prefix = MATTER_TAG_PREFIX if include_matter else TEST_TAG_PREFIX
    tag = f"{prefix}{label}-{short}"
    # Per-architecture images are pushed under run-specific tags only, and the
    # manifest is built from exactly those, so one run can never combine its images
    # with another run's (a rerun of a failed job keeps the same run id and commit).
    arch_tags = [f"{tag}-{arch}-r{run_id}" for arch in ARCHES]
    check_tags([tag, *arch_tags], include_matter)
    return {
        "tag": tag,
        "short": short,
        "arch_tags": arch_tags,
        "manifest_tags": [tag],
        "manifest_sources": arch_tags,
        "build_version": tag,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("plan")
    p.add_argument("--gateway-sha", required=True)
    p.add_argument("--test-label", default="second-site")
    p.add_argument("--run-id", required=True)
    p.add_argument("--include-matter", choices=("true", "false"), default="false")
    args = parser.parse_args()
    try:
        result = plan(args.gateway_sha, args.test_label, args.run_id, args.include_matter == "true")
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
