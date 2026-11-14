#!/usr/bin/env python3
"""Generate or check the Helianthus add-on BOM manifest.

The BOM (`helianthus/bom.json`, format `helianthus-addon-bom/1`) records the
exact inputs of one add-on image build: the gateway commit, the vrc-explorer
tag and commit (or commit alone), the gateway build's Go module pins, the
semantic contract the pinned semantic registry implements, the container base
images and the gateway CLI flag set the wrapper was verified against.

  check           offline; fails when the BOM disagrees with the Dockerfile,
                  the build workflow, config.json or the flags the wrapper
                  passes to the gateway.
  check --frozen  offline; every check rule plus the release freeze: status
                  frozen, every builder and base image referenced by its pinned
                  digest, the element catalog named, commit pins only.
  generate        online; rebuilds the BOM from the pins in the Dockerfile and
                  reads the element catalog pin of the semantic registry at its
                  pinned version. Needs a gateway `--help` capture of the
                  pinned commit, taken from the add-on profile build
                  (-tags nomatter) (--gateway-help).

The add-on gateway carries no Matter code, so the check refuses any gateway
flag that names Matter.
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import re
import sys
import urllib.error
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
REGISTRY_MODULE = "github.com/Project-Helianthus/helianthus-semreg"
REGISTRY_REPO = "Project-Helianthus/helianthus-semreg"
# The registry declares the digest of its element catalog copy in this file.
REGISTRY_PIN_FILE = "semreg/v1/graph/catalog.go"
REGISTRY_FIXTURES_README = "fixtures/README.md"
SEMANTIC_CONTRACT_MEMBERS = {"registry_module", "registry_version", "element_catalog"}
ELEMENT_CATALOG_MEMBERS = {"path", "sha256", "source"}
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
HEX64_RE = re.compile(r"[0-9a-f]{64}")
REPOSITORY_URL_RE = re.compile(r"https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")
PSEUDO_VERSION_RE = re.compile(r"[.-]\d{14}-([0-9a-f]{12})$")
PINNED_DIGEST_RE = re.compile(r'^const PinnedDigest(?:\s+[\w.]+)?\s*=\s*"sha256:([0-9a-f]{64})"\s*$', re.M)
PINNED_PATH_RE = re.compile(r"^// PinnedDigest is the SHA-256 of ([^\s,]+)", re.M)
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


def split_image(value: str) -> tuple[str, str | None]:
    """Split `name:tag@digest` into the tag reference and the digest, if any."""
    ref, separator, digest = value.partition("@")
    return ref, (digest if separator else None)


def dockerfile_pins(text: str) -> dict[str, Any]:
    gateway = re.search(r"^ARG EBUSGATEWAY_VERSION=(\S+)$", text, re.M)
    vrc = set(re.findall(r"^ARG VRCEXPLORER_VERSION=(\S+)$", text, re.M))
    go_image = re.search(r"^FROM --platform=\$TARGETPLATFORM (golang:\S+) AS builder", text, re.M)
    py_image = re.search(r"^FROM --platform=\$BUILDPLATFORM (python:\S+) AS vrc-explorer", text, re.M)
    build_from = re.search(r"^ARG BUILD_FROM=(\S+)$", text, re.M)
    if not (gateway and len(vrc) == 1 and go_image and py_image and build_from):
        raise ValueError("Dockerfile pins are missing or inconsistent")
    go_ref, go_digest = split_image(go_image.group(1))
    py_ref, py_digest = split_image(py_image.group(1))
    base_ref, base_digest = split_image(build_from.group(1))
    return {
        "gateway": gateway.group(1),
        "vrc_explorer": next(iter(vrc)),
        "go_image": go_ref,
        "go_image_digest": go_digest,
        "python_image": py_ref,
        "python_image_digest": py_digest,
        "build_from": base_ref,
        "build_from_digest": base_digest,
    }


def workflow_bases(text: str) -> dict[str, str | None]:
    """Base image references of the build workflow matrix: tag reference to digest."""
    bases: dict[str, str | None] = {}
    for value in re.findall(r"^\s*base:\s*(\S+)\s*$", text, re.M):
        ref, digest = split_image(value)
        bases[ref] = digest
    return bases


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


def gateway_flag_errors(flags: Any) -> list[str]:
    if not isinstance(flags, list) or not flags or flags != sorted(set(flags)):
        return ["gateway_cli_flags must be a sorted, unique, non-empty list"]
    errors: list[str] = []
    bad = [flag for flag in flags if not FLAG_RE.match(flag)]
    if bad:
        errors.append(f"gateway_cli_flags has malformed entries: {bad}")
    matter = [flag for flag in flags if "matter" in flag]
    if matter:
        errors.append(
            "gateway_cli_flags names matter, which the add-on profile build leaves out: "
            + ", ".join(matter)
        )
    # Flags the wrapper probes with gateway_supports_flag are optional on
    # older gateways; at the pinned commit every one must exist.
    unknown = sorted(gateway_flag_mentions(WRAPPER.read_text(encoding="utf-8")) - set(flags))
    if unknown:
        errors.append("wrapper uses flags the pinned gateway does not define: " + ", ".join(unknown))
    return errors


def registry_pin(modules: Any) -> str | None:
    """Version of the semantic registry in the gateway's Go module pins."""
    requires = modules.get("requires") if isinstance(modules, dict) else None
    for item in requires if isinstance(requires, list) else []:
        if isinstance(item, dict) and item.get("path") == REGISTRY_MODULE:
            return item.get("version")
    return None


