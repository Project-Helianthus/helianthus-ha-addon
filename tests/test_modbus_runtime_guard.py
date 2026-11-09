from __future__ import annotations

import importlib.util
import json
import os
import re
import stat
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
GUARD_PATH = ROOT / "helianthus/rootfs/usr/share/helianthus/modbus_runtime_guard.py"
RUN_PATH = ROOT / "helianthus/rootfs/etc/services.d/helianthus-gateway/run"
DOCKERFILE_PATH = ROOT / "helianthus/Dockerfile"
CONFIG_PATH = ROOT / "helianthus/config.json"
CURRENT_GATEWAY = "b223acf12162f8fee470ac337e1207a9382bae0e"


def load_guard():
    spec = importlib.util.spec_from_file_location("modbus_runtime_guard", GUARD_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def write_options(tmp_path: Path, payload: object) -> Path:
    path = tmp_path / "options.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def enabled_options(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "modbus_tcp_enabled": True,
        "modbus_tcp_endpoint": "tcp://192.0.2.40:502",
        "modbus_tcp_dial_timeout": "5s",
    }
    payload.update(overrides)
    return payload


def run_validate(options: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(GUARD_PATH),
            "validate",
            "--options",
            str(options),
        ],
        text=True,
        capture_output=True,
        check=False,
    )


def test_atomic_validation_accepts_one_complete_bounded_bundle(tmp_path: Path) -> None:
    guard = load_guard()
    config = guard.load_config(write_options(tmp_path, enabled_options()))

    assert config.enabled is True
    assert config.endpoint == "tcp://192.0.2.40:502"
    assert config.dial_timeout == "5s"


@pytest.mark.parametrize(
    "payload",
    [
        {"modbus_tcp_enabled": True},
        enabled_options(modbus_tcp_endpoint=""),
        enabled_options(modbus_tcp_dial_timeout="0s"),
        enabled_options(modbus_tcp_dial_timeout="31s"),
        enabled_options(modbus_tcp_enabled="true"),
        enabled_options(modbus_tcp_endpoint=502),
        enabled_options(modbus_tcp_endpoint="tcp://192.0.2.40"),
        enabled_options(modbus_tcp_endpoint="udp://192.0.2.40:502"),
        enabled_options(modbus_tcp_endpoint="tcp://user:secret@192.0.2.40:502"),
        enabled_options(modbus_tcp_endpoint="tcp://192.0.2.40:502/path"),
    ],
)
def test_invalid_or_partial_bundle_fails_before_gateway_start(
    tmp_path: Path, payload: object
) -> None:
    guard = load_guard()
    with pytest.raises(guard.ConfigError):
        guard.load_config(write_options(tmp_path, payload))


@pytest.mark.parametrize(
    ("endpoint", "dial_timeout"),
    [
        ("tcp://operator:retained@192.0.2.40:502", "stale-invalid-value"),
        (None, {"stale": "invalid"}),
    ],
)
def test_disabled_state_is_inert_even_with_retained_malformed_fields(
    tmp_path: Path, endpoint: object, dial_timeout: object
) -> None:
    guard = load_guard()
    config = guard.load_config(
        write_options(
            tmp_path,
            {
                "modbus_tcp_enabled": False,
                "modbus_tcp_endpoint": endpoint,
                "modbus_tcp_dial_timeout": dial_timeout,
            },
        )
    )
    assert config == guard.Config(False, "", "")


def test_cli_error_never_emits_endpoint_or_credentials(tmp_path: Path) -> None:
    endpoint = "tcp://operator:topsecret@192.0.2.40:502"
    options = write_options(tmp_path, enabled_options(modbus_tcp_endpoint=endpoint))
    endpoint_file = tmp_path / "run" / "modbus-endpoint"
    result = run_validate(options)

    assert result.returncode != 0
    assert endpoint not in result.stderr
    assert "topsecret" not in result.stderr
    assert not endpoint_file.exists()


def test_cli_returns_a_complete_validated_bundle_without_materializing_endpoint(
    tmp_path: Path,
) -> None:
    endpoint_file = tmp_path / "run" / "modbus-endpoint"
    endpoint_file.parent.mkdir(mode=0o755)
    enabled = run_validate(write_options(tmp_path, enabled_options()))

    assert enabled.returncode == 0, enabled.stderr
    assert enabled.stdout.splitlines() == [
        "MODBUS_TCP_ENABLED=true",
        "MODBUS_TCP_ENDPOINT=tcp://192.0.2.40:502",
        "MODBUS_TCP_DIAL_TIMEOUT=5s",
    ]
    assert not endpoint_file.exists()

    disabled = run_validate(write_options(tmp_path, {"modbus_tcp_enabled": False}))
    assert disabled.returncode == 0, disabled.stderr
    assert disabled.stdout.splitlines() == [
        "MODBUS_TCP_ENABLED=false",
        "MODBUS_TCP_ENDPOINT=''",
        "MODBUS_TCP_DIAL_TIMEOUT=''",
    ]
    assert not endpoint_file.exists()


def test_invalid_update_does_not_mutate_existing_endpoint(tmp_path: Path) -> None:
    endpoint_file = tmp_path / "run" / "modbus-endpoint"
    endpoint_file.parent.mkdir(parents=True)
    endpoint_file.write_text("stale", encoding="utf-8")

    invalid = run_validate(
        write_options(tmp_path, enabled_options(modbus_tcp_dial_timeout="invalid"))
    )
    assert invalid.returncode != 0
    assert endpoint_file.read_text(encoding="utf-8") == "stale"


def test_image_and_wrapper_use_only_current_gateway_and_one_exec() -> None:
    dockerfile = DOCKERFILE_PATH.read_text(encoding="utf-8")
    run = RUN_PATH.read_text(encoding="utf-8")
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))

    assert f"ARG EBUSGATEWAY_VERSION={CURRENT_GATEWAY}" in dockerfile
    assert "FALLBACK_VERSION" not in dockerfile
    assert "gateway-fallback" not in dockerfile
    assert config["options"]["modbus_tcp_enabled"] is False
    assert config["options"]["modbus_tcp_endpoint"] == ""
    assert config["schema"]["modbus_tcp_endpoint"] == "str"
    assert "-modbus-tcp-enabled=true" in run
    assert '-modbus-tcp-endpoint-file "${modbus_endpoint_file}"' in run
    assert run.count('exec "${gateway_bin}" "${gateway_args[@]}"') == 1
    assert 'gateway_args+=("${modbus_args[@]}")' in run
    assert "modbus_child_pid" not in run
    assert "modbus_write_health" not in run
    assert "probe-readiness" not in run


