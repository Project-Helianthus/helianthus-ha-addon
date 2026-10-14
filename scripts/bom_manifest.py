#!/usr/bin/env python3
"""Generate or check the Helianthus add-on BOM manifest.

The BOM (`helianthus/bom.json`, format `helianthus-addon-bom/1`) records the
exact inputs of one add-on image build: the gateway commit, the vrc-explorer
tag, the gateway build's Go module pins, the container base images and the
gateway CLI flag set the wrapper was verified against.

  check    offline; fails when the BOM disagrees with the Dockerfile, the build
           workflow, config.json or the flags the wrapper passes to the gateway.
  generate online; rebuilds the BOM from the pins in the Dockerfile. Needs a
           gateway `--help` capture of the pinned commit (--gateway-help).
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import re
import sys
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
BOM_PATH = ROOT / "helianthus/bom.json"
DOCKERFILE = ROOT / "helianthus/Dockerfile"
WORKFLOW = ROOT / ".github/workflows/build.yml"
CONFIG = ROOT / "helianthus/config.json"
WRAPPER = ROOT / "helianthus/rootfs/etc/services.d/helianthus-gateway/run"

FORMAT = "helianthus-addon-bom/1"
GATEWAY_REPO = "Project-Helianthus/helianthus-ebusgateway"
VRC_REPO = "Project-Helianthus/helianthus-vrc-explorer"
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
TAG_RE = re.compile(r"^v\d+\.\d+\.\d+$")
FLAG_RE = re.compile(r"^[a-z][a-z0-9]*(-[a-z0-9]+)*$")
# Wrapper tokens that look like gateway flags: -word at a word boundary that is
# not part of a shell option, jq filter, or longer dashed token.
WRAPPER_FLAG_RE = re.compile(r"(?<![A-Za-z0-9_$\-])-([a-z][a-z0-9]*(?:-[a-z0-9]+)*)(?==|\s|\"|\\|$)")
# Flags the wrapper uses on commands other than the gateway binary.
NON_GATEWAY_WRAPPER_TOKENS = {"a", "d", "e", "f", "n", "p", "r", "v", "z", "eq", "ne", "gt", "lt", "euo"}
BASE_IMAGES = {
    "amd64": "ghcr.io/home-assistant/amd64-base:3.20",
    "aarch64": "ghcr.io/home-assistant/aarch64-base:3.20",
}


def dockerfile_pins(text: str) -> dict[str, str]:
    gateway = re.search(r"^ARG EBUSGATEWAY_VERSION=(\S+)$", text, re.M)
    vrc = set(re.findall(r"^ARG VRCEXPLORER_VERSION=(\S+)$", text, re.M))
    go_image = re.search(r"^FROM --platform=\$TARGETPLATFORM (golang:\S+) AS builder", text, re.M)
    py_image = re.search(r"^FROM --platform=\$BUILDPLATFORM (python:\S+) AS vrc-explorer", text, re.M)
    build_from = re.search(r"^ARG BUILD_FROM=(\S+)$", text, re.M)
    if not (gateway and len(vrc) == 1 and go_image and py_image and build_from):
        raise ValueError("Dockerfile pins are missing or inconsistent")
    return {
        "gateway": gateway.group(1),
        "vrc_explorer": next(iter(vrc)),
        "go_image": go_image.group(1),
        "python_image": py_image.group(1),
        "build_from": build_from.group(1),
    }


def parse_go_mod(text: str) -> dict[str, Any]:
    go = re.search(r"^go (\S+)$", text, re.M)
    module = re.search(r"^module (\S+)$", text, re.M)
    requires: list[dict[str, Any]] = []
    in_block = False
    for raw in text.splitlines():
        line = raw.strip()
        if line == "require (":
            in_block = True
            continue
        if in_block and line == ")":
            in_block = False
            continue
        if in_block or line.startswith("require "):
            body = line[len("require "):] if line.startswith("require ") else line
            indirect = "// indirect" in body
            fields = body.split("//")[0].split()
            if len(fields) == 2:
                requires.append({"path": fields[0], "version": fields[1], "indirect": indirect})
    replaces = sorted(
        line.strip() for line in text.splitlines() if line.strip().startswith("replace ")
    )
    requires.sort(key=lambda item: item["path"])
    return {
        "module": module.group(1) if module else "",
        "go_directive": go.group(1) if go else "",
        "requires": requires,
        "replace": replaces,
    }


def parse_help_flags(help_text: str) -> list[str]:
    return sorted(set(re.findall(r"^  -([a-z][a-z0-9-]*)", help_text, re.M)))


def wrapper_flags(text: str) -> set[str]:
    flags = set()
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#") or "jq " in stripped or "sed " in stripped:
            continue
        flags.update(WRAPPER_FLAG_RE.findall(line))
    return flags - NON_GATEWAY_WRAPPER_TOKENS


def gateway_flag_mentions(text: str) -> set[str]:
    """Flags the wrapper passes to, or probes on, the gateway binary."""
    found = set()
    for match in re.finditer(r"gateway_supports_flag\s+\"([a-z0-9-]+)\"", text):
        found.add(match.group(1))
    for match in re.finditer(r"binary_supports_flag\s+\S+\s+\"([a-z0-9-]+)\"", text):
        found.add(match.group(1))
    # Flag-name list inside `for required_flag in ...; do`.
    for block in re.finditer(r"for required_flag in\s*((?:[^;]|\\\n)*?);\s*do", text):
        found.update(re.findall(r"[a-z][a-z0-9]*(?:-[a-z0-9]+)+", block.group(1)))
    found.update(wrapper_flags(text))
    return found


def validate(bom: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if bom.get("format") != FORMAT:
        errors.append(f"format must be {FORMAT}")
    docker = dockerfile_pins(DOCKERFILE.read_text(encoding="utf-8"))
    workflow = WORKFLOW.read_text(encoding="utf-8")
    config = json.loads(CONFIG.read_text(encoding="utf-8"))

    gateway = bom.get("gateway", {})
    vrc = bom.get("vrc_explorer", {})
    if not SHA_RE.match(str(gateway.get("commit", ""))):
        errors.append("gateway.commit must be a 40-hex commit")
    if not SHA_RE.match(str(gateway.get("tree", ""))):
        errors.append("gateway.tree must be a 40-hex tree")
    if gateway.get("commit") != docker["gateway"]:
        errors.append("gateway.commit differs from Dockerfile EBUSGATEWAY_VERSION")
    if f"EBUSGATEWAY_VERSION={docker['gateway']}" not in workflow:
        errors.append("build workflow EBUSGATEWAY_VERSION differs from Dockerfile")
    if not TAG_RE.match(str(vrc.get("tag", ""))):
        errors.append("vrc_explorer.tag must look like vX.Y.Z")
    if not SHA_RE.match(str(vrc.get("commit", ""))):
        errors.append("vrc_explorer.commit must be a 40-hex commit")
    if vrc.get("tag") != docker["vrc_explorer"]:
        errors.append("vrc_explorer.tag differs from Dockerfile VRCEXPLORER_VERSION")
    if f"VRCEXPLORER_VERSION={docker['vrc_explorer']}" not in workflow:
        errors.append("build workflow VRCEXPLORER_VERSION differs from Dockerfile")
    if f"refs/tags/{docker['vrc_explorer']}" not in workflow:
        errors.append("build workflow vrc-explorer tag verification differs from Dockerfile")

    if bom.get("addon", {}).get("version") != config.get("version"):
        errors.append("addon.version differs from config.json version")
    if bom.get("addon", {}).get("config_arch") != config.get("arch"):
        errors.append("addon.config_arch differs from config.json arch")

    modules = bom.get("go_modules", {})
    for key in ("go_mod_sha256", "go_sum_sha256"):
        if not re.match(r"^[0-9a-f]{64}$", str(modules.get(key, ""))):
            errors.append(f"go_modules.{key} must be a sha256 hex digest")
    requires = modules.get("requires")
    if not isinstance(requires, list) or not requires:
        errors.append("go_modules.requires must be a non-empty list")
    elif requires != sorted(requires, key=lambda item: item.get("path", "")):
        errors.append("go_modules.requires must be sorted by path")

    images = bom.get("images", {})
    for name, ref in (("builder_go", docker["go_image"]), ("builder_python", docker["python_image"])):
        if images.get(name, {}).get("ref") != ref:
            errors.append(f"images.{name}.ref differs from Dockerfile")
    for name in ("builder_go", "builder_python"):
        if not DIGEST_RE.match(str(images.get(name, {}).get("observed_digest", ""))):
            errors.append(f"images.{name}.observed_digest must be sha256:<64 hex>")
    bases = images.get("base", {})
    if set(bases) != set(BASE_IMAGES):
        errors.append("images.base must list exactly the declared add-on architectures")
    for arch, entry in bases.items():
        if entry.get("ref") != BASE_IMAGES.get(arch) or f"base: {entry.get('ref')}" not in workflow:
            errors.append(f"images.base.{arch}.ref differs from build workflow matrix")
        if not DIGEST_RE.match(str(entry.get("observed_digest", ""))):
            errors.append(f"images.base.{arch}.observed_digest must be sha256:<64 hex>")
    if docker["build_from"] != "ghcr.io/home-assistant/base:3.20":
        errors.append("Dockerfile default BUILD_FROM changed; update BASE_IMAGES and the BOM")

    flags = bom.get("gateway_cli_flags")
    if not isinstance(flags, list) or not flags or flags != sorted(set(flags)):
        errors.append("gateway_cli_flags must be a sorted, unique, non-empty list")
    else:
        bad = [flag for flag in flags if not FLAG_RE.match(flag)]
        if bad:
            errors.append(f"gateway_cli_flags has malformed entries: {bad}")
        # Flags the wrapper probes with gateway_supports_flag are optional on
        # older gateways; at the pinned commit every one must exist.
        unknown = sorted(gateway_flag_mentions(WRAPPER.read_text(encoding="utf-8")) - set(flags))
        if unknown:
            errors.append(
                "wrapper uses flags the pinned gateway does not define: " + ", ".join(unknown)
            )

    freeze = bom.get("freeze", {})
    if freeze.get("status") not in {"unfrozen", "frozen"}:
        errors.append("freeze.status must be unfrozen or frozen")
    if freeze.get("owner") != "INT-16":
        errors.append("freeze.owner must be INT-16")
    return errors


def http_json(url: str, headers: dict[str, str] | None = None) -> Any:
    request = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def http_text(url: str, headers: dict[str, str] | None = None) -> bytes:
    request = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read()


def gh_api(path: str) -> Any:
    return http_json(
        f"https://api.github.com{path}",
        {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"},
    )


def registry_digest(ref: str) -> str:
    registry, _, rest = ref.partition("/")
    name, _, tag = rest.rpartition(":")
    if registry == "ghcr.io":
        token_url = f"https://ghcr.io/token?scope=repository:{name}:pull"
        base = f"https://ghcr.io/v2/{name}/manifests/{tag}"
    else:
        name = ref.rpartition(":")[0]
        tag = ref.rpartition(":")[2]
        name = name if "/" in name else f"library/{name}"
        token_url = f"https://auth.docker.io/token?service=registry.docker.io&scope=repository:{name}:pull"
        base = f"https://registry-1.docker.io/v2/{name}/manifests/{tag}"
    token = http_json(token_url)["token"]
    request = urllib.request.Request(
        base,
        method="HEAD",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": ", ".join(
                (
                    "application/vnd.oci.image.index.v1+json",
                    "application/vnd.docker.distribution.manifest.list.v2+json",
                    "application/vnd.oci.image.manifest.v1+json",
                    "application/vnd.docker.distribution.manifest.v2+json",
                )
            ),
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.headers["Docker-Content-Digest"]


def generate(help_path: Path) -> dict[str, Any]:
    docker = dockerfile_pins(DOCKERFILE.read_text(encoding="utf-8"))
    config = json.loads(CONFIG.read_text(encoding="utf-8"))
    commit = docker["gateway"]
    tree = gh_api(f"/repos/{GATEWAY_REPO}/git/commits/{commit}")["tree"]["sha"]
    raw = {"Accept": "application/vnd.github.raw+json"}
    go_mod = http_text(f"https://api.github.com/repos/{GATEWAY_REPO}/contents/go.mod?ref={commit}", raw)
    go_sum = http_text(f"https://api.github.com/repos/{GATEWAY_REPO}/contents/go.sum?ref={commit}", raw)
    ref = gh_api(f"/repos/{VRC_REPO}/git/ref/tags/{docker['vrc_explorer']}")["object"]
    if ref["type"] == "tag":
        ref = gh_api(f"/repos/{VRC_REPO}/git/tags/{ref['sha']}")["object"]
    if ref["type"] != "commit":
        raise ValueError("vrc-explorer tag does not resolve to a commit")
    now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    modules = parse_go_mod(go_mod.decode("utf-8"))
    modules["go_mod_sha256"] = hashlib.sha256(go_mod).hexdigest()
    modules["go_sum_sha256"] = hashlib.sha256(go_sum).hexdigest()
    modules["source"] = f"https://github.com/{GATEWAY_REPO}/blob/{commit}/go.mod"
    modules["build_mode"] = "GOWORK=off GOFLAGS=-mod=readonly (Dockerfile builder stage)"
    return {
        "format": FORMAT,
        "addon": {"slug": config["slug"], "version": config["version"], "config_arch": config["arch"]},
        "gateway": {
            "repository": f"https://github.com/{GATEWAY_REPO}",
            "commit": commit,
            "tree": tree,
        },
        "vrc_explorer": {
            "repository": f"https://github.com/{VRC_REPO}",
            "tag": docker["vrc_explorer"],
            "commit": ref["sha"],
        },
        "go_modules": modules,
        "images": {
            "builder_go": {"ref": docker["go_image"], "observed_digest": registry_digest(docker["go_image"])},
            "builder_python": {
                "ref": docker["python_image"],
                "observed_digest": registry_digest(docker["python_image"]),
            },
            "base": {
                arch: {"ref": image, "observed_digest": registry_digest(image)}
                for arch, image in BASE_IMAGES.items()
            },
            "digest_note": "Digests were observed at generation time; the build references tags. INT-16 replaces them with pinned digests when it freezes the BOM.",
            "observed_at": now,
        },
        "gateway_cli_flags": parse_help_flags(help_path.read_text(encoding="utf-8")),
        "freeze": {
            "owner": "INT-16",
            "status": "unfrozen",
            "note": "INT-16 freezes this file for the 0.7 release: it replaces observed digests with pinned digests and sets status to frozen. After that, any pin change requires a new BOM generation.",
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    check = sub.add_parser("check")
    check.add_argument("--bom", type=Path, default=BOM_PATH)
    gen = sub.add_parser("generate")
    gen.add_argument("--gateway-help", type=Path, required=True, help="capture of `gateway --help` built from the pinned commit")
    gen.add_argument("--out", type=Path, default=BOM_PATH)
    args = parser.parse_args()

    if args.command == "generate":
        bom = generate(args.gateway_help)
        args.out.write_text(json.dumps(bom, indent=2) + "\n", encoding="utf-8")
        print(f"BOM written: {args.out}")
        return 0
    try:
        bom = json.loads(args.bom.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"BOM check: FAIL ({exc})")
        return 1
    errors = validate(bom)
    if errors:
        print("BOM check: FAIL")
        for error in errors:
            print(f"  - {error}")
        return 1
    print("BOM check: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
