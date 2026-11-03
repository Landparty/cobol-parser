"""Regression tests for issue #816: an edited picture mixing X/A and 9.

``PIC XXB99`` and ``PIC 99/XX`` are alphanumeric-edited (an edited picture
holding an X, or an A with 9s), not numeric-edited. The checker used to call
any edited picture holding a 9 numeric-edited, which gave false "Illegal
MOVE" errors on legal moves and missed a decimal moved into such an item.
"""

import pytest

from cobolparser import parse_cobol
from cobolparser.analysis.move_type_checker import (
    DataCategory,
    MoveTypeChecker,
    MoveViolationKind,
    _classify_picture,
)
from cobolparser.models.ast_base import SourceLocation
from cobolparser.models.data_items import PictureClause

_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. MX.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  N-DEC     PIC 9(3)V99.
       01  N-INT     PIC 9(3).
       01  A-ALPHA   PIC A(5).
       01  X-MIX-ED  PIC XXB99.
       01  X-MIX2    PIC 99/XX.
       PROCEDURE DIVISION.
           MOVE A-ALPHA TO X-MIX-ED
           MOVE A-ALPHA TO X-MIX2
           MOVE X-MIX-ED TO A-ALPHA
           MOVE N-INT TO X-MIX2
           MOVE N-DEC TO X-MIX-ED
           STOP RUN.
"""


@pytest.mark.parametrize(
    ("pattern", "expected"),
    [
        ("XXB99", DataCategory.ALPHANUMERIC_EDITED),
        ("99/XX", DataCategory.ALPHANUMERIC_EDITED),
        ("A9B9", DataCategory.ALPHANUMERIC_EDITED),
        ("X(9)BX(9)", DataCategory.ALPHANUMERIC_EDITED),
        ("ZZB99", DataCategory.NUMERIC_EDITED),
        ("99/99/99", DataCategory.NUMERIC_EDITED),
        ("ZZ9.99CR", DataCategory.NUMERIC_EDITED),
    ],
)
def test_classification(pattern: str, expected: DataCategory) -> None:
    assert _classify_picture(PictureClause(pattern, SourceLocation(1, 1))) == expected


def test_moves_follow_alphanumeric_edited_rules() -> None:
    result = parse_cobol(_SOURCE, filename="mx.cbl")
    assert result.ast is not None
    report = MoveTypeChecker().check(result.ast)
    errors = [
        (v.source_name, v.target_name)
        for v in report.violations
        if v.kind == MoveViolationKind.ERROR
    ]
    assert errors == [("N-DEC", "X-MIX-ED")]
