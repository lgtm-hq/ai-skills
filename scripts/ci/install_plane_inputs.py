#!/usr/bin/env python3
"""Match spike inputs and conservatively resolve their local Python dependencies."""

from __future__ import annotations

import ast
import fnmatch
import os
from pathlib import Path

MANIFEST = Path("research/install-plane-spike/harness-inputs.txt")
IGNORED = {
    ".git",
    ".venv",
    "node_modules",
    ".lintro",
    "__pycache__",
    "build",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
}
type Value = Path | str | int | None


def patterns(repo: Path) -> list[str]:
    """Read the committed repository-relative fnmatch patterns.

    Args:
        repo: Repository root.

    Returns:
        Nonempty patterns, excluding comments.
    """
    return [
        line.strip()
        for line in (repo / MANIFEST).read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]


def matches(path: str, globs: list[str]) -> bool:
    """Check a repository-relative path against the shared trigger list.

    Args:
        path: POSIX repository-relative filename.
        globs: Patterns from the manifest.

    Returns:
        Whether any pattern covers the path.
    """
    return any(fnmatch.fnmatchcase(path, pattern) for pattern in globs)


def _value(node: ast.AST, env: dict[str, Value], repo: Path) -> Value:
    """Interpret only literal path construction; never execute repository code.

    Args:
        node: Expression to resolve.
        env: Statically known bindings.
        repo: Base for relative literal paths.

    Returns:
        A literal value or None for a dynamic expression.
    """
    if isinstance(node, ast.Constant) and isinstance(node.value, (str, int)):
        return node.value
    if isinstance(node, ast.Name):
        return env.get(node.id)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
        left, right = _value(node.left, env, repo), _value(node.right, env, repo)
        if isinstance(left, Path) and isinstance(right, (str, Path)):
            return left / right
    if isinstance(node, ast.Attribute) and node.attr == "parent":
        parent = _value(node.value, env, repo)
        if isinstance(parent, Path):
            return parent.parent
    if isinstance(node, ast.Subscript) and isinstance(node.value, ast.Attribute):
        parent = _value(node.value.value, env, repo)
        index = _value(node.slice, env, repo)
        if (
            node.value.attr == "parents"
            and isinstance(parent, Path)
            and isinstance(index, int)
            and 0 <= index < len(parent.parents)
        ):
            return parent.parents[index]
    if isinstance(node, ast.Call):
        args = [_value(arg, env, repo) for arg in node.args]
        if (
            isinstance(node.func, ast.Name)
            and node.func.id in {"Path", "str"}
            and args
            and isinstance(args[0], (str, Path))
        ):
            if node.func.id == "str":
                return str(args[0])
            if all(isinstance(arg, (str, Path)) for arg in args):
                return repo.joinpath(*[str(arg) for arg in args])
        if isinstance(node.func, ast.Attribute):
            base = _value(node.func.value, env, repo)
            if isinstance(base, Path):
                if node.func.attr in {"resolve", "absolute"}:
                    return base.resolve()
                if node.func.attr == "joinpath" and all(
                    isinstance(arg, (str, Path)) for arg in args
                ):
                    return base.joinpath(*[str(arg) for arg in args])
                if node.func.attr == "with_name" and args and isinstance(args[0], str):
                    return base.with_name(args[0])
    return None