def element_catalog_errors(entry: Any) -> list[str]:
    if entry is None:
        return []
    if not isinstance(entry, dict):
        return ["semantic_contract.element_catalog must be null or an object"]
    errors: list[str] = []
    unknown = sorted(set(entry) - ELEMENT_CATALOG_MEMBERS)
    if unknown:
        errors.append(f"semantic_contract.element_catalog has unknown members: {unknown}")
    if not relative_path(entry.get("path")):
        errors.append("semantic_contract.element_catalog.path must be a relative path inside the registry")
    sha256 = entry.get("sha256")
    if not isinstance(sha256, str) or not HEX64_RE.fullmatch(sha256):
        errors.append("semantic_contract.element_catalog.sha256 must be the 64-hex SHA-256 of the catalog bytes")
    if "source" in entry:
        source = entry["source"]
        if (
            not isinstance(source, dict)
            or set(source) != {"repository", "path"}
            or not isinstance(source.get("repository"), str)
            or not REPOSITORY_URL_RE.fullmatch(source["repository"])
            or not relative_path(source.get("path"))
        ):
            errors.append(
                "semantic_contract.element_catalog.source must name the repository and path the registry declares"
            )
    return errors


def relative_path(value: Any) -> bool:
    return (
        isinstance(value, str)
        and bool(value)
        and not value.startswith("/")
        and "\\" not in value
        and all(part not in {"", ".", ".."} for part in value.split("/"))
    )


def semantic_contract_errors(bom: dict[str, Any], frozen: bool) -> list[str]:
    section = bom.get("semantic_contract")
    if not isinstance(section, dict):
        return ["semantic_contract must be an object naming the semantic registry pin"]
    errors: list[str] = []
    unknown = sorted(set(section) - SEMANTIC_CONTRACT_MEMBERS)
    if unknown:
        errors.append(f"semantic_contract has unknown members: {unknown}")
    missing = sorted(SEMANTIC_CONTRACT_MEMBERS - set(section))
    if missing:
        errors.append(f"semantic_contract is missing members: {missing}")
    if section.get("registry_module") != REGISTRY_MODULE:
        errors.append(f"semantic_contract.registry_module must be {REGISTRY_MODULE}")
    pinned = registry_pin(bom.get("go_modules"))
    if pinned is None:
        errors.append(f"go_modules.requires has no {REGISTRY_MODULE} entry")
    elif section.get("registry_version") != pinned:
        errors.append(f"semantic_contract.registry_version differs from the go_modules entry of {REGISTRY_MODULE}")
    errors.extend(element_catalog_errors(section.get("element_catalog")))
    if frozen and section.get("element_catalog") is None:
        errors.append("semantic_contract.element_catalog must name the element catalog in a frozen BOM")
    return errors


