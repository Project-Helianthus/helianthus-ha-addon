"""BOM manifest and wrapper-versus-gateway-flag contract tests."""

from __future__ import annotations

import copy
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import bom_manifest  # noqa: E402

BOM = json.loads(bom_manifest.BOM_PATH.read_text(encoding="utf-8"))


def test_committed_bom_is_valid() -> None:
    assert bom_manifest.validate(BOM) == []


def test_builder_image_is_the_matterreg_go_toolchain() -> None:
    dockerfile = bom_manifest.DOCKERFILE.read_text(encoding="utf-8")
    assert (
        "FROM --platform=$TARGETPLATFORM golang:1.27.4-alpine AS builder"
        in dockerfile.splitlines()
    )


def test_builder_observed_digest_is_the_registry_digest_of_the_builder_ref() -> None:
    builder = BOM["images"]["builder_go"]
    assert builder["ref"] == "golang:1.27.4-alpine"
    assert (
        builder["observed_digest"]
        == "sha256:70bd7ddea8b6cbe5d6943cde279d6b67feb10cc924fb9100d1d8757c1575b280"
    )


def test_check_cli_passes_for_committed_bom() -> None:
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts/bom_manifest.py"), "check"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout
    assert "BOM check: PASS" in result.stdout


def test_wrapper_does_not_use_removed_known_assets_flag() -> None:
    wrapper = bom_manifest.WRAPPER.read_text(encoding="utf-8")
    assert "m2m-graphql-known-assets" not in wrapper
    assert "m2m-graphql-known-assets" not in BOM["gateway_cli_flags"]
    assert "m2m-graphql-allowed-assets" in BOM["gateway_cli_flags"]


@pytest.mark.parametrize("flag", ("m2m-graphql-client-ca", "m2m-graphql-denied-principals"))
def test_listener_client_auth_flags_are_not_configuration_options(flag: str) -> None:
    config = json.loads((ROOT / "helianthus/config.json").read_text(encoding="utf-8"))
    for section in ("options", "schema"):
        assert flag not in config[section]
        assert flag.replace("-", "_") not in config[section]


def test_wrapper_omits_gateway_listener_client_auth_flags() -> None:
    used = bom_manifest.gateway_flag_mentions(
        bom_manifest.WRAPPER.read_text(encoding="utf-8")
    )
    # The pinned gateway defines both flags; the wrapper exposes neither.
    assert "m2m-graphql-client-ca" in BOM["gateway_cli_flags"]
    assert "m2m-graphql-client-ca" not in used
    assert "m2m-graphql-denied-principals" in BOM["gateway_cli_flags"]
    assert "m2m-graphql-denied-principals" not in used


def test_wrapper_flags_are_all_defined_by_pinned_gateway() -> None:
    wrapper = bom_manifest.WRAPPER.read_text(encoding="utf-8")
    used = bom_manifest.gateway_flag_mentions(wrapper)
    assert used, "no gateway flags detected in the wrapper"
    assert used <= set(BOM["gateway_cli_flags"])


@pytest.mark.parametrize("flag", ("m2m-graphql-allowed-assets",))
def test_checker_rejects_a_flag_the_gateway_removed(flag: str) -> None:
    mutated = copy.deepcopy(BOM)
    mutated["gateway_cli_flags"] = [
        entry for entry in mutated["gateway_cli_flags"] if entry != flag
    ]
    errors = bom_manifest.validate(mutated)
    assert any(flag in error for error in errors)


@pytest.mark.parametrize(
    ("path", "value", "needle"),
    (
        (("gateway", "commit"), "0" * 40, "differs from Dockerfile"),
        (("vrc_explorer", "tag"), "v0.0.1", "differs from Dockerfile"),
        (("addon", "version"), "0.0.0", "config.json version"),
        (("freeze", "owner"), "someone", "INT-16"),
        (("go_modules", "go_mod_sha256"), "xyz", "sha256"),
        (("images", "base", "amd64", "observed_digest"), "latest", "observed_digest"),
    ),
)
def test_checker_rejects_drift(path: tuple[str, ...], value: str, needle: str) -> None:
    mutated = copy.deepcopy(BOM)
    node = mutated
    for key in path[:-1]:
        node = node[key]
    node[path[-1]] = value
    assert any(needle in error for error in bom_manifest.validate(mutated))


