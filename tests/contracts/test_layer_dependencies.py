"""The package's layers depend one way: each layer imports only layers below it.

The pipeline is preprocess -> lex -> parse -> AST, with analyzers, generators
and the front ends (scan, config, CLI, MCP) reading the AST. This test reads
every ``import`` in ``cobolparser/`` (module level, inside functions, and
under ``TYPE_CHECKING``) with :mod:`ast`, maps each module to its layer, and
fails on an import that points up the stack, or on a cycle between layers.

A handful of upward imports are known and deliberate; each sits in
``KNOWN_UPWARD`` with the reason it exists. An entry that no longer matches
any import also fails, so the list shrinks when one is fixed.

Why a test and not a convention: the analysis <-> generators cycle broke
first-touch imports with "partially initialized module" three times before
the package ``__init__`` files went lazy (see ``cobolparser/generators/
__init__.py``). This keeps new back-edges from appearing silently.
"""

from __future__ import annotations

import ast
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

import pytest

pytestmark = pytest.mark.contract

PACKAGE = "cobolparser"
ROOT = Path(__file__).resolve().parents[2] / PACKAGE

#: Layer of each top-level component of ``cobolparser`` (a subpackage or a
#: top-level module; ``""`` is the package facade, ``cobolparser/__init__.py``).
#: A module may import its own component, and any component on a lower or
#: equal layer; equal layers must still not form a cycle.
LAYERS: dict[str, int] = {
    # Leaves: no cobolparser imports, or only other leaves.
    "_errors": 0,
    "_lines": 0,
    "_literals": 0,
    "_storage": 0,
    "_file_limits": 0,
    "_source_directive": 0,
    "_version": 0,
    "profiling": 0,
    "jcl": 0,
    "definitions": 1,
    "plugins": 1,
    # The AST.
    "models": 2,
    # Tokens and dialect tables.
    "lexer": 3,
    "dialects": 3,
    # Source preprocessing (tokenizes COPY / REPLACE text) and parser core.
    "preprocess": 4,
    "core": 4,
    # Parsing.
    "parsers": 5,
    "parser": 6,
    "batch": 7,
    # Record layout: byte facts both analyzers and generators read.
    "layout": 8,
    # Readers of the AST.
    "analysis": 9,
    "generators": 10,
    # Multi-file analysis and front ends.
    "_facts_cache": 11,
    "scan": 12,
    "config": 13,
    "mcp": 14,
    "cli": 15,
    "": 16,
    "__main__": 17,
}


@dataclass(frozen=True)
class Known:
    """An upward import that is allowed, with the reason it exists."""

    source: str  # module prefix doing the import
    target: str  # module prefix imported
    eager_ok: bool  # may it run at module import time?
    reason: str


KNOWN_UPWARD: tuple[Known, ...] = (
    Known(
        "cobolparser.models.program",
        "cobolparser.analysis",
        eager_ok=False,
        reason="CobolProgram convenience methods (find_dead_code(), the "
        "intrinsic-function list) call analyzers; public API.",
    ),
    Known(
        "cobolparser.lexer",
        "cobolparser.preprocess",
        eager_ok=False,
        reason="tokenize_cobol() normalizes fixed-format source before "
        "lexing, and fixed-format comment tokens use the indicator sets.",
    ),
    Known(
        "cobolparser.preprocess.copybook_expander",
        "cobolparser.parser",
        eager_ok=False,
        reason="parse_cobol_with_expansion() is an expand-then-parse "
        "orchestrator, and the debug-lines warning is shared with the parser.",
    ),
)


@dataclass(frozen=True)
class Edge:
    source: str
    target: str
    line: int
    kind: str  # "eager", "lazy" (inside a function) or "typing"


def _module_name(path: Path) -> str:
    rel = path.relative_to(ROOT.parent).with_suffix("")
    parts = list(rel.parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _component(module: str) -> str:
    parts = module.split(".")
    return parts[1] if len(parts) > 1 else ""


def _resolve(module: str, is_pkg: bool, level: int, name: str | None) -> str:
    """The absolute name a relative ``from`` import in *module* refers to."""
    base = module.split(".")
    if not is_pkg:
        base = base[:-1]
    if level > 1:
        base = base[: len(base) - (level - 1)]
    return ".".join(base + ([name] if name else []))


def _imports_of(module: str, path: Path, modules: set[str]) -> list[Edge]:
    """Every cobolparser import in *path*, tagged eager / lazy / typing.

    ``from pkg import sub`` where ``pkg.sub`` is a module is an edge to that
    submodule, not to ``pkg`` (``from . import _help`` names a sibling)."""
    is_pkg = path.name == "__init__.py"
    edges: list[Edge] = []

    def visit(node: ast.AST, kind: str) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.If) and "TYPE_CHECKING" in ast.unparse(child.test):
                for stmt in child.body:
                    visit(ast.Module(body=[stmt], type_ignores=[]), "typing")
                for stmt in child.orelse:
                    visit(ast.Module(body=[stmt], type_ignores=[]), kind)
            elif isinstance(child, ast.Import):
                for alias in child.names:
                    if alias.name.split(".")[0] == PACKAGE:
                        edges.append(Edge(module, alias.name, child.lineno, kind))
            elif isinstance(child, ast.ImportFrom):
                target = (
                    _resolve(module, is_pkg, child.level, child.module)
                    if child.level
                    else child.module or ""
                )
                if target.split(".")[0] != PACKAGE:
                    continue
                for alias in child.names:
                    sub = f"{target}.{alias.name}"
                    edges.append(
                        Edge(
                            module,
                            sub if sub in modules else target,
                            child.lineno,
                            kind,
                        )
                    )
            elif isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef):
                visit(child, "lazy" if kind == "eager" else kind)
            else:
                visit(child, kind)

    visit(ast.parse(path.read_text(encoding="utf-8"), filename=str(path)), "eager")
    return edges


