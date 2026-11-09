"""Synthetic mutations of each inventory identity and each source proof field.

Option identity fields: top-level key and nested member key (including optional
schema-only keys). Each is varied independently by deleting its translation,
README row and map entry; adding a schema key proves new consumers cannot hide.
Mapping fields: kind, description, read.file, read.text, transforms,
consumer.file, consumer.text and flags. Independent mutations catch invalid
classification, undocumented behavior, redirected/deleted config reads, missing
transformation evidence, redirected/deleted sinks and renamed/swapped CLI flags.
Source mutations independently remove each recorded read and emission; these
catch production reads or derived argument construction drifting from the map.
"""
import importlib.util
import json
import re
import shutil
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('addon_options', ROOT / 'scripts/check_addon_options.py')
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)
MAP = json.loads((ROOT / guard.MAP).read_text())
KEYS = list(MAP['options'])


@pytest.fixture
def tree(tmp_path):
    for path in (guard.RUN, guard.SERIAL, guard.MODBUS, guard.MAP,
                 'helianthus/config.json', 'helianthus/bom.json',
                 'helianthus/translations/en.yaml', 'helianthus/README.md'):
        target = tmp_path / path
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / path, target)
    return tmp_path


def write_map(tree, mapping):
    (tree / guard.MAP).write_text(json.dumps(mapping))


def read_map(tree):
    return json.loads((tree / guard.MAP).read_text())


def reject(tree):
    with pytest.raises((ValueError, KeyError, IndexError)):
        guard.validate(tree)


def test_complete_inventory(tree):
    assert guard.validate(tree) == len(KEYS)
    config = json.loads((tree / 'helianthus/config.json').read_text())
    assert set(config['options']) <= set(config['schema'])


@pytest.mark.parametrize('key', KEYS)
@pytest.mark.parametrize('surface', ['translation', 'readme', 'map'])
def test_missing_option_on_each_surface(tree, key, surface):
    if surface == 'translation':
        path = tree / 'helianthus/translations/en.yaml'
        value = yaml.safe_load(path.read_text())
        top, _, nested = key.partition('[].')
        target = value['configuration'] if not nested else value['configuration'][top]['fields']
        del target[nested or top]
        path.write_text(yaml.safe_dump(value))
    elif surface == 'readme':
        path = tree / 'helianthus/README.md'
        text = path.read_text()
        before, table = text.split('## Complete option inventory\n', 1)
        table = re.sub(r'^\| `' + re.escape(key) + r'` \|.*\n', '', table, flags=re.M)
        path.write_text(before + '## Complete option inventory\n' + table)
    else:
        value = read_map(tree)
        del value['options'][key]
        write_map(tree, value)
    reject(tree)


@pytest.mark.parametrize('surface', ['translation', 'readme', 'map'])
def test_extra_orphan_entry(tree, surface):
    if surface == 'translation':
        p = tree / 'helianthus/translations/en.yaml'
        value = yaml.safe_load(p.read_text())
        value['configuration']['synthetic_orphan'] = {'name': 'Orphan', 'description': 'Synthetic option'}
        p.write_text(yaml.safe_dump(value))
    elif surface == 'readme':
        p = tree / 'helianthus/README.md'
        p.write_text(p.read_text() + '| `synthetic_orphan` | not set | Synthetic option |\n')
    else:
        value = read_map(tree)
        value['options']['synthetic_orphan'] = value['options']['broadcast']
        write_map(tree, value)
    reject(tree)


@pytest.mark.parametrize('nested', [False, True])
def test_new_schema_option_requires_all_surfaces(tree, nested):
    p = tree / 'helianthus/config.json'
    value = json.loads(p.read_text())
    target = value['schema']['modbus_tcp_endpoints'][0] if nested else value['schema']
    target['synthetic_new_option'] = 'str?'
    p.write_text(json.dumps(value))
    reject(tree)


@pytest.mark.parametrize('key', KEYS)
@pytest.mark.parametrize('field', ['name', 'description'])
def test_english_fields_required(tree, key, field):
    p = tree / 'helianthus/translations/en.yaml'
    value = yaml.safe_load(p.read_text())
    top, _, nested = key.partition('[].')
    entry = value['configuration'][top]
    if nested:
        entry = entry['fields'][nested]
    entry[field] = ' '
    p.write_text(yaml.safe_dump(value))
    reject(tree)


@pytest.mark.parametrize('key', KEYS)
@pytest.mark.parametrize('field', ['kind', 'description', 'read.file', 'read.text',
                                   'consumer.file', 'consumer.text', 'flags'])
