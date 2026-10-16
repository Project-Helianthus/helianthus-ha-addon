# Portal / Ingress offline acceptance checklist

This is a procedure for the existing Portal and Ingress owners after their
implementation lands, not a record of successful acceptance. Every checkbox is
unexecuted. It is the documentation slice of
[issue #249](https://github.com/Project-Helianthus/helianthus-ha-addon/issues/249).
Refs [add-on #239](https://github.com/Project-Helianthus/helianthus-ha-addon/issues/239),
[gateway #999](https://github.com/Project-Helianthus/helianthus-ebusgateway/issues/999)
and [gateway #1002](https://github.com/Project-Helianthus/helianthus-ebusgateway/issues/1002).
Parent acceptance stays open. This checklist changes no image pin, option,
listener, authentication policy or deployment.

## Baseline and pending work

Recheck these sources against the candidate before executing the checklist:

| Source | Observed implementation / acceptance boundary |
| --- | --- |
| [Add-on metadata](../helianthus/config.json) | No Ingress metadata is declared. HTTP GraphQL and subscriptions have separate path options; MCP has its own path. Host networking and published ports are existing packaging, not proof of selective publication. |
| [Startup wrapper](../helianthus/rootfs/etc/services.d/helianthus-gateway/run) | Wires GraphQL/subscription/MCP paths and persistent instance identity. This does not establish a trusted-proxy or prefix contract. |
| [Add-on README](../helianthus/README.md) | Documents `/data/instance_guid` surviving restart/update when `/data` is preserved. No promise of durable Portal configuration or investigation sessions follows from that identity file. |
| [Smoke runbook](../SMOKE_RUNBOOK.md) | Existing runtime smoke checks are separate from Ingress acceptance; do not run its install/start steps as part of this offline procedure. |
| [Portal handler](https://github.com/Project-Helianthus/helianthus-ebusgateway/blob/main/portal/handler.go) and [assets](https://github.com/Project-Helianthus/helianthus-ebusgateway/tree/main/portal/static) | Source serves a root-relative handler with relative HTML asset URLs and browser API/stream fetches. Bootstrap still supplies absolute `/portal/api/v1/...` paths plus configured GraphQL/subscription/MCP paths. Snapshot/session stores are constructed in memory. These are source observations, not verification of the packaged binary. |
| [Gateway HTTP composition](https://github.com/Project-Helianthus/helianthus-ebusgateway/blob/main/cmd/gateway/main.go) | Source mounts the Portal handler under its Portal path using prefix stripping and redirects the path without a trailing slash. This alone does not implement arbitrary external Ingress prefixes. |

The release-plan PORTAL work remains with its owners: #999 covers generic
trusted external authentication and path-prefix embedding; #1002 coordinates
standalone configuration and optional Home Assistant embedding;
[gateway #1000](https://github.com/Project-Helianthus/helianthus-ebusgateway/issues/1000)
covers Portal configuration and passive observation/cache;
[gateway #1001](https://github.com/Project-Helianthus/helianthus-ebusgateway/issues/1001)
covers selective publication. Add-on #239 consumes those contracts for Ingress
and minimal installation. Output participation/publication also depends on
[eeBUS registry #137](https://github.com/Project-Helianthus/helianthus-eebusreg/issues/137)
and [Matter binding #4](https://github.com/Project-Helianthus/helianthus-matter-binding/issues/4).
This slice supplies none of those implementations or their completion evidence.

## Gateway owner acceptance handoff

The routing and trust cases below are requirements handed to
[gateway #999](https://github.com/Project-Helianthus/helianthus-ebusgateway/issues/999)
and [gateway #1002](https://github.com/Project-Helianthus/helianthus-ebusgateway/issues/1002).
Executable implementation acceptance belongs in that repository, together with
its candidate handler, synthetic providers, proxy/browser fixtures and CI
registration. These cases are not steps in this add-on's local procedure and
cannot be marked complete by its URL oracle. The gateway owners must publish
their executable procedure and results before add-on integration acceptance;
until then, implementation acceptance is Unknown and parent acceptance stays open.
Public source links above provide context only, not a reproducible test artifact.

### Routing observations to collect

Use only a synthetic fixture prefix `P = /fixture-ingress` (no trailing slash).
The table names browser-visible paths; a fixture proxy strips `P` exactly once
before forwarding. Root means the gateway's unprefixed mount, not a second
Portal implementation. If the accepted owner contract chooses another mount,
record the mapping explicitly and apply it consistently to every row.

| Case | Root path | Prefixed path | Expected observation after implementation |
| --- | --- | --- | --- |
| Entry | `/portal`, `/portal/` | `P/portal`, `P/portal/` | Slash canonicalization preserves the prefix, query and same origin; no redirect escapes to the root mount. |
| HTML and assets | `/portal/`, `/portal/assets/app.js`, `/portal/assets/app.css` | `P/portal/`, `P/portal/assets/app.js`, `P/portal/assets/app.css` | HTML and every imported asset load with appropriate content type; no missing asset is silently returned as HTML. A warm-cache reload still works. |
| Bootstrap/API | `/portal/api/v1/bootstrap`, `/portal/api/v1/health` | `P/portal/api/v1/bootstrap`, `P/portal/api/v1/health` | Browser fetches and every enabled bootstrap endpoint resolve within the prefix; absolute bootstrap paths cannot bypass it. Disabled capabilities stay unavailable. |
| GraphQL | `/graphql` | `P/graphql` | A synthetic read yields the same admitted data and error envelope through both mounts; customized configured paths are also covered. |
| Websocket subscriptions | `/graphql/subscriptions` | `P/graphql/subscriptions` | The documented websocket negotiation and synthetic subscription deliver an event through the proxy; disconnect/reconnect works without polling being mistaken for websocket success. Repeat with customized subscription path. |
| Portal stream | `/portal/api/v1/stream` | `P/portal/api/v1/stream` | SSE remains `text/event-stream`, produces bounded synthetic events and cancels on disconnect; this is separate evidence from GraphQL websocket subscriptions. |
| Relative navigation | `/portal/` | `P/portal/` | Every enabled section, keyboard navigation, refresh and browser back/forward stay under the selected mount. Follow relative links, query strings and fragments; test direct reload of any supported deep link. Unsupported routes must follow the owner's documented error behavior. |

- [ ] Exercise clean and warm browser caches; inspect requests and redirects,
  not just the first rendered page. Include nested script imports and any
  configured endpoint returned by bootstrap. Record a root-path escape as FAIL.
- [ ] Compare MCP and GraphQL observations of the same synthetic state against
  their owner contracts; Ingress routing must not redefine payloads, native
  evidence or the existing eBUS MCP behavior. Namespaces remain pre-stable
  before 1.0; intentional changes require owner documentation and goldens.

### Trust and publication boundaries

- [ ] Obtain the accepted #999 trust contract first: which proxy peer is trusted,
  how identity is supplied and sanitized, and how direct/untrusted access is
  handled. If unspecified, mark BLOCKED; do not choose header names, roles,
  grants or anonymous access rules in this checklist.
- [ ] In an in-process fixture, send missing, forged and conflicting forwarded
  identity/prefix headers from an untrusted peer. They must not grant identity,
  change the trusted base path or widen access. Trusted proxy identity must
  come only through the configured boundary; arbitrary forwarded headers are
  not authentication. Assert the exact rejection/anonymous response only after
  the owner contract specifies it. Keep existing native-write and eeBUS guards.
- [ ] Test the trusted peer with admitted and rejected identities, and a direct
  backend request outside that boundary. Distinguish HA session admission from
  gateway authorization; an authenticated page is not authority for all actions.
- [ ] Against the #1001 publication matrix, independently inspect Portal,
  adapter proxy, GraphQL, MCP, eeBUS and Matter output surfaces. A Portal session
  must not automatically publish any of them. A withheld surface remains
  unreachable/unadvertised as specified by its owner, including direct paths;
  a hidden button is insufficient. Test selective choices independently.
- [ ] Verify synthetic partial last-known-good state retains source/provenance
  and stale/unavailable markers across failures. Unknown native facts remain
  Unknown; Proven/Hypothesis/Unknown evidence is separate from qualification.
  Do not infer qualification or write authority from visibility in Portal.

The gateway owner handoff also includes zero-device onboarding with optional
families/output bindings absent, saved configuration surviving a synthetic
store restart, fresh-store defaults, and fail-closed handling of corrupt saved
configuration. Instance identity persistence must be checked separately from
Portal settings, snapshots and sessions. The gateway owners must define recovery
behavior and register implementation tests in their own CI; this add-on document
adds no executable gateway acceptance or CI registration.

## Offline fixture procedure (no Home Assistant or devices)

Run from a standalone checkout. This executable URL oracle uses synthetic
relative paths and the standard library only; it opens no sockets. It checks
the checklist's fixture expectations, not the Portal implementation.

```bash
python3 - <<'PY'
from urllib.parse import urljoin
for prefix in ("", "/fixture-ingress"):
    base = prefix + "/portal/"
    for relative in ("assets/app.js", "assets/app.css", "api/v1/bootstrap",
                     "api/v1/health", "api/v1/stream", "?view=semantic", "#semantic"):
        result = urljoin(base, relative)
        assert result.startswith(base), (base, relative, result)
    graphql = prefix + "/graphql"
    subscription = prefix + "/graphql/subscriptions"
    assert subscription == graphql + "/subscriptions"
    if prefix:
        assert not urljoin(base, "/portal/api/v1/stream").startswith(prefix + "/")
print("PASS: synthetic URL oracle; implementation acceptance remains unexecuted")
PY
```

The remaining local validation is this repository's
[local gate](../scripts/ci_local.sh), run from the checkout root:

```bash
./scripts/ci_local.sh
```

Record each command, exit status and sanitized observation. Both local checks
are runnable from this checkout alone; neither establishes gateway routing,
trust, browser streaming or persistence acceptance.

## HA / Ingress smoke (separate, not executed here)

These steps require implemented owner contracts and a separately approved test
installation. Obtain explicit operator confirmation at action time before any
install, configuration write, restart or other live mutation. Do not execute the
existing runbook's deployment commands under offline-checklist authority.

- [ ] Record the candidate image/version and the owners' accepted contracts in
  the private test record. Open Portal through the HA UI using an admitted HA
  session; repeat the routing table with the actual runtime prefix kept private.
  Confirm JS/CSS, GraphQL websocket subscriptions and SSE through HA, including
  reconnect after the separately approved restart. No mixed-content or root-path
  escape should appear in browser observations.
- [ ] Test missing/expired HA session and direct/untrusted backend access against
  the accepted trust contract. Forwarded-header spoofing must not authenticate.
- [ ] Repeat minimal installation and selective publication observations. Portal
  access must not silently enable adapter proxy, API or output sharing.
- [ ] With action-time confirmation, restart/update while preserving the add-on
  data, then compare saved configuration and instance identity privately.
  A fresh isolated installation must show documented onboarding defaults.
- [ ] Record PASS / FAIL / BLOCKED / UNVERIFIED per case with sanitized evidence.
  Publish only family-level synthetic observations: no credentials, identities,
  serials, network coordinates, private captures or capture times.

Completion of this checklist would provide integration evidence only. It does
not close #239 or its companion issues, qualify native protocol evidence, or
establish release/hardware acceptance. No eBUS protocol/transport production
change is in scope; if one becomes necessary, hold it for its owner and the
T01..T88 hardware gate. The final repository classifier and any stricter gate
still apply; G5 D6 supplies no blanket hardware waiver.
