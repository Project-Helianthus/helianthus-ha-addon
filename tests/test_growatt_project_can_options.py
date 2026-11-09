"""Synthetic packaging admission only; physical_qualified=false throughout."""
from __future__ import annotations

import copy
import itertools
import json
import shlex
import subprocess
from pathlib import Path

import pytest

from test_serial_can_options import (
    BOM, CAN_IDENTITY, CONFIG_JSON, GROWATT_IDENTITY, HELPER, ROOT, RUN, TESLA_IDENTITY,
    _wrapper_harness, options_with_defaults, run_helper, serial_can_options,
)

COMMON = ("enabled", "interface", "listen_only_confirmed", "stale_after", "project_code",
          "release", "native_profile", "scope", "bank", "context")
EXTRAS = {"pcs": "native_contract", "link": "source_selectors"}


def context(source: int = 1) -> dict:
    gate = {"configured": True, "valid": True, "status": "", "age": "0s"}
    return {
        "source": source, "interface_index": 7, "destination": 244,
        "endpoint": "synthetic", "group": "group", "slot": "slot", "epoch": 1,
        "serial_slot": 1, "serial_slot_valid": True, "native_slot": 1, "native_group": 1,
        "slot_valid": True, "group_valid": True, "publisher_resolved": True,
        "measurement_valid": True, "temperature_valid": True, "topology_associated": True,
        "field_age": "0s",
        "cells": {"count": 8, "count_valid": True, "gates": [dict(gate) for _ in range(4)]},
        "sensors": {"count": 4, "count_valid": True, "gates": [dict(gate) for _ in range(4)]},
    }


def selection(source: int = 1, *, defaults: bool = False) -> dict:
    return {"source": source, **({"use_default": True} if defaults else
            {"project_code": "QAAA", "release": "0011"}), "contract": "release11"}


def family_options(family: str, **overrides) -> dict:
    values = {"enabled": True, "interface": "synthetic1" if family == "pcs" else "synthetic2",
              "listen_only_confirmed": True, "stale_after": "2s", "project_code": "QAAA",
              "release": "0011", "native_profile": "standard", "scope": "local",
              "bank": "ordinary", "context": json.dumps([context()])}
    values.update({"native_contract": "release11"} if family == "pcs" else
                  {"source_selectors": json.dumps([selection(defaults=True)])})
    values.update(overrides)
    return {f"growatt_bms_{family}_can_{key}": value for key, value in values.items()}


def startup(tmp_path: Path, options: dict, hidden: tuple = ()) -> subprocess.CompletedProcess:
    """Execute the actual serial validation/support block, followed by a mock launch."""
    path = tmp_path / "options.json"
    path.write_text(json.dumps(options), encoding="utf-8")
    flags = set(json.loads(BOM.read_text())["gateway_cli_flags"]) - set(hidden)
    help_text = "\n".join("  -" + flag + " string" for flag in sorted(flags))
    run = RUN.read_text()
    probe = run[run.index("binary_supports_flag() {"):run.index("# The wrapper creates an identity")]
    block = run[run.index("# Serial acquisition options"):run.index("# Gate `-instance-guid-source`")]
    script = "set -euo pipefail\n" + probe
    script += "bashio::exit.nok() { printf '%s\\n' \"$*\" >&2; exit 1; }\n"
    script += "bashio::log.info() { :; }\n"
    script += "fake_gateway() { if [ \"$1\" = --help ]; then printf '%s\\n' " + shlex.quote(help_text)
    script += "; else printf 'LAUNCHED\\n'; fi; }\n"
    script += "gateway_bin=fake_gateway\naddon_options_path=" + shlex.quote(str(path)) + "\n"
    script += "HELIANTHUS_SERIAL_CAN_GUARD=" + shlex.quote(str(HELPER)) + "\n"
    script += block + '\nmock_args=("@mock-launch")\n'
    script += 'if [ "' + '$' + '{#SERIAL_CAN_ARGS[@]}" -ne 0 ]; then mock_args+=("' + '$' + '{SERIAL_CAN_ARGS[@]}"); fi\n'
    script += '"$gateway_bin" "' + '$' + '{mock_args[@]}"\n'
    return subprocess.run(["bash", "-c", script], capture_output=True, text=True, timeout=10)


