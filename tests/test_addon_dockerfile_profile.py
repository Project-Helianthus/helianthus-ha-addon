"""The add-on image builds its gateway with the profile that leaves out Matter.

The builder's `GATEWAY_TAGS` default selects the profile. The profile switch and
the gateway `go build` of the builder stage run under `sh` with a recording `go`
substitute, so the test checks the tags the committed default really produces.
"""

from __future__ import annotations

import re
import shlex
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DOCKERFILE = ROOT / "helianthus/Dockerfile"
PROFILE_TAG = "nomatter"
GO_STUB = 'go() { for word in "$@"; do printf "%s\\n" "${word}"; done; }\n'


def builder_stage(text: str) -> str:
    match = re.search(r"^FROM [^\n]* AS builder\n(.*?)(?=^FROM )", text, re.M | re.S)
    assert match, "the Dockerfile has no gateway builder stage"
    return match.group(1)


def arg_default(text: str) -> str:
    defaults = re.findall(r"^ARG GATEWAY_TAGS=(\S*)$", builder_stage(text), re.M)
    assert len(defaults) == 1, "the builder must declare GATEWAY_TAGS with a default exactly once"
    return defaults[0]


def profile_switch(text: str) -> str:
    joined = re.sub(r"\\\n", " ", builder_stage(text))
    switches = re.findall(r'case "\$\{GATEWAY_TAGS\}" in .*? esac;', joined)
    assert len(switches) == 1, "the builder must select the profile exactly once"
    return switches[0]


def gateway_build_statement(text: str) -> str:
    joined = re.sub(r"\\\n", " ", builder_stage(text))
    statements = [
        statement for statement in re.split(r";|&&", joined)
        if re.search(r"(^|\s)go build(\s|$)", statement) and statement.rstrip().endswith("./cmd/gateway")
    ]
    assert len(statements) == 1, "the builder stage must build the gateway exactly once"
    return statements[0]


def build_tags(arguments: list[str]) -> list[str]:
    tags: list[str] = []
    for index, word in enumerate(arguments):
        if word == "-tags" and index + 1 < len(arguments):
            tags.append(arguments[index + 1])
        elif word.startswith("-tags="):
            tags.append(word.split("=", 1)[1])
    return tags


def gateway_build(text: str, gateway_tags: str | None = None) -> subprocess.CompletedProcess[str]:
    """Run the profile switch and the gateway build with `go` recorded."""
    value = arg_default(text) if gateway_tags is None else gateway_tags
    script = "\n".join((
        "set -eu",
        f"GATEWAY_TAGS={shlex.quote(value)}",
        "BUILD_VERSION=test EBUSGATEWAY_VERSION=test",
        GO_STUB,
        profile_switch(text),
        gateway_build_statement(text),
    ))
    return subprocess.run(["sh", "-c", script], capture_output=True, text=True, check=False, timeout=30)


def committed_arguments(text: str) -> list[str]:
    result = gateway_build(text)
    assert result.returncode == 0, result.stderr
    arguments = result.stdout.splitlines()
    assert arguments[0] == "build"
    return arguments[1:]


def test_the_gateway_build_uses_the_profile_without_matter() -> None:
    text = DOCKERFILE.read_text(encoding="utf-8")
    assert arg_default(text) == PROFILE_TAG
    arguments = committed_arguments(text)
    assert build_tags(arguments) == [PROFILE_TAG]
    assert arguments[arguments.index("-o") + 1] == "/out/gateway"
    assert arguments[-1] == "./cmd/gateway"


def test_only_default_builds_without_tags() -> None:
    result = gateway_build(DOCKERFILE.read_text(encoding="utf-8"), "default")
    assert result.returncode == 0, result.stderr
    arguments = result.stdout.splitlines()[1:]
    assert build_tags(arguments) == []
    assert arguments[-1] == "./cmd/gateway"


@pytest.mark.parametrize("value", ["", "matter", "nomatter,extra", " nomatter", "Default", "nomatter default"])
def test_any_other_profile_value_fails_the_build(value: str) -> None:
    result = gateway_build(DOCKERFILE.read_text(encoding="utf-8"), value)
    assert result.returncode != 0
    assert result.stdout == ""
    assert "GATEWAY_TAGS must be nomatter or default" in result.stderr


@pytest.mark.parametrize(
    ("default", "reason"),
    (("default", "the default profile"), ("matter", "another profile"), ("nomatter,extra", "a widened profile"),
     ("", "an empty default")),
)
def test_a_builder_whose_default_is_not_exactly_the_profile_is_refused(default: str, reason: str) -> None:
    text = DOCKERFILE.read_text(encoding="utf-8")
    mutated, count = re.subn(r"^ARG GATEWAY_TAGS=\S*$", f"ARG GATEWAY_TAGS={default}", text, flags=re.M)
    assert count == 1
    assert arg_default(mutated) != PROFILE_TAG, reason
    result = gateway_build(mutated)
    assert result.returncode != 0 or build_tags(result.stdout.splitlines()[1:]) != [PROFILE_TAG], reason


@pytest.mark.parametrize(
    ("replacement", "reason"),
    (
        ("go build -trimpath -buildvcs=true \\", "no build profile"),
        ("go build -trimpath -buildvcs=true -tags matter \\", "another profile"),
        ("go build -trimpath -buildvcs=true -tags nomatter,extra \\", "a widened profile"),
        ("go build -trimpath -buildvcs=true ${gateway_tags_args} -tags nomatter \\", "a repeated profile"),
    ),
)
def test_a_gateway_build_without_exactly_the_profile_is_refused(replacement: str, reason: str) -> None:
    text = DOCKERFILE.read_text(encoding="utf-8")
    mutated, count = re.subn(r"go build -trimpath -buildvcs=true[^\n]*\\", lambda _: replacement, text)
    assert count == 1
    assert build_tags(committed_arguments(mutated)) != [PROFILE_TAG], reason


@pytest.mark.parametrize(
    ("old", "new", "reason"),
    (
        ('nomatter) gateway_tags_args="-tags nomatter" ;;', 'nomatter) gateway_tags_args="" ;;', "profile dropped"),
        ('nomatter) gateway_tags_args="-tags nomatter" ;;', 'nomatter) gateway_tags_args="-tags matter" ;;',
         "profile swapped"),
    ),
)
def test_a_switch_that_maps_the_default_elsewhere_is_refused(old: str, new: str, reason: str) -> None:
    text = DOCKERFILE.read_text(encoding="utf-8")
    assert text.count(old) == 1
    assert build_tags(committed_arguments(text.replace(old, new))) != [PROFILE_TAG], reason
