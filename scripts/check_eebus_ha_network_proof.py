#!/usr/bin/env python3
"""Validate MSP-03C eeBUS HA runtime networking proof artifacts."""

from __future__ import annotations

import argparse
import copy
import ipaddress
import json
from pathlib import Path
import re
import sys
import tempfile
from typing import Any

CONTRACT = "helianthus.eebus.ha-network-proof.v0"
ISSUE = "MSP-03C"
REPO = "Project-Helianthus/helianthus-ha-addon"
REQUIRED_CASES = ("EEBUS-G05", "EEBUS-G06", "EEBUS-G07", "EEBUS-G08", "EEBUS-G09")
EXPECTED_SHIP_SERVICE_TYPE = "_ship._tcp"
REDACTED_DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{12}$")
GIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
MAC_RE = re.compile(r"\b[0-9a-fA-F]{2}(?::[0-9a-fA-F]{2}){5}\b")
PEM_RE = re.compile(r"-----BEGIN [A-Z ]+-----|PRIVATE KEY", re.IGNORECASE)
SERIAL_RE = re.compile(r"\b(?:[0-9]{2}-){3,}[0-9A-Za-z-]{4,}\b")
SECRET_PATH_RE = re.compile(
    r"(^|[._\[\]-])(password|passwd|secret|token|api_token|private_key|client_secret|authorization|bearer)([._\[\]-]|$)",
    re.IGNORECASE,
)
SECRET_VALUE_RE = re.compile(
    r"(password|secret|token=|bearer\s+[a-z0-9._-]+|gh[pousr]_[a-z0-9_]+|eyj[a-z0-9_-]+\.[a-z0-9_-]+\.[a-z0-9_-]+)",
    re.IGNORECASE,
)
CONTRADICTION_KEY_RE = re.compile(
    r"(wildcard|bridge|ingress|web_ui|admin|production_trust|host_network|host_dbus|same_container|same_host|actual_bind|network_mode)",
    re.IGNORECASE,
)
LAB_EVIDENCE_RE = re.compile(r"^(msp03c-[a-z0-9][a-z0-9-]{5,80}|sha256:[0-9a-f]{12})$")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate a redacted MSP-03C eebus-transport-gate-v0 artifact",
    )
    parser.add_argument(
        "--artifact",
        default="scripts/fixtures/eebus_ha_network_proof_contract_pass.json",
        help="Path to the proof artifact JSON",
    )
    parser.add_argument(
        "--mode",
        choices=("contract", "lab"),
        default="contract",
        help="contract validates the public fixture shape; lab also requires lab_run mode",
    )
    parser.add_argument(
        "--self-test",
        action="store_true",
        help="Run validator regression tests against known-bad mutations",
    )
    return parser.parse_args()


def load_artifact(path: str) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("artifact root must be a JSON object")
    return payload


