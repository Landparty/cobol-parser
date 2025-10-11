from cobolparser import parse_cobol, ErrorRecoveryMode

def get_statement_types(ast_root):
    types = []
    if not ast_root: return types
    for div in getattr(ast_root, 'divisions', []):
        for sec in getattr(div, 'sections', []):
            for child in getattr(sec, 'children', []):
                if getattr(child, 'node_type', '') == 'Statement':
                    types.append(child.statement_type)
    return types

def test_go_to_parsed():
    src = """000100 IDENTIFICATION DIVISION.
000200 PROGRAM-ID. G1.
000300 PROCEDURE DIVISION.
000400 PARA-1.
000500     GO TO PARA-2.
000600 PARA-2.
000700     MOVE A TO B.
"""
    r = parse_cobol(src, filename='<mem>', error_recovery=ErrorRecoveryMode.COLLECT_ALL)
    assert 'GOTO' in get_statement_types(r.ast)


def test_if_else_minimal():
    src = """000100 IDENTIFICATION DIVISION.
000200 PROGRAM-ID. IF1.
000300 PROCEDURE DIVISION.
000400 PARA-1.
000500     IF A > B MOVE A TO B ELSE MOVE B TO A.
"""
    r = parse_cobol(src, filename='<mem>', error_recovery=ErrorRecoveryMode.COLLECT_ALL)
    kinds = get_statement_types(r.ast)
    # IF recorded, both MOVEs recorded
    assert kinds.count('IF') == 1
    assert kinds.count('MOVE') == 2


def test_else_recovery_without_if():
    src = """000100 IDENTIFICATION DIVISION.
000200 PROGRAM-ID. ER1.
000300 PROCEDURE DIVISION.
000400 PARA-1.
000500     ELSE MOVE A TO B MOVE B TO C.
"""
    r = parse_cobol(src, filename='<mem>', error_recovery=ErrorRecoveryMode.COLLECT_ALL)
    kinds = get_statement_types(r.ast)
    # ELSE skipped, subsequent MOVEs captured
    assert kinds.count('MOVE') >= 2
