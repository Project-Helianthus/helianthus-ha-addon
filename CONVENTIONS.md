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

That command anonymously reads a pull token and the public `0.6.58`
OCI index for `linux/arm64` once that release is published. It does not pull or execute an image, authenticate,
publish a manifest, or change a tag. Standard local and pull-request test runs
do not make this GHCR request.

## Test images

The catalog version (`helianthus/config.json`) never carries a test build: the
Supervisor offers an update whenever the catalog version differs from the
installed one, and every push to `main` republishes the stable tags. A test
image is therefore built only by the manually dispatched `test-image` workflow
(`.github/workflows/test-image.yml`) with inputs `gateway_sha` (40-hex gateway
commit, required) and `test_label` (default `second-site`). It builds the
`amd64` and `aarch64` images at that commit (the Dockerfile verifies the exact
commit), records the commit in the `io.helianthus.gateway-commit` label and
index annotation, and publishes only
`ghcr.io/project-helianthus/helianthus-ha-addon:test-<label>-<first 8 of sha>`
(plus `-amd64` / `-aarch64`). It never publishes `latest` or a version tag and
never reads or changes `config.json`, the BOM or the stable gateway pin. The tag
logic lives in `scripts/test_image_plan.py` (tested by
`tests/test_test_image_plan.py`).

Install on an existing installation by retag (operator-run, after OK):

```sh
ha addons stop local_helianthus
ha addons info local_helianthus          # note the image and version the Supervisor uses
docker inspect <container or image>      # confirm the installed image reference
docker pull ghcr.io/project-helianthus/helianthus-ha-addon:test-<label>-<short>
docker tag ghcr.io/project-helianthus/helianthus-ha-addon:test-<label>-<short> <installed image>:<installed version>
ha addons start local_helianthus
```

Verify with `ha addons info local_helianthus` and the gateway's build/commit
field (the gateway `buildID` is the pinned commit). Roll back with
`docker pull <installed image>:<installed version>`, which restores the original
image under the same reference; then stop and start the add-on again.
