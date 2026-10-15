"""Packaging-only reproduction for #148; synthetic process results are not writes."""

from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]
SUPPORT = ROOT / "helianthus/rootfs/usr/share/helianthus"
BOM = ROOT / "helianthus/bom.json"
GUID = "12345678-1234-4234-9234-123456789abc"


@pytest.mark.parametrize("config_apply", ["false", "true", "null"])
@pytest.mark.parametrize("source_addr", ["auto", "0x71"])
@pytest.mark.parametrize("exit_code", [0, 23])
def test_parameter_write_options_and_process_result_offline(
    tmp_path: Path, config_apply: str, source_addr: str, exit_code: int,
) -> None:
    # Reuse the source-address wrapper harness underlying the existing migration
    # tests; extend the fake to record help probes separately from runtime exec.
    spec = importlib.util.spec_from_file_location(
        "parameter_write_harness", ROOT / "scripts/check_source_addr_wrapper.py"
    )
    assert spec is not None and spec.loader is not None
    harness = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(harness)
    wrapper = tmp_path / "wrapper.sh"
    harness._write_test_wrapper(wrapper)
    data = tmp_path / "data"
    data.mkdir()
    wrapper.write_text(wrapper.read_text().replace("/data/", f"{data}/"))
    options = tmp_path / "options.json"
    options.write_text("{}")
    runtime_state = data / "runtime_state.json"
    original_state = json.dumps({"schema_version": 1, "meta": {"instance_guid": GUID}})
    runtime_state.write_text(original_state)
    legacy_state = data / "source_addr.last"
    legacy_state.write_text("synthetic rollback marker\n")
    calls = tmp_path / "calls.jsonl"
    gateway = tmp_path / "fake-gateway"
    harness._write_executable(gateway, '''#!/usr/bin/env python3
import json
import os
from pathlib import Path
import sys

with Path(os.environ["TEST_CALLS"]).open("a") as capture:
    capture.write(json.dumps(sys.argv[1:]) + "\\n")
if sys.argv[1:] == ["--help"]:
    flags = json.loads(Path(os.environ["TEST_BOM"]).read_text())["gateway_cli_flags"]
    # Advertise only the compatibility probes used by this scenario, as in the
    # existing harness. This is a CLI fixture, not the real gateway help output.
    probes = {"instance-guid", "instance-guid-source", "semantic-cache-path",
              "enable-static-seed-table", "startup-source-override",
              "startup-source-override-validate"}
    sys.stderr.write("\\n".join("-" + flag for flag in flags if flag in probes) + "\\n")
    sys.exit(0)
sys.stdout.write("synthetic response\\n")
sys.stderr.write("synthetic diagnostic\\n")
sys.exit(int(os.environ["TEST_EXIT_CODE"]))
''')
    env = {key: value for key, value in os.environ.items()
           if not key.startswith(("TEST_", "HELIANTHUS_"))}
    env.update({
        "TEST_GATEWAY_BIN": str(gateway),
        "TEST_GATEWAY_OVERRIDE_BIN": str(tmp_path / "absent-override"),
        "TEST_INSTANCE_GUID_FILE": str(data / "instance_guid"),
        "TEST_LEGACY_SOURCE_ADDR_STATE_FILE": str(legacy_state),
        "TEST_LOG_FILE": str(tmp_path / "wrapper.log"),
        "TEST_ADAPTER_DIRECT_ENABLED": "true",
        "TEST_ADAPTER_DIRECT_ADDRESS": "adapter.example.invalid:9999",
        "TEST_SOURCE_ADDR": source_addr,
        "TEST_MDNS": "false",
        "TEST_PASSIVE_CONFIG_DIRECT_APPLY": config_apply,
        "TEST_CALLS": str(calls),
        "TEST_BOM": str(BOM),
        "TEST_EXIT_CODE": str(exit_code),
        "HELIANTHUS_OPTIONS_PATH": str(options),
        "HELIANTHUS_RUNTIME_STATE_WRAPPER": str(SUPPORT / "check_runtime_state_wrapper.py"),
        "HELIANTHUS_RUNTIME_STATE_PATH": str(runtime_state),
        "HELIANTHUS_LEGACY_INSTANCE_GUID_PATH": str(data / "instance_guid"),
        "HELIANTHUS_MIGRATION_MARKER_PATH": str(data / "migration-marker"),
        "HELIANTHUS_MODBUS_RUNTIME_GUARD": str(SUPPORT / "modbus_runtime_guard.py"),
        "HELIANTHUS_MODBUS_OPTIONS_PATH": str(options),
        "HELIANTHUS_MODBUS_ENDPOINT_FILE": str(data / "modbus-endpoint"),
        "HELIANTHUS_SERIAL_CAN_GUARD": str(SUPPORT / "serial_can_options.py"),
    })
    result = subprocess.run(
        ["bash", str(wrapper)], env=env, capture_output=True, text=True,
        check=False, timeout=20,
    )
    assert result.returncode == exit_code, result.stderr
    assert result.stdout == "synthetic response\n"
    assert result.stderr.endswith("synthetic diagnostic\n")
    invocations = [json.loads(line) for line in calls.read_text().splitlines()]
    runtime_calls = [args for args in invocations if args != ["--help"]]
    source_args = (["-source-addr", "auto"] if source_addr == "auto" else [
        "-startup-source-override", source_addr, "-startup-source-override-validate=true",
    ])
    expected = [
        "-transport", "adapter-direct", "-network", "tcp",
        "-address", "adapter-direct://adapter.example.invalid:9999",
        *source_args, "-scan-request-timeout", "400ms",
        "-http-addr", "0.0.0.0:8080", "-graphql-path", "/graphql",
        "-subscription-path", "/graphql/subscriptions", "-mcp-path", "/mcp",
        "-mdns=false", "-mdns-instance", "helianthus", "-instance-guid", GUID,
        "-instance-guid-source", "runtime_state", "-broadcast=true",
        "-read-timeout", "5s", "-write-timeout", "5s", "-dial-timeout", "5s",
        "-observe-first-enabled=true", "-passive-state-direct-apply=true",
        f"-passive-config-direct-apply={'true' if config_apply == 'true' else 'false'}",
        "-external-write-policy", "record_only", "-enable-static-seed-table=false",
        "-semantic-cache-path", str(data / "semantic_cache.json"),
        "-proxy-listen", "0.0.0.0:19001",
    ]
    # Exact argv catches added write/intent flags, duplicated flags and retries.
    assert runtime_calls == [expected]
    assert invocations[-1] == expected
    flags = set(json.loads(BOM.read_text())["gateway_cli_flags"])
    assert all(arg[1:].split("=", 1)[0] in flags for arg in expected if arg.startswith("-"))
    assert runtime_state.read_text() == original_state
    assert legacy_state.read_text() == "synthetic rollback marker\n"
    assert not (data / "migration-marker").exists()