def test_parse_go_mod_reads_blocks_and_indirect_markers() -> None:
    parsed = bom_manifest.parse_go_mod(
        "module example.test/m\n\ngo 1.22.0\n\nrequire (\n\texample.test/b v1.2.3\n"
        "\texample.test/a v0.0.0-20260101000000-abcdefabcdef // indirect\n)\n"
        "require example.test/c v2.0.0\n"
    )
    assert parsed["go_directive"] == "1.22.0"
    assert [item["path"] for item in parsed["requires"]] == [
        "example.test/a",
        "example.test/b",
        "example.test/c",
    ]
    assert parsed["requires"][0]["indirect"] is True
    assert parsed["requires"][1]["indirect"] is False


def test_wrapper_scan_detects_an_unsupported_flag_and_omits_client_auth() -> None:
    wrapper = bom_manifest.WRAPPER.read_text(encoding="utf-8")
    assert "m2m-graphql-client-ca" not in bom_manifest.gateway_flag_mentions(wrapper)
    assert "m2m-graphql-denied-principals" not in bom_manifest.gateway_flag_mentions(wrapper)
    injected = wrapper + '\n-unsupported-test-only-flag "x"\n'
    used = bom_manifest.gateway_flag_mentions(injected)
    assert "unsupported-test-only-flag" in used
    assert not used <= set(BOM["gateway_cli_flags"])


def test_the_bom_lists_no_matter_flag_for_the_add_on_profile_build() -> None:
    assert not [flag for flag in BOM["gateway_cli_flags"] if "matter" in flag]


@pytest.mark.parametrize("flag", ("matter-library-enabled", "matter-output", "nomatter-probe"))
def test_checker_refuses_any_gateway_flag_naming_matter(flag: str) -> None:
    mutated = copy.deepcopy(BOM)
    mutated["gateway_cli_flags"] = sorted({*mutated["gateway_cli_flags"], flag})
    errors = bom_manifest.validate(mutated)
    assert any("matter" in error and flag in error for error in errors), errors


def test_usage_says_the_help_capture_comes_from_the_add_on_profile_build() -> None:
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts/bom_manifest.py"), "generate", "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    usage = " ".join(result.stdout.split())
    assert "add-on profile build (-tags nomatter)" in usage
    assert "add-on profile build (-tags nomatter)" in " ".join((bom_manifest.__doc__ or "").split())


# --- semantic contract, Explorer commit pins, frozen check, generate -------

REGISTRY_MODULE = "github.com/Project-Helianthus/helianthus-semreg"
SOURCE_DOCKERFILE = bom_manifest.DOCKERFILE
SOURCE_WORKFLOW = bom_manifest.WORKFLOW
CATALOG_PATH = "fixtures/v1/element-catalog-v1.json"


def _hex(label: str) -> str:
    """A synthetic 64-hex value computed from a label."""
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def _commit(label: str) -> str:
    """A synthetic 40-hex commit computed from a label."""
    return hashlib.sha1(label.encode("utf-8")).hexdigest()


def _registry_version(bom: dict) -> str:
    return next(
        item["version"]
        for item in bom["go_modules"]["requires"]
        if item["path"] == REGISTRY_MODULE
    )


def test_checker_requires_the_semantic_contract_section() -> None:
    mutated = copy.deepcopy(BOM)
    mutated.pop("semantic_contract", None)
    assert any("semantic_contract" in error for error in bom_manifest.validate(mutated))


def test_committed_semantic_contract_follows_the_registry_pin() -> None:
    section = BOM["semantic_contract"]
    assert section["registry_module"] == REGISTRY_MODULE
    assert section["registry_version"] == _registry_version(BOM)
    # The pinned registry predates its copy of the element catalog.
    assert section["element_catalog"] is None


def test_checker_rejects_a_registry_version_other_than_the_go_module_pin() -> None:
    mutated = copy.deepcopy(BOM)
    mutated["semantic_contract"]["registry_version"] = "v0.0.0-20260101000000-" + _hex("other")[:12]
    errors = bom_manifest.validate(mutated)
    assert any("registry_version" in error and "go_modules" in error for error in errors), errors


def test_checker_rejects_a_registry_module_other_than_the_semantic_registry() -> None:
    mutated = copy.deepcopy(BOM)
    mutated["semantic_contract"]["registry_module"] = "github.com/Project-Helianthus/helianthus-ebusreg"
    errors = bom_manifest.validate(mutated)
    assert any("registry_module" in error for error in errors), errors


