import copy
import hashlib
import importlib.util
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location('promotion', Path(__file__).resolve().parents[1] / 'scripts/release_promotion_plan.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def fixture(image='example.org/project/image'):
    def digest(text):
        return image + '@sha256:' + hashlib.sha256(text.encode()).hexdigest()

    config = {'image': image, 'arch': ['aarch64', 'amd64'], 'version': '0.7.1'}
    sources = [{'architecture': a, 'subject': digest(a), 'candidate': 'candidate-1', 'cohort': '0.7.1'} for a in module.published_architectures(module.ROOT / '.github/workflows/build.yml')]
    tests = [dict(x, verdict='pass') for x in sources]
    index = {'subject': digest('index'), 'candidate': 'candidate-1', 'cohort': '0.7.1', 'verdict': 'pass'}
    aggregate = {'candidate': 'candidate-1', 'cohort': '0.7.1', 'verdict': 'pass', 'subjects': [x['subject'] for x in sources], 'index_subject': index['subject']}
    return config, {'architectures': [x['architecture'] for x in sources], 'candidate': 'candidate-1', 'cohort': '0.7.1', 'target': image + ':0.7.1', 'sources': sources, 'tests': tests, 'aggregate': aggregate, 'index': index}


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
    config['version'] = record['cohort'] = tag
    for entry in record['sources'] + record['tests'] + [record['aggregate'], record['index']]:
        entry['cohort'] = tag
    record['target'] = config['image'] + ':' + tag
    with pytest.raises(ValueError, match='invalid target tag'):
        module.validate(record, config)


@pytest.mark.parametrize('tag', ['0.7.1', 'v0.7.1-rc.1', '0.7.1-' + 'a' * 122])
def test_valid_container_tags_accepted(tag):
    config, record = fixture()
    config['version'] = record['cohort'] = tag
    for entry in record['sources'] + record['tests'] + [record['aggregate'], record['index']]:
        entry['cohort'] = tag
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
            if change == 'missing':
                record[section].pop()
            if change == 'duplicate':
                record[section].append(copy.deepcopy(record[section][0]))
            if change == 'stale':
                record[section][0]['subject'] = record[section][1]['subject']
            if change == 'field':
                del record[section][0]['candidate']
            with pytest.raises(ValueError):
                module.validate(record, config)


def test_index_optional_only_with_explicit_null():
    config, record = fixture()
    record['index'] = record['aggregate']['index_subject'] = None
    assert module.validate(record, config)['index_subject'] is None
    del record['aggregate']['index_subject']
    with pytest.raises(ValueError):
        module.validate(record, config)


def test_supervisor_subset_cannot_omit_published_architectures():
    config, record = fixture()
    assert set(record['architectures']) == {'amd64', 'aarch64', 'armv7', 'armhf', 'i386'}
    record['architectures'] = config['arch'][:]
    for key in ('sources', 'tests'):
        record[key] = [entry for entry in record[key] if entry['architecture'] in config['arch']]
    record['aggregate']['subjects'] = [entry['subject'] for entry in record['sources']]
    with pytest.raises(ValueError, match='architectures differ from build workflow'):
        module.validate(record, config)


def test_architectures_are_read_from_workflow(tmp_path):
    config, record = fixture()
    workflow = tmp_path / 'build.yml'
    workflow.write_text('jobs: {build: {strategy: {matrix: {include: [{arch: extra}]}}}}')
    with pytest.raises(ValueError, match='architectures differ from build workflow'):
        module.validate(record, config, workflow)


@pytest.mark.parametrize('field', ['cohort', 'target'])
def test_patch_relabel_rejected(field):
    config, record = fixture()
    config['version'] = '0.6.58'
    record['cohort'] = '0.6.58'
    for entry in record['sources'] + record['tests'] + [record['aggregate'], record['index']]:
        entry['cohort'] = '0.6.58'
    record['target'] = config['image'] + ':0.6.58'
    if field == 'cohort':
        record['cohort'] = '0.6.1'
        for entry in record['sources'] + record['tests'] + [record['aggregate'], record['index']]:
            entry['cohort'] = '0.6.1'
    else:
        record['target'] = config['image'] + ':0.6.999'
    with pytest.raises(ValueError, match='release version differs from packaging'):
        module.validate(record, config)


@pytest.mark.parametrize('image', [
    'example.org/team/app:old',
    'registry.example:5000/team/app:old',
    'app:old',
    'example.org/team/app@sha256:' + 'a' * 64,
    'registry.example:5000/team/app@sha256:' + 'a' * 64,
    '', None, 123, 'https://example.org/team/app',
    'example.org/team//app', 'example.org/team/app/',
    'example.org/team/App', 'example.org/team/app name',
    'registry.example:port/team/app',
])
def test_invalid_configured_image_rejected(image):
    # Build matching references too: prefix agreement alone must not suffice.
    config, record = fixture(image if isinstance(image, str) else 'app')
    config['image'] = image
    with pytest.raises(ValueError, match='invalid packaging image repository'):
        module.validate(record, config)


@pytest.mark.parametrize('image', [
    'app', 'team/app', 'example.org/team/app',
    'registry.example:5000/team/app', 'localhost:5000/app',
    'example.org/team/app_name.part--suffix',
])
def test_unqualified_configured_image_accepted(image):
    config, record = fixture(image)
    assert module.validate(record, config)['target'] == image + ':0.7.1'


def test_registry_port_in_subjects():
    config, record = fixture()
    old_image = config['image']
    config['image'] = 'registry.example:5000/team/image'
    record['target'] = config['image'] + ':0.7.1'
    for entry in record['sources'] + record['tests'] + [record['index']]:
        entry['subject'] = entry['subject'].replace(old_image, config['image'])
    record['aggregate']['subjects'] = [entry['subject'] for entry in record['sources']]
    record['aggregate']['index_subject'] = record['index']['subject']
    assert module.validate(record, config)['target'] == record['target']


@pytest.mark.parametrize('suffix', ['@sha256:' + 'a' * 63, '@sha256:' + 'a' * 65,
                                     '@sha256:' + 'A' * 64, '@sha512:' + 'a' * 64,
                                     '/other@sha256:' + 'a' * 64, ':tag@sha256:' + 'a' * 64])
def test_subject_requires_exact_prefix_and_digest(suffix):
    config, record = fixture()
    record['sources'][0]['subject'] = config['image'] + suffix
    with pytest.raises(ValueError, match='immutable digest'):
        module.validate(record, config)


@pytest.mark.parametrize('declaration', [
    'jobs: {}',
    'jobs: {build: {strategy: {matrix: {include: []}}}}',
    'jobs: {build: {strategy: {matrix: {include: [{arch: amd64}, {arch: amd64}]}}}}',
    'jobs: {build: {strategy: {matrix: {include: [{arch: 1}]}}}}',
    'jobs: {build: {strategy: {matrix: {include: [{arch: amd64}], exclude: []}}}}',
    'jobs: [',
])
def test_invalid_workflow_fails_closed(tmp_path, declaration):
    config, record = fixture()
    workflow = tmp_path / 'build.yml'
    workflow.write_text(declaration)
    with pytest.raises(ValueError):
        module.validate(record, config, workflow)
