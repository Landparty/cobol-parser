"""The canonical nested-statement-body API on the statement models.

``cobolparser/models/statements/base.py`` owns the one list of attributes
that hold a nested statement body (IF arms, inline PERFORM, every handler
clause, EVALUATE / SEARCH WHEN arms). Analyzers walk nested statements
through ``iter_clause_bodies()`` / ``walk_statements()`` instead of keeping
private attribute lists, which drifted (audit 2026-09-27 §3.5).

The guard tests here fail when a statement node class gains a statement-list
attribute the canonical list does not name -- statically (from the
annotations in each class's source) and dynamically (from every statement
the sample corpus parses into).
"""

from __future__ import annotations

import ast
import importlib
import inspect
import pkgutil
import re
import textwrap
from pathlib import Path
from typing import Any

import pytest

import cobolparser
from cobolparser import parse_cobol
from cobolparser.models.statements import (
    HANDLER_CLAUSE_ATTRS,
    HANDLER_CLAUSE_PAIRS,
    HANDLER_CLAUSE_PHRASES,
    NESTED_BODY_ATTRS,
    STATEMENT_LIST_ATTRS,
    WHEN_ARM_ATTRS,
    CobolStatement,
    WhenClause,
    iter_clause_bodies,
    walk_statements,
)

SAMPLES = Path(__file__).resolve().parents[1] / "samples"

#: An annotation naming a statement list or a WHEN arm.
_BODY_ANNOTATION_RE = re.compile(
    r"list\[[^\]]*\b(?:CobolStatement|\w+Statement|WhenClause)\b|\bWhenClause\b"
)


def _import_all_modules() -> None:
    for module in pkgutil.walk_packages(cobolparser.__path__, "cobolparser."):
        if module.name.startswith(
            ("cobolparser.mcp", "cobolparser.jcl", "cobolparser.cli")
        ) or module.name.endswith("__main__"):
            continue  # extras and entry points; no statement node classes there
        try:
            importlib.import_module(module.name)
        except ImportError:
            continue


def _all_statement_classes() -> list[type]:
    _import_all_modules()
    found: list[type] = []
    pending = [CobolStatement]
    while pending:
        cls = pending.pop()
        for sub in cls.__subclasses__():
            if sub not in found and sub.__module__.startswith("cobolparser."):
                found.append(sub)
                pending.append(sub)
    return found


def _annotated_body_attrs(cls: type) -> set[str]:
    try:
        source = inspect.getsource(cls)
    except (OSError, TypeError):
        return set()
    return _body_attrs_in_source(source)


def _body_attrs_in_source(source: str) -> set[str]:
    """``self.<name>: <annotation>`` assignments in *source* whose annotation
    is a statement list or a WHEN arm."""
    names: set[str] = set()
    for node in ast.walk(ast.parse(textwrap.dedent(source))):
        if (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Attribute)
            and isinstance(node.target.value, ast.Name)
            and node.target.value.id == "self"
            and _BODY_ANNOTATION_RE.search(ast.unparse(node.annotation))
        ):
            names.add(node.target.attr)
    return names


def _uncovered(classes: list[type]) -> dict[str, set[str]]:
    missing: dict[str, set[str]] = {}
    for cls in classes:
        extra = _annotated_body_attrs(cls) - set(NESTED_BODY_ATTRS)
        if extra:
            missing[f"{cls.__module__}.{cls.__qualname__}"] = extra
    return missing