def test_supervisor_schema_accepts_legacy_options_and_shows_modbus_endpoint() -> None:
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))

    # Supervisor treats every schema entry with a default in options as
    # required. Upgraded pre-selector configurations must remain saveable.
    assert "adapter_direct_protocol" not in config["options"]
    assert config["schema"]["adapter_direct_protocol"] == "list(enh|ens)?"

    # A Modbus endpoint is routing configuration, not a credential. Runtime
    # validation separately rejects userinfo and keeps error output redacted.
    assert config["schema"]["modbus_tcp_endpoint"] == "str"


# --------------------------------------------------------------------------------------
# Configuration v2: the modbus_tcp_endpoints list. Every host below is a synthetic name
# under a reserved invalid domain; no value describes an installation.

DOC_TAIL = re.compile(r"^invalid Modbus TCP configuration: ([A-Z_]+)(?: \(entry (\d+)\))?\n$")
CONTRACT = "helianthus.modbus-tcp-endpoints.v2"
CANARY = "tcp://canary-endpoint.example.invalid:1502"
ABSENT = object()


def entry(**overrides: object) -> dict[str, object]:
    """A valid second entry of the contract example; ABSENT removes a member."""
    payload: dict[str, object] = {
        "label": "roof",
        "family": "sunspec",
        "endpoint": "tcp://sunspec-b.example.invalid:1502",
    }
    payload.update(overrides)
    return {key: value for key, value in payload.items() if value is not ABSENT}


def v2_options(*entries: object, **overrides: object) -> dict[str, object]:
    payload = enabled_options(modbus_tcp_endpoint="", modbus_tcp_endpoints=list(entries))
    payload.update(overrides)
    return payload


FIRST_ENTRY = entry(
    label="default",
    endpoint="tcp://sunspec-a.example.invalid:502",
    dial_timeout="5s",
    units=[1],
    pacing_gap_ms=200,
    pacing_settle_ms=1000,
    pacing_cycle_s=15,
    pacing_backoff_floor_s=5,
    pacing_backoff_ceiling_s=300,
)
CONTRACT_EXAMPLE = (
    '{"contract":"helianthus.modbus-tcp-endpoints.v2","endpoints":['
    '{"label":"default","family":"sunspec","endpoint":"tcp://sunspec-a.example.invalid:502",'
    '"dial_timeout":"5s","units":[1],"pacing":{"gap_ms":200,"settle_ms":1000,"cycle_s":15,'
    '"backoff_floor_s":5,"backoff_ceiling_s":300}},'
    '{"label":"roof","family":"sunspec","endpoint":"tcp://sunspec-b.example.invalid:1502"}]}'
)


def run_guard(command: str, options: Path, *extra: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(GUARD_PATH), command, "--options", str(options), *extra],
        text=True,
        capture_output=True,
        check=False,
    )


def test_a_valid_list_selects_configuration_v2_and_emits_the_exact_document(tmp_path: Path) -> None:
    guard = load_guard()
    config = guard.load_config(write_options(tmp_path, v2_options(FIRST_ENTRY, entry())))

    assert (config.enabled, config.endpoint, config.dial_timeout) == (True, "", "5s")
    assert [(item.label, item.family) for item in config.endpoints] == [("default", "sunspec"), ("roof", "sunspec")]
    assert guard.endpoints_document(config.endpoints).decode("ascii") == CONTRACT_EXAMPLE
    assert json.loads(CONTRACT_EXAMPLE)["contract"] == CONTRACT == guard.ENDPOINTS_CONTRACT


def test_every_family_and_member_reaches_the_document_in_contract_order(tmp_path: Path) -> None:
    guard = load_guard()
    entries = [
        entry(label="site-a", family="huawei.smartlogger", endpoint="tcp://[2001:db8::1]:502", units=[3, 1, 247]),
        entry(label="default", family="huawei.emma", endpoint="tcp://emma.example.invalid:502",
              dial_timeout="750ms", pacing_cycle_s=3600),
        entry(label="site-b", family="huawei.sdongle", endpoint="tcp://dongle.example.invalid:502",
              pacing_backoff_floor_s=300, pacing_backoff_ceiling_s=300, pacing_settle_ms=0),
    ]
    config = guard.load_config(write_options(tmp_path, v2_options(*entries)))
    assert json.loads(guard.endpoints_document(config.endpoints)) == {
        "contract": CONTRACT,
        "endpoints": [
            {"label": "site-a", "family": "huawei.smartlogger", "endpoint": "tcp://[2001:db8::1]:502",
             "units": [3, 1, 247]},
            {"label": "default", "family": "huawei.emma", "endpoint": "tcp://emma.example.invalid:502",
             "dial_timeout": "750ms", "pacing": {"cycle_s": 3600}},
            {"label": "site-b", "family": "huawei.sdongle", "endpoint": "tcp://dongle.example.invalid:502",
             "pacing": {"settle_ms": 0, "backoff_floor_s": 300, "backoff_ceiling_s": 300}},
        ],
    }
    # Members the operator did not set are not invented: the gateway owns the defaults.
    assert list(json.loads(guard.endpoints_document(config.endpoints))["endpoints"][1]) == [
        "label", "family", "endpoint", "dial_timeout", "pacing"]


def test_a_maximal_list_stays_inside_the_documented_document_size(tmp_path: Path) -> None:
    guard = load_guard()
    full = {
        "family": "huawei.smartlogger",
        "dial_timeout": "30000ms",
        "units": list(range(216, 248)),
        "pacing_gap_ms": 2000, "pacing_settle_ms": 10000, "pacing_cycle_s": 3600,
        "pacing_backoff_floor_s": 300, "pacing_backoff_ceiling_s": 3600,
    }
    entries = [
        entry(label=f"{'a' * 29}-{number:02d}"[:32],
              endpoint=f"tcp://{'h' * 63}.{'x' * 63}.{'y' * 63}.{'z' * 61}:6550{number}", **full)
        for number in range(8)
    ]
    assert all(len(item["label"]) == 32 and len(item["endpoint"]) <= 288 for item in entries)
    config = guard.load_config(write_options(tmp_path, v2_options(*entries)))
    assert len(guard.endpoints_document(config.endpoints)) < guard.MAX_DOCUMENT_BYTES == 16384


def test_the_document_is_refused_above_its_size_bound(tmp_path: Path, monkeypatch) -> None:
    guard = load_guard()
    config = guard.load_config(write_options(tmp_path, v2_options(entry())))
    monkeypatch.setattr(guard, "MAX_DOCUMENT_BYTES", 10)
    with pytest.raises(guard.ConfigRejection) as raised:
        guard.endpoints_document(config.endpoints)
    assert raised.value.summary() == "INVALID_DOCUMENT"


