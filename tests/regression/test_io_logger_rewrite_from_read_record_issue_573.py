"""Regression tests for issue #573: IOLogger's REWRITE FROM and plain READ.

``REWRITE rec FROM item`` logged the record instead of ``item`` (WRITE already
logged the FROM item), and ``READ file`` with no INTO logged no variables at
all, because READ never sets ``record_name`` and the FD's records were never
looked up.
"""

from cobolparser import IOLogger, parse_cobol

_SRC = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. IO573.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT F1 ASSIGN TO 'F1.DAT'
               ORGANIZATION IS SEQUENTIAL.
           SELECT F2 ASSIGN TO 'F2.DAT'
               ORGANIZATION IS SEQUENTIAL.
       DATA DIVISION.
       FILE SECTION.
       FD F1.
       01 R1.
          05 K1 PIC X(4).
       01 R1-ALT PIC X(4).
       FD F2.
       01 R2 PIC X(4).
       WORKING-STORAGE SECTION.
       01 WS-X PIC X(4).
       01 WS-Y PIC X(4).
       PROCEDURE DIVISION.
           OPEN I-O F1 INPUT F2
           READ F1
           READ F2 INTO WS-Y
           REWRITE R1 FROM WS-X
           REWRITE R1
           WRITE R1 FROM WS-X
           CLOSE F1 F2
           GOBACK.
"""


def _ops(operation: str):
    result = parse_cobol(_SRC)
    assert result.errors == []
    report = IOLogger().analyze(result.ast)
    return [op for op in report.operations if op.operation == operation]


def test_rewrite_from_logs_the_from_item_like_write():
    rewrite_from, rewrite_plain = _ops("REWRITE")
    assert rewrite_from.variables == ["WS-X"]
    assert rewrite_from.details == {"from_clause": "WS-X"}
    assert rewrite_from.target == "F1"
    (write,) = _ops("WRITE")
    assert rewrite_from.variables == write.variables


def test_rewrite_without_from_still_logs_the_record():
    _, rewrite_plain = _ops("REWRITE")
    assert rewrite_plain.variables == ["R1"]
    assert rewrite_plain.details == {"from_clause": None}


def test_read_without_into_logs_the_fd_records():
    read_f1, read_f2 = _ops("READ")
    assert read_f1.target == "F1"
    # every 01 under the FD shares the record area the READ fills
    assert read_f1.variables == ["R1", "R1-ALT"]


def test_read_into_still_logs_the_into_target():
    _, read_f2 = _ops("READ")
    assert read_f2.variables == ["WS-Y"]