def validate_artifact(payload: dict[str, Any], *, mode: str) -> list[str]:
    errors: list[str] = []

    errors.extend(_validate_redaction(payload))

    if payload.get("contract") != CONTRACT:
        errors.append(f"contract mismatch: got={payload.get('contract')!r} expected={CONTRACT}")
    if payload.get("issue") != ISSUE:
        errors.append(f"issue mismatch: got={payload.get('issue')!r} expected={ISSUE}")
    if payload.get("repo") != REPO:
        errors.append(f"repo mismatch: got={payload.get('repo')!r} expected={REPO}")
    if not _non_empty_string(payload.get("generated_at")):
        errors.append("generated_at missing")
    if payload.get("result") != "PASS":
        errors.append(f"result must be PASS, got={payload.get('result')!r}")

    errors.extend(_validate_unknown_fields(payload))

    artifact_mode = payload.get("mode")
    if mode == "lab":
        if artifact_mode != "lab_run":
            errors.append(f"lab validation requires mode=lab_run, got={artifact_mode!r}")
        errors.extend(_validate_lab_run(payload))
    elif artifact_mode not in {"contract_fixture", "lab_run"}:
        errors.append(f"invalid mode: {artifact_mode!r}")

    required_cases = payload.get("required_cases")
    if required_cases != list(REQUIRED_CASES):
        errors.append(f"required_cases mismatch: got={required_cases!r}")

    topology = _dict(payload.get("topology"))
    errors.extend(_validate_topology(topology))

    security = _dict(payload.get("security"))
    errors.extend(_validate_security(security))

    credential_store = _dict(payload.get("credential_store"))
    errors.extend(_validate_credential_store(credential_store))

    cases = payload.get("cases")
    if not isinstance(cases, list):
        errors.append("cases must be a list")
        return errors

    by_id: dict[str, dict[str, Any]] = {}
    for idx, case in enumerate(cases):
        if not isinstance(case, dict):
            errors.append(f"cases[{idx}] must be an object")
            continue
        case_id = case.get("id")
        if not isinstance(case_id, str):
            errors.append(f"cases[{idx}].id missing")
            continue
        if case_id in by_id:
            errors.append(f"duplicate case id: {case_id}")
            continue
        by_id[case_id] = case

    actual_ids = tuple(by_id.keys())
    if actual_ids != REQUIRED_CASES:
        errors.append(f"case order mismatch: got={actual_ids!r} expected={REQUIRED_CASES!r}")

    for case_id in REQUIRED_CASES:
        case = by_id.get(case_id)
        if case is None:
            errors.append(f"missing case: {case_id}")
            continue
        if case.get("status") != "PASS":
            errors.append(f"{case_id}: status must be PASS")
        evidence = case.get("evidence")
        if not isinstance(evidence, list) or not evidence:
            errors.append(f"{case_id}: evidence must be a non-empty list")
        elif not all(_non_empty_string(item) for item in evidence):
            errors.append(f"{case_id}: evidence entries must be non-empty strings")

    if "EEBUS-G05" in by_id:
        errors.extend(_validate_g05(by_id["EEBUS-G05"]))
    if "EEBUS-G06" in by_id:
        errors.extend(_validate_g06(by_id["EEBUS-G06"]))
    if "EEBUS-G07" in by_id:
        errors.extend(_validate_g07(by_id["EEBUS-G07"]))
    if "EEBUS-G08" in by_id:
        errors.extend(_validate_g08(by_id["EEBUS-G08"]))
    if "EEBUS-G09" in by_id:
        errors.extend(_validate_g09(by_id["EEBUS-G09"], credential_store))

    return errors


