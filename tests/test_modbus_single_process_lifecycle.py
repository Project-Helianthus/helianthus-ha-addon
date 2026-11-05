import json
import os
import signal
import stat
import subprocess
import time
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / "helianthus/rootfs/etc/services.d/helianthus-gateway/run"
GUARD = ROOT / "helianthus/rootfs/usr/share/helianthus/modbus_runtime_guard.py"
DOCKERFILE = ROOT / "helianthus/Dockerfile"
README = ROOT / "helianthus/README.md"
CHANGELOG = ROOT / "helianthus/CHANGELOG.md"
ROOT_README = ROOT / "README.md"
SMOKE_RUNBOOK = ROOT / "SMOKE_RUNBOOK.md"
CONFIG = ROOT / "helianthus/config.json"


def test_enabled_and_disabled_modbus_share_one_direct_exec_lifecycle() -> None:
    run = RUN.read_text(encoding="utf-8")

    assert run.count('exec "${gateway_bin}" "${gateway_args[@]}"') == 1
    assert 'gateway_args+=("${modbus_args[@]}")' in run
    assert run.index('gateway_args+=("${modbus_args[@]}")') < run.index(
        'exec "${gateway_bin}" "${gateway_args[@]}"'
    )

    for removed in (
        "modbus_child_pid",
        "modbus_redactor_pids",
        "modbus_write_health",
        "modbus_runtime_ready",
        "modbus_run_current",
        "modbus_run_fallback",
        "MODBUS_RECOVERY_MAX_ATTEMPTS",
        "helianthus-gateway-fallback",
        "FALLBACK_ACTIVE",
        "RECOVERY_RETRY",
        "probe-readiness",
    ):
        assert removed not in run


def test_guard_validates_and_never_writes_the_single_line_endpoint_file() -> None:
    guard = GUARD.read_text(encoding="utf-8")

    assert 'commands.add_parser("validate")' in guard
    assert "write_endpoint_file" not in guard
    assert "endpoint_file" not in guard
    for removed in (
        'commands.add_parser("health")',
        'commands.add_parser("probe-readiness")',
        'commands.add_parser("redact")',
        "helianthus.modbus-addon-health.v1",
        "FALLBACK_STARTING",
        "RECOVERY_RETRY",
    ):
        assert removed not in guard


def test_container_packages_only_the_current_gateway_binary() -> None:
    dockerfile = DOCKERFILE.read_text(encoding="utf-8")

    assert "/out/gateway ./cmd/gateway" in dockerfile
    assert "gateway-fallback" not in dockerfile
    assert "helianthus-gateway-fallback" not in dockerfile


def test_readme_matches_fail_closed_gateway_override_policy() -> None:
    readme = README.read_text(encoding="utf-8")
    normalized_readme = " ".join(readme.split())
    run = RUN.read_text(encoding="utf-8")

    assert "Persistent gateway executable overrides are not supported" in normalized_readme
    assert "remove that file or symlink before startup" in normalized_readme
    assert "Persistent gateway binary override is not supported" in run
    assert "/data/helianthus-gateway` overrides" not in readme


def test_release_history_keeps_0647_immutable_and_records_0648() -> None:
    changelog = CHANGELOG.read_text(encoding="utf-8")
    release_0648 = changelog.split("## 0.6.48", 1)[1].split("## 0.6.47", 1)[0]
    release_0647 = changelog.split("## 0.6.47", 1)[1].split("## 0.6.46", 1)[0]

    assert "7f1cbea90e0b189486febc656632e9e7430c8500" in release_0648
    assert "225f3d96fee3422bc565870f946af19fac42d471" in release_0647
    assert "7f1cbea90e0b189486febc656632e9e7430c8500" not in release_0647


def test_current_operator_docs_match_release_authority() -> None:
    version = json.loads(CONFIG.read_text(encoding="utf-8"))["version"]
    root_readme = ROOT_README.read_text(encoding="utf-8")
    smoke = SMOKE_RUNBOOK.read_text(encoding="utf-8")

    assert f"Release `{version}` packages" in root_readme
    assert f"For release `{version}`" in smoke
    assert "active Modbus runtime state" not in root_readme


