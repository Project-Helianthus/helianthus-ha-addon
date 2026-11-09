#!/usr/bin/env python3
"""Check the image's Python import boundary without executing image code.

Only the interpreter's standard library and resolved rootfs sources are admitted.
Unknown third-party imports fail closed: distribution names in a build command
alone do not establish a Python module's presence in the final image.
"""
from __future__ import annotations

import ast
from pathlib import Path
import re
import sys
import sysconfig
import tokenize


class ImportBoundary:
    def __init__(self, repository: Path):
        self.repository = repository.resolve()
        self.rootfs = self.repository / 'helianthus/rootfs'
        self.errors: list[str] = []
        self.sources: list[Path] = []
        self.visited: set[tuple[Path, tuple[Path, ...]]] = set()

    def error(self, path: Path, node: ast.AST, message: str) -> None:
        self.errors.append(f'{path.relative_to(self.repository)}:{getattr(node, "lineno", 1)}: {message}')

    def discover(self) -> None:
        if not self.rootfs.is_dir():
            self.errors.append('helianthus/rootfs: missing shipped source tree')
            return
        for path in sorted(self.rootfs.rglob('*')):
            if not path.is_file():
                continue
            try:
                with path.open('rb') as stream:
                    first = stream.readline(512)
            except OSError as exc:
                self.errors.append(f'{path.relative_to(self.repository)}: unreadable source: {exc.reason if hasattr(exc, "reason") else type(exc).__name__}')
                continue
            if path.suffix == '.py' or re.match(rb'#![^\n]*\bpython(?:\d+(?:\.\d+)*)?\b', first):
                self.sources.append(path)

    @staticmethod
    def symbol(node: ast.AST, aliases: dict[str, str]) -> str:
        if isinstance(node, ast.Name):
            return aliases.get(node.id, 'builtins' if node.id == '__builtins__' else node.id)
        if isinstance(node, ast.Attribute):
            return ImportBoundary.symbol(node.value, aliases) + '.' + node.attr
        if isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Constant) and isinstance(node.slice.value, str):
            owner = ImportBoundary.symbol(node.value, aliases).removesuffix('.__dict__')
            if owner in {'importlib', 'builtins'}:
                return owner + '.' + node.slice.value
        return ''

    def roots(self, path: Path) -> list[Path]:
        package_root = path.parent
        while (package_root / '__init__.py').is_file():
            package_root = package_root.parent
        roots = [package_root]
        roots += sorted(p for p in self.rootfs.rglob('*') if p.is_dir() and p.name in {'site-packages', 'dist-packages'})
        return list(dict.fromkeys(roots))

    def resolve(self, name: str, roots: list[Path]) -> list[Path]:
        """Resolve each package initializer before the leaf, including namespaces."""
        parts = name.split('.')
        for root in roots:
            current = root
            chain = []
            for index, part in enumerate(parts):
                module = current / (part + '.py')
                directory = current / part
                if directory.is_dir():
                    initializer = directory / '__init__.py'
                    if initializer.is_file():
                        chain.append(initializer)
                    current = directory
                elif module.is_file():
                    if index != len(parts) - 1:
                        return []
                    chain.append(module)
                    break
                else:
                    break
            else:
                return chain or [current]
            if chain and index == len(parts) - 1 and module.is_file():
                return chain
        return []

    def dependency(self, path: Path, node: ast.AST, name: str, roots: list[Path]) -> bool:
        if not name or any(not part.isidentifier() for part in name.split('.')):
            self.error(path, node, f'unresolved import {name!r}')
            return False
        if name.split('.')[0] in {'scripts', 'tests'}:
            self.error(path, node, f'forbidden import {name}')
            return False
        # Resolve shipped code before allowing a standard-library name.
        local = self.resolve(name, roots)
        if local:
            for source in local:
                if source.is_file():
                    self.visit(source, roots)
            return True
        # A local top-level package must never fall through to a host dependency.
        if self.resolve(name.split('.')[0], roots):
            self.error(path, node, f'unresolved shipped import {name}')
            return False
        if name.split('.')[0] in sys.stdlib_module_names:
            if '.' not in name or name == 'os.path' or self.resolve(name, [Path(sysconfig.get_path('stdlib'))]):
                return True
            self.error(path, node, f'unresolved standard-library submodule {name}')
            return False
        self.error(path, node, f'import {name} is not a resolved shipped module or standard-library dependency')
        return False

    def visit(self, path: Path, search_roots: list[Path] | None = None) -> None:
        roots = list(search_roots) if search_roots is not None else self.roots(path)
        key = (path, tuple(roots))
        if key in self.visited:
            return
        self.visited.add(key)
        if not path.resolve().is_relative_to(self.rootfs.resolve()):
            self.error(path, ast.Module(), 'source escapes the shipped tree')
            return
        try:
            with tokenize.open(path) as stream:
                tree = ast.parse(stream.read(), filename=str(path))
        except (OSError, SyntaxError, UnicodeError, LookupError) as exc:
            self.error(path, ast.Module(), f'source parse failure ({type(exc).__name__})')
            return
        nodes = list(ast.walk(tree))
        aliases: dict[str, str] = {}
        def bind(name: str, value: str, node: ast.AST) -> None:
            if name in aliases and aliases[name] != value:
                self.error(path, node, f'ambiguous import alias {name}')
            aliases[name] = value

        for node in nodes:
            if isinstance(node, ast.Import):
                for item in node.names:
                    bind(item.asname or item.name.split('.')[0], item.name if item.asname else item.name.split('.')[0], node)
            elif isinstance(node, ast.ImportFrom) and not node.level:
                for item in node.names:
                    bind(item.asname or item.name, f'{node.module}.{item.name}', node)
        # Propagate aliases conservatively, including aliases of dynamic loaders.
        for _ in range(len(nodes)):
            changed = False
            for node in nodes:
                if isinstance(node, ast.Assign):
                    value = self.symbol(node.value, aliases)
                    if value in {'importlib', 'builtins', 'importlib.import_module', 'builtins.__import__', '__import__', 'sys.path', 'sys'}:
                        for target in node.targets:
                            if isinstance(target, ast.Name) and aliases.get(target.id) != value:
                                aliases[target.id] = value
                                changed = True
            if not changed:
                break
        parents = {child: node for node in nodes for child in ast.iter_child_nodes(node)}
        safe_paths: set[int] = set()
        for node in nodes:
            if self.symbol(node, aliases) != 'sys.path':
                continue
            method = parents.get(node)
            call = parents.get(method)
            if not (isinstance(method, ast.Attribute) and isinstance(call, ast.Call)
                    and call.func is method and not call.keywords):
                continue
            arguments = call.args
            if method.attr == 'append' and len(arguments) == 1:
                values = arguments
            elif method.attr == 'insert' and len(arguments) == 2 and isinstance(arguments[0], ast.Constant) and isinstance(arguments[0].value, int):
                values = arguments[1:]
            elif method.attr == 'extend' and len(arguments) == 1 and isinstance(arguments[0], (ast.List, ast.Tuple)):
                values = arguments[0].elts
            else:
                continue
            directories = []
            for value in values:
                if not isinstance(value, ast.Constant) or not isinstance(value.value, str) or not value.value.startswith('/'):
                    break
                directory = (self.rootfs / value.value.lstrip('/')).resolve()
                if not directory.is_relative_to(self.rootfs.resolve()) or not directory.is_dir():
                    break
                directories.append(directory)
            else:
                roots.extend(directories)
                safe_paths.add(id(node))
        roots = list(dict.fromkeys(roots))
        package = []
        parent = path.parent
        while (parent / '__init__.py').is_file():
            package.insert(0, parent.name)
            parent = parent.parent
        for node in nodes:
            symbol = self.symbol(node, aliases)
            if symbol == 'sys.path' and id(node) not in safe_paths:
                # Runtime-computed search paths cannot establish packaged provenance.
                self.error(path, node, 'sys.path access cannot establish a safe shipped import path')
            if isinstance(node, ast.Import):
                for item in node.names:
                    self.dependency(path, node, item.name, roots)
            elif isinstance(node, ast.ImportFrom):
                if node.level:
                    if node.level > len(package):
                        self.error(path, node, 'relative import escapes its shipped package')
                        continue
                    prefix = package[:len(package) - node.level + 1]
                    name = '.'.join(prefix + ([node.module] if node.module else []))
                    import_roots = [parent]
                else:
                    name, import_roots = node.module or '', roots
                if self.dependency(path, node, name, import_roots):
                    for item in node.names:
                        child = name + '.' + item.name
                        local = self.resolve(child, import_roots)
                        if local:
                            self.dependency(path, node, child, import_roots)
            elif isinstance(node, ast.Call):
                function = self.symbol(node.func, aliases)
                if function in {'importlib.import_module', 'builtins.__import__', '__import__'}:
                    argument = node.args[0] if node.args else next((k.value for k in node.keywords if k.arg == 'name'), None)
                    if not isinstance(argument, ast.Constant) or not isinstance(argument.value, str):
                        self.error(path, node, 'dynamic import destination cannot be resolved safely')
                        continue
                    name = argument.value
                    if name.startswith('.'):
                        anchor = node.args[1] if len(node.args) > 1 else next((k.value for k in node.keywords if k.arg == 'package'), None)
                        if isinstance(anchor, ast.Name) and anchor.id == '__package__' and package:
                            anchor = ast.Constant(value='.'.join(package))
                        if function != 'importlib.import_module' or not isinstance(anchor, ast.Constant) or not isinstance(anchor.value, str):
                            self.error(path, node, f'unresolved relative dynamic import {name}')
                            continue
                        level = len(name) - len(name.lstrip('.'))
                        parts = anchor.value.split('.')
                        if level > len(parts):
                            self.error(path, node, f'relative dynamic import escapes package: {name}')
                            continue
                        name = '.'.join(parts[:len(parts) - level + 1] + ([name[level:]] if name[level:] else []))
                    if function in {'__import__', 'builtins.__import__'}:
                        # Non-default fromlist/level can add imports beyond the literal name.
                        if len(node.args) > 5 or any(k.arg not in {'name', 'globals', 'locals', 'fromlist', 'level'} for k in node.keywords):
                            self.error(path, node, '__import__ context/fromlist/level cannot be resolved safely')
                            continue
                        options = {key: node.args[index] for index, key in enumerate(('name', 'globals', 'locals', 'fromlist', 'level')) if index < len(node.args)}
                        options.update({k.arg: k.value for k in node.keywords})
                        context = [options[key] for key in ('globals', 'locals') if key in options]
                        level = options.get('level', ast.Constant(value=0))
                        fromlist = options.get('fromlist', ast.Tuple(elts=[]))
                        if (any(not isinstance(value, ast.Constant) or value.value is not None for value in context)
                                or not isinstance(level, ast.Constant) or level.value != 0
                                or not isinstance(fromlist, (ast.List, ast.Tuple))
                                or any(not isinstance(item, ast.Constant) or not isinstance(item.value, str) or item.value == '*' for item in fromlist.elts)):
                            self.error(path, node, '__import__ context/fromlist/level cannot be resolved safely')
                            continue
                        for item in fromlist.elts:
                            child = name + '.' + item.value
                            if self.resolve(child, roots):
                                self.dependency(path, node, child, roots)
                    self.dependency(path, node, name, roots)
                elif function.startswith('importlib.') and function != 'importlib.invalidate_caches':
                    self.error(path, node, f'unsupported dynamic loader {function}')
                elif function in {'eval', 'exec', 'runpy.run_path', 'runpy.run_module'}:
                    self.error(path, node, f'{function} cannot establish a static import boundary')
                elif function in {'getattr', 'setattr'}:
                    attribute = node.args[1] if len(node.args) > 1 else None
                    if (not isinstance(attribute, ast.Constant)
                            or attribute.value in {'__import__', 'import_module', 'path', 'load_module', 'exec_module'}):
                        self.error(path, node, f'{function} cannot establish a static import boundary')

    def check(self) -> list[str]:
        self.discover()
        if not self.sources and not self.errors:
            self.errors.append('helianthus/rootfs: no shipped Python sources found')
        for path in self.sources:
            self.visit(path)
        return self.errors


def main() -> int:
    checker = ImportBoundary(Path(__file__).resolve().parents[1])
    errors = checker.check()
    if errors:
        print('\n'.join(errors), file=sys.stderr)
        return 1
    print(f'Runtime import boundary OK: {len(checker.sources)} shipped Python sources parsed')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
