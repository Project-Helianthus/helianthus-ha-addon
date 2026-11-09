# Offline artifact evidence comparisons

[The comparison tool](../scripts/compare_artifact_evidence.py) checks two explicitly
supplied release-input trees and actual controlled-build outputs. It never fetches,
builds, executes a supplied binary, promotes a candidate or deploys anything.

Run from a checkout with Python and cached Go tooling available:

```sh
python3 scripts/compare_artifact_evidence.py --before BEFORE --after AFTER
python3 scripts/compare_artifact_evidence.py --self-test
```

The first command emits sanitized JSON to stdout. Exit zero and
`COMPARISONS_VERIFIED` mean the supplied comparisons passed. Any missing evidence,
unsupported recipe, syntax error, missing inspection tool or timeout returns
`UNVERIFIED` and a nonzero exit. Neither result contains local paths or literal
fingerprints. `candidate_acceptance` remains `UNVERIFIED` even on success.
The self-test uses only synthetic fixtures and a fake build-inspection adapter;
it does not establish release candidate acceptance or reproduce a build.

## Preparing controlled evidence

The operator must supply two independently controlled release builds, their
actual outputs, complete release inputs and command records. Metadata assertions
alone do not establish that a build was reproduced. The tool can inspect build
metadata and compare bytes; it cannot independently authenticate the supplied
command history, source-to-output relationship, compiler environment or inventory
completeness relative to an external release. A copied binary with matching
assertions is therefore insufficient provenance for qualification.

Each tree contains `evidence.json`, `inputs/` and `shipped/`. Put all source,
embedded data, module and dependency metadata, build scripts, runtime scripts,
packaging and configuration used by the controlled build under `inputs/`.
Put the entire extracted shipped file set under `shipped/`, including Explorer,
integration and add-on Python, executable scripts, packaged data and every target's
actual gateway output. Do not limit inventories to source extensions. The operator
must reconcile this set and the target matrix against the release packaging and
[Dockerfile](../helianthus/Dockerfile); external dependencies must be supplied
explicitly. This checker does not infer files from another checkout or a tag.
Symlinks are rejected: supply a controlled extraction of their resolved content.

The JSON object has exactly these fields:

- `version`: integer `1`.
- `files`: object keyed by every relative file path except `evidence.json`. Each
  entry has exactly `kind` and `sha256`. Compute the latter locally using SHA-256
  over the file bytes; do not publish literal values. Kinds are `input` for
  `inputs/` files, and `python`, `data` or `gateway` for `shipped/` files.
- `builds`: object keyed by every `gateway` path, with the recipe described below.

No extra, omitted or deleted file is accepted. Every inventory fingerprint must
match its actual bytes. Both trees must have the same paths and kinds. All
shipped `.py` files and Python shebang scripts must use `python`. Their comparison
is exactly `ast.dump(ast.parse(content), include_attributes=False)` using the
running interpreter: comments and locations disappear, docstrings remain.
Unsupported syntax fails closed. Other packaged data is compared byte for byte.
Input bytes may differ, but the input set must be identical; those differences
are not themselves neutrality evidence. Actual gateway output equality is required.

## Recorded Go recipe

Each build record contains exactly `toolchain`, `settings`, `dependencies`,
`command`, `environment` and `inputs`. Records must be identical between trees.
`inputs` lists every `input` inventory path, once. The first three fields must
match the corresponding output of cached `go version -m BINARY` inspection:

- `toolchain` is the compiler version recorded in the binary.
- `settings` maps each build setting to its decoded string value.
- `dependencies` contains the ordered tab-separated fields of all `path`, `mod`,
  `dep` and replacement (`=>`) records, represented as arrays of strings.

The recognized recipe uses Linux, `amd64`, `arm64`, `arm` or `386`, compiler `gc`,
executable build mode, `CGO_ENABLED=0` and `-trimpath=true`. Target tuning settings
and `-tags` are supported when recorded. Unknown build settings fail closed.
Each output is additionally inspected with `go tool buildid`; the ID must be
empty. The binaries are then compared byte for byte, independent of any source
or AST comparison.

`command` is an argv array, never executed by the checker, exactly:

```text
go build -trimpath -buildvcs=false [-tags TAGS] -ldflags FLAGS -o gateway ./cmd/gateway
```

The brackets describe the optional two tag arguments. `FLAGS` is one string with
exactly `-buildid= -X main.buildVersion=VALUE -X main.buildID=VALUE`. Both stamps
must be nonempty and identical between controlled builds. The record uses the
controlled working directory's relative output name `gateway`; place the resulting
bytes at the corresponding shipped inventory path afterward.

`environment` must record `CGO_ENABLED=0`, `GOWORK=off`, `GOENV=off`,
`GOTOOLCHAIN=local`, `GOFLAGS=-mod=readonly`, `GOPROXY=off`, `GOSUMDB=off`, plus
every recorded Go target setting. Use the same cached toolchain, dependencies,
target and flags for both builds. The checker verifies these records against
binary inspection, but does not create module caches or prove their provenance.

The shipped Dockerfile uses VCS stamping and per-release stamps. Controlled proof
builds instead use `-buildvcs=false`, an empty build ID and identical normalized
stamp values. This tool leaves the shipped build configuration unchanged. Recipe
extensions require explicit checker support; unfamiliar flags are not neutral.

## Evidence and shipping

Record the comparison outcome with the independently reviewed controlled-build
provenance and complete release target inventory. A post-convergence change needs
this evidence linked in its review; synthetic tests do not renew hardware,
transport or candidate evidence. Full repository CI, independent review,
applicable transport/conformance gates and any artifact evidence renewal remain
shipping obligations. CI here only runs synthetic unit tests and the self-test.

The guard itself is non-shipped. Its neutrality requires a before/after manifest
showing every runtime and build input unchanged and classifying the authorized
guard, documentation and test changes. Do not substitute source equality for Go
binary equality, or silently treat missing proof as neutral.
