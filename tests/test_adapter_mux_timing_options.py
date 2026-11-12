"""Adapter-mux timing options: schema, defaults, argv mapping and BOM flags.

Synthetic only: the real wrapper runs against stubbed bashio functions and a
recording gateway substitute whose help output is the pinned BOM flag set
(the Portal Ingress harness). No Supervisor, network or device is involved.

Identity of each option: option key, gateway flag and default value.
- Option key: each option is varied alone with a distinct value; reading
  another option, or swapping two reads, fails the exact argv comparison.
- Gateway flag: the exact argv pairs catch a renamed, swapped or dropped flag,
  and the option map / README / BOM checks catch a flag outside the packaged CLI.
- Default: config, README, translations and the gateway default per flag must
  agree; the default argv catches a changed or derived default.
The read_timeout distinction is varied in both directions, so aliasing or
deriving one value from the other is caught.
"""

from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "helianthus/config.json"
BOM = ROOT / "helianthus/bom.json"
RUN = ROOT / "helianthus/rootfs/etc/services.d/helianthus-gateway/run"
README = ROOT / "helianthus/README.md"
TRANSLATIONS = ROOT / "helianthus/translations/en.yaml"
OPTION_MAP = ROOT / "scripts/addon-option-map.json"
ADAPTER = "adapter.example.invalid:9999"

# option -> (gateway flag, documented gateway default)
OPTIONS = {
    "adapter_mux_idle_release_grace": ("adapter-mux-idle-release-grace", "200ms"),
    "adapter_mux_max_ownership_duration": ("adapter-mux-max-ownership-duration", "10s"),
    "adapter_mux_read_timeout": ("adapter-mux-read-timeout", "50ms"),
}
# Distinct, valid, non-default values: one per option, none equal to another.
CHANGED = {
    "adapter_mux_idle_release_grace": "350ms",
    "adapter_mux_max_ownership_duration": "45s",
    "adapter_mux_read_timeout": "75ms",
}
NON_POSITIVE_OR_MALFORMED = ("0ms", "0s", "00ms", "-1s", "-50ms", "", "0", "50", "1.5s",
                             "50us", "1m", "+5s", " 50ms", "50ms ", "50MS", "5 s")


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


HARNESS = _load("adapter_mux_portal_harness", ROOT / "tests/test_portal_ingress_wiring.py")
BOM_MANIFEST = _load("adapter_mux_bom_manifest", ROOT / "scripts/bom_manifest.py")


def _config() -> dict:
    return json.loads(CONFIG.read_text(encoding="utf-8"))


def _schema_admits(pattern: str, value: str) -> bool:
    match = re.fullmatch(r"match\((?P<regex>.*)\)", pattern)
    assert match, pattern
    return re.fullmatch(match.group("regex"), value) is not None


def _pairs(argv: list[str]) -> dict[str, list[str]]:
    found: dict[str, list[str]] = {}
    for flag, _default in OPTIONS.values():
        indexes = [i for i, arg in enumerate(argv) if arg == "-" + flag]
        found[flag] = [argv[i + 1] for i in indexes]
    return found


def _launch(tmp_path: Path, overrides: dict, hidden: tuple[str, ...] = ()) -> dict:
    tmp_path.mkdir(parents=True, exist_ok=True)
    return HARNESS._run(tmp_path, {"adapter_direct_address": ADAPTER} | overrides, hidden)


def test_config_declares_exactly_the_three_options_with_gateway_defaults() -> None:
    config = _config()
    assert {k for k in config["options"] if k.startswith("adapter_mux_")} == set(OPTIONS)
    assert {k for k in config["schema"] if k.startswith("adapter_mux_")} == set(OPTIONS)
    for option, (_flag, default) in OPTIONS.items():
        assert config["options"][option] == default
        # Same positive duration-string pattern as the endpoint dial timeout.
        assert config["schema"][option] == config["schema"]["modbus_tcp_endpoints"][0]["dial_timeout"].rstrip("?")
    # The generic read timeout keeps its own default and type.
    assert config["options"]["read_timeout"] == "5s"
    assert config["schema"]["read_timeout"] == "str"


@pytest.mark.parametrize("option", sorted(OPTIONS))
@pytest.mark.parametrize("value", NON_POSITIVE_OR_MALFORMED)
def test_schema_rejects_non_positive_and_malformed_values(option: str, value: str) -> None:
    assert not _schema_admits(_config()["schema"][option], value)


@pytest.mark.parametrize("option", sorted(OPTIONS))
@pytest.mark.parametrize("value", ("1ms", "50ms", "200ms", "1s", "10s", "9999ms"))
def test_schema_admits_positive_whole_durations(option: str, value: str) -> None:
    assert _schema_admits(_config()["schema"][option], value)


def test_defaults_reach_the_gateway_as_documented_defaults(tmp_path: Path) -> None:
    run = _launch(tmp_path, {})

    assert run["result"].returncode == 0, run["result"].stderr
    assert len(run["runtime"]) == 1
    argv = run["runtime"][0]
    assert _pairs(argv) == {flag: [default] for flag, default in OPTIONS.values()}
    assert argv[argv.index("-read-timeout") + 1] == "5s"
    policy = argv.index("-external-write-policy")
    assert argv[policy + 2: policy + 8] == [
        "-adapter-mux-idle-release-grace", "200ms",
        "-adapter-mux-max-ownership-duration", "10s",
        "-adapter-mux-read-timeout", "50ms",
    ]
    assert "does not support -adapter-mux" not in run["log"]


@pytest.mark.parametrize("option", sorted(OPTIONS))
def test_each_option_maps_only_to_its_own_flag(tmp_path: Path, option: str) -> None:
    run = _launch(tmp_path, {option: CHANGED[option]})

    assert run["result"].returncode == 0, run["result"].stderr
    expected = {flag: [default] for flag, default in OPTIONS.values()}
    expected[OPTIONS[option][0]] = [CHANGED[option]]
    assert _pairs(run["runtime"][0]) == expected