def test_pre_exec_cleanup_retires_health_and_removes_unconsumed_endpoint() -> None:
    run = RUN.read_text(encoding="utf-8")

    assert 'legacy_modbus_health_file="/data/modbus-runtime-health.json"' in run
    assert 'rm -f -- "${legacy_modbus_health_file}"' in run
    assert run.index('rm -f -- "${legacy_modbus_health_file}"') < run.index(
        "transport=$(bashio::config 'transport')"
    )
    assert "trap cleanup_modbus_pre_exec EXIT" in run
    assert 'rm -f -- "${modbus_endpoint_file}"' in run
    assert run.index("trap cleanup_modbus_pre_exec EXIT") < run.index(
        'exec "${gateway_bin}" "${gateway_args[@]}"'
    )


def test_validator_cannot_recreate_endpoint_after_wrapper_termination(
    tmp_path: Path,
) -> None:
    run = RUN.read_text(encoding="utf-8")
    assert "if modbus_eval=$(python3" not in run
    assert 'python3 "${modbus_guard}" validate' in run
    assert '> "${modbus_eval_file}"' in run
    assert run.index('python3 "${modbus_guard}" validate') < run.index(
        'mv -f -- "${modbus_endpoint_staging}" "${modbus_endpoint_file}"'
    )
    terminating_traps = run.split("trap 'exit 130' INT", 1)[1]
    assert terminating_traps.index("abort_modbus_pre_exec_on_signal") < (
        terminating_traps.index("unset MODBUS_TCP_ENDPOINT")
    )

    wrapper = tmp_path / "run-under-test.sh"
    guard = tmp_path / "delayed-guard.py"
    marker = tmp_path / "guard-started"
    endpoint = tmp_path / "modbus-endpoint"
    options = tmp_path / "options.json"
    options.write_text("{}", encoding="utf-8")

    guard.write_text(
        "#!/usr/bin/env python3\n"
        "import argparse, os, pathlib, time\n"
        "parser = argparse.ArgumentParser()\n"
        "parser.add_argument('command')\n"
        "parser.add_argument('--options')\n"
        "args = parser.parse_args()\n"
        "pathlib.Path(os.environ['TEST_GUARD_MARKER']).write_text('started', encoding='utf-8')\n"
        "time.sleep(1)\n"
        "pathlib.Path(os.environ['TEST_ENDPOINT']).write_text('tcp://192.0.2.40:502', encoding='utf-8')\n"
        "print(\"MODBUS_TCP_ENABLED='true'\")\n"
        "print(\"MODBUS_TCP_ENDPOINT='tcp://192.0.2.40:502'\")\n"
        "print(\"MODBUS_TCP_DIAL_TIMEOUT='5s'\")\n",
        encoding="utf-8",
    )
    guard.chmod(guard.stat().st_mode | stat.S_IXUSR)

    prelude = r'''
bashio::config() { printf '\n'; }
bashio::exit.nok() { exit 1; }
'''
    wrapper.write_text(prelude + "\n" + RUN.read_text(encoding="utf-8"), encoding="utf-8")

    env = os.environ | {
        "HELIANTHUS_MODBUS_RUNTIME_GUARD": str(guard),
        "HELIANTHUS_MODBUS_OPTIONS_PATH": str(options),
        "HELIANTHUS_MODBUS_ENDPOINT_FILE": str(endpoint),
        "TEST_GUARD_MARKER": str(marker),
        "TEST_ENDPOINT": str(endpoint),
    }
    process = subprocess.Popen(
        ["bash", str(wrapper)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
    )
    try:
        deadline = time.monotonic() + 2
        while not marker.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert marker.exists(), "validator did not start"
        process.send_signal(signal.SIGTERM)
        process.communicate(timeout=3)
        time.sleep(1.2)
        assert not endpoint.exists()
    finally:
        if process.poll() is None:
            process.kill()
            process.communicate(timeout=1)


# --------------------------------------------------------------------------------------
# Several Modbus TCP endpoints (the modbus_tcp_endpoints list). The real wrapper runs under
# stubbed bashio functions with a recording gateway substitute; no Supervisor, Home
# Assistant, network or device is involved, and every host is a synthetic reserved name.

BOM = ROOT / "helianthus/bom.json"
SUPPORT = ROOT / "helianthus/rootfs/usr/share/helianthus"
LIST_FLAG = "modbus-tcp-endpoints-file"
GUID = "12345678-1234-4234-9234-123456789abc"
ADAPTER = "adapter.example.invalid:9999"
V1_ENDPOINT = "tcp://v1-zqx.example.invalid:502"
FIRST = {"label": "default", "family": "sunspec", "endpoint": "tcp://zqx-a.example.invalid:502"}
SECOND = {"label": "site-b", "family": "huawei.emma", "endpoint": "tcp://zqx-b.example.invalid:1502",
          "dial_timeout": "750ms", "units": [3, 1], "pacing_gap_ms": 300, "pacing_cycle_s": 60}
SECOND_DOCUMENT = {"label": "site-b", "family": "huawei.emma", "endpoint": "tcp://zqx-b.example.invalid:1502",
                   "dial_timeout": "750ms", "units": [3, 1], "pacing": {"gap_ms": 300, "cycle_s": 60}}

BASHIO_PRELUDE = r'''
bashio::config() {
  jq -r --arg key "$1" \
    'if has($key) and .[$key] != null then .[$key] | tostring else "" end' \
    "${TEST_SUPERVISOR_OPTIONS}"
}
bashio::var.true() {
  case "$(printf '%s' "$1" | tr '[:upper:]' '[:lower:]')" in
    true|1|yes|on) return 0 ;;
    *) return 1 ;;
  esac
}
bashio::log.info() { printf 'INFO: %s\n' "$*" >> "${TEST_LOG}"; }
bashio::log.warning() { printf 'WARN: %s\n' "$*" >> "${TEST_LOG}"; }
bashio::log.error() { printf 'ERROR: %s\n' "$*" >> "${TEST_LOG}"; }
bashio::exit.nok() { printf 'NOK: %s\n' "$*" >&2; exit 1; }
'''

FAKE_GATEWAY = '''#!/usr/bin/env python3
import json, os, pathlib, stat, sys
if sys.argv[1:] == ["--help"]:
    flags = json.loads(pathlib.Path(os.environ["TEST_BOM"]).read_text(encoding="utf-8"))["gateway_cli_flags"]
    flags = (set(flags) | set(json.loads(os.environ["TEST_ADVERTISE"]))) - set(json.loads(os.environ["TEST_HELP_HIDDEN"]))
    sys.stderr.write("Usage of gateway:\\n" + "".join("  -" + flag + " string\\n" for flag in sorted(flags)))
    raise SystemExit(0)
seen = {}
for name in json.loads(os.environ["TEST_WATCH"]):
    path = pathlib.Path(name)
    seen[name] = None if not path.exists() else {
        "mode": stat.S_IMODE(path.stat().st_mode), "parent_mode": stat.S_IMODE(path.parent.stat().st_mode),
        "is_file": path.is_file() and not path.is_symlink(), "text": path.read_text(encoding="utf-8")}
with pathlib.Path(os.environ["TEST_CALLS"]).open("a", encoding="utf-8") as calls:
    calls.write(json.dumps({"argv": sys.argv[1:], "env": dict(os.environ), "files": seen}) + "\\n")
'''


def _bom_flags() -> set[str]:
    return set(json.loads(BOM.read_text(encoding="utf-8"))["gateway_cli_flags"])


def _wrapper_run(
    tmp_path: Path, overrides: dict, *, supported: bool = True, hidden: tuple[str, ...] = (),
    seed: dict[str, str] | None = None, guard: Path | None = None,
) -> dict:
    """Run the real wrapper once. `supported` decides whether the gateway advertises the list flag."""
    config = json.loads(CONFIG.read_text(encoding="utf-8"))
    data, run_dir = tmp_path / "data", tmp_path / "run"
    data.mkdir()
    run_dir.mkdir()
    options = data / "options.json"
    options.write_text(json.dumps({**config["options"], "adapter_direct_address": ADAPTER, **overrides}), encoding="utf-8")
    (data / "runtime_state.json").write_text(
        json.dumps({"schema_version": 1, "meta": {"instance_guid": GUID}}), encoding="utf-8")
    for name, body in (seed or {}).items():
        (run_dir / name).write_text(body, encoding="utf-8")

    gateway = tmp_path / "gateway.py"
    gateway.write_text(FAKE_GATEWAY, encoding="utf-8")
    gateway.chmod(gateway.stat().st_mode | stat.S_IXUSR)
    text = RUN.read_text(encoding="utf-8")
    for old, new in (
        ("/usr/local/bin/helianthus-gateway", "${TEST_GATEWAY}"),
        ("mktemp /tmp/helianthus-modbus-validate.XXXXXX", 'mktemp "${TEST_DATA}/modbus-validate.XXXXXX"'),
        ("/data/", "${TEST_DATA}/"),
    ):
        assert old in text, old
        text = text.replace(old, new)
    wrapper = tmp_path / "run-under-test.sh"
    wrapper.write_text(BASHIO_PRELUDE + "\n" + text, encoding="utf-8")

    document = run_dir / "modbus-endpoints.json"
    v1_file = run_dir / "modbus-endpoint"
    calls, log = tmp_path / "calls.jsonl", tmp_path / "wrapper.log"
    env = {key: value for key, value in os.environ.items() if not key.startswith(("TEST_", "HELIANTHUS_"))}
    env.update({
        "TEST_GATEWAY": str(gateway), "TEST_DATA": str(data), "TEST_SUPERVISOR_OPTIONS": str(options),
        "TEST_BOM": str(BOM), "TEST_CALLS": str(calls), "TEST_LOG": str(log),
        "TEST_ADVERTISE": json.dumps([LIST_FLAG] if supported else []),
        "TEST_HELP_HIDDEN": json.dumps(sorted(set(hidden) | (set() if supported else {LIST_FLAG}))),
        "TEST_WATCH": json.dumps([str(document), f"{document}.tmp", str(v1_file)]),
        "HELIANTHUS_RUNTIME_STATE_WRAPPER": str(SUPPORT / "check_runtime_state_wrapper.py"),
        "HELIANTHUS_RUNTIME_STATE_PATH": str(data / "runtime_state.json"),
        "HELIANTHUS_LEGACY_INSTANCE_GUID_PATH": str(data / "instance_guid"),
        "HELIANTHUS_MIGRATION_MARKER_PATH": str(data / ".helianthus_migration_required"),
        "HELIANTHUS_MODBUS_RUNTIME_GUARD": str(guard or GUARD),
        "HELIANTHUS_MODBUS_ENDPOINT_FILE": str(v1_file),
        "HELIANTHUS_MODBUS_ENDPOINTS_FILE": str(document),
        "HELIANTHUS_SERIAL_CAN_GUARD": str(SUPPORT / "serial_can_options.py"),
        "HELIANTHUS_M2M_IDENTITY_VALIDATOR": str(SUPPORT / "m2m_tls_identity.py"),
    })
    result = subprocess.run(["bash", str(wrapper)], env=env, capture_output=True, text=True, check=False, timeout=30)
    launches = [json.loads(line) for line in calls.read_text(encoding="utf-8").splitlines()] if calls.exists() else []
    return {
        "result": result, "launches": launches, "run_dir": run_dir, "document": document, "v1_file": v1_file,
        "log": log.read_text(encoding="utf-8") if log.exists() else "", "tmp": tmp_path,
    }


def _case(tmp_path: Path, name: str) -> Path:
    path = tmp_path / name
    path.mkdir()
    return path


def _argv(run: dict) -> list[str]:
    assert run["result"].returncode == 0, run["result"].stderr
    assert len(run["launches"]) == 1
    return run["launches"][0]["argv"]


def _normalized(run: dict) -> list[str]:
    """The gateway arguments with this run's temporary directory made comparable."""
    return [argument.replace(str(run["tmp"]), "<tmp>") for argument in _argv(run)]


def _everything_visible(run: dict) -> str:
    """All text a run exposed: wrapper streams, wrapper log, gateway arguments and gateway environment."""
    launches = run["launches"]
    return "\n".join([run["result"].stdout, run["result"].stderr, run["log"]]
                     + [" ".join(launch["argv"]) for launch in launches]
                     + [f"{key}={value}" for launch in launches for key, value in launch["env"].items()])


V1_FLAGS = ["-modbus-tcp-enabled=true", "-modbus-tcp-endpoint-file", "<tmp>/run/modbus-endpoint",
            "-modbus-tcp-dial-timeout", "5s"]


def test_a_v1_only_configuration_passes_exactly_the_current_gateway_arguments(tmp_path: Path) -> None:
    baseline = _normalized(_wrapper_run(_case(tmp_path, "disabled"), {}))
    v1 = _wrapper_run(_case(tmp_path, "v1"), {"modbus_tcp_enabled": True, "modbus_tcp_endpoint": V1_ENDPOINT})
    empty = _wrapper_run(_case(tmp_path, "empty"), {"modbus_tcp_enabled": True, "modbus_tcp_endpoint": V1_ENDPOINT,
                                                    "modbus_tcp_endpoints": []})

    for run in (v1, empty):
        expected = [argument.replace("<tmp>", str(run["tmp"])) for argument in baseline]
        assert _argv(run)[: len(expected)] == expected
        assert [a.replace(str(run["tmp"]), "<tmp>") for a in _argv(run)[len(expected):]] == V1_FLAGS
        assert LIST_FLAG not in " ".join(_argv(run))
        seen = run["launches"][0]["files"]
        assert seen[str(run["v1_file"])] == {"mode": 0o600, "parent_mode": 0o700, "is_file": True, "text": V1_ENDPOINT}
        assert seen[str(run["document"])] is None
        assert "INFO: Modbus TCP runtime: enabled" in run["log"].splitlines()
    assert _normalized(v1) == _normalized(empty)
    assert "-modbus-tcp-enabled=true" not in baseline


def test_the_disabled_path_is_inert_and_inspects_no_modbus_flag_support(tmp_path: Path) -> None:
    hidden = tuple(sorted(f for f in _bom_flags() | {LIST_FLAG} if f.startswith("modbus-")))
    assert LIST_FLAG in hidden
    baseline = _wrapper_run(_case(tmp_path, "base"), {})
    stale = {"modbus_tcp_endpoint": "tcp://op:secret@bad", "modbus_tcp_dial_timeout": "stale",
             "modbus_tcp_endpoints": [{"label": "Bad"}, None, 5]}
    off = _wrapper_run(_case(tmp_path, "off"), {"modbus_tcp_enabled": False, **stale}, hidden=hidden)

    assert _normalized(off) == _normalized(baseline)
    assert not any("modbus" in argument for argument in _argv(off))
    assert set(off["launches"][0]["files"].values()) == {None}
    assert sorted(path.name for path in off["run_dir"].iterdir()) == []
    assert "INFO: Modbus TCP runtime: disabled" in off["log"].splitlines()
    assert "secret" not in _everything_visible(off)


def test_a_list_passes_only_the_document_path_and_materializes_the_exact_document(tmp_path: Path) -> None:
    disabled = _wrapper_run(_case(tmp_path, "base"), {})
    run = _wrapper_run(_case(tmp_path, "v2"), {"modbus_tcp_enabled": True, "modbus_tcp_endpoints": [FIRST, SECOND]})

    baseline = [a.replace("<tmp>", str(run["tmp"])) for a in _normalized(disabled)]
    assert _argv(run) == baseline + ["-modbus-tcp-endpoints-file", str(run["document"])]
    assert not {"-modbus-tcp-enabled=true", "-modbus-tcp-endpoint-file", "-modbus-tcp-dial-timeout"} & set(_argv(run))
    seen = run["launches"][0]["files"]
    assert seen[str(run["v1_file"])] is None
    assert seen[str(run["document"])] == {
        "mode": 0o600, "parent_mode": 0o700, "is_file": True,
        "text": json.dumps({"contract": "helianthus.modbus-tcp-endpoints.v2",
                            "endpoints": [FIRST, SECOND_DOCUMENT]}, separators=(",", ":"))}
    assert sorted(path.name for path in run["run_dir"].iterdir()) == ["modbus-endpoints.json"]
    assert "INFO: Modbus TCP runtime: enabled (endpoint list)" in run["log"].splitlines()
    assert "INFO: Modbus TCP runtime: enabled" not in run["log"].splitlines()


def test_no_endpoint_value_reaches_output_arguments_or_environment(tmp_path: Path) -> None:
    ok = _wrapper_run(_case(tmp_path, "ok"), {"modbus_tcp_enabled": True, "modbus_tcp_endpoints": [FIRST, SECOND]})
    assert ok["result"].returncode == 0 and len(ok["launches"]) == 1
    runs = [ok]
    cases = {
        "mixed": {"modbus_tcp_endpoint": V1_ENDPOINT, "modbus_tcp_endpoints": [FIRST]},
        "invalid-endpoint": {"modbus_tcp_endpoints": [FIRST, {**SECOND, "endpoint": "tcp://u:p@zqx-b.example.invalid"}]},
        "duplicate-endpoint": {"modbus_tcp_endpoints": [FIRST, {**SECOND, "endpoint": FIRST["endpoint"]}]},
        "duplicate-label": {"modbus_tcp_endpoints": [FIRST, {**SECOND, "label": "default"}]},
    }
    for name, overrides in cases.items():
        runs.append(_wrapper_run(_case(tmp_path, name), {"modbus_tcp_enabled": True, **overrides}))
    runs.append(_wrapper_run(_case(tmp_path, "unsupported"),
                             {"modbus_tcp_enabled": True, "modbus_tcp_endpoints": [FIRST]}, supported=False))
    for run in runs:
        visible = _everything_visible(run)
        for leaked in ("zqx", "tcp://", "topsecret", V1_ENDPOINT):
            assert leaked not in visible.replace(str(run["document"]), "").replace(str(run["v1_file"]), "")
    assert "zqx" in ok["launches"][0]["files"][str(ok["document"])]["text"]  # the document is the one carrier


def test_a_gateway_without_the_list_flag_refuses_the_list_before_launch(tmp_path: Path) -> None:
    run = _wrapper_run(tmp_path, {"modbus_tcp_enabled": True, "modbus_tcp_endpoints": [FIRST]}, supported=False)

    assert run["result"].returncode == 1 and run["launches"] == []
    assert run["result"].stderr.strip().splitlines()[-1] == (
        "NOK: gateway does not support the Modbus TCP endpoint list; remove modbus_tcp_endpoints or install an "
        "add-on release with a gateway that supports it")
    assert not run["document"].exists() and not Path(f"{run['document']}.tmp").exists()
    assert not run["v1_file"].exists()


@pytest.mark.parametrize("overrides", [
    {"modbus_tcp_enabled": True, "modbus_tcp_endpoint": V1_ENDPOINT},
    {"modbus_tcp_enabled": False},
], ids=["v1", "disabled"])
def test_earlier_endpoint_material_is_gone_before_the_gateway_starts(tmp_path: Path, overrides: dict) -> None:
    run = _wrapper_run(tmp_path, overrides, seed={"modbus-endpoints.json": "stale document",
                                                  "modbus-endpoints.json.tmp": "stale staging"})
    seen = run["launches"][0]["files"]
    assert seen[str(run["document"])] is None and seen[f"{run['document']}.tmp"] is None
    assert _argv(run)


def test_a_gateway_without_the_list_flag_still_runs_v1_and_disabled(tmp_path: Path) -> None:
    for name, overrides in (("v1", {"modbus_tcp_enabled": True, "modbus_tcp_endpoint": V1_ENDPOINT}),
                            ("empty", {"modbus_tcp_enabled": True, "modbus_tcp_endpoint": V1_ENDPOINT,
                                       "modbus_tcp_endpoints": []}),
                            ("off", {"modbus_tcp_enabled": False, "modbus_tcp_endpoints": [FIRST]})):
        run = _wrapper_run(_case(tmp_path, name), overrides, supported=False)
        assert run["result"].returncode == 0, (name, run["result"].stderr)
        assert LIST_FLAG not in " ".join(_argv(run))


@pytest.mark.parametrize(
    ("overrides", "line"),
    [
        ({"modbus_tcp_endpoint": V1_ENDPOINT, "modbus_tcp_endpoints": [FIRST]}, "MIXED_CONFIGURATION"),
        ({"modbus_tcp_dial_timeout": "10s", "modbus_tcp_endpoints": [FIRST]}, "MIXED_CONFIGURATION"),
        ({"modbus_tcp_endpoints": [FIRST, {**SECOND, "family": "Huawei"}]}, "UNKNOWN_FAMILY (entry 1)"),
        ({"modbus_tcp_endpoints": [FIRST, {**SECOND, "label": "default"}]}, "DUPLICATE_LABEL"),
        ({"modbus_tcp_endpoints": [{**FIRST, "units": [2]}]}, "INVALID_UNITS (entry 0)"),
    ],
    ids=["mixed-endpoint", "mixed-timeout", "unknown-family", "duplicate-label", "invalid-units"],
)
def test_an_invalid_or_mixed_list_stops_startup_with_a_categorical_message(
    tmp_path: Path, overrides: dict, line: str
) -> None:
    run = _wrapper_run(tmp_path, {"modbus_tcp_enabled": True, **overrides},
                       seed={"modbus-endpoints.json": "stale document", "modbus-endpoints.json.tmp": "stale staging",
                             "modbus-endpoint": "tcp://stale.example.invalid:1"})

    assert run["result"].returncode == 1 and run["launches"] == []
    assert f"invalid Modbus TCP configuration: {line}" in run["result"].stderr.splitlines()
    assert "NOK: Modbus TCP options failed atomic validation; endpoint remains redacted" in run["result"].stderr
    assert sorted(path.name for path in run["run_dir"].iterdir()) == []  # stale material is gone first


def test_a_failed_materialization_stops_startup_and_leaves_no_material(tmp_path: Path) -> None:
    guard = tmp_path / "failing-guard.py"
    guard.write_text(
        "import argparse, pathlib, sys\n"
        "parser = argparse.ArgumentParser()\n"
        "parser.add_argument('command')\n"
        "parser.add_argument('--options')\n"
        "parser.add_argument('--document')\n"
        "args = parser.parse_args()\n"
        "if args.command == 'validate':\n"
        "    print(\"MODBUS_TCP_ENABLED='true'\\nMODBUS_TCP_ENDPOINT=''\\nMODBUS_TCP_DIAL_TIMEOUT='5s'\\nMODBUS_TCP_CONFIG='v2'\")\n"
        "else:\n"
        "    pathlib.Path(args.document + '.tmp').write_text('partial', encoding='utf-8')\n"
        "    sys.exit(2)\n", encoding="utf-8")
    run = _wrapper_run(_case(tmp_path, "fail"), {"modbus_tcp_enabled": True, "modbus_tcp_endpoints": [FIRST]}, guard=guard)

    assert run["result"].returncode == 1 and run["launches"] == []
    assert "NOK: Modbus TCP endpoint list could not be materialized; endpoints remain redacted" in run["result"].stderr
    assert sorted(path.name for path in run["run_dir"].iterdir()) == []


def test_an_unknown_selection_from_the_validator_is_incomplete(tmp_path: Path) -> None:
    guard = tmp_path / "odd-guard.py"
    guard.write_text(
        "print(\"MODBUS_TCP_ENABLED='true'\\nMODBUS_TCP_ENDPOINT=''\\nMODBUS_TCP_DIAL_TIMEOUT='5s'\\nMODBUS_TCP_CONFIG='v3'\")\n",
        encoding="utf-8")
    run = _wrapper_run(_case(tmp_path, "odd"), {"modbus_tcp_enabled": True}, guard=guard)
    assert run["result"].returncode == 1 and run["launches"] == []
    assert "NOK: Modbus TCP validator returned an incomplete result" in run["result"].stderr


def test_a_terminated_wrapper_never_leaves_the_endpoints_document_behind(tmp_path: Path) -> None:
    guard = tmp_path / "delayed-guard.py"
    marker = tmp_path / "materialize-started"
    document = tmp_path / "modbus-endpoints.json"
    options = tmp_path / "options.json"
    options.write_text("{}", encoding="utf-8")
    guard.write_text(
        "#!/usr/bin/env python3\n"
        "import argparse, os, pathlib, time\n"
        "parser = argparse.ArgumentParser()\n"
        "parser.add_argument('command')\n"
        "parser.add_argument('--options')\n"
        "parser.add_argument('--document')\n"
        "args = parser.parse_args()\n"
        "if args.command == 'validate':\n"
        "    print(\"MODBUS_TCP_ENABLED='true'\\nMODBUS_TCP_ENDPOINT=''\\nMODBUS_TCP_DIAL_TIMEOUT='5s'\\nMODBUS_TCP_CONFIG='v2'\")\n"
        "else:\n"
        "    pathlib.Path(os.environ['TEST_GUARD_MARKER']).write_text('started', encoding='utf-8')\n"
        "    time.sleep(1)\n"
        "    pathlib.Path(args.document + '.tmp').write_text('staged', encoding='utf-8')\n"
        "    pathlib.Path(args.document).write_text('document', encoding='utf-8')\n",
        encoding="utf-8",
    )
    guard.chmod(guard.stat().st_mode | stat.S_IXUSR)
    wrapper = tmp_path / "run-under-test.sh"
    wrapper.write_text("bashio::config() { printf '\\n'; }\nbashio::exit.nok() { exit 1; }\n\n"
                       + RUN.read_text(encoding="utf-8"), encoding="utf-8")
    env = os.environ | {
        "HELIANTHUS_MODBUS_RUNTIME_GUARD": str(guard),
        "HELIANTHUS_MODBUS_OPTIONS_PATH": str(options),
        "HELIANTHUS_MODBUS_ENDPOINT_FILE": str(tmp_path / "modbus-endpoint"),
        "HELIANTHUS_MODBUS_ENDPOINTS_FILE": str(document),
        "TEST_GUARD_MARKER": str(marker),
    }
    process = subprocess.Popen(["bash", str(wrapper)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env)
    try:
        deadline = time.monotonic() + 3
        while not marker.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert marker.exists(), "materialization did not start"
        process.send_signal(signal.SIGTERM)
        process.communicate(timeout=5)
        time.sleep(0.3)
        assert process.returncode == 143
        assert not document.exists() and not Path(f"{document}.tmp").exists()
    finally:
        if process.poll() is None:
            process.kill()
            process.communicate(timeout=1)


def test_the_wrapper_names_the_list_flag_once_and_still_ends_in_one_exec() -> None:
    run = RUN.read_text(encoding="utf-8")
    assert run.count(f'gateway_supports_flag "{LIST_FLAG}"') == 1
    assert run.count(f"-{LIST_FLAG} ") == 1
    assert run.count('exec "${gateway_bin}" "${gateway_args[@]}"') == 1
    assert run.rstrip().splitlines()[-1] == 'exec "${gateway_bin}" "${gateway_args[@]}"'
    assert run.index(f'gateway_supports_flag "{LIST_FLAG}"') < run.index('gateway_args+=("${modbus_args[@]}")')
    assert run.index('python3 "${modbus_guard}" materialize') < run.index("trap 'exit 143' TERM")
    assert 'rm -f -- "${modbus_endpoints_file}" "${modbus_endpoints_staging}"' in run


def test_the_guard_source_keeps_the_single_line_endpoint_file_with_the_wrapper() -> None:
    guard = GUARD.read_text(encoding="utf-8")
    assert "endpoint_file" not in guard
    assert 'commands.add_parser("materialize")' in guard
