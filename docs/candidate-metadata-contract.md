# Offline candidate metadata contract

This proposal extends [K25 cohort validation](https://github.com/Project-Helianthus/helianthus-ha-addon/blob/main/RELEASE_COHORT.md) for
[issue #252](https://github.com/Project-Helianthus/helianthus-ha-addon/issues/252).
It is a partial INT-16 / INT-17 acceptance slice in
[Project #2](https://github.com/orgs/Project-Helianthus/projects/2).
It specifies a document format and validation order, implemented offline by
[`scripts/check_candidate_metadata.py`](https://github.com/Project-Helianthus/helianthus-ha-addon/blob/main/scripts/check_candidate_metadata.py)
([issue #270](https://github.com/Project-Helianthus/helianthus-ha-addon/issues/270)).
Neither changes packaging nor grants acceptance to the current package.

## Public record and private verification

Public metadata identifies release labels, public repository-relative evidence
references and opaque artifact IDs. It contains no commit coordinates, source
tree IDs, content digests, build pseudoversions containing commit coordinates,
private paths, machine details, device identities or capture times. An opaque
ID is an assigned token, never an encoded or shortened commit or digest.
Release labels describe declarations; they do not prove artifact identity.

Before candidate review, the orchestrator must verify exact-BOM equality in its
private evidence record. That record maps the public association and artifact
IDs to exact source coordinates, resolved dependencies, build inputs, output
bytes and acceptance evidence. The mapping must cover the add-on, gateway,
Explorer, HA integration, every native dependency, container bases, build
toolchains, architecture variants and generated outputs. Mutable release tags
must resolve to the same privately recorded inputs and outputs. A comparison
of labels alone cannot establish equality. Missing records or incomplete
inventory leave equality unverified; any difference is a mismatch.

The public attestation ID points to the result without exposing its coordinates.
An offline reader cannot authenticate that assertion from the JSON alone.
`verified` is usable only when the orchestrator has checked the private record
against the exact bundle under review. Never fetch references, resolve tags or
query a live system while validating this format.

## Schema: `helianthus-candidate-metadata/1`

UTF-8 JSON, one object, with duplicate keys rejected at every depth. All fields
below are required, including explicitly nullable fields. Unknown fields,
enum values, wrong types and empty required collections are invalid. Booleans
are not integers. No free-form extension fields are allowed in this revision.

| Field | Type and rule |
| --- | --- |
| `format` | Literal `helianthus-candidate-metadata/1`. |
| `bundle_id` | Opaque ID of this immutable bundle. |
| `association_id` | Opaque ID binding the entire inventory, outputs and acceptance scope. |
| `kind` | `preparatory` or `candidate`; preparation alone never means accepted. |
| `cohort` | Literal `0.7` for this revision; other cohorts are unsupported, not implicitly accepted. |
| `components` | Object with exactly `addon`, `gateway`, `explorer`, `ha_integration`, `native_dependencies`. |
| `architectures` | Nonempty unique array drawn from `aarch64`, `amd64`, `armv7`, `armhf`, `i386`; must equal the complete set published by the reviewed build workflow for the version tag before readiness. |
| `output_binding` | Object described below. |
| `exact_bom` | Object described below. |
| `acceptance` | Object with exactly `INT-12`, `INT-13`, `INT-14`, `Portal`, `naming`, `identity`. |
| `disposition` | Claimed result: `not-ready`, `ready-for-review` or `accepted-candidate`; must equal the derived result. |

An opaque ID matches `[a-z][a-z0-9]*(?:-[a-z0-9]+)+`, at most 80 characters.
IDs must not embed prohibited publication data even when syntactically valid.
The validator rejects IDs, names, release labels and references containing a
hexadecimal run that resembles a commit or digest fragment or an IPv4 address,
and all but release labels when they contain a date (calendar release labels
remain allowed).
Every component and output artifact ID is unique within its own inventory.

Each of `addon`, `gateway`, `explorer`, `ha_integration` is a component object.
`native_dependencies` is a nonempty array of component objects, with unique
`name` values. A component has exactly these fields:

| Field | Type and rule |
| --- | --- |
| `name` | Nonempty public package or dependency name; no machine or device identity. |
| `release_label` | Public semantic release label or `null` when unavailable. Use K25's release syntax, including optional `v` and prerelease/build suffixes, subject to the publication restrictions above. No `latest`, branch label or opaque source pin. |
| `artifact_id` | Opaque ID for the exact privately mapped artifact. |
| `public_ref` | Public reference object, or `null` if not yet available. |

A public reference has exactly `repository` and `path`. `repository` is the
canonical HTTPS URL of a public GitHub repository, without credentials, query,
fragment or revision. `path` is a nonempty repository-relative file path, without
a leading slash, backslash, empty segment, `.` or `..` segment, URL encoding,
query or fragment. It must identify public documentation or sanitized evidence,
never a private record. Resolve it against that repository's reviewed branch
or default branch; existence and content suitability must be checked from
provisioned offline evidence. The validator checks references into this
add-on repository against the supplied checkout; other repositories rely on
the receipt's `public_references` check. This is a navigation reference, not
an identity proof. Public metadata never needs a pinned blob URL.

Inventory all resolved native dependencies, including transitive dependencies
and replacements. When a dependency has no publishable release label, retain
`null` and its opaque artifact ID; never invent a release or copy a private
pseudoversion. Such a bundle remains `not-ready`. Completeness is established
against the private resolved inventory, not by accepting any nonempty list.

`output_binding` has exactly:

| Field | Type and rule |
| --- | --- |
| `status` | `unbound`, `partial` or `bound`. |
| `association_id` | Current association ID. |
| `artifact_ids` | Unique array of opaque output IDs; empty for `unbound`, nonempty for `partial` or `bound`. |
| `evidence_ref` | Public reference or `null`; required non-null for `bound`. |

`bound` means the private record binds every required output for every declared
architecture to the entire input inventory, including the HA integration
artifact when distributed separately. `partial` preserves known bindings while
making missing outputs explicit in the private record; it never permits
admission. Output IDs cannot substitute for component inventory entries.

`exact_bom` has exactly `status` (`unverified`, `verified`, `mismatch`),
`association_id` (current ID), and `attestation_id` (opaque ID or `null`).
`verified` requires a non-null attestation and complete private equality
verification. An attestation string alone is insufficient. Other statuses must
use `null`; failed or superseded results remain in the private history.

Each acceptance entry has exactly `status` (`pending`, `accepted`, `rejected`),
`association_id` (current ID), and `evidence_ref` (public reference or `null`).
`accepted` requires a non-null reference and a corresponding privately verified
acceptance record for the same association. Acceptance scope comes from the
owning INT or companion contract; this format does not redefine those checks.
Missing evidence can be recorded as `pending` with `null`, never inferred as
accepted. No acceptance entry is optional or silently not applicable.

## Validation and admission order

1. Parse strictly and check the complete schema and publication constraints.
   Malformed documents fail validation; no disposition can be trusted.
2. Compare public inventory to provisioned package metadata. Pass the reviewed
   `helianthus/config.json`, `helianthus/Dockerfile` and
   `.github/workflows/test-image.yml` to K25 as `--addon-config`, `--dockerfile`
   and `--test-image-workflow`. A non-null `components.addon.release_label`
   must equal the config's `version` literally; the canonical build workflow
   derives `BUILD_VERSION` from that version.
   Pass non-null `components.gateway.release_label` as
   `--gateway-release-version`; privately verify its mapping to the effective
   `EBUSGATEWAY_VERSION`, the canonical build workflow's override.
   A non-null `components.explorer.release_label` must equal the effective
   `VRCEXPLORER_VERSION` for the bound output literally: the canonical build
   workflow's override, which is also the release tag its verification step
   checks. Sharing a cohort alone is insufficient for that identity check. K25 still checks all Explorer Dockerfile defaults and
   test-image overrides for cohort consistency; a differently labelled override
   needs its own bundle to bind its outputs. Add-on, Explorer and gateway must
   all declare the 0.7 cohort here. A conflicting release fails; an opaque
   gateway pin needs privately verified release mapping. HA integration and
   native dependencies retain their own release series: do not impose the
   add-on cohort on them. Require every release label and public reference to
   be available before readiness.
3. Check architecture coverage, complete dependency inventory and all output
   bindings against the private record. The declared architecture set must equal
   the set published under the version tag by the provisioned
   `.github/workflows/build.yml`, which must be the canonical packaging shape
   described below.
   The current workflow publishes `aarch64`, `amd64`, `armv7`, `armhf`, `i386`;
   matching only `config.json`'s two architectures leaves the bundle `not-ready`.
   Bind and verify every published architecture, including those outside the
   Supervisor configuration. Require `bound` and verified exact-BOM
   equality before review. Public references and release labels must agree with
   the mapped artifacts. Missing, stale or mismatched private evidence fails
   closed even if all public status strings say otherwise.
4. Check every acceptance association and the provisioned `helianthus/bom.json`
   freeze record described below. Derive `not-ready` for a preparatory bundle,
   an unfrozen BOM, unavailable component metadata, incomplete bindings,
   unverified or mismatched equality, or any pending/rejected/missing INT-12, INT-13, INT-14,
   Portal, naming or identity acceptance. For a candidate with all these checks
   satisfied, derive `ready-for-review` while independent review is pending.
   Derive `accepted-candidate` only after the orchestrator additionally verifies
   the required independent exact-bundle review and full required gates in its
   private record for this same association. No public self-declaration can
   promote the result. A claimed disposition differing from the derived result
   fails validation.

### Canonical packaging shape

Per the [owner decision on issue #270](https://github.com/Project-Helianthus/helianthus-ha-addon/issues/270),
M45 recognises exactly one canonical packaging shape: this repository's
`.github/workflows/build.yml`, including its manifest job, as it stands on
main. M45 matches the provisioned file line for line, element by element,
against that form and never interprets workflow or shell constructs:

- the triggers, permissions and image environment, and the build job header;
- the architecture matrix: `amd64`, `aarch64`, `armv7`, `armhf`, `i386`;
- each job's checkout step;
- the version-output step `addon`, which runs `set -euo pipefail` followed by
  the single assignment
  `echo "version=$(jq -r '.version' helianthus/config.json)" >> "$GITHUB_OUTPUT"`;
  the build job and the manifest job must each contain exactly this step, and
  both are matched by the same rule;
- the Explorer release-tag verification step and the set-up and registry
  login steps;
- the build step after them, with its explicit
  `push: ${{ github.event_name != 'pull_request' }}` input, platform,
  version-architecture tags, labels, build-args (`BUILD_VERSION` from the
  version output, `BUILD_FROM` from the matrix) and secrets;
- the manifest job header, its registry login step, the `latest` manifest
  command, the version manifest member list and the GHCR visibility check,
  with nothing after it.

The only variable values are two plain literals: the Explorer release,
identical in the release-tag verification step and the `VRCEXPLORER_VERSION`
override, and the `EBUSGATEWAY_VERSION` override. Every packaging input named
in steps 2–4 must resolve, after following symlinks, to a file inside the
package root. Anything unrecognised, reordered, unreachable or extra, such as
a comment, a step moved before the version output, a guarded or early-exited
assignment, an omitted or different `push` input, a changed manifest member, or
an additional job, step, build-arg record or manifest command, derives
`not-ready` with `NOT_READY: unrecognised packaging shape: …`. The reason names
the canonical element expected where the first difference occurs, or the input
that resolves outside the package root. Generalising M45 to other packaging
shapes is out of scope for 0.7. A change to the build workflow on main must
update the validator's canonical form in the same change; the validator tests
check that this checkout's workflow is recognised.

### Offline verification context and M45 results

M45's offline interface is `validate(metadata, package_root,
verification_context=None)`. `metadata` and `verification_context` are paths to
UTF-8 JSON files; `package_root` is the standalone checkout containing the
packaging files named in steps 2–4. All paths are explicit caller inputs; no
sibling checkout, environment variable, home-directory file, network lookup or
installed adapter is consulted. The command form is
`python3 scripts/check_candidate_metadata.py --metadata <file> --package-root
<checkout> [--verification-context <receipt>]`.

The optional context file is a private verification receipt in format
`helianthus-candidate-verification/1`. It is the complete input boundary for
private verification: M45 consumes this receipt, not an unspecified private
record or adapter. Before invoking M45, the operator obtains it from the
orchestrator responsible for the bundle, together with the reviewed bundle's
local inputs and outputs. The orchestrator checks its underlying source/build
and acceptance records against those exact bytes offline, then exports the
receipt below directly as JSON; no exporter or adapter installation is assumed.
If it cannot supply that verified receipt, use public-only mode; no private
store or export service is required for that mode.

The operator must provision the receipt through a trusted channel separately
from the candidate metadata and confirm it covers the actual local bundle.
M45 does not authenticate a receipt or reproduce the orchestrator's underlying
source/build verification. An arbitrary candidate-supplied JSON file is not
trusted verification. A receipt is valid only for that invocation's unchanged
bundle and package inputs; any change requires re-verification and a new
association as specified below. Keep receipts outside the checkout and never
commit them; a receipt path inside the package checkout is `INPUT_UNAVAILABLE`.
The receipt uses opaque IDs and sanitized results only; underlying private
coordinates stay in the orchestrator's private records.

The receipt is one object with exactly the following required fields. Apply the
public JSON's duplicate-key, type, unknown-field and opaque-ID rules. Arrays
are unique sets; compare them without regard to order. Inventories describe the
complete expected inventory even when a check is missing; use an empty array
when it cannot be established and report that check as `missing`.

| Field | Type and rule |
| --- | --- |
| `format` | Literal `helianthus-candidate-verification/1`. |
| `bundle_id`, `association_id` | Opaque IDs; each must equal the corresponding public field. |
| `attestation_id` | Opaque ID for satisfied exact-BOM equality, otherwise `null`; must equal the public attestation when equality is satisfied. |
| `components` | Object with exactly `addon`, `gateway`, `explorer`, `ha_integration`, `native_dependencies`; each value has the same shape and publication rules as its public counterpart and must equal it, including names, release labels, references and artifact IDs. |
| `expected_architectures` | Array of architecture values allowed by the public schema, derived from the provisioned build workflow. |
| `bound_architectures` | Array of those architecture values whose complete outputs were verified. |
| `expected_output_ids` | Array of opaque IDs for every required output of every expected architecture, including separately distributed artifacts. |
| `bound_output_ids` | Array of opaque IDs whose input/output bindings were verified. |
| `checks` | Object with exactly `package_mapping`, `public_references`, `inventory`, `output_binding`, `exact_bom`, `acceptance`, `independent_review`, `required_gates`. |

Every check value is `satisfied`, `missing` or `mismatch`, except `acceptance`,
which is an object with exactly the six public acceptance keys and one such
value for each. `missing` includes stale, unavailable or unmet verification
prerequisites. These are verification results, not evidence grades; vocabulary remains
`Proven`, `Hypothesis`, `Unknown`. The entire receipt, including every check,
is scoped to its top-level bundle and association IDs.

- `package_mapping` verifies component release/artifact mappings against the
  provisioned packaging and effective build arguments in step 2.
- `public_references` verifies the existence and suitability of every non-null
  public reference against offline copies and binds them to the mapped artifacts;
  it includes output and acceptance references. M45 never resolves them online.
- `inventory` verifies complete source, dependency (including transitive and
  replacement), container-base and toolchain coverage described above.
- `output_binding` verifies every output's binding to that complete inventory.
- `exact_bom` reports the exact input/output equality comparison.
- Each `acceptance` value verifies the owning contract's acceptance evidence and
  its public reference for this association. Pending or rejected acceptance
  cannot be `satisfied`; use `missing` when no accepted result is established,
  or `mismatch` when the evidence contradicts the public acceptance claim.
- `independent_review` and `required_gates` verify the required independent
  exact-bundle review and complete required gates respectively; pending review
  or gates, blocking findings and failed gates cannot be `satisfied`. Use
  `missing` for unmet prerequisites and `mismatch` for contradictory evidence.

M45 strictly validates the receipt before using it. A malformed receipt is
`INVALID_DOCUMENT`; unreadable explicitly supplied inputs are `INPUT_UNAVAILABLE`.
An ID/component conflict or contradictory inventory is `EVIDENCE_MISMATCH`.
Bound inventories must be subsets of expected inventories. To satisfy readiness,
expected and bound architecture sets must both equal the public architecture
set and the provisioned build workflow's published set; expected and bound output
sets must both equal public `output_binding.artifact_ids`. An incomplete subset
is missing verification, never a satisfied binding. A `satisfied` check with
incomplete required inventories or a missing required public reference is a
contradiction and fails with `EVIDENCE_MISMATCH`. An empty expected inventory
cannot satisfy its check. Public `verified`, `bound` and `accepted` claims
require the corresponding satisfied checks to be verified; strings alone never
supply evidence. Missing checks leave those claims unverified.

Readiness requires satisfied `package_mapping`, `public_references`, `inventory`,
`output_binding`, `exact_bom` and every acceptance check, plus all public
prerequisites in steps 2–4. Missing independent review or gates leaves an
otherwise ready candidate `ready-for-review`; both must be satisfied for
`accepted-candidate`. Any `mismatch` fails validation, including for `not-ready`.
Omitting the context file selects public-only mode; omitting a required field
inside a supplied receipt is malformed, not an implicit pass.

In public-only mode, check all available schema, publication and packaging
constraints, report private equality, bindings and acceptance as unverified,
and derive `not-ready`. A valid document claiming `not-ready` succeeds with
that result; a claim of `ready-for-review` or `accepted-candidate` whose public
prerequisites are satisfied reports `PRIVATE_EVIDENCE_REQUIRED` and cannot
succeed. This is an inability to verify the claim, not proof of a mismatch.
Never promote a public-only result.

M45 must use these exit codes and diagnostic classes (with sanitized reasons):

| Exit | Message class and meaning |
| --- | --- |
| `0` | `VALID: <disposition>` when the claim equals the derived result, including `not-ready`; success does not itself mean readiness. Include `NOT_READY` reasons for unmet prerequisites. |
| `1` | `INVALID_DOCUMENT` for syntax/schema/publication violations; `METADATA_CONFLICT` for conflicting labels or K25 failure; `EVIDENCE_MISMATCH` for contradictory private evidence; `DISPOSITION_MISMATCH` for a claim inconsistent with the derived result when missing private verification is not the cause. |
| `2` | `PRIVATE_EVIDENCE_REQUIRED` when missing/stale private context prevents verifying an elevated disposition claim; or `INPUT_UNAVAILABLE` when a required local packaging/evidence input cannot be read. |

Definite invalidity or conflict takes precedence over missing verification.
An elevated claim blocked by an unmet public prerequisite (for example a
preparatory kind, pending acceptance or an unfrozen BOM) is therefore
`DISPOSITION_MISMATCH` in either mode; `PRIVATE_EVIDENCE_REQUIRED` applies only
when private verification alone is missing.
Missing private checks leave a correctly claimed `not-ready` document valid;
private mismatches fail validation even when it claims `not-ready`. With a
complete trusted context, derive and compare dispositions in steps 3–4 above.
Required local input failures use `INPUT_UNAVAILABLE` in either mode. These
results belong to the M45 validator, not the existing K25 checker.

K25's exit zero means no declared cohort conflict and can include `UNVERIFIED`
or `NOT_APPLICABLE`; neither establishes candidate readiness. Its existing
behavior outside 0.7 remains unchanged. Current package versions are not
rewritten by this proposal. The current
[BOM checker](https://github.com/Project-Helianthus/helianthus-ha-addon/blob/main/scripts/bom_manifest.py) and [packaging BOM](https://github.com/Project-Helianthus/helianthus-ha-addon/blob/main/helianthus/bom.json)
remain gated by `scripts/ci_local.sh`: they check packaging consistency and
carry the INT-16 freeze record (`freeze.owner` and `freeze.status`).
`kind: preparatory` may describe an `unfrozen` BOM; `kind: candidate` requires
`freeze.status: frozen` with `freeze.owner: INT-16` before readiness. A frozen
BOM alone establishes neither verified output identity nor candidate acceptance.
The candidate metadata prohibition on exact coordinates, timestamps and digests
applies to candidate metadata only; the existing packaging BOM intentionally
records exact revisions and is not a candidate metadata template. Do not copy
those values into candidate metadata. This distinction does not authorize new
publication of restricted values in other files.

Any input, resolved dependency, configuration, wrapper, build toolchain,
container base, architecture or output change creates a new bundle and
association, even if every release label stays the same. Allocate new artifact
IDs for changed artifacts; unchanged artifacts may retain their IDs. Reset
equality to `unverified` and all acceptance entries to `pending`; output bindings
must be re-established for the new association. Previous accepted evidence
remains immutable history, never acceptance for the changed bundle. An
evidence correction or scope change also needs a new association and review.
Keep partial last-known-good state as historical evidence without promoting it
to current acceptance or changing runtime admission.

This is an offline packaging record. It does not decode protocols, qualify
device families or authorize writes. Native public documentation remains the
protocol contract; preserve native evidence and qualification separately from
the evidence vocabulary `Proven`, `Hypothesis`, `Unknown`. Metadata cannot
upgrade any of them. Existing eBUS MCP compatibility, GraphQL parity and native
trust safeguards remain required by their owning contracts. All MCP namespaces
remain pre-stable; this format creates no namespace or authorization gate.
Nothing here declares stability before 1.0. Candidate acceptance does not
publish a release, deploy, install or mutate a live system.
`accepted-candidate` does not imply hardware qualification; reference the
[consolidated hardware session](https://github.com/Project-Helianthus/helianthus-ebusgateway/issues/1099)
results under the same `association_id`, without duplicating them here.

## Synthetic preparatory example

The labels and IDs below are invented, not claims about published packages.
The deliberately incomplete acceptance makes the only valid disposition
`not-ready`.

```json
{
  "format": "helianthus-candidate-metadata/1",
  "bundle_id": "bundle-synthetic-alpha",
  "association_id": "association-synthetic-alpha",
  "kind": "preparatory",
  "cohort": "0.7",
  "components": {
    "addon": {
      "name": "helianthus-ha-addon",
      "release_label": "0.7.0-rc.1",
      "artifact_id": "artifact-addon-alpha",
      "public_ref": {
        "repository": "https://github.com/Project-Helianthus/helianthus-ha-addon",
        "path": "RELEASE_COHORT.md"
      }
    },
    "gateway": {
      "name": "helianthus-ebusgateway",
      "release_label": "v0.7.0-rc.1",
      "artifact_id": "artifact-gateway-alpha",
      "public_ref": null
    },
    "explorer": {
      "name": "helianthus-vrc-explorer",
      "release_label": "v0.7.0-rc.1",
      "artifact_id": "artifact-explorer-alpha",
      "public_ref": null
    },
    "ha_integration": {
      "name": "synthetic-ha-integration",
      "release_label": null,
      "artifact_id": "artifact-integration-alpha",
      "public_ref": null
    },
    "native_dependencies": [
      {
        "name": "synthetic-native-family-library",
        "release_label": null,
        "artifact_id": "artifact-native-alpha",
        "public_ref": null
      }
    ]
  },
  "architectures": ["aarch64", "amd64"],
  "output_binding": {
    "status": "unbound",
    "association_id": "association-synthetic-alpha",
    "artifact_ids": [],
    "evidence_ref": null
  },
  "exact_bom": {
    "status": "unverified",
    "association_id": "association-synthetic-alpha",
    "attestation_id": null
  },
  "acceptance": {
    "INT-12": {"status": "pending", "association_id": "association-synthetic-alpha", "evidence_ref": null},
    "INT-13": {"status": "pending", "association_id": "association-synthetic-alpha", "evidence_ref": null},
    "INT-14": {"status": "pending", "association_id": "association-synthetic-alpha", "evidence_ref": null},
    "Portal": {"status": "pending", "association_id": "association-synthetic-alpha", "evidence_ref": null},
    "naming": {"status": "pending", "association_id": "association-synthetic-alpha", "evidence_ref": null},
    "identity": {"status": "pending", "association_id": "association-synthetic-alpha", "evidence_ref": null}
  },
  "disposition": "not-ready"
}
```

Offline consumer checks must also exercise duplicate keys, unknown fields,
missing acceptance entries, mismatched associations, absent private evidence,
partial outputs, preparatory self-promotion and component changes under reused
labels. Parsing this example proves JSON syntax only. The validator's synthetic
tests exercise these cases and `./scripts/ci_local.sh` runs them; that gate
checks no real candidate and establishes no readiness.
