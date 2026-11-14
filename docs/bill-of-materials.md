# Bill of materials

`helianthus/bom.json` (format `helianthus-addon-bom/1`) records the exact inputs
of one add-on image build. `scripts/bom_manifest.py` checks it offline against
the files that drive the build and regenerates it online from the pins those
files name.

## Sections

| Section | Content |
| --- | --- |
| `format` | `helianthus-addon-bom/1`. |
| `addon` | Slug, version and Supervisor architectures, equal to `helianthus/config.json`. |
| `gateway` | Gateway repository, the 40-hex commit the Dockerfile builds and its tree. |
| `vrc_explorer` | Explorer repository and pin: a version tag (`vX.Y.Z`) with the commit it resolves to, or a commit alone with `tag` set to `null`. |
| `go_modules` | Go module pins of the gateway build at the pinned commit (`go.mod` requirements and replacements, SHA-256 of `go.mod` and `go.sum`). |
| `semantic_contract` | The semantic registry the gateway build pins and the element catalog that registry implements (below). |
| `images` | Builder and per-architecture base images: the tag reference, the digest observed at generation time and, once frozen, the `pinned_digest` the build references. |
| `gateway_cli_flags` | The gateway flag set of the add-on profile build (`-tags nomatter`) at the pinned commit. |
| `freeze` | Release freeze record: `owner`, `status` (`unfrozen` or `frozen`) and a note. |

### `semantic_contract`

| Member | Content |
| --- | --- |
| `registry_module` | `github.com/Project-Helianthus/helianthus-semreg`. |
| `registry_version` | The version of that module in `go_modules`; the check requires the two to be equal. |
| `element_catalog` | `null` when the pinned registry carries no element catalog copy, otherwise an object with `path` (the copy inside the registry), `sha256` (64 lowercase hexadecimal characters, the SHA-256 of the copy's bytes) and, when the registry declares where its copy comes from, `source` (`repository` URL and `path`). |

The registry declares the digest of its copy in its graph package
(`PinnedDigest` in `semreg/v1/graph/catalog.go`, whose comment names the copied
file) and accepts no other bytes. The BOM records the digest of the bytes the
registry carries at the pinned version, which `generate` refuses to record
unless it equals that declared digest. A registry version that predates the
copy is recorded with `element_catalog` set to `null`.

## `check`

`python3 scripts/bom_manifest.py check [--bom PATH]` reads only local files and
never opens a network connection. It fails when the BOM disagrees with
`helianthus/Dockerfile`, `.github/workflows/build.yml`,
`helianthus/config.json` or the flags the wrapper passes to the gateway, when
`semantic_contract` is missing, has unknown or missing members, names another
module or a version other than the `go_modules` entry, or carries a malformed
element catalog entry, and when a build file references an image at a digest
other than the BOM's `pinned_digest`. A BOM whose `freeze.status` is `frozen`
is always held to the `check --frozen` rules, so an incomplete freeze cannot
pass plain `check`. Local CI runs it on every change.

## `check --frozen`

`python3 scripts/bom_manifest.py check --frozen` applies every `check` rule and
adds the release freeze rules:

- `freeze.status` is `frozen`;
- every builder and base image the BOM lists has a `pinned_digest`, and the
  Dockerfile (builder images) or the build workflow matrix (base images)
  references it as `<ref>@sha256:<digest>` with exactly that digest;
- `semantic_contract.element_catalog` is present;
- the Dockerfile pins the gateway and the Explorer by commit, not by tag.

It prints every failed rule and exits 1. On an unfrozen BOM it is expected to
fail; the printed reasons are the remaining freeze steps.

## `generate`

`python3 scripts/bom_manifest.py generate --gateway-help HELP.txt [--out PATH]`
is the only mode that uses the network. It reads the pins from the Dockerfile,
resolves the gateway tree, the Explorer commit, the gateway's `go.mod` and
`go.sum`, and observes the image digests. For `semantic_contract` it resolves
the registry version from `go_modules` to its commit, reads the registry's
declared catalog digest and the copied file at that commit, computes the
SHA-256 of the fetched bytes and records it. It stops without writing when the
computed digest differs from the declared one or when the declared file is
missing. It records the digest a build file already references as
`pinned_digest`. `--gateway-help` is a capture of `gateway --help` from the
add-on profile build of the pinned commit. `generate` always writes
`freeze.status` as `unfrozen`.

## The freeze

Freezing is one reviewed commit that moves every build input to an exact pin:
the gateway and the Explorer by commit, every builder and base image by digest
in the Dockerfile and the build workflow with the same digests recorded as
`pinned_digest`, the element catalog of the pinned registry recorded, and
`freeze.status` set to `frozen`. `check --frozen` passes on that commit. The
release publishes the images built and tested from that commit; it does not
rebuild them. Any later pin change requires a new generation and a new freeze.
