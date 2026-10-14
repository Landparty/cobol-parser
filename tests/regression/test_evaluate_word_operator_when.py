"""EVALUATE WHEN phrases spelled with relational words, or written as a
class or sign test, are conditions (issue #387).

``WHEN X GREATER THAN 1`` was stored as the literal selector
``"X GREATER THAN 1"``: business-rules quoted it as a value, xref lost the
read of ``X`` and the constraint extractor reported an unresolvable
operand. ``X GREATER THAN OR EQUAL TO 1`` became a Condition but was tagged
``operator: "OR"`` -- the OR of ``OR EQUAL`` is not a connective.
"""

from __future__ import annotations

import pytest

from cobolparser import parse_cobol
from cobolparser.analysis.boundary_inventory import BoundaryInventoryAnalyzer
from cobolparser.analysis.business_rules import BusinessRuleExtractor
from cobolparser.analysis.complexity import ComplexityAnalyzer
from cobolparser.analysis.constraints import (
    ConstraintExtractor,
    _symbolize_relational_words,
)
from cobolparser.analysis.xref import XrefAnalyzer
from cobolparser.generators import ProgramLayoutIndex

_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. EVWORD.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT IN-FILE ASSIGN TO INFILE.
       DATA DIVISION.
       FILE SECTION.
       FD  IN-FILE.
       01  IN-REC.
           05 IN-AMT  PIC 9(3).
       WORKING-STORAGE SECTION.
       01  WS-OUT PIC 9.
       PROCEDURE DIVISION.
       MAIN-PARA.
           OPEN INPUT IN-FILE
           READ IN-FILE
           EVALUATE TRUE
             WHEN {when}
               MOVE 1 TO WS-OUT
             WHEN OTHER
               MOVE 2 TO WS-OUT
           END-EVALUATE
           DISPLAY WS-OUT
           CLOSE IN-FILE
           STOP RUN.
"""


def _parse(when: str):
    result = parse_cobol(_SOURCE.format(when=when), filename="evword.cbl")
    assert result.ast is not None, result.errors
    assert result.errors == []
    return result.ast


def _selector(when: str) -> dict:
    (evaluate,) = _parse(when).find_all_by_type("EvaluateStatement")
    (selector,) = evaluate.when_clauses[0].selectors
    return selector


class TestSelectorShape:
    @pytest.mark.parametrize(
        "when",
        [
            "IN-AMT GREATER THAN 1",
            "IN-AMT GREATER 1",
            "IN-AMT IS GREATER THAN 1",
            "IN-AMT LESS THAN 1",
            "IN-AMT EQUAL TO 1",
            "IN-AMT EQUALS 1",
            "IN-AMT IS NUMERIC",
            "IN-AMT ALPHABETIC",
            "IN-AMT IS ALPHABETIC-LOWER",
            "IN-AMT ALPHABETIC-UPPER",
            "IN-AMT DBCS",
            "IN-AMT KANJI",
            "IN-AMT IS POSITIVE",
            "IN-AMT NEGATIVE",
            "IN-AMT ZERO",
            "IN-AMT GREATER THAN OR EQUAL TO 1",
            "IN-AMT LESS OR EQUAL 1",
        ],
    )
    def test_word_operator_phrase_is_a_single_condition(self, when):
        assert _selector(when) == {"type": "Condition", "text": when}

    def test_lone_zero_is_still_the_figurative_constant(self):
        assert _selector("ZERO") == {
            "type": "Literal",
            "value": "ZERO",
            "figurative": True,
        }

    def test_quoted_relational_word_is_still_a_value(self):
        assert _selector("'GREATER'") == {
            "type": "Literal",
            "value": "GREATER",
            "quoted": True,
        }

    def test_logical_or_is_still_tagged(self):
        selector = _selector("IN-AMT GREATER THAN 1 OR IN-AMT = 0")
        assert selector["operator"] == "OR"

    def test_or_equal_next_to_a_logical_and_tags_and(self):
        selector = _selector("IN-AMT LESS OR EQUAL 5 AND IN-AMT GREATER 1")
        assert selector["operator"] == "AND"


class TestAnalyzersSeeTheCondition:
    def test_business_rules_renders_the_condition_unquoted(self):
        report = BusinessRuleExtractor().analyze(_parse("IN-AMT GREATER THAN 1"))
        (rule,) = report.rules
        assert rule.branches[0].condition == "IN-AMT GREATER THAN 1"

    def test_xref_records_the_read_of_the_subject(self):
        report = XrefAnalyzer().analyze(_parse("IN-AMT GREATER THAN 1"))
        entry = report.entry_for("IN-AMT")
        assert entry is not None
        assert any(ref.role == "condition" for ref in entry.references)

    @pytest.mark.parametrize(
        ("when", "op"),
        [
            ("IN-AMT GREATER THAN 1", "gt"),
            ("IN-AMT IS GREATER 1", "gt"),
            ("IN-AMT LESS THAN 1", "lt"),
            ("IN-AMT EQUAL TO 1", "eq"),
            ("IN-AMT GREATER THAN OR EQUAL TO 1", "ge"),
            ("IN-AMT LESS OR EQUAL 1", "le"),
            ("IN-AMT NOT GREATER THAN 1", "le"),
            ("IN-AMT IS NOT EQUAL TO 1", "ne"),
        ],
    )
    def test_constraint_extractor_reads_word_operators(self, when, op):
        ast = _parse(when)
        index = ProgramLayoutIndex.build(ast)
        boundaries = BoundaryInventoryAnalyzer().analyze(ast, index)
        report = ConstraintExtractor().extract(ast, index, boundaries)
        (branch,) = report.branches
        (constraint,) = branch.arms["WHEN_1"]
        assert constraint.field.spec.name == "IN-AMT"
        assert constraint.op == op
        assert constraint.values == ("1",)

    def test_or_equal_is_not_counted_as_a_boolean_operator(self):
        def extended(when: str) -> int:
            report = ComplexityAnalyzer().analyze(_parse(when))
            by_name = {p.name: p for p in report.procedures}
            return by_name["MAIN-PARA"].extended_complexity

        assert extended("IN-AMT GREATER THAN OR EQUAL TO 1") == extended("IN-AMT >= 1")
        assert extended("IN-AMT > 1 OR IN-AMT = 0") == extended("IN-AMT >= 1") + 1


class TestSymbolizeRelationalWords:
    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("A GREATER THAN B", "A > B"),
            ("A IS LESS B", "A < B"),
            ("A EQUALS B", "A = B"),
            ("A IS NOT LESS THAN OR EQUAL TO B", "A > B"),
            ("WS-GREATER-AMT > 1", "WS-GREATER-AMT > 1"),
            ("A = 'LESS THAN'", "A = 'LESS THAN'"),
        ],
    )
    def test_rewrites(self, text, expected):
        assert _symbolize_relational_words(text) == expected
