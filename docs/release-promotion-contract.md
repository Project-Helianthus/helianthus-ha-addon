# Offline promotion plan

`python3 scripts/release_promotion_plan.py RECORD.json` reads the local add-on
configuration and an evidence declaration. Python dependencies are listed in
`requirements-ci.txt`. `--config` selects a local packaging
configuration; the required architecture set always comes from the local
`.github/workflows/build.yml` build matrix, including architectures absent from
the Supervisor configuration. It emits a deterministic JSON plan or fails closed.
It does not execute the plan. The configured `image` must be an unqualified
repository name, without a tag, digest, or URL scheme. A numeric registry port
before the repository path is allowed. Repository path components use lowercase
letters and digits, with periods, underscores or hyphens as separators.
The declaration must contain exactly these fields:

- `architectures`: all architectures published by the build workflow.
- `candidate`: one nonempty candidate identifier shared by all records.
- `cohort`: the exact packaging version (the field name is retained).
  Release versions allow an optional `v` prefix and dot-separated prerelease
  and build identifiers containing ASCII letters, digits or hyphens. Identifiers
  must be nonempty; numeric prerelease identifiers cannot have leading zeros.
- `target`: the declared image name followed by the exact packaging version as its tag.
  The tag must also satisfy container tag syntax: 1–128 ASCII letters, digits,
  underscores, periods or hyphens, starting with a letter, digit or underscore.
  Release build metadata containing `+` is rejected.
- `sources`: one record per architecture with `architecture`, `subject`,
  `candidate`, and `cohort`.
- `tests`: one record per architecture with the same fields and `verdict` set
  to `pass`. Each subject must exactly match its source.
- `aggregate`: `candidate`, `cohort`, `verdict` (`pass`), `subjects` (the
  complete list of source subjects), and `index_subject`.
- `index`: null when no index is proposed, otherwise one record containing
  `subject`, `candidate`, `cohort`, and `verdict` (`pass`). Its subject must
  exactly match the aggregate's `index_subject`; both are null without an index.

Subjects use the exact declared image prefix followed by `@sha256:` and 64
lowercase hexadecimal characters. Configured registry ports are supported.
Architecture subjects must be distinct. Duplicate keys, unexpected fields, unknown verdicts,
and incomplete or conflicting declarations are rejected. An index is never
computed or inferred. List order does not affect the output.

This validates declarations only. It cannot verify registry existence,
attestations, the truth of test results, or actual promotion, and cannot
authorize publishing. Workflow policy, stopping publication on main pushes,
and release promotion remain separate work.
