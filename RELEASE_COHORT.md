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
