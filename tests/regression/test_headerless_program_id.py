"""A PROGRAM-ID / FUNCTION-ID written without its IDENTIFICATION DIVISION
header (optional in COBOL 2002, GnuCOBOL and Micro Focus) opens a unit.

Nested in another program, it used to be read as part of the enclosing
program: the outer PROCEDURE DIVISION was replaced and its statements lost,
with no error and no warning (open-source corpus finding, GnuCOBOL tests).
"""

from cobolparser import CobolParser, ErrorRecoveryMode
from cobolparser.models.walk import own_statements


def _parse(src: str):
    result = CobolParser(error_recovery=ErrorRecoveryMode.COLLECT_ALL).parse(src)
    assert result.ast is not None
    return result


def _units(result):
    return [
        (u.program_name, [type(s).__name__ for s in own_statements(u)])
        for u in result.ast.program_units()
    ]


NESTED = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. T.
       PROCEDURE DIVISION.
           CALL "P2"
           IF 1 = 1
              DISPLAY "X"
           END-IF
           STOP RUN.
       PROGRAM-ID. P2.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 W PIC X.
       PROCEDURE DIVISION.
           DISPLAY "IN P2"
           EXIT PROGRAM.
       END PROGRAM P2.
       END PROGRAM T.
"""


def test_nested_headerless_program_keeps_outer_procedure_division():
    result = _parse(NESTED)
    units = dict(_units(result))
    assert units["T"] == [
        "CallStatement",
        "IfStatement",
        "DisplayStatement",
        "StopStatement",
    ]
    assert units["P2"] == ["DisplayStatement", "ExitStatement"]
    assert not result.errors


def test_headerless_program_at_top_of_file():
    src = """\
       PROGRAM-ID. TOP.
       PROCEDURE DIVISION.
           DISPLAY "HI"
           STOP RUN.
"""
    result = _parse(src)
    assert result.ast.program_name == "TOP"
    assert _units(result) == [("TOP", ["DisplayStatement", "StopStatement"])]
    ident = result.ast.get_division("IDENTIFICATION")
    assert ident is not None and ident.metadata.get("header_omitted") is True
    assert not result.errors


def test_headerless_function_id():
    src = """\
       FUNCTION-ID. DOUBLE.
       DATA DIVISION.
       LINKAGE SECTION.
       01 X PIC 9.
       01 R PIC 99.
       PROCEDURE DIVISION USING X RETURNING R.
           COMPUTE R = X * 2
           GOBACK.
       END FUNCTION DOUBLE.
"""
    result = _parse(src)
    assert result.ast.program_name == "DOUBLE"
    assert result.ast.unit_kind == "FUNCTION"
    assert _units(result) == [("DOUBLE", ["ComputeStatement", "GobackStatement"])]


def test_headerless_program_after_data_only_program():
    # The DATA DIVISION section loop used to swallow END PROGRAM and the
    # next unit as an "unknown section".
    src = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. T.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 A PIC X.
       END PROGRAM T.
       PROGRAM-ID. P2.
       PROCEDURE DIVISION.
           DISPLAY "P2".
"""
    result = _parse(src)
    assert _units(result) == [("T", []), ("P2", ["DisplayStatement"])]
    assert not result.errors


def test_headered_program_after_data_only_program():
    src = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. T.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 A PIC X.
       END PROGRAM T.
       IDENTIFICATION DIVISION.
       PROGRAM-ID. P2.
       PROCEDURE DIVISION.
           DISPLAY "P2".
"""
    result = _parse(src)
    assert _units(result) == [("T", []), ("P2", ["DisplayStatement"])]
    assert not result.errors
