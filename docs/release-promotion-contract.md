# Offline promotion plan

`python3 scripts/release_promotion_plan.py RECORD.json` reads the local add-on
configuration and an evidence declaration. `--config` selects a local packaging
configuration. It emits a deterministic JSON plan or fails closed. It does not
execute the plan. The declaration must contain exactly these fields:

- `architectures`: all architectures declared by the add-on.
- `candidate`: one nonempty candidate identifier shared by all records.
- `cohort`: a release version in the packaging version's major/minor cohort.
- `target`: the declared image name followed by a release version tag in that cohort.
- `sources`: one record per architecture with `architecture`, `subject`,
  `candidate`, and `cohort`.
- `tests`: one record per architecture with the same fields and `verdict` set
  to `pass`. Each subject must exactly match its source.
- `aggregate`: `candidate`, `cohort`, `verdict` (`pass`), `subjects` (the
  complete list of source subjects), and `index_subject`.
- `index`: null when no index is proposed, otherwise one record containing
  `subject`, `candidate`, `cohort`, and `verdict` (`pass`). Its subject must
  exactly match the aggregate's `index_subject`; both are null without an index.

Subjects are digest-qualified references to the declared image. Architecture
subjects must be distinct. Duplicate keys, unexpected fields, unknown verdicts,
and incomplete or conflicting declarations are rejected. An index is never
computed or inferred. List order does not affect the output.

This validates declarations only. It cannot verify registry existence,
attestations, the truth of test results, or actual promotion, and cannot
authorize publishing. Workflow policy, stopping publication on main pushes,
and release promotion remain separate work.
