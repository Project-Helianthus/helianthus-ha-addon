"""BOM manifest and wrapper-versus-gateway-flag contract tests."""

from __future__ import annotations

import copy
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


def test_listener_client_ca_is_supported_but_denied_principals_is_removed() -> None:
    used = bom_manifest.gateway_flag_mentions(
        bom_manifest.WRAPPER.read_text(encoding="utf-8")
    )
    # The client CA is a conditional flag: the wrapper emits it only when the
    # optional CA file is present (runtime tests cover both outcomes).
    assert "m2m-graphql-client-ca" in BOM["gateway_cli_flags"]
    assert "m2m-graphql-client-ca" in used
    assert "m2m-graphql-denied-principals" not in BOM["gateway_cli_flags"]
    assert "m2m-graphql-denied-principals" not in used


def test_wrapper_flags_are_all_defined_by_pinned_gateway() -> None:
    wrapper = bom_manifest.WRAPPER.read_text(encoding="utf-8")
    used = bom_manifest.gateway_flag_mentions(wrapper)
    assert used, "no gateway flags detected in the wrapper"
    assert used <= set(BOM["gateway_cli_flags"])


@pytest.mark.parametrize("flag", ("m2m-graphql-allowed-assets", "m2m-graphql-client-ca"))
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


def test_wrapper_scan_flags_denied_principals_and_accepts_conditional_client_ca() -> None:
    wrapper = bom_manifest.WRAPPER.read_text(encoding="utf-8")
    assert "m2m-graphql-client-ca" in bom_manifest.gateway_flag_mentions(wrapper)
    injected = wrapper + '\n-m2m-graphql-denied-principals "x"\n'
    used = bom_manifest.gateway_flag_mentions(injected)
    assert "m2m-graphql-denied-principals" in used
    assert not used <= set(BOM["gateway_cli_flags"])
