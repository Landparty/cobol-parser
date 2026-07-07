"""Regression tests for EVALUATE WHEN-clause AST-child registration.

Broken behavior (before the fix):
    EvaluateStatementParser attached WHEN branches by mutating the model's
    attributes directly -- ``stmt.when_clauses.append(when_clause)`` and
    ``stmt.default_when = WhenClause(...)`` -- bypassing the model's
    ``add_when_clause`` / ``set_default_when`` methods that call ``add_child``.

    As a result the WhenClause nodes (and every statement nested inside a WHEN
    or WHEN OTHER branch) were never registered as AST children. The public
    tree-walk API -- ``find_all_by_type`` / ``find_first_by_type`` /
    ``traverse_depth_first`` (which only descend ``node.children``) -- silently
    returned nothing for statements inside an EVALUATE, even though the data
    was present in the ``when_clauses`` attribute and reachable via the
    separate ``get_all_statements`` traversal. Consumers using the documented
    ``ast.find_all_by_type(...)`` API (including the vendored backend) therefore
    under-counted every EVALUATE-nested statement.

    The fix routes both paths through ``add_when_clause`` / ``set_default_when``
    so the WhenClause becomes a real child. ``get_all_statements`` already
    dedupes by ``id`` (visited set), so the now-registered children are not
    double-counted.
"""

import textwrap

from cobolparser import parse_cobol
from cobolparser.plugins.core import ErrorRecoveryMode


def _evaluate_program(body: str) -> str:
    return textwrap.dedent(f"""\
        IDENTIFICATION DIVISION.
        PROGRAM-ID. REGTEST.
        PROCEDURE DIVISION.
        MAIN.
        {body}
        PARA-X.
            DISPLAY 'X'.
        """)


def _parse(body: str):
    return parse_cobol(
        _evaluate_program(body), error_recovery=ErrorRecoveryMode.COLLECT_ALL
    )


class TestEvaluateChildRegistration:
    def test_when_branch_statements_are_findable(self):
        result = _parse("""\
            EVALUATE WS-X
              WHEN 1
                MOVE A TO B
                PERFORM PARA-X
              WHEN 2
                DISPLAY 'TWO'
              WHEN OTHER
                DISPLAY 'OTHER'
            END-EVALUATE.
            """)
        assert result.ast is not None
        # MOVE and PERFORM live only inside a WHEN branch.
        assert len(result.ast.find_all_by_type("MoveStatement")) == 1
        assert len(result.ast.find_all_by_type("PerformStatement")) == 1
        # Three DISPLAYs: WHEN 2, WHEN OTHER, and PARA-X (outside the EVALUATE).
        assert len(result.ast.find_all_by_type("DisplayStatement")) == 3

    def test_when_clauses_registered_as_children(self):
        result = _parse("""\
            EVALUATE WS-X
              WHEN 1
                DISPLAY 'ONE'
              WHEN OTHER
                DISPLAY 'OTHER'
            END-EVALUATE.
            """)
        evaluate = result.ast.find_first_by_type("EvaluateStatement")
        assert evaluate is not None
        # One WHEN clause + one WHEN OTHER (default) clause == 2 children.
        assert len(evaluate.children) == 2

    def test_find_first_reaches_into_when_branch(self):
        result = _parse("""\
            EVALUATE WS-X
              WHEN 1
                MOVE A TO B
            END-EVALUATE.
            """)
        # Previously find_first_by_type returned None for this MOVE.
        assert result.ast.find_first_by_type("MoveStatement") is not None

    def test_no_double_counting_via_get_all_statements(self):
        result = _parse("""\
            EVALUATE WS-X
              WHEN 1
                MOVE A TO B
              WHEN OTHER
                MOVE C TO D
            END-EVALUATE.
            """)
        moves = [
            s
            for s in result.ast.get_all_statements()
            if type(s).__name__ == "MoveStatement"
        ]
        # Exactly two MOVEs -- registering the clauses as children must not make
        # get_all_statements (which visits both children and the when_clauses
        # attribute) report them twice.
        assert len(moves) == 2

    def test_default_when_statements_are_findable(self):
        result = _parse("""\
            EVALUATE WS-X
              WHEN 1
                DISPLAY 'ONE'
              WHEN OTHER
                MOVE A TO B
                PERFORM PARA-X
            END-EVALUATE.
            """)
        # Statements inside WHEN OTHER must be reachable too.
        assert len(result.ast.find_all_by_type("MoveStatement")) == 1
        assert len(result.ast.find_all_by_type("PerformStatement")) == 1

    def test_duplicate_when_other_does_not_orphan_children(self):
        # Malformed input: two WHEN OTHER branches. set_default_when always
        # calls add_child, so attaching a fresh clause each time would leave an
        # orphaned default WhenClause child that the tree-walk APIs surface but
        # default_when / to_dict() (which reference only the last) do not. The
        # parser must reuse the single default clause so traversal and to_dict
        # stay consistent -- while still reporting the error.
        result = _parse("""\
            EVALUATE WS-X
              WHEN 1
                DISPLAY 'ONE'
              WHEN OTHER
                MOVE A TO B
              WHEN OTHER
                MOVE C TO D
            END-EVALUATE.
            """)
        # Error is still reported.
        assert any(
            "Multiple WHEN OTHER" in str(e) for e in result.errors
        ), "duplicate WHEN OTHER should be reported"
        evaluate = result.ast.find_first_by_type("EvaluateStatement")
        # Exactly one WHEN branch + one default clause == 2 children (no orphan).
        assert len(evaluate.children) == 2
        assert evaluate.children.count(evaluate.default_when) == 1
        # Traversal and to_dict must agree on the default-clause statements.
        moves_via_traversal = len(result.ast.find_all_by_type("MoveStatement"))
        default_when = evaluate.to_dict().get("default_when") or {}
        moves_in_to_dict = len(default_when.get("statements", []))
        assert moves_via_traversal == 2
        assert moves_in_to_dict == 2
