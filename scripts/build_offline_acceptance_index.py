#!/usr/bin/env python3
"""Assemble a bounded offline acceptance index for a supplied candidate.

Implements docs/offline-acceptance-index.md. The candidate metadata is validated by
scripts/check_candidate_metadata.py in public-only mode, so the one canonical packaging
shape and every other packaging rule stay that validator's: this tool never reads or
interprets workflows or packaging files itself. Explicit test-result manifests and
separately supplied operator evidence are joined to the candidate by bundle, association
and opaque artifact identity, and every required software and physical gate is reported
as pass, fail or unverified; anything unrecognised is a named reason, never an
interpretation. A complete index is not a candidate disposition, which stays the
validator's and, without its private receipt, never rises above not-ready.

The physical gates are the active form of the gateway's hardware-acceptance catalog, read
from the copy beside this script; a copy whose SHA-256 differs from the pin refuses to start.
Every input is an explicit file inside the supplied worktree. Nothing is executed,
fetched, built, written, deployed, released or tagged, no directory outside the worktree
is listed, and the index never echoes input paths or free-form input text.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import sys
from typing import Any, Callable

import check_candidate_metadata as ccm


INDEX_FORMAT = "helianthus-offline-acceptance-index/1"
RESULTS_FORMAT = "helianthus-offline-test-results/1"
EVIDENCE_FORMAT = "helianthus-operator-evidence/1"
MAX_INPUT_BYTES = 1 << 20  # 1 MiB, as the diagnostics and docs state
MAX_RESULT_FILES = 16
MAX_EVIDENCE_FILES = 16
MAX_ENTRIES = 64
NOTE = (
    "Offline index only: nothing was executed, fetched, built, written, deployed, released or tagged. "
    "Complete means every required gate has one current passing result in the supplied evidence; it is "
    "not a candidate disposition, which stays the candidate metadata validator's. Pass, fail and "
    "unverified are index results, not evidence grades or qualification; physical rows pass only with "
    "separately supplied, reviewed live operator evidence."
)

# ------------------------------------------------------------ gate catalogue
# Software gates: the candidate metadata's public checks (validated here, never supplied as a result) and
# the required local gate of each component repository, run on that component's candidate artifact.
CANDIDATE_GATE = "candidate-metadata-public"
SOFTWARE_GATES = (
    ("addon-local-gate", "addon"),
    ("gateway-local-gate", "gateway"),
    ("explorer-offline-acceptance", "explorer"),
    ("ha-integration-local-gate", "ha_integration"),
)
SOFTWARE_GATE_IDS = tuple(gate for gate, _ in SOFTWARE_GATES)


# Physical gates: one per gate of the active form of the gateway's hardware-acceptance catalog, in the
# catalog's order, taken from the copy beside this script. The copy is used only when its SHA-256 equals the
# pin below, so the catalog changes only through a reviewed change of the copy and the pin together. Every
# gate is a single-case gate (the case is named after the gate) with its own record and review.
CATALOG_FILE = Path(__file__).resolve().parent / "fixtures" / "hardware-acceptance-catalog.json"
CATALOG_SHA256 = "cc0d54e96ac6a9ce35ccfcbab8b998ff6c1558fb0d8a8183f8285b2cd2657bd1"
CATALOG_REFUSED = "the hardware-acceptance catalog copy does not match the pin in this script"
# The handoff's Huawei Modbus TCP rows: for each gateway family of the multi-endpoint contract, in the
# catalog's order, one row per kind of evidence. The gateway registers every Huawei instance withheld until
# that family's own native contract admits a qualification, so these gates stay unverified until the
# operator supplies reviewed live evidence for them. Simulated evidence and software results never count.
HUAWEI_FAMILIES = ("smartlogger", "emma", "sdongle")
HUAWEI_ROWS = ("identity", "monitoring-publication", "degraded-reconnect", "negative-cross-family")
HUAWEI_GATES = tuple(f"huawei-{family}-{row}" for family in HUAWEI_FAMILIES for row in HUAWEI_ROWS)
# The one table from the catalog's retained rows to index gates: each keeps its index name. The output
# binding that the add-on build leaves out maps to None and is not a gate here. Every other row of the
# active form must be a matrix cell, named adaptermux-<transport>-<invariant> in lower case; a row that is
# neither makes the catalog copy unusable. The prior RTU applicability row is historical, never a gate.
RETAINED_GATES: dict[str, str | None] = {
    "P01": "passive-smoke-p01",
    "P02": "passive-smoke-p02",
    "P06": "passive-smoke-p06",
    "ESERA / FOLLOWUP-01": "esera-passive-boundary",
    "LEGACY-PERSIST P1": "legacy-persist-p1",
    "LEGACY-PERSIST P2": "legacy-persist-p2",
    "LEGACY-PERSIST P3": "legacy-persist-p3",
    "LEGACY-PERSIST P4": "legacy-persist-p4",
    "LEGACY-PERSIST P5": "legacy-persist-p5",
    "LEGACY-PERSIST P6": "legacy-persist-p6",
    "LEGACY-PERSIST N1": "legacy-persist-n1",
    "LEGACY-PERSIST N2": "legacy-persist-n2",
    "LEGACY-PERSIST N3": "legacy-persist-n3",
    "LEGACY-PERSIST N4": "legacy-persist-n4",
    "LEGACY-IDENTITY P1": "legacy-identity-p1",
    "LEGACY-IDENTITY P2": "legacy-identity-p2",
    "LEGACY-IDENTITY P3": "legacy-identity-p3",
    "LEGACY-IDENTITY P4": "legacy-identity-p4",
    "LEGACY-IDENTITY P5": "legacy-identity-p5",
    "LEGACY-IDENTITY P6": "legacy-identity-p6",
    "LEGACY-IDENTITY N1": "legacy-identity-n1",
    "LEGACY-IDENTITY N2": "legacy-identity-n2",
    "LEGACY-IDENTITY N3": "legacy-identity-n3",
    "LEGACY-IDENTITY N4": "legacy-identity-n4",
    "LEGACY-IDENTITY N5": "legacy-identity-n5",
    "LEGACY-MUX": "legacy-mux",
    "HA/Ingress routing": "ha-ingress-routing",
    "HA/Ingress trust": "ha-ingress-trust",
    "HA/Ingress lifecycle and identity": "ha-ingress-lifecycle",
    "Explorer Pi": "explorer-pi",
    "INT-12 eeBUS output binding": "eebus-output-binding",
    "INT-13 Matter output binding": None,
    "HUAWEI-SMARTLOGGER identity": "huawei-smartlogger-identity",
    "HUAWEI-SMARTLOGGER monitoring publication": "huawei-smartlogger-monitoring-publication",
    "HUAWEI-SMARTLOGGER degraded and reconnect": "huawei-smartlogger-degraded-reconnect",
    "HUAWEI-SMARTLOGGER negative cross-family": "huawei-smartlogger-negative-cross-family",
    "HUAWEI-EMMA identity": "huawei-emma-identity",
    "HUAWEI-EMMA monitoring publication": "huawei-emma-monitoring-publication",
    "HUAWEI-EMMA degraded and reconnect": "huawei-emma-degraded-reconnect",
    "HUAWEI-EMMA negative cross-family": "huawei-emma-negative-cross-family",
    "HUAWEI-SDONGLE identity": "huawei-sdongle-identity",
    "HUAWEI-SDONGLE monitoring publication": "huawei-sdongle-monitoring-publication",
    "HUAWEI-SDONGLE degraded and reconnect": "huawei-sdongle-degraded-reconnect",
    "HUAWEI-SDONGLE negative cross-family": "huawei-sdongle-negative-cross-family",
}
CELL_ID = re.compile(r"([A-Z]+)-([A-Z]+[0-9]+)")
# A reserved cell is reported without being run: its one passing case outcome is its category's outcome.
CATEGORY_OUTCOMES = ("blocked-infra", "planned")


class CatalogRefusedError(Exception):
    """The catalog copy is not the pinned one, or its active form does not fit this index."""

    def __init__(self) -> None:
        super().__init__(CATALOG_REFUSED)


@dataclass(frozen=True)
class Catalog:
    version: str
    form: str
    gate_names: dict[str, str | None]  # Every row of the active form, in its order, to its gate or None.
    cells: tuple[str, ...]
    reserved: dict[str, tuple[str, str]]  # Cell gate to its first category in precedence order and outcome.

    @property
    def gates(self) -> tuple[str, ...]:
        return tuple(gate for gate in self.gate_names.values() if gate is not None)


def _cell_gate(cell: Any) -> str:
    match = CELL_ID.fullmatch(cell) if type(cell) is str else None
    if match is None:
        raise ValueError("not a matrix cell")
    return f"adaptermux-{match[1].lower()}-{match[2].lower()}"


def _gate_names(doc: dict[str, Any]) -> dict[str, str | None]:
    active, cells = doc["forms"][doc["active_form"]], doc["v2_cells"]
    single = {row["id"] for row in doc["handoff_rows"] if row["kind"] == "single" and row["cases"] == [row["id"]]}
    retained = [row for row in active if row not in cells]
    if (len(set(active)) != len(active) or set(retained) != set(RETAINED_GATES) or not set(cells) <= set(active)
            or not set(retained) <= single):  # No range row and no row of another form.
        raise ValueError("the active form does not fit the gate table")
    names = {row: RETAINED_GATES[row] if row in RETAINED_GATES else _cell_gate(row) for row in active}
    gates = [gate for gate in names.values() if gate is not None]
    if len(set(gates)) != len(gates) or not all(ccm.OPAQUE_ID.fullmatch(gate) for gate in gates):
        raise ValueError("gate names are not distinct opaque IDs")
    return names


def _reserved(doc: dict[str, Any], names: dict[str, str | None]) -> dict[str, tuple[str, str]]:
    categories = {category["id"]: category for category in doc["categories"]}
    reserved: dict[str, tuple[str, str]] = {}
    for cell in doc["v2_cells"]:
        first = next((name for name in doc["category_precedence"] if cell in categories[name]["cases"]), None)
        if first is not None:
            if categories[first]["outcome"] not in CATEGORY_OUTCOMES:
                raise ValueError("a reserved category has an outcome this index cannot accept")
            reserved[names[cell]] = (first, categories[first]["outcome"])
    return reserved


def load_catalog(raw: bytes) -> Catalog:
    """The pinned catalog's active form, checked byte for byte against the pin before it is parsed."""
    if hashlib.sha256(raw).hexdigest() != CATALOG_SHA256:
        raise CatalogRefusedError()
    try:
        doc = ccm._strict_json(raw)
        names = _gate_names(doc)
        return Catalog(doc["version"], doc["active_form"], names,
                       tuple(names[cell] for cell in doc["v2_cells"]), _reserved(doc, names))
    except (ccm._Invalid, KeyError, TypeError, ValueError, AttributeError):
        raise CatalogRefusedError() from None


