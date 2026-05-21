#!/usr/bin/env python3
"""Validate source-address wrapper migration behavior."""

from __future__ import annotations

import json
import os
from pathlib import Path
import stat
import subprocess
import tempfile


REPO_ROOT = Path(__file__).resolve().parents[1]
RUN_SCRIPT = REPO_ROOT / "helianthus/rootfs/etc/services.d/helianthus-gateway/run"
RUNTIME_STATE_WRAPPER = REPO_ROOT / "helianthus/rootfs/usr/share/helianthus/check_runtime_state_wrapper.py"
DOCKERFILE = REPO_ROOT / "helianthus/Dockerfile"
BUILD_WORKFLOW = REPO_ROOT / ".github/workflows/build.yml"
TOP_README = REPO_ROOT / "README.md"
ADDON_README = REPO_ROOT / "helianthus/README.md"

VALID_INSTANCE_GUID = "12345678-1234-4234-9234-123456789abc"
MIN_GATEWAY_WITH_STARTUP_SOURCE_OVERRIDE = "267d243fe3305d04a2d41376215ae462edac9eed"

BASHIO_PRELUDE = r'''
bashio::config() {
  case "$1" in
    transport) printf '%s\n' "${TEST_TRANSPORT:-enh}" ;;
    network) printf '%s\n' "${TEST_NETWORK:-tcp}" ;;
    address) printf '%s\n' "${TEST_ADDRESS:-203.0.113.10:9999}" ;;
    proxy_profile) printf '%s\n' "${TEST_PROXY_PROFILE:-disabled}" ;;
    proxy_endpoint) printf '%s\n' "${TEST_PROXY_ENDPOINT:-}" ;;
    host) printf '%s\n' "${TEST_HOST:-127.0.0.1}" ;;
    port) printf '%s\n' "${TEST_PORT:-8080}" ;;
    path) printf '%s\n' "${TEST_PATH:-/graphql}" ;;
    http_port) printf '%s\n' "${TEST_HTTP_PORT:-8080}" ;;
    graphql_path) printf '%s\n' "${TEST_GRAPHQL_PATH:-/graphql}" ;;
    subscription_path) printf '%s\n' "${TEST_SUBSCRIPTION_PATH:-/graphql/subscriptions}" ;;
    mcp_path) printf '%s\n' "${TEST_MCP_PATH:-/mcp}" ;;
    mdns) printf '%s\n' "${TEST_MDNS:-true}" ;;
    mdns_instance) printf '%s\n' "${TEST_MDNS_INSTANCE:-helianthus}" ;;
    broadcast) printf '%s\n' "${TEST_BROADCAST:-true}" ;;
    source_addr) printf '%s\n' "${TEST_SOURCE_ADDR:-auto}" ;;
    scan_request_timeout) printf '%s\n' "${TEST_SCAN_REQUEST_TIMEOUT:-400ms}" ;;
    read_timeout) printf '%s\n' "${TEST_READ_TIMEOUT:-5s}" ;;
    write_timeout) printf '%s\n' "${TEST_WRITE_TIMEOUT:-5s}" ;;
    dial_timeout) printf '%s\n' "${TEST_DIAL_TIMEOUT:-5s}" ;;
    adapter_direct_enabled) printf '%s\n' "${TEST_ADAPTER_DIRECT_ENABLED:-false}" ;;
    adapter_direct_address) printf '%s\n' "${TEST_ADAPTER_DIRECT_ADDRESS:-}" ;;
    proxy_listen_addr) printf '%s\n' "${TEST_PROXY_LISTEN_ADDR:-0.0.0.0:19001}" ;;
    observe_first_enabled) printf '%s\n' "${TEST_OBSERVE_FIRST_ENABLED:-true}" ;;
    passive_state_direct_apply) printf '%s\n' "${TEST_PASSIVE_STATE_DIRECT_APPLY:-true}" ;;
    passive_config_direct_apply) printf '%s\n' "${TEST_PASSIVE_CONFIG_DIRECT_APPLY:-false}" ;;
    external_write_policy) printf '%s\n' "${TEST_EXTERNAL_WRITE_POLICY:-record_only}" ;;
    *) printf '\n' ;;
  esac
}

bashio::var.true() {
  case "$(printf '%s' "$1" | tr '[:upper:]' '[:lower:]')" in
    true|1|yes|on) return 0 ;;
    *) return 1 ;;
  esac
}

bashio::log.info() {
  printf 'INFO: %s\n' "$*" >> "${TEST_LOG_FILE}"
}

bashio::log.warning() {
  printf 'WARN: %s\n' "$*" >> "${TEST_LOG_FILE}"
}

bashio::exit.nok() {
  printf 'NOK: %s\n' "$*" >&2
  exit 1
}
'''


