"""Tests for CBL/PROCESS compiler directive handling in the library API path.

Prior to the fix, strip_compiler_directives() was only called from the CLI.
When using parse_cobol() directly, programs with CBL/PROCESS header lines
would fail or produce parse errors.
"""

import textwrap

from cobolparser import parse_cobol

_PROGRAM_BODY = textwrap.dedent("""\
    IDENTIFICATION DIVISION.
    PROGRAM-ID. TESTPROG.
    DATA DIVISION.
    WORKING-STORAGE SECTION.
    01 WS-X PIC X.
    PROCEDURE DIVISION.
    STOP RUN.
    """)


def test_cbl_directive_via_api():
    src = "       CBL RENT,APOST\n" + _PROGRAM_BODY
    result = parse_cobol(src, filename="test.cbl")
    assert result.success, f"Parse errors with CBL directive: {result.errors}"
    assert result.ast is not None


def test_process_directive_via_api():
    src = "       PROCESS RENT,APOST\n" + _PROGRAM_BODY
    result = parse_cobol(src, filename="test.cbl")
    assert result.success, f"Parse errors with PROCESS directive: {result.errors}"
    assert result.ast is not None


def test_multiple_cbl_directives():
    src = "       CBL RENT\n" "       CBL APOST\n" + _PROGRAM_BODY
    result = parse_cobol(src, filename="test.cbl")
    assert result.success


def test_no_directive_still_works():
    result = parse_cobol(_PROGRAM_BODY, filename="test.cbl")
    assert result.success
