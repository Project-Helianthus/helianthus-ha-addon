# Changelog

## 0.6.30 (2026-05-23)

### M4 startup L1 semantic barrier release

Bumps the bundled `helianthus-gateway` to commit
[`1bd068b`](https://github.com/Project-Helianthus/helianthus-ebusgateway/commit/1bd068b08534be86d06e630b3d46674e23ab0bef)
(PR #664).

This release fixes the real v0.6.29 startup O1 failure where startup scan
enrichment and source-selection/root-confirmation work could consume the first
60 seconds before semantic L1 priming completed. The gateway now releases
source-selection semantic bootstrap as soon as active source evidence exists,
retries the DHW singleton before the startup zone sweep, and defers delayed
physical serial identity enrichment beyond the L1 semantic window.

Local HA override proof before this add-on pin:
`_work_adaptermux_audit/v8-enforce-stress/m4-verification/20260523T150427Z_m4.txt`
showed all 12 MCP planes non-null at 48s and
`semantic_b524_root_discovery address=0x15` at 2026-05-23 18:04:36 local.

Docs evidence:
[helianthus-docs-ebus PR #315](https://github.com/Project-Helianthus/helianthus-docs-ebus/pull/315).

## 0.6.29 (2026-05-23)

### M4 startup L1 direct probes and empty-plane preservation

Bumps the bundled `helianthus-gateway` to commit
[`e068f46`](https://github.com/Project-Helianthus/helianthus-ebusgateway/commit/e068f46c713ea7dee86c87ffd6fb7397577c4a04)
(PR #663).

This release fixes the real v0.6.28 startup O1 failure where `solar` and
`cylinders` remained null in the first 60 seconds. The gateway now publishes
non-null empty FM5 semantic planes for known non-interpreted/GPIO-only FM5
states, preserves empty `cylinders` and `radio_devices` through GraphQL and
MCP adapters, and uses direct live B524 startup probes so the first-minute L1
readiness path is not blocked by semantic read-breaker cooldown. Interpreted
FM5 mode still requires non-empty cylinder evidence before startup L1 can pass.

Local HA override proof before this add-on pin:
`_work_adaptermux_audit/v8-enforce-stress/m4-verification/20260523T132412Z_m4.txt`
showed all 12 MCP planes non-null at 48s; logs showed
`semantic_b524_root_discovery address=0x15` about 12s after gateway startup.

Docs evidence:
[helianthus-docs-ebus PR #313](https://github.com/Project-Helianthus/helianthus-docs-ebus/pull/313)
and
[helianthus-docs-ebus PR #314](https://github.com/Project-Helianthus/helianthus-docs-ebus/pull/314).

## 0.6.28 (2026-05-23)

### M4 startup L1 semantic priming

Bumps the bundled `helianthus-gateway` to commit
[`2fbef5a`](https://github.com/Project-Helianthus/helianthus-ebusgateway/commit/2fbef5ab5e8510b0442c6b61416804ee1b51a0d5)
(PR #662).

This release keeps the Direction C first-byte arbitration revalidation from
v0.6.27 and adds the startup semantic priming needed for the M4 live gate:
after B524 root discovery, the gateway primes zones, circuits, DHW,
radio devices, FM5 mode, solar, cylinders, system, and boiler status with
bounded startup probes so all 12 MCP semantic planes can populate inside
the 60-second O1 window.

Local HA override proof before this add-on pin:
`_work_adaptermux_audit/v8-enforce-stress/m4-verification/20260523T121840Z_m4.txt`
showed `discoverB524Root` at 12s and all 12 MCP planes non-null at 47s.

## 0.6.27 (2026-05-23)

### F-NEW-29: first-byte arbitration revalidation + F-22 log spam rate-limit

Bumps the bundled `helianthus-gateway` to commit
[`cc0beb1`](https://github.com/Project-Helianthus/helianthus-ebusgateway/commit/cc0beb1)
which combines two merged gateway PRs:

- **PR #660 (F-22 log spam debounce)** — rate-limits the
  `tryGrantAndStart skipped — waiting to absorb N stale arbitration
  response(s)` log line to 1 Hz with `(N suppressed)` suffix. Under
  sustained stress this line was emitting at 144 lines/sec (763
  lines/min steady-state); operators lost log signal-to-noise.

- **PR #661 (F-NEW-29 first-byte arbitration revalidation)** — closes
  the semantic-layer recovery-time regression. Pre-fix on production
  HA host: `discoverB524Root` took ~9 hours to resolve `0x15` after
  addon restart under bus contention. Root cause: the P11 round-2
  strict mid-write byte filter at `mux.go:2315-2317` (commit
  `a35b51d1`, 2026-05-10) drops every wire byte that doesn't match
  `preMatchHead`. When the gateway "wins" arbitration but the wire
  actually has a competing Vaillant internal initiator (e.g. 0xF1)
  mid-frame, all foreign bytes are suppressed, `bus.go`'s
  first-byte-after-arbitration classifier never raises
  `ErrBusCollision`, and `sendWithRetries` never retries. The fix
  adds an event-driven revalidation predicate: when
  `matchCount==0 && writeCount==1` and the first wire byte is a
  foreign initiator-class address mismatching `preMatchHead`, forward
  the byte to `activeCh` (do NOT drop) so `bus.go`'s classifier
  engages naturally. P11 round-2 strict drop preserved for all
  other mismatches.

**Plan**: [helianthus-execution-plans#30](https://github.com/Project-Helianthus/helianthus-execution-plans/issues/30)
(adversarial converged: Codex R1 + fresh Opus R1+R2).

**Verification gates** (run M4 verification on .4 after deploy):
- Within 60s of addon startup, all 12 MCP semantic planes return non-null.
- `discoverB524Root: address=0x15` log line within 60s.
- `round9_absorb_entered_total` slope = 0/min over 90-min stress.
- `post_grant_ack` rate ≤ 10/hour absolute.
- collision rate ≤ 1.5× pre-fix baseline (~825/hr).

(v0.6.26 was prepared but never released; superseded by v0.6.27 which
combines both fixes.)

## 0.6.25 (2026-05-21)

### F-NEW-28: layer-correct round-9 fix — close midWriteSyn payload-0xAA leak

Bumps the bundled `helianthus-gateway` to commit
[`6c982e1`](https://github.com/Project-Helianthus/helianthus-ebusgateway/commit/6c982e1)
(PR #659), which pins to `helianthus-ebusgo` commit
[`f9919f4`](https://github.com/Project-Helianthus/helianthus-ebusgo/commit/f9919f4)
(PR #168).

**What v0.6.24 missed.** PR #658 closed a real classifier-layer bypass
for `StreamEventWireSyn` (pre-grant SYN markers). But the stress-test
re-baseline showed `helianthus_round9_absorb_entered_total` still
ticking at ~4/min — same rate as pre-fix. Dual adversarial review
(Codex + fresh Opus angry-tester) converged on the actual leak path:

  mux.go:2487 `midWriteSyn` predicate distinguished by BYTE VALUE
  alone. Pending `(SymbolSyn, structural-terminator)` and
  `(SymbolSyn, payload-0xAA)` expected echoes were indistinguishable.
  The predicate treated BOTH as "not mid-write" and let wire AUTO-SYNs
  through to bus.go's echo position during payload-0xAA writes.

**This fix (cross-repo).**

1. `helianthus-ebusgo` PR #168: new optional transport interface
   `StructuralWriteSignaler`. `sendRawWithEcho` calls
   `SignalNextWriteIsStructuralSyn()` before each structural-SymbolSyn
   write (i.e. `expectRawSyn=true`). Backward-compatible: transports
   that don't implement the interface degrade gracefully (round-9
   absorb at `bus.go:1204` remains the canonical filter for them,
   per v8 §1.8).

2. `helianthus-ebusgateway` PR #659: `activeTransport` implements
   `StructuralWriteSignaler`. Threads the flag through
   `sendRequest.structural` into `echoTracker.expectedStructural`
   (new length-locked slice). `midWriteSyn` predicate updated to
   `hasPendingEcho && !(nextByte == SymbolSyn && nextStructural)` —
   correctly distinguishes structural-terminator (allow through) from
   payload-0xAA (suppress wire SYN interference).

**Production expectation.** After deploy: `round9_absorb_entered_total`
rate → 0 within 5 min on the HA host (where v8 is in enforce mode).
The 99.78% suppression rate v0.6.24 already provided was the v8
classifier doing its job; this fix closes the remaining 0.22% leak
at the SYN-delivery gate.

**Risk note.** Batch-25 reverted an earlier wider suppression that
caused 65% throughput drop. This fix is **strictly narrower**: it
only suppresses when the pending echo is specifically
`(SymbolSyn, structural=false)`, which corresponds to a payload-0xAA
in-flight write. Legitimate terminator SYNs (the common case after
non-0xAA-ending frames) are unaffected. To be empirically verified
in the post-deploy stress test.

Full diagnosis: `_work_adaptermux_audit/v8-enforce-stress/findings.md`.

## 0.6.24 (2026-05-21)

### F-NEW-27: close StreamEventWireSyn classifier bypass

Bumps the bundled `helianthus-gateway` to commit
[`267d243`](https://github.com/Project-Helianthus/helianthus-ebusgateway/commit/267d243fe3305d04a2d41376215ae462edac9eed)
(PR #658). Closes a v8 classifier bypass surfaced during the
2026-05-21 enforce-mode stress test:

- PR #155 (2026-05-15) introduced `StreamEventWireSyn` — a
  pre-grant SYN passive marker emitted by enh_transport during
  awaiting-start. The mux routes WireSyn to
  `onReceived(event.Byte, wasEscaped=false)`, treating it as a
  raw wire 0xAA byte downstream.
- The v8 classifier's `Observe()` switch (designed before
  WireSyn existed) had no case for `StreamEventWireSyn` — the
  event fell through, returning `drop=false` regardless of mode.
- Consequence: wire SYNs delivered via this newer event kind
  bypassed the v8 filter entirely and reached the gateway's
  echo position unfiltered, producing sustained
  `helianthus_round9_absorb_entered_total` ticks (~2.6/min) in
  enforce mode — the I8 invariant violation the
  `HelianthusRound9FiredUnderProxy` alert exists to catch.

Diagnosed via Codex + fresh Opus adversarial reviews of the
2026-05-21 enforce stress test baseline snapshot (test was
held at T+1m for this exact reason). Independently verified by
reading `classifier.go:298-321` vs `mux.go:1946-1952`.

Fix: classifier's `Observe()` switch gets a `StreamEventWireSyn`
case that delegates to the same FSM-driven classification path
as `StreamEventByte`, with `WasEscaped` forced to `false` (kind
implies raw wire; trusting `event.WasEscaped` would re-open the
bypass). In enforce mode, mid-frame WireSyn now returns
`drop=true` and is filtered out of session dispatch.

Post-deploy expectation: `helianthus_round9_absorb_entered_total`
PLATEAUS in enforce mode. Any continued ticking indicates a
different bypass path that needs separate investigation.

No config schema changes. No new env vars.

## 0.6.23 (2026-05-21)

### Default `v8_classifier_mode` promoted from `off` → `enforce`

Closes the shadow→enforce promotion gate documented in
helianthus-docs-ebus/deployment/prometheus-alerts.md. New addon
installations now default to enforce mode — the v8 classifier
actively filters mid-telegram wire AUTO-SYN (0xAA) bytes out of
cross-proxy session byte streams.

**Why this is safe** (live-bus validation evidence):

- `_work_adaptermux_audit/v8-shadow-validation-20260520T055414Z.md`
  iter-7 captured the per-event distribution behind the aggregate
  `helianthus_v8_shadow_would_have_dropped_total` counter using the
  new `GET /debug/v8/admin-events?peek=true` endpoint added in
  addon 0.6.22.
- 100% of `aa_injection_drop` events showed the canonical pattern:
  `byte=0xAA, was_escaped=false, fsm_state=PASSIVE_TRACKING`. Zero
  false-positives across multiple sustained observation windows.
- The signal is bounded — ~3 bytes/s under healthy bus, all
  validated as real wire garbage that enforce mode now filters out
  of cross-proxy streams.

**In-place upgrade contract:**

- Existing addon installations whose `/data/options.json` explicitly
  sets `v8_classifier_mode` to `"off"` or `"shadow"` are NOT
  affected — the addon options blob overrides the config-schema
  default. Operators opting out of enforce must explicitly set the
  option in addon options.
- Operators who never set the option (using the implicit `off`
  default) get the new `enforce` default automatically on next
  addon restart.

**Operator opt-out:** for any reason an operator wants the previous
`off` or `shadow` behavior, set the option explicitly in the addon
config UI or via `ha addons options local_helianthus --options
'{"v8_classifier_mode": "off"}'`.

**Observability post-promotion:**

- `helianthus_v8_shadow_would_have_dropped_total` stays at 0 in
  enforce mode (Classifier.ShadowWouldHaveDroppedTotal returns 0
  outside ModeShadow).
- The byte filtering is observable via the inverse counter:
  `helianthus_v8_classifier_enforce_drops_applied_total` (via
  `EnforceDropsAppliedTotal()` — already exported by the
  gateway's classifier; not in PR scope here).
- `helianthus_round9_absorb_entered_total` should stay at 0 under
  enforce; any non-zero rate fires
  `HelianthusRound9FiredUnderProxy` per
  prometheus-alerts.md.

No config schema changes (option already existed since 0.6.18).
No gateway pin change (consumes commit `1c76be8` from addon
0.6.22).

## 0.6.22 (2026-05-21)

### v8 admin events HTTP endpoint

Bumps the bundled `helianthus-gateway` to commit
[`1c76be8`](https://github.com/Project-Helianthus/helianthus-ebusgateway/commit/1c76be8f332f10f6f2cbc881529461c4006485ee)
(PR #657), which adds:

- New `AdminEventKindAaInjectionDrop` v8 classifier admin event,
  emitted on every `DecisionDropAaInjection` in ModeShadow or
  ModeEnforce. Captures wire byte, FSM state at decision time,
  escape-decoded provenance, and observation timestamp.

- New HTTP endpoint `GET /debug/v8/admin-events`:
  - Default: drains the classifier's admin event ring buffer
    (destructive — the long-running poller contract).
  - `?peek=true`: returns the ring without clearing (for ad-hoc
    operator inspection like `curl | jq` or dashboards).

This unblocks the shadow→enforce promotion gate documented in
helianthus-docs-ebus/deployment/prometheus-alerts.md by making the
`helianthus_v8_shadow_would_have_dropped_total` counter
introspectable byte-by-byte. Operators can now decide whether
v8's would-have-drops are true-positive (real wire AA-injection,
safe to enforce) or false-positive (legitimate traffic v8
over-eagerly flags, do not promote).

Wire format (stable for operator tooling):

```
{
  "events": [
    {
      "at": "2026-05-21T...",
      "kind": "aa_injection_drop",
      "fsm_state": "<TELEGRAM_STATE>",
      "byte": "0xAA",
      "was_escaped": false
    }
  ],
  "dropped": 0
}
```

No config schema changes. No observable behavior changes in healthy
paths (the v8 classifier was already running with shadow-mode
counters; this exposes per-event detail behind those counters).

## 0.6.21 (2026-05-21)

### Bug fix: F-22 absorb-reset debounce (defense-in-depth)

Bumps the bundled `helianthus-gateway` to commit
[`953f641`](https://github.com/Project-Helianthus/helianthus-ebusgateway/commit/953f641f393db829ce0867c25053a4af194d803a)
(PR #656), which replaces the per-arm `time.AfterFunc` +
generation-invalidation pattern in `armPendingStartAbsorbLocked` with
a single persistent `*time.Timer` + `Reset()` (debounce).

The old pattern had a theoretical livelock failure mode when
re-arming faster than `StartDeadline`: each new arm bumped the
generation counter, invalidating its own AfterFunc's gen check at
fire time. The reset never executed and `pendingStartAbsorb` could
stay > 0 indefinitely, blocking new RequestStart grants.

The 2026-05-20 12:25 UTC drop in active B524 polling on this addon
was investigated and the root cause was bus-physical (signal-loss
storms on the eBUS adapter), NOT this livelock. The semantic
read-breaker correctly opened during the impaired period and the
gateway recovered when the bus stabilized. This PR closes the
class of bug structurally so it cannot manifest in any future
condition.

Also includes a stale-callback race fix flagged by Codex round-1
review: a pre-empted AfterFunc callback acquiring stateMu after a
fresh arm could clear a fresh post-arm counter. Fixed via
`pendingAbsorbResetDueAt` — the callback no-ops when a fresh arm
has bumped the deadline.

No config schema changes. No observable behavior changes in
healthy paths.

## 0.6.20 (2026-05-20)

### Observability: v8 rollout + round-9 counters now on /metrics and /debug/vars

Bumps the bundled `helianthus-gateway` to commit
[`0690e66`](https://github.com/Project-Helianthus/helianthus-ebusgateway/commit/0690e661690a64508d4efc2fecee25ec304de9b6)
(PR #655), which publishes five new counters needed to evaluate the
`v8_classifier_mode` shadow → enforce promotion gate:

- `helianthus_round9_absorb_entered_total` — backs the
  `HelianthusRound9FiredUnderProxy` alert.
- `helianthus_payload_aa_auto_syn_absorbed_total` — forensic
  byte-cost of round-9 firings.
- `helianthus_payload_aa_auto_syn_recovered_total` — forensic
  recovery rate of round-9 firings.
- `helianthus_payload_aa_auto_syn_drain_exhausted_total` — forensic
  unrecovered round-9 firings.
- `helianthus_v8_shadow_would_have_dropped_total` — backs the
  `HelianthusV8ShadowWouldHaveDroppedGrowing` alert; reports 0 when
  `v8_classifier_mode` is `off` or `enforce`.

All five names are exposed both on `/metrics` (Prometheus) and
`/debug/vars` (expvar). Operator usage documented in
helianthus-docs-ebus/deployment/prometheus-alerts.md.

No config schema changes. No behavior changes — observability only.

## 0.6.13 (2026-05-13)

### F-22: absorb-timeout no transport reconnect

**Companion to 0.6.12.** Batch-19 live verification measured the
`unexpected_symbol` rate that F-19e instrumented post-deploy: 0.87
events/min, dominated by Pattern A (offending=0x00 @ WaitTerminal,
26/68 min). Same window measured a parallel issue: 13 transport
reconnects / 90 min from the active-mux absorb-safety-net, each
producing cascade `RequestStart failed` events (263 total) on
external sessions (ebusd) that had no transport-level reason to
fail.

F-22 (helianthus-ebusgateway PR #632) replaces the transport-
reconnect side effect with a counter-reset-only behavior. When the
absorb-safety-net fires (an expected stale STARTED/FAILED never
arrived from the adapter), the mux now logs the event, bumps a new
`absorbResetTotal` counter, clears `pendingStartAbsorb`, and lets
the next semantic poll iteration issue a fresh `RequestStart` on
the still-open ENH connection. Mirrors F-15's reasoning that
internal state-machine timeouts don't justify a transport reset.

**F-15 blocking-path AM8 reconnect** (legacy `StartArbitration`
goroutine that may genuinely hang) is UNAFFECTED — that's a
separate code path keyed on `blockingArb=true` and pinned by
`TestF15_AM8_DeadlineReconnect`.

### F-23: ENH transport unescapes eBUS byte pairs + WasEscaped propagation

**Two-repo change merged together** (ebusgo PR #154 → 5215685 and
ebusgateway PR #632 → 6f44780).

Before F-23, the ENH transport claimed `BytesAreUnescaped()=true`
but actually forwarded raw wire bytes — escape pairs leaked through
as two-byte sequences. Live evidence (batch-19): two recurring
fingerprints:

- **Pattern A** (CRC=0xA9 wire-encoded `A9 00`): the trailing 0x00
  was misclassified as a spurious byte at WaitTerminal phase →
  `unexpected_symbol offending=0x00` (~26/68 min).
- **Pattern B** (data byte 0xA9 at response index 13): wire-encoded
  `A9 00` overran the response-length counter by 1 → response
  overrun at WaitFinalACK with `offending=0x1B` (~4/68 min).

CRC arithmetic verification (operator pre-flight): three production
sequences matched expected CRCs under the escape-leak hypothesis
(`0xA9`, `0xA9`, `0x1B`).

#### What changed

- **PR-1 (ebusgo)**: new `EbusEscapeDecoder` runs on every
  StreamEventByte emission in `ENHTransport`. `BytesAreUnescaped()`
  contract is now honest. New `StreamEvent.WasEscaped` field carries
  the wire-side truth flag. New `EscapeFlaggedReader` interface
  exposes `ReadByteWithEscape()`. 16 reset call sites cover every
  Layer-1 boundary (reconnect, RESETTED, parse-error, arbitration
  abort/timeout/expiry/completion, RequestStart write-failure).
  8 rounds of Codex bot adversarial review converged on yes-ship.

- **PR-2 (ebusgateway)**: WasEscaped propagation end-to-end through
  both adapter-direct passive path and active mux path. New fields
  `PassiveEvent.WasEscaped` and `activeEvent.wasEscaped`.
  `onReceived(symbol, wasEscaped)` signature change. SYN-detection
  at mux level now provenance-aware (`isWireSyn := symbol ==
  SymbolSyn && !wasEscaped`) so escape-decoded payload 0xAA is not
  misclassified as wire SYN — preventing false ownership release and
  phase-tracker corruption. `activeTransport` implements
  `EscapeFlaggedReader` so `protocol.Bus`'s post-F-23 waitForSyn /
  sendRawWithEcho guards activate on the gateway's active bus.
  4 rounds of Codex bot adversarial review.

- **F-22 stale-absorb window**: secondary fix triggered by Codex
  P1 on PR-2 — software-side equivalent of the pre-F-22 transport
  reconnect boundary. When the absorb-safety-net fires, set
  `staleAbsorbDeadline = now + StartDeadline`. `readLoop` drops any
  STARTED/FAILED arriving inside this window. Prevents reused-
  initiator-grants-wrong-owner and stale-FAILED-fails-new-request.

### Gateway version

- `cmd/gateway/main.go` `buildVersion` bumped `0.4.0` → `0.6.0`
  (was stale; aligns with addon's 0.6.x cadence). Surfaces via
  `GatewayVersion` (portal HTTP responses) and `GatewayBuild`
  (runtime_state.json `<version>+<build_id>`).

### Post-deploy

Operator runs ≥60 min then dispatches the batch-20 bucketing agent.
Expected metrics per operator's predicted outcome (batch-19 spec):

- F-22 path: 5 transport reconnects/68min → 0; cascade RequestStart
  failures 92/68min → <10/68min.
- F-23 Pattern A (offending=0x00 @ WaitTerminal) 10/68min → 0.
- F-23 Pattern B (offending=0x1B @ WaitFinalACK) 4/68min → 0.
- Total unexpected_symbol: 20/68min → ~5–7/68min residual.
- F-18, F-15, F-17, F-19a/c/d/e: unchanged.
- ebusd messages counter: continues climbing.
- ebusd reconnects: stays at 0.

### Refs

- helianthus-ebusgo PR #154 (commit 5215685): F-23 ENH unescape.
- helianthus-ebusgateway PR #632 (commit 6f44780): F-22 + F-23
  consumer cleanup + buildVersion 0.6.0.
- `_work_adaptermux_audit/EBUSD-VERIFICATION-2026-05-13-batch19.md`.

## 0.6.12 (2026-05-13)

### F-19e: forensic instrumentation for unexpected_symbol diagnostics

**Companion to 0.6.11.** v0.6.11 (F-19d) eliminated the AA-cascade
fingerprint (7 → 0 mid-frame wire-SYN events per batch-18
verification). Batch-18 then surfaced `unexpected_symbol` as the
next-largest abandon category at ~50 events / 69 min (0.72/min).
Pre-F-19e these abandons emitted reason/phase/src/dst/prim/sec and
req_raw/resp_raw forensics — but NOT the single observed wire byte
that triggered the abandon, so the rate was undiagnosable.

### What changed

**Instrumentation only.** No behavior changes, no new abandon reasons,
no logic changes.

- `abandonLocked` signature extended with `offendingSymbol byte,
  offendingWasEscaped bool` (trailing params).
- `PassiveClassifiedEvent` gains `OffendingSymbol` +
  `OffendingWasEscaped` fields.
- `logForensicsLocked` log line now ends with
  `offending_symbol=0x%02X offending_was_escaped=%v` AFTER the
  existing `observed_at=` token (preserving legacy regex
  compatibility).
- F-19d `wasEscaped` flag threaded into handleACKSymbolLocked,
  handleFinalACKSymbolLocked, handleTerminalSymbolLocked (informational
  at these phases since they don't observe ambiguous 0xAA bytes, but
  forwarded for forensic uniformity).
- All 27 `abandonLocked` call sites updated. Byte-driven sites
  forward the current byte + `wasEscaped`; lifecycle abandons
  (Shutdown, TransportReset, NoProgress watchdog, etc.) pass
  `(0, false)` and are gated out of forensics by
  `shouldLogReconstructorForensics`.

### Post-deploy

Run ≥60 min then bucket the `offending_symbol=0xXX
offending_was_escaped=v` distribution from logs. The distribution
guides v0.6.13:

- Clustering near 0x00 / 0xFF → upstream phase-tracking drift in
  the WaitACK / WaitFinalACK arms (reclassify as `near_ack_drift`?).
- Clustering at escape-sequence fragments (0xA9 / 0xAA with
  `was_escaped=true`) → upstream decoder fault, F-19f territory.
- Uniform random distribution → wire corruption on the live bus,
  no Helianthus-side fix.

### Codex bot review

One P2 finding addressed in PR #631 (commit d0a7104): the two
`InvalidZZ` branches initially hardcoded `offendingWasEscaped=false`
based on the sender-side spec invariant (`symbol.h:41` — QQ/ZZ are
never escape-encoded). Fix: forward the handler's `wasEscaped`
parameter so spec-violating escape-encoded bytes at ZZ position are
preserved in the forensic data.

### Sample log line

```
passive_reconstructor abandon reason=unexpected_symbol phase=2
  src=0x10 dst=0x08 prim=0xB5 sec=0x16
  req_raw=10 08 B5 16 01 55 BF resp_raw=<empty>
  observed_at=2026-05-13T13:01:20Z
  offending_symbol=0x42 offending_was_escaped=false
```

### Refs

- helianthus-ebusgateway PR #631 (commit 259243c)
- `_work_adaptermux_audit/EBUSD-VERIFICATION-2026-05-13-batch18.md`

## 0.6.11 (2026-05-13)

### F-19d: WasEscaped plumbing for SYN-vs-data disambiguation

**Companion to 0.6.10.** v0.6.10 (F-19c) shipped spec-bound checks at
QQ/ZZ/NN/buffer; live verification (batch-17) confirmed the F-19c
gate works but surfaced ~9 cascade-fingerprint events/hour where a
wire SYN arrives mid-frame and the heuristic `isMidRequestFrame()` /
`isMidResponseFrame()` misclassifies it as escape-decoded data 0xAA.
The buffer absorbs the SYN, eats the next frame's
SRC/DST/PB/SB/LEN, and F-19a abandons the bogus 16+ byte buffer as
`corrupted_request` — masking a true bus-event SYN as a CRC fault.

### Root cause + fix

Wire encoding (john30/ebusd `symbol.h:79-82`): both `0xA9 0x01` and
raw wire `0xAA` produce logical 0xAA after upstream decoding. The
previous heuristic disambiguated by buffer length — wrong on a
3-initiator Vaillant bus where wire SYNs mid-data happen during bus
errors / collisions.

Fix: carry a per-byte `WasEscaped bool` flag from the passive bus
tap's escape decoder through `PassiveTapEvent` into the
reconstructor. Replace the heuristic with the wire-side ground
truth. Reuse the existing `unexpected_syn` reason for the
SYN-mid-frame abandon path (distinct from `corrupted_request`).

Path 1 (raw wire transports): the local escape decoder produces
WasEscaped precisely.

Path 2 (already-logical observer streams: adapter-direct via
PassiveTransport, ENH/ENS proxy-like): the upstream layer has
already decoded escapes. WasEscaped=false is the conservative
default. The reconstructor treats !wasEscaped logical 0xAA as a
wire SYN — the dominant interpretation for production Vaillant
traffic per batch-17 evidence.

### Adversarial review

- Operator-locked spec (single-repo per AGENTS.md invariant).
- Codex CLI: VERDICT SHIP, no real defects.

### Observability

The new `unexpected_syn` reason is distinct from `corrupted_request`
in the abandon-reason metric. Operators can grep:

```
passive_reconstructor abandon reason=unexpected_syn phase=1 …
                                                   ^^^^^^^^^^
```

to identify frames terminated by a bus event mid-stream (vs frames
with a bad CRC at LEN-completion which still classify as
`corrupted_request`).

### Predicted pass criteria (batch-18)

| Metric | v0.6.10 | v0.6.11 target |
|---|---|---|
| `corrupted_request phase=1 src=0x10` rate | 0.98/min | < 0.4/min |
| `corrupted_request phase=1 src=0xF1` rate | 0.86/min | < 0.4/min |
| `unexpected_syn` reason events | small | rising to ~0.15/min |
| `invalid_nn_m` / `invalid_nn_s` / `buffer_overflow` | unchanged | unchanged |
| F-18 metrics | green | unchanged |

### Out of scope

- F-19b cleanup (dead `arbitration_fragment` branch): tracked separately.
- Spec-strict tightening (`> 16` → `> 14`): deferred per batch-16.

### Gateway

- Bump pin to `837cdfe`.

---

## 0.6.10 (2026-05-12)

### F-19c: eBUS spec bound checks at QQ/ZZ/NN/buffer

**Companion to 0.6.9.** v0.6.9 partially fixed F-19 but live
verification (batch-16) surfaced 14 abandons per 75-min log window
where the LEN byte itself was corrupted to a spec-illegal value
(0x84=132, 0xAF=175, 0xFF=255). F-19a's `5+LEN+1` completion target
overshot the next bus SYN, so the buffer ate next-frame bytes before
the SYN-trigger path classified the abandon.

### Root cause + fix

The passive reconstructor previously trusted any byte at logical
offset 4 as the initiator-side LEN. The OSI-7 spec caps NN at 14
(mfr-specific)
/ 10 (standardised); the codebase uses 16 via the existing
`maxPassiveDataLen` constant per industry folklore. Similarly, no
defensive checks existed for QQ (initiator nibble rule), ZZ
(non-SYN/non-ESC), or NN_s on the responder side.

Code changes:

1. Five new abandon reason constants:
   - `invalid_qq` — QQ violates the nibble rule (defense-in-depth)
   - `invalid_zz` — ZZ is SYN/ESC (per symbol.h:41 QQ/ZZ never escape-encoded)
   - `invalid_nn_m` — initiator-side LEN > 16
   - `invalid_nn_s` — responder-side LEN > 16
   - `buffer_overflow` — post-unescape buffer > 50 bytes (tight cap,
     replaces the looser 512-byte one)

2. Helper functions in `passive_reconstructor_f19c_helpers.go`:
   `isInitiatorAddr`, `isInitiatorNibble`, `isValidTargetAddr`.
   Reference: john30/ebusd `symbol.cpp:209-229` (25-initiator nibble rule).

3. Bound checks fire at byte-observation time:
   - QQ check at the Idle-handler call site (between Layer 2 gate
     and `startRequestLocked`)
   - ZZ + NN_m + watchdog in `handleRequestSymbolLocked` post-append
   - NN_s in `handleResponseSymbolLocked` before
     `responseExpectedLen` is computed

4. Layer-1 reset: all F-19c abandons use plain `resetStateLocked`
   (no AfterSyn) — the offending byte is never a wire SYN; the next
   bus SYN re-engages the Layer-1 gate via the Idle handler.

5. Observability: F-19c reasons added to
   `shouldLogReconstructorForensics` (Codex bot P2 round 1) and to
   `classifyPassiveAbandon`'s non-error bucket (Codex bot P2 round 2)
   — preserves the `req_raw=...` diagnostic evidence AND prevents
   passive error metrics from spuriously incrementing on reclassified
   noise abandons.

### Adversarial review trail

- 2-agent pre-PR convergence (Explore code-walk + angry-tester
  adversarial attack) decomposed F-19c into the 5-reason fix surface
- Codex CLI: VERDICT NEEDS-CHANGES → FIXED in-PR. Caught that the
  per-byte switch's `case 1` (QQ check) was dead code because
  `startRequestLocked` appends QQ before `handleRequestSymbolLocked`
  runs. Relocated to Idle-handler call site.
- Codex bot round 1 (P2): F-19c reasons missing from forensic-log
  predicate. Added.
- Codex bot round 2 (P2-A): F-19c reasons missing from non-error
  metric bucket. Added.
- Codex bot round 2 (P2-B): NN_s byte lost from forensic log because
  abandon fired before responseRaw append. Reordered.
- Zero unresolved threads at merge.

### Tests added

11 regression tests in `passive_reconstructor_f19c_test.go` covering:
- All 3 live-evidence wire patterns (0x84, 0xAF, 0xFF)
- NN=16 boundary acceptance
- QQ defense-in-depth + nibble-rule unit test
- ZZ SYN + ESC variants
- NN_s response-side path with log-capture assertion
- Buffer-overflow watchdog
- F-19a regression guard (valid LEN + bad CRC still hits F-19a)
- F-18 echo-passthrough separation
- Forensic-log predicate inclusion (5 sub-cases)

### Predicted pass criteria (batch-17)

| Metric | v0.6.9 | v0.6.10 target |
|---|---|---|
| `corrupted_request phase=1 src=0x10` rate | 2.21/min | < 0.8/min |
| `corrupted_request phase=1 src=0xF1` rate | 1.19/min | < 0.5/min |
| `invalid_nn_m` / `invalid_nn_s` events | 0/min | ~0.2/min |
| `buffer_overflow` events | 0/min | ~0/min |
| F-18 metrics | green | unchanged |

### Out of scope

- F-19d forensic instrumentation (WasEscaped plumbing): future work
- F-19b reconsideration (dead `arbitration_fragment` branch):
  unchanged
- Tightening the cap below 16 for strict spec fidelity:
  operator-deferred

### Gateway

- Bump pin to `dd8750c`.

---

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
