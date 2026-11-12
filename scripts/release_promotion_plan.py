#!/usr/bin/env python3
"""Validate a local declaration of tested immutable image promotion sources."""
import argparse
import json
from pathlib import Path
import re
import sys
import subprocess


ROOT = Path(__file__).resolve().parents[1]
DIGEST = re.compile(r'[0-9a-f]{64}')
PRERELEASE_IDENTIFIER = r'(?:0|[1-9][0-9]*|[0-9]*[A-Za-z-][0-9A-Za-z-]*)'
VERSION = re.compile(
    r'v?(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)'
    rf'(?:-{PRERELEASE_IDENTIFIER}(?:\.{PRERELEASE_IDENTIFIER})*)?'
    r'(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?'
)
TAG = re.compile(r'[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}')
REPOSITORY_COMPONENT = r'[a-z0-9]+(?:(?:[._]|__|-+)[a-z0-9]+)*'
REGISTRY = r'[A-Za-z0-9]+(?:[.-][A-Za-z0-9]+)*(?::[0-9]+)?'
REPOSITORY = re.compile(
    rf'(?:{REGISTRY}/)?{REPOSITORY_COMPONENT}(?:/{REPOSITORY_COMPONENT})*'
)


def fields(value, keys):
    if not isinstance(value, dict) or set(value) != set(keys):
        raise ValueError('missing or unknown record fields')
    return value


def cohort(version):
    match = VERSION.fullmatch(version) if isinstance(version, str) else None
    if not match:
        raise ValueError('invalid release version')
    return match.group(1, 2)


def subject(value, image):
    if not isinstance(value, str) or not value.startswith(image + '@sha256:') or not DIGEST.fullmatch(value[len(image) + len('@sha256:'):]):
        raise ValueError('source must be an immutable digest for the declared image')
    return value


def published_architectures(workflow):
    import yaml
    try:
        build = yaml.safe_load(workflow.read_text())
        matrix = build['jobs']['build']['strategy']['matrix']
        if set(matrix) != {'include'}:
            raise ValueError('unsupported build matrix')
        declared = [entry['arch'] for entry in matrix['include']]
    except (KeyError, TypeError, yaml.YAMLError) as exc:
        raise ValueError('invalid build architecture declaration') from exc
    if not declared or any(not isinstance(x, str) or not x for x in declared) or len(set(declared)) != len(declared):
        raise ValueError('invalid build architecture declaration')
    return declared


def validate_identity(record, config, declared):
    fields(record, ('architectures', 'candidate', 'cohort', 'target', 'sources', 'tests', 'aggregate', 'index'))
    fields(config, config.keys())
    image = config.get('image')
    if not isinstance(image, str) or not REPOSITORY.fullmatch(image):
        raise ValueError('invalid packaging image repository')
    arches = record['architectures']
    if not isinstance(arches, list) or any(not isinstance(x, str) for x in arches) or len(arches) != len(set(arches)) or set(arches) != set(declared):
        raise ValueError('architectures differ from build workflow')
    candidate = record['candidate']
    if not isinstance(candidate, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,127}', candidate):
        raise ValueError('invalid candidate identity')
    release = record['cohort']
    cohort(release)
    cohort(config.get('version'))
    if release != config['version']:
        raise ValueError('release version differs from packaging')
    target = record['target']
    if not isinstance(target, str) or not target.startswith(image + ':'):
        raise ValueError('invalid target image')
    tag = target[len(image) + 1:]
    if not TAG.fullmatch(tag):
        raise ValueError('invalid target tag')
    cohort(tag)
    if tag != config['version']:
        raise ValueError('target release version differs from packaging')
    return image, candidate, release, target


def validate_subjects(record, image, declared, candidate, release):
    collections = []
    for key, keys in [('sources', ('architecture', 'subject', 'candidate', 'cohort')), ('tests', ('architecture', 'subject', 'candidate', 'cohort', 'verdict'))]:
        entries = record[key]
        if not isinstance(entries, list):
            raise ValueError('expected a record list')
        by_arch = {}
        for item in entries:
            fields(item, keys)
            arch = item['architecture']
            if not isinstance(arch, str) or arch not in declared or arch in by_arch:
                raise ValueError('extra or duplicate architecture')
            subject(item['subject'], image)
            if item['candidate'] != candidate or item['cohort'] != release or (key == 'tests' and item['verdict'] != 'pass'):
                raise ValueError('identity, cohort or verdict mismatch')
            by_arch[arch] = item['subject']
        if set(by_arch) != set(declared):
            raise ValueError('missing architecture')
        collections.append(by_arch)
    if collections[0] != collections[1] or len(set(collections[0].values())) != len(declared):
        raise ValueError('tested subjects differ or are ambiguous')
    return collections[0]


