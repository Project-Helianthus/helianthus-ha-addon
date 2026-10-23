#!/usr/bin/env python3
"""Validate offline candidate metadata (helianthus-candidate-metadata/1).

Implements docs/candidate-metadata-contract.md against a standalone add-on
checkout. Packaging cohort consistency is delegated to the K25 guard in
scripts/check_release_cohort.py. Every input is an explicit local path: nothing
is fetched, resolved, built, written, published or tagged, and diagnostics never
echo input paths, receipt contents or exact coordinates.
"""

from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
import json
from pathlib import Path
import re
import shlex
from typing import Any, Callable

import yaml

import check_release_cohort as k25


METADATA_FORMAT = "helianthus-candidate-metadata/1"
RECEIPT_FORMAT = "helianthus-candidate-verification/1"
COHORT = "0.7"
COHORT_RELEASE = (0, 7)
KINDS = ("preparatory", "candidate")
DISPOSITIONS = ("not-ready", "ready-for-review", "accepted-candidate")
RANK = {name: rank for rank, name in enumerate(DISPOSITIONS)}
ARCHITECTURES = ("aarch64", "amd64", "armv7", "armhf", "i386")
COMPONENT_KEYS = ("addon", "gateway", "explorer", "ha_integration")
COMPONENTS_FIELDS = COMPONENT_KEYS + ("native_dependencies",)
COMPONENT_FIELDS = ("name", "release_label", "artifact_id", "public_ref")
ACCEPTANCE_KEYS = ("INT-12", "INT-13", "INT-14", "Portal", "naming", "identity")
METADATA_FIELDS = (
    "format", "bundle_id", "association_id", "kind", "cohort", "components",
    "architectures", "output_binding", "exact_bom", "acceptance", "disposition",
)
RECEIPT_FIELDS = (
    "format", "bundle_id", "association_id", "attestation_id", "components",
    "expected_architectures", "bound_architectures", "expected_output_ids",
    "bound_output_ids", "checks",
)
READINESS_CHECKS = ("package_mapping", "public_references", "inventory", "output_binding", "exact_bom")
PROMOTION_CHECKS = ("independent_review", "required_gates")
RECEIPT_CHECKS = READINESS_CHECKS + ("acceptance",) + PROMOTION_CHECKS
CHECK_VALUES = ("satisfied", "missing", "mismatch")
ADDON_REPOSITORY = "https://github.com/project-helianthus/helianthus-ha-addon"
PACKAGE_INPUTS = (
    ("config", "helianthus/config.json", "json"),
    ("dockerfile", "helianthus/Dockerfile", "text"),
    ("bom", "helianthus/bom.json", "json"),
    ("build", ".github/workflows/build.yml", "yaml"),
    ("test_image", ".github/workflows/test-image.yml", "yaml"),
)
NOTE = (
    "Structural verification only: nothing was fetched, built, written, published or tagged; "
    "a valid result is neither a release, a tag nor hardware qualification."
)

OPAQUE_ID = re.compile(r"[a-z][a-z0-9]*(?:-[a-z0-9]+)+")
NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/+-]{0,199}")
REPOSITORY = re.compile(
    r"https://github\.com/([A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?)/([A-Za-z0-9._-]{1,100})"
)
PATH_SEGMENT = re.compile(r"[A-Za-z0-9._+-]+")
# Restricted publication data: commit/tree/digest fragments, capture dates, IPv4.
HEX_RUN = re.compile(r"[0-9A-Fa-f]{7,}")
DATE = re.compile(r"(?:19|20)\d\d[-_./]?(?:0[1-9]|1[0-2])[-_./]?(?:0[1-9]|[12]\d|3[01])")
IPV4 = re.compile(r"(?<!\d)(?<!\d\.)\d{1,3}(?:\.\d{1,3}){3}(?!\.?\d)")
DERIVED_VERSION = re.compile(r"\$\{\{\s*steps\.addon\.outputs\.version\s*\}\}")
CONFIG_VERSION_STEP = re.compile(
    r"""echo "version=\$\(jq -r '\.version' helianthus/config\.json\)" >> "\$GITHUB_OUTPUT\"""")
MANIFEST_MEMBER = re.compile(r".+:\$\{\{\s*steps\.addon\.outputs\.version\s*\}\}-([a-z0-9]+)")
VERSION_TAG = re.compile(r".+:\$\{\{\s*steps\.addon\.outputs\.version\s*\}\}")
CONFIG_VERSION = object()  # BUILD_VERSION provably read from helianthus/config.json
DOCKERFILE_DEFAULT = object()  # A build step without this override uses the Dockerfile default