def _collect_edges() -> list[Edge]:
    modules = {_module_name(p): p for p in ROOT.rglob("*.py")}
    return [
        edge
        for name, path in sorted(modules.items())
        for edge in _imports_of(name, path, set(modules))
    ]


EDGES = _collect_edges()


def _matches(known: Known, edge: Edge) -> bool:
    def under(module: str, prefix: str) -> bool:
        return module == prefix or module.startswith(prefix + ".")

    return under(edge.source, known.source) and under(edge.target, known.target)


def _allowed(edge: Edge) -> bool:
    return any(
        _matches(k, edge) and (k.eager_ok or edge.kind != "eager") for k in KNOWN_UPWARD
    )


def test_every_component_has_a_layer() -> None:
    components = {_component(e.source) for e in EDGES} | {
        _component(_module_name(p)) for p in ROOT.rglob("*.py")
    }
    missing = sorted(c for c in components if c not in LAYERS)
    assert not missing, f"add these to LAYERS: {missing}"


def test_imports_point_down_the_layers() -> None:
    upward = []
    for edge in EDGES:
        src, dst = _component(edge.source), _component(edge.target)
        if src == dst or dst not in LAYERS or src not in LAYERS:
            continue
        if LAYERS[dst] > LAYERS[src] and not _allowed(edge):
            upward.append(
                f"{edge.source}:{edge.line} imports {edge.target} ({edge.kind}): "
                f"{src or 'cobolparser'} (layer {LAYERS[src]}) -> "
                f"{dst or 'cobolparser'} (layer {LAYERS[dst]})"
            )
    assert not upward, "upward imports:\n" + "\n".join(upward)


def test_no_cycle_between_components() -> None:
    graph: dict[str, set[str]] = defaultdict(set)
    for edge in EDGES:
        src, dst = _component(edge.source), _component(edge.target)
        if src != dst and not _allowed(edge):
            graph[src].add(dst)

    seen: set[str] = set()
    stack: list[str] = []

    def walk(node: str) -> list[str] | None:
        if node in stack:
            return stack[stack.index(node) :] + [node]
        if node in seen:
            return None
        seen.add(node)
        stack.append(node)
        for nxt in sorted(graph.get(node, ())):
            cycle = walk(nxt)
            if cycle:
                return cycle
        stack.pop()
        return None

    for start in sorted(graph):
        cycle = walk(start)
        assert cycle is None, "cycle: " + " -> ".join(c or "cobolparser" for c in cycle)


@pytest.mark.parametrize("known", KNOWN_UPWARD, ids=lambda k: f"{k.source}->{k.target}")
def test_known_upward_import_still_exists(known: Known) -> None:
    """A fixed exception must leave the list, so it cannot quietly return."""
    assert any(_matches(known, e) for e in EDGES), (
        f"{known.source} no longer imports {known.target}: "
        "remove it from KNOWN_UPWARD"
    )


def test_no_eager_cycle_between_modules() -> None:
    """No two modules import each other at module load, directly or around
    a loop. Such a loop works in one import order and fails with "partially
    initialized module" in another: ``preprocess/__init__`` re-exported
    ``copybook_expander``, which imported names back from
    ``preprocess/__init__`` instead of from ``_normalize``. (A package
    ``__init__`` importing its own submodules is fine; the submodule
    importing names back from the package is the loop.)"""
    modules = {_module_name(p) for p in ROOT.rglob("*.py")}

    def deepest(target: str) -> str:
        while target not in modules and "." in target:
            target = target.rsplit(".", 1)[0]
        return target

    graph: dict[str, set[str]] = defaultdict(set)
    for edge in EDGES:
        if edge.kind == "eager":
            target = deepest(edge.target)
            if target != edge.source:
                graph[edge.source].add(target)

    # Iterative Tarjan: any strongly connected component of size > 1 is a loop.
    index: dict[str, int] = {}
    low: dict[str, int] = {}
    on_stack: set[str] = set()
    stack: list[str] = []
    loops: list[list[str]] = []
    counter = 0
    for root in sorted(graph):
        if root in index:
            continue
        work = [(root, iter(sorted(graph[root])))]
        index[root] = low[root] = counter
        counter += 1
        stack.append(root)
        on_stack.add(root)
        while work:
            node, children = work[-1]
            child = next(children, None)
            if child is not None:
                if child not in index:
                    index[child] = low[child] = counter
                    counter += 1
                    stack.append(child)
                    on_stack.add(child)
                    work.append((child, iter(sorted(graph.get(child, ())))))
                elif child in on_stack:
                    low[node] = min(low[node], index[child])
                continue
            work.pop()
            if work:
                low[work[-1][0]] = min(low[work[-1][0]], low[node])
            if low[node] == index[node]:
                component = []
                while True:
                    member = stack.pop()
                    on_stack.discard(member)
                    component.append(member)
                    if member == node:
                        break
                if len(component) > 1:
                    loops.append(sorted(component))
    assert not loops, "eager import loops:\n" + "\n".join(map(str, loops))
