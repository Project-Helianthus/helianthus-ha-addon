#!/usr/bin/env python3
"""Offline comparisons of operator-supplied controlled build evidence."""
import argparse
import ast
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import subprocess


class Unverified(ValueError):
    """Required evidence is absent, ambiguous or inconsistent."""


def require(condition):
    if not condition:
        raise Unverified('evidence rejected')


def fingerprint(data):
    return hashlib.sha256(data).hexdigest()


def inspect_go(path):
    """Inspect only; never execute the supplied binary or build its sources."""
    env = dict(os.environ, GOPROXY='off', GOSUMDB='off', GOTOOLCHAIN='local',
               GOENV='off', GOWORK='off')
    def run(args):
        return subprocess.run(['go', *args, str(path)], check=True,
                              capture_output=True, text=True, timeout=20,
                              env=env).stdout
    require(run(['tool', 'buildid']).strip() == '')
    lines = run(['version', '-m']).splitlines()
    require(bool(lines))
    toolchain = lines[0].rsplit(': ', 1)[-1]
    settings = {}
    deps = []
    for line in lines[1:]:
        fields = line.strip().split('\t')
        if fields[0] == 'build':
            key, value = fields[1].split('=', 1)
            require(key not in settings)
            settings[key] = json.loads(value) if value.startswith(chr(34)) else value
        elif fields[0] in {'dep', 'mod', 'path', '=>'}:
            deps.append(fields)
        else:
            raise Unverified('unknown build metadata')
    return {'toolchain': toolchain, 'settings': settings, 'dependencies': deps}


def load_tree(root):
    root = Path(root)
    require(root.is_dir() and not root.is_symlink())
    manifest = json.loads((root / 'evidence.json').read_text())
    require(set(manifest) == {'version', 'files', 'builds'})
    require(manifest['version'] == 1 and bool(manifest['files']))
    actual = {}
    for path in root.rglob('*'):
        require(not path.is_symlink())
        if path.is_file() and path != root / 'evidence.json':
            actual[path.relative_to(root).as_posix()] = path.read_bytes()
    require(set(actual) == set(manifest['files']))
    for name, entry in manifest['files'].items():
        require(isinstance(name, str) and not PurePosixPath(name).is_absolute()
                and '..' not in PurePosixPath(name).parts)
        require(set(entry) == {'kind', 'sha256'})
        require(entry['kind'] in {'python', 'data', 'gateway', 'input'})
        require(name.startswith('inputs/') if entry['kind'] == 'input' else name.startswith('shipped/'))
        require(entry['sha256'] == fingerprint(actual[name]))
        data = actual[name]
        python_script = (name.endswith('.py') or
                         (data.startswith(b'#!') and b'python' in data.split(b'\n')[0]))
        require(not name.startswith('shipped/') or not python_script or entry['kind'] == 'python')
    gateways = {n for n, e in manifest['files'].items() if e['kind'] == 'gateway'}
    require(bool(gateways) and set(manifest['builds']) == gateways)
    require(any(e['kind'] == 'input' for e in manifest['files'].values()))
    return manifest, actual