def test_materialize_writes_the_document_atomically_with_owner_only_modes(tmp_path: Path) -> None:
    options = write_options(tmp_path, v2_options(FIRST_ENTRY, entry()))
    directory = tmp_path / "run"
    document = directory / "modbus-endpoints.json"
    directory.mkdir(mode=0o755)
    directory.chmod(0o755)
    document.write_text("stale", encoding="utf-8")
    document.chmod(0o644)
    (directory / "modbus-endpoints.json.tmp").write_text("stale staging", encoding="utf-8")

    result = run_guard("materialize", options, "--document", str(document))

    assert result.returncode == 0 and (result.stdout, result.stderr) == ("", "")
    assert document.read_bytes() == CONTRACT_EXAMPLE.encode("ascii")
    assert stat.S_IMODE(document.stat().st_mode) == 0o600
    assert stat.S_IMODE(directory.stat().st_mode) == 0o700
    assert sorted(path.name for path in directory.iterdir()) == ["modbus-endpoints.json"]


def test_materialize_creates_a_missing_directory_and_ignores_the_umask(tmp_path: Path) -> None:
    guard = load_guard()
    config = guard.load_config(write_options(tmp_path, v2_options(entry())))
    document = tmp_path / "missing" / "run" / "modbus-endpoints.json"
    previous = os.umask(0)
    try:
        guard.materialize(config, document)
    finally:
        os.umask(previous)

    assert stat.S_IMODE(document.stat().st_mode) == 0o600
    assert stat.S_IMODE(document.parent.stat().st_mode) == 0o700
    assert document.read_bytes() == guard.endpoints_document(config.endpoints)


def test_materialize_never_follows_a_staging_link(tmp_path: Path) -> None:
    guard = load_guard()
    config = guard.load_config(write_options(tmp_path, v2_options(entry())))
    document = tmp_path / "run" / "modbus-endpoints.json"
    document.parent.mkdir()
    victim = tmp_path / "victim"
    victim.write_text("untouched", encoding="utf-8")
    (document.parent / "modbus-endpoints.json.tmp").symlink_to(victim)

    guard.materialize(config, document)

    assert victim.read_text(encoding="utf-8") == "untouched"
    assert document.read_bytes() == guard.endpoints_document(config.endpoints)
    assert not document.is_symlink()


def test_a_failed_write_leaves_neither_document_nor_staging_nor_a_leak(tmp_path: Path) -> None:
    document = tmp_path / "run" / "modbus-endpoints.json"
    document.parent.mkdir()
    (document.parent / "modbus-endpoints.json.tmp").mkdir()  # an unusable staging path

    result = run_guard("materialize", write_options(tmp_path, v2_options(entry(endpoint=CANARY))),
                       "--document", str(document))

    assert result.returncode == 2 and result.stdout == ""
    assert result.stderr == "unable to materialize the Modbus TCP endpoints document\n"
    assert not document.exists()


def test_a_failed_rename_removes_the_staging_file_and_keeps_what_was_there(tmp_path: Path) -> None:
    guard = load_guard()
    config = guard.load_config(write_options(tmp_path, v2_options(entry(endpoint=CANARY))))
    document = tmp_path / "run" / "modbus-endpoints.json"
    document.mkdir(parents=True)  # a directory cannot be replaced by the staged file
    (document / "keep").write_text("kept", encoding="utf-8")

    with pytest.raises(OSError):
        guard.materialize(config, document)

    assert sorted(path.name for path in document.parent.iterdir()) == ["modbus-endpoints.json"]
    assert (document / "keep").read_text(encoding="utf-8") == "kept"


def test_materialize_refuses_a_configuration_that_selects_no_list(tmp_path: Path) -> None:
    document = tmp_path / "run" / "modbus-endpoints.json"
    for options in (enabled_options(), {"modbus_tcp_enabled": False}, v2_options()):
        result = run_guard("materialize", write_options(tmp_path, options), "--document", str(document))
        assert result.returncode == 2 and result.stdout == ""
        assert result.stderr == "invalid Modbus TCP configuration\n"
        assert not document.exists()


