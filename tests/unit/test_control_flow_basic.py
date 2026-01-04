from cobolparser import parse_cobol, ErrorRecoveryMode
from cobolparser.models.statements import IfStatement

def get_statement_types(ast_root):
    types = []
    if not ast_root: return types
    for div in getattr(ast_root, 'divisions', []):
        for sec in getattr(div, 'sections', []):
            for child in getattr(sec, 'children', []):
                if getattr(child, 'node_type', '') == 'Statement':
                    types.append(child.statement_type)
    return types

def get_if_statements(ast_root):
    """Extract all IfStatement objects from AST."""
    if_stmts = []
    if not ast_root: return if_stmts
    for div in getattr(ast_root, 'divisions', []):
        for sec in getattr(div, 'sections', []):
            for child in getattr(sec, 'children', []):
                if isinstance(child, IfStatement):
                    if_stmts.append(child)
    return if_stmts

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
    # IF recorded at top level (MOVEs are in branches)
    assert kinds.count('IF') == 1
    
    # NEW: Verify IfStatement structure (fix verification)
    if_stmts = get_if_statements(r.ast)
    assert len(if_stmts) == 1, "Should have exactly one IfStatement"
    if_stmt = if_stmts[0]
    
    assert isinstance(if_stmt, IfStatement), f"Expected IfStatement, got {type(if_stmt)}"
    assert hasattr(if_stmt, 'condition'), "IfStatement should have condition attribute"
    assert hasattr(if_stmt, 'then_statements'), "IfStatement should have then_statements"
    assert hasattr(if_stmt, 'else_statements'), "IfStatement should have else_statements"
    
    assert len(if_stmt.then_statements) > 0, "THEN branch should have statements"
    assert len(if_stmt.else_statements) > 0, "ELSE branch should have statements"


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

def test_if_with_end_if_explicit():
    """Test IF statement with explicit END-IF terminator."""
    src = """000100 IDENTIFICATION DIVISION.
000200 PROGRAM-ID. IF2.
000300 PROCEDURE DIVISION.
000400 PARA-1.
000500     IF A > B
000600         MOVE A TO B
000700     ELSE
000800         MOVE B TO A
000900     END-IF.
"""
    r = parse_cobol(src, filename='<mem>', error_recovery=ErrorRecoveryMode.COLLECT_ALL)
    if_stmts = get_if_statements(r.ast)
    
    assert len(if_stmts) >= 1, "Should have at least one IfStatement"
    if_stmt = if_stmts[0]
    
    assert isinstance(if_stmt, IfStatement)
    assert len(if_stmt.then_statements) > 0
    assert len(if_stmt.else_statements) > 0


def test_nested_if_statements():
    """Test nested IF statements with END-IF."""
    src = """000100 IDENTIFICATION DIVISION.
000200 PROGRAM-ID. NIF1.
000300 PROCEDURE DIVISION.
000400 PARA-1.
000500     IF A > B
000600         IF C > D
000700             MOVE A TO C
000800         ELSE
000900             MOVE B TO D
001000         END-IF
001100     ELSE
001200         MOVE B TO A
001300     END-IF.
"""
    r = parse_cobol(src, filename='<mem>', error_recovery=ErrorRecoveryMode.COLLECT_ALL)
    if_stmts = get_if_statements(r.ast)
    
    # Should have at least one outer IF
    assert len(if_stmts) >= 1, "Should have at least one IfStatement"
    
    # Verify first IF has proper structure
    outer_if = if_stmts[0]
    assert isinstance(outer_if, IfStatement)
    # Nested IF will appear as a separate statement in then_statements or get_all_statements
    # The important thing is that outer IF has the proper structure
    assert hasattr(outer_if, 'then_statements'), "IF should have then_statements"
    assert hasattr(outer_if, 'else_statements'), "IF should have else_statements"


def test_get_all_statements_includes_if_branches():
    """Test that get_all_statements() includes IF branches properly."""
    src = """000100 IDENTIFICATION DIVISION.
000200 PROGRAM-ID. GAS1.
000300 PROCEDURE DIVISION.
000400 PARA-1.
000500     IF A > B
000600         MOVE A TO B
000700         MOVE C TO D
000800     ELSE
000900         MOVE X TO Y
001000     END-IF.
"""
    r = parse_cobol(src, filename='<mem>', error_recovery=ErrorRecoveryMode.COLLECT_ALL)
    
    # Use get_all_statements() to verify IF branches are included
    all_stmts = r.ast.get_all_statements()
    statement_types = [s.statement_type for s in all_stmts if hasattr(s, 'statement_type')]
    
    # Should have IF and MOVEs
    assert 'IF' in statement_types, "get_all_statements() should include IF"
    assert statement_types.count('MOVE') >= 3, "get_all_statements() should include all MOVEs from branches"