"""Stage 2: import graph and symbol table via stdlib ast."""
from __future__ import annotations

import ast
from pathlib import Path

from . import _artifacts

ROOT_PACKAGE = "plex_renamer"


def _module_name(rel_posix: str) -> str:
    parts = list(Path(rel_posix).with_suffix("").parts)
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def _resolve_relative(current_module: str, is_init: bool, level: int, module: str | None) -> str | None:
    parts = current_module.split(".")
    drop = level - 1 if is_init else level
    if drop > 0:
        if drop >= len(parts):
            return None
        parts = parts[: len(parts) - drop]
    if module:
        parts = parts + module.split(".")
    return ".".join(parts) or None


def _signature(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    a = node.args
    parts = [arg.arg for arg in a.posonlyargs + a.args]
    if a.vararg is not None:
        parts.append("*" + a.vararg.arg)
    elif a.kwonlyargs:
        parts.append("*")
    parts += [arg.arg for arg in a.kwonlyargs]
    if a.kwarg is not None:
        parts.append("**" + a.kwarg.arg)
    sig = f"{node.name}({', '.join(parts)})"
    if node.returns is not None:
        sig += f" -> {ast.unparse(node.returns)}"
    return sig


def _first_doc_line(node) -> str:
    doc = ast.get_docstring(node)
    return doc.splitlines()[0].strip() if doc else ""


def _symbols(tree: ast.Module) -> list[dict]:
    out = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            out.append({
                "name": node.name, "kind": "function", "line": node.lineno,
                "signature": _signature(node), "doc": _first_doc_line(node),
                "public": not node.name.startswith("_"), "imported_by": [],
            })
        elif isinstance(node, ast.ClassDef):
            out.append({
                "name": node.name, "kind": "class", "line": node.lineno,
                "signature": node.name, "doc": _first_doc_line(node),
                "public": not node.name.startswith("_"), "imported_by": [],
            })
    return out


def _strongly_connected(adj: dict[str, list[str]]) -> list[list[str]]:
    """Tarjan SCC; returns components of size > 1 (cycles)."""
    index: dict[str, int] = {}
    lowlink: dict[str, int] = {}
    on_stack: set[str] = set()
    stack: list[str] = []
    counter = [0]
    cycles: list[list[str]] = []

    def strongconnect(v: str) -> None:
        index[v] = lowlink[v] = counter[0]
        counter[0] += 1
        stack.append(v)
        on_stack.add(v)
        for w in adj.get(v, []):
            if w not in adj:
                continue
            if w not in index:
                strongconnect(w)
                lowlink[v] = min(lowlink[v], lowlink[w])
            elif w in on_stack:
                lowlink[v] = min(lowlink[v], index[w])
        if lowlink[v] == index[v]:
            comp = []
            while True:
                w = stack.pop()
                on_stack.discard(w)
                comp.append(w)
                if w == v:
                    break
            if len(comp) > 1:
                cycles.append(sorted(comp))

    import sys
    old_limit = sys.getrecursionlimit()
    sys.setrecursionlimit(max(old_limit, 10000))
    try:
        for v in adj:
            if v not in index:
                strongconnect(v)
    finally:
        sys.setrecursionlimit(old_limit)
    return sorted(cycles)


def build_graph(repo_root: Path, inventory: dict) -> dict:
    modules: dict[str, dict] = {}
    trees: dict[str, ast.Module] = {}
    for rec in inventory["python_files"]:
        name = _module_name(rec["path"])
        try:
            tree = ast.parse((repo_root / rec["path"]).read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            tree = ast.Module(body=[], type_ignores=[])
        trees[name] = tree
        modules[name] = {
            "path": rec["path"], "doc": _first_doc_line(tree),
            "imports": [], "fan_in": 0, "fan_out": 0, "symbols": _symbols(tree),
            "external_imports": [],
        }

    # symbol lookup for imported_by attribution
    sym_index = {(mod, s["name"]): s for mod, m in modules.items() for s in m["symbols"]}

    for name, tree in trees.items():
        is_init = modules[name]["path"].endswith("__init__.py")
        internal: set[str] = set()
        external: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.startswith(ROOT_PACKAGE):
                        internal.add(alias.name)
                    else:
                        external.add(alias.name.split(".")[0])
            elif isinstance(node, ast.ImportFrom):
                if node.level == 0 and node.module and not node.module.startswith(ROOT_PACKAGE):
                    external.add(node.module.split(".")[0])
                    continue
                target = (node.module if node.level == 0
                          else _resolve_relative(name, is_init, node.level, node.module))
                if not target or not target.startswith(ROOT_PACKAGE):
                    continue
                for alias in node.names:
                    # `from pkg import submodule` imports a module, not a symbol
                    if f"{target}.{alias.name}" in modules:
                        internal.add(f"{target}.{alias.name}")
                        continue
                    internal.add(target)
                    sym = sym_index.get((target, alias.name))
                    if sym is not None and name not in sym["imported_by"]:
                        sym["imported_by"].append(name)
        resolved = sorted(m for m in internal if m in modules and m != name)
        modules[name]["imports"] = resolved
        modules[name]["fan_out"] = len(resolved)
        modules[name]["external_imports"] = sorted(external)

    for name, mod in modules.items():
        for target in mod["imports"]:
            modules[target]["fan_in"] += 1

    for mod in modules.values():
        for sym in mod["symbols"]:
            sym["imported_by"].sort()

    adj = {name: mod["imports"] for name, mod in modules.items()}
    return {"modules": modules, "cycles": _strongly_connected(adj)}


def run(repo_root: Path, options) -> int:
    inventory = _artifacts.read_artifact(repo_root, "inventory")
    graph = build_graph(repo_root, inventory)
    _artifacts.write_artifact(repo_root, "graph", graph)
    print(f"graph: {len(graph['modules'])} modules, {len(graph['cycles'])} cycles")
    return 0