# Each case: id, options, expected category, expected entry position (None when not entry-local).
def _rejections() -> list[tuple[str, dict[str, object], str, int | None]]:
    ok = entry()
    cases: list[tuple[str, dict[str, object], str, int | None]] = []

    def add(case: str, options: dict[str, object], category: str, position: int | None = None) -> None:
        cases.append((case, options, category, position))

    # Selection.
    add("mixed-scalar-endpoint", v2_options(ok, modbus_tcp_endpoint="tcp://192.0.2.40:502"), "MIXED_CONFIGURATION")
    add("mixed-scalar-endpoint-beats-an-invalid-list", v2_options({}, modbus_tcp_endpoint="x"), "MIXED_CONFIGURATION")
    add("mixed-dial-timeout", v2_options(ok, modbus_tcp_dial_timeout="10s"), "MIXED_CONFIGURATION")
    add("mixed-equivalent-dial-timeout-spelling", v2_options(ok, modbus_tcp_dial_timeout="5000ms"),
        "MIXED_CONFIGURATION")
    add("mixed-null-scalar", v2_options(ok, modbus_tcp_endpoint=None), "MIXED_CONFIGURATION")
    # Document stage.
    add("list-is-an-object", v2_options(ok, modbus_tcp_endpoints={"label": "roof"}), "INVALID_DOCUMENT")
    add("list-is-a-string", v2_options(ok, modbus_tcp_endpoints="tcp://x.example.invalid:1"), "INVALID_DOCUMENT")
    add("list-is-null", v2_options(ok, modbus_tcp_endpoints=None), "INVALID_DOCUMENT")
    add("null-member", v2_options(entry(dial_timeout=None)), "INVALID_DOCUMENT")
    add("fractional-number", v2_options(entry(pacing_gap_ms=200.0)), "INVALID_DOCUMENT")
    add("fractional-unit", v2_options(entry(units=[1.5])), "INVALID_DOCUMENT")
    add("control-character-in-endpoint", v2_options(entry(endpoint="tcp://x.example.invalid:1\n")), "INVALID_DOCUMENT")
    add("control-character-in-label", v2_options(entry(label="ro\tof")), "INVALID_DOCUMENT")
    add("control-character-in-key", v2_options({**ok, "bad\x00key": 1}), "INVALID_DOCUMENT")
    add("nesting-too-deep", v2_options(entry(units=[[1]])), "INVALID_DOCUMENT")
    add("entry-not-an-object", v2_options(ok, "tcp://x.example.invalid:1"), "INVALID_DOCUMENT", 1)
    # Top level: the entry count.
    add("nine-entries", v2_options(*[entry(label=f"site{number}", endpoint=f"tcp://h{number}.example.invalid:1")
                                      for number in range(9)]), "TOO_MANY_ENTRIES")
    # Entry stage, in order.
    for member in ("label", "family", "endpoint"):
        add(f"missing-{member}", v2_options(ok, entry(**{member: ABSENT})), "MISSING_FIELD", 1)
    add("unknown-member", v2_options(entry(enabled=True)), "UNKNOWN_MEMBER", 0)
    add("unknown-member-with-a-lone-surrogate", v2_options(entry(**{"ro\ud800of": 1})), "UNKNOWN_MEMBER", 0)
    add("nested-pacing-object", v2_options(entry(pacing={"gap_ms": 200})), "UNKNOWN_MEMBER", 0)
    add("unknown-pacing-member", v2_options(entry(pacing_burst=1)), "UNKNOWN_MEMBER", 0)
    labels = ("Roof_1", "1roof", "roof-", "a.b", "", "a" * 33, "roof--a", "-roof", "Roof", "roof\u00e9", 7, ["roof"],
              "ro\ud800of", "\udc00")
    for index, label in enumerate(labels):
        add(f"invalid-label-{index}", v2_options(entry(label=label)), "INVALID_LABEL", 0)
    families = ("Sunspec", "huawei", "huawei.inverter", "huawei.smartlogger.x", "", " sunspec", "modbus.sunspec", 5,
                "sun\ud800spec")
    for index, family in enumerate(families):
        add(f"unknown-family-{index}", v2_options(entry(family=family)), "UNKNOWN_FAMILY", 0)
    endpoints = (
        "tcp://host.example.invalid", "tcp://host.example.invalid:0", "tcp://host.example.invalid:65536",
        "tcp://host.example.invalid:502/path", "tcp://host.example.invalid:502?x=1", "tcp://host.example.invalid:502#f",
        "tcp://user:secret@host.example.invalid:502", "tcp://user@host.example.invalid:502",
        "udp://host.example.invalid:502", "host.example.invalid:502", "", " tcp://host.example.invalid:502",
        "tcp://host.example.invalid:502 ", "tcp://-bad.example.invalid:502", "tcp://bad_host.example.invalid:502",
        "tcp://host.example.invalid:50\u0662", "tcp://h\u00f6st.example.invalid:502", "tcp://:502",
        "tcp://" + "a" * 290 + ":502", 502, ["tcp://host.example.invalid:502"],
        "tcp://h\ud800.example.invalid:502", "tcp://host.example.invalid:502\udfff", "\ud800",
    )
    for index, endpoint in enumerate(endpoints):
        add(f"invalid-endpoint-{index}", v2_options(entry(endpoint=endpoint)), "INVALID_ENDPOINT", 0)
    timeouts = ("50ms", "99ms", "45s", "31s", "30001ms", "0s", "5", "5m", "-5s", "05s", "5 s", "5s\u00a0", 5, True,
                "5\ud800s")
    for index, timeout in enumerate(timeouts):
        add(f"invalid-timeout-{index}", v2_options(entry(dial_timeout=timeout)), "INVALID_TIMEOUT", 0)
    bad_units = ([], [0], [248], [1, 1], [-1], [True], ["1"], "1", 1, list(range(1, 34)), {"1": 1})
    for index, units in enumerate(bad_units):  # a family without the SunSpec rule exercises the generic bounds
        add(f"invalid-units-{index}", v2_options(entry(family="huawei.smartlogger", units=units)), "INVALID_UNITS", 0)
    add("sunspec-units-other-than-one", v2_options(entry(units=[2])), "INVALID_UNITS", 0)
    add("sunspec-units-widened", v2_options(entry(units=[1, 2])), "INVALID_UNITS", 0)
    for option, low, high in (
        ("pacing_gap_ms", 50, 2000), ("pacing_settle_ms", 0, 10000), ("pacing_cycle_s", 15, 3600),
        ("pacing_backoff_floor_s", 1, 300), ("pacing_backoff_ceiling_s", 5, 3600),
    ):
        for kind, value in (("below", low - 1), ("above", high + 1), ("boolean", True), ("text", str(low))):
            add(f"invalid-{option}-{kind}", v2_options(entry(**{option: value})), "INVALID_PACING", 0)
    add("floor-above-ceiling", v2_options(entry(pacing_backoff_floor_s=60, pacing_backoff_ceiling_s=30)),
        "INVALID_PACING", 0)
    # Across entries.
    add("duplicate-label", v2_options(ok, entry(endpoint="tcp://sunspec-c.example.invalid:1502")), "DUPLICATE_LABEL")
    add("duplicate-label-across-families",
        v2_options(ok, entry(family="huawei.emma", endpoint="tcp://sunspec-c.example.invalid:1502")), "DUPLICATE_LABEL")
    add("duplicate-endpoint", v2_options(ok, entry(label="ridge")), "DUPLICATE_ENDPOINT")
    # Position and order.
    add("first-failing-entry-decides", v2_options(entry(endpoint="tcp://nope"), entry(label="Bad")),
        "INVALID_ENDPOINT", 0)
    add("later-entry-position-is-reported",
        v2_options(ok, entry(label="ridge", endpoint="tcp://sunspec-c.example.invalid:1502"),
                   entry(label="third", family="huawei.emma", units=[0])), "INVALID_UNITS", 2)
    return cases


REJECTIONS = _rejections()


@pytest.mark.parametrize(("options", "category", "position"), [case[1:] for case in REJECTIONS],
                         ids=[case[0] for case in REJECTIONS])
def test_each_invalid_list_is_rejected_with_one_static_category(
    tmp_path: Path, options: dict[str, object], category: str, position: int | None
) -> None:
    guard = load_guard()
    with pytest.raises(guard.ConfigRejection) as raised:
        guard.load_config(write_options(tmp_path, options))
    assert (raised.value.category, raised.value.entry) == (category, position)
    assert category in guard.CATEGORIES
    assert raised.value.args == (category,)


