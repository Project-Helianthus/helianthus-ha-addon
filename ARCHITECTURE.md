# Architecture

This repository is a minimal Home Assistant add-on skeleton for Helianthus. There is no functional integration yet; it only provides the basic add-on layout required by Home Assistant.

## Structure

- `config.json`: Add-on manifest and metadata.
- `Dockerfile`: Minimal container image build using `BUILD_FROM`.
- `rootfs/`: Add-on filesystem overlay (empty for now).
- `README.md`: Repository and add-on overview.

## Runtime

The container runs a placeholder command that logs a startup message and stays alive. No ports, services, or integrations are configured at this stage.
