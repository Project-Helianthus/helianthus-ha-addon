#!/usr/bin/env python3
"""Validate a local declaration of tested immutable image promotion sources."""
import argparse
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
DIGEST = re.compile(r"[a-z0-9]+(?:[._-][a-z0-9]+)*(?:/[a-z0-9]+(?:[._-][a-z0-9]+)*)+@sha256:[0-9a-f]{64}")
VERSION = re.compile(r"v?(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(?:[-+][0-9A-Za-z.-]+)?")


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
    if not isinstance(value, str) or not DIGEST.fullmatch(value) or not value.startswith(image + '@'):
        raise ValueError('source must be an immutable digest for the declared image')
    return value


def validate(record, config):
    fields(record, ('architectures', 'candidate', 'cohort', 'target', 'sources', 'tests', 'aggregate', 'index'))
    fields(config, config.keys())
    image, declared = config.get('image'), config.get('arch')
    if not isinstance(image, str) or not isinstance(declared, list) or not declared or any(not isinstance(x, str) or not x for x in declared) or len(set(declared)) != len(declared):
        raise ValueError('invalid packaging declaration')
    arches = record['architectures']
    if not isinstance(arches, list) or any(not isinstance(x, str) for x in arches) or len(arches) != len(set(arches)) or set(arches) != set(declared):
        raise ValueError('architectures differ from packaging')
    candidate = record['candidate']
    if not isinstance(candidate, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,127}', candidate):
        raise ValueError('invalid candidate identity')
    release = record['cohort']
    if cohort(release) != cohort(config.get('version')):
        raise ValueError('release cohort differs from packaging')
    target = record['target']
    if not isinstance(target, str) or not target.startswith(image + ':') or cohort(target[len(image) + 1:]) != cohort(release):
        raise ValueError('invalid target or release cohort')
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
    aggregate = fields(record['aggregate'], ('candidate', 'cohort', 'verdict', 'subjects', 'index_subject'))
    if aggregate['candidate'] != candidate or aggregate['cohort'] != release or aggregate['verdict'] != 'pass':
        raise ValueError('aggregate identity or verdict mismatch')
    subjects = aggregate['subjects']
    if not isinstance(subjects, list) or any(not isinstance(x, str) for x in subjects) or len(subjects) != len(set(subjects)) or set(subjects) != set(collections[0].values()):
        raise ValueError('aggregate subjects mismatch')
    index = record['index']
    if index is not None:
        fields(index, ('subject', 'candidate', 'cohort', 'verdict'))
        subject(index['subject'], image)
        if index['candidate'] != candidate or index['cohort'] != release or index['verdict'] != 'pass' or index['subject'] != aggregate['index_subject'] or index['subject'] in subjects:
            raise ValueError('index evidence mismatch')
    elif aggregate['index_subject'] is not None:
        raise ValueError('missing index evidence')
    return {'target': target, 'sources': [{'architecture': a, 'subject': collections[0][a]} for a in sorted(declared)], 'index_subject': index['subject'] if index else None}


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate JSON key')
        result[key] = value
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('record', type=Path, help='local JSON evidence declaration')
    parser.add_argument('--config', type=Path, default=ROOT / 'helianthus/config.json')
    args = parser.parse_args()
    try:
        record = json.loads(args.record.read_text(), object_pairs_hook=unique_object)
        config = json.loads(args.config.read_text(), object_pairs_hook=unique_object)
        print(json.dumps(validate(record, config), indent=2, sort_keys=True))
    except (OSError, ValueError, TypeError) as exc:
        print(f'invalid promotion plan: {exc}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
