"""Stage 2: import graph and symbol table via stdlib ast."""
from __future__ import annotations

import ast
import tomllib
from pathlib import Path

from . import _artifacts

ROOT_PACKAGE = "plex_renamer"


def _in_root_package(module: str) -> bool:
    return module == ROOT_PACKAGE or module.startswith(ROOT_PACKAGE + ".")


def _module_name(rel_posix: str) -> str:
    parts = list(Path(rel_posix).with_suffix("").parts)
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


_DOTTED_EFFECTS = {
    "os.rename": "file-move", "os.replace": "file-move", "shutil.move": "file-move",
    "os.remove": "file-delete", "os.unlink": "file-delete", "os.rmdir": "file-delete",
    "shutil.rmtree": "file-delete",
    "shutil.copy": "file-write", "shutil.copy2": "file-write",
    "shutil.copyfile": "file-write", "shutil.copytree": "file-write",
    "os.makedirs": "file-write", "os.mkdir": "file-write",
    "os.system": "subprocess", "subprocess.run": "subprocess",
    "subprocess.Popen": "subprocess", "subprocess.call": "subprocess",
    "subprocess.check_call": "subprocess", "subprocess.check_output": "subprocess",
    "os.getenv": "env",
}
_METHOD_EFFECTS = {
    "write_text": "file-write", "write_bytes": "file-write",
    "touch": "file-write", "mkdir": "file-write",
    "rename": "file-move",
    "unlink": "file-delete", "rmdir": "file-delete",
}
_NETWORK_IMPORTS = {"requests", "urllib", "urllib3", "http", "socket"}
_WRITE_MODE_CHARS = set("wax+")


def _dotted_name(node: ast.AST) -> str | None:
    parts: list[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
        return ".".join(reversed(parts))
    return None


def _open_mode(call: ast.Call) -> str:
    mode = ""
    if len(call.args) >= 2 and isinstance(call.args[1], ast.Constant) and isinstance(call.args[1].value, str):
        mode = call.args[1].value
    for kw in call.keywords:
        if kw.arg == "mode" and isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str):
            mode = kw.value.value
    return mode


def _effects(tree: ast.Module, external_imports: list[str]) -> list[str]:
    found: set[str] = set()
    if set(external_imports) & _NETWORK_IMPORTS:
        found.add("network")
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            dotted = _dotted_name(node.func)
            if dotted in _DOTTED_EFFECTS:
                found.add(_DOTTED_EFFECTS[dotted])
            elif isinstance(node.func, ast.Attribute) and node.func.attr in _METHOD_EFFECTS:
                found.add(_METHOD_EFFECTS[node.func.attr])
            elif (isinstance(node.func, ast.Attribute) and node.func.attr == "replace"
                  and len(node.args) == 1):
                found.add("file-move")
            elif isinstance(node.func, ast.Name) and node.func.id == "open":
                if _WRITE_MODE_CHARS & set(_open_mode(node)):
                    found.add("file-write")
        elif isinstance(node, ast.Attribute):
            if node.attr == "environ" and isinstance(node.value, ast.Name) and node.value.id == "os":
                found.add("env")
    return sorted(found)


def _entrypoint_modules(repo_root: Path, module_names: set[str]) -> set[str]:
    """Modules runnable directly: dunder-main files and [project.scripts] targets."""
    eps = {name for name in module_names
           if name == "__main__" or name.endswith(".__main__")}
    pyproject = repo_root / "pyproject.toml"
    if not pyproject.exists():
        return eps
    try:
        data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
        scripts = data.get("project", {}).get("scripts", {})
        targets = scripts.values() if isinstance(scripts, dict) else []
        for target in targets:
            if not isinstance(target, str):
                continue
            module = target.split(":", 1)[0].strip()
            if module in module_names:
                eps.add(module)
    except Exception:
        return eps
    return eps


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


def _reexport_map(modules: dict[str, dict], trees: dict) -> dict[tuple[str, str], tuple[str, str]]:
    """(module, exported name) -> (origin module, origin name) for __init__ re-exports."""
    reexports: dict[tuple[str, str], tuple[str, str]] = {}
    for name, tree in trees.items():
        if not modules[name]["path"].endswith("__init__.py"):
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom):
                continue
            target = (node.module if node.level == 0
                      else _resolve_relative(name, True, node.level, node.module))
            if not target or not _in_root_package(target):
                continue
            for alias in node.names:
                reexports[(name, alias.asname or alias.name)] = (target, alias.name)
    return reexports


def _resolve_symbol(sym_index: dict, reexports: dict, target: str, name: str):
    """Resolve (target, name) through __init__ re-export chains: origin plus up to 4 hops."""
    for _ in range(5):
        sym = sym_index.get((target, name))
        if sym is not None:
            return sym
        step = reexports.get((target, name))
        if step is None:
            return None
        target, name = step
    return None


def build_graph(repo_root: Path, inventory: dict) -> dict:
    modules: dict[str, dict] = {}
    trees: dict[str, ast.Module] = {}
    for rec in inventory["python_files"]:
        name = _module_name(rec["path"])
        try:
            tree = ast.parse((repo_root / rec["path"]).read_text(encoding="utf-8", errors="replace"))
        except SyntaxError as exc:
            line = exc.lineno or "?"
            raise RuntimeError(f"cannot parse {rec['path']}:{line}: {exc.msg}") from exc
        trees[name] = tree
        modules[name] = {
            "path": rec["path"], "doc": _first_doc_line(tree),
            "imports": [], "fan_in": 0, "fan_out": 0, "symbols": _symbols(tree),
            "external_imports": [], "effects": [],
        }

    # symbol lookup for imported_by attribution
    sym_index = {(mod, s["name"]): s for mod, m in modules.items() for s in m["symbols"]}
    reexports = _reexport_map(modules, trees)

    for name, tree in trees.items():
        is_init = modules[name]["path"].endswith("__init__.py")
        internal: set[str] = set()
        external: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if _in_root_package(alias.name):
                        internal.add(alias.name)
                    else:
                        external.add(alias.name.split(".")[0])
            elif isinstance(node, ast.ImportFrom):
                if node.level == 0 and node.module and not _in_root_package(node.module):
                    external.add(node.module.split(".")[0])
                    continue
                target = (node.module if node.level == 0
                          else _resolve_relative(name, is_init, node.level, node.module))
                if not target or not _in_root_package(target):
                    continue
                for alias in node.names:
                    # `from pkg import submodule` imports a module, not a symbol
                    if f"{target}.{alias.name}" in modules:
                        internal.add(f"{target}.{alias.name}")
                        continue
                    internal.add(target)
                    sym = _resolve_symbol(sym_index, reexports, target, alias.name)
                    if sym is not None and name not in sym["imported_by"]:
                        sym["imported_by"].append(name)
        resolved = sorted(m for m in internal if m in modules and m != name)
        modules[name]["imports"] = resolved
        modules[name]["fan_out"] = len(resolved)
        modules[name]["external_imports"] = sorted(external)
        modules[name]["effects"] = _effects(tree, modules[name]["external_imports"])

    for name, mod in modules.items():
        for target in mod["imports"]:
            modules[target]["fan_in"] += 1

    entrypoints = _entrypoint_modules(repo_root, set(modules))
    for name, mod in modules.items():
        mod["entrypoint"] = name in entrypoints

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
