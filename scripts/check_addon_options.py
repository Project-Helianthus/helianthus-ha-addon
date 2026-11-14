#!/usr/bin/env python3
"""Offline, source-backed inventory of Supervisor options and their consumers.

This validates packaging wiring, not native support or hardware qualification.
The schema, shipped reads, helper binding tables and BOM are independent inputs.
Every option is also classified as a bootstrap setting the host keeps or a
setting the gateway Portal configuration record owns.
"""
from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
RUN = 'helianthus/rootfs/etc/services.d/helianthus-gateway/run'
SERIAL = 'helianthus/rootfs/usr/share/helianthus/serial_can_options.py'
MODBUS = 'helianthus/rootfs/usr/share/helianthus/modbus_runtime_guard.py'
MAP = 'scripts/addon-option-map.json'
CLASSES_DOC = 'docs/addon-option-classes.md'
CLASS_FIELDS = ('class', 'reason', 'portal_key')
# Gateway Portal configuration contract, relative to the gateway docs directory.
PORTAL_CONTRACT = 'architecture/portal-config-sharing.md'

# Members of the gateway Portal configuration record. Driver enablement is one
# member per editable driver. portal_keys_from_docs rederives this set from the
# gateway contract so drift is caught wherever that contract is available.
PORTAL_KEYS = frozenset({
    'drivers[ebus.primary].enabled', 'drivers[eebus.primary].enabled',
    'drivers[growatt.bms.rs485].enabled', 'drivers[modbus.sunspec].enabled',
    'sharing.graphql', 'sharing.mcp', 'adapter_proxy', 'output_bindings.matter',
})

# Why the host, not the Portal record, keeps a bootstrap option.
BOOTSTRAP_REASONS = ('listener', 'transport', 'identity', 'paths',
                     'native-policy', 'unmanaged-driver')

# Options whose ordinary choice the Portal record owns. The add-on value stays
# host eligibility: a Portal selection narrows it and never widens it.
PORTAL_OWNERS = {
    'eebus_enabled': 'drivers[eebus.primary].enabled',
    'growatt_bms_rs485_enabled': 'drivers[growatt.bms.rs485].enabled',
    'modbus_tcp_enabled': 'drivers[modbus.sunspec].enabled',
}

BOOTSTRAP_OPTIONS = {
    'listener': ('host', 'http_port', 'mdns', 'proxy_listen_addr', 'eebus_listen_port',
                 'eebus_interface', 'eebus_subnets', 'eebus_discovery_enabled',
                 'm2m_graphql_enabled'),
    'transport': ('adapter_direct_enabled', 'adapter_direct_protocol', 'adapter_direct_address',
                  'transport', 'network', 'address', 'proxy_profile', 'proxy_endpoint',
                  'scan_request_timeout', 'read_timeout', 'write_timeout', 'dial_timeout',
                  'adapter_mux_idle_release_grace', 'adapter_mux_max_ownership_duration',
                  'adapter_mux_read_timeout', 'modbus_tcp_endpoint', 'modbus_tcp_dial_timeout',
                  'modbus_tcp_endpoints'),
    'identity': ('source_addr', 'mdns_instance', 'eebus_remote_ski_allowlist',
                 'm2m_graphql_server_name', 'm2m_graphql_asset_ref',
                 'modbus_tcp_endpoints[].label'),
    'paths': ('graphql_path', 'subscription_path', 'mcp_path'),
    'native-policy': ('broadcast', 'observe_first_enabled', 'passive_state_direct_apply',
                      'passive_config_direct_apply', 'external_write_policy',
                      'enable_static_seed_table', 'v8_classifier_mode',
                      'modbus_tcp_endpoints[].family'),
    'unmanaged-driver': ('growatt_bms_can_enabled', 'growatt_bms_pcs_can_enabled',
                         'growatt_bms_link_can_enabled', 'tesla_gen3_hsc_retained_enabled'),
}