def validate_recipe(recipe, inspection):
    require(set(recipe) == {'toolchain', 'settings', 'dependencies', 'command',
                            'environment', 'inputs'})
    require({k: recipe[k] for k in ('toolchain', 'settings', 'dependencies')} == inspection)
    settings = recipe['settings']
    require(settings.get('-trimpath') == 'true')
    require(settings.get('-buildmode') == 'exe')
    require(settings.get('-compiler') == 'gc')
    require(settings.get('CGO_ENABLED') == '0')
    require(settings.get('GOOS') in {'linux'})
    require(settings.get('GOARCH') in {'amd64', 'arm64', 'arm', '386'})
    # -trimpath builds omit -ldflags from inspected metadata, so the linker
    # flags are recorded only in the build command and checked from there.
    allowed = {'-trimpath', '-buildmode', '-compiler', '-tags',
               'CGO_ENABLED', 'GOOS', 'GOARCH', 'GOAMD64', 'GOARM', 'GOARM64', 'GO386'}
    require(set(settings) <= allowed)
    command_args = recipe['command']
    require(isinstance(command_args, list) and command_args.count('-ldflags') == 1
            and command_args.index('-ldflags') + 1 < len(command_args))
    flags = command_args[command_args.index('-ldflags') + 1]
    require(isinstance(flags, str))
    # One empty build ID and exactly two normalized build stamp assignments.
    import shlex
    parts = shlex.split(flags)
    require(len(parts) == 5 and parts[0] == '-buildid=' and parts[1] == '-X'
            and parts[3] == '-X')
    require(parts[2].startswith('main.buildVersion=') and parts[2].split('=', 1)[1])
    require(parts[4].startswith('main.buildID=') and parts[4].split('=', 1)[1])
    command = ['go', 'build', '-trimpath', '-buildvcs=false']
    if '-tags' in settings:
        command += ['-tags', settings['-tags']]
    command += ['-ldflags', flags, '-o', 'gateway', './cmd/gateway']
    require(recipe['command'] == command)
    env = {'CGO_ENABLED': '0', 'GOWORK': 'off', 'GOENV': 'off',
           'GOTOOLCHAIN': 'local', 'GOFLAGS': '-mod=readonly',
           'GOPROXY': 'off', 'GOSUMDB': 'off'}
    env.update({k: v for k, v in settings.items() if k.startswith('GO')})
    require(recipe['environment'] == env)
    require(bool(recipe['dependencies']))
    require(bool(recipe['inputs']))


def compare(before, after, inspector=inspect_go):
    """Return only sanitized outcomes. Input hashes remain local evidence."""
    try:
        bm, bd = load_tree(before)
        am, ad = load_tree(after)
        require(set(bd) == set(ad))
        for name, entry in bm['files'].items():
            kind = entry['kind']
            require(kind == am['files'][name]['kind'])
            if kind == 'python':
                require(ast.dump(ast.parse(bd[name]), include_attributes=False) ==
                        ast.dump(ast.parse(ad[name]), include_attributes=False))
            elif kind == 'data':
                require(bd[name] == ad[name])
            elif kind == 'gateway':
                br, ar = bm['builds'][name], am['builds'][name]
                require(br == ar)
                for root, manifest, recipe in ((before, bm, br), (after, am, ar)):
                    inputs = {n for n, e in manifest['files'].items() if e['kind'] == 'input'}
                    require(set(recipe['inputs']) == inputs and len(recipe['inputs']) == len(inputs))
                    validate_recipe(recipe, inspector(Path(root) / name))
                require(bd[name] == ad[name])
        return {'status': 'COMPARISONS_VERIFIED', 'files_compared': len(bd),
                'provenance': 'operator-controlled builds required; not independently reproduced',
                'candidate_acceptance': 'UNVERIFIED'}
    except (ValueError, TypeError, KeyError, IndexError, AttributeError, OSError,
            SyntaxError, subprocess.SubprocessError, RecursionError):
        return {'status': 'UNVERIFIED', 'candidate_acceptance': 'UNVERIFIED'}


def self_test():
    # Exercise the same CLI comparison path with synthetic data and a fake inspector.
    import importlib.util
    test_path = Path(__file__).resolve().parents[1] / 'tests/test_artifact_evidence.py'
    spec = importlib.util.spec_from_file_location('artifact_self_tests', test_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    import unittest
    result = unittest.TextTestRunner(verbosity=0).run(unittest.defaultTestLoader.loadTestsFromModule(module))
    return result.wasSuccessful() and result.testsRun > 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--before', type=Path)
    parser.add_argument('--after', type=Path)
    parser.add_argument('--self-test', action='store_true')
    args = parser.parse_args()
    if args.self_test:
        ok = self_test()
        print(json.dumps({'self_test': 'PASS' if ok else 'UNVERIFIED', 'synthetic_only': True}))
        return 0 if ok else 1
    if args.before is None or args.after is None:
        parser.error('--before and --after are required')
    result = compare(args.before, args.after)
    print(json.dumps(result, sort_keys=True))
    return 0 if result['status'] == 'COMPARISONS_VERIFIED' else 1


if __name__ == '__main__':
    raise SystemExit(main())