def test_checker_accepts_a_present_element_catalog() -> None:
    mutated = copy.deepcopy(BOM)
    mutated["semantic_contract"]["element_catalog"] = {
        "path": CATALOG_PATH,
        "sha256": _hex("catalog bytes"),
        "source": {
            "repository": "https://github.com/Project-Helianthus/helianthus-docs-semantic",
            "path": "api/v1/element-catalog-v1.json",
        },
    }
    assert bom_manifest.validate(mutated) == []


@pytest.mark.parametrize(
    "sha256",
    (None, "", "sha256:" + _hex("prefixed"), _hex("short")[:63], _hex("upper").upper(), _hex("long") + "0"),
    ids=("missing", "empty", "prefixed", "short", "uppercase", "long"),
)
def test_checker_rejects_an_element_catalog_without_a_64_hex_sha256(sha256: object) -> None:
    mutated = copy.deepcopy(BOM)
    entry: dict = {"path": CATALOG_PATH}
    if sha256 is not None:
        entry["sha256"] = sha256
    mutated["semantic_contract"]["element_catalog"] = entry
    errors = bom_manifest.validate(mutated)
    assert any("element_catalog.sha256" in error for error in errors), errors


@pytest.mark.parametrize(
    ("entry", "needle"),
    (
        ({"sha256": _hex("no path")}, "element_catalog.path"),
        ({"path": "/abs/catalog.json", "sha256": _hex("abs")}, "element_catalog.path"),
        ({"path": "../catalog.json", "sha256": _hex("up")}, "element_catalog.path"),
        ({"path": CATALOG_PATH, "sha256": _hex("extra"), "note": "x"}, "element_catalog"),
        ({"path": CATALOG_PATH, "sha256": _hex("src"), "source": {"path": "a.json"}}, "element_catalog.source"),
        ("catalog", "element_catalog"),
    ),
)
def test_checker_rejects_a_malformed_element_catalog(entry: object, needle: str) -> None:
    mutated = copy.deepcopy(BOM)
    mutated["semantic_contract"]["element_catalog"] = entry
    errors = bom_manifest.validate(mutated)
    assert any(needle in error for error in errors), errors


def test_checker_rejects_unknown_semantic_contract_members() -> None:
    mutated = copy.deepcopy(BOM)
    mutated["semantic_contract"]["catalog_note"] = "x"
    assert any("semantic_contract" in error for error in bom_manifest.validate(mutated))


def _write_build_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    explorer: str,
    image_digests: dict[str, str] | None = None,
) -> None:
    """Point the checker at Dockerfile and workflow copies with replaced pins."""
    dockerfile = SOURCE_DOCKERFILE.read_text(encoding="utf-8")
    workflow = SOURCE_WORKFLOW.read_text(encoding="utf-8")
    current = BOM["vrc_explorer"]["tag"]
    dockerfile = dockerfile.replace(f"VRCEXPLORER_VERSION={current}", f"VRCEXPLORER_VERSION={explorer}")
    workflow = workflow.replace(f"VRCEXPLORER_VERSION={current}", f"VRCEXPLORER_VERSION={explorer}")
    for name, digest in (image_digests or {}).items():
        if name.startswith("base."):
            ref = bom_manifest.BUILD_BASE_IMAGES[name.split(".", 1)[1]]
            workflow = workflow.replace(f"base: {ref}\n", f"base: {ref}@{digest}\n")
        else:
            ref = BOM["images"][name]["ref"]
            dockerfile = dockerfile.replace(f" {ref} AS ", f" {ref}@{digest} AS ")
    docker_path = tmp_path / "Dockerfile"
    workflow_path = tmp_path / "build.yml"
    docker_path.write_text(dockerfile, encoding="utf-8")
    workflow_path.write_text(workflow, encoding="utf-8")
    monkeypatch.setattr(bom_manifest, "DOCKERFILE", docker_path)
    monkeypatch.setattr(bom_manifest, "WORKFLOW", workflow_path)