def assert_refused(tmp_path: Path, options: dict) -> None:
    snapshot = copy.deepcopy(options)
    result = startup(tmp_path, options)
    assert result.returncode == 1, result.stderr
    assert result.stdout == ""  # no partial argv or process startup
    assert options == snapshot
    assert json.loads((tmp_path / "options.json").read_text()) == snapshot  # retained source options


def test_project_schema_defaults_match_the_cli_inventory_and_are_inert() -> None:
    expected = {f"growatt_bms_{family}_can_{suffix}"
                for family, extra in EXTRAS.items() for suffix in (*COMMON, extra)}
    for section in ("options", "schema"):
        assert {key for key in CONFIG_JSON[section] if key.startswith(
            ("growatt_bms_pcs_can_", "growatt_bms_link_can_"))} == expected
    assert {flag.replace("-", "_") for flag in serial_can_options.project_flags()} == expected
    assert serial_can_options.project_flags() <= set(json.loads(BOM.read_text())["gateway_cli_flags"])
    for key in expected:
        boolean = key.endswith(("_enabled", "_listen_only_confirmed"))
        assert CONFIG_JSON["options"][key] == (False if boolean else "")
        assert CONFIG_JSON["schema"][key] == ("bool?" if boolean else "str?")
    assert serial_can_options.build_args(CONFIG_JSON["options"]) == []
    stale = {**family_options("pcs"), **family_options("link")}
    for family in EXTRAS:
        stale[f"growatt_bms_{family}_can_enabled"] = False
        stale[f"growatt_bms_{family}_can_context"] = "malformed"
        stale[f"growatt_bms_{family}_can_stale_after"] = "2s"
    assert serial_can_options.build_args(stale) == []


@pytest.mark.parametrize("family", EXTRAS)
def test_every_project_option_reaches_its_exact_flag_verbatim(family: str) -> None:
    options = family_options(family)
    argv = serial_can_options.build_args(options)
    expected = []
    for suffix in (*COMMON, EXTRAS[family]):
        value = options[f"growatt_bms_{family}_can_{suffix}"]
        flag = f"-growatt-bms-{family}-can-" + suffix.replace("_", "-")
        expected.extend([flag + "=true"] if type(value) is bool else [flag, value])
    assert argv == expected
    assert not any(word in arg for arg in argv for word in ("bitrate", "transmit", "probe"))


@pytest.mark.parametrize("families", [(), ("pcs",), ("link",), ("pcs", "link")])
def test_independent_families_with_existing_serial_and_can_options(tmp_path: Path, families: tuple) -> None:
    options = {**GROWATT_IDENTITY, **TESLA_IDENTITY, **CAN_IDENTITY}
    for family in families:
        options.update(family_options(family))
    harness = _wrapper_harness()
    run = harness._wrapper_run(tmp_path, options)
    argv = harness._argv(run)
    expected = serial_can_options.build_args(options_with_defaults(options))
    assert argv[-len(expected):] == expected
    for family in EXTRAS:
        assert (f"-growatt-bms-{family}-can-enabled=true" in argv) == (family in families)


@pytest.mark.parametrize("family,suffix", [(family, suffix) for family in EXTRAS
                         for suffix in (*COMMON[1:], EXTRAS[family])
                         if not (family == "pcs" and suffix == "native_contract")])
def test_missing_explicit_inputs_refuse_startup(tmp_path: Path, family: str, suffix: str) -> None:
    options = family_options(family)
    del options[f"growatt_bms_{family}_can_{suffix}"]
    assert_refused(tmp_path, options)


