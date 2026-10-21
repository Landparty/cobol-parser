"""Regression tests for issue #520: special registers with a fixed category.

``MoveTypeChecker`` knew only RETURN-CODE, TALLY and LINAGE-COUNTER, so a
MOVE of ``LENGTH OF x``, SORT-RETURN, WHEN-COMPILED, XML-CODE, ... went
unchecked and counted as unresolved -- and ``lint`` then told the user to fix
copybook paths in a program with no COPY statement.
"""

import pytest

from cobolparser import parse_cobol
from cobolparser.analysis.lint import LintAnalyzer
from cobolparser.analysis.move_type_checker import MoveTypeChecker

_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. MV.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 W PIC X(8).
       01 N PIC 9(4).
       PROCEDURE DIVISION.
           MOVE LENGTH OF W TO N
           MOVE SORT-RETURN TO N
           MOVE WHEN-COMPILED TO W
           MOVE XML-CODE TO N
           MOVE JSON-CODE TO N
           MOVE SORT-CORE-SIZE TO N
           MOVE SORT-FILE-SIZE TO N
           MOVE SORT-MODE-SIZE TO N
           MOVE SORT-CONTROL TO W
           MOVE SORT-MESSAGE TO W
           MOVE N TO SORT-RETURN
           STOP RUN.
"""


def _ast(source: str = _SOURCE):  # type: ignore[no-untyped-def]
    result = parse_cobol(source, filename="mv.cbl")
    assert result.ast is not None
    return result.ast


def test_special_registers_resolve_and_are_checked() -> None:
    report = MoveTypeChecker().check(_ast())
    assert report.unresolved_count == 0
    assert report.violations == []


def test_lint_has_no_copybook_caveat() -> None:
    report = LintAnalyzer().analyze(_ast())
    assert not any("COPY" in caveat for caveat in report.caveats)


@pytest.mark.parametrize(
    ("register", "category"),
    [
        ("LENGTH OF W", "NUMERIC"),
        ("length of w", "NUMERIC"),
        ("SORT-RETURN", "NUMERIC"),
        ("XML-CODE", "NUMERIC"),
        ("JSON-CODE", "NUMERIC"),
        ("WHEN-COMPILED", "ALPHANUMERIC"),
        ("SORT-CONTROL", "ALPHANUMERIC"),
        ("SORT-MESSAGE", "ALPHANUMERIC"),
    ],
)
def test_register_category(register: str, category: str) -> None:
    checker = MoveTypeChecker()
    checker.check(_ast())
    assert checker._resolve_category(register).name == category


def test_alphanumeric_register_to_numeric_is_now_checked() -> None:
    source = _SOURCE.replace(
        "           MOVE N TO SORT-RETURN\n",
        "           MOVE WHEN-COMPILED TO N\n",
    )
    report = MoveTypeChecker().check(_ast(source))
    assert [(v.source_name, v.target_name) for v in report.violations] == [
        ("WHEN-COMPILED", "N")
    ]