class _Invalid(Exception):
    """A syntax, schema or publication violation in a supplied document."""


@dataclass
class Outcome:
    exit_code: int
    disposition: str | None
    lines: list[str]


class _Report:
    def __init__(self) -> None:
        self.invalid: list[str] = []
        self.conflict: list[str] = []
        self.mismatch: list[str] = []
        self.unavailable: list[str] = []
        self.public: list[str] = []
        self.private: list[str] = []
        self.pending: list[str] = []
        self.k25: list[str] = []


def _hex_like(run: str) -> bool:
    return True


def _restricted(text: str, dates: bool = True) -> bool:
    return (any(_hex_like(run) for run in HEX_RUN.findall(text))
            or (dates and bool(DATE.search(text))) or bool(IPV4.search(text)))


def _redact(line: str) -> str:
    line = HEX_RUN.sub(lambda match: "<redacted>" if _hex_like(match[0]) else match[0], line)
    return IPV4.sub("<redacted>", line)


def _unique_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _Invalid("duplicate key")
        result[key] = value
    return result


def _no_constant(name: str) -> Any:
    raise _Invalid(f"non-finite number {name}")


def _strict_json(raw: bytes) -> Any:
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise _Invalid("not UTF-8") from None
    try:
        return json.loads(text, object_pairs_hook=_unique_keys, parse_constant=_no_constant)
    except json.JSONDecodeError as exc:
        raise _Invalid(f"not JSON ({exc.msg} at line {exc.lineno} column {exc.colno})") from None
    except RecursionError:
        raise _Invalid("nested too deeply") from None
    except ValueError:  # For example an integer literal beyond the interpreter's digit limit.
        raise _Invalid("not JSON (unsupported literal)") from None


def _object(value: Any, fields: tuple[str, ...], where: str) -> dict[str, Any]:
    if type(value) is not dict:
        raise _Invalid(f"{where} must be an object")
    unknown = [key for key in value if key not in fields]
    if unknown:
        raise _Invalid(f"{where} has {len(unknown)} unknown field(s)")
    missing = [key for key in fields if key not in value]
    if missing:
        raise _Invalid(f"{where} is missing {', '.join(missing)}")
    return value


def _literal(value: Any, expected: str, where: str) -> None:
    if type(value) is not str or value != expected:
        raise _Invalid(f"{where} must be the literal {expected}")


def _enum(value: Any, allowed: tuple[str, ...], where: str) -> str:
    if type(value) is not str or value not in allowed:
        raise _Invalid(f"{where} must be one of {', '.join(allowed)}")
    return value


def _opaque(value: Any, where: str, nullable: bool = False) -> str | None:
    if value is None and nullable:
        return None
    if type(value) is not str or len(value) > 80 or not OPAQUE_ID.fullmatch(value):
        raise _Invalid(f"{where} must be an opaque ID")
    if _restricted(value):
        raise _Invalid(f"{where} embeds restricted publication data")
    return value


def _current(value: Any, association: str, where: str) -> None:
    if _opaque(value, where) != association:
        raise _Invalid(f"{where} must equal the current association_id")


def _array(value: Any, where: str, item: Callable[[Any, str], Any], allow_empty: bool) -> list[str]:
    if type(value) is not list:
        raise _Invalid(f"{where} must be an array")
    if not value and not allow_empty:
        raise _Invalid(f"{where} must not be empty")
    for index, entry in enumerate(value):
        item(entry, f"{where}[{index}]")
    if len(set(value)) != len(value):
        raise _Invalid(f"{where} must not repeat values")
    return value


def _architecture(value: Any, where: str) -> None:
    _enum(value, ARCHITECTURES, where)


def _public_ref(value: Any, where: str) -> None:
    if value is None:
        return
    _object(value, ("repository", "path"), where)
    repository, path = value["repository"], value["path"]
    match = REPOSITORY.fullmatch(repository) if type(repository) is str else None
    if (not match or match[2] in {".", ".."} or match[2].lower().endswith(".git")
            or _restricted(repository)):
        raise _Invalid(f"{where}.repository must be a canonical public GitHub repository URL")
    if (type(path) is not str or len(path) > 512
            or any(segment in {".", ".."} or segment.lower() == ".git" or not PATH_SEGMENT.fullmatch(segment)
                   for segment in path.split("/"))
            or _restricted(path)):
        raise _Invalid(f"{where}.path must be a clean repository-relative file path")


