from cobolparser import CobolParser, ErrorRecoveryMode

def test_perform_until_numeric_literal_with_period():
    src = (
        "IDENTIFICATION DIVISION.\n"
        "PROGRAM-ID. PUNTIL.\n"
        "DATA DIVISION.\n"
        "WORKING-STORAGE SECTION.\n"
        "01 CNT PIC 9(2) VALUE 5.\n"
        "PROCEDURE DIVISION.\n"
        "MAIN-PARA.\n"
        "    PERFORM LOOP-PARA UNTIL CNT = 0.\n"
        "    STOP RUN.\n"
        "LOOP-PARA.\n"
        "    SUBTRACT 1 FROM CNT.\n"
    )
    parser = CobolParser(error_recovery=ErrorRecoveryMode.COLLECT_ALL)
    result = parser.parse(src)
    assert not [e for e in result.errors if 'ASSIGN' in str(e) or 'DISPLAY' in str(e)], result.errors