class TestCanonicalListCoversEveryStatementClass:
    def test_static_annotations_are_covered(self) -> None:
        classes = _all_statement_classes()
        assert len(classes) > 50  # the scan really found the node classes
        assert _uncovered(classes) == {}, (
            "statement node attributes hold a nested statement body but are "
            "missing from NESTED_BODY_ATTRS in models/statements/base.py"
        )

    def test_guard_flags_a_new_clause_body(self) -> None:
        """The static scan does catch an attribute the list does not name."""
        source = """
            class NewVerbStatement(CobolStatement):
                def __init__(self, location):
                    super().__init__("NEWVERB", location)
                    self.on_new_condition: list[CobolStatement] | None = None
                    self.arms: list[WhenClause] = []
                    self.at_end_clause: list[CobolStatement] | None = None
                    self.names: list[str] = []
        """
        found = _body_attrs_in_source(source)
        assert found == {"on_new_condition", "arms", "at_end_clause"}
        assert found - set(NESTED_BODY_ATTRS) == {"on_new_condition", "arms"}

    def test_every_handler_attribute_is_declared_on_a_node(self) -> None:
        """No stale entry: every canonical attribute exists on some node."""
        declared: set[str] = set()
        for cls in _all_statement_classes():
            declared |= _annotated_body_attrs(cls)
        # SEARCH's WHEN arms are dicts (annotated list[dict[...]]).
        assert set(NESTED_BODY_ATTRS) - declared <= {"when_clauses"}

    @pytest.mark.parametrize(
        "path", sorted(SAMPLES.glob("*.cbl")), ids=lambda p: p.name
    )
    def test_parsed_statements_hold_bodies_only_in_listed_attrs(
        self, path: Path
    ) -> None:
        result = parse_cobol(path.read_text(encoding="utf-8", errors="replace"))
        if result.ast is None:
            pytest.skip("sample does not parse")
        for unit in result.ast.program_units():
            for stmt in unit.get_all_statements():
                for name, value in vars(stmt).items():
                    if name in ("children", "parent") or name.startswith("_"):
                        continue
                    items = value if isinstance(value, list) else [value]
                    holds_statements = any(
                        isinstance(item, CobolStatement) for item in items
                    )
                    holds_arms = any(
                        isinstance(item, WhenClause)
                        or (isinstance(item, dict) and "statements" in item)
                        for item in items
                    )
                    if holds_statements:
                        assert name in STATEMENT_LIST_ATTRS, (type(stmt), name)
                    if holds_arms:
                        assert name in WHEN_ARM_ATTRS, (type(stmt), name)


class TestCanonicalLists:
    def test_handler_lists_agree(self) -> None:
        flat = [attr for pair in HANDLER_CLAUSE_PAIRS for attr in pair]
        assert tuple(flat) == HANDLER_CLAUSE_ATTRS
        assert set(HANDLER_CLAUSE_PHRASES) == set(HANDLER_CLAUSE_ATTRS)
        assert len(set(NESTED_BODY_ATTRS)) == len(NESTED_BODY_ATTRS)

    def test_receive_and_eop_bodies_are_listed(self) -> None:
        # The bodies several private copies used to miss.
        for attr in ("not_at_eop_clause", "no_data_clause", "with_data_clause"):
            assert attr in HANDLER_CLAUSE_ATTRS


_PROGRAM = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. BODIES.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-MSG PIC X(10).
       01 WS-X PIC 9.
       01 WS-T.
          05 WS-E PIC X OCCURS 3 INDEXED BY WS-I.
       COMMUNICATION SECTION.
       CD IN-Q FOR INPUT.
          05 IN-STATUS PIC XX.
       PROCEDURE DIVISION.
       MAIN-PARA.
           IF WS-X = 1 DISPLAY 'THEN' ELSE DISPLAY 'ELSE' END-IF
           EVALUATE WS-X
               WHEN 1 DISPLAY 'W1'
               WHEN OTHER DISPLAY 'OTHER'
           END-EVALUATE
           SEARCH WS-E
               AT END DISPLAY 'AT-END'
               WHEN WS-E (WS-I) = 'X' DISPLAY 'S-WHEN'
           END-SEARCH
           PERFORM 2 TIMES DISPLAY 'LOOP' END-PERFORM
           ADD 1 TO WS-X ON SIZE ERROR DISPLAY 'SIZE' END-ADD
           RECEIVE IN-Q MESSAGE INTO WS-MSG
               NO DATA DISPLAY 'NO-DATA'
           END-RECEIVE
           STOP RUN.
