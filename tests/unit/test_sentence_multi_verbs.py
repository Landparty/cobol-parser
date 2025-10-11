from cobolparser import parse_cobol, ErrorRecoveryMode

def extract_statements(ast_root):
    out = []
    if not ast_root: return out
    for div in getattr(ast_root, 'divisions', []):
        for sec in getattr(div, 'sections', []):
            for child in getattr(sec, 'children', []):
                if getattr(child, 'node_type', '') == 'Statement':
                    out.append(child)
    return out

def test_multi_verbs_one_sentence():
    src = """000100 IDENTIFICATION DIVISION.
000200 PROGRAM-ID. M1.
000300 PROCEDURE DIVISION.
000400 PARA-1.
000500     MOVE A TO B PERFORM PARA-2 WRITE OUTREC.
000600 PARA-2.
000700     MOVE X TO Y.
"""
    result = parse_cobol(src, filename='<mem>', error_recovery=ErrorRecoveryMode.COLLECT_ALL)
    stmts = extract_statements(result.ast)
    kinds = [s.statement_type for s in stmts]
    assert 'MOVE' in kinds and 'PERFORM' in kinds and 'WRITE' in kinds
