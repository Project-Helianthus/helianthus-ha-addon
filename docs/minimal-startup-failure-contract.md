# Minimal-install startup failure and retry dispositions

This packaging lifecycle contract is the documentation slice of
[add-on #260](https://github.com/Project-Helianthus/helianthus-ha-addon/issues/260).
Refs [parent #239](https://github.com/Project-Helianthus/helianthus-ha-addon/issues/239);
parent acceptance remains open. It describes source-observed behavior and
explicit future proposals; it implements no startup change. Nothing is stable
before Helianthus 1.0. No new namespace or authentication, credential, principal
or permission check is introduced. Authentication/authorization evolution belongs
to 0.11, not this 0.7 slice; no authorization gate is added before 0.9.

## Source authority and scope

The current observations below come from these public source destinations:

- [Modbus guard](https://github.com/Project-Helianthus/helianthus-ha-addon/blob/main/helianthus/rootfs/usr/share/helianthus/modbus_runtime_guard.py):
  `load_config`, `_duration_milliseconds`, `_validate_endpoint`, `main`.
- [Serial/CAN option helper](https://github.com/Project-Helianthus/helianthus-ha-addon/blob/main/helianthus/rootfs/usr/share/helianthus/serial_can_options.py):
  `load_options`, `_family`, `_convert`, `build_args`, `main`.
- [Startup wrapper](https://github.com/Project-Helianthus/helianthus-ha-addon/blob/main/helianthus/rootfs/etc/services.d/helianthus-gateway/run):
  Modbus validation/staging, transport selection, `binary_supports_flag`,
  `gateway_supports_flag`, enabled-feature checks and final `exec`.
- [Portal / Ingress offline acceptance](https://github.com/Project-Helianthus/helianthus-ha-addon/blob/main/docs/portal-ingress-offline-acceptance.md):
  existing owner handoff and unexecuted acceptance boundaries.

These links track main and may change. Source inspection establishes **Proven**
control-flow observations only, not execution or qualification. **Hypothesis**
marks proposed dispositions; **Unknown** marks unavailable evidence. Neither
Proven nor a visible diagnostic admits a profile, proves hardware, or grants
write authority. No native protocol fact is established here: protocol/type
contracts remain with their public native owners.

This page classifies packaging startup failures. K26 owns the routing checklist,
M34 owns wiring, and W28 owns cohort upgrades/rollback. None is consumed or
completed here. The Portal checklist link is context, not evidence that Ingress
works. This page changes no options, persistence precedence, gateway semantics,
listener policy, eBUS MCP behavior or GraphQL payload/error parity. Preserve
native evidence and partial last-known-good state under their existing owners;
never replace Unknown or stale state with fabricated success. Existing runtime
admission stays fail-closed. Output bindings remain with their drivers.

## Current guard sequence

The wrapper uses `set -euo pipefail`. Modbus `load_config` treats a missing
options document as an empty object, requires a real boolean enabled field,
and ignores inactive endpoint/timeout fields when disabled. When enabled it
requires strings, a positive `ms`/`s` duration from 100 ms through 30 s, and a
TCP URI with a host and explicit valid port, without user information, path,
query or fragment. This is syntax validation, not a connection attempt.
`main` returns 2 with `invalid Modbus TCP configuration` on handled failures.
The wrapper captures successful shell assignments in a protected temporary
file, stages the endpoint privately and atomically, passes an endpoint-file
flag rather than its value, and cleans pre-exec material on exit. It removes
the retired health record; that file is not a supported diagnostic interface.

The serial/CAN helper's name does not imply CAN hardware probing. `_family`
emits nothing for a disabled family, including dormant fields. Enabled
RS-485 observer and retained charging-controller families require every listed
field; `_convert` checks types/ranges, label syntax, duration syntax and device
path syntax. `build_args` requires distinct asset/source labels for each family
and observer quiescence strictly greater than maximum response delay. `main`
returns 2 with a fixed prefix and a key/rule explanation for handled errors.
It shell-quotes successful argv for internal evaluation. No device is opened or
checked for existence by these functions. The retained owner is described by
the source as identity/epoch wiring without opening a serial or network path;
that observation is not a physical CAN qualification.

Transport selection rejects an invalid proxy profile or adapter-direct protocol,
a selected proxy without its endpoint, and adapter-direct with a nonempty proxy
endpoint or missing direct address. Legacy selector handling remains unchanged.
The wrapper checks enabled Modbus and serial-family flags against gateway help;
disabled serial families require no flags. Mandatory `instance-guid` support is
checked independently. Help-probe errors are swallowed by
`binary_supports_flag`, so missing/broken binaries can resemble missing support.

Other existing prelaunch guards remain: protected eeBUS option types, enabled
eeBUS flag completeness and readable interface identity; runtime-state identity
resolution; and the enabled M2M bundle/flag checks. This contract adds no device
check or client-bundle requirement. In particular, the existing M2M client-bundle
requirement is observed, not endorsed or extended; Y03 owns its removal.

## Input / error / exit / retry / diagnostic matrix

**Current** means source-observed. Helpers' status 2 is not necessarily the
wrapper's status: `bashio::exit.nok` stops launch, but its numeric mapping is not
defined in the inspected sources. “Stop” below means prelaunch non-success,
with no gateway `exec`. There is no wrapper retry loop for these rows; service
manager restart limits are Unknown. Proposed retry policy is specified below.

| Input or failure | Current guard / error class | Current exit or transition | Retry disposition | Diagnostic and Portal disposition |
| --- | --- | --- | --- | --- |
| No optional protocol selected | `load_config` disabled result; `build_args` empty; wrapper disabled branches | Helpers return 0; no optional flags; remaining bootstrap guards still apply before `exec` | No optional activation or retry | Current disabled-family logs. Zero-device Portal onboarding is Proposed, not proven. |
| Malformed active option or options document | Modbus `load_config` / duration / endpoint checks; serial `load_options`, `_family`, `_convert` | Helper 2; wrapper Stop | Proposed: no automatic retry until corrected input | Current Modbus generic message; serial key/rule explanation. No gateway Portal from this attempt. |
| Incompatible active values | `build_args`: equal asset/source labels or quiescence not exceeding delay; wrapper transport conflicts above | Serial helper 2 or wrapper Stop | Proposed: no retry of unchanged combination | Current key/rule or fixed combination error; no Portal from stopped gateway. |
| Optional family enabled but packaged feature unsupported | `gateway_supports_flag` loops for Modbus, serial, eeBUS or M2M | Stop; no silent disabling of the requested family | Proposed: no retry until compatible package/configuration | Current feature/flag error, no Portal. Not evidence of absent hardware. |
| Optional artifact absent while its feature is off | Disabled M2M skips bundle checks; disabled families skip feature flag checks | Continue those branches; does not waive mandatory helpers/binary | No retry for unused artifact | Proposed: explain unavailable optional capability if Portal runs. Current Portal diagnostic Unknown. |
| Required artifact for an enabled optional feature absent | Enabled M2M file readability/completeness loop | Stop with fixed bundle error | Proposed: no automatic retry until provisioned by its owner | Current log only, no Portal. Adds no new bundle or credential check. |
| Packaging helper or gateway binary absent/broken | Python invocation failure or failed help probe; required identity flag gate | Stop or shell failure; missing binary can be reported as unsupported required flag | Proposed: no automatic retry of unchanged broken package | Current classification can be ambiguous. Proposed sanitized packaging-artifact error; no Portal. |
| Hardware unavailable with syntactically valid active options | No Modbus dial or serial existence probe in these helpers; enabled eeBUS already checks readable interface identity | Serial/Modbus may reach `exec`; existing eeBUS interface failure stops before launch | Post-exec reconnect belongs to gateway; limits Unknown here | Serial/Modbus Portal survival Unknown. Proposed degraded Portal only if gateway remains healthy; eeBUS prelaunch failure has log only. |
| Temporary-file/staging/cleanup or identity bootstrap failure | Modbus pre-exec cleanup/staging; runtime-state wrapper result handling | Stop; identity migration result 1 explicitly exits 1; pre-exec TERM/INT exits 143/130 | Proposed: no automatic retry until cause resolved; signals are not config errors | Fixed Modbus errors where explicit; arbitrary tool stderr is not certified safe. No Portal from this attempt. |
| Gateway cannot start or exits after launch | Final `exec` replaces wrapper; no supervising loop here | Shell exec failure or daemon exit; daemon status/health classification Unknown from these sources | Proposed bounded service-manager policy below | No in-process Portal can diagnose a dead daemon. Use sanitized service diagnostics; no Portal availability promise. |

## Proposed diagnostic and retry contract (future work)

The following transitions are **Hypothesis**, not implemented acceptance or a new
API. They require their owners' implementation and evidence before adoption.

1. For configuration rejection, incompatible input, requested unsupported feature,
   required missing artifact and bootstrap failure, stop before launch. Do not
   silently switch transports, enable a device, discard saved configuration or
   restart with defaults. The wrapper performs one validation/launch attempt and
   zero automatic retries for an unchanged deterministic failure. Correction is
   an explicit owner/operator action, not a retry timer.
2. A successfully running gateway with an optional acquisition failure may keep
   a useful Portal showing that family unavailable, sanitized cause and stale or
   Unknown evidence while preserving partial last-known-good data and provenance.
   This is conditional on the gateway owner's isolation contract; the wrapper
   must not bypass an existing guard to obtain it. No placeholder Portal, new
   endpoint/envelope, or persistence format is specified here.
3. After a genuine daemon startup failure, the service-manager owner would allow
   at most three automatic relaunches per explicit start, at delays of 1, 2 and
   4 seconds, then latch stopped with a diagnostic. An explicit operator start
   would reset the budget; mere process uptime would not. This candidate budget
   is unimplemented; the actual manager configuration, failure classification
   signal and distinction between deliberate stop and crash are Unknown. Do not
   claim the current add-on is bounded. No wrapper/Portal/client retry loop may
   multiply that budget. Gateway transport reconnect limits remain gateway-owned
   and must be documented separately; these delays do not redefine them.
4. Public-safe diagnostics must use fixed categories and known option keys/rules,
   never rejected values, full argv, eval output, endpoint material, identity,
   certificate contents, device identifiers or raw exception/tool output. A useful
   stopped-service record would say which phase failed, whether correction or a
   compatible package is required, and whether retries exhausted. These are
   human-facing requirements, not a new stable machine-readable interface.

Current Modbus handled errors meet the narrow value-redaction observation;
serial handled errors name fixed keys/rules without interpolating rejected
values. Successful helper stdout is internal wiring and must never be logged as
a diagnostic. The wrapper elsewhere logs effective addresses, identity and
endpoints, and one source-override rejection includes its value. Thus existing
logs as a whole are **not certified public-safe**. Sanitized categories and
service diagnostics above remain proposed; log-redaction implementation is
outside this page. Do not copy raw startup logs into public reports.

## Synthetic review cases and remaining acceptance

These are manually traced cases, not executed tests or a runnable install recipe.
All other mandatory bootstrap conditions are assumed satisfied unless stated.

| Case | Source-grounded result | Evidence gap |
| --- | --- | --- |
| Zero devices; optional toggles off; valid bootstrap context | Modbus disabled config and empty serial argv; disabled eeBUS/M2M branches skip optional prerequisites | Positive packaging branch trace only. Base transport arguments still exist; standalone zero-device Portal availability and onboarding remain Proposed and unexecuted. |
| Active Modbus timeout `0s` | `_duration_milliseconds` rejects before endpoint validation; helper 2 | Wrapper/container execution unverified. |
| Serial enabled field is string `true` | `_family` rejects non-boolean; helper 2 | No runtime or hardware inference. |
| Valid observer fields except asset/source both `fixture-a` | `build_args` rejects equality | Source trace assumes other required fields valid. |
| Valid observer fields except delay `2s`, quiescence `2s` | `build_args` rejects non-increasing interval | No transport timing qualification. |
| Adapter-direct true with nonempty synthetic proxy endpoint | Wrapper rejects the combination before launch | No endpoint value needs publication or connection. |
| Enabled optional feature missing one required help flag | Wrapper rejects requested feature before `exec` | Packaged binary compatibility not exercised. |
| M2M disabled with optional bundle absent; then enabled with one file absent | Disabled branch skips checks; enabled branch stops | Does not remove the current requirement or add one; Y03 remains separate. |
| Valid serial path syntax with no device present | `_convert` checks syntax only | No device probing performed; gateway failure isolation and Portal health Unknown. |
| Daemon fails after `exec` | Wrapper cannot serve a fallback Portal or supervise it | Manager retries, daemon exit categories and Portal health require owner evidence. |

Manual review covers each table row, proposed transition and synthetic case
against the linked functions/branches. Readability and offline link-destination
checks establish neither semantic execution nor runtime success. No new tests or
CI registration are required by this contract-only slice; the existing smoke
validator targets the smoke runbook, not this page. CI therefore supplies no
semantic verification of this proposed contract.

Remaining parent acceptance includes minimal-install implementation and failure
isolation, Portal configuration persistence, accepted routing/embedding contracts,
selective listener publication, MCP/GraphQL compatibility, coherent package and
upgrade/rollback proof, and desktop/mobile/Companion/session/reconnect evidence.
Ingress functionality, full committed-head gates, independent review, profile
admission, hardware and authorized live HA acceptance remain unverified here.
No restart, deployment, credential change or parent closure is authorized by
this document.