def test_each_mapping_field_is_checked(tree, key, field):
    value = read_map(tree)
    entry = value['options'][key]
    if '.' in field:
        parent, member = field.split('.')
        value['evidence'][entry[parent]][member] = 'synthetic_missing'
    elif field == 'flags':
        entry[field] = ['synthetic-nonexistent-flag']
    else:
        entry[field] = 'synthetic_invalid'
    write_map(tree, value)
    reject(tree)


@pytest.mark.parametrize('key', KEYS)
@pytest.mark.parametrize('proof', ['read', 'consumer'])
def test_production_read_and_sink_mutations(tree, key, proof):
    evidence = MAP['evidence'][MAP['options'][key][proof]]
    path = tree / evidence['file']
    original = path.read_text()
    assert evidence['text'] in original
    text = evidence['text']
    if proof == 'consumer' and 'argv.extend((f"-{flag}", converted[key]))' in text:
        mutated = text.replace('f"-{flag}"', 'f"-synthetic-{flag}"')
    elif proof == 'consumer' and 'argv.append(f"-{GROWATT_CAN_LISTEN_ONLY[1]}=true")' in text:
        mutated = text.replace('f"-{GROWATT_CAN_LISTEN_ONLY[1]}=true"',
                               'f"-synthetic-{GROWATT_CAN_LISTEN_ONLY[1]}=true"')
    elif proof == 'consumer' and 'f"-{flag_prefix}enabled=true"' in text:
        mutated = text.replace('f"-{flag_prefix}enabled=true"', 'f"-synthetic-{flag_prefix}enabled=true"')
    elif proof == 'consumer' and 'pacing.append((member, value))' in text:
        mutated = text.replace('pacing.append((member, value))',
                               'pacing.append(("synthetic_member", value))')
    elif proof == 'consumer' and MAP['options'][key]['flags'] and evidence['file'] == guard.RUN:
        flag = next(flag for flag in MAP['options'][key]['flags'] if '-' + flag in text)
        mutated = text.replace('-' + flag, '-synthetic-' + flag)
        assert mutated != text
    else:
        # Config key / prefix / tuple bindings and non-CLI consumers.
        quote = re.search(r'[\"\']', text)
        assert quote is not None
        offset = quote.end()
        mutated = text[:offset] + 'synthetic_' + text[offset:]
    path.write_text(original.replace(text, mutated))
    reject(tree)


@pytest.mark.parametrize('key', [k for k in KEYS if MAP['options'][k]['transforms']])
def test_missing_transformation_proof(tree, key):
    value = read_map(tree)
    value['options'][key]['transforms'] = []
    write_map(tree, value)
    reject(tree)


@pytest.mark.parametrize('key', [k for k in KEYS if MAP['options'][k]['flags']])
def test_swapping_to_another_real_flag_fails(tree, key):
    value = read_map(tree)
    value['options'][key]['flags'] = ['mcp-path' if key != 'mcp_path' else 'graphql-path']
    write_map(tree, value)
    reject(tree)


def test_removed_packaged_flag_fails(tree):
    p = tree / 'helianthus/bom.json'
    value = json.loads(p.read_text())
    value['gateway_cli_flags'].remove('modbus-tcp-endpoints-file')
    p.write_text(json.dumps(value))
    reject(tree)


@pytest.mark.parametrize('path,fragment', [(path, fragment) for path, values in guard.HANDOFFS.items() for fragment in values])
def test_disconnected_helper_handoff_fails(tree, path, fragment):
    source = tree / path
    source.write_text(source.read_text().replace(fragment, 'synthetic_disconnected'))
    reject(tree)


@pytest.mark.parametrize('key', KEYS)
def test_documented_default_matches_authoritative_config(tree, key):
    path = tree / 'helianthus/README.md'
    before, table = path.read_text().split('## Complete option inventory\n', 1)
    table = re.sub(r'(^\| `' + re.escape(key) + r'` \| )[^\n]*?( \| )',
                   r'\g<1>synthetic_wrong_default\g<2>', table, flags=re.M)
    path.write_text(before + '## Complete option inventory\n' + table)
    reject(tree)


@pytest.mark.parametrize('reference', sorted({ref for entry in MAP['options'].values() for ref in entry['transforms']}))
@pytest.mark.parametrize('field', ['file', 'text'])
def test_each_transformation_evidence_field(tree, reference, field):
    value = read_map(tree)
    value['evidence'][reference][field] = 'synthetic_missing_transformation'
    write_map(tree, value)
    reject(tree)