def _pinned_catalog() -> Catalog | None:
    try:  # One checked descriptor, bounded like every input; the copy is never written.
        return load_catalog(ccm._read_path(CATALOG_FILE))
    except (OSError, RuntimeError, ValueError, ccm._WrongType, CatalogRefusedError):
        return None


CATALOG = _pinned_catalog()  # None when the copy is missing or does not match the pin: nothing starts.
CATALOG_VERSION = CATALOG.version if CATALOG else None
CATALOG_FORM = CATALOG.form if CATALOG else None
GATE_NAMES: dict[str, str | None] = dict(CATALOG.gate_names) if CATALOG else {}
CELL_GATES: tuple[str, ...] = CATALOG.cells if CATALOG else ()
PHYSICAL_GATE_IDS: tuple[str, ...] = CATALOG.gates if CATALOG else ()
ROW_GATES = tuple(gate for gate in PHYSICAL_GATE_IDS if gate not in CELL_GATES)
RESERVED = {gate: outcome for gate, (_, outcome) in (CATALOG.reserved if CATALOG else {}).items()}
RESERVED_UNDER = {gate: category for gate, (category, _) in (CATALOG.reserved if CATALOG else {}).items()}
PHYSICAL_GATES = tuple((gate, (gate,)) for gate in PHYSICAL_GATE_IDS)
CASES = dict(PHYSICAL_GATES)
# Per-row evidence records are published by the project; any other repository is not a record.
EVIDENCE_OWNER = "https://github.com/project-helianthus/"

