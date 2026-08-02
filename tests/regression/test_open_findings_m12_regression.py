"""Regression tests for finding M12 (reports/open-findings.md).

M12 — expression/condition nodes were cosmetic, not structural:

* ``ComputeStatement.expression`` was always a plain space-joined string,
  never decomposed. Now a precedence-parsed tree is additionally attached
  as ``expression_tree`` (the string stays byte-identical for compat).
* ``PERFORM ... UNTIL`` stored the whole raw condition string as the single
  operand of a ``CobolExpression("CONDITION")``. That shape is preserved,
  but the same tokens are now also decomposed with the IF parser's shared
  condition machinery and attached as ``condition_tree``.
* The IF parser's fallback for non-comparison conditions (class conditions
  like ``IS NUMERIC``, sign conditions, condition-names) stored only a raw
  ``metadata.raw_condition`` string. It now produces a structured
  ConditionalExpression while still populating ``raw_condition``.
"""

from __future__ import annotations

import json
import textwrap

from cobolparser import ErrorRecoveryMode, parse_cobol
from cobolparser.models.statements import (
    ComputeStatement,
    IfStatement,
    PerformStatement,
)
from cobolparser.models.statements.base import (
    ArithmeticExpression,
    ConditionalExpression,
    LogicalExpression,
)


def _program(procedure_body: str) -> str:
    return textwrap.dedent(f"""\
        IDENTIFICATION DIVISION.
        PROGRAM-ID. M12TEST.
        DATA DIVISION.
        WORKING-STORAGE SECTION.
        01 X PIC 9(4).
        01 A PIC 9(4).
        01 B PIC 9(4).
        01 C PIC 9(4).
        01 D PIC 9(4).
        PROCEDURE DIVISION.
        MAIN-PARA.
        {procedure_body}
            STOP RUN.
        """)


def _statements(result):
    proc = result.ast.procedure_division
    if proc.paragraphs:
        return proc.paragraphs[0].statements
    if proc.sections and proc.sections[0].paragraphs:
        return proc.sections[0].paragraphs[0].statements
    return []


def _first(result, cls):
    stmts = [s for s in _statements(result) if isinstance(s, cls)]
    assert stmts, f"no {cls.__name__} found"
    return stmts[0]