def validate_index(record, image, candidate, release, sources):
    aggregate = fields(record['aggregate'], ('candidate', 'cohort', 'verdict', 'subjects', 'index_subject'))
    if aggregate['candidate'] != candidate or aggregate['cohort'] != release or aggregate['verdict'] != 'pass':
        raise ValueError('aggregate identity or verdict mismatch')
    subjects = aggregate['subjects']
    if not isinstance(subjects, list) or any(not isinstance(x, str) for x in subjects) or len(subjects) != len(set(subjects)) or set(subjects) != set(sources.values()):
        raise ValueError('aggregate subjects mismatch')
    index = record['index']
    if index is not None:
        fields(index, ('subject', 'candidate', 'cohort', 'verdict'))
        subject(index['subject'], image)
        if index['candidate'] != candidate or index['cohort'] != release or index['verdict'] != 'pass' or index['subject'] != aggregate['index_subject'] or index['subject'] in subjects:
            raise ValueError('index evidence mismatch')
    elif aggregate['index_subject'] is not None:
        raise ValueError('missing index evidence')
    return index['subject'] if index else None


def validate(record, config, workflow=ROOT / '.github/workflows/build.yml'):
    declared = published_architectures(workflow)
    image, candidate, release, target = validate_identity(record, config, declared)
    sources = validate_subjects(record, image, declared, candidate, release)
    index = validate_index(record, image, candidate, release, sources)
    return {'target': target, 'sources': [{'architecture': a, 'subject': sources[a]} for a in sorted(declared)], 'index_subject': index}


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate JSON key')
        result[key] = value
    return result


def promotion_identity(record, config, release_tag, candidate):
    fields(record, ('version', 'image', 'candidate', 'digest'))
    version = config['version']
    image = config['image']
    if (not isinstance(image, str) or not REPOSITORY.fullmatch(image)
            or not TAG.fullmatch(version) or not VERSION.fullmatch(version)
            or release_tag != 'v' + version or record['version'] != version
            or record['image'] != image or record['candidate'] != candidate
            or not re.fullmatch(r'candidate-[0-9]+-[0-9]+', candidate)):
        raise ValueError('candidate packaging or release identity mismatch')
    digest = record['digest']
    if not isinstance(digest, str) or not re.fullmatch(r'sha256:[0-9a-f]{64}', digest):
        raise ValueError('invalid candidate digest')
    return image, version, digest


def publish(record, config, release_tag, candidate, run=subprocess.run):
    image, version, digest = promotion_identity(record, config, release_tag, candidate)

    def docker(*args):
        return run(['docker', 'buildx', 'imagetools', *args],
                   capture_output=True, text=True, timeout=120)

    def inspect(reference):
        result = docker('inspect', reference, '--format', '{{json .Manifest}}')
        if result.returncode:
            raise ValueError('cannot inspect immutable candidate')
        return json.loads(result.stdout)['digest']

    source = image + '@' + digest
    if inspect(source) != digest:
        raise ValueError('candidate digest mismatch')
    target = image + ':' + version
    existing = docker('inspect', target)
    if existing.returncode == 0:
        raise ValueError('version tag already exists')
    # Only an explicit registry absence permits a publication attempt.
    if 'manifest unknown' not in existing.stderr.lower():
        raise ValueError('cannot establish version tag absence')
    for tag in (version, 'latest'):
        result = docker('create', '--prefer-index=false', '-t', image + ':' + tag, source)
        if result.returncode:
            raise ValueError('promotion failed')
        if inspect(image + ':' + tag) != digest:
            raise ValueError('promoted digest mismatch')
    return {'version': version, 'digest': digest, 'source': source}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('record', type=Path, help='local JSON evidence declaration')
    parser.add_argument('--publish', action='store_true')
    parser.add_argument('--release-tag')
    parser.add_argument('--candidate')
    parser.add_argument('--config', type=Path, default=ROOT / 'helianthus/config.json')
    args = parser.parse_args()
    try:
        record = json.loads(args.record.read_text(), object_pairs_hook=unique_object)
        config = json.loads(args.config.read_text(), object_pairs_hook=unique_object)
        if args.publish:
            result = publish(record, config, args.release_tag, args.candidate)
            import os
            with open(os.environ['GITHUB_STEP_SUMMARY'], 'a') as summary:
                summary.write(f"Promoted {result['version']} and latest from {result['source']}\n")
        else:
            result = validate(record, config)
        print(json.dumps(result, indent=2, sort_keys=True))
    except (OSError, ValueError, TypeError) as exc:
        print(f'invalid promotion plan: {exc}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