INVALID_OPTIONS = [
    ("enabled", "true"), ("listen_only_confirmed", False), ("listen_only_confirmed", 1),
    ("interface", ""), ("interface", "can;echo"), ("interface", "$(false)"),
    ("interface", "can\n0"), ("interface", "can\x000"), ("interface", "can/0"),
    ("interface", "1234567890123456"), ("stale_after", "0s"), ("stale_after", "-1ns"),
    ("stale_after", "0.1ns"), ("stale_after", "9223372036854775808ns"),
    ("stale_after", "2s;false"), ("stale_after", "2s\n"),
    ("project_code", ""), ("project_code", "qaaa"), ("project_code", "QAA\n"),
    ("release", ""), ("release", "unknown"), ("release", "11"), ("release", 11),
    ("native_profile", ""), ("native_profile", "Standard"), ("native_profile", "auto"),
    ("scope", "Local"), ("scope", ""), ("bank", "Ordinary"), ("bank", "parallel"),
    ("context", ""), ("context", "[]"), ("context", "null"),
]


@pytest.mark.parametrize("family", EXTRAS)
@pytest.mark.parametrize("suffix,value", INVALID_OPTIONS)
def test_invalid_project_options_never_start(tmp_path: Path, family: str, suffix: str, value) -> None:
    assert_refused(tmp_path, family_options(family, **{suffix: value}))


@pytest.mark.parametrize("left,right", list(itertools.combinations(("v104", "pcs", "link"), 2)) +
                         [("all", "all")])
def test_pairwise_and_triple_interface_conflicts_refuse_startup(tmp_path: Path, left: str, right: str) -> None:
    options = dict(CAN_IDENTITY)
    options.update(family_options("pcs"))
    options.update(family_options("link"))
    for family in (("v104", "pcs", "link") if left == "all" else (left, right)):
        key = "growatt_bms_can_interface" if family == "v104" else f"growatt_bms_{family}_can_interface"
        options[key] = "synthetic0"
    assert_refused(tmp_path, options)


@pytest.mark.parametrize("flag", sorted(serial_can_options.project_flags()))
def test_every_emitted_flag_is_probed_before_startup(tmp_path: Path, flag: str) -> None:
    options = family_options("pcs") | family_options("link")
    result = startup(tmp_path, options, hidden=(flag,))
    assert result.returncode == 1 and result.stdout == ""
    assert result.stderr.strip() == "gateway does not support the serial acquisition flags: " + flag


@pytest.mark.parametrize("family", EXTRAS)
def test_disabled_families_need_no_gateway_support(tmp_path: Path, family: str) -> None:
    options = family_options(family, enabled=False)
    result = startup(tmp_path, options, hidden=tuple(serial_can_options.project_flags()))
    assert result.returncode == 0 and result.stdout == "LAUNCHED\n"


@pytest.mark.parametrize("source,accepted", [(0, False), (1, True), (243, True), (244, False),
                                           (245, False), (246, True), (254, True), (255, False),
                                           (256, False), (True, False), (1.0, False), ("1", False)])
def test_selector_source_software_admission_boundaries(tmp_path: Path, source, accepted: bool) -> None:
    options = family_options("link", source_selectors=json.dumps([selection(source)]),
                             context=json.dumps([context(source)]))
    if accepted:
        assert serial_can_options.build_args(options)
    else:
        assert_refused(tmp_path, options)


@pytest.mark.parametrize("count", [0, 1, 32, 33])
def test_source_selector_count_boundaries(tmp_path: Path, count: int) -> None:
    options = family_options("link", source_selectors=json.dumps([selection(i) for i in range(1, count + 1)]),
                             context=json.dumps([context(i) for i in range(1, count + 1)]))
    if 1 <= count <= 32:
        assert serial_can_options.build_args(options)
    else:
        assert_refused(tmp_path, options)


