"""Regression: SELECT clauses IBM Enterprise COBOL writes in short form.

* ``[ORGANIZATION IS] INDEXED | RELATIVE | SEQUENTIAL | LINE SEQUENTIAL`` --
  the words ORGANIZATION IS are optional. Written bare, the organization
  used to be glued onto the ASSIGN name (``assign_to == "F1DD INDEXED"``)
  with ``organization`` left None, and a bare ``RELATIVE`` was dispatched
  to the RELATIVE KEY parser, which took the next word as the key.
* ``ASSIGN USING data-name`` stored ``assign_to == "USING WS-DSN"``, and the
  data item that names the file at run time was reported unused.
* A clause broken across lines between its own words (``ACCESS`` /
  ``MODE IS DYNAMIC``, ``RECORD KEY`` / ``IS K``) lost its value: only one
  line break, directly before the value, was tolerated.
"""

from cobolparser import UnusedVariableAnalyzer, parse_cobol
from cobolparser.plugins.core import ErrorRecoveryMode


def _program(file_control: str, working_storage: str = "") -> str:
    return (
        "       IDENTIFICATION DIVISION.\n"
        "       PROGRAM-ID. SELTEST.\n"
        "       ENVIRONMENT DIVISION.\n"
        "       INPUT-OUTPUT SECTION.\n"
        "       FILE-CONTROL.\n"
        f"{file_control}"
        "       DATA DIVISION.\n"
        "       WORKING-STORAGE SECTION.\n"
        "       01 WS-X PIC X.\n"
        f"{working_storage}"
        "       PROCEDURE DIVISION.\n"
        "           STOP RUN.\n"
    )


def _selects(source: str) -> dict:
    result = parse_cobol(source, error_recovery=ErrorRecoveryMode.FAIL_FAST)
    assert result.errors == []
    assert result.warnings == []
    return {
        node.file_name: node
        for node in result.ast.find_all_by_type("Statement")
        if node.to_dict().get("statement_type") == "SELECT"
    }


def test_bare_organization_words() -> None:
    selects = _selects(
        _program(
            "           SELECT F1 ASSIGN TO F1DD INDEXED\n"
            "               ACCESS DYNAMIC RECORD KEY K1.\n"
            "           SELECT F2 ASSIGN TO F2DD RELATIVE\n"
            "               ACCESS RANDOM RELATIVE KEY IS WS-R.\n"
            "           SELECT F3 ASSIGN TO F3DD SEQUENTIAL.\n"
            "           SELECT F4 ASSIGN F4DD LINE SEQUENTIAL.\n"
        )
    )
    assert (selects["F1"].assign_to, selects["F1"].organization) == ("F1DD", "INDEXED")
    assert selects["F1"].access_mode == "DYNAMIC"
    assert selects["F1"].record_key == "K1"
    assert (selects["F2"].assign_to, selects["F2"].organization) == ("F2DD", "RELATIVE")
    assert selects["F2"].access_mode == "RANDOM"
    assert selects["F2"].relative_key == "WS-R"
    assert (selects["F3"].assign_to, selects["F3"].organization) == (
        "F3DD",
        "SEQUENTIAL",
    )
    assert (selects["F4"].assign_to, selects["F4"].organization) == (
        "F4DD",
        "LINE SEQUENTIAL",
    )


def test_assign_using_data_name() -> None:
    source = _program(
        "           SELECT DYN-FILE ASSIGN USING WS-DSN.\n",
        "       01 WS-DSN PIC X(44).\n",
    )
    select = _selects(source)["DYN-FILE"]
    assert select.assign_to == "WS-DSN"
    assert select.assign_using == "WS-DSN"
    assert select.to_dict()["assign_using"] == "WS-DSN"
    ast = parse_cobol(source).ast
    unused = {item.name for item in UnusedVariableAnalyzer().analyze(ast).unused_items}
    assert "WS-DSN" not in unused


def test_clause_words_split_across_lines() -> None:
    selects = _selects(
        _program(
            "           SELECT F6 ASSIGN TO F6DD ORGANIZATION\n"
            "               IS INDEXED ACCESS\n"
            "               MODE IS DYNAMIC RECORD\n"
            "               KEY IS K6 FILE\n"
            "               STATUS IS WS-FS.\n"
        )
    )
    f6 = selects["F6"]
    assert f6.organization == "INDEXED"
    assert f6.access_mode == "DYNAMIC"
    assert f6.record_key == "K6"
    assert f6.file_status == "WS-FS"
