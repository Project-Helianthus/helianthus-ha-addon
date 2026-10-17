# Bundled Explorer: process and artifact ownership

This is a proposed packaging contract for an explicitly invoked, optional
Explorer command. It advances [issue #259](https://github.com/Project-Helianthus/helianthus-ha-addon/issues/259)
and partially addresses [issue #246](https://github.com/Project-Helianthus/helianthus-ha-addon/issues/246).
It changes no executable behavior. Nothing described here becomes stable before
Helianthus 1.0; proposed guarantees require implementation and offline evidence.

## Sources and evidence boundary

The current-behavior statements below come from these public source locations:

- **S1 — [Explorer wrapper](https://github.com/Project-Helianthus/helianthus-ha-addon/blob/main/helianthus/rootfs/usr/bin/helianthus_vrc_explorer):**
  the `with-contenv bashio` interpreter, strict shell options, `PYTHONPATH`
  export and final `exec python3 -m helianthus_vrc_explorer "$@"`.
- **S2 — [Image build](https://github.com/Project-Helianthus/helianthus-ha-addon/blob/main/helianthus/Dockerfile):**
  the Explorer build stage installs the selected release into `/out/python`;
  the runtime image copies it to `/opt/helianthus-vrc-explorer`, installs
  Python and copies the filesystem overlay.
- **S3 — [Add-on documentation](https://github.com/Project-Helianthus/helianthus-ha-addon/blob/main/helianthus/README.md):**
  “Debugging tools” describes the bundled `/usr/bin/helianthus_vrc_explorer`
  command and its help invocation. “Configuration” describes the separate
  startup wrapper directly executing the packaged gateway.

These links track main and can change. Source inspection establishes packaging
structure, not the behavior of the installed Explorer module or a running image.
The module implementation, help output and runtime traces are not evidence for
this contract yet. No transport or device semantics are inferred from packaging.

## Current wrapper versus proposed guarantees

| Interface or transition | Current source-backed behavior | Proposed guarantee; future work unless already structural |
| --- | --- | --- |
| Invocation and arguments | S1 forwards `"$@"` to the Python module without adding CLI arguments. Zero arguments remain zero; spaces, empty arguments and argument order retain shell argument boundaries. | Preserve exact forwarding, with no shell re-evaluation, injected endpoint, default scan or invented output flag. Verify module handling offline before documenting supported CLI syntax. |
| Module environment | S1 prepends `/opt/helianthus-vrc-explorer` to any nonempty existing `PYTHONPATH`; S2 supplies that directory. | Retain bundled-module resolution and verify it in the built image. Source layout alone does not prove import success or dependency compatibility. |
| Zero arguments and help | S1 delegates both cases. S3 documents help, but supplies no observed status, output or no-I/O guarantee. | Zero arguments must terminate with usage without acquisition; help must terminate successfully without acquisition. Exact zero-argument status and help text remain to be specified by Explorer's CLI owner. |
| Invalid arguments | S1 delegates parsing; no packaging-side validation is present. | Reject invalid arguments with a nonzero status and useful diagnostics before acquisition or artifact creation. Exact parser status/text remain an upstream CLI contract gap. |
| Process and exit | On successful `exec`, S1 is replaced by Python in the same process; no wrapper child is left to reap, retry or translate status. Launch failure is subject to the shell/interpreter environment. | The caller waits for the invoked process and receives its termination result without conversion to success. Preserve a Python-selected exit code; do not normalize signal termination into a fabricated numeric code. Launch failures remain failures. |
| Signals and interruption | S1 installs no signal traps or forwarding supervisor. After `exec`, signals addressed to that process reach Python; handlers and descendant behavior are unknown. | The invoking caller owns cancellation and waiting. Interrupt/terminate must end owned work within a declared bound, reap descendants and leave no background Explorer. A future harness must specify process-group handling and escalation; the wrapper does not provide them today. |
| Standard streams | S1 adds no redirection, capture, merge or logging pipeline. The executed module inherits stdin, stdout and stderr. Module stream contents are unknown. | Preserve separate stdout/stderr and the termination result. The caller owns any synthetic transcript files and drains both streams without deadlock. Capturing output must not turn a failure into success. No automatic log ingestion or artifact parsing by gateway startup. |
| Bounded failure | S1 has no timeout, retry or child supervision. A hung module can remain running until externally stopped. | An offline caller/harness supplies a deadline, terminates and waits for all owned work on expiry, and reports timeout distinctly from a successful exit. Timeout status encoding and duration must be declared before acceptance. |
| Output selection | S1 adds no output option, directory creation, cleanup or collision policy. Module output defaults, writes and overwrite behavior are unknown. | No implicit persistent output. Persistence requires an explicitly selected destination using a verified Explorer interface or a separately owned caller interface. No new CLI flag is specified here. |
| Gateway independence | S1 invokes only Explorer. S3 describes gateway startup separately; these sources do not demonstrate a runtime failure-isolation test. | Explorer remains an optional command, never an always-running service, startup prerequisite or gateway health dependency. Its error, timeout or interruption must not stop, restart or change the gateway or its MCP/GraphQL lifecycle. |

The proposed zero-argument, cancellation, deadline and output rules are not
promises made by the current wrapper. They require coordination with the
Explorer CLI owner or a separately scoped invoking harness; this page does not
assign new runtime behavior to the gateway.

## Artifact ownership and publication proposal

All paths in this section are inert synthetic acceptance examples, not command
instructions. No device invocation is authorized or demonstrated here.

1. The future caller creates an exclusively owned temporary directory such as
   `synthetic-work/run-a/`. It records which files and child processes belong
   to that invocation. Neither the wrapper nor cleanup may sweep shared paths,
   gateway state, or another invocation's files. Current S1 performs none of
   this allocation or bookkeeping.
2. Temporary stdout/stderr transcripts and staged output remain separate.
   A partial artifact is explicitly incomplete, never a completed result or an
   admission input. Native evidence stays unmodified; packaging must not
   rewrite it into invented protocol meaning. Where diagnostics are retained,
   retention is an explicit caller choice in its owned directory.
3. Persistent publication is opt-in, for example a caller-selected
   `synthetic-results/run-a/result.json`. This illustrates a destination only;
   no supported Explorer output option or artifact schema is established by
   S1–S3. Successful process termination alone does not validate an artifact.
4. A future publisher stages complete output, validates the relevant published
   artifact contract, then publishes without replacing an existing destination.
   Collision checks must remain effective at publication time, including
   concurrent writers and symlinks; a preliminary existence check alone is
   insufficient. An existing file, directory or symlink causes a visible
   failure, never silent truncation or overwrite. This page adds no replace
   mode. Existing last-known-good artifacts remain byte-for-byte intact.
5. On parse error, child failure, interruption, deadline expiry, validation
   failure or an unwritable destination, publish no completed artifact.
   Retain already valid independent artifacts and existing partial
   last-known-good state. Report failure on stderr and through a non-success
   outcome; do not substitute stale output as a new success or admission.
6. Normal completion and handled failure clean up only invocation-owned
   temporary files after any explicitly selected diagnostic retention. The
   caller owns cleanup; S1 has no cleanup handler. An uncatchable kill or
   container loss cannot guarantee immediate cleanup. Future recovery must
   identify stale owned staging safely, never promote it automatically, and
   avoid deleting another live invocation's data.

These are artifact lifecycle requirements, not new credentials, principals,
authentication or authorization checks. They define no protocol profile,
qualification, discovery, public API, MCP method or GraphQL field. Existing MCP
compatibility and GraphQL parity must be preserved by later implementation.

## Future offline acceptance obligations

Use a synthetic module/process substitute and isolated synthetic filesystem;
never rely on a device, endpoint, installed deployment or a scan. The cases
below are obligations, not executed tests. Concrete CLI output syntax, module
fixtures and timeout values remain to be agreed before implementation.

| Case | Future synthetic stimulus and required observation | Source boundary / remaining gap |
| --- | --- | --- |
| Argument fidelity | Pass separated tokens including an empty token, whitespace and metacharacters to a recording substitute; observe identical ordered arguments and no evaluation. | S1 establishes quoting; executed argv evidence is missing. |
| Zero arguments / help | Run each case separately with I/O instrumentation; observe bounded usage termination for zero arguments and successful help, with no acquisition, persistent writes or children left behind. | S1 delegates; S3 documents help only. Actual CLI defaults and zero-argument status are unknown. |
| Invalid arguments | Supply an invalid option to a synthetic parser; observe nonzero termination, stderr diagnostics and no output publication or acquisition. | S1 adds no parser. The real parser's early-failure behavior still needs evidence. |
| User interruption | Interrupt a substitute that has staged a partial file and spawned a child; wait for bounded termination and reaping. Verify the partial is not published, existing output survives, and owned cleanup/retention follows the declared policy. | S1 uses exec without traps. Module handlers, child groups, escalation and recovery need separate evidence. |
| Bounded child failure | Substitute exits with a chosen nonzero status after writing to both streams; caller preserves status and stream separation. Separately substitute a hung child; deadline expiry is reported, descendants are reaped, and no complete artifact appears. | S1 has no bound or supervision. A caller deadline and its result representation are future work. |
| Unwritable output | Use a controlled filesystem failure for an explicitly selected synthetic destination; observe visible non-success, no completed artifact, owned staging cleanup and unchanged prior output. Do not depend on host privilege assumptions to manufacture the failure. | S1 has no output policy. Explorer output interface and publication owner are unresolved. |
| Existing output / collision | Prepopulate a synthetic destination; repeat with a symlink and competing publisher. Assert no replacement/truncation, visible failure and unchanged last-known-good contents. | No collision control exists in S1; atomic no-replace implementation is unproven. |
| Cleanup boundaries | Place another invocation's sentinel beside owned staging; exercise success, error and interruption. Verify only owned staging is removed. Simulate abandoned staging separately and forbid automatic promotion. | No staging or recovery implementation is supplied by S1–S3. |
| Gateway isolation | Use independent synthetic gateway and Explorer processes. Fail, interrupt and time out Explorer; the gateway remains running with unchanged invocation and state, and no new Explorer startup dependency. | S3 describes separate startup; built-image isolation and MCP/GraphQL parity evidence are still missing. |

## Evidence status and remaining parent acceptance

**Proven by source inspection:** the exec/argument/environment wiring in S1,
the packaging layout in S2, and the documented optional debugging entrypoint
and separate gateway startup description in S3. These are static observations.

**Hypothesis to verify:** inherited process/stream behavior works as expected
in the actual container/interpreter environment and optional command failure
leaves the running gateway unaffected.

**Unknown:** installed module parsing/defaults, signal handlers, descendants,
artifact format and output syntax, collision behavior, cleanup, actual exit
results, duration bounds and recovery behavior. Proposed requirements above do
not fill these gaps with evidence.

No runtime, transport, passive capture, hardware, qualification or profile
admission acceptance is claimed. Reading this document validates readability
only. Later artifact admission must remain fail-closed and preserve native
evidence and partial last-known-good state.

The parent remains open: candidate release selection, coordinated packaging
pins and BOM/changelog updates, and offline wrapper regression against the
selected Explorer release still require their own evidence. This page changes
no image pins, wrapper, cohort validator, upgrade/rollback policy or candidate
metadata, and does not close any of those acceptance items.
