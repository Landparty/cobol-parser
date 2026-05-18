"""Branch coverage tests for UNLOCK parser.

Targets uncovered branches in parsers/statements/unlock_parser.py:
  - Line 29: IOUnlockStatement fallback when factory returns non-IOUnlockStatement
  - Branches 34->38, 49->54, 51->54: missing file name, missing period
"""

from __future__ import annotations

from cobolparser import parse_cobol


def _prog(procedure_stmts: str) -> str:
    return f"""
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TESTPROG.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-VAR   PIC X(10).
       PROCEDURE DIVISION.
       MAIN-PARA.
{procedure_stmts}
           GOBACK.
"""


class TestUnlockParserBranches:
    def test_unlock_records_plural(self):
        """UNLOCK file-name RECORDS (plural variant) takes the same branch as RECORD."""
        result = parse_cobol(_prog("           UNLOCK WS-VAR RECORDS."))
        assert result.ast is not None
        stmts = result.ast.find_statements("UNLOCK_STATEMENT")
        assert len(stmts) >= 1
        assert stmts[0].record_scope == "RECORD"

    def test_unlock_no_period(self):
        """UNLOCK with no trailing period — branch 51->54 (peek non-PERIOD)."""
        # Following statement provides the next token (non-PERIOD), exercising
        # the `if p and p.type == TokenType.PERIOD` false branch.
        result = parse_cobol(
            _prog("           UNLOCK WS-VAR\n" "           DISPLAY 'after unlock'.")
        )
        assert result.ast is not None
        stmts = result.ast.find_statements("UNLOCK_STATEMENT")
        assert len(stmts) >= 1

    def test_unlock_file_name_then_period(self):
        """UNLOCK file-name. — file name set, no RECORD clause."""
        result = parse_cobol(_prog("           UNLOCK WS-VAR."))
        assert result.ast is not None
        stmts = result.ast.find_statements("UNLOCK_STATEMENT")
        assert len(stmts) >= 1
        # file_name should be set; record_scope should NOT be RECORD
        assert stmts[0].file_name == "WS-VAR"
        assert stmts[0].record_scope is None or stmts[0].record_scope != "RECORD"


class TestUnlockParserDirectInvocation:
    """Drive the parser directly to hit edge branches (no file name; empty stream)."""

    def test_unlock_period_immediately(self):
        """UNLOCK followed by a period — peek returns PERIOD, branch 34->38."""
        from cobolparser.core.token_stream import TokenStream
        from cobolparser.lexer import CobolLexer
        from cobolparser.parsers.statements.unlock_parser import UnlockStatementParser

        tokens = CobolLexer("UNLOCK.").tokenize()
        stream = TokenStream(tokens)
        parser = UnlockStatementParser()
        stmt = parser.parse(stream)
        # No file name was set
        assert stmt.file_name is None or stmt.file_name == ""

    def test_unlock_empty_after_verb(self):
        """UNLOCK with empty stream after verb — branch 49->54 (stream is_empty)."""
        from cobolparser.core.token_stream import TokenStream
        from cobolparser.lexer import CobolLexer
        from cobolparser.parsers.statements.unlock_parser import UnlockStatementParser

        tokens = CobolLexer("UNLOCK").tokenize()
        stream = TokenStream(tokens)
        parser = UnlockStatementParser()
        stmt = parser.parse(stream)
        # Should not crash; no period to consume
        assert stmt is not None
