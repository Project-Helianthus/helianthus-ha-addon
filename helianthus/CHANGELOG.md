# Changelog

## 0.6.9 (2026-05-12)

### F-19: passive reconstructor early-abandon + arbitration fragment classification

**Companion to 0.6.8.** v0.6.8 (F-18) verified working: ebusd actively
scans the bus and identifies all 6 slaves including stealth SOL00@0xEC.
But batch-14 live measurement surfaced F-19: passive reconstructor
abandons 146 src=0x10 + 115 src=0xF1 frames per 30k log lines as
`corrupted_request phase=1`.

### Root cause (decomposed into F-19a + F-19b)

Operator hypothesis: "interleaved-initiator frame extraction in the
passive reconstructor's state machine. Two SYN terminators (AA AA)
caught inside what was treated as one frame." 2-agent convergence
(Explore code-walk + angry-tester adversarial attack) confirmed the
hypothesis is correct for src=0x10 **and** decomposed F-19 into TWO
distinct sub-mechanisms that both produce the same
`corrupted_request phase=1` string, masking them as one bug.

**F-19a — LEN-completion CRC fail (src=0x10, ~146/30k)**

`req_raw=10 26 B5 23 01 AA AA resp_raw=<empty>`. The eBUS CRC8(0x9B)
of `10 26 B5 23 01 AA` is 0x7C, not 0xAA. The
`isMidRequestFrame()` predicate routes both 0xAA bytes into the
buffer as data+CRC (correct P7.1 behavior for escape-decoded 0xAA).
At `len=6+LEN`, parseFrame fails. **Pre-F-19a: the parser kept
accumulating**, consuming bytes from the NEXT frame into a buffer
that would never validate — cascading the corruption.

Fix: abandon early at LEN-completion when parseFrame fails, re-parsing
to disambiguate Broadcast-defer (preserves pre-F-19a behavior) from
true parseFrame failure (F-19a abandon path). Replicate the same
classification helpers (`self_echo` / `scan_collision` /
`corrupted_request`) the SYN-triggered path uses. Layer-1 invariant:
plain `resetStateLocked` (NOT `AfterSyn`) — the tap does not carry a
`WasEscaped` flag, so a logical 0xAA cannot be reliably distinguished
from an escape-decoded data byte; the next wire SYN re-engages the
gate.

**F-19b — 4-byte truncated arbitration fragment (src=0xF1, ~115/30k)**

`req_raw=F1 15 B5 24 resp_raw=<empty>`. A 4-byte buffer reaches SB
but never observes LEN — structurally a truncated arbitration attempt
(lost to a higher-priority initiator, or wire byte loss), not a
corrupted frame. **Pre-F-19b: the `<= 3` threshold for
`arbitration_fragment` mis-classified these as `corrupted_request`**,
inflating the F-19 metric.

Fix: widen `arbitration_fragment` threshold from `<= 3` to `< 5`.
Pure metric-attribution change; abandon still fires.

### Adversarial review trail

- 2-agent convergence pre-PR: Explore code-walk + angry-tester
  adversarial attack converged on the diagnosis. Angry-tester
  decomposed F-19 into F-19a + F-19b and surfaced Finding C
  (classification replication mandatory).
- Codex CLI review on diff: **VERDICT: SHIP**, no real defects.
- Codex bot review round 1 (P2): caught a subtle Layer-1 invariant
  bug in my P2 fix. Addressed in commit.
- Codex bot review round 2 (P2): caught that my round-1 fix was
  ALSO wrong (escape-decoded 0xAA isn't a real wire SYN; without
  WasEscaped plumbing, the safe-fail choice is always plain
  `resetStateLocked`). Addressed in commit.

### Predicted pass criteria (batch-15)

| Metric | v0.6.8 | v0.6.9 target |
|---|---|---|
| `passive_reconstructor abandon ... reason=corrupted_request phase=1 src=0x10` per 30k | ~146 | < 20 |
| `passive_reconstructor abandon ... reason=corrupted_request phase=1 src=0xF1` per 30k | ~115 | ≈ 0 |
| `passive_reconstructor abandon ... reason=arbitration_fragment` per 30k | small | ≈ 115 + epsilon |
| Other F-18 metrics (SEND-byte multiplicity, ebusctl `messages`, `signal: acquired`) | green | unchanged |

### Tests added

8 new tests in `passive_reconstructor_f19_test.go` (operator's exact
wire example, classification replication for self_echo and
scan_collision, F-19b reclassification, P7.1 regression guards, Layer-1
gate behavior for both escape-decoded and non-SYN trigger cases). Plus
1 updated test in `passive_reconstructor_p71_escape_test.go` to assert
the new F-19b semantic.

