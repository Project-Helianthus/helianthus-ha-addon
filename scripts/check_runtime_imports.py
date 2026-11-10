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
        if isinstance(node, ast.NamedExpr):
            return ImportBoundary.symbol(node.value, aliases)
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
        # A namespace directory belongs to the same import tree as entrypoints
        # above it, even though it has no package initializer.
        for source in self.sources:
            candidate = source.parent
            while (candidate / '__init__.py').is_file():
                candidate = candidate.parent
            if package_root.is_relative_to(candidate):
                package_root = candidate
        roots = [package_root]
        roots += sorted(p for p in self.rootfs.rglob('*') if p.is_dir() and p.name in {'site-packages', 'dist-packages'})
        if (package_root == path.parent and not (package_root / '__init__.py').is_file()
                and not any(path.is_relative_to(root) for root in roots[1:])):
            # An isolated namespace source may have no importing entrypoint in
            # this tree. Its relative imports still establish sibling context.
            try:
                with tokenize.open(path) as stream:
                    tree = ast.parse(stream.read())
                level = max((node.level for node in ast.walk(tree)
                             if isinstance(node, ast.ImportFrom)), default=0)
                for _ in range(level):
                    package_root = package_root.parent
                if package_root.is_relative_to(self.rootfs):
                    roots[0] = package_root
            except (OSError, SyntaxError, UnicodeError, LookupError):
                pass  # visit() reports invalid sources.
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

    @staticmethod
    def package_context(path: Path, roots: list[Path]) -> tuple[list[str], Path]:
        for root in sorted(roots, key=lambda item: len(item.parts)):
            if path.parent.is_relative_to(root):
                return list(path.parent.relative_to(root).parts), root
        return [], path.parent

    def loader_alias(self, value: str, roots: list[Path], seen: frozenset = frozenset()) -> str:
        """Follow simple shipped re-exports without executing their modules."""
        parts = value.split('.')
        for split in range(len(parts) - 1, 0, -1):
            sources = self.resolve('.'.join(parts[:split]), roots)
            if not sources or not sources[-1].is_file():
                continue
            source = sources[-1]
            key = (source, tuple(parts[split:]), tuple(roots))
            if key in seen or not source.resolve().is_relative_to(self.rootfs.resolve()):
                return value
            try:
                with tokenize.open(source) as stream:
                    tree = ast.parse(stream.read())
            except (OSError, SyntaxError, UnicodeError, LookupError):
                return value  # The ordinary dependency traversal reports this.
            aliases = self.reexport_aliases(source, tree, roots)
            binding = aliases.get(parts[split])
            if binding:
                return self.loader_alias('.'.join([binding] + parts[split + 1:]), roots, seen | {key})
            return value
        return value

    @staticmethod
    def assignment(node: ast.AST) -> tuple[list[ast.AST], ast.AST | None]:
        if isinstance(node, ast.Assign):
            return node.targets, node.value
        if isinstance(node, (ast.AnnAssign, ast.NamedExpr)):
            return [node.target], node.value
        return [], None

    def import_bindings(self, node: ast.AST, package: list[str]):
        if isinstance(node, ast.Import):
            return [(item.asname or item.name.split('.')[0],
                     item.name if item.asname else item.name.split('.')[0])
                    for item in node.names]
        if not isinstance(node, ast.ImportFrom) or node.level > len(package):
            return []
        prefix = package[:len(package) - node.level + 1] if node.level else []
        module = '.'.join(prefix + ([node.module] if node.module else []))
        return [(item.asname or item.name, module + '.' + item.name)
                for item in node.names]

    def reexport_aliases(self, source: Path, tree: ast.AST, roots: list[Path]):
        aliases = {}
        package, _ = self.package_context(source, roots)
        # Only module-scope bindings can be imported by another shipped source.
        nodes, _ = self.scope_nodes(tree)
        for node in nodes:
            aliases.update(self.import_bindings(node, package))
        for _ in range(len(nodes)):
            changed = False
            for node in nodes:
                targets, expression = self.assignment(node)
                if expression is None:
                    continue
                binding = self.symbol(expression, aliases)
                for target in targets:
                    if binding and isinstance(target, ast.Name) and aliases.get(target.id) != binding:
                        aliases[target.id] = binding
                        changed = True
            if not changed:
                break
        return aliases

    @staticmethod
    def scope_nodes(scope: ast.AST) -> tuple[list[ast.AST], list[ast.AST]]:
        nodes, children = [], []
        pending = list(ast.iter_child_nodes(scope))
        while pending:
            node = pending.pop(0)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
                children.append(node)
            else:
                nodes.append(node)
                pending.extend(ast.iter_child_nodes(node))
        return nodes, children

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
        self.visit_scope(path, tree, roots, {}, {})

    def bind_imports(self, path, nodes, roots, aliases, package):
        local = {}
        for node in nodes:
            for name, binding in self.import_bindings(node, package):
                if binding in {'importlib.*', 'runpy.*', 'builtins.*'}:
                    self.error(path, node, f'wildcard import from dynamic-loader module {binding[:-2]}')
                value = self.loader_alias(binding, roots)
                if name in local and local[name] != value:
                    self.error(path, node, f'ambiguous import alias {name}')
                local[name] = value
        aliases.update(local)

    def propagate_aliases(self, nodes, roots, aliases):
        # Propagate aliases conservatively, including aliases of dynamic loaders.
        for _ in range(len(nodes)):
            changed = False
            for node in nodes:
                targets, expression = self.assignment(node)
                if expression is not None:
                    value = self.loader_alias(self.symbol(expression, aliases), roots)
                    if value in {'importlib', 'builtins', 'importlib.import_module',
                                 'builtins.__import__', '__import__', 'sys.path', 'sys',
                                 'runpy', 'runpy.run_path', 'runpy.run_module',
                                 'exec', 'eval', 'getattr', 'setattr',
                                 'builtins.exec', 'builtins.eval', 'builtins.getattr', 'builtins.setattr'}:
                        for target in targets:
                            if isinstance(target, ast.Name) and aliases.get(target.id) != value:
                                aliases[target.id] = value
                                changed = True
            if not changed:
                break

    def safe_search_paths(self, nodes, roots, aliases):
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
        return list(dict.fromkeys(roots)), safe_paths

    def visit_scope(self, path, scope, roots, inherited, enclosing):
        nodes, children = self.scope_nodes(scope)
        aliases = dict(inherited)
        package, _ = self.package_context(path, roots)
        self.bind_imports(path, nodes, roots, aliases, package)
        self.propagate_aliases(nodes, roots, aliases)
        roots, safe_paths = self.safe_search_paths(nodes, list(roots), aliases)
        for node in nodes:
            symbol = self.symbol(node, aliases)
            if symbol == 'sys.path' and id(node) not in safe_paths:
                # Runtime-computed search paths cannot establish packaged provenance.
                self.error(path, node, 'sys.path access cannot establish a safe shipped import path')
            self.check_import(path, node, roots)
            if isinstance(node, ast.Call):
                self.check_call(path, node, roots, aliases)
        # Class namespaces are visible in the class body, but are not enclosing
        # lexical scopes for methods or nested classes.
        lexical = enclosing if isinstance(scope, ast.ClassDef) else aliases
        for child in children:
            inherited = aliases if not isinstance(scope, ast.ClassDef) else enclosing
            self.visit_scope(path, child, roots, inherited, lexical)

    def check_import(self, path, node, roots):
        package, parent = self.package_context(path, roots)
        if isinstance(node, ast.Import):
            for item in node.names:
                self.dependency(path, node, item.name, roots)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                if node.level > len(package):
                    self.error(path, node, 'relative import escapes its shipped package')
                    return
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

    def check_call(self, path, node, roots, aliases):
        function = self.loader_alias(self.symbol(node.func, aliases), roots)
        if function in {'builtins.exec', 'builtins.eval', 'builtins.getattr', 'builtins.setattr'}:
            function = function.removeprefix('builtins.')
        if function in {'importlib.import_module', 'builtins.__import__', '__import__'}:
            self.check_dynamic_import(path, node, function, roots)
        elif function.startswith('importlib.') and function != 'importlib.invalidate_caches':
            self.error(path, node, f'unsupported dynamic loader {function}')
        elif function in {'eval', 'exec', 'runpy.run_path', 'runpy.run_module'}:
            self.error(path, node, f'{function} cannot establish a static import boundary')
        elif function in {'getattr', 'setattr'}:
            attribute = node.args[1] if len(node.args) > 1 else None
            if (not isinstance(attribute, ast.Constant)
                    or attribute.value in {'__import__', 'import_module', 'path', 'load_module', 'exec_module'}):
                self.error(path, node, f'{function} cannot establish a static import boundary')

    def check_dynamic_import(self, path, node, function, roots):
        argument = node.args[0] if node.args else next((k.value for k in node.keywords if k.arg == 'name'), None)
        if not isinstance(argument, ast.Constant) or not isinstance(argument.value, str):
            self.error(path, node, 'dynamic import destination cannot be resolved safely')
            return
        name = argument.value
        if name.startswith('.'):
            name = self.relative_dynamic_name(path, node, function, name, roots)
            if name is None:
                return
        if function in {'__import__', 'builtins.__import__'}:
            if not self.check_fromlist(path, node, name, roots):
                return
        self.dependency(path, node, name, roots)

    def relative_dynamic_name(self, path, node, function, name, roots):
        package, _ = self.package_context(path, roots)
        anchor = node.args[1] if len(node.args) > 1 else next((k.value for k in node.keywords if k.arg == 'package'), None)
        if isinstance(anchor, ast.Name) and anchor.id == '__package__' and package:
            anchor = ast.Constant(value='.'.join(package))
        if function != 'importlib.import_module' or not isinstance(anchor, ast.Constant) or not isinstance(anchor.value, str):
            self.error(path, node, f'unresolved relative dynamic import {name}')
            return None
        level = len(name) - len(name.lstrip('.'))
        parts = anchor.value.split('.')
        if level > len(parts):
            self.error(path, node, f'relative dynamic import escapes package: {name}')
            return None
        return '.'.join(parts[:len(parts) - level + 1] + ([name[level:]] if name[level:] else []))

    def check_fromlist(self, path, node, name, roots):
        # Non-default fromlist/level can add imports beyond the literal name.
        if len(node.args) > 5 or any(k.arg not in {'name', 'globals', 'locals', 'fromlist', 'level'} for k in node.keywords):
            self.error(path, node, '__import__ context/fromlist/level cannot be resolved safely')
            return False
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
            return False
        for item in fromlist.elts:
            child = name + '.' + item.value
            if self.resolve(child, roots):
                self.dependency(path, node, child, roots)
        return True

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