# Family members not listed above follow their suffix.
BOOTSTRAP_SUFFIXES = (
    ('identity', r'(asset_id|source_id|source_epoch|driver_generation|unit_id|endpoint_id'
                 r'|clock_epoch|evse_id|connector_id|node)'),
    ('native-policy', r'(stale_after|project_code|release|native_profile|scope|bank|context'
                      r'|native_contract|source_selectors)'),
    ('transport', r'(serial_path|baud|parity|stop_bits|response_timeout|max_response_delay'
                  r'|max_quiescence|interface|listen_only_confirmed)'),
)


def expected_class(key: str) -> tuple[str, str]:
    if key in PORTAL_OWNERS:
        return 'portal', PORTAL_OWNERS[key]
    for reason, keys in BOOTSTRAP_OPTIONS.items():
        if key in keys:
            return 'bootstrap', reason
    if key.startswith('modbus_tcp_endpoints[].'):
        return 'bootstrap', 'transport'
    if key.startswith(('growatt_', 'tesla_')):
        for reason, suffix in BOOTSTRAP_SUFFIXES:
            if re.search(r'_' + suffix + r'$', key):
                return 'bootstrap', reason
    raise ValueError('No option class rule: ' + key)


def portal_keys_from_docs(docs: Path) -> frozenset[str]:
    """Derive the record members from the gateway Portal configuration contract."""
    text = (docs / PORTAL_CONTRACT).read_text(encoding='utf-8')
    if '| Record option |' not in text:
        raise ValueError('Portal contract has no record option table')
    table = text.split('| Record option |', 1)[1].split('\n\n', 1)[0]
    members = re.findall(r'(?m)^\| `([^`]+)` \|', table)
    drivers = re.search(r'The editable drivers are the compiled managed set:(.+?)\.\s', text, re.S)
    if not members or drivers is None:
        raise ValueError('Portal contract has no editable driver set')
    ids = re.findall(r'`([^`]+)`', drivers.group(1))
    keys = set()
    for member in members:
        if member == 'drivers[].enabled':
            keys.update(f'drivers[{driver}].enabled' for driver in ids)
        else:
            keys.add(member)
    if not ids or 'drivers[].enabled' not in members:
        raise ValueError('Portal contract has no driver enablement member')
    return frozenset(keys)


def section(text: str, heading: str) -> str:
    if '\n' + heading + '\n' not in text:
        raise ValueError('Missing section: ' + heading)
    body = text.split('\n' + heading + '\n', 1)[1]
    return re.split(r'(?m)^## ', body, maxsplit=1)[0]


def classified(mapped: dict, document: str, portal_keys: frozenset[str]) -> dict:
    """Check each option's class against its rule, the Portal keys and the document."""
    unknown = set(PORTAL_OWNERS.values()) - portal_keys
    if unknown:
        raise ValueError(f'Portal key absent from gateway contract: {sorted(unknown)}')
    reasons = dict(re.findall(r'(?m)^\| `([^`]+)` \| ([^|\n]*\S[^|\n]*) \|$',
                              section(document, '## Bootstrap reasons')))
    if set(reasons) != set(BOOTSTRAP_REASONS):
        raise ValueError('Bootstrap reasons are not all defined')
    rows = re.findall(r'(?m)^\| `([^`]+)` \| (bootstrap|portal) \| `([^`]+)` \|$',
                      section(document, '## Classification'))
    documented = {key: (cls, detail) for key, cls, detail in rows}
    if len(rows) != len(documented) or set(documented) != set(mapped):
        raise ValueError('Option classes document inventory mismatch')
    for key, entry in mapped.items():
        if documented[key] != option_class(key, entry, portal_keys):
            raise ValueError('Option classes document mismatch: ' + key)
    return mapped


def option_class(key: str, entry: dict, portal_keys: frozenset[str]) -> tuple[str, str]:
    cls = entry.get('class')
    member = {'bootstrap': 'reason', 'portal': 'portal_key'}.get(cls)
    if member is None:
        raise ValueError('Unclassified option: ' + key)
    if set(entry) & {'reason', 'portal_key'} != {member}:
        raise ValueError('Class member mismatch: ' + key)
    detail = entry[member]
    allowed = BOOTSTRAP_REASONS if cls == 'bootstrap' else portal_keys
    if detail not in allowed:
        raise ValueError(f'Unknown {member}: {key}')
    if (cls, detail) != expected_class(key):
        raise ValueError('Incorrect option class: ' + key)
    return cls, detail


