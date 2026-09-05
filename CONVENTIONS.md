# Conventions

## Repository Layout

- Root contains add-on files: `config.json`, `Dockerfile`, `rootfs/`.
- Documentation files live at the repo root.

## Files

- `config.json`: Keep minimal; add settings only when required.
- `Dockerfile`: Use `BUILD_FROM` and keep build steps minimal.
- `rootfs/`: Add-on filesystem overlay. Add files only when a real service is introduced.

## Style

- Prefer short, declarative documentation.
- Avoid implementation details until functionality is added.

## Validation

Run `./scripts/ci_local.sh` for the repository's complete local CI and
`python3 -m pytest tests -q` for the default test suite. Resolver tests use
mocked HTTP responses, deny unmocked registry access, and skip the public GHCR
probe by default.

Run the public release metadata probe explicitly when outbound access to
`ghcr.io` is available:

```sh
HELIANTHUS_RUN_PUBLIC_GHCR_PROBE=1 python3 -m pytest tests/test_fronius_ha_rollout.py::test_public_release_manifest_probe_resolves_existing_tag -q
```

That command anonymously reads a pull token and the existing public `0.6.56`
OCI index for `linux/arm64`. It does not pull or execute an image, authenticate,
publish a manifest, or change a tag. Standard local and pull-request test runs
do not make this GHCR request.
