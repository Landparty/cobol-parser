"""Issue #498 (option b): a file a SORT / MERGE reads (USING) or writes
(GIVING) is not a boundary, and nothing said so, so a program whose only I/O
is ``SORT ... USING IN-FILE GIVING OUT-FILE`` produced an empty bundle with
nothing unresolved.  Each such file is now an ``unresolved`` entry (and so
``gen-fixtures --strict`` fails), pending a decision on a real boundary.
"""

from __future__ import annotations

import pytest

from cobolparser import ErrorRecoveryMode, parse_cobol
from cobolparser.analysis.boundary_inventory import BoundaryInventoryAnalyzer
from cobolparser.generators import ProgramFixtureGenerator
from cobolparser.generators.data.program_layout import ProgramLayoutIndex


def _program(statement: str) -> str:
    return (
        "       IDENTIFICATION DIVISION.\n"
        "       PROGRAM-ID. SRT3.\n"
        "       ENVIRONMENT DIVISION.\n"
        "       INPUT-OUTPUT SECTION.\n"
        "       FILE-CONTROL.\n"
        "           SELECT IN-FILE ASSIGN TO INF.\n"
        "           SELECT IN-FILE2 ASSIGN TO INF2.\n"
        "           SELECT OUT-FILE ASSIGN TO OUTF.\n"
        "           SELECT SRT-FILE ASSIGN TO SRTWK.\n"
        "       DATA DIVISION.\n"
        "       FILE SECTION.\n"
        "       FD IN-FILE.\n"
        "       01 IN-REC.\n"
        "          05 IN-KEY PIC X(5).\n"
        "          05 IN-AMT PIC 9(5).\n"
        "       FD IN-FILE2.\n"
        "       01 IN-REC2 PIC X(10).\n"
        "       FD OUT-FILE.\n"
        "       01 OUT-REC PIC X(10).\n"
        "       SD SRT-FILE.\n"
        "       01 SRT-REC.\n"
        "          05 SRT-KEY PIC X(5).\n"
        "          05 SRT-AMT PIC 9(5).\n"
        "       PROCEDURE DIVISION.\n"
        "       MAIN-PARA.\n" + statement + "           GOBACK.\n"
    )


@pytest.mark.parametrize(
    ("statement", "expected"),
    [
        (
            "           SORT SRT-FILE ON ASCENDING KEY SRT-KEY\n"
            "               USING IN-FILE GIVING OUT-FILE\n",
            ["SORT USING file IN-FILE", "SORT GIVING file OUT-FILE"],
        ),
        (
            "           MERGE SRT-FILE ON ASCENDING KEY SRT-KEY\n"
            "               USING IN-FILE IN-FILE2 GIVING OUT-FILE\n",
            [
                "MERGE USING file IN-FILE ",
                "MERGE USING file IN-FILE2",
                "MERGE GIVING file OUT-FILE",
            ],
        ),
    ],
)
def test_sort_merge_files_are_reported_unresolved(
    statement: str, expected: list[str]
) -> None:
    result = parse_cobol(
        _program(statement),
        filename="srt3.cbl",
        error_recovery=ErrorRecoveryMode.FAIL_FAST,
    )
    assert result.ast is not None, result.errors
    index = ProgramLayoutIndex.build(result.ast)
    report = BoundaryInventoryAnalyzer().analyze(result.ast, index)
    assert report.boundaries == []
    assert len(report.unresolved) == len(expected)
    for prefix, note in zip(expected, report.unresolved, strict=True):
        assert note.startswith(prefix)
        assert "not modelled as a boundary" in note
    bundle = ProgramFixtureGenerator().generate(result.ast, index, report, seed=1)
    assert len(bundle.unresolved) == len(expected)
