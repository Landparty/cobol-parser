"""Regression tests for io-sequence issues #735 and #736.

#735: an OPEN of a file that is already open fails (status 41) and the file
keeps its first mode, but the analyzer went on in the second OPEN's mode --
flagging a legal READ and missing an illegal WRITE.

#736: a REWRITE of a sequential file is legal only right after a READ;
otherwise the runtime returns status 43. It was not reported at all.

Every expected status below is what GnuCOBOL 3.1.2 (``-std=ibm``) returns.
"""

from cobolparser import LintAnalyzer, parse_cobol
from cobolparser.analysis.io_sequence import IOSequenceAnalyzer


def _kinds(body: str, organization: str = "SEQUENTIAL") -> list[tuple[int, str]]:
    lines = [
        "IDENTIFICATION DIVISION.",
        "PROGRAM-ID. IO.",
        "ENVIRONMENT DIVISION.",
        "INPUT-OUTPUT SECTION.",
        "FILE-CONTROL.",
        f"    SELECT F1 ASSIGN TO 'f1.dat' ORGANIZATION {organization}",
        "        FILE STATUS IS FS.",
        "DATA DIVISION.",
        "FILE SECTION.",
        "FD  F1.",
        "01  R1 PIC X(4).",
        "WORKING-STORAGE SECTION.",
        "01  FS PIC XX.",
        "PROCEDURE DIVISION.",
        "MAIN.",
        *("    " + line for line in body.strip("\n").split("\n")),
        "    STOP RUN.",
    ]
    source = "".join(f"       {line}\n" for line in lines)
    result = parse_cobol(source, filename="io.cbl")
    assert result.ast is not None, result.errors
    report = IOSequenceAnalyzer().analyze(result.ast)
    return [
        (v.location.line - 15, v.kind.name)
        for v in report.violations
        if v.kind.name != "FILE_LEFT_OPEN" and v.location is not None
    ]


# -- #735 -------------------------------------------------------------------


def test_failed_duplicate_open_keeps_the_first_mode() -> None:
    # READ: status 00 (still INPUT). WRITE: status 48.
    assert _kinds("""
OPEN INPUT F1
OPEN OUTPUT F1
READ F1
WRITE R1
CLOSE F1
""") == [(2, "DOUBLE_OPEN"), (4, "WRITE_WRONG_MODE")]


def test_open_on_a_path_where_the_file_was_closed_still_opens() -> None:
    assert _kinds("""
OPEN INPUT F1
CLOSE F1
OPEN OUTPUT F1
WRITE R1
CLOSE F1
""") == []


# -- #736 -------------------------------------------------------------------


def test_rewrite_right_after_open_is_reported() -> None:
    # Status 43.
    assert _kinds("""
OPEN I-O F1
REWRITE R1
CLOSE F1
""") == [(2, "REWRITE_WITHOUT_READ")]


def test_rewrite_after_a_read_is_legal() -> None:
    assert _kinds("""
OPEN I-O F1
READ F1
REWRITE R1
CLOSE F1
""") == []


def test_a_second_rewrite_needs_another_read() -> None:
    # The first REWRITE is legal, the second returns status 43.
    assert _kinds("""
OPEN I-O F1
READ F1
REWRITE R1
REWRITE R1
CLOSE F1
""") == [(4, "REWRITE_WITHOUT_READ")]


def test_a_read_in_one_arm_only_is_not_judged() -> None:
    assert _kinds("""
OPEN I-O F1
IF FS = '00'
    READ F1
END-IF
REWRITE R1
CLOSE F1
""") == []


def test_an_indexed_file_is_not_judged() -> None:
    # A keyed REWRITE needs no READ first (random / dynamic access).
    assert (
        _kinds(
            """
OPEN I-O F1
REWRITE R1
CLOSE F1
""",
            organization="INDEXED ACCESS RANDOM RECORD KEY R1",
        )
        == []
    )


def test_lint_grades_it_a_warning() -> None:
    lines = [
        "IDENTIFICATION DIVISION.",
        "PROGRAM-ID. IO.",
        "ENVIRONMENT DIVISION.",
        "INPUT-OUTPUT SECTION.",
        "FILE-CONTROL.",
        "    SELECT F1 ASSIGN TO 'f1.dat'.",
        "DATA DIVISION.",
        "FILE SECTION.",
        "FD  F1.",
        "01  R1 PIC X(4).",
        "PROCEDURE DIVISION.",
        "MAIN.",
        "    OPEN I-O F1",
        "    REWRITE R1",
        "    CLOSE F1",
        "    STOP RUN.",
    ]
    source = "".join(f"       {line}\n" for line in lines)
    result = parse_cobol(source, filename="io.cbl")
    assert result.ast is not None
    findings = LintAnalyzer(["io-sequence"]).analyze(result.ast).findings
    assert [(f.kind, f.severity) for f in findings] == [
        ("REWRITE_WITHOUT_READ", "warning")
    ]