def _component(value: Any, where: str) -> None:
    _object(value, COMPONENT_FIELDS, where)
    name = value["name"]
    if (type(name) is not str or not NAME.fullmatch(name) or "//" in name or ".." in name
            or _restricted(name)):
        raise _Invalid(f"{where}.name must be a public package or dependency name")
    label = value["release_label"]
    if label is not None:
        try:
            if type(label) is not str:
                raise ValueError
            k25.cohort(label)
        except ValueError:
            raise _Invalid(f"{where}.release_label must be null or a K25 release label") from None
        if _restricted(label, dates=False):  # Calendar releases are labels; pseudoversions still fail.
            raise _Invalid(f"{where}.release_label embeds restricted publication data")
    _opaque(value["artifact_id"], f"{where}.artifact_id")
    _public_ref(value["public_ref"], f"{where}.public_ref")


def _components(value: Any, where: str) -> None:
    _object(value, COMPONENTS_FIELDS, where)
    for key in COMPONENT_KEYS:
        _component(value[key], f"{where}.{key}")
    natives = value["native_dependencies"]
    if type(natives) is not list or not natives:
        raise _Invalid(f"{where}.native_dependencies must be a nonempty array")
    for index, native in enumerate(natives):
        _component(native, f"{where}.native_dependencies[{index}]")
    names = [native["name"] for native in natives]
    if len(set(names)) != len(names):
        raise _Invalid(f"{where}.native_dependencies names must be unique")
    ids = [value[key]["artifact_id"] for key in COMPONENT_KEYS] + [native["artifact_id"] for native in natives]
    if len(set(ids)) != len(ids):
        raise _Invalid(f"{where} artifact IDs must be unique")


def _component_ids(components: dict[str, Any]) -> set[str]:
    return ({components[key]["artifact_id"] for key in COMPONENT_KEYS}
            | {native["artifact_id"] for native in components["native_dependencies"]})


def _validate_metadata(doc: Any) -> None:
    _object(doc, METADATA_FIELDS, "document")
    _literal(doc["format"], METADATA_FORMAT, "format")
    _opaque(doc["bundle_id"], "bundle_id")
    association = _opaque(doc["association_id"], "association_id")
    _enum(doc["kind"], KINDS, "kind")
    if type(doc["cohort"]) is not str or doc["cohort"] != COHORT:
        raise _Invalid("cohort must be the literal 0.7; other cohorts are unsupported")
    _components(doc["components"], "components")
    _array(doc["architectures"], "architectures", _architecture, allow_empty=False)

    binding = _object(doc["output_binding"], ("status", "association_id", "artifact_ids", "evidence_ref"),
                      "output_binding")
    status = _enum(binding["status"], ("unbound", "partial", "bound"), "output_binding.status")
    _current(binding["association_id"], association, "output_binding.association_id")
    outputs = _array(binding["artifact_ids"], "output_binding.artifact_ids", _opaque, allow_empty=True)
    if (status == "unbound") != (not outputs):
        raise _Invalid("output_binding.artifact_ids must be empty exactly when the status is unbound")
    if set(outputs) & _component_ids(doc["components"]):
        raise _Invalid("output_binding.artifact_ids must not reuse component artifact IDs")
    _public_ref(binding["evidence_ref"], "output_binding.evidence_ref")
    if status == "bound" and binding["evidence_ref"] is None:
        raise _Invalid("output_binding.evidence_ref is required when the status is bound")

    bom = _object(doc["exact_bom"], ("status", "association_id", "attestation_id"), "exact_bom")
    status = _enum(bom["status"], ("unverified", "verified", "mismatch"), "exact_bom.status")
    _current(bom["association_id"], association, "exact_bom.association_id")
    attestation = _opaque(bom["attestation_id"], "exact_bom.attestation_id", nullable=True)
    if (status == "verified") != (attestation is not None):
        raise _Invalid("exact_bom.attestation_id must be set exactly when the status is verified")

    acceptance = _object(doc["acceptance"], ACCEPTANCE_KEYS, "acceptance")
    for key in ACCEPTANCE_KEYS:
        where = f"acceptance.{key}"
        entry = _object(acceptance[key], ("status", "association_id", "evidence_ref"), where)
        status = _enum(entry["status"], ("pending", "accepted", "rejected"), f"{where}.status")
        _current(entry["association_id"], association, f"{where}.association_id")
        _public_ref(entry["evidence_ref"], f"{where}.evidence_ref")
        if status == "accepted" and entry["evidence_ref"] is None:
            raise _Invalid(f"{where}.evidence_ref is required when the status is accepted")
    _enum(doc["disposition"], DISPOSITIONS, "disposition")


