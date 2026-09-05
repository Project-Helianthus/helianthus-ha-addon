from __future__ import annotations

from copy import deepcopy
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import urllib.request

import pytest


ROOT = Path(__file__).resolve().parents[1]
VERSION = "0.6.56"
GATEWAY = "a759efd7f72a099288f1fc2b7cf20236d37cfa0b"
HA_INTEGRATION = "e614e63898d4ddc317c66f1a673fefe0e2786245"
FIXTURE = ROOT / "scripts/fixtures/fronius_ha_rollout_contract_pass.json"
VERIFIER = ROOT / "scripts/check_fronius_ha_rollout.py"
MANIFEST_DIGEST = "sha256:" + "a" * 64
PLATFORM_DIGEST = "sha256:" + "b" * 64
PUBLICATION = {
    "image_repository": "ghcr.io/project-helianthus/helianthus-ha-addon",
    "image_tag": VERSION,
    "target_platform": "linux/arm64",
    "manifest_digest": MANIFEST_DIGEST,
    "platform_digest": PLATFORM_DIGEST,
}
PUBLIC_GHCR_PROBE_ENV = "HELIANTHUS_RUN_PUBLIC_GHCR_PROBE"
_ORIGINAL_URLOPEN = urllib.request.urlopen


@pytest.fixture(autouse=True)
def _deny_unmocked_registry_access(monkeypatch: pytest.MonkeyPatch) -> None:
    def denied_urlopen(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("unit tests must not access the public registry")

    monkeypatch.setattr(urllib.request, "urlopen", denied_urlopen)


@pytest.fixture
def _public_ghcr_probe(monkeypatch: pytest.MonkeyPatch) -> None:
    if os.environ.get(PUBLIC_GHCR_PROBE_ENV) != "1":
        pytest.skip(f"set {PUBLIC_GHCR_PROBE_ENV}=1 to run the public GHCR probe")
    monkeypatch.setattr(urllib.request, "urlopen", _ORIGINAL_URLOPEN)


class _Response:
    def __init__(self, raw: bytes, headers: dict[str, str] | None = None) -> None:
        self._raw = raw
        self.headers = headers or {}

    def __enter__(self):  # noqa: ANN204
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self, _limit: int) -> bytes:
        return self._raw


def _mock_registry(
    monkeypatch: pytest.MonkeyPatch,
    verifier,
    *,
    token_payload: object = None,
    manifest_payload: object = None,
    manifest_raw: bytes | None = None,
    manifest_digest: str = MANIFEST_DIGEST,
) -> list:
    if token_payload is None:
        token_payload = {"token": "fixture-token"}
    if manifest_payload is None:
        manifest_payload = {
            "manifests": [
                {
                    "digest": "sha256:" + "c" * 64,
                    "platform": {"os": "linux", "architecture": "amd64"},
                },
                {
                    "digest": PLATFORM_DIGEST,
                    "platform": {"os": "linux", "architecture": "arm64"},
                },
            ]
        }
    requests = []

    def fake_urlopen(request, *, timeout: int):  # noqa: ANN001, ANN202
        requests.append((request, timeout))
        if len(requests) == 1:
            return _Response(json.dumps(token_payload).encode())
        raw = manifest_raw
        if raw is None:
            raw = json.dumps(manifest_payload).encode()
        return _Response(raw, {"Docker-Content-Digest": manifest_digest})

    monkeypatch.setattr(verifier, "urlopen", fake_urlopen)
    return requests


