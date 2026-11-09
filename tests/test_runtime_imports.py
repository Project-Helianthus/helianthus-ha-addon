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
        self.assertLessEqual(
            {'serial_can_options.py', 'm2m_tls_identity.py',
             'check_runtime_state_wrapper.py', 'modbus_runtime_guard.py'},
            {p.name for p in guard.sources})

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

    def test_namespace_relative_imports(self):
        for initializer in ({}, {'ns/pkg/__init__.py': ''}):
            with self.subTest(initializer=initializer):
                _, errors = self.check({
                    'entry.py': 'import ns.pkg.child',
                    'ns/pkg/child.py': 'from . import helper\nfrom .. import shared\n'
                                       'import importlib\nimportlib.import_module(".helper", __package__)',
                    'ns/pkg/helper.py': 'value = 1',
                    'ns/shared.py': 'import json',
                    **initializer,
                })
                self.assertEqual(errors, [])

    def test_namespace_relative_dependency_is_checked(self):
        _, errors = self.check({
            'entry.py': 'import ns.child',
            'ns/child.py': 'from . import helper',
            'ns/helper.py': 'import scripts.hidden',
        })
        self.assertTrue(any('forbidden import scripts.hidden' in e for e in errors), errors)

    def test_namespace_relative_imports_in_site_packages(self):
        for directory in ('site-packages', 'dist-packages'):
            with self.subTest(directory=directory):
                _, errors = self.check({
                    f'lib/{directory}/ns/child.py': 'from . import helper',
                    f'lib/{directory}/ns/helper.py': 'import json',
                })
                self.assertEqual(errors, [])

    def test_isolated_namespace_relative_imports(self):
        _, errors = self.check({
            'ns/child.py': 'from . import helper',
            'ns/helper.py': 'import json',
        })
        self.assertEqual(errors, [])

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

    def test_wildcard_dynamic_loader_imports(self):
        for module, call in (
            ('importlib', 'import_module("scripts.hidden")'),
            ('runpy', 'run_module("tests.hidden")'),
            ('runpy', 'run_path(target)'),
            ('builtins', 'exec(source)'),
        ):
            with self.subTest(module=module, call=call):
                _, errors = self.check({'entry.py': f'from {module} import *\n{call}'})
                self.assertTrue(any('wildcard import from dynamic-loader module' in e
                                    for e in errors), errors)

    def test_reexported_dynamic_loaders(self):
        for helper, call, expected in (
            ('from importlib import import_module as load', 'load("scripts.hidden")', 'forbidden import'),
            ('import importlib\nload: object = importlib.import_module', 'load(target)',
             'dynamic import destination'),
            ('import importlib as load', 'load.import_module("tests.hidden")', 'forbidden import'),
            ('from runpy import run_module as load', 'load(target)', 'runpy.run_module'),
            ('from builtins import exec as load', 'load(source)', 'exec cannot establish'),
        ):
            for entry in (f'from helper import load\n{call}',
                          f'import helper\nhelper.{call}',
                          f'from bridge import load\n{call}'):
                with self.subTest(helper=helper, entry=entry):
                    _, errors = self.check({
                        'entry.py': entry, 'helper.py': helper,
                        'bridge.py': 'from helper import load',
                    })
                    self.assertTrue(any(expected in e for e in errors), errors)

    def test_reexported_loader_allows_resolved_imports(self):
        _, errors = self.check({
            'entry.py': 'from pkg import load\nload("json")\nload("helper")',
            'pkg/__init__.py': 'from .loader import load',
            'pkg/loader.py': 'from importlib import import_module as load',
            'helper.py': 'from json import loads\nloads("{}")',
        })
        self.assertEqual(errors, [])

    def test_regular_reexports_and_cycles_are_allowed(self):
        _, errors = self.check({
            'entry.py': 'from helper import decode\ndecode("{}")',
            'helper.py': 'from json import loads as decode\nimport entry',
        })
        self.assertEqual(errors, [])

    def test_dynamic_loader_module_assignment_aliases(self):
        for bindings, function in (
            ('import importlib\nloader = importlib', 'loader.import_module'),
            ('import importlib as module\nloader = module\nnext_loader = loader',
             'next_loader.import_module'),
            ('import builtins\nloader = builtins', 'loader.__import__'),
        ):
            for destination, expected in (
                ('target', 'dynamic import destination cannot be resolved safely'),
                ('"scripts.hidden"', 'forbidden import scripts.hidden'),
                ('"tests.hidden"', 'forbidden import tests.hidden'),
            ):
                with self.subTest(bindings=bindings, destination=destination):
                    _, errors = self.check({'entry.py': f'{bindings}\n{function}({destination})'})
                    self.assertTrue(any(expected in e for e in errors), errors)
            with self.subTest(bindings=bindings, destination='allowed'):
                _, errors = self.check({
                    'entry.py': f'{bindings}\n{function}("json")\n{function}("helper")',
                    'helper.py': '',
                })
                self.assertEqual(errors, [])

    def test_dynamic_relative(self):
        _, errors = self.check({'pkg/__init__.py': '', 'pkg/helper.py': '',
                                'entry.py': 'from importlib import import_module\nimport_module(".helper", "pkg")'})
        self.assertEqual(errors, [])

    def test_annotated_dynamic_import_aliases(self):
        for binding in (
            'loader: object = importlib.import_module',
            'module: object = importlib\nloader: object = module.import_module',
        ):
            for destination, expected in (
                ('"scripts.hidden"', 'forbidden import scripts.hidden'),
                ('"tests.hidden"', 'forbidden import tests.hidden'),
                ('target', 'dynamic import destination cannot be resolved safely'),
            ):
                with self.subTest(binding=binding, destination=destination):
                    _, errors = self.check({'entry.py':
                        f'import importlib\n{binding}\nloader({destination})'})
                    self.assertTrue(any(expected in e for e in errors), errors)
            with self.subTest(binding=binding, destination='allowed'):
                _, errors = self.check({'entry.py':
                    f'import importlib\n{binding}\nloader("json")\nloader("helper")',
                    'helper.py': ''})
                self.assertEqual(errors, [])

    def test_runpy_loader_aliases(self):
        for loader in ('run_path', 'run_module'):
            for binding, function in (
                ('', f'runpy.{loader}'),
                ('module = runpy', f'module.{loader}'),
                (f'runner = runpy.{loader}', 'runner'),
                (f'runner: object = runpy.{loader}', 'runner'),
                (f'module: object = runpy\nrunner = module.{loader}\nnext_runner = runner',
                 'next_runner'),
            ):
                with self.subTest(loader=loader, binding=binding):
                    _, errors = self.check({'entry.py':
                        f'import runpy\n{binding}\n{function}(target)'})
                    self.assertTrue(any(f'runpy.{loader} cannot establish a static import boundary'
                                        in e for e in errors), errors)

    def test_qualified_builtin_dynamic_calls(self):
        for function, arguments in (
            ('exec', 'source'), ('eval', 'source'),
            ('getattr', 'loader, method'), ('setattr', 'loader, method, value'),
        ):
            for binding, call in (
                ('import builtins', f'builtins.{function}'),
                ('import builtins as b', f'b.{function}'),
                (f'from builtins import {function} as action', 'action'),
                ('', f'__builtins__.{function}'),
                ('', f'__builtins__["{function}"]'),
                (f'import builtins\naction = builtins.{function}', 'action'),
                (f'import builtins\naction: object = builtins.{function}', 'action'),
                (f'import builtins\nmodule: object = builtins\naction = module.{function}',
                 'action'),
            ):
                with self.subTest(function=function, binding=binding, call=call):
                    _, errors = self.check({'entry.py': f'{binding}\n{call}({arguments})'})
                    self.assertTrue(any(f'{function} cannot establish a static import boundary'
                                        in e for e in errors), errors)

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
