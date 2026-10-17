# Coherent cohort upgrades and rollback limits

This is the proposed operator contract for the bundled add-on, gateway and
Explorer 0.7, specified by issue #256. It changes no build, version, setting or
runtime behavior. Refs parent #246: packaging, wrapper regression, candidate
acceptance and release delivery remain outstanding with their owners.
Nothing is stable before Helianthus 1.0. This contract adds no authorization
gate before 0.9 and does not change existing admission or trust safeguards.

## Current contents versus proposed delivery

The following are offline source observations, not verification of an installed
image or a published registry artifact. Recheck them for the bundle under review.

| Operator-visible choice | Current source / proposed requirement | What the label proves |
| --- | --- | --- |
| Unchanged 0.6 catalog contents | [Add-on configuration](https://github.com/Project-Helianthus/helianthus-ha-addon/blob/main/helianthus/config.json) declares `0.6.58`; [Dockerfile](https://github.com/Project-Helianthus/helianthus-ha-addon/blob/main/helianthus/Dockerfile) defaults Explorer to `v0.6.1` and uses an opaque gateway source pin. Leave these contents unchanged in this slice. | A catalog label is a declaration, not proof of the installed bytes or gateway release. |
| Explicit test image | [Test-image workflow](https://github.com/Project-Helianthus/helianthus-ha-addon/blob/main/.github/workflows/test-image.yml) is manually dispatched, selects the gateway input explicitly and currently overrides Explorer to `v0.6.1`. It publishes test images separately from catalog/version tags. | A test label identifies an experiment; neither the label nor a successful build makes it a coherent accepted 0.7 candidate. |
| Exact 0.7 candidate | Proposed: add-on, gateway and Explorer all declare the 0.7 cohort and their effective artifacts belong to one privately verified candidate association. | Matching major/minor labels are necessary but insufficient; acceptance requires exact input/output bindings and the owning gates. |

Under parent #246, Explorer 0.7 ships with add-on 0.7 and gateway 0.7; there is
no intermediate add-on release for Explorer alone. Never silently change
Explorer under the unchanged `0.6.58` catalog version. The current
[build workflow](https://github.com/Project-Helianthus/helianthus-ha-addon/blob/main/.github/workflows/build.yml)
republishes version and latest tags on main pushes; that mechanism is not an
immutability guarantee. [Test-image conventions](https://github.com/Project-Helianthus/helianthus-ha-addon/blob/main/CONVENTIONS.md)
describe the separate opt-in path, not candidate acceptance.

## Identity and evidence presented to the operator

Use the existing [candidate metadata contract](https://github.com/Project-Helianthus/helianthus-ha-addon/blob/main/docs/candidate-metadata-contract.md)
and [cohort guard contract](https://github.com/Project-Helianthus/helianthus-ha-addon/blob/main/RELEASE_COHORT.md).
This page defines decision requirements, not another BOM or metadata schema.
It does not introduce a receipt, identity ledger or recovery implementation.

| Decision information | Public presentation | Required private verification / limit |
| --- | --- | --- |
| Selected versus running cohort | Distinguish intended release labels from observed labels; state when the running artifact is Unknown. | Bind the actual installed output and architecture, including both bundled binaries, to the reviewed candidate. A requested tag or healthy process alone is insufficient. |
| Exact candidate association | Existing opaque bundle, association and artifact IDs; never encoded source coordinates or digests. | Verify complete source, dependency, base, toolchain and output inventory using the metadata owner's contract. Include every published architecture and separately distributed HA integration; the latter retains its own release series. |
| Acceptance | Report the existing metadata disposition and its verification limits. | A public status string or attestation token cannot establish private equality, required gates or independent review. Missing, stale or contradictory evidence prevents promotion. |
| Recovery target | Public label plus opaque reference to the retained prior artifact and its compatibility result. | Retain the exact previously installed image locally or by an immutable private artifact reference; do not reconstruct it from a mutable version/latest tag. Keep exact coordinates private. |

Observation presentation belongs to the published
[semantic snapshot read contract](https://github.com/Project-Helianthus/helianthus-docs-ebus/blob/main/api/semantic-snapshot-read.md)
and its referenced data owners. Consume that interface without defining age,
freshness, provenance, availability, evidence grade, admission or write authority
here. Any upgrade/restore behavior not covered by the owner's published contract
needs owner clarification before replacement; this packaging proposal supplies
no missing data semantics. Do not copy private records or capture times into
public examples or metadata.

The current [cohort checker](https://github.com/Project-Helianthus/helianthus-ha-addon/blob/main/scripts/check_release_cohort.py)
checks declared cohorts offline. Its exit zero can include `NOT_APPLICABLE`
outside 0.7 or `UNVERIFIED` gateway metadata. It does not establish exact binary
identity, persisted-state compatibility, startup success or release readiness.
Any changed input or output requires the new association and renewed bindings
and acceptance specified by the metadata contract, even if labels stay equal.

## Pre-replacement compatibility requirements

Before any replacement, the operator must have a compatibility result for the
exact source and target artifacts and the state they will read or write:

- Check existing add-on options, defaults, wrapper arguments and entry points
  against the target without rewriting settings to make the target start.
  Unsupported or ambiguous settings block the replacement pending an explicit
  owner migration contract; they must not be silently discarded or defaulted.
- Check persisted formats and migration behavior for both upgrade and downgrade,
  including whether a failed target start can already have changed persisted
  state. Check instance identity separately from Portal settings, snapshots and
  sessions. Preserving the data directory alone proves none of these formats
  are readable by the previous binary.
- Retain the prior exact image and a recoverable pre-replacement settings/data
  snapshot, with their association and compatibility evidence kept privately.
  Establish the owner's supported restore path before allowing a migration;
  this page prescribes no restore mechanism or automatic recovery controller.
- Require coherent gateway/Explorer outputs, architecture coverage and accepted
  candidate evidence for the same association. Preserve eBUS MCP envelopes and
  GraphQL parity under their existing owner contracts; no new API semantics or
  protocol facts are defined here.

Unknown compatibility means hold, not presumed compatibility. This is a
packaging/release compatibility decision, not a new authorization feature.

## Upgrade, failure and rollback decisions

These are proposed required outcomes, not claims of an available automatic
rollback facility. Every live install, configuration write, stop/start or restore
requires explicit operator confirmation at action time.

| Transition / observation | Required decision | Settings, state and evidence outcome |
| --- | --- | --- |
| Unchanged 0.6 to an explicit test image | Treat as an opt-in experiment with a separately verified target and recovery plan; never relabel it as catalog or candidate acceptance. | Keep catalog metadata unchanged; preserve original settings and record the actual artifact privately. |
| Existing installation to exact 0.7 candidate; all preflight evidence satisfied | Eligible for a separately approved replacement; candidate acceptance alone does not execute it. | Preserve settings and identity as their owner contracts require. Verify the running gateway and Explorer against the bound outputs before reporting cohort success. |
| Missing identity, compatibility, architecture coverage or acceptance before replacement | Hold replacement. | Keep the existing installation and last-known-good evidence; report the missing result as Unknown/unverified. |
| Target fails to start; prior image retained and current persisted state proven readable by it | Offer separately approved rollback to that exact image. | Do not rewrite settings to force startup. Retain failure evidence; returning to a prior binary still needs startup and identity verification. |
| Target fails to start or degrades; persisted-state downgrade compatibility Unknown or incompatible | Do not declare safe binary rollback, even with the prior image available. | Preserve settings, native evidence and retained data. Hold for the owner's supported recovery/restore decision; no automatic reset, deletion or speculative reverse migration. |
| Supported restoration of pre-replacement state is available | Treat restore plus prior binary as a separate recovery operation requiring action-time confirmation and owner acceptance. | Explicitly account for state lost since the snapshot. Keep failed-attempt evidence separately; validate restored data through its owning contract. |
| Target starts but gateway/Explorer identity is missing or mixed, or parity/acceptance fails | Do not report a successful coherent upgrade. Apply the same compatibility conditions before offering rollback. | Keep the failure visible and fail closed under existing admission rules; process health cannot promote evidence or trust. |
| Prior image restarted after rollback | Report rollback complete only after verifying actual prior artifacts, startup, preserved settings/identity and applicable interface checks. | Apply the owning data contract when checking restored output. Binary rollback does not undo external effects or establish hardware qualification. |

## Synthetic decision review and remaining acceptance

These invented examples illustrate requirements only; none was run against a
container, Supervisor, registry or device:

| Synthetic case | Independent expected decision and reason |
| --- | --- |
| All three labels say 0.7, but `association-synthetic-alpha` lacks Explorer output binding | Hold: matching labels cannot prove a coherent binary cohort. |
| A changed Explorer output keeps the same labels and old accepted association | Reject reuse of acceptance: create a new association and reverify under the metadata contract. |
| Target startup fails; prior image exists; downgrade readability is Unknown | Hold safe-rollback claim: image availability cannot prove persisted-state compatibility. |
| Prior binary is verified again, but owner-defined data recovery checks are missing | Hold the data recovery claim pending owner verification; binary identity alone does not complete recovery acceptance. |

The [gateway repository](https://github.com/Project-Helianthus/helianthus-ebusgateway)
owns gateway runtime and recovery implementation; the
[Explorer repository](https://github.com/Project-Helianthus/helianthus-vrc-explorer)
owns Explorer implementation. Add-on build and startup wiring remain with this
repository, under the linked cohort guard and candidate metadata contracts.
This page implements none of those mechanisms and does not require an unmerged
implementation before the requirements can be reviewed. Principal boundaries,
receipts, idempotency ledgers and recovery redesign remain outside this packaging
proposal; their runtime contracts belong to the gateway owner.
The [Portal / Ingress checklist](https://github.com/Project-Helianthus/helianthus-ha-addon/blob/main/docs/portal-ingress-offline-acceptance.md)
keeps runtime persistence and HA acceptance separate from offline documentation.
Full gates, exact-candidate review, wrapper regression, downgrade/failed-start
acceptance and any separately approved runtime smoke remain outstanding. This
partial contract closes neither [parent #246](https://github.com/Project-Helianthus/helianthus-ha-addon/issues/246)
nor release or hardware acceptance. The requirements slice is tracked in
[issue #256](https://github.com/Project-Helianthus/helianthus-ha-addon/issues/256);
the parent tracks the remaining cohort delivery work.