RESULTS_FIELDS = ("format", "bundle_id", "association_id", "results")
RESULT_FIELDS = ("gate", "artifact_id", "outcome", "omitted_checks")
OUTCOMES = ("pass", "fail", "timeout", "not-run")
EVIDENCE_FIELDS = ("format", "bundle_id", "association_id", "environment", "gates")
EVIDENCE_GATE_FIELDS = ("gate", "independent_review", "evidence_ref", "cases")
CASE_FIELDS = ("case", "outcome")
ENVIRONMENTS = ("live", "simulated")
REVIEW_VALUES = ("satisfied", "missing")
CASE_OUTCOMES = ("pass", "fail", "blocked", "not-run", *CATEGORY_OUTCOMES)
CHECK_NAME = re.compile(r"[a-z0-9][a-z0-9._-]{0,63}")

# Validator result classes. Only VALID (exit 0) establishes the candidate identity: the private receipt
# never enters a worktree, so an elevated claim (PRIVATE_EVIDENCE_REQUIRED) cannot be used either.
CLASSES = ("INVALID_DOCUMENT", "METADATA_CONFLICT", "EVIDENCE_MISMATCH", "DISPOSITION_MISMATCH",
           "PRIVATE_EVIDENCE_REQUIRED", "INPUT_UNAVAILABLE")
