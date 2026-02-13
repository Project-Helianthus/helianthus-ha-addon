#!/usr/bin/env python3
"""Deterministic smoke checklist for local HA add-on operator runs."""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import json
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlunsplit
from urllib.request import Request, urlopen

CHECK_CONNECTION_GRAPHQL = "CHECK_CONNECTION_GRAPHQL"
CHECK_CONNECTION_MCP = "CHECK_CONNECTION_MCP"
CHECK_LOG_STARTUP = "CHECK_LOG_STARTUP"
CHECK_LOG_TRANSPORT = "CHECK_LOG_TRANSPORT"
CHECK_LOG_PROXY_PROFILE = "CHECK_LOG_PROXY_PROFILE"
CHECK_LOG_PROXY_ENDPOINT = "CHECK_LOG_PROXY_ENDPOINT"
CHECK_LOG_GRAPHQL_ENDPOINT = "CHECK_LOG_GRAPHQL_ENDPOINT"
CHECK_LOG_SUBSCRIPTION_ENDPOINT = "CHECK_LOG_SUBSCRIPTION_ENDPOINT"
CHECK_LOG_MCP_ENDPOINT = "CHECK_LOG_MCP_ENDPOINT"

DEFAULT_GRAPHQL_PATH = "/graphql"
DEFAULT_SUBSCRIPTION_PATH = "/graphql/subscriptions"

TRIAGE = {
    CHECK_CONNECTION_GRAPHQL: "verify addon started and graphql_path/http_port are reachable",
    CHECK_CONNECTION_MCP: "verify mcp_path/http_port and supervisor host-network reachability",
    CHECK_LOG_STARTUP: "verify add-on process did not exit before gateway startup",
    CHECK_LOG_TRANSPORT: "verify transport/network/address options match local ebusd-tcp target",
    CHECK_LOG_PROXY_PROFILE: "verify proxy_profile is disabled, enh, or ens",
    CHECK_LOG_PROXY_ENDPOINT: "verify proxy_endpoint and proxy endpoint normalization",
    CHECK_LOG_GRAPHQL_ENDPOINT: "verify host/http_port/graphql_path options and restart add-on",
    CHECK_LOG_SUBSCRIPTION_ENDPOINT: "verify subscription_path and graphql_path normalization",
    CHECK_LOG_MCP_ENDPOINT: "verify mcp_path normalization and gateway startup options",
}


@dataclass(frozen=True)
class CheckResult:
    check: str
    ok: bool
    details: str
    triage: str


@dataclass(frozen=True)
class SmokeChecklist:
    version: str
    checks: list[CheckResult]

    @property
    def ok(self) -> bool:
        return all(item.ok for item in self.checks)

    def as_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "ok": self.ok,
            "checks": [asdict(item) for item in self.checks],
        }

    def as_lines(self) -> list[str]:
        lines = [f"HELIANTHUS_ADDON_SMOKE {self.version}"]
        for item in self.checks:
            state = "PASS" if item.ok else "FAIL"
            lines.append(f"[{state}] {item.check} :: {item.details} | triage={item.triage}")
        lines.append(f"OVERALL {'PASS' if self.ok else 'FAIL'}")
        return lines