BAD_SELECTORS = [
    "[", "null", "{}", "[]", json.dumps([selection()]) + " []",
    '[{"source":1,"source":2,"use_default":true,"contract":"release11"}]',
    json.dumps([selection(), selection()]), json.dumps([{**selection(), "unknown": 0}]),
    json.dumps([{**selection(), "use_default": True}]),
    json.dumps([{**selection(defaults=True), "use_default": False}]),
    json.dumps([{**selection(defaults=True), "use_default": 1}]),
    json.dumps([{**selection(), "contract": "Release11"}]),
    json.dumps([{**selection(), "release": None}]),
    json.dumps([{**selection(), "project_code": "qaaa"}]),
    json.dumps([{**selection(), "project_code": "$(false)"}]),
    json.dumps([{**selection(), "project_code": "QAA\u007f"}]),
    '[{"source":NaN,"use_default":true,"contract":"release11"}]',
]


@pytest.mark.parametrize("value", BAD_SELECTORS)
def test_strict_source_selector_grammar(tmp_path: Path, value: str) -> None:
    assert_refused(tmp_path, family_options("link", source_selectors=value))


@pytest.mark.parametrize("limit,suffix", [(16384, "source_selectors"), (131072, "context")])
@pytest.mark.parametrize("delta", [0, 1])
def test_json_byte_limits(tmp_path: Path, limit: int, suffix: str, delta: int) -> None:
    options = family_options("link")
    key = "growatt_bms_link_can_" + suffix
    options[key] += " " * (limit - len(options[key].encode()) + delta)
    if delta == 0:
        assert serial_can_options.build_args(options)
    else:
        assert_refused(tmp_path, options)


def test_explicit_ordered_heterogeneous_sources_do_not_inherit_a_default(tmp_path: Path) -> None:
    selectors = [selection(2), {"source": 1, "project_code": "QAAa", "release": "9011", "contract": "legacy19"}]
    raw = json.dumps(selectors, separators=(",", ":"))
    options = family_options("link", project_code="", release="", source_selectors=raw,
                             context=json.dumps([context(2), context(1)]))
    argv = serial_can_options.build_args(options)
    assert argv[argv.index("-growatt-bms-link-can-source-selectors") + 1] == raw
    assert "-growatt-bms-link-can-project-code" not in argv and "-growatt-bms-link-can-release" not in argv
    assert json.loads(raw) == selectors  # ordered source/project/release/contract fields unchanged
    options["growatt_bms_link_can_source_selectors"] = json.dumps([selection(2, defaults=True)])
    assert_refused(tmp_path, options)


def test_selector_key_fields_are_independently_preserved() -> None:
    base = selection()
    for field, replacement in (("source", 2), ("project_code", "QAAa"), ("release", "0005"),
                               ("contract", "legacy19")):
        candidate = {**base, field: replacement}
        options = family_options("link", source_selectors=json.dumps([candidate]),
                                 context=json.dumps([context(candidate["source"])]))
        argv = serial_can_options.build_args(options)
        encoded = argv[argv.index("-growatt-bms-link-can-source-selectors") + 1]
        assert json.loads(encoded) == [candidate], field


@pytest.mark.parametrize("family", EXTRAS)
def test_shell_escaping_preserves_json_without_execution(tmp_path: Path, family: str) -> None:
    c = context()
    c["endpoint"] = r"synthetic'\"$()'\u005cvalue"
    raw = json.dumps([c], separators=(",", ":"))
    options = family_options(family, context=raw)
    result = run_helper(tmp_path, options)
    assert result.returncode == 0
    script = result.stdout + 'printf "%s\\n" "${SERIAL_CAN_ARGS[@]}"\n'
    evaluated = subprocess.run(["bash", "-c", script], capture_output=True, text=True, timeout=10)
    assert evaluated.returncode == 0
    assert evaluated.stdout.splitlines() == serial_can_options.build_args(options)
    assert run_helper(tmp_path, options).stdout == result.stdout


