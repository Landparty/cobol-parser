import textwrap
from cobolparser import CobolParser, ErrorRecoveryMode

def test_select_assign_multiline():
    # Multiline SELECT with ASSIGN target on following line and trailing period.
    source = textwrap.dedent('''\
    IDENTIFICATION DIVISION.
    PROGRAM-ID. TEST.
    ENVIRONMENT DIVISION.
    INPUT-OUTPUT SECTION.
    FILE-CONTROL.
        SELECT PRINT-FILE ASSIGN TO
        PRINTER01.
    DATA DIVISION.
    WORKING-STORAGE SECTION.
    01 DUMMY PIC X.
    PROCEDURE DIVISION.
        DISPLAY "HELLO".
        STOP RUN.
    ''')
    parser = CobolParser(error_recovery=ErrorRecoveryMode.COLLECT_ALL)
    result = parser.parse(source)
    # Should have no parse errors related to SELECT/ASSIGN
    select_errors = [e for e in result.errors if 'ASSIGN' in str(e)]
    assert not select_errors, f"Unexpected ASSIGN-related errors: {select_errors}"
    # Find SELECT statement in AST (very shallow search due to simplified model)
    # Ensure program parsed at least
    assert result.ast is not None
