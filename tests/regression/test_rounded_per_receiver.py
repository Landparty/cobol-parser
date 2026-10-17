"""Issue #517: arithmetic ROUNDED was one statement-wide flag, so which
receiver is rounded -- and its ``ROUNDED MODE IS`` mode -- was lost.
``COMPUTE B ROUNDED C = A / 3`` and ``COMPUTE B C ROUNDED = A / 3`` store
different values but had the same AST: ``diff`` said "No structural
changes", ``business-rules`` showed every target as rounded, and
``redundancy`` called the two a TYPE_1 clone.
"""

from __future__ import annotations

import pytest

from cobolparser import parse_cobol
from cobolparser.analysis.ast_diff import ProgramDiffer
from cobolparser.analysis.business_rules import BusinessRuleExtractor
from cobolparser.analysis.redundancy import RedundancyAnalyzer


def _program(body: str, extra: str = "") -> str:
    return (
        "IDENTIFICATION DIVISION.\n"
        "PROGRAM-ID. R1.\n"
        "DATA DIVISION.\n"
        "WORKING-STORAGE SECTION.\n"
        "01 A PIC 9(5)V99.\n"
        "01 B PIC 9(5).\n"
        "01 C PIC 9(5).\n"
        "01 D PIC 9(5).\n"
        "PROCEDURE DIVISION.\n"
        "MAIN-PARA.\n"
        "    ACCEPT A\n"
        + "".join(f"    {line}\n" for line in body.strip().splitlines())
        + "    GOBACK.\n"
        + extra
    )


def _ast(source: str):
    result = parse_cobol(source, filename="r.cbl")
    assert result.ast is not None and result.errors == [], result.errors
    return result.ast


def _first(body: str):
    statements = _ast(_program(body)).get_all_statements()
    return statements[1]


@pytest.mark.parametrize(
    ("body", "rounded_targets", "modes"),
    [
        ("COMPUTE B ROUNDED C = A / 3", ["B"], {}),
        ("COMPUTE B C ROUNDED = A / 3", ["C"], {}),
        (
            "COMPUTE B ROUNDED MODE IS NEAREST-EVEN = A / 7",
            ["B"],
            {"B": "NEAREST-EVEN"},
        ),
        ("ADD A TO B ROUNDED C", ["B"], {}),
        ("ADD A TO B C ROUNDED MODE TRUNCATION", ["C"], {"C": "TRUNCATION"}),
        ("SUBTRACT A FROM B C ROUNDED", ["C"], {}),
        ("ADD A TO B GIVING C D ROUNDED", ["D"], {}),
        ("MULTIPLY A BY B ROUNDED C", ["B"], {}),
        ("DIVIDE A INTO B C ROUNDED", ["C"], {}),
        ("DIVIDE A BY 3 GIVING B ROUNDED C", ["B"], {}),
        ("COMPUTE B C = A / 3", [], {}),
    ],
)
def test_rounding_is_recorded_per_receiver(body, rounded_targets, modes) -> None:
    stmt = _first(body)
    assert stmt.rounded == bool(rounded_targets)
    assert stmt.rounded_targets == rounded_targets
    assert stmt.rounding_modes == modes
    data = stmt.to_dict()
    assert data.get("rounded_targets", []) == rounded_targets
    assert data.get("rounding_modes", {}) == modes


def test_rounding_of_reports_each_receiver() -> None:
    stmt = _first("COMPUTE B ROUNDED MODE IS NEAREST-EVEN C D ROUNDED = A / 3")
    assert stmt.rounding_of("B") == "ROUNDED MODE IS NEAREST-EVEN"
    assert stmt.rounding_of("C") == ""
    assert stmt.rounding_of("D") == "ROUNDED"


@pytest.mark.parametrize(
    ("old", "new"),
    [
        ("COMPUTE B ROUNDED C = A / 3", "COMPUTE B C ROUNDED = A / 3"),
        ("ADD A TO B ROUNDED C", "ADD A TO B C ROUNDED"),
        (
            "COMPUTE B ROUNDED MODE IS NEAREST-EVEN = A / 7",
            "COMPUTE B ROUNDED MODE IS TRUNCATION = A / 7",
        ),
    ],
)
def test_diff_reports_moved_rounding(old: str, new: str) -> None:
    result = ProgramDiffer().diff(_ast(_program(old)), _ast(_program(new)))
    assert any(c.kind == "statement-changed" for c in result.changes), result


def test_business_rules_round_only_the_rounded_receiver() -> None:
    report = BusinessRuleExtractor().analyze(
        _ast(
            _program(
                "ADD A TO B ROUNDED C\n"
                "COMPUTE B C ROUNDED MODE IS TRUNCATION = A / 3\n"
                "DISPLAY B C"
            )
        )
    )
    formulas = [rule.formula for rule in report.rules]
    assert "B ROUNDED = B + A; C = C + A" in formulas
    assert "B, C ROUNDED MODE IS TRUNCATION = A / 3" in formulas


def test_redundancy_does_not_clone_differently_rounded_paragraphs() -> None:
    paragraphs = (
        "P1.\n"
        "    COMPUTE B ROUNDED C = A / 3\n"
        "    ADD A TO B ROUNDED C\n"
        "    DISPLAY B C.\n"
        "P2.\n"
        "    COMPUTE B C ROUNDED = A / 3\n"
        "    ADD A TO B C ROUNDED\n"
        "    DISPLAY B C.\n"
    )
    ast = _ast(_program("PERFORM P1\nPERFORM P2", paragraphs))
    report = RedundancyAnalyzer().analyze(ast, min_clone_statements=2)
    members = [{m.name for m in g.members} for g in report.clone_groups]
    assert {"P1", "P2"} not in members, report.clone_groups
