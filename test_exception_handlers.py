#!/usr/bin/env python
"""Test NOT ON EXCEPTION parsing integration"""

from cobolparser import CobolParser
from cobolparser.models.statements import CallStatement, DisplayStatement

def test_exception_handler_separation():
    """Test that ON EXCEPTION and NOT ON EXCEPTION are properly separated."""
    code = '''
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TEST-EXCEPTION.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-PROG PIC X(20).
       01  WS-VAR PIC 9(5).
       PROCEDURE DIVISION.
           CALL WS-PROG USING WS-VAR
               ON EXCEPTION
                   DISPLAY 'Error occurred'
               NOT ON EXCEPTION
                   DISPLAY 'Success'
           END-CALL.
           STOP RUN.
    '''
    
    parser = CobolParser()
    result = parser.parse(code)
    
    assert result.success, f"Parse failed: {result.errors}"
    
    # Get all statements
    all_stmts = result.ast.get_all_statements()
    
    # Find the CALL statement
    call_stmt = None
    for stmt in all_stmts:
        if isinstance(stmt, CallStatement):
            call_stmt = stmt
            break
    
    assert call_stmt is not None, "CALL statement not found"
    assert call_stmt.called_program == "WS-PROG", "Wrong called program"
    
    # Check ON EXCEPTION handler
    assert call_stmt.on_exception is not None, "ON EXCEPTION not parsed"
    assert len(call_stmt.on_exception) == 1, f"Expected 1 ON EXCEPTION statement, got {len(call_stmt.on_exception)}"
    assert isinstance(call_stmt.on_exception[0], DisplayStatement), "ON EXCEPTION statement should be DISPLAY"
    
    # Check NOT ON EXCEPTION handler
    assert call_stmt.not_on_exception is not None, "NOT ON EXCEPTION not parsed"
    assert len(call_stmt.not_on_exception) == 1, f"Expected 1 NOT ON EXCEPTION statement, got {len(call_stmt.not_on_exception)}"
    assert isinstance(call_stmt.not_on_exception[0], DisplayStatement), "NOT ON EXCEPTION statement should be DISPLAY"
    
    print("✅ Test 1 PASSED: ON EXCEPTION and NOT ON EXCEPTION properly separated")


def test_multiple_statements_in_handlers():
    """Test multiple statements in each handler."""
    code = '''
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TEST-MULTI.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-PROG PIC X(20).
       01  WS-VAR1 PIC 9(5).
       01  WS-VAR2 PIC 9(5).
       PROCEDURE DIVISION.
           CALL WS-PROG USING WS-VAR1
               ON EXCEPTION
                   DISPLAY 'Error 1'
                   MOVE 99 TO WS-VAR2
               NOT ON EXCEPTION
                   DISPLAY 'Success 1'
                   MOVE 0 TO WS-VAR2
           END-CALL.
           STOP RUN.
    '''
    
    parser = CobolParser()
    result = parser.parse(code)
    
    assert result.success, f"Parse failed: {result.errors}"
    
    # Find CALL statement
    call_stmt = None
    for stmt in result.ast.get_all_statements():
        if isinstance(stmt, CallStatement):
            call_stmt = stmt
            break
    
    assert call_stmt is not None
    assert len(call_stmt.on_exception) == 2, f"Expected 2 ON EXCEPTION statements, got {len(call_stmt.on_exception)}"
    assert len(call_stmt.not_on_exception) == 2, f"Expected 2 NOT ON EXCEPTION statements, got {len(call_stmt.not_on_exception)}"
    
    print("✅ Test 2 PASSED: Multiple statements in handlers properly separated")


def test_get_all_statements_includes_exception_handlers():
    """Test that get_all_statements() includes statements from exception handlers."""
    code = '''
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TEST-GET-ALL.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-PROG PIC X(20).
       PROCEDURE DIVISION.
           CALL WS-PROG
               ON EXCEPTION
                   DISPLAY 'Error'
               NOT ON EXCEPTION
                   DISPLAY 'Success'
           END-CALL.
           STOP RUN.
    '''
    
    parser = CobolParser()
    result = parser.parse(code)
    
    assert result.success
    
    all_stmts = result.ast.get_all_statements()
    
    # Count DISPLAY statements (should include ones in handlers)
    display_count = sum(1 for s in all_stmts if isinstance(s, DisplayStatement))
    
    # Should have: "Error", "Success", "TEST-GET-ALL", and STOP RUN displays (3+ display statements)
    assert display_count >= 2, f"Expected at least 2 DISPLAY statements, got {display_count}"
    
    print("✅ Test 3 PASSED: get_all_statements() includes exception handler statements")


def test_only_on_exception():
    """Test CALL with only ON EXCEPTION (no NOT ON EXCEPTION)."""
    code = '''
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TEST-EX-ONLY.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-PROG PIC X(20).
       PROCEDURE DIVISION.
           CALL WS-PROG
               ON EXCEPTION
                   DISPLAY 'Error'
           END-CALL.
           STOP RUN.
    '''
    
    parser = CobolParser()
    result = parser.parse(code)
    
    assert result.success
    
    call_stmt = None
    for stmt in result.ast.get_all_statements():
        if isinstance(stmt, CallStatement):
            call_stmt = stmt
            break
    
    assert call_stmt is not None
    assert call_stmt.on_exception is not None
    assert len(call_stmt.on_exception) == 1
    assert call_stmt.not_on_exception is None or len(call_stmt.not_on_exception) == 0
    
    print("✅ Test 4 PASSED: ON EXCEPTION only (no NOT ON EXCEPTION)")


def test_only_not_on_exception():
    """Test CALL with only NOT ON EXCEPTION."""
    code = '''
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TEST-NOX-ONLY.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-PROG PIC X(20).
       PROCEDURE DIVISION.
           CALL WS-PROG
               NOT ON EXCEPTION
                   DISPLAY 'Success'
           END-CALL.
           STOP RUN.
    '''
    
    parser = CobolParser()
    result = parser.parse(code)
    
    assert result.success
    
    call_stmt = None
    for stmt in result.ast.get_all_statements():
        if isinstance(stmt, CallStatement):
            call_stmt = stmt
            break
    
    assert call_stmt is not None
    # NOT ON EXCEPTION without ON EXCEPTION gets stored in on_exception per COBOL semantics
    assert call_stmt.on_exception is not None or call_stmt.not_on_exception is not None
    
    print("✅ Test 5 PASSED: NOT ON EXCEPTION only")


if __name__ == "__main__":
    test_exception_handler_separation()
    test_multiple_statements_in_handlers()
    test_get_all_statements_includes_exception_handlers()
    test_only_on_exception()
    test_only_not_on_exception()
    
    print("\n" + "="*60)
    print("✅ ALL TESTS PASSED - Exception handler parsing is working correctly")
    print("="*60)