@pytest.mark.parametrize("command", ["validate", "materialize"])
def test_rejections_print_one_redacted_line_and_leave_no_document(
    tmp_path: Path, monkeypatch, capsys, command: str
) -> None:
    guard = load_guard()
    document = tmp_path / "run" / "modbus-endpoints.json"
    document.parent.mkdir()
    for case, options, category, position in REJECTIONS:
        document.write_text("stale", encoding="utf-8")
        argv = [str(GUARD_PATH), command, "--options", str(write_options(tmp_path, options))]
        if command == "materialize":
            argv += ["--document", str(document)]
        monkeypatch.setattr(sys, "argv", argv)
        assert guard.main() == 2, case
        captured = capsys.readouterr()
        assert captured.out == "", case
        expected = category if position is None else f"{category} (entry {position})"
        assert captured.err == f"invalid Modbus TCP configuration: {expected}\n", case
        assert DOC_TAIL.fullmatch(captured.err), case
        if command == "materialize":
            assert not document.exists() and not Path(f"{document}.tmp").exists(), case


def test_cli_rejection_never_echoes_an_endpoint_label_or_credential(tmp_path: Path) -> None:
    secret = "tcp://operator:topsecret@canary-endpoint.example.invalid:1502"
    for options in (v2_options(entry(endpoint=secret, label="canary-label")),
                    v2_options(entry(label="canary-label"), entry(label="canary-label", endpoint=CANARY)),
                    v2_options(entry(endpoint=CANARY), modbus_tcp_endpoint=secret)):
        for command, extra in (("validate", ()), ("materialize", ("--document", str(tmp_path / "doc")))):
            result = run_guard(command, write_options(tmp_path, options), *extra)
            assert result.returncode == 2
            for leaked in ("topsecret", "operator", "canary", secret, CANARY):
                assert leaked not in result.stdout + result.stderr
    assert not (tmp_path / "doc").exists()


def test_a_valid_list_never_reaches_stdout_stderr_or_the_arguments(tmp_path: Path) -> None:
    options = write_options(tmp_path, v2_options(entry(endpoint=CANARY), entry(
        label="ridge", endpoint="tcp://canary-second.example.invalid:1502")))
    document = tmp_path / "run" / "modbus-endpoints.json"
    for command, extra in (("validate", ()), ("materialize", ("--document", str(document)))):
        result = run_guard(command, options, *extra)
        assert result.returncode == 0, result.stderr
        assert "canary" not in result.stdout + result.stderr
    guard_argv = [sys.executable, str(GUARD_PATH), "materialize", "--options", str(options), "--document", str(document)]
    assert not any("canary" in argument for argument in guard_argv)
    assert "canary" in document.read_text(encoding="ascii")  # the document is the one carrier


def test_a_validated_entry_does_not_print_its_endpoint(tmp_path: Path) -> None:
    guard = load_guard()
    config = guard.load_config(write_options(tmp_path, v2_options(entry(endpoint=CANARY))))
    assert "canary" not in repr(config) and "canary" not in repr(config.endpoints[0])


def test_validate_reports_v2_only_for_a_list_and_keeps_the_v1_output_otherwise(tmp_path: Path) -> None:
    listed = run_guard("validate", write_options(tmp_path, v2_options(entry())))
    assert listed.stdout.splitlines() == [
        "MODBUS_TCP_ENABLED=true", "MODBUS_TCP_ENDPOINT=''", "MODBUS_TCP_DIAL_TIMEOUT=5s", "MODBUS_TCP_CONFIG=v2"]
    for options in (enabled_options(), enabled_options(modbus_tcp_endpoints=[])):
        v1 = run_guard("validate", write_options(tmp_path, options))
        assert v1.stdout.splitlines() == [
            "MODBUS_TCP_ENABLED=true", "MODBUS_TCP_ENDPOINT=tcp://192.0.2.40:502", "MODBUS_TCP_DIAL_TIMEOUT=5s"]
    guard = load_guard()
    assert guard.load_config(write_options(tmp_path, enabled_options(modbus_tcp_endpoints=[]))).endpoints == ()


@pytest.mark.parametrize(
    "extra",
    [
        {"modbus_tcp_endpoints": [{"label": "Bad", "family": 7}]},
        {"modbus_tcp_endpoints": "not a list"},
        {"modbus_tcp_endpoints": [entry()] * 9, "modbus_tcp_endpoint": "tcp://192.0.2.40:502"},
        {"modbus_tcp_endpoints": [None], "modbus_tcp_dial_timeout": "stale-invalid-value"},
    ],
)
def test_the_disabled_path_ignores_the_list_and_every_scalar(tmp_path: Path, extra: dict) -> None:
    guard = load_guard()
    options = write_options(tmp_path, {"modbus_tcp_enabled": False, **extra})
    assert guard.load_config(options) == guard.Config(False, "", "")
    result = run_guard("validate", options)
    assert result.returncode == 0
    assert result.stdout.splitlines() == [
        "MODBUS_TCP_ENABLED=false", "MODBUS_TCP_ENDPOINT=''", "MODBUS_TCP_DIAL_TIMEOUT=''"]
    assert result.stderr == ""
    document = tmp_path / "run" / "modbus-endpoints.json"
    assert run_guard("materialize", options, "--document", str(document)).returncode == 2
    assert not document.exists()


def test_the_check_order_follows_the_contract(tmp_path: Path) -> None:
    guard = load_guard()

    def category(*entries: object, **overrides: object) -> tuple[str, int | None]:
        with pytest.raises(guard.ConfigRejection) as raised:
            guard.load_config(write_options(tmp_path, v2_options(*entries, **overrides)))
        return raised.value.category, raised.value.entry

    # Selection first, then the document stage, then the count, then each entry, then across entries.
    broken = entry(label="Bad", family="x", endpoint="tcp://nope", dial_timeout="0s", units=[0], pacing_gap_ms=1)
    assert category(broken, modbus_tcp_endpoint="x") == ("MIXED_CONFIGURATION", None)
    assert category(entry(dial_timeout=None), *[broken] * 9) == ("INVALID_DOCUMENT", None)
    assert category(*[broken] * 9) == ("TOO_MANY_ENTRIES", None)

    # Inside one entry: required, unknown, label, family, endpoint, timeout, units, pacing. Each stage
    # fixes only the check that just fired, so the next one is the first to fail.
    current: dict[str, object] = {**broken, "extra": 1}
    del current["family"]
    stages = [
        ("MISSING_FIELD", {"family": "x"}),
        ("UNKNOWN_MEMBER", {"extra": ABSENT}),
        ("INVALID_LABEL", {"label": "ok"}),
        ("UNKNOWN_FAMILY", {"family": "huawei.emma"}),
        ("INVALID_ENDPOINT", {"endpoint": "tcp://h.example.invalid:1"}),
        ("INVALID_TIMEOUT", {"dial_timeout": "5s"}),
        ("INVALID_UNITS", {"units": [1]}),
        ("INVALID_PACING", {"pacing_gap_ms": 200}),
    ]
    for expected, fix in stages:
        assert category(current) == (expected, 0)
        current = {key: value for key, value in {**current, **fix}.items() if value is not ABSENT}
    assert len(guard.load_config(write_options(tmp_path, v2_options(current))).endpoints) == 1

    # A later entry never outranks an earlier one, and duplicates are judged only after every entry passed.
    assert category(entry(label="a", endpoint="tcp://h.example.invalid:1", units=[0]),
                    entry(label="b", endpoint="tcp://h.example.invalid:1", family="x")) == ("INVALID_UNITS", 0)
    assert category(entry(label="a", endpoint="tcp://h.example.invalid:1"),
                    entry(label="a", endpoint="tcp://h.example.invalid:1")) == ("DUPLICATE_LABEL", None)
    assert category(entry(label="a", endpoint="tcp://h.example.invalid:1"),
                    entry(label="b", endpoint="tcp://h.example.invalid:1"),
                    entry(label="a", endpoint="tcp://h2.example.invalid:1")) == ("DUPLICATE_LABEL", None)