def _post_json(url: str, payload: dict[str, Any], timeout: float) -> dict[str, Any]:
    raw = json.dumps(payload).encode("utf-8")
    request = Request(
        url,
        data=raw,
        headers={"content-type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            response_bytes = response.read()
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"http {exc.code}: {body}") from exc
    except URLError as exc:
        raise RuntimeError(f"connection error: {exc.reason}") from exc
    except TimeoutError as exc:
        raise RuntimeError("timeout") from exc

    try:
        decoded = json.loads(response_bytes.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"invalid json response: {exc}") from exc
    if not isinstance(decoded, dict):
        raise RuntimeError("response is not a json object")
    return decoded


def _check_graphql(graphql_url: str, timeout: float) -> CheckResult:
    try:
        response = _post_json(graphql_url, {"query": "{ __typename }", "variables": {}}, timeout)
    except RuntimeError as exc:
        return CheckResult(CHECK_CONNECTION_GRAPHQL, False, str(exc), TRIAGE[CHECK_CONNECTION_GRAPHQL])

    errors = response.get("errors")
    if isinstance(errors, list) and errors:
        return CheckResult(
            CHECK_CONNECTION_GRAPHQL,
            False,
            f"graphql errors={_join_messages(errors)}",
            TRIAGE[CHECK_CONNECTION_GRAPHQL],
        )
    data = response.get("data")
    typename = None if not isinstance(data, dict) else data.get("__typename")
    if not isinstance(typename, str) or typename.strip() == "":
        return CheckResult(
            CHECK_CONNECTION_GRAPHQL,
            False,
            "missing __typename field",
            TRIAGE[CHECK_CONNECTION_GRAPHQL],
        )
    return CheckResult(
        CHECK_CONNECTION_GRAPHQL,
        True,
        f"typename={typename}",
        "none",
    )


def _check_mcp(mcp_url: str, timeout: float) -> CheckResult:
    payload = {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}
    try:
        response = _post_json(mcp_url, payload, timeout)
    except RuntimeError as exc:
        return CheckResult(CHECK_CONNECTION_MCP, False, str(exc), TRIAGE[CHECK_CONNECTION_MCP])

    error = response.get("error")
    if isinstance(error, dict):
        message = str(error.get("message", "")).strip() or "rpc error"
        return CheckResult(
            CHECK_CONNECTION_MCP,
            False,
            f"rpc_error={message}",
            TRIAGE[CHECK_CONNECTION_MCP],
        )
    result = response.get("result")
    tools = None if not isinstance(result, dict) else result.get("tools")
    if not isinstance(tools, list) or len(tools) == 0:
        return CheckResult(
            CHECK_CONNECTION_MCP,
            False,
            "missing or empty tools list",
            TRIAGE[CHECK_CONNECTION_MCP],
        )
    return CheckResult(
        CHECK_CONNECTION_MCP,
        True,
        f"tools={len(tools)}",
        "none",
    )


def _check_marker(check: str, log_text: str, marker: str) -> CheckResult:
    if marker in log_text:
        return CheckResult(check, True, f'marker="{marker}"', "none")
    return CheckResult(
        check,
        False,
        f'missing marker="{marker}"',
        TRIAGE[check],
    )


def run_checklist(
    *,
    log_text: str,
    graphql_url: str,
    mcp_url: str,
    expected_transport: str,
    expected_network: str,
    expected_address: str,
    expected_proxy_profile_marker: str,
    expected_proxy_endpoint_marker: str,
    expected_graphql_marker: str,
    expected_subscription_marker: str,
    expected_mcp_marker: str,
    timeout: float,
) -> SmokeChecklist:
    checks = [
        _check_graphql(graphql_url, timeout),
        _check_mcp(mcp_url, timeout),
        _check_marker(CHECK_LOG_STARTUP, log_text, "Starting Helianthus gateway"),
        _check_marker(
            CHECK_LOG_TRANSPORT,
            log_text,
            f"Transport: {expected_transport} ({expected_network} {expected_address})",
        ),
        _check_marker(CHECK_LOG_PROXY_PROFILE, log_text, expected_proxy_profile_marker),
        _check_marker(CHECK_LOG_PROXY_ENDPOINT, log_text, expected_proxy_endpoint_marker),
        _check_marker(CHECK_LOG_GRAPHQL_ENDPOINT, log_text, expected_graphql_marker),
        _check_marker(CHECK_LOG_SUBSCRIPTION_ENDPOINT, log_text, expected_subscription_marker),
        _check_marker(CHECK_LOG_MCP_ENDPOINT, log_text, expected_mcp_marker),
    ]
    return SmokeChecklist(version="v1", checks=checks)


def _join_messages(items: list[Any]) -> str:
    messages: list[str] = []
    for item in items:
        if isinstance(item, dict):
            message = str(item.get("message", "")).strip()
            if message:
                messages.append(message)
        elif item:
            messages.append(str(item))
    return "; ".join(messages) if messages else "unknown"


def _normalize_path(path: str) -> str:
    normalized = path.strip() or "/"
    if not normalized.startswith("/"):
        normalized = f"/{normalized}"
    return normalized


def _build_url(host: str, port: int, path: str) -> str:
    return urlunsplit(("http", f"{host}:{port}", _normalize_path(path), "", ""))


def _normalize_proxy_profile(proxy_profile: str) -> str:
    normalized = proxy_profile.strip().lower()
    if normalized == "":
        return "disabled"
    return normalized


def _derive_proxy_endpoint_marker(proxy_profile: str, proxy_endpoint: str) -> str:
    normalized_endpoint = proxy_endpoint.strip()
    if proxy_profile in {"enh", "ens"}:
        if normalized_endpoint == "":
            return "(none)"
        if "://" in normalized_endpoint:
            return normalized_endpoint
        return f"{proxy_profile}://{normalized_endpoint}"
    if normalized_endpoint == "":
        return "(none)"
    return normalized_endpoint


def _derive_transport_marker(
    transport: str,
    network: str,
    address: str,
    proxy_profile: str,
    proxy_endpoint_marker: str,
) -> tuple[str, str, str]:
    expected_transport = transport.strip()
    expected_network = network.strip()
    expected_address = address.strip()
    if proxy_profile in {"enh", "ens"} and proxy_endpoint_marker != "(none)":
        return proxy_profile, "tcp", proxy_endpoint_marker
    return expected_transport, expected_network, expected_address


def _derive_subscription_path(graphql_path: str, subscription_path: str) -> str:
    normalized_graphql_path = _normalize_path(graphql_path)
    normalized_subscription_path = _normalize_path(subscription_path)
    if (
        normalized_subscription_path == DEFAULT_SUBSCRIPTION_PATH
        and normalized_graphql_path != DEFAULT_GRAPHQL_PATH
    ):
        return f"{normalized_graphql_path.rstrip('/')}/subscriptions"
    return normalized_subscription_path


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run deterministic smoke checklist for Helianthus HA add-on.",
    )
    parser.add_argument("--log-file", required=True, help="Path to exported add-on logs file.")
    parser.add_argument(
        "--transport",
        default="ebusd-tcp",
        help="Expected transport marker value.",
    )
    parser.add_argument(
        "--network",
        default="tcp",
        help="Expected network marker value.",
    )
    parser.add_argument(
        "--address",
        required=True,
        help="Expected transport address marker value (for example 192.168.100.2:9999).",
    )
    parser.add_argument(
        "--proxy-profile",
        default="disabled",
        help="Expected proxy profile marker value (disabled|enh|ens).",
    )
    parser.add_argument(
        "--proxy-endpoint",
        default="",
        help="Expected proxy endpoint marker value or host:port when proxy_profile is enabled.",
    )
    parser.add_argument("--host", default="127.0.0.1", help="Expected endpoint host in startup log markers.")
    parser.add_argument("--http-port", type=int, default=8080, help="Expected endpoint port in startup markers.")
    parser.add_argument("--graphql-path", default="/graphql", help="Expected graphql path in markers.")
    parser.add_argument(
        "--subscription-path",
        default="/graphql/subscriptions",
        help="Expected subscriptions path in markers.",
    )
    parser.add_argument("--mcp-path", default="/mcp", help="Expected mcp path in markers.")
    parser.add_argument("--timeout", type=float, default=10.0, help="Endpoint request timeout seconds.")
    parser.add_argument("--json", action="store_true", help="Output JSON instead of checklist text.")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    with open(args.log_file, "r", encoding="utf-8") as handle:
        log_text = handle.read()

    proxy_profile = _normalize_proxy_profile(args.proxy_profile)
    if proxy_profile not in {"disabled", "enh", "ens"}:
        raise SystemExit("--proxy-profile must be one of: disabled, enh, ens")
    proxy_endpoint_marker = _derive_proxy_endpoint_marker(proxy_profile, args.proxy_endpoint)
    expected_transport, expected_network, expected_address = _derive_transport_marker(
        args.transport,
        args.network,
        args.address,
        proxy_profile,
        proxy_endpoint_marker,
    )

    graphql_path = _normalize_path(args.graphql_path)
    subscription_path = _derive_subscription_path(graphql_path, args.subscription_path)
    graphql_url = _build_url(args.host, args.http_port, graphql_path)
    mcp_url = _build_url(args.host, args.http_port, args.mcp_path)
    subscription_url = _build_url(args.host, args.http_port, subscription_path)

    result = run_checklist(
        log_text=log_text,
        graphql_url=graphql_url,
        mcp_url=mcp_url,
        expected_transport=expected_transport,
        expected_network=expected_network,
        expected_address=expected_address,
        expected_proxy_profile_marker=f"Proxy profile: {proxy_profile}",
        expected_proxy_endpoint_marker=f"Proxy endpoint: {proxy_endpoint_marker}",
        expected_graphql_marker=f"GraphQL endpoint: {graphql_url}",
        expected_subscription_marker=f"Subscriptions endpoint: {subscription_url}",
        expected_mcp_marker=f"MCP endpoint: {mcp_url}",
        timeout=args.timeout,
    )

    if args.json:
        print(json.dumps(result.as_dict(), indent=2, sort_keys=True))
    else:
        for line in result.as_lines():
            print(line)
    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