def image_digest_errors(
    images: dict[str, Any], docker: dict[str, Any], workflow: str, frozen: bool
) -> list[str]:
    """Pinned image digests against the digests the Dockerfile and the workflow reference."""
    bases = workflow_bases(workflow)
    entries: list[tuple[str, Any, str, str | None]] = [
        ("builder_go", images.get("builder_go"), "Dockerfile", docker["go_image_digest"]),
        ("builder_python", images.get("builder_python"), "Dockerfile", docker["python_image_digest"]),
    ]
    base_entries = images.get("base")
    for arch, entry in (base_entries.items() if isinstance(base_entries, dict) else ()):
        ref = entry.get("ref") if isinstance(entry, dict) else None
        entries.append((f"base.{arch}", entry, "build workflow", bases.get(ref)))
    errors: list[str] = []
    for name, entry, where, referenced in entries:
        pinned = entry.get("pinned_digest") if isinstance(entry, dict) else None
        if (pinned is not None or frozen) and not DIGEST_RE.match(str(pinned)):
            errors.append(f"images.{name}.pinned_digest must be sha256:<64 hex>")
        if referenced is not None and referenced != pinned:
            errors.append(f"{where} references images.{name} at {referenced}, not at its pinned_digest")
        if frozen and referenced is None:
            errors.append(f"{where} must reference images.{name} by its pinned_digest (@sha256:...)")
    return errors


def explorer_errors(vrc: dict[str, Any], pin: str, workflow: str) -> list[str]:
    """The Explorer pin: a tag with its commit, or a commit alone with a null tag."""
    errors: list[str] = []
    if not SHA_RE.match(str(vrc.get("commit", ""))):
        errors.append("vrc_explorer.commit must be a 40-hex commit")
    if SHA_RE.match(pin):
        if vrc.get("tag") is not None:
            errors.append("vrc_explorer.tag must be null when the Dockerfile pins a commit")
        if vrc.get("commit") != pin:
            errors.append("vrc_explorer.commit differs from Dockerfile VRCEXPLORER_VERSION")
    else:
        if not TAG_RE.match(str(vrc.get("tag", ""))):
            errors.append("vrc_explorer.tag must look like vX.Y.Z")
        if vrc.get("tag") != pin:
            errors.append("vrc_explorer.tag differs from Dockerfile VRCEXPLORER_VERSION")
        if f"refs/tags/{pin}" not in workflow:
            errors.append("build workflow vrc-explorer tag verification differs from Dockerfile")
    if f"VRCEXPLORER_VERSION={pin}" not in workflow:
        errors.append("build workflow VRCEXPLORER_VERSION differs from Dockerfile")
    return errors