def _validate_topology(topology: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    addon = _dict(topology.get("ha_addon"))
    lan_peer = _dict(topology.get("lan_peer"))

    if addon.get("host_network") is not True:
        errors.append("topology.ha_addon.host_network must be true for LAN-side proof")
    if addon.get("host_dbus") is not False:
        errors.append("topology.ha_addon.host_dbus must be false for current add-on negative DBus proof")
    if addon.get("same_container_or_bridge_only") is not False:
        errors.append("same-container or same-bridge proof is not sufficient")

    if lan_peer.get("scope") != "external_lan":
        errors.append("topology.lan_peer.scope must be external_lan")
    if lan_peer.get("same_host") is not False:
        errors.append("topology.lan_peer.same_host must be false")
    if not _non_empty_string(lan_peer.get("address_ref")):
        errors.append("topology.lan_peer.address_ref missing")

    return errors


def _validate_security(security: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    booleans = {
        "wildcard_bind_allowed": False,
        "unexpected_bridge_exposure": False,
        "ingress_reachable": False,
        "web_ui_reachable": False,
        "vendor_restricted": False,
    }
    for key, expected in booleans.items():
        if security.get(key) is not expected:
            errors.append(f"security.{key} must be {str(expected).lower()}")
    if security.get("admin_surface") != "none":
        errors.append("security.admin_surface must be none for MSP-03C")
    return errors


def _validate_lab_run(payload: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    lab = _dict(payload.get("lab"))
    if not lab:
        return ["lab_run artifacts require a lab object"]

    required_strings = (
        "repo_branch",
        "addon_build_id",
        "collector_command_log_ref",
        "external_lan_peer_namespace_ref",
        "listener_socket_ref",
        "mdns_browse_ref",
        "mdns_resolve_ref",
        "restart_ref",
        "collected_at",
    )
    for key in required_strings:
        if not _non_empty_string(lab.get(key)):
            errors.append(f"lab.{key} missing")

    repo_commit = lab.get("repo_commit")
    if not isinstance(repo_commit, str) or not GIT_SHA_RE.fullmatch(repo_commit):
        errors.append("lab.repo_commit must be a 40-character lowercase git SHA")

    if not (
        _non_empty_string(lab.get("configured_interface_ref"))
        or _non_empty_string(lab.get("configured_subnet_ref"))
    ):
        errors.append("lab requires configured_interface_ref or configured_subnet_ref")

    evidence_ids = lab.get("case_evidence_ids")
    if not isinstance(evidence_ids, dict):
        errors.append("lab.case_evidence_ids must be an object")
    else:
        for case_id in REQUIRED_CASES:
            ids = evidence_ids.get(case_id)
            if not isinstance(ids, list) or not ids:
                errors.append(f"lab.case_evidence_ids.{case_id} must be a non-empty list")
                continue
            if not all(_non_empty_string(item) for item in ids):
                errors.append(f"lab.case_evidence_ids.{case_id} entries must be non-empty strings")
            for item in ids:
                if isinstance(item, str) and not LAB_EVIDENCE_RE.fullmatch(item):
                    errors.append(
                        f"lab.case_evidence_ids.{case_id} entry must be an msp03c evidence id or sha256:12hex",
                    )

    for key in ("collector_command_log_ref", "listener_socket_ref", "mdns_browse_ref", "mdns_resolve_ref", "restart_ref"):
        value = lab.get(key)
        if isinstance(value, str) and not LAB_EVIDENCE_RE.fullmatch(value):
            errors.append(f"lab.{key} must be an msp03c evidence id or sha256:12hex")

    return errors


def _validate_credential_store(store: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if store.get("path") != "/data/eebus-proof":
        errors.append("credential_store.path must be /data/eebus-proof")
    if store.get("class") != "disposable_proof":
        errors.append("credential_store.class must be disposable_proof")
    if store.get("production_trust_written") is not False:
        errors.append("credential_store.production_trust_written must be false")
    if store.get("persistent_across_restart") is not True:
        errors.append("credential_store.persistent_across_restart must be true")
    if store.get("symlink_checked") is not True:
        errors.append("credential_store.symlink_checked must be true")
    if store.get("path_traversal_checked") is not True:
        errors.append("credential_store.path_traversal_checked must be true")

    permissions = _dict(store.get("permissions"))
    if permissions.get("directory") != "0700":
        errors.append("credential_store.permissions.directory must be 0700")
    if permissions.get("files") != "0600":
        errors.append("credential_store.permissions.files must be 0600")

    pre = store.get("pre_restart_identity_ref")
    post = store.get("post_restart_identity_ref")
    if not _is_redacted_digest(pre):
        errors.append("credential_store.pre_restart_identity_ref must be sha256:12hex")
    if not _is_redacted_digest(post):
        errors.append("credential_store.post_restart_identity_ref must be sha256:12hex")
    if pre != post:
        errors.append("credential_store identity ref must survive restart")

    return errors


def _validate_g05(case: dict[str, Any]) -> list[str]:
    listener = _dict(case.get("listener"))
    errors: list[str] = []
    if listener.get("bind_policy") not in {"configured_interface", "configured_subnet"}:
        errors.append("EEBUS-G05: listener.bind_policy must be configured_interface or configured_subnet")
    if listener.get("wildcard_bind") is not False:
        errors.append("EEBUS-G05: wildcard_bind must be false")
    if listener.get("unexpected_bridge_exposure") is not False:
        errors.append("EEBUS-G05: unexpected_bridge_exposure must be false")
    if listener.get("lan_tcp_reachable") is not True:
        errors.append("EEBUS-G05: lan_tcp_reachable must be true")
    return errors


def _validate_g06(case: dict[str, Any]) -> list[str]:
    mdns = _dict(case.get("mdns"))
    errors: list[str] = []
    if mdns.get("lan_peer_resolved") is not True:
        errors.append("EEBUS-G06: lan_peer_resolved must be true")
    if mdns.get("peer_scope") != "external_lan":
        errors.append("EEBUS-G06: peer_scope must be external_lan")
    if mdns.get("service_type") != EXPECTED_SHIP_SERVICE_TYPE:
        errors.append(f"EEBUS-G06: service_type must be {EXPECTED_SHIP_SERVICE_TYPE}")
    return errors


def _validate_g07(case: dict[str, Any]) -> list[str]:
    negative = _dict(case.get("negative"))
    errors: list[str] = []
    if negative.get("mdns_disabled_absent") is not True:
        errors.append("EEBUS-G07: mdns_disabled_absent must be true")
    if negative.get("avahi_dbus_state") != "degraded_explicit":
        errors.append("EEBUS-G07: avahi_dbus_state must be degraded_explicit")
    if negative.get("pairing_closed_absent_or_ttl_expired") is not True:
        errors.append("EEBUS-G07: pairing_closed_absent_or_ttl_expired must be true")
    return errors


def _validate_g08(case: dict[str, Any]) -> list[str]:
    manual = _dict(case.get("manual_endpoint"))
    errors: list[str] = []
    if manual.get("configured") is not True:
        errors.append("EEBUS-G08: manual_endpoint.configured must be true")
    if manual.get("requires_discovery") is not False:
        errors.append("EEBUS-G08: manual_endpoint.requires_discovery must be false")
    if manual.get("reaches_peer_when_discovery_unavailable") is not True:
        errors.append("EEBUS-G08: manual endpoint must reach peer when discovery is unavailable")
    if manual.get("source") != "operator_config":
        errors.append("EEBUS-G08: manual endpoint source must be operator_config")
    return errors


def _validate_g09(case: dict[str, Any], store: dict[str, Any]) -> list[str]:
    persistence = _dict(case.get("credential_persistence"))
    errors: list[str] = []
    if persistence.get("store_path") != store.get("path"):
        errors.append("EEBUS-G09: credential_persistence.store_path must match credential_store.path")
    if persistence.get("disposable_only") is not True:
        errors.append("EEBUS-G09: disposable_only must be true")
    if persistence.get("survives_restart") is not True:
        errors.append("EEBUS-G09: survives_restart must be true")
    if persistence.get("production_trust_written") is not False:
        errors.append("EEBUS-G09: production_trust_written must be false")
    return errors


def _validate_redaction(payload: Any) -> list[str]:
    errors: list[str] = []
    for path, value in _walk_strings(payload):
        if SECRET_PATH_RE.search(path):
            errors.append(f"{path}: secret-bearing key is forbidden")
        if PEM_RE.search(value):
            errors.append(f"{path}: PEM/private key material is forbidden")
        if SECRET_VALUE_RE.search(value):
            errors.append(f"{path}: secret-bearing value is forbidden")
        if MAC_RE.search(value):
            errors.append(f"{path}: MAC address is forbidden")
        if SERIAL_RE.search(value):
            errors.append(f"{path}: device serial-like value is forbidden")
        for token in _find_ip_tokens(value):
            if _is_forbidden_ip(token):
                errors.append(f"{path}: raw IP address is forbidden")
    return errors


def _validate_unknown_fields(payload: dict[str, Any]) -> list[str]:
    allowed = {
        "$": {
            "contract",
            "issue",
            "repo",
            "generated_at",
            "mode",
            "result",
            "required_cases",
            "topology",
            "security",
            "credential_store",
            "cases",
            "lab",
        },
        "$.topology": {"ha_addon", "lan_peer"},
        "$.topology.ha_addon": {
            "host_network",
            "host_dbus",
            "same_container_or_bridge_only",
            "network_namespace_ref",
        },
        "$.topology.lan_peer": {"scope", "same_host", "address_ref"},
        "$.security": {
            "wildcard_bind_allowed",
            "unexpected_bridge_exposure",
            "ingress_reachable",
            "web_ui_reachable",
            "vendor_restricted",
            "admin_surface",
        },
        "$.credential_store": {
            "path",
            "class",
            "production_trust_written",
            "persistent_across_restart",
            "symlink_checked",
            "path_traversal_checked",
            "permissions",
            "pre_restart_identity_ref",
            "post_restart_identity_ref",
        },
        "$.credential_store.permissions": {"directory", "files"},
        "$.cases[]": {"id", "status", "evidence", "listener", "mdns", "negative", "manual_endpoint", "credential_persistence"},
        "$.cases[].listener": {"bind_policy", "wildcard_bind", "unexpected_bridge_exposure", "lan_tcp_reachable"},
        "$.cases[].mdns": {"lan_peer_resolved", "peer_scope", "service_type"},
        "$.cases[].negative": {
            "mdns_disabled_absent",
            "avahi_dbus_state",
            "pairing_closed_absent_or_ttl_expired",
        },
        "$.cases[].manual_endpoint": {
            "configured",
            "requires_discovery",
            "reaches_peer_when_discovery_unavailable",
            "source",
        },
        "$.cases[].credential_persistence": {
            "store_path",
            "disposable_only",
            "survives_restart",
            "production_trust_written",
        },
        "$.lab": {
            "repo_branch",
            "repo_commit",
            "addon_build_id",
            "collector_command_log_ref",
            "external_lan_peer_namespace_ref",
            "listener_socket_ref",
            "mdns_browse_ref",
            "mdns_resolve_ref",
            "restart_ref",
            "collected_at",
            "configured_interface_ref",
            "configured_subnet_ref",
            "case_evidence_ids",
        },
        "$.lab.case_evidence_ids": set(REQUIRED_CASES),
    }

    errors: list[str] = []
    for path, obj in _walk_dicts(payload):
        normalized = _normalize_schema_path(path)
        allowed_keys = allowed.get(normalized)
        if allowed_keys is None:
            continue
        for key in obj:
            if key in allowed_keys:
                continue
            if CONTRADICTION_KEY_RE.search(key):
                errors.append(f"{path}.{key}: contradiction-prone extra field is forbidden")
            else:
                errors.append(f"{path}.{key}: unexpected field")
    return errors


def _walk_dicts(value: Any, path: str = "$"):
    if isinstance(value, dict):
        yield path, value
        for key, child in value.items():
            yield from _walk_dicts(child, f"{path}.{key}")
    elif isinstance(value, list):
        for idx, child in enumerate(value):
            yield from _walk_dicts(child, f"{path}[{idx}]")


def _normalize_schema_path(path: str) -> str:
    return re.sub(r"\[\d+\]", "[]", path)


def _walk_strings(value: Any, path: str = "$"):
    if isinstance(value, dict):
        for key, child in value.items():
            yield from _walk_strings(child, f"{path}.{key}")
    elif isinstance(value, list):
        for idx, child in enumerate(value):
            yield from _walk_strings(child, f"{path}[{idx}]")
    elif isinstance(value, str):
        yield path, value


def _is_private_or_link_local_ip(value: str) -> bool:
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        return False
    return address.is_private or address.is_link_local or address.is_loopback


def _find_ip_tokens(value: str) -> set[str]:
    tokens: set[str] = set()
    for match in re.findall(r"\b(?:(?:\d{1,3})\.){3}(?:\d{1,3})\b", value):
        tokens.add(match)
    for raw in re.findall(r"(?<![A-Za-z0-9])\[?[0-9A-Fa-f:.%]+\]?(?![A-Za-z0-9])", value):
        candidate = raw.strip("[]().,;")
        if ":" not in candidate:
            continue
        if "%" in candidate:
            candidate = candidate.split("%", 1)[0]
        try:
            ipaddress.ip_address(candidate)
        except ValueError:
            continue
        tokens.add(candidate)
    return tokens


def _is_forbidden_ip(value: str) -> bool:
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        return False
    return True


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _non_empty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _is_redacted_digest(value: Any) -> bool:
    return isinstance(value, str) and bool(REDACTED_DIGEST_RE.fullmatch(value))


def run_self_tests() -> int:
    fixture_path = Path("scripts/fixtures/eebus_ha_network_proof_contract_pass.json")
    payload = load_artifact(str(fixture_path))
    baseline_errors = validate_artifact(payload, mode="contract")
    if baseline_errors:
        print(f"self-test baseline failed: {'; '.join(baseline_errors)}")
        return 1

    mutations = {
        "wildcard bind rejected": lambda p: p["cases"][0]["listener"].__setitem__("wildcard_bind", True),
        "same bridge rejected": lambda p: p["topology"]["ha_addon"].__setitem__(
            "same_container_or_bridge_only",
            True,
        ),
        "raw private IP rejected": lambda p: p["topology"]["lan_peer"].__setitem__(
            "address_ref",
            "192.168.1.44",
        ),
        "production trust rejected": lambda p: p["credential_store"].__setitem__(
            "production_trust_written",
            True,
        ),
        "manual endpoint discovery dependency rejected": lambda p: p["cases"][3][
            "manual_endpoint"
        ].__setitem__("requires_discovery", True),
        "wrong mDNS service type rejected": lambda p: p["cases"][1]["mdns"].__setitem__(
            "service_type",
            "_eebus._tcp",
        ),
        "secret-bearing key rejected": lambda p: p.__setitem__("password", "hunter2"),
        "bearer token rejected": lambda p: p["topology"]["lan_peer"].__setitem__(
            "address_ref",
            "Bearer abc.def.ghi",
        ),
        "IPv6 link-local rejected": lambda p: p["topology"]["lan_peer"].__setitem__(
            "address_ref",
            "fe80::1%eth0",
        ),
        "IPv6 ULA rejected": lambda p: p["topology"]["lan_peer"].__setitem__(
            "address_ref",
            "fd00::1",
        ),
        "IPv6 loopback rejected": lambda p: p["topology"]["lan_peer"].__setitem__(
            "address_ref",
            "::1",
        ),
        "IPv6 documentation address rejected": lambda p: p["topology"]["lan_peer"].__setitem__(
            "address_ref",
            "2001:db8::1",
        ),
        "wildcard contradiction field rejected": lambda p: p["cases"][0]["listener"].__setitem__(
            "actual_bind",
            "*:4712",
        ),
    }

    for name, mutate in mutations.items():
        mutated = copy.deepcopy(payload)
        mutate(mutated)
        errors = validate_artifact(mutated, mode="contract")
        if not errors:
            print(f"self-test mutation did not fail: {name}")
            return 1

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp, "lab-required.json")
        lab_required = copy.deepcopy(payload)
        lab_required["mode"] = "contract_fixture"
        tmp_path.write_text(json.dumps(lab_required), encoding="utf-8")
        errors = validate_artifact(load_artifact(str(tmp_path)), mode="lab")
        if not any("mode=lab_run" in error for error in errors):
            print("self-test lab mode did not require mode=lab_run")
            return 1

        relabeled_fixture = copy.deepcopy(payload)
        relabeled_fixture["mode"] = "lab_run"
        tmp_path.write_text(json.dumps(relabeled_fixture), encoding="utf-8")
        errors = validate_artifact(load_artifact(str(tmp_path)), mode="lab")
        if not any("lab object" in error for error in errors):
            print("self-test lab mode accepted relabeled contract fixture")
            return 1

        valid_lab = copy.deepcopy(payload)
        valid_lab["mode"] = "lab_run"
        valid_lab["lab"] = {
            "repo_branch": "issue/166-msp-03c-ha-eebus-network-proof",
            "repo_commit": "0123456789abcdef0123456789abcdef01234567",
            "addon_build_id": "msp03c-addon-build",
            "collector_command_log_ref": "msp03c-command-log-redacted",
            "external_lan_peer_namespace_ref": "msp03c-peer-namespace-redacted",
            "listener_socket_ref": "msp03c-listener-socket-redacted",
            "mdns_browse_ref": "msp03c-mdns-browse-redacted",
            "mdns_resolve_ref": "msp03c-mdns-resolve-redacted",
            "restart_ref": "msp03c-restart-redacted",
            "collected_at": "2026-07-08T00:00:00Z",
            "configured_interface_ref": "msp03c-interface-redacted",
            "case_evidence_ids": {
                case_id: [f"msp03c-{case_id.lower()}-redacted"] for case_id in REQUIRED_CASES
            },
        }
        tmp_path.write_text(json.dumps(valid_lab), encoding="utf-8")
        errors = validate_artifact(load_artifact(str(tmp_path)), mode="lab")
        if errors:
            print(f"self-test valid lab fixture failed: {'; '.join(errors)}")
            return 1

    print("eeBUS HA network proof self-test: PASS")
    return 0


def main() -> int:
    args = parse_args()
    if args.self_test:
        return run_self_tests()

    try:
        payload = load_artifact(args.artifact)
    except (FileNotFoundError, json.JSONDecodeError, ValueError) as exc:
        print(f"eeBUS HA network proof: FAIL ({exc})")
        return 1

    errors = validate_artifact(payload, mode=args.mode)
    if errors:
        print(f"eeBUS HA network proof: FAIL ({'; '.join(errors)})")
        return 1

    print(f"eeBUS HA network proof: PASS ({args.mode})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
