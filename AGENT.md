# Helianthus HA Add-on – Agent Instructions

## Scope

This repository contains the Home Assistant add-on for Helianthus. The current phase is bootstrap only: add minimal add-on structure and repo docs without any functional daemon or integration logic.

## Constraints

- Keep changes minimal and focused on scaffolding.
- Do not introduce real eBUS/HA integration until explicitly requested.
- Follow `CONVENTIONS.md` for repo structure and documentation style.
- React (emoji) to every review comment and reply with status when actioned.

## MCP-first Policy

### Scope and ordering
- MCP is the primary prototyping/exploration interface.
- GraphQL is second and may reach parity only after MCP tools are deterministic and contract-solid.
- Home Assistant and other consumers are enabled only after GraphQL parity and stability gates are met.

### Tool taxonomy and naming
- Core stable tools use versioned names: `ebus.v<MAJOR>.<domain>.<subdomain>.<verb>`.
- Experimental tools live under `ebus.experimental.*` and are never used by external consumers.
- Prefer composable tools over monolithic endpoints.

### Contract envelope (required for ebus.v1.*)
Each `ebus.v1.*` tool returns:
- `meta` with `contract`, `consistency`, `data_timestamp`, `data_hash`
- `data`
- `error` (null or structured error)

### Determinism requirements
- List ordering must be stable.
- Snapshot mode must produce stable `data_hash` for identical snapshot + request.
- Tool schemas and outputs must have golden snapshots.

### Invoke safety
`ebus.v1.rpc.invoke` requires:
- explicit `intent` (`READ_ONLY` or `MUTATE`)
- `allow_dangerous=true` for mutating or unknown methods
- `idempotency_key` for mutating intent

### Graduation gates (MCP -> GraphQL)
A capability may graduate to GraphQL only if:
1. it exists as core stable MCP (`ebus.v1.*`)
2. it passes determinism + contract + golden tests
3. parity tests MCP <-> GraphQL are green

### End-of-cycle cleanup
At cycle end, each `ebus.experimental.*` tool must be promoted, deleted, or moved to internal-only with written justification.
No temporary/junk tool may remain in the showroom surface.

### CI gates
- Breaking changes in `ebus.v1.*` require a new major namespace.
- Parity drift MCP vs GraphQL fails CI.
