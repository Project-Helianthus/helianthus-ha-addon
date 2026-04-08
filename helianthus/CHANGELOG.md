# Changelog

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
