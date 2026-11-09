"""Synthetic import graphs; shipped entrypoints are never executed."""
import importlib.util
from pathlib import Path
import tempfile
import unittest

SPEC = importlib.util.spec_from_file_location(
    'runtime_import_guard', Path(__file__).resolve().parents[1] / 'scripts/check_runtime_imports.py')
GUARD = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(GUARD)


class RuntimeImportsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.repo = Path(self.temp.name)
        self.runtime = 'helianthus/rootfs/usr/share/helianthus/'

    def write(self, name, content):
        path = self.repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
        return path

    def check(self, files):
        for name, content in files.items():
            self.write(self.runtime + name, content)
        guard = GUARD.ImportBoundary(self.repo)
        return guard, guard.check()

    def test_repository_inventory(self):
        guard = GUARD.ImportBoundary(Path(__file__).resolve().parents[1])
        self.assertEqual(guard.check(), [])
        self.assertTrue({'serial_can_options.py', 'm2m_tls_identity.py',
                         'check_runtime_state_wrapper.py', 'modbus_runtime_guard.py'}
                        <= {p.name for p in guard.sources})

    def test_stdlib_import_and_from_alias(self):
        _, errors = self.check({'entry.py': 'import json as codec\nfrom pathlib import Path as P\n'})
        self.assertEqual(errors, [])

    def test_forbidden_import_forms(self):
        for source in ('import scripts.something', 'import tests.helper as helper',
                       'from scripts import something', 'from tests.helper import value as v'):
            with self.subTest(source=source):
                _, errors = self.check({'entry.py': source})
                self.assertTrue(any('entry.py:1:' in e and ('scripts' in e or 'tests' in e) for e in errors), errors)

    def test_unshipped_bare_module(self):
        self.write('scripts/helper.py', '')
        _, errors = self.check({'entry.py': 'import helper'})
        self.assertTrue(any('import helper' in e for e in errors), errors)

    def test_same_basename_does_not_forbid_shipped_module(self):
        self.write('scripts/helper.py', 'import tests.private')
        _, errors = self.check({'entry.py': 'import helper', 'helper.py': 'import json'})
        self.assertEqual(errors, [])

    def test_transitive_and_stdlib_shadow(self):
        for name in ('helper', 'json'):
            with self.subTest(name=name):
                _, errors = self.check({'entry.py': f'import {name}', f'{name}.py': 'import scripts.hidden'})
                self.assertTrue(any(f'{name}.py' in e and 'scripts.hidden' in e for e in errors), errors)

    def test_package_initializer_and_from_child(self):
        _, errors = self.check({'entry.py': 'from pkg import child', 'pkg/__init__.py': '',
                                'pkg/child.py': 'import tests.hidden'})
        self.assertTrue(any('pkg/child.py' in e and 'tests.hidden' in e for e in errors), errors)

    def test_allowed_relative_local_imports(self):
        _, errors = self.check({'entry.py': 'from pkg import child', 'pkg/__init__.py': '',
                                'pkg/child.py': 'from . import helper\nfrom .helper import value',
                                'pkg/helper.py': 'value = 1'})
        self.assertEqual(errors, [])

    def test_relative_escape(self):
        _, errors = self.check({'pkg/__init__.py': '', 'pkg/child.py': 'from .. import scripts'})
        self.assertTrue(any('relative import escapes' in e for e in errors), errors)

    def test_shadow_package_does_not_fall_back_to_stdlib(self):
        _, errors = self.check({'entry.py': 'import json.tool', 'json/__init__.py': ''})
        self.assertTrue(any('unresolved shipped import json.tool' in e for e in errors), errors)

    def test_unrelated_directory_is_not_on_search_path(self):
        _, errors = self.check({'entry.py': 'import helper', 'unrelated/helper.py': ''})
        self.assertTrue(any('import helper' in e for e in errors), errors)

    def test_extensionless_python_entrypoint(self):
        guard, errors = self.check({'command': '#!/usr/bin/env python3\nimport scripts.hidden\n'})
        self.assertIn('command', {p.name for p in guard.sources})
        self.assertTrue(any('command:2:' in e and 'scripts.hidden' in e for e in errors), errors)

    def test_parse_failure(self):
        _, errors = self.check({'broken.py': 'def broken('})
        self.assertTrue(any('source parse failure' in e for e in errors), errors)

    def test_encoding_failure(self):
        self.write(self.runtime + 'bad.py', '# coding: unknown-encoding\n')
        guard = GUARD.ImportBoundary(self.repo)
        self.assertTrue(any('source parse failure' in e for e in guard.check()))

    def test_dynamic_import_aliases(self):
        for source in (
            'import importlib\nimportlib.import_module("scripts.hidden")',
            'import importlib as loader\nloader.import_module("tests.hidden")',
            'from importlib import import_module as load\nload("scripts.hidden")',
            '__import__("tests.hidden")',
            '__builtins__.__import__("scripts.hidden")',
            '__builtins__["__import__"]("tests.hidden")',
            'import importlib\nimportlib.__dict__["import_module"]("scripts.hidden")',
            'import builtins as b\nb.__import__("scripts.hidden")',
            'from builtins import __import__ as load\nload("tests.hidden")',
            'import importlib\nload = importlib.import_module\nload("scripts.hidden")',
        ):
            with self.subTest(source=source):
                _, errors = self.check({'entry.py': source})
                self.assertTrue(any('forbidden import' in e for e in errors), errors)

    def test_dynamic_constant_local_and_stdlib(self):
        _, errors = self.check({'entry.py': 'import importlib\nimportlib.import_module("helper")\n__import__("json")',
                                'helper.py': ''})
        self.assertEqual(errors, [])

    def test_dynamic_relative(self):
        _, errors = self.check({'pkg/__init__.py': '', 'pkg/helper.py': '',
                                'entry.py': 'from importlib import import_module\nimport_module(".helper", "pkg")'})
        self.assertEqual(errors, [])

    def test_dynamic_relative_package_context(self):
        _, errors = self.check({'pkg/__init__.py': '', 'pkg/helper.py': '',
                                'pkg/child.py': 'import importlib\nimportlib.import_module(".helper", __package__)'})
        self.assertEqual(errors, [])

    def test_unknown_dynamic_destinations(self):
        for source in ('import importlib\nimportlib.import_module(target)', '__import__(target)',
                       'from importlib import import_module\nimport_module(".helper")',
                       '__import__("pkg", fromlist=names)',
                       'import importlib.util\nimportlib.util.spec_from_file_location("helper", location)',
                       'exec(source)', 'getattr(loader, method)(target)'):
            with self.subTest(source=source):
                _, errors = self.check({'entry.py': source})
                self.assertTrue(errors)

    def test_search_path_aliases_and_mutations(self):
        for source in ('import sys\nsys.path.insert(0, "scripts")',
                       'import sys as system\nsystem.path.append("tests")',
                       'from sys import path as paths\npaths[:] = ["scripts"]',
                       'import sys\npaths = sys.path\npaths.extend([target])',
                       'import sys\nsys.path = [target]'):
            with self.subTest(source=source):
                _, errors = self.check({'entry.py': source})
                self.assertTrue(any('sys.path' in e for e in errors), errors)

    def test_package_sibling_requires_relative_import(self):
        _, errors = self.check({'entry.py': 'import pkg.child', 'pkg/__init__.py': '',
                                'pkg/child.py': 'import helper', 'pkg/helper.py': ''})
        self.assertTrue(any('pkg/child.py' in e and 'import helper' in e for e in errors), errors)

    def test_dynamic_fromlist_traverses_child(self):
        _, errors = self.check({'entry.py': '__import__("pkg", fromlist=["child"])',
                                'pkg/__init__.py': '', 'pkg/child.py': 'import scripts.hidden'})
        self.assertTrue(any('pkg/child.py' in e and 'scripts.hidden' in e for e in errors), errors)

    def test_dynamic_fromlist_stdlib_attribute(self):
        _, errors = self.check({'entry.py': '__import__("json", fromlist=["loads"])'})
        self.assertEqual(errors, [])

    def test_nonexistent_standard_library_submodule(self):
        _, errors = self.check({'entry.py': 'import json.nonexistent'})
        self.assertTrue(any('unresolved standard-library submodule' in e for e in errors), errors)

    def test_cyclic_shipped_imports_terminate(self):
        _, errors = self.check({'entry.py': 'import helper',
                                'helper.py': 'import sys\nsys.path.append("/usr/share/helianthus")\nimport entry'})
        self.assertEqual(errors, [])

    def test_safe_absolute_shipped_search_path(self):
        _, errors = self.check({'entry.py': 'import sys\nsys.path.append("/usr/share/helianthus/lib")\nimport helper',
                                'lib/helper.py': 'import json'})
        self.assertEqual(errors, [])

    def test_absolute_search_path_to_repository_is_rejected(self):
        self.write('scripts/helper.py', '')
        _, errors = self.check({'entry.py': f'import sys\nsys.path.append({str(self.repo / "scripts")!r})\nimport helper'})
        self.assertTrue(any('sys.path' in e for e in errors), errors)

    def test_conflicting_aliases_fail_closed(self):
        _, errors = self.check({'entry.py': 'from importlib import import_module as load\ndef other():\n from json import loads as load\nload(target)'})
        self.assertTrue(any('ambiguous import alias load' in e for e in errors), errors)

    def test_imports_are_parsed_even_in_unreachable_code(self):
        _, errors = self.check({'entry.py': 'if False:\n import scripts.hidden'})
        self.assertTrue(any('scripts.hidden' in e for e in errors), errors)

    def test_symlink_escape(self):
        outside = self.write('scripts/helper.py', 'import json')
        path = self.repo / self.runtime / 'entry.py'
        path.parent.mkdir(parents=True, exist_ok=True)
        path.symlink_to(outside)
        guard = GUARD.ImportBoundary(self.repo)
        self.assertTrue(any('escapes the shipped tree' in e for e in guard.check()))

    def test_no_execution(self):
        _, errors = self.check({'entry.py': 'raise RuntimeError("must not execute")\nimport json'})
        self.assertEqual(errors, [])

    def test_missing_or_empty_runtime_is_not_success(self):
        self.assertTrue(GUARD.ImportBoundary(self.repo).check())
        (self.repo / 'helianthus/rootfs').mkdir(parents=True)
        self.assertTrue(GUARD.ImportBoundary(self.repo).check())


if __name__ == '__main__':
    unittest.main()