@pytest.mark.parametrize("family", EXTRAS)
@pytest.mark.parametrize("field", sorted(context()))
def test_wire_identity_cannot_fill_missing_association_assertions(tmp_path: Path, family: str, field: str) -> None:
    c = context()
    del c[field]
    assert_refused(tmp_path, family_options(family, context=json.dumps([c])))


@pytest.mark.parametrize("field", ["interface_index", "destination", "endpoint", "group", "slot", "epoch"])
def test_link_common_identity_checks_every_field(tmp_path: Path, field: str) -> None:
    first, second = context(), context(2)
    second[field] = {"interface_index": 8, "destination": 245, "endpoint": "other",
                     "group": "other", "slot": "other", "epoch": 2}[field]
    assert_refused(tmp_path, family_options("link", source_selectors=json.dumps([selection(), selection(2)]),
                                          context=json.dumps([first, second])))


@pytest.mark.parametrize("destination,accepted", [(243, False), (244, True), (245, True), (246, False)])
def test_link_direction_requires_coordinator_destination(tmp_path: Path, destination: int, accepted: bool) -> None:
    c = context()
    c["destination"] = destination
    options = family_options("link", context=json.dumps([c]))
    if accepted:
        assert serial_can_options.build_args(options)
    else:
        assert_refused(tmp_path, options)


@pytest.mark.parametrize("vector,maximum", [("cells", 16), ("sensors", 8)])
@pytest.mark.parametrize("count,valid", [(-1, False), (0, False), (0, True), (1, True), ("max", True), ("over", True)])
def test_context_count_validity_boundaries(tmp_path: Path, vector: str, maximum: int, count, valid: bool) -> None:
    c = context()
    count = maximum if count == "max" else maximum + 1 if count == "over" else count
    c[vector].update(count=count, count_valid=valid)
    options = family_options("pcs", context=json.dumps([c]))
    if 0 <= count <= maximum and (count > 0 or not valid):
        assert serial_can_options.build_args(options)
    else:
        assert_refused(tmp_path, options)


def test_false_validity_and_independent_rejected_fields_remain_exact_raw_options() -> None:
    c = context()
    for field in ("serial_slot_valid", "slot_valid", "group_valid", "publisher_resolved",
                  "measurement_valid", "temperature_valid", "topology_associated"):
        c[field] = False
    c["cells"]["count"], c["cells"]["count_valid"] = 0, False
    for gate, status in zip(c["cells"]["gates"], ("absent", "invalid", "unsupported", "conflict")):
        gate.update(configured=False, valid=False, status=status, age="1s")
    raw = json.dumps([c])
    options = family_options("pcs", context=raw)
    argv = serial_can_options.build_args(options)
    assert argv[argv.index("-growatt-bms-pcs-can-context") + 1] == raw
    assert json.loads(raw)[0]["sensors"] == context()["sensors"]


@pytest.mark.parametrize("family", EXTRAS)
@pytest.mark.parametrize("duration", ["1ns", "1.5ms", "1m2s", "+2s", "9223372036854775807ns"])
def test_positive_go_duration_boundaries(family: str, duration: str) -> None:
    argv = serial_can_options.build_args(family_options(family, stale_after=duration))
    assert argv[argv.index(f"-growatt-bms-{family}-can-stale-after") + 1] == duration


def test_matching_wire_identity_cannot_supply_project_release_or_profile(tmp_path: Path) -> None:
    for family in EXTRAS:
        for field in ("project_code", "release", "native_profile"):
            case = tmp_path / (family + field)
            case.mkdir()
            assert_refused(case, family_options(family, **{field: ""}))


def test_link_scope_cannot_be_inferred_from_peer_identity(tmp_path: Path) -> None:
    assert_refused(tmp_path, family_options("link", scope="aggregate"))