class TestM12ExpressionTrees:
    """M12 — COMPUTE/PERFORM UNTIL/IF conditions become structural trees."""

    # ------------------------------------------------------------------
    # COMPUTE
    # ------------------------------------------------------------------

    def test_compute_precedence_tree_shape(self):
        """COMPUTE X = (A + B) * C - D / 2 nests as ((A+B)*C) - (D/2)."""
        result = parse_cobol(_program("    COMPUTE X = (A + B) * C - D / 2.\n"))
        assert result.errors == []
        stmt = _first(result, ComputeStatement)

        # Raw string surface unchanged (space-joined tokens, as before M12).
        assert stmt.expression == "( A + B ) * C - D / 2"

        tree = stmt.expression_tree
        assert isinstance(tree, ArithmeticExpression)
        assert tree.operator == "-"

        left = tree.left_operand
        assert isinstance(left, ArithmeticExpression)
        assert left.operator == "*"
        assert isinstance(left.left_operand, ArithmeticExpression)
        assert left.left_operand.operator == "+"
        assert left.left_operand.left_operand == "A"
        assert left.left_operand.right_operand == "B"
        assert left.right_operand == "C"

        right = tree.right_operand
        assert isinstance(right, ArithmeticExpression)
        assert right.operator == "/"
        assert right.left_operand == "D"
        assert right.right_operand == "2"

    def test_compute_exponentiation_binds_tighter_than_addition(self):
        """A ** 3 + 1 parses as (A ** 3) + 1, not A ** (3 + 1)."""
        result = parse_cobol(_program("    COMPUTE X = A ** 3 + 1.\n"))
        assert result.errors == []
        stmt = _first(result, ComputeStatement)

        tree = stmt.expression_tree
        assert isinstance(tree, ArithmeticExpression)
        assert tree.operator == "+"
        power = tree.left_operand
        assert isinstance(power, ArithmeticExpression)
        assert power.operator == "**"
        assert power.left_operand == "A"
        assert power.right_operand == "3"
        assert tree.right_operand == "1"

    def test_compute_unary_minus(self):
        """-A + 5: the unary minus becomes a NEGATE node around A."""
        result = parse_cobol(_program("    COMPUTE X = -A + 5.\n"))
        assert result.errors == []
        stmt = _first(result, ComputeStatement)

        tree = stmt.expression_tree
        assert isinstance(tree, ArithmeticExpression)
        assert tree.operator == "+"
        negate = tree.left_operand
        assert isinstance(negate, ArithmeticExpression)
        assert negate.operator == "NEGATE"
        assert negate.left_operand is None
        assert negate.right_operand == "A"
        assert tree.right_operand == "5"

    def test_compute_subscripted_operand_folded_into_leaf(self):
        """A(I) stays a single leaf string, mirroring operand style elsewhere."""
        result = parse_cobol(_program("    COMPUTE X = A(I) + 1.\n"))
        assert result.errors == []
        stmt = _first(result, ComputeStatement)

        tree = stmt.expression_tree
        assert isinstance(tree, ArithmeticExpression)
        assert tree.operator == "+"
        assert tree.left_operand == "A ( I )"
        assert tree.right_operand == "1"

    def test_compute_tree_survives_to_dict_and_to_json(self):
        result = parse_cobol(_program("    COMPUTE X = (A + B) * C.\n"))
        stmt = _first(result, ComputeStatement)

        d = stmt.to_dict()
        # Raw string key unchanged, new expression_tree key added.
        assert d["expression"] == "( A + B ) * C"
        tree_dict = d["expression_tree"]
        assert tree_dict is not None
        assert tree_dict["operator"] == "*"
        assert tree_dict["left_operand"]["operator"] == "+"
        assert tree_dict["left_operand"]["left_operand"] == "A"
        assert tree_dict["right_operand"] == "C"

        # And the whole program AST remains JSON-serializable.
        parsed_back = json.loads(result.ast.to_json())
        assert parsed_back is not None

    def test_compute_degraded_input_leaves_tree_none_string_unchanged(self):
        """Tokens that don't form an expression keep the raw string, tree None,
        with zero new errors or warnings (fail-soft requirement)."""
        result = parse_cobol(
            _program("    COMPUTE X = A B.\n"),
            error_recovery=ErrorRecoveryMode.COLLECT_ALL,
        )
        assert result.errors == []
        assert result.warnings == []
        stmt = _first(result, ComputeStatement)
        assert stmt.expression == "A B"
        assert stmt.expression_tree is None
        assert stmt.to_dict()["expression_tree"] is None

    def test_compute_unbalanced_parens_still_reported_tree_not_built(self):
        """H2 behavior unchanged: unbalanced parens still produce the same
        diagnostic; the structural tree never masks or replaces it."""
        result = parse_cobol(
            _program("    COMPUTE X = ((A + B)\n    DISPLAY 'DONE'.\n"),
            error_recovery=ErrorRecoveryMode.COLLECT_ALL,
        )
        assert any(
            "unbalanced parentheses" in str(e).lower() for e in result.errors
        ), result.errors
        # Any surviving COMPUTE node must not have grown a bogus tree.
        for stmt in _statements(result):
            if isinstance(stmt, ComputeStatement):
                assert stmt.expression_tree is None

    # ------------------------------------------------------------------
    # PERFORM UNTIL
    # ------------------------------------------------------------------

    def test_perform_until_condition_decomposed_to_and_tree(self):
        cobol = textwrap.dedent("""\
            IDENTIFICATION DIVISION.
            PROGRAM-ID. M12PERF.
            DATA DIVISION.
            WORKING-STORAGE SECTION.
            01 A PIC 9(4).
            01 B PIC 9(4).
            PROCEDURE DIVISION.
            MAIN-PARA.
                PERFORM P1 UNTIL A > 10 AND B < 5.
                STOP RUN.
            P1.
                DISPLAY 'LOOP'.
            """)
        result = parse_cobol(cobol)
        assert result.errors == []
        stmt = _first(result, PerformStatement)
        assert stmt.perform_type == "UNTIL"

        cond = stmt.until_condition
        assert cond is not None
        # Pre-M12 raw shape preserved exactly: one raw joined operand string
        # on a CONDITION expression (consumers like ProgramFlowAnalyzer's
        # edge builder read exactly this).
        assert cond.expression_type == "CONDITION"
        assert cond.operands == ["A > 10 AND B < 5"]

        # New structural decomposition.
        tree = cond.condition_tree
        assert isinstance(tree, LogicalExpression)
        assert tree.operator == "AND"
        left = tree.left_condition
        assert isinstance(left, ConditionalExpression)
        assert left.operator == "GREATER"
        assert left.left_operand == "A"
        assert left.right_operand == "10"
        right = tree.right_condition
        assert isinstance(right, ConditionalExpression)
        assert right.operator == "LESS"
        assert right.left_operand == "B"
        assert right.right_operand == "5"

        # Serialization: raw operands unchanged, tree under a new key.
        d = stmt.to_dict()["until_condition"]
        assert d["operands"] == ["A > 10 AND B < 5"]
        assert d["condition_tree"]["operator"] == "AND"

    def test_perform_inline_until_also_gets_condition_tree(self):
        cobol = textwrap.dedent("""\
            IDENTIFICATION DIVISION.
            PROGRAM-ID. M12PERF2.
            DATA DIVISION.
            WORKING-STORAGE SECTION.
            01 I PIC 9(3).
            PROCEDURE DIVISION.
            MAIN-PARA.
                PERFORM UNTIL I > 5
                    DISPLAY I
                END-PERFORM.
                STOP RUN.
            """)
        result = parse_cobol(cobol)
        stmt = _first(result, PerformStatement)
        cond = stmt.until_condition
        assert cond is not None
        assert cond.operands == ["I > 5"]
        tree = cond.condition_tree
        assert isinstance(tree, ConditionalExpression)
        assert tree.operator == "GREATER"
        assert tree.left_operand == "I"
        assert tree.right_operand == "5"

    # ------------------------------------------------------------------
    # IF fallback conditions
    # ------------------------------------------------------------------

    def test_if_class_condition_is_numeric_now_structured(self):
        result = parse_cobol(
            _program("    IF A IS NUMERIC\n        DISPLAY 'N'\n    END-IF.\n")
        )
        stmt = _first(result, IfStatement)
        cond = stmt.condition
        assert isinstance(cond, ConditionalExpression)
        assert cond.operator == "IS NUMERIC"
        assert cond.left_operand == "A"
        assert cond.right_operand is None
        # raw_condition metadata is still populated exactly as before.
        assert cond._metadata["raw_condition"] == "A IS NUMERIC"
        assert cond.to_dict()["metadata"]["raw_condition"] == "A IS NUMERIC"

    def test_if_negated_sign_condition_structured(self):
        result = parse_cobol(
            _program("    IF A IS NOT POSITIVE\n        DISPLAY 'N'\n    END-IF.\n")
        )
        cond = _first(result, IfStatement).condition
        assert isinstance(cond, ConditionalExpression)
        assert cond.operator == "IS NOT POSITIVE"
        assert cond.left_operand == "A"
        assert cond._metadata["raw_condition"] == "A IS NOT POSITIVE"

    def test_if_bare_condition_name_structured(self):
        result = parse_cobol(
            _program("    IF END-OF-FILE\n        DISPLAY 'EOF'\n    END-IF.\n")
        )
        cond = _first(result, IfStatement).condition
        assert isinstance(cond, ConditionalExpression)
        assert cond.operator == "CONDITION_NAME"
        assert cond.left_operand == "END-OF-FILE"
        assert cond._metadata["raw_condition"] == "END-OF-FILE"

    def test_if_unrecognized_fallback_keeps_raw_comparison_shape(self):
        """Multi-token conditions with no recognizable shape keep the
        historical raw COMPARISON fallback node."""
        result = parse_cobol(
            _program("    IF A B\n        DISPLAY 'MULTI'\n    END-IF.\n")
        )
        cond = _first(result, IfStatement).condition
        assert isinstance(cond, ConditionalExpression)
        assert cond.operator == "COMPARISON"
        assert cond._metadata["raw_condition"] == "A B"