@pytest.mark.parametrize(
    ("first", "second", "duplicate"),
    [
        ("tcp://host.example.invalid:502", "tcp://host.example.invalid:502", True),
        ("tcp://host.example.invalid:502", "tcp://HOST.Example.INVALID:502", True),
        ("tcp://host.example.invalid:502", "tcp://host.example.invalid.:502", True),
        ("tcp://host.example.invalid:502", "tcp://host.example.invalid:0502", True),
        ("tcp://192.0.2.7:502", "tcp://192.0.2.7.:502", True),
        ("tcp://[2001:db8::1]:502", "tcp://[2001:0DB8:0:0:0:0:0:1]:502", True),
        ("tcp://host.example.invalid:502", "tcp://host.example.invalid:503", False),
        ("tcp://host.example.invalid:502", "tcp://other.example.invalid:502", False),
        ("tcp://192.0.2.7:502", "tcp://192.0.2.8:502", False),
        ("tcp://[2001:db8::1]:502", "tcp://[2001:db8::2]:502", False),
        ("tcp://host.example.invalid:502", "tcp://host.example.invalid..:502", False),
    ],
)
def test_endpoint_uniqueness_is_judged_after_normalization(
    tmp_path: Path, first: str, second: str, duplicate: bool
) -> None:
    guard = load_guard()
    options = write_options(tmp_path, v2_options(entry(label="one", endpoint=first), entry(label="two", endpoint=second)))
    if duplicate:
        with pytest.raises(guard.ConfigRejection) as raised:
            guard.load_config(options)
        assert (raised.value.category, raised.value.entry) == ("DUPLICATE_ENDPOINT", None)
    else:
        try:
            assert len(guard.load_config(options).endpoints) == 2
        except guard.ConfigRejection as raised:  # an invalid spelling is a different category, never a duplicate
            assert raised.category == "INVALID_ENDPOINT"


def test_the_family_table_is_closed_and_a_duplicate_label_is_the_only_identity_collision() -> None:
    guard = load_guard()
    assert guard.FAMILIES == ("sunspec", "huawei.smartlogger", "huawei.emma", "huawei.sdongle")
    # The merged contract has no driver ID category: labels are unique across families and the
    # driver ID derivation is injective, so a duplicate label is the rejection.
    assert "DUPLICATE_DRIVER_ID" not in guard.CATEGORIES
    assert guard.CATEGORIES[-2:] == ("DUPLICATE_LABEL", "DUPLICATE_ENDPOINT")


def test_eight_entries_are_accepted_and_the_list_option_is_never_required(tmp_path: Path) -> None:
    guard = load_guard()
    eight = [entry(label=f"site{number}", endpoint=f"tcp://h{number}.example.invalid:502") for number in range(8)]
    assert len(guard.load_config(write_options(tmp_path, v2_options(*eight))).endpoints) == 8
    assert guard.load_config(write_options(tmp_path, enabled_options())).endpoints == ()


def test_v1_only_validation_is_unchanged_by_the_list_option(tmp_path: Path) -> None:
    guard = load_guard()
    for payload in (enabled_options(), enabled_options(modbus_tcp_endpoints=[])):
        config = guard.load_config(write_options(tmp_path, payload))
        assert config == guard.Config(True, "tcp://192.0.2.40:502", "5s")
        assert config.endpoints == ()
    with pytest.raises(guard.ConfigError) as raised:
        guard.load_config(write_options(tmp_path, enabled_options(modbus_tcp_endpoint="")))
    assert not isinstance(raised.value, guard.ConfigRejection)  # v1 errors keep their uncategorised message
    failed = run_guard("validate", write_options(tmp_path, enabled_options(modbus_tcp_dial_timeout="0s")))
    assert (failed.returncode, failed.stdout, failed.stderr) == (2, "", "invalid Modbus TCP configuration\n")


# --------------------------------------------------------------------------------------
# Supervisor schema. A small offline mirror of the public option-schema grammar and of the
# acceptance rules in the Supervisor's option validator (supervisor/apps/options.py of
# home-assistant/supervisor): a leaf is optional only through a trailing "?", a list is
# optional through its element, a nested object is always required, unknown keys are
# dropped, a list has no length bound and "int" coerces. It is not the Supervisor; it
# fails when config.json leaves the grammar or stops saying what these tests state.

SCHEMA_ELEMENT = re.compile(
    r"^(?:"
    r"|bool"
    r"|email"
    r"|url"
    r"|port"
    r"|device(?:\((?P<filter>subsystem=[a-z]+)\))?"
    r"|str(?:\((?P<s_min>\d+)?,(?P<s_max>\d+)?\))?"
    r"|password(?:\((?P<p_min>\d+)?,(?P<p_max>\d+)?\))?"
    r"|int(?:\((?P<i_min>-?\d+)?,(?P<i_max>-?\d+)?\))?"
    r"|float(?:\((?P<f_min>-?\d*\.?\d+)?,(?P<f_max>-?\d*\.?\d+)?\))?"
    r"|match\((?P<match>.*)\)"
    r"|list\((?P<list>.+)\)"
    r")\??$"
)
CONFIG_DOC = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
SCHEMA = CONFIG_DOC["schema"]
LIST_SCHEMA = SCHEMA["modbus_tcp_endpoints"]
ENTRY_SCHEMA = LIST_SCHEMA[0]


class SchemaInvalid(Exception):
    pass