def frozen_errors(bom: dict[str, Any], docker: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if bom.get("freeze", {}).get("status") != "frozen":
        errors.append("freeze.status must be frozen")
    if not SHA_RE.match(docker["gateway"]):
        errors.append("Dockerfile EBUSGATEWAY_VERSION must be a commit in a frozen BOM")
    if not SHA_RE.match(docker["vrc_explorer"]):
        errors.append("Dockerfile VRCEXPLORER_VERSION must be a commit in a frozen BOM")
    return errors


def validate(bom: dict[str, Any], frozen: bool = False) -> list[str]:
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
    errors.extend(explorer_errors(vrc, docker["vrc_explorer"], workflow))

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
    errors.extend(image_digest_errors(images, docker, workflow, frozen))

    errors.extend(semantic_contract_errors(bom, frozen))
    errors.extend(gateway_flag_errors(bom.get("gateway_cli_flags")))

    freeze = bom.get("freeze", {})
    if freeze.get("status") not in {"unfrozen", "frozen"}:
        errors.append("freeze.status must be unfrozen or frozen")
    if freeze.get("owner") != "INT-16":
        errors.append("freeze.owner must be INT-16")
    if frozen:
        errors.extend(frozen_errors(bom, docker))
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


def registry_file(commit: str, path: str) -> bytes | None:
    """One file of the semantic registry at a commit; None when it does not exist there."""
    try:
        return http_text(
            f"https://api.github.com/repos/{REGISTRY_REPO}/contents/{path}?ref={commit}",
            {"Accept": "application/vnd.github.raw+json"},
        )
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        raise


def module_version_ref(version: str) -> str:
    """The revision a Go module version names: the commit prefix of a pseudo-version, else the tag."""
    base = version.removesuffix("+incompatible")
    match = PSEUDO_VERSION_RE.search(base)
    return match.group(1) if match else base


def declared_catalog_source(readme: bytes | None, path: str) -> dict[str, str] | None:
    """The source the registry's fixture index declares for its catalog copy, if it declares one."""
    if readme is None:
        return None
    relative = path.removeprefix("fixtures/")
    pattern = re.escape(f"[`{relative}`]({relative})") + (
        r"\s+is\s+a\s+byte-for-byte\s+copy\s+of\s+`([^`\s]+)`\s+from\s+`([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)`"
    )
    match = re.search(pattern, readme.decode("utf-8"))
    if match is None:
        return None
    return {"repository": f"https://github.com/{match.group(2)}", "path": match.group(1)}


def element_catalog_from_registry(commit: str) -> dict[str, Any] | None:
    """The element catalog pin of the registry at a commit; None when the registry declares none."""
    graph = registry_file(commit, REGISTRY_PIN_FILE)
    declared = PINNED_DIGEST_RE.search(graph.decode("utf-8")) if graph is not None else None
    if graph is None or declared is None:
        return None
    named = PINNED_PATH_RE.search(graph.decode("utf-8"))
    if named is None:
        raise ValueError(f"{REGISTRY_PIN_FILE} declares PinnedDigest without naming the file it pins")
    path = named.group(1)
    data = registry_file(commit, path)
    if data is None:
        raise ValueError(f"the registry pins {path}, which is missing at its pinned version")
    computed = hashlib.sha256(data).hexdigest()
    if computed != declared.group(1):
        raise ValueError(
            f"element catalog {path} hashes to {computed}, which differs from the digest the registry "
            f"declares in {REGISTRY_PIN_FILE}; refusing to record it"
        )
    entry: dict[str, Any] = {"path": path, "sha256": computed}
    source = declared_catalog_source(registry_file(commit, REGISTRY_FIXTURES_README), path)
    if source is not None:
        entry["source"] = source
    return entry


def semantic_contract_from_registry(modules: dict[str, Any]) -> dict[str, Any]:
    version = registry_pin(modules)
    if version is None:
        raise ValueError(f"the gateway go.mod does not require {REGISTRY_MODULE}")
    ref = module_version_ref(version)
    commit = gh_api(f"/repos/{REGISTRY_REPO}/commits/{ref}")["sha"]
    if not SHA_RE.match(commit) or (ref != version.removesuffix("+incompatible") and not commit.startswith(ref)):
        raise ValueError(f"{REGISTRY_MODULE} {version} does not resolve to the commit it names")
    return {
        "registry_module": REGISTRY_MODULE,
        "registry_version": version,
        "element_catalog": element_catalog_from_registry(commit),
    }


def generate(help_path: Path) -> dict[str, Any]:
    docker = dockerfile_pins(DOCKERFILE.read_text(encoding="utf-8"))
    config = json.loads(CONFIG.read_text(encoding="utf-8"))
    commit = docker["gateway"]
    tree = gh_api(f"/repos/{GATEWAY_REPO}/git/commits/{commit}")["tree"]["sha"]
    raw = {"Accept": "application/vnd.github.raw+json"}
    go_mod = http_text(f"https://api.github.com/repos/{GATEWAY_REPO}/contents/go.mod?ref={commit}", raw)
    go_sum = http_text(f"https://api.github.com/repos/{GATEWAY_REPO}/contents/go.sum?ref={commit}", raw)
    if SHA_RE.match(docker["vrc_explorer"]):
        vrc_tag = None
        vrc_commit = gh_api(f"/repos/{VRC_REPO}/commits/{docker['vrc_explorer']}")["sha"]
        if vrc_commit != docker["vrc_explorer"]:
            raise ValueError("vrc-explorer commit pin does not resolve to itself")
    else:
        ref = gh_api(f"/repos/{VRC_REPO}/git/ref/tags/{docker['vrc_explorer']}")["object"]
        if ref["type"] == "tag":
            ref = gh_api(f"/repos/{VRC_REPO}/git/tags/{ref['sha']}")["object"]
        if ref["type"] != "commit":
            raise ValueError("vrc-explorer tag does not resolve to a commit")
        vrc_tag, vrc_commit = docker["vrc_explorer"], ref["sha"]
    now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    modules = parse_go_mod(go_mod.decode("utf-8"))
    modules["go_mod_sha256"] = hashlib.sha256(go_mod).hexdigest()
    modules["go_sum_sha256"] = hashlib.sha256(go_sum).hexdigest()
    modules["source"] = f"https://github.com/{GATEWAY_REPO}/blob/{commit}/go.mod"
    modules["build_mode"] = "GOWORK=off GOFLAGS=-mod=readonly (Dockerfile builder stage)"
    bases = workflow_bases(WORKFLOW.read_text(encoding="utf-8"))

    def image(ref: str, pinned: str | None) -> dict[str, str]:
        entry = {"ref": ref, "observed_digest": registry_digest(ref)}
        if pinned is not None:
            entry["pinned_digest"] = pinned
        return entry

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
            "tag": vrc_tag,
            "commit": vrc_commit,
        },
        "go_modules": modules,
        "semantic_contract": semantic_contract_from_registry(modules),
        "images": {
            "builder_go": image(docker["go_image"], docker["go_image_digest"]),
            "builder_python": image(docker["python_image"], docker["python_image_digest"]),
            "base": {arch: image(ref, bases.get(ref)) for arch, ref in BASE_IMAGES.items()},
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
    check.add_argument(
        "--frozen",
        action="store_true",
        help="also require the release freeze: status frozen, digest-pinned images, the element catalog, commit pins",
    )
    gen = sub.add_parser("generate")
    gen.add_argument(
        "--gateway-help",
        type=Path,
        required=True,
        help="capture of `gateway --help` from the add-on profile build (-tags nomatter) of the pinned commit",
    )
    gen.add_argument("--out", type=Path, default=BOM_PATH)
    args = parser.parse_args()

    if args.command == "generate":
        try:
            bom = generate(args.gateway_help)
        except (ValueError, urllib.error.URLError) as exc:
            print(f"BOM generate: FAIL ({exc})")
            return 1
        args.out.write_text(json.dumps(bom, indent=2) + "\n", encoding="utf-8")
        print(f"BOM written: {args.out}")
        return 0
    label = "BOM check --frozen" if args.frozen else "BOM check"
    try:
        bom = json.loads(args.bom.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"{label}: FAIL ({exc})")
        return 1
    errors = validate(bom, frozen=args.frozen)
    if errors:
        print(f"{label}: FAIL")
        for error in errors:
            print(f"  - {error}")
        return 1
    print(f"{label}: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