UNVERIFIED_CLASSES = {"PRIVATE_EVIDENCE_REQUIRED", "INPUT_UNAVAILABLE"}
# The only unmet public prerequisite tolerated: acceptance decisions that this evidence feeds.
PENDING_ACCEPTANCE = tuple(f"acceptance.{key} is pending" for key in ccm.ACCEPTANCE_KEYS)


@dataclass(frozen=True)
class _Result:
    bundle_id: str
    association_id: str
    gate: str
    artifact_id: str
    outcome: str
    omitted: int


@dataclass(frozen=True)
class _Evidence:
    bundle_id: str
    association_id: str
    live: bool
    gate: str
    reviewed: bool
    evidence_ref: dict[str, str] | None
    cases: dict[str, str]


@dataclass
class Index:
    exit_code: int
    document: dict[str, Any]


# ---------------------------------------------------------- explicit inputs

def _resolve_root(package_root: Path) -> Path | None:
    try:
        root = package_root.resolve(strict=True)
    except (OSError, RuntimeError, ValueError):
        return None
    return root if root.is_dir() else None


def _file_identity(root: Path, relative: str, *, root_fd: int | None = None) -> tuple[int, int] | None:
    """Identity of a record inside the worktree, taken from a no-follow descriptor opened below the root."""
    try:  # Links that stay inside the worktree are followed once, here; the open itself follows none.
        parts = (root / relative).resolve(strict=True).relative_to(root).parts
        descriptor = ccm._open_beneath(root, parts, root_fd=root_fd)
    except (OSError, RuntimeError, ValueError, ccm._WrongType):
        return None
    try:
        info = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    return info.st_dev, info.st_ino


def _read_input(path: Path, root: Path, role: str, seen: set[tuple[int, int]], errors: list[str],
                *, root_fd: int | None = None) -> bytes | None:
    """Read an explicit input: a distinct regular file (also across hard links) inside the worktree.

    The supplied path is resolved only to learn its place below the worktree, so links that stay inside
    remain accepted. The file is then opened one component at a time relative to pinned directory
    descriptors, never following a link, and both its identity and its bytes come from that descriptor.
    """
    try:
        resolved = path.resolve(strict=True)
    except (OSError, RuntimeError, ValueError):
        errors.append(f"{role} cannot be read")
        return None
    if resolved == root or not resolved.is_relative_to(root):
        errors.append(f"{role} is not a file inside the worktree")
        return None
    relative = resolved.relative_to(root).parts
    if ".git" in {part.lower() for part in relative}:
        errors.append(f"{role} is inside repository metadata")
        return None
    try:
        descriptor = ccm._open_beneath(root, relative, root_fd=root_fd)
    except ccm._WrongType:
        errors.append(f"{role} is not a regular file")
        return None
    except OSError as exc:
        errors.append(f"{role} cannot be read ({exc.strerror or type(exc).__name__})")
        return None
    try:
        info = os.fstat(descriptor)
        identity = (info.st_dev, info.st_ino)
        if identity in seen:
            errors.append(f"{role} repeats an input that was already supplied")
            return None
        seen.add(identity)
        return ccm._read_descriptor(descriptor, MAX_INPUT_BYTES)
    except OSError as exc:
        errors.append(f"{role} " + ("exceeds the 1 MiB input limit" if exc.strerror == "exceeds the 1 MiB input limit"
                                    else f"cannot be read ({exc.strerror or type(exc).__name__})"))
        return None
    finally:
        os.close(descriptor)


def _entries(value: Any, where: str, limit: int) -> list[Any]:
    if type(value) is not list or not value:
        raise ccm._Invalid(f"{where} must be a nonempty array")
    if len(value) > limit:
        raise ccm._Invalid(f"{where} must not exceed {limit} entries")
    return value


def _check_name(value: Any, where: str) -> None:
    if type(value) is not str or not CHECK_NAME.fullmatch(value) or ccm._restricted(value):
        raise ccm._Invalid(f"{where} must be a short public check name")


def _validate_results(doc: Any) -> None:
    ccm._object(doc, RESULTS_FIELDS, "document")
    ccm._literal(doc["format"], RESULTS_FORMAT, "format")
    ccm._opaque(doc["bundle_id"], "bundle_id")
    ccm._opaque(doc["association_id"], "association_id")
    for index, entry in enumerate(_entries(doc["results"], "results", MAX_ENTRIES)):
        where = f"results[{index}]"
        ccm._object(entry, RESULT_FIELDS, where)
        ccm._enum(entry["gate"], SOFTWARE_GATE_IDS, f"{where}.gate")
        ccm._opaque(entry["artifact_id"], f"{where}.artifact_id")
        ccm._enum(entry["outcome"], OUTCOMES, f"{where}.outcome")
        if type(entry["omitted_checks"]) is list and len(entry["omitted_checks"]) > MAX_ENTRIES:
            raise ccm._Invalid(f"{where}.omitted_checks must not exceed {MAX_ENTRIES} entries")
        ccm._array(entry["omitted_checks"], f"{where}.omitted_checks", _check_name, allow_empty=True)