"""


def _statements() -> list[Any]:
    result = parse_cobol(_PROGRAM)
    assert result.success, result.errors
    return list(result.ast.procedure_division.paragraphs[0].statements)


def _displayed(statements: Any) -> list[str]:
    return [
        s.operands[0].strip("'\"")
        for s in statements
        if s.statement_type == "DISPLAY" and s.operands
    ]


class TestIterClauseBodies:
    def test_shapes_and_kinds(self) -> None:
        if_stmt, evaluate, search, perform, add, receive, _ = _statements()
        assert [(b.attr, b.kind) for b in if_stmt.iter_clause_bodies()] == [
            ("then_statements", "branch"),
            ("else_statements", "branch"),
        ]
        bodies = list(evaluate.iter_clause_bodies())
        assert [(b.attr, b.position) for b in bodies] == [
            ("when_clauses", 1),
            ("default_when", None),
        ]
        assert bodies[0].clause is evaluate.when_clauses[0]
        assert bodies[1].clause is evaluate.default_when
        # SEARCH: AT END (written first) before the WHEN arms.
        assert [(b.attr, b.kind) for b in search.iter_clause_bodies()] == [
            ("at_end_clause", "handler"),
            ("when_clauses", "branch"),
        ]
        assert [b.kind for b in perform.iter_clause_bodies()] == ["loop"]
        assert [b.attr for b in add.iter_clause_bodies()] == ["on_size_error"]
        assert [b.attr for b in receive.iter_clause_bodies()] == ["no_data_clause"]

    def test_filters(self) -> None:
        _, _, search, perform, add, _, _ = _statements()
        assert [b.attr for b in search.iter_clause_bodies(include_handlers=False)] == [
            "when_clauses"
        ]
        assert list(perform.iter_clause_bodies(include_loops=False)) == []
        assert list(add.iter_clause_bodies(include_handlers=False)) == []

    def test_include_empty(self) -> None:
        if_stmt = parse_cobol(_PROGRAM.replace(" ELSE DISPLAY 'ELSE'", "")).ast
        first = if_stmt.procedure_division.paragraphs[0].statements[0]
        assert [b.attr for b in first.iter_clause_bodies()] == ["then_statements"]
        assert [b.attr for b in first.iter_clause_bodies(include_empty=True)] == [
            "then_statements",
            "else_statements",
        ]

    def test_iter_child_statements_and_plain_objects(self) -> None:
        if_stmt = _statements()[0]
        assert _displayed(if_stmt.iter_child_statements()) == ["THEN", "ELSE"]
        assert list(iter_clause_bodies(object())) == []


class TestWalkStatements:
    def test_every_body_in_source_order(self) -> None:
        assert _displayed(walk_statements(_statements())) == [
            "THEN",
            "ELSE",
            "W1",
            "OTHER",
            "AT-END",
            "S-WHEN",
            "LOOP",
            "SIZE",
            "NO-DATA",
        ]

    def test_without_handlers(self) -> None:
        assert _displayed(walk_statements(_statements(), include_handlers=False)) == [
            "THEN",
            "ELSE",
            "W1",
            "OTHER",
            "S-WHEN",
            "LOOP",
        ]

    def test_shared_node_yielded_once_and_deep_nesting(self) -> None:
        depth = 150
        nested = "\n".join(
            [f"           IF WS-X = {i % 9} " for i in range(depth)]
            + ["               DISPLAY 'DEEP'"]
            + ["           END-IF" for _ in range(depth)]
        )
        source = _PROGRAM.split("       MAIN-PARA.\n")[0] + (
            f"       MAIN-PARA.\n{nested}\n           STOP RUN.\n"
        )
        result = parse_cobol(source)
        statements = result.ast.procedure_division.paragraphs[0].statements
        walked = list(walk_statements(statements + statements))
        assert len(walked) == len({id(s) for s in walked})
        assert _displayed(walked) == ["DEEP"]