def test_docs_name_options_flags_and_native_owners() -> None:
    readme = (ROOT / "README.md").read_text()
    for flag in serial_can_options.project_flags():
        assert "-" + flag in readme
        assert flag.replace("-", "_") in readme
    for text in ("Profile selection", "Data validity and consumer obligations",
                 "Identify the peer before interpreting version-dependent fields",
                 "Transport, addressing and data validity", "physical_qualified=false",
                 "Nothing is stable before 1.0", "receive-only", "listen-only"):
        assert text in readme


@pytest.mark.parametrize("family", EXTRAS)
@pytest.mark.parametrize("profile,bank", [("standard", "ordinary"), ("extended19", "ordinary"),
                                        ("parallel", "parallel")])
def test_profiles_and_matching_banks_are_explicit(family: str, profile: str, bank: str) -> None:
    options = family_options(family, native_profile=profile, bank=bank,
                             release="0010" if profile == "extended19" else "0011")
    argv = serial_can_options.build_args(options)
    assert argv[argv.index(f"-growatt-bms-{family}-can-native-profile") + 1] == profile
    assert argv[argv.index(f"-growatt-bms-{family}-can-bank") + 1] == bank


@pytest.mark.parametrize("field,value", [("interface_index", 0), ("interface_index", True),
    ("epoch", 0), ("epoch", 2**64), ("source", 256), ("source", -1),
    ("endpoint", "bad\nlabel"), ("group", "bad\x00label"), ("slot", ""),
    ("measurement_valid", 1), ("topology_associated", None), ("field_age", "-1ns")])
def test_invalid_association_assertions_refuse_startup(tmp_path: Path, field: str, value) -> None:
    c = context()
    c[field] = value
    assert_refused(tmp_path, family_options("pcs", context=json.dumps([c])))


@pytest.mark.parametrize("part", ["vector", "gate"])
@pytest.mark.parametrize("mutation", ["missing", "unknown", "null", "wrong_type", "bad_age", "bad_status"])
def test_nested_context_assertions_are_strict(tmp_path: Path, part: str, mutation: str) -> None:
    c = context()
    target = c["cells"] if part == "vector" else c["cells"]["gates"][0]
    field = "count_valid" if part == "vector" else "valid"
    if mutation == "missing":
        del target[field]
    elif mutation == "unknown":
        target["unknown"] = 0
    elif mutation == "null":
        target[field] = None
    elif mutation == "wrong_type":
        target[field] = 1
    elif mutation == "bad_age":
        c["cells"]["gates"][0]["age"] = "-1ns"
    else:
        c["cells"]["gates"][0]["status"] = "Unknown"
    assert_refused(tmp_path, family_options("pcs", context=json.dumps([c])))


@pytest.mark.parametrize("mutation", ["duplicate", "trailing", "unknown", "bad_array", "source_order"])
def test_context_json_never_invents_association(tmp_path: Path, mutation: str) -> None:
    raw = json.dumps([context()])
    if mutation == "duplicate":
        raw = raw.replace('"configured": true', '"configured": true, "configured": false', 1)
    elif mutation == "trailing":
        raw += " []"
    elif mutation == "unknown":
        raw = raw.replace('"source": 1', '"source": 1, "direction": "module-to-coordinator"', 1)
    elif mutation == "bad_array":
        c = context()
        c["cells"]["gates"].pop()
        raw = json.dumps([c])
    else:
        raw = json.dumps([context(2)])
    assert_refused(tmp_path, family_options("link", context=raw))


@pytest.mark.parametrize("contract", ["Release11", "unknown", None])
def test_pcs_contract_is_never_guessed(tmp_path: Path, contract) -> None:
    assert_refused(tmp_path, family_options("pcs", native_contract=contract))


def test_opt_in_default_does_not_fill_an_omitted_source(tmp_path: Path) -> None:
    assert_refused(tmp_path, family_options("link", context=json.dumps([context(), context(2)])))