def _validate_receipt(doc: Any) -> None:
    _object(doc, RECEIPT_FIELDS, "document")
    _literal(doc["format"], RECEIPT_FORMAT, "format")
    _opaque(doc["bundle_id"], "bundle_id")
    _opaque(doc["association_id"], "association_id")
    attestation = _opaque(doc["attestation_id"], "attestation_id", nullable=True)
    _components(doc["components"], "components")
    for name in ("expected_architectures", "bound_architectures"):
        _array(doc[name], name, _architecture, allow_empty=True)
    for name in ("expected_output_ids", "bound_output_ids"):
        if set(_array(doc[name], name, _opaque, allow_empty=True)) & _component_ids(doc["components"]):
            raise _Invalid(f"{name} must not reuse component artifact IDs")
    checks = _object(doc["checks"], RECEIPT_CHECKS, "checks")
    for name in READINESS_CHECKS + PROMOTION_CHECKS:
        _enum(checks[name], CHECK_VALUES, f"checks.{name}")
    acceptance = _object(checks["acceptance"], ACCEPTANCE_KEYS, "checks.acceptance")
    for key in ACCEPTANCE_KEYS:
        _enum(acceptance[key], CHECK_VALUES, f"checks.acceptance.{key}")
    if (checks["exact_bom"] == "satisfied") != (attestation is not None):
        raise _Invalid("attestation_id must be set exactly when checks.exact_bom is satisfied")


def _load(path: Path, label: str, validator: Callable[[Any], None], report: _Report) -> Any:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        report.unavailable.append(f"{label} cannot be read ({exc.strerror or type(exc).__name__})")
        return None
    try:
        doc = _strict_json(raw)
        validator(doc)
    except _Invalid as exc:
        report.invalid.append(f"{label}: {exc}")
        return None
    return doc


def _inside(path: Path, root: Path) -> bool:
    try:
        return path.resolve().is_relative_to(root.resolve())
    except (OSError, RuntimeError):
        return True


def _read_package(root: Path, report: _Report) -> dict[str, Any] | None:
    if not root.is_dir():
        report.unavailable.append("package root is not a readable directory")
        return None
    package: dict[str, Any] = {}
    for key, relative, kind in PACKAGE_INPUTS:
        try:
            text = (root / relative).read_bytes().decode("utf-8")
            value = json.loads(text) if kind == "json" else yaml.safe_load(text) if kind == "yaml" else text
        except OSError as exc:
            report.unavailable.append(
                f"package input {relative} cannot be read ({exc.strerror or type(exc).__name__})")
            continue
        except (ValueError, yaml.YAMLError, RecursionError):
            report.unavailable.append(f"package input {relative} cannot be parsed")
            continue
        if kind != "text" and type(value) is not dict:
            report.unavailable.append(f"package input {relative} is not a mapping")
            continue
        package[key] = value
    return package if len(package) == len(PACKAGE_INPUTS) else None


