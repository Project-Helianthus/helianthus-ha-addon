# AGENTS

## Scope

This repository owns the Helianthus Home Assistant add-on packaging only:

- add-on metadata and configuration;
- container image and filesystem overlay;
- startup, argument wiring, and safe runtime guards.

Do not add gateway semantics, protocol decoding, device discovery, public API
design, or Home Assistant integration entities here. Consume already-published
artifacts and stable interfaces without redefining their contracts.

## Workflow

1. Create one English GitHub issue for the change.
2. Create `issue/<number>-<short-slug>` from `origin/main`.
3. Make the smallest scoped change and add or update focused tests when behavior
   changes.
4. Run `./scripts/ci_local.sh`, commit, push, and open one PR that links the
   issue.
5. Resolve every valid P0-P2 finding and rerun validation after each fix.
6. Obtain a fresh exact-HEAD `NO_BLOCKING_FINDINGS` review with all required
   checks green.
7. Squash merge, verify remote `main`, and close the issue.

Use public GitHub URLs in tracked documentation. Instructions must remain
usable when this repository is checked out alone and must not depend on external
checkout or machine state.

## Validation and deployment

- Validate packaging, configuration, startup, and container behavior with local
  checks, fixtures, or mocks where practical.
- A local or real Home Assistant deployment is optional validation, not a
  prerequisite for ordinary changes.
- Never perform a live deployment, installation write, credential change, or
  live-system mutation without explicit operator confirmation at action time.
- Record the command and result for every validation run in the PR.
- Packaging, startup-contract, or operator-workflow changes require a companion
  public documentation update when they change externally visible behavior.

## Review hygiene

- Keep one active issue and PR for the same repository change.
- Reply to actionable review comments with the result and commit reference.
- Preserve backward-compatible add-on configuration unless an approved issue
  explicitly requires a migration.