### Out of scope

- **F-19c** (forensic instrumentation: per-byte timestamps,
  abandon-trigger-site logging) — deferred
- **F-20** (`phase=4 unexpected_symbol` abandons — response-side,
  different fault class)

### Gateway

- Bump pin to `cb2d641`.

---

## 0.6.8 (2026-05-12)

### F-18: external ENH sessions must receive own echoes

**Companion to 0.6.7.** v0.6.7 fixed the F-17 retry-feedback-loop and
cancelled-flag contract; ebusd's `0x31` now wins arbitration through
the proxy. But live capture after 0.6.7 deploy showed ebusd issued
`ENHReqSend(0xFE)` once per scan attempt, then **never** issued
`ENHReqSend(0x07)` (length byte) or anything after. 237
`passive_reconstructor abandon reason=corrupted_request phase=1
src=0x31` events per 30k log lines.

### Root cause

The embedded mux suppressed every byte the adapter echoed back to the
owning external ENH session. Per john30/ebusd's
[`enhanced_proto.md`](https://github.com/john30/ebusd/blob/main/docs/enhanced_proto.md):

> "Note that this message [ENH_RES_RECEIVED] shall not be sent when
>  the byte received was part of an arbitration request initiated
>  by ebusd."

So the protocol forbids echo for the **arbitration byte** (handled
correctly by `deliverWinnerByteToOtherSessions` which skips the
winner), but **requires echo for every subsequent SEND byte**.
john30/ebusd's [`DirectProtocolHandler` at
`protocol_direct.cpp:412-414`](https://github.com/john30/ebusd/blob/main/src/lib/ebus/protocol_direct.cpp)
compares `recvSymbol != sentSymbol` after each send and collapses to
`bs_skip` on mismatch or `SEND_TIMEOUT` (~10 ms). Without the echo,
ebusd cannot advance past byte 1 — the entire post-arbitration phase
abandons silently, and the next retry cycle repeats the failure.

The standalone `helianthus-ebus-adapter-proxy` at `server.go:126`
uses a single shared `ownerObserverSeen []byte` and works correctly
for ENH external clients. The bug was introduced when the embedded
mux generalized `echoTracker` per-session and applied it to ENH
externals that should have been pass-through.

### Code changes

1. `mux.go` `deliverToSessions`: deleted the per-session `matchEcho`
   block. Every session now receives every byte. The latent
   `echoMatchFlushed` reorder hazard (Codex bonus finding) is
   eliminated by the same deletion.
2. `mux.go` `doSend`: deleted the external-session `recordSent` +
   `rollbackSent` blocks (would have grown the `expectedEchoes` queue
   to its 256-byte cap and triggered spurious `totalOverflowResets`
   alarms every 256 external SENDs).
3. `session.go`: removed per-session `echoTracker` field +
   initializer. Cleaned up 5 helper-call sites and 2 helper
   functions (`flushSessionEchoTrackers`, `resetAllSessionEchoes`).
4. Retargeted `echo_tracker_test.go` → `echo_tracker_gateway_test.go`:
   the 8 unit tests continue to validate `m.gatewayEcho` (gateway
   path is unchanged and still uses the `echoTracker` struct).
5. New `echo_passthrough_test.go`: 10 hermetic tests covering F-18
   contract + adversarial-review risk mitigations + Codex round-1
   integration test (`onReceived` → `phase.advance` →
   `wirePhaseEventTransactionDone` → `releaseOwnership` →
   `tryGrantAndStart` pipeline).

### Documentation

`helianthus-docs-ebus#307` documents the converse of the existing
arbitration-byte non-echo rule in `protocols/enh.md`:
post-arbitration bytes MUST be echoed via `ENH_RES_RECEIVED`. Merged
alongside this gateway PR per the `AGENTS.md` doc-gate (Codex P1
review finding on the gateway PR).

### Expected verification post-deploy (batch-13 pass criteria)

| Metric | 0.6.7 | After 0.6.8 |
|---|---|---|
| Distinct `SEND 0xXX forwarded` byte values | 1 (0xFE only) | ≥ 5 (full broadcast scan) |
| `corrupted_request reason=phase=1 src=0x31` per 30k lines | ~237 | < 10 |
| ebusctl `messages` after 5 min uptime | 17 | > 100 |
| `grab result all` frames with src=0x31 | 0 | > 0 |
| `totalOverflowResets` increments | 0 | 0 |
| `ebusctl scan 08` returns real BAI00 identity | from passive cache | from real ebusd-initiated scan |

### Adversarial-review trail

- Four independent agents (Explore code-walk, angry-tester
  adversarial attack, consultant with direct john30/ebusd source
  citations, and Codex CLI) converged on F-18 with no surviving
  alternative hypothesis. Full agent reports in
  `_work_adaptermux_audit/EBUSD-VERIFICATION-2026-05-12-batch13.md`.
- Codex round-1 review on the gateway PR surfaced one LOW finding
  (the phase-tracker unit test wasn't covering the full integration
  path) and one P1 doc-gate finding. Both addressed in-PR /
  companion docs-ebus#307.

### Gateway

- Bump pin to `7aa1d8b`.

---

## 0.6.7 (2026-05-12)

### F-17: close the ebusd retry-feedback-loop (pcap-confirmed root cause)

**Headline.** Microsecond-resolution TCP capture (operator's batch-9
audit, `EBUSD-VERIFICATION-2026-05-11-batch9.md`) showed every
`ReqStart(0x31)` from ebusd received `ENHResFailed(0x31)` within
~0.3 ms — far faster than the bus can physically arbitrate (eBUS
bit-time ~4 ms). The proxy was synthesizing these failures locally
with `data = 0x31` (ebusd's own initiator byte), telling ebusd "you
lost to yourself."

`startRequest` carries a struct-field `cancelled atomic.Bool` for
in-flight-at-adapter suppression. `startResult` carries a value-field
`cancelled bool` for the channel handshake. Both must be set on
cancellation: the struct flag lets `handleArbitrationResponse`
suppress late STARTED/FAILED; the value flag lets
`session.handleStart` silent-return instead of falling through to
`deliverFailed(initiator)` and emitting `ENHResFailed` on the wire.

`arbitration.requestStart`'s same-session-replace paths set the
struct flag but NOT the value flag. Result: every same-session
replace produced `ENHResFailed(0x31)` on the wire in ~0.3 ms. ebusd
read it as arbitration-lost-to-self, retried within ~50 ms, cancelled
the just-queued entry, produced another spurious FAILED —
positive-feedback loop. **No bid ever physically arbitrated on the
bus.** This is the root cause of "ebusd never lands a frame through
the proxy" that survived through 0.6.4 / 0.6.5 / 0.6.6.

### F-15: gate AM8 deadline reconnect on transport type

The AM8 deadline callback previously used `needReconnect := true`
unconditionally. Every deadline expiry forced an upstream conn.Close
— including on the non-blocking ENH RequestStart path where the
adapter is merely slow, not hung. Under F-17's retry storm this
asymmetry amplified into a feedback loop: adapter backlog → slow
STARTED → AM8 trips → forced reconnect → next ReqStart dropped →
another retry.

Fix: mirror `cancelPendingStart`'s `wasBlocking := pending.blockingArb`
pattern. Blocking transport keeps its reconnect (goroutine may still
be hung in the transport call). Non-blocking transport relies on the
absorb safety-net inside `armPendingStartAbsorbLocked` for the rare
truly-hung case (its own StartDeadline-bounded reconnect timer).

### Cancelled-flag contract surface (10 paths now consistent)

PR #626 swept every code path that resolves a cancelled
`startRequest`. The contract: any path that resolves via the
**normal (non-boundary) resolution path** MUST set `cancelled: true`
on the `startResult`. Paths that resolve via a
**transport-level boundary error** (`failAllPending`, `reconnect`,
`handleReset`, `Close`) MUST NOT set `cancelled: true` —
`session.handleStart`'s branch order
(`granted → cancelled → err(reset) → deliverFailed`) requires
err-routing to drive `deliverReset(...)` on RESETTED/disconnect.

Paths now honoring the contract:

| Path | Branch |
| --- | --- |
| `arb.requestStart` | gateway-replace + external-replace |
| `arb.cancelStart` | gateway + external |
| `handleArbitrationResponse` | matched STARTED + cancelled in flight |
| `handleArbitrationResponse` | AM56 STARTED-mismatch + cancelled in flight |
| `handleArbitrationResponse` | FAILED + cancelled in flight |
| AM8 deadline callback | deadline expired + cancelled in flight |
| `RequestStart` err callback | transport err + cancelled in flight (gated on `!isResetOrDisconnectError`) |
| `StartArbitration` err callback | transport err + cancelled in flight (gated on `!isResetOrDisconnectError`) |

### Codex bot findings (P1 + P2, both addressed in-PR)

- **P1**: F-15's fix only prevented the IMMEDIATE AM8 deadline
  reconnect on the non-blocking path. `handleArbitrationResponse`'s
  absorb-consume branch still had `needReconnect := started`, so a
  LATE STARTED arriving after the deadline armed `pendingStartAbsorb`
  would still tear down TCP via the absorb path — preserving the
  retry-feedback-loop on a delayed path. Fixed: mirror F-15's
  transport-type gate in the absorb branch by determining
  `isBlockingPath` from the upstream transport's interface satisfaction.
- **P2**: The M2 transport-err fix violated the contract documented
  in `arbitration.failAllPending` by setting `cancelled: true` even
  when the err matched `isResetOrDisconnectError`. session.go's
  branch order would silent-return and the client would miss
  RESETTED. Fixed: gate `deliverAsCancelled` on
  `cancelledInFlight && !isResetOrDisconnectError(err)`.

### New diagnostic log markers

For operator log-grep during verification:

    "absorbed (C4/R4)"              — matched STARTED for cancelled bid (existing in 0.6.6)
    "absorbed (C4/R4 AM56-half)"    — STARTED-mismatch for cancelled bid (new)
    "absorbed (C4/R4 FAILED-half)"  — FAILED for cancelled bid (new)
    "wasBlocking=false"             — AM8 deadline on non-blocking path (no reconnect)
    "cancelledInFlight=true"        — AM8 deadline on cancelled bid (suppressed)
    "isBlockingPath=false"          — absorb-consume on non-blocking (no reconnect)

### Predicted post-deploy outcome (batch-9 table)

| Metric | 0.6.6 | After 0.6.7 |
| --- | --- | --- |
| `FAILED(0x31)` response within <1 ms of ReqStart | 100 % | < 5 % |
| `grab result all` frames with src=0x31 | 0 | > 0 within 60 s |
| ebusd `messages` counter (15 min uptime) | 17 plateau | > 50 |
| ebusd "won in invalid state" rate | many/scan | < 1/5 min |

### Gateway

- Bump pin to `61fc36c`.

### Review process

PR #626 went through four rounds of adversarial review
(angry-tester subagent), addressing 7 cycles of findings (F-1, F-2,
F-3, F-4, F-5, F-NEW-1, F-NEW-2, F-NEW-4, F-NEW-5, F-NEW-6, M1, M2,
L2, L3) plus two Codex bot findings (P1, P2). All findings closed
in-PR with regression tests. 16 new tests across 5 files. Full
adaptermux suite + `-race` green throughout the iteration.

---

## 0.6.6 (2026-05-11)

### Revert C4/R4 upstream-reconnect on cancelled STARTED (v0.6.5 regression)

**Urgent revert.** The C4/R4 path in `handleArbitrationResponse`
shipped in 0.6.4 (and unchanged in 0.6.5) closed the upstream TCP to
the adapter every time an external session re-submitted a START
while a previous request was still in flight at the adapter. Live
capture on 0.6.5 showed this produces a continuous ~5-second cycle:

    device invalid → signal lost → signal acquired (5.013 s later)
    → device invalid → ...

with the addon functionally worse than 0.6.3 in this regime. Symptom
recurred every time any external session re-submitted a START.

The "force reconnect for adapter resync" theory that prompted the
close-call was wrong on the live bus: eBUS arbitration is per-SYN
stateless from the adapter's perspective, so the next SYN boundary
resets adapter arbitration state naturally. No TCP rebuild is
required when a cancelled-bid STARTED arrives.

Restore the original C4 spec — absorb the STARTED, deliver
`granted=false` on the abandoned notify, advance the queue, **don't
touch the transport.**

Log line:

    - 0.6.4-0.6.5: "suppressing STARTED for session N — request was
                   replaced; forcing reconnect for adapter resync (C4/R4)"
    + 0.6.6:       "suppressing STARTED for session N — request was
                   cancelled/replaced; absorbed (C4/R4)"

The `"cancelled-STARTED triggered transport reconnect"` companion
line is gone with the close call.

### Regression guards

Two new tests pin the revert so it can't reappear silently:

- `TestHandleArbitrationResponse_CancelledStartedAbsorbsWithoutReconnect`
  — asserts `pendingStartAbsorb == 0` AND that `conn.Close` was NOT
  called on an upstream mock when a cancelled-bid STARTED arrives.
- `TestCancelledStartedLog_DoesNotMentionReconnect` — string-level
  guard. Banned substrings: `"forcing reconnect for adapter resync"`,
  `"cancelled-STARTED triggered transport reconnect"`, `"cancelled-
  STARTED reconnect close"`. Required substring: `"absorbed (C4/R4)"`.

### Other 0.6.4/0.6.5 fixes are retained

C1 (bus-idle fast path), C3 (PendingStartTTL drain), C5 (phantom-
byte filter), `IsKnownInitiatorByte` callback, `requestStartForSession`
wrapper with in-flight cancel + idle-kick, passive wire-activity
tracking, and the round-6 `lastWireActivity` bumps on consumed
arbitration bytes all stay in place. Only the upstream-reconnect on
cancelled STARTED is reverted.

### Expected verification post-deploy

    # Continuous ebusctl loop should show "ERR: arbitration lost"
    # (bus contention) but NOT "ERR: no signal", "device invalid",
    # or "signal lost". TCP to .2:9999 stays up indefinitely.
    while true; do docker exec addon_2ad9b828_ebusd ebusctl scan ec; done

    # Pre-revert: ~6 reconnects/min. Post-revert: 0.
    ha apps logs local_helianthus --lines 1000 \
      | grep -cE 'triggered transport reconnect|old conn close'

### Gateway

- Bump pin to `63a9b15`.

### Process note

This regression originated from following Codex review round 3 on PR
#623, which asked for an adapter resync after cancelled STARTED. The
review reasoning was internally consistent ("adapter is one
arbitration ahead") but turned out to be wrong on the live bus. The
two-test regression guard added here prevents the same conclusion
from being reintroduced via a different code path.

---

## 0.6.5 (2026-05-11)

### Round-6 follow-ups on the proxy-bug stack

Two post-merge Codex P2 findings on the 0.6.4 release, addressed
inline:

- **Wire activity tracked on consumed arbitration bytes.** When the
  adapter reports `StreamEventFailed` (or the mismatched-STARTED
  branch inside `handleArbitrationResponse`), the winning initiator
  byte has been consumed from the wire — but only later
  `StreamEventByte`s used to bump `lastWireActivity`. A new external
  START enqueued in that gap could see a stale timestamp and take
  the C1 idle-kick path mid-third-party-transaction. `lastWireActivity =
  time.Now()` now fires at every arbitration-byte consumption site
  (STARTED + FAILED in `readLoop`, AM56 mismatched-STARTED in
  `handleArbitrationResponse`).

- **FAILED bookkeeping fused into one `stateMu` critical section.**
  The first fix for the above had a sub-race: the
  bump/snapshot/phantom-substitution happened across an unlock/relock
  gap, so a concurrent `requestStartForSession` could still observe
  the old timestamp. Restructured into a single acquire/release that
  fuses `lastWireActivity = time.Now()` → active-bidder snapshot →
  phantom-byte substitution atomically. The `IsKnownInitiatorByte`
  predicate runs **before** the lock (callback is read-only by
  contract; we don't want operator code executing under stateMu).

### Gateway

- Bump pin to `34a71c7`.

### No new config knobs

This release is a correctness follow-up; the Config surface is
unchanged from 0.6.4.

---

## 0.6.4 (2026-05-11)

### Proxy-bug fixes — unblock external sessions on idle bus

Live capture revealed ebusd, when connected to the gateway-embedded
adaptermux proxy on `:19001`, had never put a single frame on the
bus (`ebusctl grab result all` showed 0 frames with `src=0x31` over
multi-hour soak). Root cause: the proxy delivered arbitration grants
seconds-to-tens-of-seconds after ebusd's local arbitration deadline.
Latency capture before this release: REQ-burst → STARTED p50 = 2 s,
p99 = 12 s, max = 39 s. Bus utilization at the time was only ~15 %.

This release fixes that path with five corrective changes:

- **C1 — Bus-idle fast path.** New `SYNInterval` knob (default 4576 µs
  at 2400 baud). When the wire has been quiet for at least one SYN
  interval, the arbitrator grants external sessions immediately and
  skips the fairness-rotation counter. Fairness is for contention; on
  an idle bus there's nothing to balance.

- **C3 — Stale-START TTL.** New `PendingStartTTL` knob (default
  250 ms; negative disables). External pending requests whose enqueue
  age exceeds the TTL are drained from the queue head and rejected
  with `errStaleStartRequest`, so the client retries cleanly instead
  of receiving a grant past its own local deadline.

- **C4 — In-flight cancel + adapter resync.** When a session re-
  submits a START while a previous request is still in flight at the
  adapter, the late STARTED is converted to a FAILED and the
  transport is reconnected to resync the adapter's bus state. Stops
  the leak where ebusd would otherwise be handed a bus grant it had
  already abandoned.

- **C5 — Phantom-byte filter.** New `IsKnownInitiatorByte` config
  callback. FAILED data bytes classified as fictitious AND-collision
  artifacts (e.g. `0x7F & 0xF1 = 0x71` on a bus that has no `0x71`
  initiator) are substituted with the bidder's own initiator on the
  notify path AND suppressed from mirror delivery to other sessions —
  no more `0x71`/`0x01` pollution in ebusd's passive view.

- **Idle-kick on enqueue + passive wire-activity tracking.** The
  Mux-level `requestStartForSession` wrapper kicks `tryGrantAndStart`
  on enqueue when the wire is quiet (so external STARTs land within
  microseconds instead of waiting up to ReadTimeout for the next
  SYN-driven cycle), and `lastWireActivity` now bumps on *every*
  non-SYN adapter byte regardless of ownership, so third-party
  frames correctly register as wire activity.

The PR cycle drew **8 rounds of Codex P1+P2 review** (in-flight
cancel API gap, idle-kick gating, zero-TTL semantic, absorb-arm
drop, reconnect-on-cancelled-STARTED, stateMu race closure, pre-
notify phantom filter, passive wire-activity tracking). All addressed
inline.

### Observability scope alignment (Option A)

Active-path errors now bump `ebus_frames_observed_total` and
`ebus_frame_bytes_total` in addition to `ebus_errors_total` —
matching the long-standing passive-path semantic. Both scopes now
share the contract:

    frames_observed = attempts (success + failure)
    errors_total    = subset of failures, by class
    success ratio   = 1 - rate(errors) / rate(frames_observed)

**Dashboard migration:** anyone reading
`rate(ebus_frames_observed_total{scope="active"})` as "successful
active txns / sec" must subtract `sum(rate(ebus_errors_total{scope=
"active"}))` to recover the old meaning.

### Live evidence (post-deploy, against the pre-deploy baseline)

| Signal | Before | After |
| --- | --- | --- |
| Gateway `0x7f` frames in `ebusctl grab result all` | 0 | 90+ |
| ebusd `SEND 0xFE` forwarded by proxy | 0 | yes (live trace) |
| `max arbitration micros` | ~1228 | 14 |
| Frame pipeline latency (47k samples) | n/a | **100 % ≤ 5 ms** |
| ebusd error rate / min | ~30 | ~22 |
| Remaining error class (dominant) | self-inflicted mid-frame yanks | genuine bus contention from a third-party initiator at 0x10 |

The proxy-internal starvation is fixed. The remaining ebusd error
rate is **bus-physics**: ebusd at `0x31` loses bit-level arbitration
against the heavy `0x10` initiator on this physical bus, independent
of the gateway. That track is being investigated separately.

### Gateway

- Bump pin to `0f48902` (helianthus-ebusgateway main with PRs #622 +
  #623 merged).
- New `adaptermux.Config` fields: `SYNInterval`, `PendingStartTTL`,
  `ExternalSessionSYNGrace`, `LatencyHistogramReportInterval`,
  `IsKnownInitiatorByte`.

### Cache-bypass deploy note

HA Supervisor caches the local-addon version under its first-seen
tag. When the host already has 0.6.3 installed, the deploy path is
`docker pull :0.6.4-aarch64` + `docker tag … :0.6.1` + `ha addons
start` (Supervisor's internal version stays pinned to the original
install). A clean install picks the correct tag automatically.

---

## 0.6.3 (2026-05-11)

### F-10v2 — SYN-timeout grace asymmetry for external sessions

Pre-0.6.3, `wirePhaseEventSYNTimeout` released bus ownership
immediately regardless of who owned the bus. That fits the gateway's
own tight protocol (B5.24 directed reads, no inter-byte gap) but
wrongly tore down ebusd's broadcast scans whose multi-second inter-
responder gaps look identical to SYN-timeout to the wire-phase
machine. A 5000-log-line capture showed 80 false-positive releases
on ebusd's session vs 0 on the gateway's — a 96 % false-positive
rate against ebusd.

The release policy now splits on owner identity AND on the actual
idle gap, not the grant timestamp:

- **Gateway owner**: release immediately on SYN-timeout; 200 ms
  grace on SYNIdle measured from `busOwned` (legacy behaviour,
  unchanged).
- **External owner**: both wire-phase events use a grace measured
  from `lastWireActivity` (bumped on every non-SYN adapter byte),
  threshold `ExternalSessionSYNGrace` (new config knob, default
  **2 s**, calibrated to the ~190 ms inter-responder gap observed
  in a live ebusd scan trace).

### Diagnostic improvements (carries forward from 0.6.2)

- `adaptermux_session_frame_latency_us_bucket_total` is now also
  emitted as a single log line every 60 s. Cumulative semantics
  preserved in the log surface; histogram is visible in
  `ha addons logs` without curling `/debug/vars` from inside the
  addon container.

- Ownership-release log lines carry `remote=<addr>` for external
  sessions; the gateway's internal session shows `remote=unknown`
  (no TCP client).

### Gateway

- Bump pin to `df75035`.
- New `adaptermux.Config` fields: `ExternalSessionSYNGrace`,
  `LatencyHistogramReportInterval`.

---

## 0.6.2 (2026-05-11)

### F-9 — Arbitration-winner byte synthesis (root cause of "invisible gateway traffic")

The ENH adapter consumes the arbitration-winner byte as a
`StreamEventStarted` control event instead of echoing it through
`StreamEventByte`. Pre-0.6.2, external sessions (ebusd) never saw
the gateway's initiator byte (`0x7F`) on the wire — their ENH parser
then misread the next target/PB byte as the frame source, dropped
the frame as malformed, and the gateway's traffic was invisible in
`ebusctl grab result all` / initiator enumeration.

The mux now synthesizes the arbitration-winner byte into the per-
session ENH stream and the passive observer pipeline at the
StreamEventStarted/StreamEventFailed boundary. The synthesis covers
every arbitration outcome (matched STARTED — gateway wins / external
wins, mismatched STARTED — third-party won, FAILED — gateway lost /
external lost / absorbed-stale / no-pending).

**Net effect for ebusd**: gateway-initiated frames (initiator
`0x7F`) now appear in `ebusctl grab result all` and contribute to
the initiator count. Capture before/after the F-9 fix: `2` frames →
`145` frames in the same window.

8 rounds of Codex P2 review inline during the PR (STARTED ordering,
gateway-lost FAILED, multi-session non-bidder routing, disconnect
race, passive emit, mismatched STARTED, winner-byte-in-FAILED-
notify, FAILED-absorb preservation).

### F-10 — Byte-pipeline latency histogram

New expvar surface at `/debug/vars`:
`adaptermux_session_frame_latency_us_bucket_total` — Prometheus-style
cumulative histogram of enqueue → TCP-write latency. Buckets:
`le_1000`, `le_5000`, `le_25000`, `le_100000` (cumulative) plus
`gt_100000` (non-cumulative overflow bin).

Per-frame slow-log line when elapsed > 25 ms (= ebusd's default
`--receivetimeout`).

Timestamps captured via a process-start monotonic anchor so wall-
clock NTP/chrony steps cannot distort samples. Storage is an `int64`
nanosecond delta in each `sessionFrame` (8 bytes vs 24 for
`time.Time`) — saves ~128 MiB of baseline channel capacity at the
1000-session ceiling.

**Live result**: 100 % of frames ≤ 5 ms; the latency-as-root-cause
hypothesis for the "ebusd read timeout" cascade was falsified at
47 000+ samples on the live bus.

### Gateway

- Bump pin to `df75035`.
- Companion docs PR in `helianthus-docs-ebus` (`architecture/
  observability.md` extended with the F-10 histogram contract).

---

## 0.6.1 (2026-05-11)

### F-7 — Raw-TCP client diagnostic

ebusd configured with `network_device: HOST:PORT` (no `enh:` scheme
prefix) sends raw eBUS frames over TCP to our ENH-only listener,
producing a flood of `SEND … rejected — session does not own bus`
log lines until the operator notices.

After 16 SEND frames without a preceding ENH `INIT`/`INFO`/`START`
handshake, the session is now auto-closed with a clear log line:

    adaptermux: session N (pipe) sent 16 SEND frames with no
    preceding ENH INIT/INFO/START — closing as suspected raw-TCP
    client (did you forget the `enh:` scheme prefix? e.g. ebusd
    `network_device: enh:HOST:PORT`)

### Gateway

- Bump pin to `0cd06bd`.

---

## 0.6.0 (2026-05-11)

### Runtime state file — `/data/runtime_state.json`

Single persistent state file replaces the legacy
`/data/instance_guid` text file and centralises bus-membership
caching. Schema (v1):

    {
      "schema_version": 1,
      "meta": { "instance_guid", "written_at", "gateway_build", "addon_version" },
      "ebus": {
        "schema_version": 1,
        "self": { "last_join_initiator", "last_join_at", "join_method", "companion_target" },
        "known_bus_members": [ { addr, companion_addr, identity, last_seen_at, last_source, confidence } ]
      }
    }

- **Sole writer**: gateway. The addon wrapper only reads
  `meta.instance_guid` at startup and passes it via the
  `-instance-guid` flag.
- **Persistence cadence**: shutdown + every 15 min + on
  `JoinResult.Initiator` change.
- **Atomic writes** via temp + rename.
- **Schema versioning**: top-level `schema_version` + per-plugin
  `<plugin>.schema_version`. Mismatch per plugin = ignore that
  namespace, not fail startup.
- **Member cap**: 256 (one per eBUS address). Pruning via startup
  `07 04` directed re-validation; non-responders are dropped.
- **Corruption handling**: missing file = empty start; corrupt
  file = rename to `.corrupt-<ts>` and empty start, log warning.
  Gateway never blocks startup on cache state.

**Migration from 0.5.x is manual.** If you skipped 0.6.0 and went
straight to 0.6.1+, copy the value from `/data/instance_guid` into
`/data/runtime_state.json` under `meta.instance_guid` before
restarting, or delete `/data/runtime_state.json` to start fresh.

### F-1 — `proxy_listen_addr` fallback for HA Supervisor cache bug

When the HA Supervisor's option-rendering cache lags behind a config
update, the wrapper now falls back to a sane default for
`proxy_listen_addr` instead of refusing to start.

### F-4 — External-session fairness window

`FairnessRatio = 4` — when both the gateway and ≥ 1 external session
have pending START requests, every 4th `tryGrant` rotation goes to
the external FIFO instead of gateway-priority. Bounds the worst-case
external START latency to ~4 gateway-transaction windows.

### F-6 — Per-session frame logging

Each external session's INIT/INFO/START/SEND frames produce a single
log line, useful for distinguishing "no client traffic" from "client
traffic but no grants" when debugging arbitration starvation.

### Gateway

- Bump pin to `8fc34a2`.

### Other

- M0..M5 milestones of the `runtime-state-w19-26` execution plan
  shipped together. M6 (wrapper integration with AD09a/b/26/27) +
  M8 (Codex P1 follow-up) also included.

---

## 0.5.0 (2026-04-18)

### Source-address authority migration (SAS-02A / SAS-08A)

The legacy `/data/source_addr.last` file is no longer the authority
for source-address selection. The wrapper:

- No longer reads or writes `source_addr.last`.
- No longer exposes a `state-file` option.
- Treats any leftover `/data/source_addr.last` as a rollback marker
  only.

The runtime authority is the join-admission result tracked in
process state (the precursor to the `runtime_state.ebus.self.last_
join_initiator` field that landed in 0.6.0).

### `enable_static_seed_table` option (P3)

New advanced-config flag (default **off**) — when on, the gateway
seeds its address table from `helianthus-ebus-vaillant-productids`
for known Vaillant deployments. Operator-only escape hatch for
unusual bus topologies.

### Gateway

- Bump pin to `25d0636`.

---

## 0.4.0 (2026-04-11)

### Gateway v0.4.0

- **Adapter-direct mode stable** — dual-transport (setup + readLoop), stale comment cleanup
- **Wire phase tracker** — accounts for ArbitrationSendsSource (B524 root discovery fix)
- **INFO cache hardening** — volatile ID passthrough, invalidate on disconnect, rebuild on RESETTED
- **MaxOwnershipDuration** increased to 5s for contended bus headroom
- **B524 probe** timeout budget + retry backoff for adapter-direct reliability
- **Byte-level debug logging** removed from receive path (performance)
- **Startup scan** safety-net for unconfirmed passes

### Addon

- Bump gateway to v0.4.0 (commit 25d0636)
- Standalone adapter-proxy removed (gateway-embedded mux replaces it)
- VRC Explorer still bundled (main branch)

## 0.3.58 (2026-04-08)

### Transport reliability (ebusgo, proxy)

- **TCP_NODELAY** on ENH adapter socket — reduces per-operation latency by ~40ms
- **50ms collision backoff floor** — prevents PIC16F firmware race where rapid START floods cause transient eBUS signal loss
- **RESETTED TCP teardown+reconnect** — full close+re-dial+re-INIT on adapter reset instead of parser-only reset; eliminates stale kernel-buffered bytes from pre-reset session
- **Bus-level TCP reconnect** after timeout retry exhaustion — 3 attempts x 2s delay, resets timeout budget per session; recovers from dead TCP without restarting the gateway
- **waitForSyn** treats ErrAdapterReset as transient (suppress + continue), not terminal
- **Reconnect robustness** — fail fast without DialFunc; dial new connection before closing old to preserve retry budget on dial failure

### Proxy (adapter-proxy)

- **RESETTED recovery** — abort pending START/INFO, release bus ownership, re-INIT with feedback-loop guard (initSentAtNano timestamp + reinitGuard semaphore)
- **ENH collision backoff** — 50ms delay before releasing bus token after FAILED/ErrorEBUS/ErrorHost
- **200ms stabilization delay** before re-INIT after RESETTED
- **initSentAtNano race fix** — store timestamp before SendInit, clear on failure

### Gateway

- Bump helianthus-ebusgo to c3a36d2 (all transport fixes above)
- RawTransportOp lifecycle hardening: pending drain on INFO timeout

### VRC Explorer (v0.2.1)

- OP-first artifact structure refactor — eliminate namespace concept
- Planner: per-(OP,GG) recommended logic + rr_max_full for research
- HTML report: date/string constraint bounds display
- Fixes: sequence-offset INIT-only, absent presence exclusion, nack_or_crc support, stale schema refs