def _validate_evidence(doc: Any) -> None:
    ccm._object(doc, EVIDENCE_FIELDS, "document")
    ccm._literal(doc["format"], EVIDENCE_FORMAT, "format")
    ccm._opaque(doc["bundle_id"], "bundle_id")
    ccm._opaque(doc["association_id"], "association_id")
    ccm._enum(doc["environment"], ENVIRONMENTS, "environment")
    gates: set[str] = set()
    for index, entry in enumerate(_entries(doc["gates"], "gates", len(PHYSICAL_GATES))):
        where = f"gates[{index}]"
        ccm._object(entry, EVIDENCE_GATE_FIELDS, where)
        gate = ccm._enum(entry["gate"], PHYSICAL_GATE_IDS, f"{where}.gate")
        if gate in gates:
            raise ccm._Invalid(f"{where}.gate repeats {gate}")
        gates.add(gate)
        ccm._enum(entry["independent_review"], REVIEW_VALUES, f"{where}.independent_review")
        ccm._public_ref(entry["evidence_ref"], f"{where}.evidence_ref")
        cases: set[str] = set()
        for number, case in enumerate(_entries(entry["cases"], f"{where}.cases", len(CASES[gate]))):
            at = f"{where}.cases[{number}]"
            ccm._object(case, CASE_FIELDS, at)
            if type(case["case"]) is not str or case["case"] not in CASES[gate]:
                raise ccm._Invalid(f"{at}.case is not a case of {gate}")
            if case["case"] in cases:
                raise ccm._Invalid(f"{at}.case repeats a case of {gate}")
            cases.add(case["case"])
            outcome = ccm._enum(case["outcome"], CASE_OUTCOMES, f"{at}.outcome")
            if outcome in CATEGORY_OUTCOMES and RESERVED.get(gate) != outcome:  # Never generic missing evidence.
                raise ccm._Invalid(f"{at}.outcome {outcome} is not the category outcome of {gate}")


def _results(doc: dict[str, Any]) -> list[_Result]:
    return [_Result(doc["bundle_id"], doc["association_id"], entry["gate"], entry["artifact_id"],
                    entry["outcome"], len(entry["omitted_checks"])) for entry in doc["results"]]


def _evidence(doc: dict[str, Any]) -> list[_Evidence]:
    return [_Evidence(doc["bundle_id"], doc["association_id"], doc["environment"] == "live", entry["gate"],
                      entry["independent_review"] == "satisfied", entry["evidence_ref"],
                      {case["case"]: case["outcome"] for case in entry["cases"]}) for entry in doc["gates"]]


def _collect(paths: list[Path], limit: int, label: str, root: Path | None, seen: set[tuple[int, int]],
             errors: list[str], validator: Callable[[Any], None], convert: Callable[[Any], list[Any]],
             root_fd: int | None = None) -> list[Any]:
    if len(paths) > limit:
        errors.append(f"at most {limit} {label} files may be supplied")
        return []
    items: list[Any] = []
    for index, path in enumerate(paths):
        role = f"{label}[{index}]"
        raw = _read_input(Path(path), root, role, seen, errors, root_fd=root_fd) if root is not None else None
        if raw is None:
            continue
        try:
            doc = ccm._strict_json(raw)
            validator(doc)
        except ccm._Invalid as exc:
            errors.append(f"{role}: {exc}")
            continue
        items.extend(convert(doc))
    return items


# --------------------------------------------------------------------- rows

def _row(gate: str, status: str, reasons: list[str], **extra: Any) -> dict[str, Any]:
    return {"gate": gate, **extra, "status": status, "reasons": reasons}


def _accepted(outcome: ccm.Outcome | None) -> bool:
    return outcome is not None and outcome.exit_code == 0 and outcome.metadata is not None


