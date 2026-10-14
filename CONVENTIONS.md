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

Run `./scripts/ci_local.sh` (it creates the gitignored `.venv-ci` from `requirements-ci.txt` on first use, so it needs network access once, and runs every stage with that environment first on `PATH`) for the repository's complete local CI and
`.venv-ci/bin/python3 -m pytest tests -q` for the default test suite. Resolver tests use
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
(assembled from run-specific `-amd64-r<run id>` / `-aarch64-r<run id>` images, so a manifest never combines images of different runs). It never publishes `latest` or a version tag and
never reads or changes `config.json`, the BOM or the stable gateway pin. The tag
logic lives in `scripts/test_image_plan.py` (tested by
`tests/test_test_image_plan.py`).

Install on an existing installation by retag (operator-run, after OK). Before
retagging, record the installed image digest and keep a local rollback tag, so
rollback never depends on a mutable version tag in the registry:

```sh
ha addons stop local_helianthus
ha addons info local_helianthus          # note the image and version the Supervisor uses
docker inspect <container or image>      # confirm the installed image reference
docker inspect --format '{{index .RepoDigests 0}}' <installed image>:<installed version>   # record this digest
docker tag <installed image>:<installed version> <installed image>:rollback-<date>
docker pull ghcr.io/project-helianthus/helianthus-ha-addon:test-<label>-<short>
docker tag ghcr.io/project-helianthus/helianthus-ha-addon:test-<label>-<short> <installed image>:<installed version>
ha addons start local_helianthus
```

Verify with `ha addons info local_helianthus` and the gateway's build/commit
field (the gateway `buildID` is the pinned commit). Roll back with the local tag
(`docker tag <installed image>:rollback-<date> <installed image>:<installed version>`)
or by digest (`docker pull <recorded digest>`, then tag it as
`<installed image>:<installed version>`), then stop and start the add-on again.
Do not roll back by re-pulling `<installed image>:<installed version>`: that tag
is mutable and may no longer match what was installed.

Test dependencies (pytest, PyYAML for the workflow test) are exact-pinned in
`requirements-ci.txt`, used by both `ci_local.sh` and `pr-ci.yml`.