def inventory(schema: dict, prefix: str = '') -> set[str]:
    result = set()
    for name, value in schema.items():
        key = prefix + name
        result.add(key)
        if isinstance(value, list) and value and isinstance(value[0], dict):
            result.update(inventory(value[0], key + '[].'))
        elif isinstance(value, dict):
            result.update(inventory(value, key + '.'))
    return result


def translation_inventory(configuration: dict, prefix: str = '') -> set[str]:
    result = set()
    for key, value in configuration.items():
        name = prefix + key
        if not isinstance(value, dict) or not all(
            isinstance(value.get(field), str) and value[field].strip()
            for field in ('name', 'description')
        ):
            raise ValueError('Missing English name/description: ' + name)
        result.add(name)
        if 'fields' in value:
            result.update(translation_inventory(value['fields'], name + '[].'))
    return result


def literals(source: str) -> dict:
    values = {}
    try:
        tree = ast.parse(source)
    except SyntaxError as error:
        raise ValueError('Invalid shipped helper syntax') from error
    for node in tree.body:
        if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name):
            try:
                values[node.targets[0].id] = ast.literal_eval(node.value)
            except (ValueError, TypeError):
                # Non-literal assignments are not binding tables; skip them.
                continue
    return values


# Nontrivial wrapper routes are explicit: spelling an option like a CLI flag
# would be wrong for aliases, file materialization and boolean bundles.
WRAPPER_FLAGS = {
    **{key: ['transport', 'network', 'address'] for key in (
        'transport', 'network', 'address', 'adapter_direct_enabled',
        'adapter_direct_protocol', 'adapter_direct_address', 'proxy_profile', 'proxy_endpoint')},
    'host': [], 'port': ['http-addr'], 'http_port': ['http-addr'],
    'path': ['graphql-path'], 'proxy_listen_addr': ['proxy-listen'],
    'source_addr': ['source-addr', 'startup-source-override', 'startup-source-override-validate'],
    'v8_classifier_mode': [], 'eebus_interface': ['eebus-interfaces'],
    'eebus_enabled': ['eebus-enabled', 'eebus-listen-port', 'eebus-interfaces', 'eebus-subnets', 'eebus-state-root', 'eebus-discovery-enabled', 'eebus-remote-ski-allowlist', 'eebus-pairing-window-mode'],
    'm2m_graphql_enabled': ['m2m-graphql-listen', 'm2m-graphql-server-name', 'm2m-graphql-server-cert', 'm2m-graphql-server-key', 'm2m-graphql-allowed-assets', 'portal-pv-semantic-enabled', 'portal-pv-m2m-url', 'portal-pv-m2m-server-name', 'portal-pv-m2m-ca', 'portal-pv-m2m-client-cert', 'portal-pv-m2m-client-key', 'portal-pv-asset-ref'],
    'm2m_graphql_server_name': ['m2m-graphql-server-name', 'portal-pv-m2m-server-name'],
    'm2m_graphql_asset_ref': ['m2m-graphql-allowed-assets', 'portal-pv-asset-ref'],
    'modbus_tcp_enabled': ['modbus-tcp-enabled', 'modbus-tcp-endpoint-file',
                           'modbus-tcp-dial-timeout', 'modbus-tcp-endpoints-file'],
    'modbus_tcp_endpoint': ['modbus-tcp-endpoint-file'],
    'modbus_tcp_endpoints': ['modbus-tcp-endpoints-file'],
    'modbus_tcp_dial_timeout': ['modbus-tcp-dial-timeout'],
}


