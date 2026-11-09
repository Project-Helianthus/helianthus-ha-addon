#!/usr/bin/env python3
"""Offline, source-backed inventory of Supervisor options and their consumers.

This validates packaging wiring, not native support or hardware qualification.
The schema, shipped reads, helper binding tables and BOM are independent inputs.
"""
from __future__ import annotations

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


def validate(root: Path = ROOT) -> int:
    def read(path: str) -> str:
        return (root / path).read_text(encoding='utf-8')

    config = json.loads(read('helianthus/config.json'))
    expected = inventory(config['schema'])
    translated = translation_inventory(yaml.safe_load(read('helianthus/translations/en.yaml'))['configuration'])
    mapping = json.loads(read(MAP))
    if mapping.get('format') != 1:
        raise ValueError('Unknown option map format')
    mapped = mapping['options']
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
        entry = dict(stored)
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


def main() -> int:
    try:
        count = validate()
    except (ValueError, KeyError, IndexError, TypeError, OSError, yaml.YAMLError) as error:
        print('FAIL:', error, file=sys.stderr)
        return 1
    print(f'PASS: {count} option paths have English translations, README rows and source-backed consumers')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
