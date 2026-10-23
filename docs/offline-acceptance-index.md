# Offline acceptance index

[`scripts/build_offline_acceptance_index.py`](https://github.com/Project-Helianthus/helianthus-ha-addon/blob/main/scripts/build_offline_acceptance_index.py)
assembles a bounded index of supplied test results for one already supplied 0.7
candidate ([issue #273](https://github.com/Project-Helianthus/helianthus-ha-addon/issues/273)).
It is a partial INT-17 preparation slice in
[Project #2](https://github.com/orgs/Project-Helianthus/projects/2): it collects
evidence, it does not produce it. It runs no check, fetches nothing, and builds,
writes, deploys, releases or tags nothing. A complete index is neither a release,
a candidate disposition nor hardware qualification.

```bash
python3 scripts/build_offline_acceptance_index.py --package-root <worktree> \
  --metadata <candidate.json> [--results <manifest.json> ...] \
  [--operator-evidence <record.json> ...]
```

The index is printed as one `helianthus-offline-acceptance-index/1` JSON document.

| Exit | Meaning |
| --- | --- |
| `0` | Complete: every required software and physical gate passes. |
| `1` | An input could not be used (unreadable, outside the worktree, inside `.git`, repeated, oversized or malformed, or a usage error), or the candidate metadata validator did not return `VALID`. |
| `2` | Incomplete: each failed or unverified gate names its reason. |

## Inputs

Every input is an explicit file named on the command line. Each must resolve,
after following links, to a regular file inside `--package-root` and outside
`.git`, at most 1 MiB, named once (a hard link to an input counts as the same
input). At most 16 result manifests and 16 operator
evidence records are read. Through the candidate metadata validator, the
worktree's packaging files are read as well. Nothing else is consulted: no
environment variable, home-directory file, sibling checkout, glob, default path
or network lookup. The only directory listings are the exact-case lookups of
references into this repository, and they never leave the worktree.
Diagnostics name an input by its role and position, never by its path, and never
echo unknown keys or other free-form input text.

All documents are strict UTF-8 JSON as in the
[candidate metadata contract](https://github.com/Project-Helianthus/helianthus-ha-addon/blob/main/docs/candidate-metadata-contract.md):
duplicate keys, unknown or missing fields, wrong types and unknown values make
the whole document unusable. IDs are opaque IDs under the same publication
rules. Manifests carry no paths, host or network details, serials, captures,
times, contributor identities or source coordinates.

### Candidate metadata

The metadata is validated by
[`scripts/check_candidate_metadata.py`](https://github.com/Project-Helianthus/helianthus-ha-addon/blob/main/scripts/check_candidate_metadata.py)
against the worktree, in public-only mode: the private verification receipt
stays outside the checkout, while this tool reads only worktree-local inputs.
The packaging checks, including the one canonical packaging shape, remain that
validator's; this tool reads no workflow or packaging file itself.

Only a `VALID` result establishes the candidate identity. Any other result
leaves the `candidate-metadata-public` row unverified (`PRIVATE_EVIDENCE_REQUIRED`,
`INPUT_UNAVAILABLE`) or failed (every other class), exits `1`, and joins no
result or evidence to the candidate. A claim the validator can verify only with
its private receipt is therefore not usable here: supply metadata whose claim the
validator accepts in public-only mode.

With `VALID`, the row passes only when the validator reports no unmet public
prerequisite other than an acceptance entry that is still `pending`, because
those acceptance decisions are what the indexed evidence feeds. An unrecognised
packaging shape, a preparatory kind, an unfrozen BOM, unavailable labels or
references, outputs that are not bound, exact-BOM equality that is not claimed
verified, or a rejected acceptance entry leaves the row unverified with the
validator's reason. The index relies on the validator's public checks only: it
cannot check the private record behind a `verified` or `bound` claim and makes no
claim about it.

### Test-result manifests

A `helianthus-offline-test-results/1` manifest reports software gate runs:

```json
{
  "format": "helianthus-offline-test-results/1",
  "bundle_id": "bundle-synthetic-example",
  "association_id": "association-synthetic-example",
  "results": [
    {"gate": "addon-local-gate", "artifact_id": "artifact-addon-example",
     "outcome": "pass", "omitted_checks": []}
  ]
}
```

`results` holds 1 to 64 entries. `gate` is one of the software gates below
except `candidate-metadata-public`; a physical gate is invalid here. `outcome` is
`pass`, `fail`, `timeout` or `not-run`. `omitted_checks` names each required
check the run skipped, such as a network-only step, as a short public name
(`[a-z0-9][a-z0-9._-]*`, at most 64 characters, no restricted data); the index
reports only their count.

### Operator evidence records

A `helianthus-operator-evidence/1` record reports physical gate results:

```json
{
  "format": "helianthus-operator-evidence/1",
  "bundle_id": "bundle-synthetic-example",
  "association_id": "association-synthetic-example",
  "environment": "live",
  "gates": [
    {"gate": "passive-smoke-p01", "independent_review": "satisfied",
     "evidence_ref": {"repository": "https://github.com/Project-Helianthus/helianthus-ebusgateway",
                      "path": "docs/testing/synthetic-example-record.md"},
     "cases": [{"case": "passive-smoke-p01", "outcome": "pass"}]}
  ]
}
```

`environment` is `live` or `simulated`; fixture, replay and emulator runs are
`simulated`. Each gate appears at most once per record, with its own
`independent_review` (`satisfied` or `missing`), its own public per-row evidence
record reference (the candidate metadata public reference form; `null` when not
yet available) and cases drawn from that gate's case list, each at most once. A
case `outcome` is the owning procedure's per-case disposition: `pass`, `fail`,
`blocked` or `not-run`. The owning gate's classification decides it: a
documented expected failure is `pass` only when that classification accepts the
case, and an unexpected failure, an unexpected pass or an infrastructure block is
`fail` or `blocked`, never `pass`. Operator evidence is supplied only through
`--operator-evidence`; a record passed as a result manifest, or the reverse, is
malformed.

## Required gates

The catalogue is fixed in the tool. Rows are never taken from the inputs, so an
omitted gate cannot disappear; changing the catalogue needs a reviewed change to
the tool and this page.

| Software gate | Subject | Required result |
| --- | --- | --- |
| `candidate-metadata-public` | Candidate metadata | Computed by this tool as described above; never supplied. |
| `addon-local-gate` | `components.addon` | This repository's `./scripts/ci_local.sh` on the candidate add-on artifact. |
| `gateway-local-gate` | `components.gateway` | The gateway repository's required local gate on the candidate gateway artifact. |
| `explorer-offline-acceptance` | `components.explorer` | The [Explorer offline acceptance card](https://github.com/Project-Helianthus/helianthus-vrc-explorer/blob/main/docs/offline-acceptance.md) on the candidate Explorer artifact. |
| `ha-integration-local-gate` | `components.ha_integration` | The HA integration repository's required local gate on the candidate integration artifact. |

There is one physical gate per live-result row of the gateway's
[consolidated candidate hardware acceptance handoff](https://github.com/Project-Helianthus/helianthus-ebusgateway/blob/main/docs/testing/consolidated-candidate-handoff.md),
in its order; its procedures, preconditions and stop conditions govern every
case. A range row accounts for every case ID in its range through one per-case
report. Every other row is a single-case gate whose one case is named after the
gate, with its own per-row record and review.

| Physical gates | Handoff rows | Cases |
| --- | --- | --- |
| `transport-direct-adapter` | T01–T04 | `T01`–`T04` |
| `transport-ebusd-tcp` | T05–T08 | `T05`–`T08` |
| `transport-proxy-single-client` | T09–T24 | `T09`–`T24` |
| `transport-proxy-dual-client` | T25–T88 | `T25`–`T88` |
| `proxy-semantics-adjunct` | PX01–PX12 | `PX01`–`PX12` |
| `adapter-direct-ad01` … `adapter-direct-ad12` | AD01 … AD12 | the gate's own ID |
| `passive-smoke-p01` … `passive-smoke-p06` | P01 … P06 | the gate's own ID |
| `esera-passive-boundary` | ESERA / FOLLOWUP-01 | the gate's own ID |
| `legacy-persist-p1` … `legacy-persist-p6`, `legacy-persist-n1` … `legacy-persist-n4` | LEGACY-PERSIST P1 … N4 | the gate's own ID |
| `legacy-identity-p1` … `legacy-identity-p6`, `legacy-identity-n1` … `legacy-identity-n5` | LEGACY-IDENTITY P1 … N5 | the gate's own ID |
| `legacy-mux` | LEGACY-MUX | the gate's own ID |
| `ha-ingress-routing`, `ha-ingress-trust`, `ha-ingress-lifecycle` | HA/Ingress routing, trust, lifecycle and identity | the gate's own ID |
| `explorer-pi` | Explorer Pi | the gate's own ID |
| `eebus-output-binding`, `matter-output-binding` | INT-12 eeBUS and INT-13 Matter output binding | the gate's own ID |

The handoff makes `PX01`–`PX12` conditional on proxy wire semantics being in
scope; the index cannot decide scope, so the row stays required until an owner
decision changes this catalogue. The handoff's prior RTU applicability row is
not a gate: it records historical evidence that stays Not run for this
candidate, with no repeat session scheduled, and the index never turns it into
a live result.

## Joining and row results

Results are joined to the validated candidate by bundle, association and opaque
artifact identity. A manifest or record is current only when both its
`bundle_id` and `association_id` equal the candidate's.

A software row passes only when exactly one current result names the gate, that
result names the candidate's artifact for the row's subject, its outcome is
`pass` and it omitted no check. Otherwise the row is:

- `fail` when the single current result reports `fail`;
- `unverified` when the result timed out, was not run, omitted checks or names
  another artifact; when more than one current result names the gate; when only
  results for another association of the same bundle (stale) or for another
  bundle (a different BOM) exist; or when no result exists (missing).

A physical row passes only when exactly one current `live` record covers the
gate, its entry has `independent_review: satisfied` and a linked per-row
evidence record, and every case of the gate is `pass`. The record must be in a
Project-Helianthus repository; when it points into this repository it must
exist in the worktree and must not be one of the supplied inputs, also through a
hard link. With that one
live record, any failed case makes the row `fail`. Otherwise the row stays
`unverified`: no evidence, only simulated evidence, only stale or different-BOM
evidence, more than one live record, a missing review or record, or a case that
is blocked, not run or not accounted for. A record linked from more than one
gate leaves each of those gates `unverified`, also when the links reach the same
file under different spellings. Software results never reach physical rows.

The index is `complete` only when no input error occurred and every row passes;
missing and stale results keep it `incomplete`. Each section reports `complete`
or `incomplete`, and `blocking` lists every input error and every row reason.
The index also carries the candidate's opaque IDs, the validator's exit code,
its public-only derived disposition and its own sanitized lines, never input
paths or values from manifests that do not match the candidate. A complete index
promotes no disposition: the candidate stays `not-ready` until the validator,
with its private receipt, derives more.

## Limits

`pass`, `fail` and `unverified` are index results for the supplied evidence,
not evidence grades: the evidence vocabulary remains `Proven`, `Hypothesis`,
`Unknown`, and qualification and admission stay separate decisions under their
owning contracts. The index authenticates no manifest or record, reads no record
outside this repository and reproduces no run; it trusts its explicit inputs
only as far as these rules allow. Live results stay with the consolidated
operator session and its separately authorized procedures; nothing here
authorizes a device action, an installation write or a release. Any candidate
change creates a new association under the candidate metadata contract, which
makes every earlier result stale here.
