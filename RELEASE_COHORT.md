# Release cohort validation

The [PR workflow](https://github.com/Project-Helianthus/helianthus-ha-addon/blob/main/.github/workflows/pr-ci.yml)
and `./scripts/ci_local.sh` both run `scripts/check_release_cohort.py` and its
focused tests. For an add-on declaring the 0.7 cohort, a conflicting Explorer
release cohort fails validation automatically on pull requests.

The guard checks declared packaging metadata offline. An opaque gateway pin
leaves its release cohort Unknown unless release metadata is supplied; a passing
check does not establish artifact provenance, hardware qualification, or release
readiness. Add-ons outside the enforced cohort retain their existing behavior.