def test_checker_accepts_an_explorer_commit_pin_with_a_null_tag(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    commit = _commit("explorer")
    _write_build_files(tmp_path, monkeypatch, explorer=commit)
    mutated = copy.deepcopy(BOM)
    mutated["vrc_explorer"]["tag"] = None
    mutated["vrc_explorer"]["commit"] = commit
    assert bom_manifest.validate(mutated) == []


@pytest.mark.parametrize(
    ("tag", "commit_label", "needle"),
    (
        (None, "another explorer", "vrc_explorer.commit differs"),
        ("v0.6.1", "explorer", "vrc_explorer.tag must be null"),
    ),
)
def test_checker_rejects_an_explorer_commit_pin_that_disagrees(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, tag: object, commit_label: str, needle: str
) -> None:
    _write_build_files(tmp_path, monkeypatch, explorer=_commit("explorer"))
    mutated = copy.deepcopy(BOM)
    mutated["vrc_explorer"]["tag"] = tag
    mutated["vrc_explorer"]["commit"] = _commit(commit_label)
    errors = bom_manifest.validate(mutated)
    assert any(needle in error for error in errors), errors


IMAGE_KEYS = ("builder_go", "builder_python") + tuple(
    f"base.{arch}" for arch in bom_manifest.BUILD_BASE_IMAGES
)


def _image_entry(bom: dict, key: str) -> dict:
    if key.startswith("base."):
        return bom["images"]["base"][key.split(".", 1)[1]]
    return bom["images"][key]


def _track_every_workflow_base(bom: dict) -> None:
    """Add the base images the build workflow publishes beyond the declared ones."""
    for arch, ref in bom_manifest.WORKFLOW_ONLY_BASE_IMAGES.items():
        bom["images"]["base"][arch] = {"ref": ref, "observed_digest": "sha256:" + _hex(f"observed {arch}")}


def _frozen(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    skip_reference: str = "",
) -> dict:
    """A synthetic frozen BOM over the unmodified build matrix, every image by digest."""
    digests = {key: "sha256:" + _hex(f"pinned {key}") for key in IMAGE_KEYS}
    commit = _commit("frozen explorer")
    _write_build_files(
        tmp_path,
        monkeypatch,
        explorer=commit,
        image_digests={key: value for key, value in digests.items() if key != skip_reference},
    )
    bom = copy.deepcopy(BOM)
    _track_every_workflow_base(bom)
    bom["vrc_explorer"]["tag"] = None
    bom["vrc_explorer"]["commit"] = commit
    for key, digest in digests.items():
        _image_entry(bom, key)["pinned_digest"] = digest
    bom["semantic_contract"]["element_catalog"] = {"path": CATALOG_PATH, "sha256": _hex("frozen catalog")}
    bom["freeze"]["status"] = "frozen"
    return bom


def test_frozen_check_passes_for_a_synthetic_frozen_bom(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bom = _frozen(tmp_path, monkeypatch)
    # The build matrix keeps every architecture the workflow publishes.
    workflow = bom_manifest.WORKFLOW.read_text(encoding="utf-8")
    for ref in bom_manifest.BUILD_BASE_IMAGES.values():
        assert f"base: {ref}@" in workflow
    assert set(bom_manifest.workflow_bases(workflow)) == set(bom_manifest.BUILD_BASE_IMAGES.values())
    assert bom_manifest.validate(bom) == []
    assert bom_manifest.validate(bom, frozen=True) == []


def test_build_base_images_are_the_build_workflow_matrix() -> None:
    workflow = SOURCE_WORKFLOW.read_text(encoding="utf-8")
    assert set(bom_manifest.workflow_bases(workflow)) == set(bom_manifest.BUILD_BASE_IMAGES.values())
    assert set(bom_manifest.BASE_IMAGES) <= set(bom_manifest.BUILD_BASE_IMAGES)


def test_plain_check_accepts_an_unfrozen_bom_tracking_every_workflow_base() -> None:
    mutated = copy.deepcopy(BOM)
    _track_every_workflow_base(mutated)
    assert bom_manifest.validate(mutated) == []


@pytest.mark.parametrize(
    ("change", "needle"),
    (
        ("drop amd64", "images.base must list the declared add-on architectures"),
        ("add riscv64", "images.base must list the declared add-on architectures"),
        ("retag armv7", "images.base.armv7.ref differs"),
    ),
)
def test_plain_check_rejects_base_images_outside_the_build_matrix(change: str, needle: str) -> None:
    mutated = copy.deepcopy(BOM)
    _track_every_workflow_base(mutated)
    bases = mutated["images"]["base"]
    if change == "drop amd64":
        del bases["amd64"]
    elif change == "add riscv64":
        bases["riscv64"] = {"ref": "ghcr.io/home-assistant/riscv64-base:3.20", "observed_digest": "sha256:" + _hex("r")}
    else:
        bases["armv7"]["ref"] = "ghcr.io/home-assistant/armv7-base:3.19"
    errors = bom_manifest.validate(mutated)
    assert any(needle in error for error in errors), errors


def test_frozen_check_rejects_an_unfrozen_status(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    bom = _frozen(tmp_path, monkeypatch)
    bom["freeze"]["status"] = "unfrozen"
    assert bom_manifest.validate(bom) == []
    assert any("freeze.status" in error for error in bom_manifest.validate(bom, frozen=True))


def test_plain_check_applies_frozen_rules_to_a_bom_declaring_itself_frozen(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bom = _frozen(tmp_path, monkeypatch)
    bom["semantic_contract"]["element_catalog"] = None
    _image_entry(bom, IMAGE_KEYS[0])["pinned_digest"] = None
    errors = bom_manifest.validate(bom)
    assert any("element_catalog" in error for error in errors)
    assert any("pinned" in error for error in errors)


@pytest.mark.parametrize("key", IMAGE_KEYS)
def test_frozen_check_rejects_an_image_without_a_pinned_digest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, key: str
) -> None:
    bom = _frozen(tmp_path, monkeypatch, skip_reference=key)
    del _image_entry(bom, key)["pinned_digest"]
    errors = bom_manifest.validate(bom, frozen=True)
    assert any(f"images.{key}.pinned_digest" in error for error in errors), errors


@pytest.mark.parametrize("key", IMAGE_KEYS)
def test_frozen_check_rejects_a_build_reference_without_the_pinned_digest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, key: str
) -> None:
    bom = _frozen(tmp_path, monkeypatch, skip_reference=key)
    where = "build workflow" if key.startswith("base.") else "Dockerfile"
    assert bom_manifest.validate({**bom, "freeze": {**bom["freeze"], "status": "unfrozen"}}) == []
    errors = bom_manifest.validate(bom, frozen=True)
    assert any(where in error and f"images.{key}" in error for error in errors), errors


@pytest.mark.parametrize("key", IMAGE_KEYS)
def test_checker_rejects_a_build_digest_other_than_the_pinned_digest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, key: str
) -> None:
    bom = _frozen(tmp_path, monkeypatch)
    _image_entry(bom, key)["pinned_digest"] = "sha256:" + _hex(f"other {key}")
    for frozen in (False, True):
        errors = bom_manifest.validate(bom, frozen=frozen)
        assert any(f"images.{key}" in error and "pinned_digest" in error for error in errors), errors


def test_frozen_check_rejects_a_null_element_catalog(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    bom = _frozen(tmp_path, monkeypatch)
    bom["semantic_contract"]["element_catalog"] = None
    assert bom_manifest.validate({**bom, "freeze": {**bom["freeze"], "status": "unfrozen"}}) == []
    assert any("element_catalog" in error for error in bom_manifest.validate(bom, frozen=True))


def test_frozen_check_rejects_an_explorer_tag_pin(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    bom = _frozen(tmp_path, monkeypatch)
    _write_build_files(
        tmp_path,
        monkeypatch,
        explorer=BOM["vrc_explorer"]["tag"],
        image_digests={key: _image_entry(bom, key)["pinned_digest"] for key in IMAGE_KEYS},
    )
    bom["vrc_explorer"] = copy.deepcopy(BOM["vrc_explorer"])
    assert bom_manifest.validate({**bom, "freeze": {**bom["freeze"], "status": "unfrozen"}}) == []
    errors = bom_manifest.validate(bom, frozen=True)
    assert any("VRCEXPLORER_VERSION" in error and "commit" in error for error in errors), errors


def test_frozen_check_rejects_a_workflow_base_the_bom_does_not_track(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bom = _frozen(tmp_path, monkeypatch)
    untracked = bom["images"]["base"].pop("armv7")["ref"]
    assert f"base: {untracked}@" in bom_manifest.WORKFLOW.read_text(encoding="utf-8")
    assert bom_manifest.validate({**bom, "freeze": {**bom["freeze"], "status": "unfrozen"}}) == []
    errors = bom_manifest.validate(bom, frozen=True)
    assert any(untracked in error and "not covered" in error for error in errors), errors
    assert any("every build workflow architecture" in error for error in errors), errors


@pytest.mark.parametrize(
    "replace",
    (
        [f"replace {REGISTRY_MODULE} v0.0.0-20200101000000-aaaaaaaaaaaa => {REGISTRY_MODULE} v0.0.0-20210101000000-bbbbbbbbbbbb"],
        [f"replace {REGISTRY_MODULE} => {REGISTRY_MODULE} v0.0.0-20210101000000-bbbbbbbbbbbb"],
    ),
)
def test_checker_rejects_a_registry_replacement(replace: list[str]) -> None:
    mutated = copy.deepcopy(BOM)
    mutated["go_modules"]["replace"] = replace
    errors = bom_manifest.validate(mutated)
    assert any("replace" in error and REGISTRY_MODULE in error for error in errors), errors


def test_parse_go_mod_reads_replace_blocks() -> None:
    text = f"module m\n\ngo 1.22\n\nreplace (\n\t{REGISTRY_MODULE} v1 => ../x\n)\n"
    parsed = bom_manifest.parse_go_mod(text)
    assert parsed["replace"] == [f"replace {REGISTRY_MODULE} v1 => ../x"]
    assert bom_manifest.registry_replaced(parsed)


def test_generate_refuses_a_registry_replacement(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _stub_network(monkeypatch, {})
    original = bom_manifest.http_text

    def with_replace(url: str, headers=None) -> bytes:
        data = original(url, headers)
        if "/go.mod" in url:
            data += f"\nreplace {REGISTRY_MODULE} v1 => {REGISTRY_MODULE} v2\n".encode()
        return data

    monkeypatch.setattr(bom_manifest, "http_text", with_replace)
    code, out, stdout = _run_generate(tmp_path, monkeypatch, capsys)
    assert code == 1
    assert not out.exists()
    assert "replaces" in stdout


def test_frozen_check_cli_reports_the_committed_bom_as_unfrozen() -> None:
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts/bom_manifest.py"), "check", "--frozen"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 1, result.stdout
    assert "BOM check --frozen: FAIL" in result.stdout
    assert "freeze.status must be frozen" in result.stdout
    assert "element_catalog" in result.stdout


# --- generate with stubbed network access ----------------------------------

REGISTRY_COMMIT = _commit("registry")
REGISTRY_VERSION = "v0.0.0-20260101000000-" + REGISTRY_COMMIT[:12]
CATALOG_BYTES = b'{"contract": "synthetic element catalog"}\n'


def _graph_source(digest: str) -> bytes:
    return (
        "package graph\n\n"
        f"// PinnedDigest is the SHA-256 of {CATALOG_PATH}, the\n"
        "// byte copy of the accepted catalog. Load accepts no other bytes.\n"
        f'const PinnedDigest semreg.Digest = "sha256:{digest}"\n'
    ).encode("utf-8")


FIXTURES_README = (
    b"# Fixtures\n\n[`v1/element-catalog-v1.json`](v1/element-catalog-v1.json) is a\n"
    b"byte-for-byte copy of `api/v1/element-catalog-v1.json` from\n"
    b"`Project-Helianthus/helianthus-docs-semantic`, as accepted.\n"
)


def _stub_network(monkeypatch: pytest.MonkeyPatch, files: dict[str, bytes | None]) -> list[tuple[str, str]]:
    gateway = BOM["gateway"]["commit"]
    tag = BOM["vrc_explorer"]["tag"]
    go_mod = (
        "module github.com/Project-Helianthus/helianthus-ebusgateway\n\ngo 1.22.0\n\n"
        f"require (\n\t{REGISTRY_MODULE} {REGISTRY_VERSION}\n)\n"
    ).encode("utf-8")
    api = {
        f"/repos/{bom_manifest.GATEWAY_REPO}/git/commits/{gateway}": {"tree": {"sha": _commit("tree")}},
        f"/repos/{bom_manifest.VRC_REPO}/git/ref/tags/{tag}": {
            "object": {"type": "commit", "sha": _commit("explorer")}
        },
        f"/repos/{bom_manifest.REGISTRY_REPO}/commits/{REGISTRY_COMMIT[:12]}": {"sha": REGISTRY_COMMIT},
    }
    monkeypatch.setattr(bom_manifest, "gh_api", lambda path: api[path])
    monkeypatch.setattr(
        bom_manifest,
        "http_text",
        lambda url, headers=None: go_mod if "/go.mod" in url else b"synthetic go.sum\n",
    )
    monkeypatch.setattr(bom_manifest, "registry_digest", lambda ref: "sha256:" + _hex(ref))
    fetched: list[tuple[str, str]] = []

    def fetch(commit: str, path: str) -> bytes | None:
        fetched.append((commit, path))
        return files.get(path)

    monkeypatch.setattr(bom_manifest, "registry_file", fetch)
    return fetched


def _run_generate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> tuple[int, Path, str]:
    help_path = tmp_path / "help.txt"
    help_path.write_text("  -address string\n  -transport string\n", encoding="utf-8")
    out = tmp_path / "bom.json"
    monkeypatch.setattr(
        sys, "argv", ["bom_manifest.py", "generate", "--gateway-help", str(help_path), "--out", str(out)]
    )
    code = bom_manifest.main()
    return code, out, capsys.readouterr().out


def test_generate_records_the_digest_computed_from_the_fetched_catalog(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    computed = hashlib.sha256(CATALOG_BYTES).hexdigest()
    fetched = _stub_network(
        monkeypatch,
        {
            bom_manifest.REGISTRY_PIN_FILE: _graph_source(computed),
            CATALOG_PATH: CATALOG_BYTES,
            bom_manifest.REGISTRY_FIXTURES_README: FIXTURES_README,
        },
    )
    code, out, _ = _run_generate(tmp_path, monkeypatch, capsys)
    assert code == 0
    section = json.loads(out.read_text(encoding="utf-8"))["semantic_contract"]
    assert section == {
        "registry_module": REGISTRY_MODULE,
        "registry_version": REGISTRY_VERSION,
        "element_catalog": {
            "path": CATALOG_PATH,
            "sha256": computed,
            "source": {
                "repository": "https://github.com/Project-Helianthus/helianthus-docs-semantic",
                "path": "api/v1/element-catalog-v1.json",
            },
        },
    }
    # Every registry file is read at the full commit the version names.
    assert fetched and {commit for commit, _ in fetched} == {REGISTRY_COMMIT}


def test_generate_records_a_base_image_for_every_build_workflow_architecture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _stub_network(monkeypatch, {})
    code, out, _ = _run_generate(tmp_path, monkeypatch, capsys)
    assert code == 0
    bases = json.loads(out.read_text(encoding="utf-8"))["images"]["base"]
    assert {arch: entry["ref"] for arch, entry in bases.items()} == bom_manifest.BUILD_BASE_IMAGES


def test_generate_records_a_null_catalog_for_a_registry_without_the_copy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _stub_network(monkeypatch, {})
    code, out, _ = _run_generate(tmp_path, monkeypatch, capsys)
    assert code == 0
    section = json.loads(out.read_text(encoding="utf-8"))["semantic_contract"]
    assert section["registry_version"] == REGISTRY_VERSION
    assert section["element_catalog"] is None


def test_generate_refuses_a_catalog_whose_digest_differs_from_the_registry_pin(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _stub_network(
        monkeypatch,
        {
            bom_manifest.REGISTRY_PIN_FILE: _graph_source(_hex("declared elsewhere")),
            CATALOG_PATH: CATALOG_BYTES,
        },
    )
    code, out, stdout = _run_generate(tmp_path, monkeypatch, capsys)
    assert code == 1
    assert not out.exists()
    assert "BOM generate: FAIL" in stdout
    assert "differs from the digest the registry declares" in stdout


def test_generate_refuses_a_declared_catalog_that_is_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _stub_network(monkeypatch, {bom_manifest.REGISTRY_PIN_FILE: _graph_source(_hex("declared"))})
    code, out, stdout = _run_generate(tmp_path, monkeypatch, capsys)
    assert code == 1
    assert not out.exists()
    assert "BOM generate: FAIL" in stdout


@pytest.mark.parametrize(
    ("version", "ref"),
    (
        ("v0.0.0-20260101000000-" + _commit("a")[:12], _commit("a")[:12]),
        ("v1.2.4-0.20260101000000-" + _commit("b")[:12], _commit("b")[:12]),
        ("v1.2.3-rc.1.0.20260101000000-" + _commit("c")[:12], _commit("c")[:12]),
        ("v1.2.3", "v1.2.3"),
        ("v2.0.0+incompatible", "v2.0.0"),
    ),
)
def test_module_version_ref_names_the_registry_revision(version: str, ref: str) -> None:
    assert bom_manifest.module_version_ref(version) == ref
