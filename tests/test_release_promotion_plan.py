import copy
import hashlib
import importlib.util
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location('promotion', Path(__file__).resolve().parents[1] / 'scripts/release_promotion_plan.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def fixture():
    image = 'example.org/project/image'
    digest = lambda text: image + '@sha256:' + hashlib.sha256(text.encode()).hexdigest()
    config = {'image': image, 'arch': ['arm', 'amd'], 'version': '0.7.1'}
    sources = [{'architecture': a, 'subject': digest(a), 'candidate': 'candidate-1', 'cohort': '0.7.1'} for a in config['arch']]
    tests = [dict(x, verdict='pass') for x in sources]
    index = {'subject': digest('index'), 'candidate': 'candidate-1', 'cohort': '0.7.1', 'verdict': 'pass'}
    aggregate = {'candidate': 'candidate-1', 'cohort': '0.7.1', 'verdict': 'pass', 'subjects': [x['subject'] for x in sources], 'index_subject': index['subject']}
    return config, {'architectures': config['arch'][:], 'candidate': 'candidate-1', 'cohort': '0.7.1', 'target': image + ':0.7.1', 'sources': sources, 'tests': tests, 'aggregate': aggregate, 'index': index}


def test_order_and_environment(monkeypatch):
    config, record = fixture()
    expected = module.validate(record, config)
    monkeypatch.setenv('RELEASE_TARGET', 'unexpected')
    for key in ('architectures', 'sources', 'tests'):
        record[key].reverse()
    record['aggregate']['subjects'].reverse()
    assert module.validate(record, config) == expected


@pytest.mark.parametrize('tag', ['0.7.1+build', '0.7.1-' + 'a' * 123, '0.7.1-' + 'a' * 130])
def test_invalid_container_tags_rejected(tag):
    config, record = fixture()
    record['target'] = config['image'] + ':' + tag
    with pytest.raises(ValueError, match='invalid target tag'):
        module.validate(record, config)


@pytest.mark.parametrize('tag', ['0.7.1', 'v0.7.1-rc.1', '0.7.1-' + 'a' * 122])
def test_valid_container_tags_accepted(tag):
    config, record = fixture()
    record['target'] = config['image'] + ':' + tag
    assert module.validate(record, config)['target'] == record['target']


@pytest.mark.parametrize('version', [
    '0.7.1-', '0.7.1-rc.', '0.7.1-.rc', '0.7.1-rc..1', '0.7.1-01',
    '0.7.1+', '0.7.1+build.', '0.7.1+.build', '0.7.1+build..1',
    '0.7.1-rc.1+', '0.7.1-rc..1+build', '0.7.1-rc.1+build..1',
])
@pytest.mark.parametrize('field', ['target', 'cohort', 'config'])
def test_invalid_release_versions_rejected(version, field):
    config, record = fixture()
    if field == 'target':
        record['target'] = config['image'] + ':' + version
    elif field == 'cohort':
        record['cohort'] = version
    else:
        config['version'] = version
    with pytest.raises(ValueError, match='invalid (release version|target tag)'):
        module.validate(record, config)


@pytest.mark.parametrize('version', [
    '0.7.1', 'v0.7.1-rc.1', '0.7.1-0', '0.7.1-0a',
    '0.7.1+build.01', '0.7.1-rc.1+build.01',
])
def test_valid_release_versions_accepted(version):
    assert module.cohort(version) == ('0', '7')


@pytest.mark.parametrize('section,key,value', [
    ('sources', 'architecture', 'other'), ('sources', 'subject', 'example.org/project/image:latest'),
    ('sources', 'candidate', 'other'), ('sources', 'cohort', '0.8.0'),
    ('tests', 'architecture', 'other'), ('tests', 'subject', 'example.org/project/image:latest'),
    ('tests', 'candidate', 'other'), ('tests', 'cohort', '0.8.0'), ('tests', 'verdict', 'unknown'),
    ('aggregate', 'candidate', 'other'), ('aggregate', 'cohort', '0.8.0'),
    ('aggregate', 'verdict', 'unknown'), ('aggregate', 'subjects', []), ('aggregate', 'index_subject', None),
    ('index', 'subject', 'example.org/project/image:latest'), ('index', 'candidate', 'other'),
    ('index', 'cohort', '0.8.0'), ('index', 'verdict', 'unknown'),
])
def test_identity_fields_rejected(section, key, value):
    config, record = fixture()
    obj = record[section][0] if isinstance(record[section], list) else record[section]
    obj[key] = value
    with pytest.raises(ValueError):
        module.validate(record, config)


@pytest.mark.parametrize('key,value', [('architectures', ['arm']), ('candidate', ''), ('cohort', '0.8.0'), ('target', 'example.org/project/image:0.8.0'), ('index', None)])
def test_top_level_identity_rejected(key, value):
    config, record = fixture()
    record[key] = value
    with pytest.raises(ValueError):
        module.validate(record, config)


def test_missing_duplicate_and_stale():
    config, original = fixture()
    for section in ('sources', 'tests'):
        for change in ('missing', 'duplicate', 'stale', 'field'):
            record = copy.deepcopy(original)
            if change == 'missing': record[section].pop()
            if change == 'duplicate': record[section].append(copy.deepcopy(record[section][0]))
            if change == 'stale': record[section][0]['subject'] = record[section][1]['subject']
            if change == 'field': del record[section][0]['candidate']
            with pytest.raises(ValueError): module.validate(record, config)


def test_index_optional_only_with_explicit_null():
    config, record = fixture()
    record['index'] = record['aggregate']['index_subject'] = None
    assert module.validate(record, config)['index_subject'] is None
    del record['aggregate']['index_subject']
    with pytest.raises(ValueError): module.validate(record, config)