def _candidate_row(outcome: ccm.Outcome | None) -> dict[str, Any]:
    extra = {"subject": "candidate metadata", "artifact_id": None}
    if outcome is None:
        return _row(CANDIDATE_GATE, "unverified", ["the candidate metadata was not validated"], **extra)
    if not _accepted(outcome):
        classes = list(dict.fromkeys(line.split(":", 1)[0] for line in outcome.lines
                                     if line.split(":", 1)[0] in CLASSES)) or ["an unrecognised result"]
        status = "unverified" if set(classes) <= UNVERIFIED_CLASSES else "fail"
        return _row(CANDIDATE_GATE, status,
                    [f"the candidate metadata validator reported {', '.join(classes)}"], **extra)
    blocking = [reason for reason in outcome.public_reasons if reason not in PENDING_ACCEPTANCE]
    if blocking:
        return _row(CANDIDATE_GATE, "unverified",
                    [f"unmet candidate prerequisite: {reason}" for reason in blocking], **extra)
    return _row(CANDIDATE_GATE, "pass", [], **extra)


def _current(entry: _Result | _Evidence, meta: dict[str, Any]) -> bool:
    return (entry.bundle_id, entry.association_id) == (meta["bundle_id"], meta["association_id"])


def _software_row(gate: str, component: str, meta: dict[str, Any] | None,
                  results: list[_Result]) -> dict[str, Any]:
    subject = f"components.{component}"
    if meta is None:
        return _row(gate, "unverified", ["the candidate identity was not established"],
                    subject=subject, artifact_id=None)
    artifact = meta["components"][component]["artifact_id"]

    def row(status: str, reason: str | None = None) -> dict[str, Any]:
        return _row(gate, status, [reason] if reason else [], subject=subject, artifact_id=artifact)

    for_gate = [result for result in results if result.gate == gate]
    current = [result for result in for_gate if _current(result, meta)]
    if len(current) > 1:
        return row("unverified", f"{len(current)} results were supplied for this gate and association; "
                                 "exactly one is required")
    if current:
        result = current[0]
        if result.artifact_id != artifact:
            return row("unverified", f"the result names an artifact other than the candidate's {subject}")
        if result.outcome == "fail":
            return row("fail", "the result reports a failure")
        if result.outcome == "timeout":
            return row("unverified", "the run timed out")
        if result.outcome == "not-run":
            return row("unverified", "the check was not run")
        if result.omitted:
            return row("unverified", f"the run omitted {result.omitted} required check(s)")
        return row("pass")
    if any(result.bundle_id == meta["bundle_id"] for result in for_gate):
        return row("unverified", "only results for another association of this bundle were supplied (stale)")
    if for_gate:
        return row("unverified", "only results for a different BOM were supplied")
    return row("unverified", "no result was supplied (missing)")


def _record_key(ref: dict[str, str], root: Path, root_fd: int | None) -> tuple[Any, ...]:
    """Normalized identity of a linked record: the device and inode for this repository, else its path."""
    repository = ref["repository"].lower()
    if repository == ccm.ADDON_REPOSITORY:
        identity = _file_identity(root, ref["path"], root_fd=root_fd)
        if identity is not None:
            return ("file", *identity)
    return ("ref", repository, ref["path"])


def _shared_records(evidence: list[_Evidence], meta: dict[str, Any] | None, root: Path | None,
                    root_fd: int | None) -> set[tuple[Any, ...]]:
    """Record keys linked from more than one current live gate."""
    if meta is None or root is None:
        return set()
    counts: dict[tuple[Any, ...], int] = {}
    for gate in PHYSICAL_GATE_IDS:
        live = [entry for entry in evidence if entry.gate == gate and _current(entry, meta) and entry.live]
        keys = {_record_key(entry.evidence_ref, root, root_fd) for entry in live if entry.evidence_ref is not None}
        for key in keys:  # One count per gate, however many of its own entries link the record.
            counts[key] = counts.get(key, 0) + 1
    return {key for key, count in counts.items() if count > 1}


def _record_problem(ref: dict[str, str] | None, root: Path, inputs: set[tuple[int, int]],
                    shared: set[tuple[Any, ...]] | None = None, *, root_fd: int | None = None) -> str | None:
    """Why a linked per-row evidence record cannot be used, or None."""
    if ref is None:
        return "no per-row evidence record is linked"
    if not ref["repository"].lower().startswith(EVIDENCE_OWNER):
        return "the linked per-row evidence record is not in a Project-Helianthus repository"
    if ccm._absent_locally(ref, root, root_fd=root_fd):  # Only references into this repository are looked up.
        return "the linked per-row evidence record does not exist in the worktree"
    if ref["repository"].lower() == ccm.ADDON_REPOSITORY:
        identity = _file_identity(root, ref["path"], root_fd=root_fd)
        if identity is None:  # Vanished or unopenable since the existence check: nothing to verify.
            return "the linked per-row evidence record does not exist in the worktree"
        if identity in inputs:
            return "the linked per-row evidence record is one of the supplied inputs"
    if shared and _record_key(ref, root, root_fd) in shared:
        return "the linked per-row evidence record is also linked from another gate; each gate needs its own record"
    return None


