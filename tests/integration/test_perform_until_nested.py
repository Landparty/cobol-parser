"""Test PERFORM UNTIL with nested CALL and IF statements."""

import pytest

from cobolparser import ErrorRecoveryMode, parse_cobol
from cobolparser.models.statements import CallStatement, IfStatement, PerformStatement

pytestmark = pytest.mark.integration


class TestPerformUntilNestedStatements:
    """Test nested statements within PERFORM UNTIL blocks."""

    def test_perform_until_with_simple_call(self):
        """Test PERFORM UNTIL with a single nested CALL statement."""
        src = """000100 IDENTIFICATION DIVISION.
000200 PROGRAM-ID. PU1.
000300 PROCEDURE DIVISION.
000400 PARA-1.
000500     PERFORM VARYING I FROM 1 BY 1
000600         UNTIL I > 10
000700         CALL 'PROG1' USING I
000800     END-PERFORM.
"""
        r = parse_cobol(
            src, filename="<mem>", error_recovery=ErrorRecoveryMode.COLLECT_ALL
        )

        # Get PERFORM statements
        perform_stmts = [
            s
            for s in r.ast.get_all_statements()
            if isinstance(s, PerformStatement) and s.statement_type == "PERFORM"
        ]

        assert (
            len(perform_stmts) >= 1
        ), f"Expected at least 1 PERFORM statement, got {len(perform_stmts)}"

        pf = perform_stmts[0]
        assert hasattr(
            pf, "inline_statements"
        ), "PERFORM should have inline_statements attribute"
        assert (
            len(pf.inline_statements) >= 1
        ), f"PERFORM should have inline statements, got {len(pf.inline_statements)}"

        # Check for CALL statement in inline_statements
        call_stmts = [s for s in pf.inline_statements if isinstance(s, CallStatement)]
        assert (
            len(call_stmts) >= 1
        ), f"Expected at least 1 CALL in PERFORM, got {len(call_stmts)}"

        call = call_stmts[0]
        assert call.statement_type == "CALL"
        assert hasattr(
            call, "called_program"
        ), "CALL should have called_program attribute"

    def test_perform_until_with_multiple_calls(self):
        """Test PERFORM UNTIL with multiple nested CALL statements."""
        src = """000100 IDENTIFICATION DIVISION.
000200 PROGRAM-ID. PU2.
000300 PROCEDURE DIVISION.
000400 PARA-1.
000500     PERFORM VARYING I FROM 1 BY 1
000600         UNTIL I > 10
000700         CALL 'PROG1' USING I
000800         CALL 'PROG2' USING I
000900     END-PERFORM.
"""
        r = parse_cobol(
            src, filename="<mem>", error_recovery=ErrorRecoveryMode.COLLECT_ALL
        )

        perform_stmts = [
            s
            for s in r.ast.get_all_statements()
            if isinstance(s, PerformStatement) and s.statement_type == "PERFORM"
        ]

        assert len(perform_stmts) >= 1
        pf = perform_stmts[0]

        # Should have at least 2 inline statements (2 CALLs)
        assert (
            len(pf.inline_statements) >= 2
        ), f"PERFORM should have at least 2 inline statements, got {len(pf.inline_statements)}"

        # Count CALL statements
        call_stmts = [s for s in pf.inline_statements if isinstance(s, CallStatement)]
        assert len(call_stmts) >= 2, f"Expected at least 2 CALLs, got {len(call_stmts)}"

    def test_perform_until_with_nested_if(self):
        """Test PERFORM UNTIL with nested IF statement."""
        src = """000100 IDENTIFICATION DIVISION.
000200 PROGRAM-ID. PU3.
000300 PROCEDURE DIVISION.
000400 PARA-1.
000500     PERFORM VARYING I FROM 1 BY 1
000600         UNTIL I > 10
000700         IF I > 5
000800             CALL 'PROG1' USING I
000900         ELSE
001000             CALL 'PROG2' USING I
001100         END-IF
001200     END-PERFORM.
"""
        r = parse_cobol(
            src, filename="<mem>", error_recovery=ErrorRecoveryMode.COLLECT_ALL
        )

        perform_stmts = [
            s
            for s in r.ast.get_all_statements()
            if isinstance(s, PerformStatement) and s.statement_type == "PERFORM"
        ]

        assert len(perform_stmts) >= 1
        pf = perform_stmts[0]

        # Check for IF statement in inline_statements
        if_stmts = [s for s in pf.inline_statements if isinstance(s, IfStatement)]
        assert (
            len(if_stmts) >= 1
        ), f"Expected at least 1 IF in PERFORM, got {len(if_stmts)}"

        if_stmt = if_stmts[0]
        assert hasattr(if_stmt, "then_statements"), "IF should have then_statements"
        assert hasattr(if_stmt, "else_statements"), "IF should have else_statements"

    def test_perform_until_varying_clause(self):
        """Test that PERFORM VARYING clause is properly set."""
        src = """000100 IDENTIFICATION DIVISION.
000200 PROGRAM-ID. PU4.
000300 PROCEDURE DIVISION.
000400 PARA-1.
000500     PERFORM VARYING I FROM 1 BY 1
000600         UNTIL I > 100
000700         CALL 'PROCESS' USING I
000800     END-PERFORM.
"""
        r = parse_cobol(
            src, filename="<mem>", error_recovery=ErrorRecoveryMode.COLLECT_ALL
        )

        perform_stmts = [
            s
            for s in r.ast.get_all_statements()
            if isinstance(s, PerformStatement) and s.statement_type == "PERFORM"
        ]

        assert len(perform_stmts) >= 1
        pf = perform_stmts[0]

        # Check VARYING attributes
        assert hasattr(pf, "varying_clause"), "PERFORM should have varying_clause"
        assert pf.varying_clause is not None, "varying_clause should not be None"

        assert (
            pf.varying_clause["variable"] == "I"
        ), f"Expected variable 'I', got '{pf.varying_clause['variable']}'"
        assert (
            pf.varying_clause["from_value"] == "1"
        ), f"Expected from '1', got '{pf.varying_clause['from_value']}'"
        assert (
            pf.varying_clause["by_value"] == "1"
        ), f"Expected by '1', got '{pf.varying_clause['by_value']}'"

    def test_get_all_statements_includes_perform_nested(self):
        """Test that get_all_statements() includes statements nested in PERFORM."""
        src = """000100 IDENTIFICATION DIVISION.
000200 PROGRAM-ID. PU5.
000300 PROCEDURE DIVISION.
000400 PARA-1.
000500     PERFORM VARYING I FROM 1 BY 1
000600         UNTIL I > 10
000700         CALL 'PROG1' USING I
000800         CALL 'PROG2' USING I
000900     END-PERFORM.
"""
        r = parse_cobol(
            src, filename="<mem>", error_recovery=ErrorRecoveryMode.COLLECT_ALL
        )

        all_stmts = r.ast.get_all_statements()
        statement_types = [
            s.statement_type for s in all_stmts if hasattr(s, "statement_type")
        ]

        # Should have PERFORM and nested CALLs
        assert (
            "PERFORM" in statement_types
        ), "get_all_statements() should include PERFORM"
        assert (
            statement_types.count("CALL") >= 2
        ), f"get_all_statements() should include nested CALLs, got {statement_types.count('CALL')}"

    def test_perform_until_json_serialization(self):
        """Test that PERFORM UNTIL serializes correctly with inline statements."""
        src = """000100 IDENTIFICATION DIVISION.
000200 PROGRAM-ID. PU6.
000300 PROCEDURE DIVISION.
000400 PARA-1.
000500     PERFORM VARYING I FROM 1 BY 1
000600         UNTIL I > 10
000700         CALL 'TEST' USING I
000800     END-PERFORM.
"""
        r = parse_cobol(
            src, filename="<mem>", error_recovery=ErrorRecoveryMode.COLLECT_ALL
        )

        perform_stmts = [
            s for s in r.ast.get_all_statements() if isinstance(s, PerformStatement)
        ]

        assert len(perform_stmts) >= 1
        pf = perform_stmts[0]

        # Serialize to dict
        pf_dict = pf.to_dict()

        assert (
            "inline_statements" in pf_dict
        ), "Serialized PERFORM should include inline_statements"
        assert isinstance(
            pf_dict["inline_statements"], list
        ), "inline_statements should be a list"
        assert (
            len(pf_dict["inline_statements"]) >= 1
        ), "inline_statements should have at least 1 item"

    def test_perform_until_with_nested_if_and_calls(self):
        """Test complex structure: PERFORM UNTIL with IF containing CALLs."""
        src = """000100 IDENTIFICATION DIVISION.
000200 PROGRAM-ID. PU7.
000300 PROCEDURE DIVISION.
000400 PARA-1.
000500     PERFORM VARYING I FROM 1 BY 1
000600         UNTIL I > 100
000700         IF I > 50
000800             CALL 'HIGH' USING I
000900         ELSE
001000             CALL 'LOW' USING I
001100             CALL 'EXTRA' USING I
001200         END-IF
001300     END-PERFORM.
"""
        r = parse_cobol(
            src, filename="<mem>", error_recovery=ErrorRecoveryMode.COLLECT_ALL
        )

        perform_stmts = [
            s for s in r.ast.get_all_statements() if isinstance(s, PerformStatement)
        ]

        assert len(perform_stmts) >= 1
        pf = perform_stmts[0]

        # Find IF in inline_statements
        if_stmts = [s for s in pf.inline_statements if isinstance(s, IfStatement)]
        assert len(if_stmts) >= 1, "Should have IF in PERFORM inline statements"

        if_stmt = if_stmts[0]

        # Check THEN branch has CALL
        then_calls = [
            s for s in if_stmt.then_statements if isinstance(s, CallStatement)
        ]
        assert len(then_calls) >= 1, "THEN branch should have at least 1 CALL"

        # Check ELSE branch has CALLs
        else_calls = [
            s for s in if_stmt.else_statements if isinstance(s, CallStatement)
        ]
        assert len(else_calls) >= 2, "ELSE branch should have at least 2 CALLs"