def sv_grammar(node: object, where: str = "schema") -> None:
    if isinstance(node, str):
        assert SCHEMA_ELEMENT.match(node), (where, node)
    elif isinstance(node, list):
        assert len(node) == 1 and not isinstance(node[0], list), where  # a list never holds a list
        sv_grammar(node[0], where)
    else:
        assert isinstance(node, dict), where
        for key, value in node.items():
            sv_grammar(value, f"{where}.{key}")


def sv_leaf(typ: str, value: object) -> object:
    match = SCHEMA_ELEMENT.match(typ)
    if value is None:
        raise SchemaInvalid("missing")
    bounds = {name[2:]: float(match.group(name)) for name in
              ("s_min", "s_max", "p_min", "p_max", "i_min", "i_max") if match.group(name)}
    if typ.startswith(("str", "password")):
        if not isinstance(value, str) or len(value) < bounds.get("min", 0) or len(value) > bounds.get("max", 1e9):
            raise SchemaInvalid("string")
    elif typ.startswith("int"):
        try:
            value = int(value)  # voluptuous Coerce(int): "5", True and 5.9 are all accepted
        except (TypeError, ValueError):
            raise SchemaInvalid("int") from None
        if value < bounds.get("min", -1e18) or value > bounds.get("max", 1e18):
            raise SchemaInvalid("range")
    elif typ.startswith("match"):
        if not re.match(match.group("match"), str(value)):
            raise SchemaInvalid("match")
    elif typ.startswith("list"):
        if str(value) not in match.group("list").split("|"):
            raise SchemaInvalid("list")
    elif typ.startswith("bool"):
        if not isinstance(value, bool):
            raise SchemaInvalid("bool")
    else:
        raise NotImplementedError(typ)
    return value


def sv_element(typ: object, value: object) -> object:
    if isinstance(typ, list):
        if not isinstance(value, list):
            raise SchemaInvalid("list")
        return [sv_element(typ[0], item) for item in value]
    if isinstance(typ, dict):
        if not isinstance(value, dict):
            raise SchemaInvalid("dict")
        done = {key: sv_element(typ[key], item) for key, item in value.items() if key in typ}
        sv_missing(typ, done)
        return done
    return sv_leaf(typ, value)


def sv_missing(origin: dict, done: dict) -> None:
    for key in set(origin) - set(done):
        typ = origin[key]
        if isinstance(typ, list) and typ:
            typ = typ[0]
        if not (isinstance(typ, str) and typ.endswith("?")):
            raise SchemaInvalid(f"missing {key}")


def sv_options(schema: dict, options: dict) -> dict:
    done = {key: sv_element(schema[key], value) for key, value in options.items() if key in schema}
    sv_missing(schema, done)
    return done


def sv_entries(*entries: object) -> dict:
    return sv_options({"modbus_tcp_endpoints": LIST_SCHEMA}, {"modbus_tcp_endpoints": list(entries)})


def test_the_list_option_defaults_to_empty_and_the_scalar_options_are_unchanged() -> None:
    options = CONFIG_DOC["options"]
    assert options["modbus_tcp_endpoints"] == []
    assert (options["modbus_tcp_enabled"], options["modbus_tcp_endpoint"], options["modbus_tcp_dial_timeout"]) == (
        False, "", "5s")
    assert (SCHEMA["modbus_tcp_enabled"], SCHEMA["modbus_tcp_endpoint"], SCHEMA["modbus_tcp_dial_timeout"]) == (
        "bool", "str", "str")
    assert isinstance(LIST_SCHEMA, list) and len(LIST_SCHEMA) == 1 and isinstance(ENTRY_SCHEMA, dict)


def test_the_whole_schema_stays_inside_the_supervisor_grammar_and_the_defaults_stay_saveable() -> None:
    sv_grammar(SCHEMA)
    assert sv_options(SCHEMA, CONFIG_DOC["options"]) == CONFIG_DOC["options"]
    # An installation saved before this option existed lacks it. A list of objects is never optional
    # in the Supervisor schema, so the shipped default [] (merged in by the Supervisor) is what keeps
    # such an installation saveable.
    saved_before = {key: value for key, value in CONFIG_DOC["options"].items() if key != "modbus_tcp_endpoints"}
    with pytest.raises(SchemaInvalid):
        sv_options(SCHEMA, saved_before)
    assert sv_options(SCHEMA, {**CONFIG_DOC["options"], **saved_before})["modbus_tcp_endpoints"] == []


def test_the_entry_schema_has_exactly_the_members_the_guard_reads() -> None:
    guard = load_guard()
    assert set(ENTRY_SCHEMA) == set(guard.ENTRY_KEYS)
    required = {key for key, typ in ENTRY_SCHEMA.items()
                if not (typ[0] if isinstance(typ, list) else typ).endswith("?")}
    assert required == set(guard.ENTRY_REQUIRED)
    assert ENTRY_SCHEMA["units"] == [f"int(1,{guard.MAX_UNIT})?"]
    for option, _, low, high in guard.PACING_OPTIONS:
        assert ENTRY_SCHEMA[option] == f"int({low},{high})?", option
    assert ENTRY_SCHEMA["endpoint"] == f"password(1,{guard.MAX_ENDPOINT_BYTES})"
    assert ENTRY_SCHEMA["family"] == "list(" + "|".join(guard.FAMILIES) + ")"


def test_the_contract_example_is_accepted_unchanged() -> None:
    assert sv_entries(FIRST_ENTRY, entry())["modbus_tcp_endpoints"] == [FIRST_ENTRY, entry()]
    assert sv_entries()["modbus_tcp_endpoints"] == []
    assert sv_entries(entry(units=[1, 2, 3], family="huawei.smartlogger"))  # a list of integers


@pytest.mark.parametrize(
    "bad",
    [
        entry(label=ABSENT), entry(family=ABSENT), entry(endpoint=ABSENT),
        entry(label="Roof_1"), entry(label="1roof"), entry(label="roof-"), entry(label="a.b"), entry(label=""),
        entry(label="a" * 33), entry(label=7), entry(label=["roof"]),
        entry(family="Sunspec"), entry(family="huawei"), entry(family=""), entry(family="huawei.inverter"),
        entry(endpoint=""), entry(endpoint="x" * 289), entry(endpoint=None),
        entry(dial_timeout="0s"), entry(dial_timeout="5"), entry(dial_timeout="5m"), entry(dial_timeout="05s"),
        entry(units=[0]), entry(units=[248]), entry(units=["a"]), entry(units="1"), entry(units=1),
        entry(pacing_gap_ms=49), entry(pacing_gap_ms=2001), entry(pacing_settle_ms=-1), entry(pacing_settle_ms=10001),
        entry(pacing_cycle_s=14), entry(pacing_cycle_s=3601), entry(pacing_backoff_floor_s=0),
        entry(pacing_backoff_floor_s=301), entry(pacing_backoff_ceiling_s=4), entry(pacing_backoff_ceiling_s=3601),
        entry(pacing_gap_ms="fast"), entry(pacing_gap_ms=None),
    ],
    ids=lambda bad: ",".join(f"{key}={str(value)[:12]}" for key, value in bad.items() if key != "endpoint"
                             or len(str(value)) < 4) or "empty",
)
def test_the_schema_rejects_an_entry_that_breaks_a_member_rule(bad: dict) -> None:
    with pytest.raises(SchemaInvalid):
        sv_entries(bad)