def _physical_row(gate: str, cases: tuple[str, ...], meta: dict[str, Any] | None,
                  evidence: list[_Evidence], root: Path | None, inputs: set[tuple[int, int]],
                  shared: set[tuple[Any, ...]] | None = None, *, root_fd: int | None = None) -> dict[str, Any]:
    def row(status: str, reason: str | None = None) -> dict[str, Any]:
        return _row(gate, status, [reason] if reason else [], cases=len(cases))

    if meta is None or root is None:
        return row("unverified", "the candidate identity was not established")
    for_gate = [entry for entry in evidence if entry.gate == gate]
    current = [entry for entry in for_gate if _current(entry, meta)]
    live = [entry for entry in current if entry.live]
    if len(live) > 1:
        return row("unverified", f"{len(live)} live operator evidence records were supplied for this gate; "
                                 "exactly one is required")
    if not live:
        if current:
            return row("unverified", "only simulated evidence was supplied; it cannot establish live acceptance")
        if any(entry.bundle_id == meta["bundle_id"] for entry in for_gate):
            return row("unverified", "only operator evidence for another association of this bundle was supplied "
                                     "(stale)")
        if for_gate:
            return row("unverified", "only operator evidence for a different BOM was supplied")
        return row("unverified", "no operator evidence was supplied")
    entry = live[0]
    failed = [case for case in cases if entry.cases.get(case) == "fail"]
    if failed:
        return row("fail", f"{len(failed)} case(s) failed")
    if not entry.reviewed:
        return row("unverified", "independent review of this row's evidence is missing")
    problem = _record_problem(entry.evidence_ref, root, inputs, shared, root_fd=root_fd) or _case_problem(
        cases, entry)
    if problem:
        return row("unverified", problem)
    return row("pass")


def _case_problem(cases: tuple[str, ...], entry: _Evidence) -> str | None:
    """Why the cases of a live, reviewed and recorded entry do not pass the gate, or None."""
    unaccounted = [case for case in cases if case not in entry.cases]
    if unaccounted:
        return f"{len(unaccounted)} case(s) are not accounted for"
    for case in cases:  # A reserved cell passes only with its category outcome, and with nothing else.
        if case in RESERVED and entry.cases[case] != RESERVED[case]:
            return f"the cell is reserved under {RESERVED_UNDER[case]}; its case outcome must be {RESERVED[case]}"
    open_cases = [case for case in cases if entry.cases[case] != RESERVED.get(case, "pass")]
    if open_cases:
        return f"{len(open_cases)} case(s) were blocked or not run"
    return None


def _section(rows: list[dict[str, Any]]) -> dict[str, Any]:
    complete = all(row["status"] == "pass" for row in rows)
    return {"status": "complete" if complete else "incomplete", "gates": rows}


def _sanitized(value: Any) -> Any:
    if isinstance(value, str):
        return ccm._redact(value)
    if isinstance(value, list):
        return [_sanitized(entry) for entry in value]
    if isinstance(value, dict):
        return {key: _sanitized(entry) for key, entry in value.items()}
    return value


def build_index(package_root: str | Path, metadata: str | Path, results: list[str | Path] | None = None,
                operator_evidence: list[str | Path] | None = None) -> Index:
    """Join explicit worktree-local result manifests and operator evidence to a validated candidate."""
    if CATALOG is None:
        raise CatalogRefusedError()
    errors: list[str] = []
    seen: set[tuple[int, int]] = set()
    root = _resolve_root(Path(package_root))
    root_fd = ccm._pin_root(root) if root is not None else None  # Pinned once: every traversal starts here.
    try:
        return _build(root, root_fd, errors, seen, metadata, results, operator_evidence)
    finally:
        if root_fd is not None:
            os.close(root_fd)