def _run(command: list[str], *, cwd: Path = REPO_ROOT) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, cwd=cwd, text=True, capture_output=True, check=False)


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _write_executable(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def _write_gateway_stub(path: Path, mode: str) -> None:
    help_by_mode = {
        # `old` predates startup-source-override AND -instance-guid-source —
        # the bash run script must suppress -instance-guid-source via the
        # AD27 compatibility gate (Codex P2 follow-up on PR #127).
        "old": "Usage of gateway:\n  -source-addr string\n",
        # `new` advertises both the M2_GATEWAY_LOADER -instance-guid-source
        # flag and the source-override flags. The bash gate must pass through
        # the provenance tag in this mode.
        "new": (
            "Usage of gateway:\n"
            "  -source-addr string\n"
            "  -startup-source-override string\n"
            "  -startup-source-override-validate\n"
            "  -instance-guid-source string\n"
        ),
    }
    script = f"""#!/usr/bin/env python3
from pathlib import Path
import os
import sys

mode = {mode!r}
if "--help" in sys.argv:
    if mode == "unknown":
        sys.stderr.write("help unavailable\\n")
        sys.exit(2)
    sys.stderr.write({help_by_mode.get(mode, "")!r})
    sys.exit(0)

Path(os.environ["TEST_ARGV_FILE"]).write_text("\\n".join(sys.argv[1:]) + "\\n", encoding="utf-8")
sys.exit(0)
"""
    _write_executable(path, script)


def _write_test_wrapper(path: Path) -> None:
    text = RUN_SCRIPT.read_text(encoding="utf-8")
    text = text.replace("/usr/local/bin/helianthus-gateway", "${TEST_GATEWAY_BIN}")
    text = text.replace("/data/helianthus-gateway", "${TEST_GATEWAY_OVERRIDE_BIN}")
    text = text.replace("/data/instance_guid", "${TEST_INSTANCE_GUID_FILE}")
    text = text.replace("/data/source_addr.last", "${TEST_LEGACY_SOURCE_ADDR_STATE_FILE}")
    path.write_text(BASHIO_PRELUDE + "\n" + text, encoding="utf-8")


def _run_wrapper_case(
    *,
    source_addr: str,
    gateway_mode: str,
    existing_state: str | None = None,
    transport: str = "enh",
    adapter_direct_enabled: bool = True,
    expect_success: bool = True,
) -> tuple[list[str], str, bool, str, str]:
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        state_file = tmp / "source_addr.last"
        if existing_state is not None:
            state_file.write_text(existing_state, encoding="utf-8")

        wrapper = tmp / "run-under-test.sh"
        gateway = tmp / "gateway-stub.py"
        argv_file = tmp / "argv.txt"
        log_file = tmp / "wrapper.log"
        # The bash run script delegates instance_guid resolution to the
        # Python wrapper (M6_HA_ADDON_MIGRATION). For these source-address
        # tests we want the wrapper to take the AD09b case (1) read-precedence
        # path: pre-write a schema-valid runtime_state.json and redirect the
        # wrapper's path env vars into the temp sandbox so it reads our test
        # GUID without touching /data/.
        runtime_state_file = tmp / "runtime_state.json"
        runtime_state_file.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "meta": {
                        "instance_guid": VALID_INSTANCE_GUID,
                        "written_at": "2026-05-10T00:00:00Z",
                    },
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        instance_guid_file = tmp / "instance_guid"
        # Legacy file deliberately absent; runtime_state.json is the source.
        legacy_marker_file = tmp / "migration_marker"
        _write_test_wrapper(wrapper)
        _write_gateway_stub(gateway, gateway_mode)

        env = os.environ.copy()
        env.update(
            {
                "TEST_ARGV_FILE": str(argv_file),
                "TEST_GATEWAY_BIN": str(gateway),
                "TEST_GATEWAY_OVERRIDE_BIN": str(tmp / "missing-override"),
                "TEST_INSTANCE_GUID_FILE": str(instance_guid_file),
                "TEST_LOG_FILE": str(log_file),
                "TEST_SOURCE_ADDR": source_addr,
                "TEST_LEGACY_SOURCE_ADDR_STATE_FILE": str(state_file),
                "TEST_TRANSPORT": transport,
                "TEST_ADAPTER_DIRECT_ENABLED": "true" if adapter_direct_enabled else "false",
                "TEST_ADAPTER_DIRECT_ADDRESS": "203.0.113.10:9999",
                # M6 wrapper integration: redirect bash + Python sides at the
                # in-repo wrapper script and the temp-sandboxed runtime-state
                # paths so the test runs on a host without /data/ (CI).
                "HELIANTHUS_RUNTIME_STATE_WRAPPER": str(RUNTIME_STATE_WRAPPER),
                "HELIANTHUS_RUNTIME_STATE_PATH": str(runtime_state_file),
                "HELIANTHUS_LEGACY_INSTANCE_GUID_PATH": str(instance_guid_file),
                "HELIANTHUS_MIGRATION_MARKER_PATH": str(legacy_marker_file),
            },
        )

        result = subprocess.run(["bash", str(wrapper)], cwd=REPO_ROOT, env=env, text=True, capture_output=True, check=False)
        if expect_success:
            _assert(
                result.returncode == 0,
                f"wrapper case source_addr={source_addr!r} gateway_mode={gateway_mode!r} failed\n"
                f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}",
            )
        else:
            _assert(
                result.returncode != 0,
                f"wrapper case source_addr={source_addr!r} gateway_mode={gateway_mode!r} unexpectedly succeeded",
            )

        argv = argv_file.read_text(encoding="utf-8").splitlines() if argv_file.exists() else []
        logs = log_file.read_text(encoding="utf-8") if log_file.exists() else ""
        state_exists = state_file.exists()
        state_content = state_file.read_text(encoding="utf-8") if state_exists else ""
        return argv, logs, state_exists, state_content, result.stderr


