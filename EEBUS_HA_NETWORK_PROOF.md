# eeBUS HA Network Proof

This runbook defines the `MSP-03C` proof artifact for Home Assistant add-on
networking readiness. It proves the add-on runtime can support a future raw
eeBUS sidecar, but it does not enable eeBUS, pair devices, persist production
trust, or expose GraphQL/Portal/Home Assistant consumer semantics.

## Scope

The proof maps to `eebus-transport-gate-v0` cases:

| Case | Scope |
| --- | --- |
| `EEBUS-G05` | Listener binds only the configured interface or subnet. Wildcard and unexpected bridge exposure fail. |
| `EEBUS-G06` | An external LAN peer can browse and resolve the SHIP mDNS service `_ship._tcp`. |
| `EEBUS-G07` | Disabled mDNS, unavailable Avahi/DBus, and closed pairing are explicit negative states. |
| `EEBUS-G08` | Manual endpoint fallback reaches the peer when discovery is unavailable. |
| `EEBUS-G09` | Disposable proof credentials survive restart without writing production trust. |

The CI fixture is a contract fixture, not lab evidence:

```bash
python3 scripts/check_eebus_ha_network_proof.py \
  --artifact scripts/fixtures/eebus_ha_network_proof_contract_pass.json \
  --mode contract
```

Use `--mode lab` for a real artifact collected from a Home Assistant runtime.
Lab mode requires `"mode": "lab_run"` and a `lab` object with repo branch,
commit, add-on build id, command-log ref, interface or subnet ref, external LAN
peer ref, listener socket ref, mDNS browse/resolve refs, restart ref, and
evidence IDs for each required case.

## Artifact Rules

The artifact must be public-safe. It must not contain:

- PEM blocks or private keys;
- passwords, tokens, or secret-bearing values;
- private or link-local IP addresses;
- MAC addresses;
- device serials or full fingerprints;
- vendor-restricted protocol details.

Use stable redacted references such as `sha256:0123456789ab` for disposable
identity continuity checks. Public PRs and issues cite only the redacted
artifact and publishable evidence IDs.

## Lab Collection Checklist

1. Confirm the add-on reports `host_network: true` and `host_dbus: false` from
   Supervisor metadata.
2. Start the proof runtime with a disposable store at `/data/eebus-proof`.
3. Confirm the listener is bound to the configured interface or subnet.
4. From a second LAN host, confirm TCP reachability to the configured listener.
5. From that same LAN host, browse and resolve the expected mDNS service.
6. Disable discovery or close the pairing window and confirm the service is
   absent or expires after TTL.
7. Configure a manual endpoint and confirm peer reachability with discovery
   unavailable.
8. Restart the proof runtime and confirm the same redacted disposable identity
   ref, with directory mode `0700` and file mode `0600`.
9. Run the validator in lab mode:

```bash
python3 scripts/check_eebus_ha_network_proof.py \
  --artifact /path/to/redacted-msp-03c-lab-artifact.json \
  --mode lab
```

## Non-Goals

- No `eebus.enabled` add-on option is added in this milestone.
- No SHIP/SPINE listener is started by the production add-on wrapper.
- No trust or pairing mutation is exposed to web UI, ingress, GraphQL, MCP, or
  Home Assistant.
- Same-container or same-bridge success is not accepted as LAN-side proof.