def _build(root: Path | None, root_fd: int | None, errors: list[str], seen: set[tuple[int, int]],
           metadata: str | Path, results: list[str | Path] | None,
           operator_evidence: list[str | Path] | None) -> Index:
    outcome = None
    if root is None or root_fd is None:
        root = None
        errors.append("package root is not a readable directory")
    else:
        raw = _read_input(Path(metadata), root, "metadata", seen, errors, root_fd=root_fd)
        if raw is not None:
            # Public-only: the private receipt never enters a worktree. The validator receives the bounded
            # bytes read here, so a file that grows or is swapped afterwards is never read again.
            outcome = ccm.validate(Path(metadata), root, metadata_bytes=raw, root_fd=root_fd)
    supplied = _collect([Path(path) for path in results or []], MAX_RESULT_FILES, "results", root, seen,
                        errors, _validate_results, _results, root_fd)
    evidence = _collect([Path(path) for path in operator_evidence or []], MAX_EVIDENCE_FILES,
                        "operator evidence", root, seen, errors, _validate_evidence, _evidence, root_fd)

    # Rows are joined only to an identity the validator accepted; nothing is looked up for any other.
    meta = outcome.metadata if _accepted(outcome) else None
    software = [_candidate_row(outcome)] + [_software_row(gate, component, meta, supplied)
                                            for gate, component in SOFTWARE_GATES]
    shared = _shared_records(evidence, meta, root, root_fd)
    physical = [_physical_row(gate, cases, meta, evidence, root, seen, shared, root_fd=root_fd)
                for gate, cases in PHYSICAL_GATES]
    rows = software + physical
    complete = not errors and all(row["status"] == "pass" for row in rows)
    identity = outcome.metadata if outcome is not None else None
    candidate = {
        "bundle_id": identity["bundle_id"] if identity else None,
        "association_id": identity["association_id"] if identity else None,
        "kind": identity["kind"] if identity else None,
        "validator": None if outcome is None else {
            "exit_code": outcome.exit_code,
            "derived_disposition": outcome.disposition,  # Public-only, never promoted by this index.
            "lines": [line for line in outcome.lines if line != ccm.NOTE],
        },
    }
    document = {
        "format": INDEX_FORMAT,
        "evidence": "complete" if complete else "incomplete",
        "candidate": candidate,
        "hardware_acceptance_catalog": {"version": CATALOG_VERSION, "form": CATALOG_FORM},
        "software": _section(software),
        "physical": _section(physical),
        "input_errors": errors,
        "blocking": [f"input: {error}" for error in errors]
                    + [f"{row['gate']}: {reason}" for row in rows for reason in row["reasons"]],
        "note": NOTE,
    }
    if errors or not _accepted(outcome):
        code = 1
    else:
        code = 0 if complete else 2
    return Index(code, _sanitized(document))


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:  # A usage error is an input that cannot be used: exit 1, not 2.
        # The message can carry option names, values and paths; only the fixed usage line is printed.
        self.print_usage(sys.stderr)
        self.exit(1, f"{self.prog}: error: the command line cannot be used\n")


def main(argv: list[str] | None = None) -> int:
    if CATALOG is None:  # Refuse before reading any argument or input: no physical gate can be named.
        print(f"{Path(__file__).name}: {CATALOG_REFUSED}", file=sys.stderr)
        return 1
    parser = _Parser(
        description=__doc__.splitlines()[0],
        epilog=(
            "Prints a helianthus-offline-acceptance-index/1 JSON document. Exit 0: complete, every required "
            "software and physical gate passes. Exit 1: an input could not be used (unreadable, outside the "
            "worktree, inside .git, repeated, oversized, malformed, or a usage error) or the candidate "
            "metadata validator did not return VALID. Exit 2: incomplete; each failed or unverified gate "
            "names its reason. Missing, stale, different-BOM, different-artifact, ambiguous, timed-out, "
            "not-run and omitted-check results never count as pass. Physical rows stay unverified unless "
            "separately supplied live operator evidence, reviewed row by row with a linked per-row record, "
            "accounts for every case; simulated evidence never upgrades them. The candidate metadata is "
            "validated in public-only mode; its packaging shape is the validator's decision and a complete "
            "index promotes no disposition. The physical gates are the active form of the pinned "
            "hardware-acceptance catalog copy beside this script; a copy that does not match its SHA-256 pin "
            "refuses to start (exit 1). Reads only that copy, the explicit files named here, which must lie "
            "inside --package-root, and, through the validator, that worktree's packaging files: no execution, "
            "fetch, build, write, deployment, release, tag or listing outside the worktree; the index is "
            "not a release or hardware qualification."
        ),
    )
    parser.add_argument("--package-root", type=Path, required=True,
                        help="the add-on worktree; every other input must be a file inside it")
    parser.add_argument("--metadata", type=Path, required=True,
                        help="the supplied candidate metadata (helianthus-candidate-metadata/1)")
    parser.add_argument("--results", type=Path, action="append", default=[],
                        help=f"a test-result manifest ({RESULTS_FORMAT}); repeat for more, at most "
                             f"{MAX_RESULT_FILES}")
    parser.add_argument("--operator-evidence", type=Path, action="append", default=[],
                        help=f"an operator evidence record ({EVIDENCE_FORMAT}); repeat for more, at most "
                             f"{MAX_EVIDENCE_FILES}")
    args = parser.parse_args(argv)
    index = build_index(args.package_root, args.metadata, args.results, args.operator_evidence)
    print(json.dumps(index.document, indent=2))
    return index.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