def expected_flags(key: str, serial: dict) -> list[str]:
    if '[].' in key:
        return ['modbus-tcp-endpoints-file']
    for name in ('GROWATT_FIELDS', 'TESLA_FIELDS', 'CAN_FIELDS'):
        for option, flag, _ in serial[name]:
            if key == option:
                return [flag]
    for name in ('GROWATT_ENABLED', 'TESLA_ENABLED', 'GROWATT_CAN_ENABLED', 'GROWATT_CAN_LISTEN_ONLY'):
        if key == serial[name][0]:
            return [serial[name][1]]
    match = re.fullmatch(r'growatt_bms_(pcs|link)_can_(.+)', key)
    if match:
        family, suffix = match.groups()
        suffix = suffix.replace('_', '-')
        if suffix not in (*serial['PROJECT_SUFFIXES'], serial['PROJECT_EXTRA'][family]):
            raise ValueError('No helper consumer: ' + key)
        return [f'growatt-bms-{family}-can-{suffix}']
    if key.startswith(('growatt_', 'tesla_')):
        raise ValueError('No helper consumer: ' + key)
    return WRAPPER_FLAGS.get(key, [key.replace('_', '-')])


def expected_kind(key: str) -> str:
    if '[].' in key:
        return 'document-member'
    if key.startswith(('growatt_', 'tesla_')):
        return 'helper-derived'
    if key == 'host':
        return 'wrapper-only'
    if key == 'v8_classifier_mode':
        return 'environment'
    if key in ('modbus_tcp_endpoint', 'modbus_tcp_endpoints'):
        return 'protected-file'
    if key in ('proxy_listen_addr', 'source_addr') or key.startswith(('eebus_', 'modbus_tcp_', 'm2m_')):
        return 'derived'
    return 'gateway'


# Each helper-derived option is transformed by exactly one helper invocation or
# binding table; a proof borrowed from another route must be rejected.
HELPER_TRANSFORMS = (
    ('growatt_bms_rs485_', 'growatt = _family(payload, GROWATT_ENABLED, GROWATT_FIELDS)'),
    ('growatt_bms_can_', 'can = _family(payload, GROWATT_CAN_ENABLED, CAN_FIELDS)'),
    ('growatt_bms_pcs_can_', 'PROJECT_SUFFIXES = ('),
    ('growatt_bms_link_can_', 'PROJECT_SUFFIXES = ('),
    ('tesla_', 'tesla = _family(payload, TESLA_ENABLED, TESLA_FIELDS)'),
)


def expected_helper_transform(key: str) -> str | None:
    for prefix, text in HELPER_TRANSFORMS:
        if key.startswith(prefix):
            return text
    return None


# Each helper-derived option must be proven by the sink that emits its own
# flag; a consumer excerpt borrowed from another helper route is rejected.
def expected_consumer_markers(key: str, serial: dict) -> tuple[str, ...] | None:
    if re.match(r'growatt_bms_(pcs|link)_can_', key):
        return ('argv = [f"-{flag_prefix}enabled=true"]', 'f"-{flag_prefix}{suffix}"')
    if key == serial['GROWATT_CAN_LISTEN_ONLY'][0]:
        return ('f"-{GROWATT_CAN_LISTEN_ONLY[1]}=true"',)
    if not key.startswith(('growatt_', 'tesla_')):
        return None
    if key in (serial[name][0] for name in ('GROWATT_ENABLED', 'TESLA_ENABLED', 'GROWATT_CAN_ENABLED')):
        return ('argv = [f"-{enabled[1]}=true"]',)
    return ('argv.extend((f"-{flag}", converted[key]))',)


# These are the final handoff edges, independent of the per-option map. A
# helper table alone is insufficient if the wrapper stops invoking its helper.
HANDOFFS = {
    RUN: (
        'python3 "${modbus_guard}" validate',
        'python3 "${modbus_guard}" materialize',
        'modbus_tcp_enabled="${MODBUS_TCP_ENABLED}"',
        'modbus_tcp_dial_timeout="${MODBUS_TCP_DIAL_TIMEOUT}"',
        'python3 "${serial_can_guard}" argv --options "${addon_options_path}"',
        'gateway_args+=("${SERIAL_CAN_ARGS[@]}")',
        'gateway_args+=("${modbus_args[@]}")',
        'exec "${gateway_bin}" "${gateway_args[@]}"',
        '/usr/share/helianthus/serial_can_options.py',
        '/usr/share/helianthus/modbus_runtime_guard.py',
    ),
    SERIAL: ('build_args(load_options(args.options))',
             '"SERIAL_CAN_ARGS=("', 'project_argv = _project_family(payload, family)',
             'argv.extend(project_argv)', 'argv.extend(growatt_argv)',
             'argv.extend(tesla_argv)', 'argv.extend(can_argv[3:])'),
    MODBUS: ('materialize(config, args.document)',
             'body = endpoints_document(config.endpoints)'),
}