def local_inputs(repo: Path, entrypoints: set[Path]) -> set[Path]:
    """Follow AST imports, importlib/runpy literals and literal file references.

    Import lookup follows literal sys.path additions and repository module
    suffixes when a search path is dynamic. Imported path constants
    are propagated without importing or executing the modules. Fixture directory
    copies include all their files. Dynamic temporary/output paths are ignored.

    Args:
        repo: Absolute repository root.
        entrypoints: Harness tests, helpers, conftests and workflow script inputs.

    Returns:
        Resolved repository files in the transitive local input closure.
    """
    files: set[Path] = set()
    modules: dict[str, set[Path]] = {}
    for directory, dirs, names in os.walk(repo):
        dirs[:] = [name for name in dirs if name not in IGNORED]
        for name in names:
            path = Path(directory) / name
            files.add(path)
            if path.suffix == ".py":
                parts = list(path.relative_to(repo).with_suffix("").parts)
                if parts[-1] == "__init__":
                    parts.pop()
                for offset in range(len(parts)):
                    modules.setdefault(".".join(parts[offset:]), set()).add(path)

    contexts: dict[Path, dict[str, Value]] = {}
    dependencies: dict[Path, set[Path]] = {}

    def imports(
        name: str, path: Path, env: dict[str, Value], nodes: list[ast.Call]
    ) -> set[Path]:
        """Find local imports using explicit search paths before suffix fallback.

        Args:
            name: Imported module name.
            path: Importing source file.
            env: Known literal bindings.
            nodes: Source AST, including sys.path additions.

        Returns:
            Resolved local module files.
        """
        roots = [path.parent, repo, repo / "scripts"]
        for node in nodes:
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in {"syspath_prepend", "insert", "append"}
                and node.args
            ):
                directory = _value(node.args[-1], env, repo)
                if isinstance(directory, (str, Path)):
                    roots.insert(0, Path(directory))
        for root in roots:
            base = root.joinpath(*name.split("."))
            candidates = {base.with_suffix(".py"), base / "__init__.py"} & files
            if candidates:
                return candidates
        return modules.get(name, set())

    def context(path: Path) -> dict[str, Value]:
        """Resolve module bindings and queue its local dependencies.

        Args:
            path: Python source file.

        Returns:
            Known literal bindings, with cycles stopped at the current context.
        """
        if path in contexts:
            return contexts[path]
        env: dict[str, Value] = {"__file__": path}
        contexts[path] = env
        found = dependencies.setdefault(path, set())
        nodes = list(ast.walk(ast.parse(path.read_text(encoding="utf-8"))))
        path_calls = [
            node
            for node in nodes
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in {"syspath_prepend", "insert", "append"}
        ]
        for node in nodes:
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                names = [module, *[f"{module}.{alias.name}" for alias in node.names]]
                for imported in sorted(imports(module, path, env, path_calls)):
                    imported_env = context(imported)
                    for alias in node.names:
                        env[alias.asname or alias.name] = imported_env.get(alias.name)
            elif (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "import_module"
                and node.args
            ):
                name = _value(node.args[0], env, repo)
                if isinstance(name, str):
                    names = [name.lstrip(".")]
            for name in names:
                # Include package initializers as well as the imported leaf.
                parts = name.lstrip(".").split(".")
                for length in range(1, len(parts) + 1):
                    found.update(
                        imports(".".join(parts[:length]), path, env, path_calls)
                    )
        for node in nodes:
            if isinstance(node, (ast.Assign, ast.AnnAssign)):
                value = _value(node.value, env, repo) if node.value else None
                targets = (
                    node.targets if isinstance(node, ast.Assign) else [node.target]
                )
                for target in targets:
                    if isinstance(target, ast.Name) and value is not None:
                        env[target.id] = value
            value = _value(node, env, repo)
            if isinstance(value, Path) and value in files:
                found.add(value)
            if isinstance(node, ast.Call):
                function = node.func
                name = (
                    function.attr
                    if isinstance(function, ast.Attribute)
                    else (function.id if isinstance(function, ast.Name) else "")
                )
                if name in {"run_path", "spec_from_file_location", "open"}:
                    for arg in node.args:
                        literal = _value(arg, env, repo)
                        if isinstance(literal, str):
                            found.update(
                                candidate
                                for base in (repo, path.parent)
                                if (candidate := base / literal) in files
                            )
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "copytree"
            ):
                sources = [
                    *node.args[:1],
                    *[kw.value for kw in node.keywords if kw.arg == "src"],
                ]
                for source in sources:
                    directory = _value(source, env, repo)
                    if isinstance(directory, Path):
                        found.update(
                            file for file in files if file.is_relative_to(directory)
                        )
        return env

    resolved: set[Path] = set()
    pending = set(entrypoints)
    while pending:
        path = pending.pop()
        if path in resolved:
            continue
        resolved.add(path)
        if path.suffix == ".py":
            context(path)
            pending.update(dependencies[path] - resolved)
    return resolved