def _verifier_module():  # noqa: ANN202
    spec = importlib.util.spec_from_file_location("check_fronius_ha_rollout", VERIFIER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _live_payload() -> dict:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    payload["mode"] = "lab"
    payload["evidence_kind"] = "live_smoke_v1"
    payload["required_assertions"] = {
        name: "pass" for name in payload["required_assertions"]
    }
    payload["live"] = {
        "image_repository": PUBLICATION["image_repository"],
        "image_tag": VERSION,
        "target_platform": PUBLICATION["target_platform"],
        "manifest_digest": MANIFEST_DIGEST,
        "platform_digest": PLATFORM_DIGEST,
        "installed_image_digest": MANIFEST_DIGEST,
        "installed_at": "2026-08-20T15:00:00+03:00",
        "backup_ref": "b930e982",
        "evidence_ref": "sha256:" + "c" * 64,
        "runtime_version": VERSION,
        "gateway_build_id": GATEWAY,
        "ha_integration_ref": HA_INTEGRATION,
    }
    return payload


def test_release_pins_exact_m5_06_gateway_and_m5_07_consumer() -> None:
    config = json.loads((ROOT / "helianthus/config.json").read_text(encoding="utf-8"))
    dockerfile = (ROOT / "helianthus/Dockerfile").read_text(encoding="utf-8")
    workflow = (ROOT / ".github/workflows/build.yml").read_text(encoding="utf-8")
    changelog = (ROOT / "helianthus/CHANGELOG.md").read_text(encoding="utf-8")

    assert config["version"] == VERSION
    assert f"ARG EBUSGATEWAY_VERSION={GATEWAY}" in dockerfile
    assert f"EBUSGATEWAY_VERSION={GATEWAY}" in workflow
    assert f"## {VERSION} " in changelog
    assert GATEWAY in changelog
    assert HA_INTEGRATION in changelog


def test_rollout_contract_fixture_covers_every_m5_08_gate() -> None:
    assert VERIFIER.is_file()
    assert FIXTURE.is_file()
    completed = subprocess.run(
        [sys.executable, str(VERIFIER), "--artifact", str(FIXTURE), "--mode", "contract"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr

    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert payload["release"] == {
        "addon_version": VERSION,
        "gateway_ref": GATEWAY,
        "ha_integration_ref": HA_INTEGRATION,
    }
    assert set(payload["required_assertions"]) == {
        "raw_mcp",
        "semantic_mcp",
        "graphql_m2m",
        "portal_semantic",
        "portal_raw",
        "home_assistant",
        "external_mtls",
        "credential_recovery",
        "channel_recovery",
        "restart",
        "modbus_independent_disable",
        "ha_independent_disable",
        "compatible_rollback",
    }
    assert payload["rollback"] == {
        "prior_version": "0.6.55",
        "schema_compatible": True,
        "backup_required": True,
    }


def test_rollout_verifier_is_wired_into_ci_and_smoke_runbook() -> None:
    ci = (ROOT / "scripts/ci_local.sh").read_text(encoding="utf-8")
    pr_ci = (ROOT / ".github/workflows/pr-ci.yml").read_text(encoding="utf-8")
    runbook = (ROOT / "SMOKE_RUNBOOK.md").read_text(encoding="utf-8")

    assert "tests/test_fronius_ha_rollout.py" in ci
    assert "check_fronius_ha_rollout.py" in ci
    assert "tests/test_fronius_ha_rollout.py" in pr_ci
    assert "check_fronius_ha_rollout.py" in pr_ci
    for marker in (
        "M5_08_RAW_MCP",
        "M5_08_SEMANTIC_MCP",
        "M5_08_GRAPHQL_M2M",
        "M5_08_PORTAL_SEMANTIC",
        "M5_08_PORTAL_RAW",
        "M5_08_HOME_ASSISTANT",
        "M5_08_EXTERNAL_MTLS",
        "M5_08_RECOVERY",
        "M5_08_INDEPENDENT_DISABLE",
        "M5_08_ROLLBACK",
    ):
        assert marker in runbook


def test_rollout_verifier_rejects_numeric_boolean_claims() -> None:
    verifier = _verifier_module()
    for path in (
        ("safety", "no_modbus_writes"),
        ("safety", "no_inverter_mutation"),
        ("safety", "endpoint_values_redacted"),
        ("rollback", "schema_compatible"),
        ("rollback", "backup_required"),
    ):
        payload = deepcopy(_live_payload())
        payload[path[0]][path[1]] = 1
        assert verifier.validate(payload, "lab", publication=PUBLICATION)


def test_rollout_verifier_rejects_whitespace_backup_reference() -> None:
    verifier = _verifier_module()
    payload = _live_payload()
    payload["live"]["backup_ref"] = " "
    assert verifier.validate(payload, "lab", publication=PUBLICATION)


def test_rollout_verifier_binds_live_image_to_public_manifest_and_platform() -> None:
    verifier = _verifier_module()
    payload = _live_payload()
    assert verifier.validate(payload, "lab", publication=PUBLICATION) == []

    payload["live"]["installed_image_digest"] = "sha256:" + "d" * 64
    assert verifier.validate(payload, "lab", publication=PUBLICATION)

    payload = _live_payload()
    wrong_platform = dict(PUBLICATION, target_platform="linux/amd64")
    assert verifier.validate(payload, "lab", publication=wrong_platform)


def test_rollout_verifier_rejects_non_rfc3339_timestamp() -> None:
    verifier = _verifier_module()
    for invalid in (
        "20260820T150000+0300",
        "2026-08-20X15:00:00+03:00",
        "2026-08-20T15:00:00,1+03:00",
        "2026-08-20T15:00:00+03",
    ):
        payload = _live_payload()
        payload["live"]["installed_at"] = invalid
        assert verifier.validate(payload, "lab", publication=PUBLICATION)


@pytest.mark.parametrize("token_payload", ({}, {"token": ""}, {"token": 7}))
def test_publication_resolver_rejects_missing_token(
    monkeypatch: pytest.MonkeyPatch, token_payload: object
) -> None:
    verifier = _verifier_module()
    _mock_registry(monkeypatch, verifier, token_payload=token_payload)

    with pytest.raises(ValueError, match="pull token missing"):
        verifier.resolve_publication(
            PUBLICATION["image_repository"], VERSION, PUBLICATION["target_platform"]
        )


@pytest.mark.parametrize(
    ("manifest_raw", "manifest_payload", "expected_error"),
    (
        (b"x" * 1_048_577, None, (ValueError,)),
        (b"not-json", None, (json.JSONDecodeError,)),
        (None, {"manifests": {}}, (ValueError,)),
    ),
)
def test_publication_resolver_rejects_invalid_or_oversized_index(
    monkeypatch: pytest.MonkeyPatch,
    manifest_raw: bytes | None,
    manifest_payload: object,
    expected_error: tuple[type[Exception], ...],
) -> None:
    verifier = _verifier_module()
    _mock_registry(
        monkeypatch,
        verifier,
        manifest_raw=manifest_raw,
        manifest_payload=manifest_payload,
    )

    with pytest.raises(expected_error):
        verifier.resolve_publication(
            PUBLICATION["image_repository"], VERSION, PUBLICATION["target_platform"]
        )


def test_publication_resolver_rejects_invalid_index_digest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    verifier = _verifier_module()
    _mock_registry(monkeypatch, verifier, manifest_digest="sha256:not-a-digest")

    with pytest.raises(ValueError, match="manifest response is invalid"):
        verifier.resolve_publication(
            PUBLICATION["image_repository"], VERSION, PUBLICATION["target_platform"]
        )


@pytest.mark.parametrize(
    "matching_descriptors",
    (
        [],
        [
            {
                "digest": PLATFORM_DIGEST,
                "platform": {"os": "linux", "architecture": "arm64"},
            },
            {
                "digest": "sha256:" + "d" * 64,
                "platform": {"os": "linux", "architecture": "arm64"},
            },
        ],
    ),
)
def test_publication_resolver_rejects_absent_or_ambiguous_platform(
    monkeypatch: pytest.MonkeyPatch, matching_descriptors: list[dict]
) -> None:
    verifier = _verifier_module()
    manifest = {
        "manifests": [
            {
                "digest": "sha256:" + "c" * 64,
                "platform": {"os": "linux", "architecture": "amd64"},
            },
            *matching_descriptors,
        ]
    }
    _mock_registry(monkeypatch, verifier, manifest_payload=manifest)

    with pytest.raises(ValueError, match="platform is missing or ambiguous"):
        verifier.resolve_publication(
            PUBLICATION["image_repository"], VERSION, PUBLICATION["target_platform"]
        )


def test_publication_resolver_rejects_malformed_platform_digest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    verifier = _verifier_module()
    manifest = {
        "manifests": [
            {
                "digest": "sha256:invalid",
                "platform": {"os": "linux", "architecture": "arm64"},
            }
        ]
    }
    _mock_registry(monkeypatch, verifier, manifest_payload=manifest)

    with pytest.raises(ValueError, match="platform digest is invalid"):
        verifier.resolve_publication(
            PUBLICATION["image_repository"], VERSION, PUBLICATION["target_platform"]
        )


def test_publication_resolver_binds_exact_index_and_platform_digests(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    verifier = _verifier_module()
    requests = _mock_registry(monkeypatch, verifier)

    publication = verifier.resolve_publication(
        PUBLICATION["image_repository"], VERSION, PUBLICATION["target_platform"]
    )

    assert publication == PUBLICATION
    assert len(requests) == 2
    token_request, token_timeout = requests[0]
    manifest_request, manifest_timeout = requests[1]
    assert token_timeout == manifest_timeout == 30
    assert token_request.full_url.startswith("https://ghcr.io/token?")
    assert "repository%3Aproject-helianthus%2Fhelianthus-ha-addon%3Apull" in (
        token_request.full_url
    )
    assert manifest_request.full_url.endswith(
        "/project-helianthus/helianthus-ha-addon/manifests/0.6.56"
    )
    assert manifest_request.get_header("Authorization") == "Bearer fixture-token"
    assert "application/vnd.oci.image.index.v1+json" in manifest_request.get_header(
        "Accept"
    )


def test_default_resolver_suite_denies_unmocked_registry_access() -> None:
    verifier = _verifier_module()

    with pytest.raises(AssertionError, match="must not access the public registry"):
        verifier.resolve_publication(
            PUBLICATION["image_repository"], VERSION, PUBLICATION["target_platform"]
        )


def test_public_release_manifest_probe_resolves_existing_tag(
    _public_ghcr_probe: None,
) -> None:
    verifier = _verifier_module()

    publication = verifier.resolve_publication(
        PUBLICATION["image_repository"], VERSION, PUBLICATION["target_platform"]
    )

    assert publication["image_repository"] == PUBLICATION["image_repository"]
    assert publication["image_tag"] == VERSION
    assert publication["target_platform"] == PUBLICATION["target_platform"]
    assert verifier.DIGEST_RE.fullmatch(publication["manifest_digest"])
    assert verifier.DIGEST_RE.fullmatch(publication["platform_digest"])
