# Architecture

This repository is a minimal Home Assistant add-on skeleton for Helianthus. There is no functional integration yet; it only provides the basic add-on layout required by Home Assistant.

## Structure

- `config.json`: Add-on manifest and metadata.
- `Dockerfile`: Minimal container image build using `BUILD_FROM`.
- `rootfs/`: Add-on filesystem overlay (empty for now).
- `README.md`: Repository and add-on overview.

## Runtime

The container runs a placeholder command that logs a startup message and stays alive. No ports, services, or integrations are configured at this stage.

## Consumer Rollout Guardrails

Add-on consumer expansion is controlled by `helianthus/rollout_guardrails.json`.
Default stage is `pre_parity`, which blocks consumer expansion until parity completion gates are approved.
Post-parity enablement tasks are executed via `scripts/run_post_parity_enablement.py` and only run when guardrails are in `post_parity` stage with green parity artifact gates.