def _component_entries(meta: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    components = meta["components"]
    entries = [(f"components.{key}", components[key]) for key in COMPONENT_KEYS]
    entries += [(f"components.native_dependencies[{index}]", native)
                for index, native in enumerate(components["native_dependencies"])]
    return entries


def _public_refs(meta: dict[str, Any]) -> list[tuple[str, dict[str, Any] | None]]:
    refs = [(f"{where}.public_ref", component["public_ref"]) for where, component in _component_entries(meta)]
    refs.append(("output_binding.evidence_ref", meta["output_binding"]["evidence_ref"]))
    refs += [(f"acceptance.{key}.evidence_ref", meta["acceptance"][key]["evidence_ref"]) for key in ACCEPTANCE_KEYS]
    return refs


def _absent_locally(ref: dict[str, Any] | None, root: Path) -> bool:
    """Offline existence check for references into this add-on repository only."""
    if ref is None or ref["repository"].lower() != ADDON_REPOSITORY:
        return False
    try:
        base = current = root.resolve(strict=True)
        for segment in ref["path"].split("/"):  # Exact case, as on the published repository.
            if segment not in {entry.name for entry in current.iterdir()}:
                return True
            current = current / segment
        target = current.resolve(strict=True)
        return not (target.is_file() and target.is_relative_to(base)
                    and ".git" not in {part.lower() for part in target.relative_to(base).parts})
    except (OSError, RuntimeError):
        return True


def _version_manifest_members(run: str) -> set[str]:
    """Members of active imagetools commands whose destination is the version tag."""
    text = "\n".join(line for line in run.splitlines() if not line.strip().startswith("#"))
    members: set[str] = set()
    for command in re.sub(r"\\\n", " ", text).splitlines():
        if "imagetools create" not in command:
            continue
        try:
            tokens = shlex.split(command)
        except ValueError:
            continue
        for index, token in enumerate(tokens[:-1]):
            if token != "-t":
                continue
            target = tokens[index + 1]
            if not VERSION_TAG.fullmatch(target):
                continue
            repository = target.rsplit(":", 1)[0]
            for source in tokens:
                found = MANIFEST_MEMBER.fullmatch(source)
                if found and source.startswith(repository + ":"):
                    members.add(found[1])
    return members


def _derives_version(run: str) -> bool:
    """Prove the step's only version output is assigned from the config.json version."""
    lines = [line.strip() for line in run.splitlines() if line.strip() and not line.strip().startswith("#")]
    writers = [line for line in lines if "version=" in line or "GITHUB_OUTPUT" in line]
    return len(writers) == 1 and CONFIG_VERSION_STEP.fullmatch(writers[0]) is not None


def _build_workflow(workflow: dict[str, Any], report: _Report) -> tuple[dict[str, set[Any]], set[str], set[str]]:
    """Return build-argument values, matrix architectures and version-manifest members."""
    values: dict[str, set[Any]] = {}
    step_names: list[set[str]] = []
    matrix: set[str] = set()
    manifest: set[str] = set()
    jobs = workflow.get("jobs")
    if type(jobs) is not dict:
        report.conflict.append("build workflow has no jobs mapping")
        return values, matrix, manifest
    for job in jobs.values():
        steps = job.get("steps", []) if type(job) is dict else []
        steps = [step for step in steps if type(step) is dict] if type(steps) is list else []
        for step in steps:
            run = step.get("run")
            if type(run) is str and "imagetools create" in run:
                manifest.update(_version_manifest_members(run))
        builds = [step for step in steps if str(step.get("uses", "")).startswith("docker/build-push-action@")]
        if not builds:
            continue
        strategy = job.get("strategy") if type(job.get("strategy")) is dict else {}
        include = strategy.get("matrix", {}).get("include", []) if type(strategy.get("matrix")) is dict else []
        for entry in include if type(include) is list else []:
            if type(entry) is dict and type(entry.get("arch")) is str:
                matrix.add(entry["arch"])
        reads_version = any(step.get("id") == "addon" and type(step.get("run")) is str
                            and _derives_version(step["run"]) for step in steps)
        for step in builds:
            settings = step.get("with") if type(step.get("with")) is dict else {}
            build_args = settings.get("build-args", "")
            try:
                records = list(k25.build_arg_records(build_args if type(build_args) is str else ""))
            except csv.Error:
                report.conflict.append("build workflow build-args are malformed CSV")
                continue
            seen: set[str] = set()
            for name, separator, value in records:
                name, value = name.strip(), value.strip()
                if "${{" in name:
                    report.conflict.append("build workflow build-args contain an opaque expression record")
                    continue
                seen.add(name)
                if name == "BUILD_VERSION" and separator and reads_version and DERIVED_VERSION.fullmatch(value):
                    values.setdefault(name, set()).add(CONFIG_VERSION)
                else:
                    values.setdefault(name, set()).add(value if separator else None)
            step_names.append(seen)
    for name, found in values.items():
        if any(name not in seen for seen in step_names):
            found.add(DOCKERFILE_DEFAULT)
    return values, matrix, manifest


def _effective(values: dict[str, set[Any]], name: str, default: str, report: _Report) -> str | None:
    found = {default if value is DOCKERFILE_DEFAULT else value for value in values.get(name, ())}
    if not found:
        return default
    if len(found) > 1:
        report.conflict.append(f"build workflow declares conflicting {name} values")
        return None
    (value,) = found
    if type(value) is not str or "${{" in value:
        report.conflict.append(f"build workflow {name} is not a literal")
        return None
    return value


def _check_package(meta: dict[str, Any], package: dict[str, Any], root: Path,
                   report: _Report) -> tuple[set[str] | None, bool]:
    """Step 2-4 packaging checks. Return the published architecture set and local-reference absence."""
    components = meta["components"]
    labels = {key: components[key]["release_label"] for key in ("addon", "gateway", "explorer")}
    for key, label in labels.items():
        if label is not None and k25.cohort(label) != COHORT_RELEASE:
            report.conflict.append(f"components.{key}.release_label is outside the 0.7 cohort")

    try:
        messages = k25.check(package["config"], package["dockerfile"], labels["gateway"], package["test_image"])
    except (ValueError, csv.Error) as exc:
        report.conflict.append(f"K25 cohort guard failed: {exc}")
        messages = None
    except (KeyError, TypeError, AttributeError):
        report.conflict.append("K25 cohort guard could not read the packaging structure")
        messages = None
    if messages is not None:
        report.k25.extend(messages)
        if any(message.startswith("NOT_APPLICABLE") for message in messages):
            report.conflict.append("provisioned add-on version is outside the 0.7 cohort")
            messages = None

    values, matrix, manifest = _build_workflow(package["build"], report)
    if labels["addon"] is not None:
        if labels["addon"] != package["config"].get("version"):
            report.conflict.append("components.addon.release_label differs from the helianthus/config.json version")
        build_version = values.get("BUILD_VERSION", set())
        literals = {value for value in build_version if type(value) is str and "${{" not in value}
        if len(build_version) > 1:
            report.conflict.append("build workflow declares conflicting BUILD_VERSION values")
        elif literals and literals != {labels["addon"]}:
            report.conflict.append("build workflow BUILD_VERSION differs from components.addon.release_label")
        elif build_version != {CONFIG_VERSION} and not literals:
            report.public.append(
                "build workflow BUILD_VERSION cannot be tied to the helianthus/config.json version offline")

    if messages is not None:  # K25 passed for a 0.7 add-on: compare effective build arguments.
        explorer = _effective(values, "VRCEXPLORER_VERSION",
                              k25.arg_default(package["dockerfile"], "VRCEXPLORER_VERSION"), report)
        if explorer is not None:
            try:
                in_cohort = k25.cohort(explorer) == COHORT_RELEASE
            except ValueError:
                in_cohort = False
            if not in_cohort:
                report.conflict.append("effective Explorer release for published outputs is outside the 0.7 cohort")
            elif labels["explorer"] is not None and labels["explorer"] != explorer:
                report.conflict.append(
                    "components.explorer.release_label differs from the effective VRCEXPLORER_VERSION")
        gateway = _effective(values, "EBUSGATEWAY_VERSION",
                             k25.arg_default(package["dockerfile"], "EBUSGATEWAY_VERSION"), report)
        if gateway is not None:
            try:
                pin_release = k25.cohort(gateway)
            except ValueError:
                pin_release = None  # Opaque pin: only the private package mapping can bind it.
            if pin_release is not None and pin_release != COHORT_RELEASE:
                report.conflict.append("effective gateway release pin is outside the 0.7 cohort")
            elif pin_release is not None and labels["gateway"] not in (None, gateway):
                report.conflict.append(
                    "components.gateway.release_label differs from the effective gateway release pin")

    published: set[str] | None = matrix
    if not matrix:
        report.public.append("build workflow publishes no recognizable architecture matrix")
        published = None
    elif matrix != manifest:
        report.public.append("build workflow matrix and version manifest members differ")
        published = None
    elif not matrix <= set(ARCHITECTURES):
        report.public.append("build workflow publishes an architecture outside the metadata schema")
        published = None
    elif set(meta["architectures"]) != matrix:
        report.public.append("architectures differ from the set the build workflow publishes under the version tag")

    freeze = package["bom"].get("freeze")
    if not (type(freeze) is dict and freeze.get("owner") == "INT-16" and freeze.get("status") == "frozen"):
        report.public.append("helianthus/bom.json is not frozen by INT-16")

    absent = False
    for where, ref in _public_refs(meta):
        if _absent_locally(ref, root):
            report.public.append(f"{where} does not exist in the provisioned package")
            absent = True
    return published, absent


def _public_reasons(meta: dict[str, Any], report: _Report) -> None:
    if meta["kind"] == "preparatory":
        report.public.append("kind is preparatory; preparation alone never means accepted")
    for where, component in _component_entries(meta):
        if component["release_label"] is None:
            report.public.append(f"{where}.release_label is unavailable")
        if component["public_ref"] is None:
            report.public.append(f"{where}.public_ref is unavailable")
    if meta["output_binding"]["status"] != "bound":
        report.public.append(f"output_binding is {meta['output_binding']['status']}")
    if meta["exact_bom"]["status"] != "verified":
        report.public.append(f"exact_bom is {meta['exact_bom']['status']}")
    for key in ACCEPTANCE_KEYS:
        status = meta["acceptance"][key]["status"]
        if status != "accepted":
            report.public.append(f"acceptance.{key} is {status}")


def _canonical(value: Any) -> str:
    if type(value) is list:
        value = sorted(value, key=lambda entry: entry["name"])
    return json.dumps(value, sort_keys=True)


def _check_receipt(meta: dict[str, Any], receipt: dict[str, Any], published: set[str] | None,
                   absent: bool, report: _Report) -> None:
    mismatch = report.mismatch.append
    checks = receipt["checks"]
    for name in ("bundle_id", "association_id"):
        if receipt[name] != meta[name]:
            mismatch(f"verification context {name} differs from the metadata")
    for key in COMPONENTS_FIELDS:
        if _canonical(receipt["components"][key]) != _canonical(meta["components"][key]):
            mismatch(f"verification context components.{key} differs from the metadata")

    expected_arch, bound_arch = set(receipt["expected_architectures"]), set(receipt["bound_architectures"])
    expected_out, bound_out = set(receipt["expected_output_ids"]), set(receipt["bound_output_ids"])
    public_arch, public_out = set(meta["architectures"]), set(meta["output_binding"]["artifact_ids"])
    if not bound_arch <= expected_arch:
        mismatch("bound_architectures is not a subset of expected_architectures")
    if not bound_out <= expected_out:
        mismatch("bound_output_ids is not a subset of expected_output_ids")
    if expected_arch and published is not None and expected_arch != published:
        mismatch("expected_architectures differs from the set the provisioned build workflow publishes")
    if expected_out and not public_out <= expected_out:
        mismatch("output_binding.artifact_ids lists outputs outside expected_output_ids")

    for name in READINESS_CHECKS + PROMOTION_CHECKS:
        if checks[name] == "mismatch":
            mismatch(f"verification check {name} reports a mismatch")
    for key in ACCEPTANCE_KEYS:
        if checks["acceptance"][key] == "mismatch":
            mismatch(f"verification check acceptance.{key} reports a mismatch")

    if checks["public_references"] == "satisfied":
        if any(component["public_ref"] is None for _, component in _component_entries(meta)):
            mismatch("public_references is satisfied while a component public_ref is unavailable")
        if absent:
            mismatch("public_references is satisfied while a reference is absent from the provisioned package")
    outputs_complete = bool(expected_out) and bound_out == expected_out == public_out
    arches_complete = bool(expected_arch) and bound_arch == expected_arch == public_arch
    if checks["inventory"] == "satisfied" and not (expected_out and expected_arch):
        mismatch("inventory is satisfied while the expected output or architecture inventory is empty")
    if checks["output_binding"] == "satisfied":
        if meta["output_binding"]["status"] != "bound":
            mismatch("output_binding is satisfied while the metadata output_binding is not bound")
        if not outputs_complete:
            mismatch("output_binding is satisfied with an incomplete or different output inventory")
        if not arches_complete:
            mismatch("output_binding is satisfied with an incomplete or different architecture inventory")
    if checks["exact_bom"] == "satisfied":
        if receipt["attestation_id"] != meta["exact_bom"]["attestation_id"]:
            mismatch("exact_bom is satisfied with an attestation_id that differs from the metadata")
        if not (outputs_complete and arches_complete):
            mismatch("exact_bom is satisfied with an incomplete or different output or architecture inventory")
    for key in ACCEPTANCE_KEYS:
        status = meta["acceptance"][key]["status"]
        if checks["acceptance"][key] == "satisfied" and status != "accepted":
            mismatch(f"acceptance.{key} is satisfied while the metadata status is {status}")

    for name in READINESS_CHECKS:
        if checks[name] == "missing":
            report.private.append(f"verification check {name} is missing")
    for key in ACCEPTANCE_KEYS:
        if checks["acceptance"][key] == "missing":
            report.private.append(f"verification check acceptance.{key} is missing")
    for name in PROMOTION_CHECKS:
        if checks[name] != "satisfied":
            report.pending.append(f"verification check {name} is missing; accepted-candidate requires it")


def _identity(meta: dict[str, Any]) -> list[str]:
    lines = [f"IDENTITY: bundle_id {meta['bundle_id']}, association_id {meta['association_id']}, kind {meta['kind']}"]
    lines += [f"ARTIFACT: {where} {component['artifact_id']}" for where, component in _component_entries(meta)]
    lines += [f"OUTPUT: {artifact}" for artifact in meta["output_binding"]["artifact_ids"]]
    if meta["exact_bom"]["attestation_id"] is not None:
        lines.append(f"ATTESTATION: {meta['exact_bom']['attestation_id']}")
    return lines


def validate(metadata: str | Path, package_root: str | Path,
             verification_context: str | Path | None = None) -> Outcome:
    """Validate public metadata against a local checkout and an optional private receipt."""
    report = _Report()
    root = Path(package_root)
    meta = _load(Path(metadata), "metadata", _validate_metadata, report)
    receipt = None
    if verification_context is not None:
        context = Path(verification_context)
        if _inside(context, root):
            report.unavailable.append("verification context must be provisioned outside the package checkout")
        else:
            receipt = _load(context, "verification context", _validate_receipt, report)
    package = _read_package(root, report)

    published: set[str] | None = None
    absent = False
    if meta is not None:
        _public_reasons(meta, report)
        if package is not None:
            published, absent = _check_package(meta, package, root, report)
        if verification_context is None:
            report.private.append(
                "private verification context not supplied: package mapping, public references, inventory, "
                "output binding, exact-BOM equality and acceptance remain unverified")
        elif receipt is not None:
            _check_receipt(meta, receipt, published, absent, report)

    lines: list[str] = []
    derived = None
    errors = ([f"INVALID_DOCUMENT: {reason}" for reason in report.invalid]
              + [f"METADATA_CONFLICT: {reason}" for reason in report.conflict]
              + [f"EVIDENCE_MISMATCH: {reason}" for reason in report.mismatch])
    if errors:
        code = 1
        lines += errors
    elif report.unavailable or meta is None:
        code = 2
        lines += [f"INPUT_UNAVAILABLE: {reason}" for reason in report.unavailable]
    else:
        if report.public or report.private:
            derived = "not-ready"
        elif report.pending:
            derived = "ready-for-review"
        else:
            derived = "accepted-candidate"
        claim = meta["disposition"]
        if claim == derived:
            code = 0
            lines.append(f"VALID: {derived}")
        elif RANK[claim] > RANK[derived] and not report.public:
            code = 2
            lines.append(f"PRIVATE_EVIDENCE_REQUIRED: claimed {claim} cannot be verified without the missing "
                         f"private verification; derived {derived}")
        else:
            code = 1
            lines.append(f"DISPOSITION_MISMATCH: claimed {claim}, derived {derived}")
    if meta is not None:
        lines += _identity(meta)
    lines += [f"K25: {message}" for message in report.k25]
    if derived is not None:
        lines += [f"NOT_READY: {reason}" for reason in report.public + report.private]
        if derived == "ready-for-review":
            lines += [f"PENDING: {reason}" for reason in report.pending]
    lines.append(NOTE)
    return Outcome(code, derived, [_redact(line) for line in lines])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__.splitlines()[0],
        epilog=(
            "Exit 0: VALID: <disposition> when the claim equals the derived result (including not-ready, "
            "with NOT_READY reasons). Exit 1: INVALID_DOCUMENT, METADATA_CONFLICT (conflicting labels or "
            "a K25 failure), EVIDENCE_MISMATCH or DISPOSITION_MISMATCH. Exit 2: PRIVATE_EVIDENCE_REQUIRED "
            "or INPUT_UNAVAILABLE. Without --verification-context the result is public-only and never "
            "above not-ready. An elevated claim blocked by an unmet public prerequisite is "
            "DISPOSITION_MISMATCH in either mode. The receipt is trusted as supplied, never authenticated, and must stay "
            "outside the checkout. Structural verification only: no fetch, tag resolution, build, "
            "write, publication or tag; a valid result is not a release or hardware qualification."
        ),
    )
    parser.add_argument("--metadata", type=Path, required=True,
                        help="public candidate metadata JSON (helianthus-candidate-metadata/1)")
    parser.add_argument("--package-root", type=Path, required=True,
                        help="standalone add-on checkout providing helianthus/config.json, helianthus/Dockerfile, "
                             "helianthus/bom.json and the build and test-image workflows")
    parser.add_argument("--verification-context", type=Path,
                        help="private receipt (helianthus-candidate-verification/1) provisioned outside the "
                             "checkout; omit for public-only mode")
    args = parser.parse_args(argv)
    outcome = validate(args.metadata, args.package_root, args.verification_context)
    print("\n".join(outcome.lines))
    return outcome.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
