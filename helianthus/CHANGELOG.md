# Changelog

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
