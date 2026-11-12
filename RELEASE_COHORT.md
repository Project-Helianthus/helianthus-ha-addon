# Release cohort validation

The [PR workflow](https://github.com/Project-Helianthus/helianthus-ha-addon/blob/main/.github/workflows/pr-ci.yml)
and `./scripts/ci_local.sh` both run `scripts/check_release_cohort.py` and its
focused tests. For an add-on declaring the 0.7 cohort, a conflicting Explorer
release cohort fails validation automatically on pull requests.
This includes the Dockerfile default and every Explorer build-argument override
in the [test-image workflow](https://github.com/Project-Helianthus/helianthus-ha-addon/blob/main/.github/workflows/test-image.yml).
An omitted override uses the checked Dockerfile default; an invalid or conflicting
override fails the guard. Use `--test-image-workflow path/test-image.yml` to check
an alternate workflow alongside `--addon-config` and `--dockerfile`.
Build-argument entries use quote-aware CSV parsing: quoted entries are unquoted,
quoted multiline values stay in one entry, and commas remain within each
argument, matching the action's `ignoreComma` list handling. Malformed CSV fails
validation.

The guard checks declared packaging metadata offline. An opaque gateway pin
leaves its release cohort Unknown unless release metadata is supplied; a passing
check does not establish artifact provenance, hardware qualification, or release
readiness. Add-ons outside the enforced cohort retain their existing behavior.

## Candidate publication and release promotion

The [image workflow](https://github.com/Project-Helianthus/helianthus-ha-addon/blob/main/.github/workflows/build.yml)
builds pull requests without publishing. Main runs publish only
`candidate-<run_id>-<run_attempt>-<architecture>` and the corresponding
multi-architecture candidate index. Main never publishes version or `latest`
tags. Each successful run retains its index digest as a workflow artifact.

For a failed main candidate run, select **Re-run all jobs**. **Re-run failed
jobs** is unsupported: successful architecture jobs retain the previous attempt's
tags, while the index requires every architecture from the current attempt.
The index preflight aborts on a missing current-attempt image and reports this
recovery instruction before creating an index. Rerun all jobs even when only
the manifest job failed.

Push a `v<version>` release tag at the same commit as a successful main push
run. The release job selects that run's candidate artifact, checks its version,
repository and run identity against the release, and promotes its immutable
index digest without rebuilding. Missing or expired artifacts require a new
successful main candidate run before release. Manual main runs build candidates;
release selection uses successful main push runs only.

Publication is serialized within this workflow. An existing version tag aborts
publication; registry errors other than explicit manifest absence also abort.
The version and `latest` tags must resolve to the candidate digest, which is
recorded in the run summary. Registry administrators must restrict other writers:
the registry tag API does not provide an atomic create-if-absent operation.
A failure after writing the version can leave `latest` unchanged; investigate
that state rather than overwriting or deleting the version to retry.

A successful candidate build establishes build evidence only. Hosted test-run
proof that main leaves release tags untouched and release preserves the digest
is required before release acceptance. Security, transport, smoke and hardware
qualification remain separate release gates; this workflow grants none of them.
