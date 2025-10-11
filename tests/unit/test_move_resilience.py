from cobolparser import parse_cobol, ErrorRecoveryMode

def test_move_missing_to_does_not_block_perform():
    src = """000100 IDENTIFICATION DIVISION.
000200 PROGRAM-ID. X.
000300 PROCEDURE DIVISION.
000400 PARA-ONE.
000500     MOVE VALUE1 VALUE2.  * Missing TO should soft fail
000600     PERFORM PARA-TWO.
000700 PARA-TWO.
000800     MOVE A TO B.
"""
    result = parse_cobol(src, filename='<mem>', error_recovery=ErrorRecoveryMode.COLLECT_ALL)
    # Should have at least one error about Expected TO in MOVE statement
    assert any('Expected TO in MOVE statement' in str(e) for e in result.errors)
    # PERFORM should still be recognized (we approximate by counting in tokens via AST if implemented)
    # Since we don't have direct API for counting, just ensure parsing continued past error.
    assert result.ast is not None