def _check_static_run_script() -> None:
    syntax = _run(["bash", "-n", str(RUN_SCRIPT)])
    _assert(syntax.returncode == 0, f"run script shell syntax failed:\n{syntax.stderr}")

    text = RUN_SCRIPT.read_text(encoding="utf-8")
    dockerfile_text = DOCKERFILE.read_text(encoding="utf-8")
    build_workflow_text = BUILD_WORKFLOW.read_text(encoding="utf-8")
    legacy_log_term = "gentle" + "-join"
    forbidden_terms = [
        "load_source_addr_state",
        "persist_source_addr_state",
        "persist_source_addr=",
        "persisted_source_addr",
        legacy_log_term,
        "reusing persisted source address",
        "source_addr_state_file",
        "legacy -source-addr compatibility path",
        "without wrapper-side persistence",
    ]
    for term in forbidden_terms:
        _assert(term not in text, f"run script still contains forbidden source-state term: {term}")

    _assert(
        'source_addr_args=(-source-addr "auto")' in text,
        "source_addr=auto must pass the gateway default source-selection intent",
    )
    _assert(
        'source_addr_args=(-source-addr "${source_addr_intent}")' in text,
        "transport=ebusd-tcp exact source must preserve ebusd-compatible -source-addr input",
    )
    _assert(
        "startup-source-override" in text and "startup-source-override-validate" in text,
        "exact source validation flags must be used by the wrapper",
    )
    _assert(
        f"EBUSGATEWAY_VERSION={MIN_GATEWAY_WITH_STARTUP_SOURCE_OVERRIDE}" in dockerfile_text,
        "pinned gateway must advertise startup-source-override for exact source_addr",
    )
    _assert(
        f"EBUSGATEWAY_VERSION={MIN_GATEWAY_WITH_STARTUP_SOURCE_OVERRIDE}" in build_workflow_text,
        "published image workflow must use a gateway that advertises startup-source-override",
    )
    _assert(
        "upgrade helianthus-gateway or set source_addr=auto" in text,
        "exact source config must fail closed when validate-only startup input is unavailable",
    )
    _assert(
        "rollback only" in text,
        "run script must log that leftover source state is rollback-only",
    )


def _check_docs() -> None:
    forbidden_doc_claims = [
        "gentle-join",
        "gentle join",
        "stores the last explicit source address used by the gateway",
        "reuses the persisted address",
        "reusing persisted source address",
        "currently pinned gateway receives the legacy",
        "legacy -source-addr compatibility path",
    ]
    for path in (TOP_README, ADDON_README):
        text = path.read_text(encoding="utf-8")
        lower = text.lower()
        for claim in forbidden_doc_claims:
            _assert(claim not in lower, f"{path.relative_to(REPO_ROOT)} still claims wrapper-side persisted source reuse")
        _assert("source_addr=auto" in text, f"{path.relative_to(REPO_ROOT)} must document source_addr=auto")
        _assert("rollback" in lower, f"{path.relative_to(REPO_ROOT)} must document rollback behavior for legacy state")
        _assert(
            "ebusd-compatible" in lower and "transport=ebusd-tcp" in text,
            f"{path.relative_to(REPO_ROOT)} must document the ebusd-tcp exact source exception",
        )