def validate(root: Path = ROOT, portal_keys: frozenset[str] = PORTAL_KEYS) -> int:
    def read(path: str) -> str:
        return (root / path).read_text(encoding='utf-8')

    config = json.loads(read('helianthus/config.json'))
    expected = inventory(config['schema'])
    translated = translation_inventory(yaml.safe_load(read('helianthus/translations/en.yaml'))['configuration'])
    mapping = json.loads(read(MAP))
    if mapping.get('format') != 1:
        raise ValueError('Unknown option map format')
    mapped = classified(mapping['options'], read(CLASSES_DOC), portal_keys)
    # Restrict row extraction to the maintained table, so a prose mention cannot
    # satisfy coverage and earlier explanatory tables may remain useful.
    table = read('helianthus/README.md').split('## Complete option inventory\n', 1)[1]
    table = re.split(r'(?m)^## ', table, maxsplit=1)[0]
    rows = re.findall(r'^\| `([^`]+)` \| (.+) \| (.+) \|$', table, re.M)
    rowkeys = [row[0] for row in rows]
    for label, keys in [('translations', translated), ('README', set(rowkeys)), ('map', set(mapped))]:
        if keys != expected:
            raise ValueError(f'{label} inventory mismatch; missing={sorted(expected - keys)}, extra={sorted(keys - expected)}')
    if len(rowkeys) != len(set(rowkeys)):
        raise ValueError('Duplicate README rows')
    sources = {path: read(path) for path in (RUN, SERIAL, MODBUS)}
    for path, fragments in HANDOFFS.items():
        for fragment in fragments:
            if fragment not in sources[path]:
                raise ValueError('Disconnected helper/argv handoff: ' + path)
    serial = literals(sources[SERIAL])
    flags = set(json.loads(read('helianthus/bom.json'))['gateway_cli_flags'])
    rowtext = {key: behavior for key, _, behavior in rows}
    for key, default, _ in rows:
        expected_default = (json.dumps(config['options'][key], ensure_ascii=False)
                            if key in config['options'] else 'not set')
        if default != expected_default.replace('|', r'\|'):
            raise ValueError('README default mismatch: ' + key)
    evidence = mapping['evidence']
    referenced = set()
    for key, stored in mapped.items():
        referenced.update([stored['read'], *stored['transforms'], stored['consumer']])
    if referenced != set(evidence):
        raise ValueError('Missing or orphan source proof')
    for key, stored in mapped.items():
        entry = {field: value for field, value in stored.items() if field not in CLASS_FIELDS}
        entry['read'] = evidence[stored['read']]
        entry['consumer'] = evidence[stored['consumer']]
        entry['transforms'] = [evidence[ref] for ref in stored['transforms']]
        required = {'kind', 'description', 'read', 'transforms', 'consumer', 'flags'}
        if set(entry) != required or not entry['description'].strip():
            raise ValueError('Incomplete mapping: ' + key)
        if entry['kind'] not in {'gateway', 'derived', 'wrapper-only', 'environment',
                                  'protected-file', 'helper-derived', 'document-member'}:
            raise ValueError('Unknown consumer kind: ' + key)
        if entry['kind'] != expected_kind(key):
            raise ValueError('Incorrect consumer kind: ' + key)
        if entry['flags'] != expected_flags(key, serial):
            raise ValueError('Incorrect option/flag binding: ' + key)
        for flag in entry['flags']:
            if flag not in flags:
                raise ValueError('Flag absent from packaged CLI contract: ' + flag)
            if '`-' + flag + '`' not in rowtext[key]:
                raise ValueError('README consumer mismatch: ' + key)
        if entry['description'] not in rowtext[key]:
            raise ValueError('README behavior mismatch: ' + key)
        needs_transform = (key in WRAPPER_FLAGS and key not in ('source_addr', 'v8_classifier_mode', 'proxy_listen_addr')) or key.startswith(('growatt_', 'tesla_', 'modbus_', 'eebus_', 'm2m_')) or key in ('graphql_path', 'subscription_path', 'mcp_path')
        if needs_transform and not entry['transforms']:
            raise ValueError('Missing transformation proof: ' + key)
        if key == 'host' and entry['kind'] != 'wrapper-only':
            raise ValueError('Host is a logging consumer only')
        if key == 'v8_classifier_mode' and entry['kind'] != 'environment':
            raise ValueError('Classifier uses environment')
        if key in ('modbus_tcp_endpoint', 'modbus_tcp_endpoints') and entry['kind'] != 'protected-file':
            raise ValueError('Endpoint uses a protected file')
        helper_text = expected_helper_transform(key)
        if helper_text is not None:
            transform_texts = [item['text'] for item in entry['transforms']]
            if len(transform_texts) != 1 or not transform_texts[0].lstrip().startswith(helper_text):
                raise ValueError('Transformation proof from another route: ' + key)
        excerpts = [entry['read'], *entry['transforms'], entry['consumer']]
        for excerpt in excerpts:
            if set(excerpt) != {'file', 'text'} or excerpt['file'] not in sources:
                raise ValueError('Invalid source path: ' + key)
            if not excerpt['text'].strip() or excerpt['text'] not in sources[excerpt['file']]:
                raise ValueError('Missing source evidence: ' + key)
        read_evidence = entry['read']
        if key.startswith(('growatt_', 'tesla_')):
            if read_evidence['file'] != SERIAL or entry['consumer']['file'] != SERIAL:
                raise ValueError('Invalid helper route: ' + key)
            if re.match(r'growatt_bms_(pcs|link)_can_', key):
                if 'payload.get(prefix + suffix.replace' not in read_evidence['text']:
                    raise ValueError('Missing generated config read: ' + key)
            elif '"' + key + '"' not in read_evidence['text']:
                raise ValueError('Missing helper table read: ' + key)
            markers = expected_consumer_markers(key, serial)
            if markers is None or any(m not in entry['consumer']['text'] for m in markers):
                raise ValueError('Consumer proof from another route: ' + key)
        elif key.startswith('modbus_'):
            if read_evidence['file'] != MODBUS:
                raise ValueError('Invalid Modbus read route: ' + key)
            member = key.split('[].')[-1]
            if '[].' not in key:
                needle = 'payload.get("' + key + '"'
            elif member.startswith('pacing_'):
                needle = '("' + member + '",'
            else:
                needle = 'raw["' + member + '"]'
            if needle not in read_evidence['text']:
                raise ValueError('Missing protected config read: ' + key)
        else:
            needle = ('.' + key + ' //' if key.startswith('m2m_') else "bashio::config '" + key + "'")
            if read_evidence['file'] != RUN or needle not in read_evidence['text']:
                raise ValueError('Missing wrapper config read: ' + key)
        # Literal wrapper routes must show a real emitted flag, rather than a
        # support probe or log mentioning its name. Helper flags are proven by
        # their tuple tables / prefix construction above and generic argv loop.
        if entry['consumer']['file'] == RUN:
            for flag in entry['flags']:
                if not re.search(r'(?m)(?:^|[\s(])-' + re.escape(flag) + r'(?:[=\s])', '\n'.join(excerpt['text'] for excerpt in excerpts[1:])):
                    raise ValueError('Missing flag emission: ' + key)
    return len(expected)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--portal-docs', type=Path,
                        help='gateway docs directory; derive Portal keys from its configuration contract')
    args = parser.parse_args(argv)
    try:
        keys = PORTAL_KEYS if args.portal_docs is None else portal_keys_from_docs(args.portal_docs)
        if keys != PORTAL_KEYS:
            raise ValueError('Portal keys differ from the gateway contract')
        count = validate(portal_keys=keys)
    except (ValueError, KeyError, IndexError, TypeError, OSError, yaml.YAMLError) as error:
        print('FAIL:', error, file=sys.stderr)
        return 1
    print(f'PASS: {count} option paths have English translations, README rows, source-backed consumers'
          ' and a bootstrap or Portal class')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
