# Offline candidate metadata contract

This proposal extends [K25 cohort validation](../RELEASE_COHORT.md) for
[issue #252](https://github.com/Project-Helianthus/helianthus-ha-addon/issues/252).
It is a partial INT-16 / INT-17 acceptance slice in
[Project #2](https://github.com/orgs/Project-Helianthus/projects/2).
It specifies a document format and validation order; it does not implement a
validator, change packaging, or grant acceptance to the current package.

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
| `architectures` | Nonempty unique array drawn from `aarch64`, `amd64`, matching the reviewed package configuration. |
| `output_binding` | Object described below. |
| `exact_bom` | Object described below. |
| `acceptance` | Object with exactly `INT-12`, `INT-13`, `INT-14`, `Portal`, `naming`, `identity`. |
| `disposition` | Claimed result: `not-ready`, `ready-for-review` or `accepted-candidate`; must equal the derived result. |

An opaque ID matches `[a-z][a-z0-9]*(?:-[a-z0-9]+)+`, at most 80 characters.
IDs must not embed prohibited publication data even when syntactically valid.
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
provisioned offline evidence. This is a navigation reference, not an identity
proof. Public metadata never needs a pinned blob URL.

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
2. Compare public inventory to provisioned package metadata. Apply K25 to the
   add-on release, all Explorer Dockerfile defaults and test-image overrides,
   and declared gateway release. All three must declare the 0.7 cohort here.
   A conflicting release fails; an opaque gateway pin needs privately verified
   release mapping. HA integration and native dependencies retain their own
   release series: do not impose the add-on cohort on them. Require every
   release label and public reference to be available before readiness.
3. Check architecture coverage, complete dependency inventory and all output
   bindings against the private record. Require `bound` and verified exact-BOM
   equality before review. Public references and release labels must agree with
   the mapped artifacts. Missing, stale or mismatched private evidence fails
   closed even if all public status strings say otherwise.
4. Check every acceptance association. Derive `not-ready` for a preparatory
   bundle, unavailable component metadata, incomplete bindings, unverified or
   mismatched equality, or any pending/rejected/missing INT-12, INT-13, INT-14,
   Portal, naming or identity acceptance. For a candidate with all these checks
   satisfied, derive `ready-for-review` while independent review is pending.
   Derive `accepted-candidate` only after the orchestrator additionally verifies
   the required independent exact-bundle review and full required gates in its
   private record for this same association. No public self-declaration can
   promote the result. A claimed disposition differing from the derived result
   fails validation.

K25's exit zero means no declared cohort conflict and can include `UNVERIFIED`
or `NOT_APPLICABLE`; neither establishes candidate readiness. Its existing
behavior outside 0.7 remains unchanged. Current package versions are not
rewritten by this proposal. The existing
[BOM checker](../scripts/bom_manifest.py) checks packaging consistency but does
not authenticate build outputs or provide this new validation contract. Its
legacy manifest is not a public candidate metadata template: do not copy its
exact coordinates, timestamps or digests into a candidate document.

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
labels. Parsing this example proves JSON syntax only. Implementing and
registering a validator requires a separately owned code change; this document
does not add an executable gate or imply that its checks already run in CI.