@pytest.mark.parametrize("bad", ["roof", {"label": "roof"}, 5, None])
def test_the_schema_rejects_a_list_or_entry_of_the_wrong_shape(bad: object) -> None:
    with pytest.raises(SchemaInvalid):
        sv_options({"modbus_tcp_endpoints": LIST_SCHEMA}, {"modbus_tcp_endpoints": bad})
    if bad is not None:
        with pytest.raises(SchemaInvalid):
            sv_entries(bad)


def test_the_supervisor_drops_unknown_members_and_coerces_integers_before_the_guard_sees_them() -> None:
    saved = sv_entries(entry(extra="dropped", pacing={"gap_ms": 1}, pacing_gap_ms="200", units=[True, "2"],
                             family="huawei.emma"))["modbus_tcp_endpoints"][0]
    assert saved == entry(pacing_gap_ms=200, units=[1, 2], family="huawei.emma")


def test_what_the_schema_cannot_say_is_left_to_the_guard(tmp_path: Path) -> None:
    guard = load_guard()
    cases = [
        ([entry(label=f"s{number}", endpoint=f"tcp://h{number}.example.invalid:1") for number in range(9)],
         "TOO_MANY_ENTRIES"),
        ([entry(), entry(endpoint="tcp://other.example.invalid:1")], "DUPLICATE_LABEL"),
        ([entry(), entry(label="ridge")], "DUPLICATE_ENDPOINT"),
        ([entry(dial_timeout="50ms")], "INVALID_TIMEOUT"),
        ([entry(pacing_backoff_floor_s=60, pacing_backoff_ceiling_s=30)], "INVALID_PACING"),
        ([entry(units=[1, 1], family="huawei.emma")], "INVALID_UNITS"),
        ([entry(units=[2])], "INVALID_UNITS"),
        ([entry(endpoint="tcp://no-port.example.invalid")], "INVALID_ENDPOINT"),
        ([entry(endpoint="tcp://u:p@h.example.invalid:1")], "INVALID_ENDPOINT"),
        ([entry(label="roof\n")], "INVALID_DOCUMENT"),  # the pattern's $ accepts a trailing newline
    ]
    for entries, category in cases:
        assert sv_entries(*entries)["modbus_tcp_endpoints"] == entries
        with pytest.raises(guard.ConfigRejection) as raised:
            guard.load_config(write_options(tmp_path, v2_options(*entries)))
        assert raised.value.category == category


@pytest.mark.parametrize(
    ("label", "valid"),
    [("default", True), ("roof", True), ("a", True), ("a1", True), ("site-a", True), ("a-b-c", True),
     ("x" * 32, True), ("a1-b2", True), ("a" * 33, False), ("", False), ("Roof", False), ("roof_1", False),
     ("1roof", False), ("roof-", False), ("-roof", False), ("roof--a", False), ("a.b", False),
     ("roof ", False), ("röof", False)],
)
def test_the_label_grammar_agrees_between_the_schema_and_the_guard(tmp_path: Path, label: str, valid: bool) -> None:
    guard = load_guard()
    try:
        sv_entries(entry(label=label))
        in_schema = True
    except SchemaInvalid:
        in_schema = False
    try:
        guard.load_config(write_options(tmp_path, v2_options(entry(label=label))))
        in_guard = True
    except guard.ConfigRejection:
        in_guard = False
    assert (in_schema, in_guard) == (valid, valid)


@pytest.mark.parametrize("timeout", ["100ms", "999ms", "1000ms", "5s", "30s", "30000ms", "99ms", "50ms", "0s", "31s",
                                     "5", "5m", "05s", "1.5s"])
def test_every_timeout_the_guard_accepts_passes_the_schema_pattern(tmp_path: Path, timeout: str) -> None:
    guard = load_guard()
    try:
        guard.load_config(write_options(tmp_path, v2_options(entry(dial_timeout=timeout))))
        accepted = True
    except guard.ConfigRejection:
        accepted = False
    try:
        sv_entries(entry(dial_timeout=timeout))
        pattern = True
    except SchemaInvalid:
        pattern = False
    assert pattern or not accepted  # the pattern is a first filter; the 100 ms to 30 s bound is the guard's


def test_the_option_translations_describe_exactly_the_schema_members() -> None:
    yaml = pytest.importorskip("yaml")
    translated = yaml.safe_load((ROOT / "helianthus/translations/en.yaml").read_text(encoding="utf-8"))
    option = translated["configuration"]["modbus_tcp_endpoints"]
    assert set(option) == {"name", "description", "fields"}
    assert set(option["fields"]) == set(ENTRY_SCHEMA)
    for member in option["fields"].values():
        assert set(member) == {"name", "description"} and all(isinstance(text, str) and text for text in member.values())
    assert set(translated["configuration"]) == {"modbus_tcp_endpoints"}


def test_the_option_documentation_names_every_member_category_and_limit() -> None:
    guard = load_guard()
    readme = (ROOT / "helianthus/README.md").read_text(encoding="utf-8")
    section = readme.split("## Several Modbus TCP endpoints", 1)[1].split("## Serial acquisition options", 1)[0]
    for member in ENTRY_SCHEMA:
        assert f"`{member}`" in section, member
    for category in guard.CATEGORIES:
        assert f"`{category}`" in section, category
    for family in guard.FAMILIES:
        assert f"`{family}`" in section, family
    for statement in ["-modbus-tcp-endpoints-file", "0600", "0700", "eight", "password field", "next add-on start",
                      "does not advertise"]:
        assert statement in section, statement
    for option, _, low, high in guard.PACING_OPTIONS:
        assert f"{low} to {high}" in section, option
    assert "`modbus_tcp_endpoints`" in readme.split("## Several Modbus TCP endpoints", 1)[0]