def test_all_options_changed_together_keep_their_own_flags(tmp_path: Path) -> None:
    run = _launch(tmp_path, dict(CHANGED))

    assert run["result"].returncode == 0, run["result"].stderr
    assert _pairs(run["runtime"][0]) == {OPTIONS[o][0]: [CHANGED[o]] for o in OPTIONS}


def test_read_timeout_is_not_reused_aliased_or_derived(tmp_path: Path) -> None:
    generic = _launch(tmp_path / "generic", {"read_timeout": "7s"})
    mux = _launch(tmp_path / "mux", {"adapter_mux_read_timeout": "75ms"})

    for run in (generic, mux):
        assert run["result"].returncode == 0, run["result"].stderr
    generic_argv, mux_argv = generic["runtime"][0], mux["runtime"][0]
    assert generic_argv[generic_argv.index("-read-timeout") + 1] == "7s"
    assert generic_argv[generic_argv.index("-adapter-mux-read-timeout") + 1] == "50ms"
    assert mux_argv[mux_argv.index("-read-timeout") + 1] == "5s"
    assert mux_argv[mux_argv.index("-adapter-mux-read-timeout") + 1] == "75ms"


@pytest.mark.parametrize("option", sorted(OPTIONS))
@pytest.mark.parametrize("value", ("0ms", "0s", "-1s", "", "1.5s", "50us"))
def test_wrapper_refuses_a_non_positive_value_before_launch(tmp_path: Path, option: str, value: str) -> None:
    # Bypasses the Supervisor schema to prove the wrapper also fails closed.
    run = _launch(tmp_path, {option: value})

    assert run["result"].returncode != 0
    assert run["runtime"] == []
    assert f"NOK: {option} must be a positive duration in whole ms or s" in run["result"].stderr


@pytest.mark.parametrize("option", sorted(OPTIONS))
def test_gateway_without_the_flag_starts_only_at_the_default(tmp_path: Path, option: str) -> None:
    flag, default = OPTIONS[option]
    kept = _launch(tmp_path / "kept", {}, hidden=(flag,))
    changed = _launch(tmp_path / "changed", {option: CHANGED[option]}, hidden=(flag,))

    assert kept["result"].returncode == 0, kept["result"].stderr
    pairs = _pairs(kept["runtime"][0])
    assert pairs.pop(flag) == []
    assert pairs == {other: [value] for other, value in OPTIONS.values() if other != flag}
    assert f"does not support -{flag}; {option} keeps its default {default}" in kept["log"]

    assert changed["result"].returncode != 0
    assert changed["runtime"] == []
    assert f"NOK: {option}={CHANGED[option]} requires gateway support for -{flag}" in changed["result"].stderr


def test_bom_flag_list_contains_the_three_flags_and_covers_the_wrapper() -> None:
    flags = json.loads(BOM.read_text(encoding="utf-8"))["gateway_cli_flags"]
    assert flags == sorted(set(flags))
    for flag, _default in OPTIONS.values():
        assert flag in flags
    # The BOM check accepts every flag the wrapper emits or probes.
    mentioned = BOM_MANIFEST.gateway_flag_mentions(RUN.read_text(encoding="utf-8"))
    assert {flag for flag, _default in OPTIONS.values()} <= mentioned
    assert mentioned <= set(flags)


def test_option_map_translations_and_readme_document_each_option() -> None:
    mapping = json.loads(OPTION_MAP.read_text(encoding="utf-8"))["options"]
    translations = yaml.safe_load(TRANSLATIONS.read_text(encoding="utf-8"))["configuration"]
    readme = README.read_text(encoding="utf-8")
    configuration = readme.split("## Configuration\n", 1)[1].split("\n## ", 1)[0]
    for option, (flag, default) in OPTIONS.items():
        assert mapping[option]["flags"] == [flag]
        assert mapping[option]["kind"] == "gateway"
        assert f"Default {default}." in translations[option]["description"]
        assert f"-{flag}" in translations[option]["description"]
        assert f"| `{option}` | `-{flag}` | `ms` or `s` | `{default}` |" in configuration
    assert "must be positive" in configuration
    assert "`adapter_mux_read_timeout` is separate from `read_timeout`" in configuration
    assert "`-read-timeout` flag (default `5s`)" in configuration
    assert "`50ms` is the effective adapter-mux read timeout default" in configuration


# Settings removed from the gateway, and fixed internal limits, must not become
# add-on options, schema entries, translations, documentation or argv.
FORBIDDEN = re.compile(
    r"stale(?:ness)?[_ -]?budget|fairness|post[_ -]?external[_ -]?release|pending[_ -]?start"
    r"|start[_ -]?deadline|ownership[_ -]?guard|external[_ -]?start",
    re.IGNORECASE,
)


@pytest.mark.parametrize("path", (CONFIG, RUN, README, TRANSLATIONS, OPTION_MAP),
                         ids=lambda path: path.name)
def test_removed_settings_and_fixed_limits_do_not_appear(path: Path) -> None:
    assert FORBIDDEN.findall(path.read_text(encoding="utf-8")) == []


def test_runtime_argv_carries_no_removed_setting(tmp_path: Path) -> None:
    run = _launch(tmp_path, {})

    assert run["result"].returncode == 0, run["result"].stderr
    assert [arg for arg in run["runtime"][0] if FORBIDDEN.search(arg)] == []
    assert [arg for arg in run["runtime"][0] if arg.startswith("-adapter-mux-")] == [
        "-" + flag for flag, _default in OPTIONS.values()
    ]