def _check_runtime_cases() -> None:
    argv, logs, state_exists, state_content, _ = _run_wrapper_case(
        source_addr="auto",
        gateway_mode="old",
        existing_state="0xf7\n",
    )
    _assert("-source-addr" in argv, "auto case must pass -source-addr to old gateway")
    _assert(argv[argv.index("-source-addr") + 1] == "auto", "auto case must not pass legacy state file contents")
    _assert("0xf7" not in argv, "auto case leaked persisted raw source as active source config")
    _assert(state_exists and state_content == "0xf7\n", "auto case must not rewrite existing source state file")
    _assert("gateway default source-selection policy" in logs, "auto case must log gateway default policy")
    _assert("rollback only" in logs, "auto case must log rollback-only state-file handling")
    _assert(
        "-instance-guid-source" not in argv,
        "old gateway lacking AD27 flag must not receive -instance-guid-source (compatibility gate)",
    )
    _assert(
        "does not support -instance-guid-source" in logs,
        "old gateway path must log the AD27 compatibility-gate warning",
    )

    argv, logs, state_exists, _state_content, _ = _run_wrapper_case(
        source_addr="0x71",
        gateway_mode="new",
        existing_state="0xf7\n",
    )
    _assert("-startup-source-override" in argv, "new gateway exact source must use startup override")
    _assert(argv[argv.index("-startup-source-override") + 1] == "0x71", "new gateway exact source changed operator intent")
    _assert("-startup-source-override-validate=true" in argv, "new gateway exact source must request validate-only startup override")
    _assert("-source-addr" not in argv, "new gateway exact source must not also use legacy -source-addr")
    _assert(state_exists, "new gateway exact source must not remove rollback-only source state file")
    _assert("rollback only" in logs, "new gateway exact source must log rollback-only state-file handling")
    _assert(
        "-instance-guid-source" in argv,
        "new gateway advertising AD27 flag must receive -instance-guid-source",
    )
    _assert(
        argv[argv.index("-instance-guid-source") + 1] == "runtime_state",
        "new gateway must receive the resolver-emitted identity-source tag",
    )

    argv, logs, state_exists, state_content, _ = _run_wrapper_case(
        source_addr="0x71",
        gateway_mode="new",
        existing_state="0xf7\n",
        transport="ebusd-tcp",
        adapter_direct_enabled=False,
    )
    _assert("-source-addr" in argv, "ebusd-tcp exact source must use ebusd-compatible -source-addr")
    _assert(argv[argv.index("-source-addr") + 1] == "0x71", "ebusd-tcp exact source changed operator intent")
    _assert("-startup-source-override" not in argv, "ebusd-tcp exact source must not use direct-transport startup override")
    _assert(
        state_exists and state_content == "0xf7\n",
        "ebusd-tcp exact source must not rewrite rollback-only source state file",
    )
    _assert("ebusd-compatible gateway source input" in logs, "ebusd-tcp exact source must log ebusd-compatible handling")

    argv, logs, state_exists, state_content, stderr = _run_wrapper_case(
        source_addr="0x71",
        gateway_mode="old",
        existing_state="0xf7\n",
        expect_success=False,
    )
    _assert(argv == [], "old gateway exact source must fail before invoking gateway")
    _assert("-source-addr" not in argv, "old gateway exact source must not use legacy active source input")
    _assert(state_exists and state_content == "0xf7\n", "old gateway failure must not rewrite existing source state file")
    _assert("requires gateway startup source override validation support" in stderr, "old gateway failure must explain missing startup override support")

    argv, _logs, state_exists, _state_content, stderr = _run_wrapper_case(
        source_addr="0x71",
        gateway_mode="unknown",
        expect_success=False,
    )
    _assert(argv == [], "unknown gateway exact source must fail before invoking gateway")
    _assert("-source-addr" not in argv, "unknown gateway exact source must not use legacy active source input")
    _assert(not state_exists, "unknown gateway exact source must not create source state file")
    _assert("requires gateway startup source override validation support" in stderr, "unknown gateway failure must explain missing startup override support")


def main() -> int:
    try:
        _check_static_run_script()
        _check_docs()
        _check_runtime_cases()
    except AssertionError as exc:
        print(f"Source address wrapper check: FAIL ({exc})")
        return 1

    print("Source address wrapper check passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
