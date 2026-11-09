"""Synthetic pairs; build inspection is deliberately faked, never qualification."""
import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location(
    'artifact_evidence', Path(__file__).resolve().parents[1] / 'scripts/compare_artifact_evidence.py')
proof = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(proof)


class EvidenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.before = Path(self.tmp.name) / 'before'
        self.after = Path(self.tmp.name) / 'after'
        flags = '-buildid= -X main.buildVersion=normalized -X main.buildID=normalized'
        self.settings = {'-trimpath': 'true', '-buildmode': 'exe', '-compiler': 'gc',
                         'CGO_ENABLED': '0', 'GOOS': 'linux', 'GOARCH': 'amd64'}
        self.inspection = {'toolchain': 'go1.synthetic', 'settings': self.settings,
                           'dependencies': [['path', 'example.invalid/gateway'],
                                            ['mod', 'example.invalid/gateway', '(devel)']]}
        self.recipe = dict(self.inspection, command=['go', 'build', '-trimpath', '-buildvcs=false',
                           '-ldflags', flags, '-o', 'gateway', './cmd/gateway'],
                           environment={'CGO_ENABLED': '0', 'GOWORK': 'off', 'GOENV': 'off',
                                        'GOTOOLCHAIN': 'local', 'GOFLAGS': '-mod=readonly',
                                        'GOPROXY': 'off', 'GOSUMDB': 'off',
                                        'GOOS': 'linux', 'GOARCH': 'amd64'},
                           inputs=['inputs/go.mod', 'inputs/main.go'])
        self.files = {'shipped/gateway': ('gateway', b'synthetic binary'),
                      'shipped/package/module.py': ('python', b'value = 1\n'),
                      'shipped/bin/helper': ('python', b'#!/usr/bin/env python3\nvalue = 1\n'),
                      'shipped/data': ('data', b'packaged data'),
                      'inputs/go.mod': ('input', b'module example.invalid/gateway\n'),
                      'inputs/main.go': ('input', b'package main\n')}
        self.write(self.before)
        self.write(self.after)

    def write(self, root, files=None, recipe=None):
        files = self.files if files is None else files
        root.mkdir(parents=True, exist_ok=True)
        entries = {}
        for name, (kind, data) in files.items():
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
            entries[name] = {'kind': kind, 'sha256': proof.fingerprint(data)}
        (root / 'evidence.json').write_text(json.dumps({
            'version': 1, 'files': entries,
            'builds': {'shipped/gateway': self.recipe if recipe is None else recipe}}))

    def compare(self, inspector=None):
        return proof.compare(self.before, self.after, inspector or (lambda _: self.inspection))['status']

    def test_identical(self):
        self.assertEqual(self.compare(), 'COMPARISONS_VERIFIED')

    def test_byte_change(self):
        self.files['shipped/gateway'] = ('gateway', b'synthetic binarz')
        self.write(self.after)
        self.assertEqual(self.compare(), 'UNVERIFIED')

    def test_comment_only_module_and_extensionless_script(self):
        for name in ('shipped/package/module.py', 'shipped/bin/helper'):
            with self.subTest(name=name):
                kind, data = self.files[name]
                self.files[name] = (kind, data + b'# public synthetic comment\n')
                self.write(self.after)
                self.assertEqual(self.compare(), 'COMPARISONS_VERIFIED')

    def test_semantics_docstrings_and_syntax(self):
        for name in ('shipped/package/module.py', 'shipped/bin/helper'):
            for data in (b'value = 2\n', b'"changed docstring"\nvalue = 1\n', b'if :\n'):
                with self.subTest(name=name, data=data):
                    files = dict(self.files, **{name: ('python', data)})
                    self.write(self.after, files)
                    self.assertEqual(self.compare(), 'UNVERIFIED')

    def test_packaged_data(self):
        self.files['shipped/data'] = ('data', b'changed data')
        self.write(self.after)
        self.assertEqual(self.compare(), 'UNVERIFIED')

    def test_extra_deleted_and_omitted_inventory(self):
        path = self.after / 'shipped/data'
        path.unlink()
        self.assertEqual(self.compare(), 'UNVERIFIED')
        self.write(self.after)
        extra = self.after / 'shipped/extra'
        extra.write_bytes(b'extra')
        self.assertEqual(self.compare(), 'UNVERIFIED')
        extra.unlink()
        manifest = json.loads((self.after / 'evidence.json').read_text())
        del manifest['files']['shipped/data']
        (self.after / 'evidence.json').write_text(json.dumps(manifest))
        self.assertEqual(self.compare(), 'UNVERIFIED')

    def test_missing_evidence_or_binary(self):
        for name in ('evidence.json', 'shipped/gateway'):
            self.write(self.after)
            (self.after / name).unlink()
            self.assertEqual(self.compare(), 'UNVERIFIED')

    def test_nonempty_build_id_adapter(self):
        with patch.object(proof.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, 'nonempty\n')):
            self.assertEqual(proof.compare(self.before, self.after)['status'], 'UNVERIFIED')

    def test_missing_tool(self):
        with patch.object(proof.subprocess, 'run', side_effect=FileNotFoundError):
            self.assertEqual(proof.compare(self.before, self.after)['status'], 'UNVERIFIED')

    def test_recipe_fields_independently(self):
        # Each recorded identity field must be compared, not just binary content.
        changes = {'toolchain': 'different', 'settings': {}, 'dependencies': [],
                   'command': ['go', 'build'], 'environment': {}, 'inputs': []}
        for field, value in changes.items():
            with self.subTest(field=field):
                recipe = copy.deepcopy(self.recipe)
                recipe[field] = value
                self.write(self.after, recipe=recipe)
                self.assertEqual(self.compare(), 'UNVERIFIED')

    def test_matching_but_invalid_recipes(self):
        for field, value in (('-trimpath', 'false'), ('GOARCH', 'unknown'),
                             ('CGO_ENABLED', '1'), ('-ldflags', '-buildid=other')):
            with self.subTest(field=field):
                recipe = copy.deepcopy(self.recipe)
                if field == '-ldflags':
                    recipe['command'][recipe['command'].index('-ldflags') + 1] = value
                else:
                    recipe['settings'][field] = value
                self.write(self.before, recipe=recipe)
                self.write(self.after, recipe=recipe)
                inspection = {k: recipe[k] for k in ('toolchain', 'settings', 'dependencies')}
                self.assertEqual(self.compare(lambda _: inspection), 'UNVERIFIED')

    def test_trimpath_metadata_omits_ldflags(self):
        # Realistic inspected metadata never carries -ldflags under -trimpath.
        self.assertNotIn('-ldflags', self.inspection['settings'])
        self.assertEqual(self.compare(), 'COMPARISONS_VERIFIED')

    def test_ldflags_in_metadata_is_not_accepted_setting_mismatch(self):
        recipe = copy.deepcopy(self.recipe)
        recipe['settings']['-ldflags'] = '-buildid='
        inspection = {k: recipe[k] for k in ('toolchain', 'settings', 'dependencies')}
        for root in (self.before, self.after):
            self.write(root, recipe=recipe)
        self.assertEqual(self.compare(lambda _: inspection), 'UNVERIFIED')

    def test_flags_differ(self):
        recipe = copy.deepcopy(self.recipe)
        recipe['command'][recipe['command'].index('-ldflags') + 1] += ' -s'
        self.write(self.after, recipe=recipe)
        self.assertEqual(self.compare(), 'UNVERIFIED')

    def test_input_and_role_binding(self):
        manifest = json.loads((self.after / 'evidence.json').read_text())
        manifest['files']['shipped/data']['kind'] = 'input'
        (self.after / 'evidence.json').write_text(json.dumps(manifest))
        self.assertEqual(self.compare(), 'UNVERIFIED')
        self.write(self.after)
        (self.after / 'inputs/main.go').write_bytes(b'changed without renewed manifest')
        self.assertEqual(self.compare(), 'UNVERIFIED')

    def test_python_build_input_is_not_shipped(self):
        self.files['inputs/generator.py'] = ('input', b'print("synthetic")\n')
        recipe = copy.deepcopy(self.recipe)
        recipe['inputs'].append('inputs/generator.py')
        for root in (self.before, self.after):
            self.write(root, recipe=recipe)
        self.assertEqual(self.compare(), 'COMPARISONS_VERIFIED')

    def test_each_target_setting_is_identity(self):
        for field, value in (('GOOS', 'other'), ('GOARCH', 'arm64'),
                             ('GOARM', '7'), ('GOAMD64', 'v3'), ('GOARM64', 'v8.1'),
                             ('GO386', 'softfloat'), ('-tags', 'other'),
                             ('-compiler', 'other'), ('-buildmode', 'other'),
                             ('CGO_ENABLED', '1'), ('-trimpath', 'false')):
            with self.subTest(field=field):
                recipe = copy.deepcopy(self.recipe)
                recipe['settings'][field] = value
                self.write(self.after, recipe=recipe)
                self.assertEqual(self.compare(), 'UNVERIFIED')

    def test_inspection_mismatch_and_failure(self):
        for field, value in (('toolchain', 'different'), ('settings', {}),
                             ('dependencies', [])):
            inspection = copy.deepcopy(self.inspection)
            inspection[field] = value
            self.assertEqual(self.compare(lambda _: inspection), 'UNVERIFIED')
        with patch.object(proof.subprocess, 'run', side_effect=subprocess.TimeoutExpired('go', 20)):
            self.assertEqual(proof.compare(self.before, self.after)['status'], 'UNVERIFIED')

    def test_missing_input_binding_and_unknown_recipe(self):
        recipe = copy.deepcopy(self.recipe)
        recipe['inputs'] = ['inputs/go.mod']
        for root in (self.before, self.after):
            self.write(root, recipe=recipe)
        self.assertEqual(self.compare(), 'UNVERIFIED')
        recipe = copy.deepcopy(self.recipe)
        recipe['settings']['unknown'] = 'value'
        for root in (self.before, self.after):
            self.write(root, recipe=recipe)
        inspection = {k: recipe[k] for k in ('toolchain', 'settings', 'dependencies')}
        self.assertEqual(self.compare(lambda _: inspection), 'UNVERIFIED')

    def test_inspection_parser(self):
        lines = ['output: go1.synthetic']
        lines += ['\t' + '\t'.join(item) for item in self.inspection['dependencies']]
        lines += ['\tbuild\t' + k + '=' + (json.dumps(v) if ' ' in v else v)
                  for k, v in self.settings.items()]
        results = [subprocess.CompletedProcess([], 0, '\n'),
                   subprocess.CompletedProcess([], 0, '\n'.join(lines))]
        with patch.object(proof.subprocess, 'run', side_effect=results):
            self.assertEqual(proof.inspect_go(Path('synthetic')), self.inspection)


if __name__ == '__main__':
    unittest.main()
