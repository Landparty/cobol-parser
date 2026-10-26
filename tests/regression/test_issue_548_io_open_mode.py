"""io-sequence checks each verb against the file's OPEN mode (#548).

``IOSequenceAnalyzer`` tracked only whether a file was open, so READ on a
file opened OUTPUT (status 47), WRITE on INPUT (48), REWRITE on EXTEND (49)
and an OPEN after ``CLOSE ... WITH LOCK`` (38) were all reported clean --
and the failed OPEN after the lock earned a FILE_LEFT_OPEN instead.
"""

from __future__ import annotations

import pytest

from cobolparser import IOSequenceAnalyzer, LintAnalyzer, parse_cobol


def _program(*body: str, selects: tuple[str, ...] = ()) -> str:
    lines = (
        "IDENTIFICATION DIVISION.",
        "PROGRAM-ID. IO2.",
        "ENVIRONMENT DIVISION.",
        "INPUT-OUTPUT SECTION.",
        "FILE-CONTROL.",
        *(selects or ("    SELECT F2 ASSIGN TO DD2 FILE STATUS FS.",)),
        "DATA DIVISION.",
        "FILE SECTION.",
        "FD F2.",
        "01 R2.",
        "   05 R2-KEY PIC X(4).",
        "   05 R2-DATA PIC X(6).",
        "WORKING-STORAGE SECTION.",
        "01 FS PIC XX.",
        "01 WS-X PIC 9 VALUE 0.",
        "PROCEDURE DIVISION.",
        "MAIN-PARA.",
        *body,
    )
    return "".join(f"       {line}\n" for line in lines)


def _violations(source: str) -> list[tuple[str, int | None]]:
    result = parse_cobol(source)
    assert result.success, result.errors
    return [
        (v.kind.name, v.location.line if v.location else None)
        for v in IOSequenceAnalyzer().analyze(result.ast).violations
    ]


ISSUE_REPRO = _program(
    "    OPEN OUTPUT F2",
    "    READ F2 END-READ",
    "    CLOSE F2",
    "    OPEN INPUT F2",
    "    WRITE R2",
    "    CLOSE F2",
    "    OPEN EXTEND F2",
    "    REWRITE R2",
    "    CLOSE F2 WITH LOCK",
    "    OPEN INPUT F2",
    "    STOP RUN.",
)


def test_issue_repro_reports_each_mode_error_and_no_left_open():
    assert _violations(ISSUE_REPRO) == [
        ("READ_WRONG_MODE", 19),
        ("WRITE_WRONG_MODE", 22),
        ("REWRITE_WRONG_MODE", 25),
        ("OPEN_AFTER_LOCK", 27),
    ]


def test_mode_errors_are_lint_errors():
    result = parse_cobol(ISSUE_REPRO)
    findings = LintAnalyzer(["io-sequence"]).analyze(result.ast).findings
    assert {f.severity for f in findings} == {"error"}
    assert len(findings) == 4


@pytest.mark.parametrize(
    "body",
    [
        ("    OPEN I-O F2", "    READ F2 END-READ", "    REWRITE R2", "    CLOSE F2"),
        ("    OPEN INPUT F2", "    READ F2 END-READ", "    CLOSE F2"),
        ("    OPEN OUTPUT F2", "    WRITE R2", "    CLOSE F2"),
        ("    OPEN EXTEND F2", "    WRITE R2", "    CLOSE F2"),
        ("    CLOSE F2 WITH LOCK",),
    ],
    ids=["io-read-rewrite", "input-read", "output-write", "extend-write", "lock"],
)
def test_allowed_verbs_are_clean(body):
    violations = _violations(_program(*body, "    STOP RUN."))
    assert not [v for v in violations if v[0].endswith(("_MODE", "_LOCK"))]


def test_write_under_io_depends_on_organization():
    sequential = _program(
        "    OPEN I-O F2", "    WRITE R2", "    CLOSE F2", "    STOP RUN."
    )
    assert _violations(sequential) == [("WRITE_WRONG_MODE", 19)]
    indexed = _program(
        "    OPEN I-O F2",
        "    WRITE R2",
        "    DELETE F2",
        "    START F2",
        "    CLOSE F2",
        "    STOP RUN.",
        selects=(
            "    SELECT F2 ASSIGN TO DD2 ORGANIZATION INDEXED",
            "        ACCESS DYNAMIC RECORD KEY R2-KEY FILE STATUS FS.",
        ),
    )
    assert _violations(indexed) == []


def test_write_under_io_with_no_select_in_sight_is_not_judged():
    # The SELECT lives in a COPY member that was not expanded: the file may
    # be indexed, where WRITE under I-O is legal, so no error is claimed.
    source = _program(
        "    OPEN I-O F2",
        "    WRITE R2",
        "    CLOSE F2",
        "    STOP RUN.",
        selects=("    COPY FSELECTS.",),
    )
    assert _violations(source) == []


def test_delete_and_start_on_input_or_output():
    source = _program(
        "    OPEN INPUT F2",
        "    DELETE F2",
        "    CLOSE F2",
        "    OPEN OUTPUT F2",
        "    START F2",
        "    CLOSE F2",
        "    STOP RUN.",
        selects=(
            "    SELECT F2 ASSIGN TO DD2 ORGANIZATION INDEXED",
            "        ACCESS DYNAMIC RECORD KEY R2-KEY FILE STATUS FS.",
        ),
    )
    assert _violations(source) == [
        ("DELETE_WRONG_MODE", 20),
        ("START_WRONG_MODE", 23),
    ]


def test_mode_differing_between_arms_is_not_an_error():
    source = _program(
        "    IF WS-X = 1",
        "       OPEN INPUT F2",
        "    ELSE",
        "       OPEN OUTPUT F2",
        "    END-IF",
        "    READ F2 END-READ",
        "    WRITE R2",
        "    CLOSE F2",
        "    STOP RUN.",
    )
    assert _violations(source) == []


def test_lock_on_one_arm_only_is_not_an_error():
    source = _program(
        "    OPEN INPUT F2",
        "    IF WS-X = 1",
        "       CLOSE F2 WITH LOCK",
        "    ELSE",
        "       CLOSE F2",
        "    END-IF",
        "    OPEN INPUT F2",
        "    CLOSE F2",
        "    STOP RUN.",
    )
    assert _violations(source) == []


def test_conditional_go_to_target_keeps_the_mode_at_the_go_to():
    # The loop is left through a GO TO met inside an IF; the walk only
    # reaches its target after a later paragraph reopened the file INPUT.
    # The DELETE runs with the file open I-O, as it was at the GO TO.
    source = _program(
        "    OPEN I-O F2.",
        "LOOP-PARA.",
        "    READ F2 AT END GO TO LATER-PARA END-READ",
        "    IF WS-X = 1",
        "       GO TO DELETE-PARA",
        "    END-IF",
        "    GO TO LOOP-PARA.",
        "LATER-PARA.",
        "    CLOSE F2",
        "    OPEN INPUT F2",
        "    READ F2 END-READ",
        "    GO TO LOOP-PARA.",
        "DELETE-PARA.",
        "    DELETE F2",
        "    CLOSE F2",
        "    STOP RUN.",
        selects=(
            "    SELECT F2 ASSIGN TO DD2 ORGANIZATION INDEXED",
            "        ACCESS DYNAMIC RECORD KEY R2-KEY FILE STATUS FS.",
        ),
    )
    assert not [v for v in _violations(source) if v[0] == "DELETE_WRONG_MODE"]
