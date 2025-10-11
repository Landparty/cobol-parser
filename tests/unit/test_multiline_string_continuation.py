from cobolparser import CobolParser, ErrorRecoveryMode

# Simulate fixed-format lines with continuation '-' in column 7
# Columns: 1-6 seq, 7 indicator, 8+ text
SOURCE = (
    "000100 IDENTIFICATION DIVISION.\n"
    "000200 PROGRAM-ID. TESTML.\n"
    "000300 DATA DIVISION.\n"
    "000400 WORKING-STORAGE SECTION.\n"
    # Start string literal but do not close on this line
    "000500 01 MSG PIC X(40) VALUE \"This is a very long literal that\n"
    # Continuation line with '-' indicator and closing quote
    "000600-     CONTINUES HERE\".\n"
    "000700 PROCEDURE DIVISION.\n"
    "000800     DISPLAY MSG.\n"
)

def test_multiline_string_continuation():
    parser = CobolParser(error_recovery=ErrorRecoveryMode.COLLECT_ALL)
    result = parser.parse(SOURCE)
    assert result.success, result.errors
    # Ensure no unterminated string errors
    unterr = [e for e in result.errors if 'Unterminated string' in str(e)]
    assert not unterr, unterr
