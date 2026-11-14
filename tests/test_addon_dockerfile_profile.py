"""The add-on image builds its gateway with the profile that leaves out Matter."""

from __future__ import annotations

import re
import shlex
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DOCKERFILE = ROOT / "helianthus/Dockerfile"
PROFILE_TAG = "nomatter"


def builder_stage(text: str) -> str:
    match = re.search(r"^FROM [^\n]* AS builder\n(.*?)(?=^FROM )", text, re.M | re.S)
    assert match, "the Dockerfile has no gateway builder stage"
    return match.group(1)


def go_build_commands(text: str) -> list[list[str]]:
    joined = re.sub(r"\\\n", " ", builder_stage(text))
    commands = []
    for statement in re.split(r";|&&", joined):
        words = shlex.split(statement, posix=True)
        for index in range(len(words) - 1):
            if words[index] == "go" and words[index + 1] == "build":
                commands.append(words[index + 2:])
    return commands


def build_tags(arguments: list[str]) -> list[str]:
    tags: list[str] = []
    for index, word in enumerate(arguments):
        if word == "-tags" and index + 1 < len(arguments):
            tags.append(arguments[index + 1])
        elif word.startswith("-tags="):
            tags.append(word.split("=", 1)[1])
    return tags


def gateway_build(text: str) -> list[str]:
    commands = [arguments for arguments in go_build_commands(text) if arguments[-1:] == ["./cmd/gateway"]]
    assert len(commands) == 1, "the builder stage must build the gateway exactly once"
    return commands[0]


def test_the_gateway_build_uses_the_profile_without_matter() -> None:
    arguments = gateway_build(DOCKERFILE.read_text(encoding="utf-8"))
    assert build_tags(arguments) == [PROFILE_TAG]
    assert arguments[arguments.index("-o") + 1] == "/out/gateway"


@pytest.mark.parametrize(
    ("replacement", "reason"),
    (
        ("go build -trimpath -buildvcs=true \\", "no build profile"),
        ("go build -trimpath -buildvcs=true -tags matter \\", "another profile"),
        ("go build -trimpath -buildvcs=true -tags nomatter,extra \\", "a widened profile"),
        ("go build -trimpath -buildvcs=true -tags nomatter -tags nomatter \\", "a repeated profile"),
    ),
)
def test_a_gateway_build_without_exactly_the_profile_is_refused(replacement: str, reason: str) -> None:
    text = DOCKERFILE.read_text(encoding="utf-8")
    mutated, count = re.subn(r"go build -trimpath -buildvcs=true[^\n]*\\", lambda _: replacement, text)
    assert count == 1
    assert build_tags(gateway_build(mutated)) != [PROFILE_TAG], reason
