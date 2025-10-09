from cobolparser import CobolParser, ErrorRecoveryMode, normalize_fixed_format, parse_cobol

FIXED_SOURCE = (
    "000100 IDENTIFICATION DIVISION.\n"
    "000200 PROGRAM-ID. FFREE.\n"
    "000300 DATA DIVISION.\n"
    "000400 WORKING-STORAGE SECTION.\n"
    "000500 01 MSG PIC X(20) VALUE \"HELLO\".\n"
    "000600 PROCEDURE DIVISION.\n"
    "000700     DISPLAY MSG.\n"
)

def test_normalize_fixed_format():
    normalized = normalize_fixed_format(FIXED_SOURCE.splitlines())
    # Should remove sequence numbers and keep core tokens
    assert 'IDENTIFICATION DIVISION.' in normalized
    assert 'PROGRAM-ID.' in normalized
    assert 'DISPLAY MSG.' in normalized


def test_parse_with_free_form_flag():
    parser = CobolParser(error_recovery=ErrorRecoveryMode.COLLECT_ALL, free_form=True)
    result = parser.parse(normalize_fixed_format(FIXED_SOURCE.splitlines()))
    assert result.success, result.errors


def test_parse_cobol_preprocess():
    result = parse_cobol(FIXED_SOURCE, preprocess_fixed=True, error_recovery=ErrorRecoveryMode.COLLECT_ALL)
    assert result.success, result.errors
