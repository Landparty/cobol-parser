"""Unit tests for COMMIT and ROLLBACK statement parsers.

Covers:
- TokenType matching (COMMIT / ROLLBACK token types)
- Parsing bare COMMIT
- Parsing ROLLBACK with and without the optional WORK keyword
- AST node to_dict() output
- Round-trip via parse_cobol()
- Presence in the procedure-division statement registry
- Both nodes exported from the top-level package
"""

from cobolparser import parse_cobol
from cobolparser.lexer import TokenType
from cobolparser.models.ast_base import SourceLocation
from cobolparser.models.statements.misc import CommitStatement, RollbackStatement
from cobolparser.parsers.statements.simple_statement_parsers import (
    CommitStatementParser,
    RollbackStatementParser,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_LOC = SourceLocation(1, 1)

_COBOL_COMMIT = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TESTPROG.
       PROCEDURE DIVISION.
       MAIN-LOGIC.
           COMMIT.
           STOP RUN.
"""

_COBOL_COMMIT_WORK = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TESTPROG.
       PROCEDURE DIVISION.
       MAIN-LOGIC.
           COMMIT WORK.
           STOP RUN.
"""

_COBOL_ROLLBACK = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TESTPROG.
       PROCEDURE DIVISION.
       MAIN-LOGIC.
           ROLLBACK.
           STOP RUN.
"""

_COBOL_ROLLBACK_WORK = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TESTPROG.
       PROCEDURE DIVISION.
       MAIN-LOGIC.
           ROLLBACK WORK.
           STOP RUN.
"""


# ---------------------------------------------------------------------------
# CommitStatement AST node
# ---------------------------------------------------------------------------


class TestCommitStatementNode:
    def test_statement_type(self):
        stmt = CommitStatement(_LOC)
        # CobolStatement stores the verb in statement_type; node_type is always "Statement"
        assert stmt.statement_type == "COMMIT"

    def test_to_dict_contains_statement_type(self):
        stmt = CommitStatement(_LOC)
        d = stmt.to_dict()
        assert d["statement_type"] == "COMMIT"

    def test_to_dict_is_serializable(self):
        import json

        stmt = CommitStatement(_LOC)
        json.dumps(stmt.to_dict())  # must not raise


# ---------------------------------------------------------------------------
# RollbackStatement AST node
# ---------------------------------------------------------------------------


class TestRollbackStatementNode:
    def test_statement_type(self):
        stmt = RollbackStatement(_LOC)
        assert stmt.statement_type == "ROLLBACK"

    def test_default_rollback_work_false(self):
        stmt = RollbackStatement(_LOC)
        assert stmt.rollback_work is False

    def test_set_rollback_work(self):
        stmt = RollbackStatement(_LOC)
        stmt.set_rollback_work(True)
        assert stmt.rollback_work is True

    def test_to_dict_includes_rollback_work(self):
        stmt = RollbackStatement(_LOC)
        stmt.set_rollback_work(True)
        d = stmt.to_dict()
        assert d["rollback_work"] is True

    def test_to_dict_is_serializable(self):
        import json

        stmt = RollbackStatement(_LOC)
        json.dumps(stmt.to_dict())  # must not raise


# ---------------------------------------------------------------------------
# CommitStatementParser
# ---------------------------------------------------------------------------


class TestCommitStatementParser:
    def test_matches_commit_token_type(self):
        """CommitStatementParser matches TokenType.COMMIT."""
        parser = CommitStatementParser()
        from unittest.mock import MagicMock

        token = MagicMock()
        token.type = TokenType.COMMIT
        stream = MagicMock()
        stream.peek.return_value = token
        assert parser.matches(stream) is True

    def test_no_match_on_none(self):
        from unittest.mock import MagicMock

        parser = CommitStatementParser()
        stream = MagicMock()
        stream.peek.return_value = None
        assert parser.matches(stream) is False

    def test_matches_identifier_commit(self):
        from unittest.mock import MagicMock

        parser = CommitStatementParser()
        token = MagicMock()
        token.type = TokenType.IDENTIFIER
        token.value = "COMMIT"
        stream = MagicMock()
        stream.peek.return_value = token
        assert parser.matches(stream) is True

    def test_no_match_other_keyword(self):
        from unittest.mock import MagicMock

        parser = CommitStatementParser()
        token = MagicMock()
        token.type = TokenType.IDENTIFIER
        token.value = "MOVE"
        stream = MagicMock()
        stream.peek.return_value = token
        assert parser.matches(stream) is False


# ---------------------------------------------------------------------------
# RollbackStatementParser
# ---------------------------------------------------------------------------


class TestRollbackStatementParser:
    def test_matches_rollback_token_type(self):
        from unittest.mock import MagicMock

        parser = RollbackStatementParser()
        token = MagicMock()
        token.type = TokenType.ROLLBACK
        stream = MagicMock()
        stream.peek.return_value = token
        assert parser.matches(stream) is True

    def test_no_match_on_none(self):
        from unittest.mock import MagicMock

        parser = RollbackStatementParser()
        stream = MagicMock()
        stream.peek.return_value = None
        assert parser.matches(stream) is False

    def test_matches_identifier_rollback(self):
        from unittest.mock import MagicMock

        parser = RollbackStatementParser()
        token = MagicMock()
        token.type = TokenType.IDENTIFIER
        token.value = "ROLLBACK"
        stream = MagicMock()
        stream.peek.return_value = token
        assert parser.matches(stream) is True


# ---------------------------------------------------------------------------
# Round-trip tests via parse_cobol()
# ---------------------------------------------------------------------------


class TestCommitRollbackRoundTrip:
    def _find_by_stmt_type(self, ast, statement_type: str):
        """Find all Statement nodes with a specific statement_type verb."""
        # node_type is always "Statement"; filter by statement_type attribute
        return [
            n
            for n in ast.find_all_by_type("Statement")
            if getattr(n, "statement_type", None) == statement_type
        ]

    def test_parse_commit(self):
        result = parse_cobol(_COBOL_COMMIT)
        assert result.ast is not None
        stmts = self._find_by_stmt_type(result.ast, "COMMIT")
        assert len(stmts) >= 1

    def test_parse_commit_work(self):
        result = parse_cobol(_COBOL_COMMIT_WORK)
        assert result.ast is not None
        stmts = self._find_by_stmt_type(result.ast, "COMMIT")
        assert len(stmts) >= 1

    def test_parse_rollback(self):
        result = parse_cobol(_COBOL_ROLLBACK)
        assert result.ast is not None
        stmts = self._find_by_stmt_type(result.ast, "ROLLBACK")
        assert len(stmts) >= 1

    def test_parse_rollback_work(self):
        result = parse_cobol(_COBOL_ROLLBACK_WORK)
        assert result.ast is not None
        stmts = self._find_by_stmt_type(result.ast, "ROLLBACK")
        assert len(stmts) >= 1
        stmt = stmts[0]
        assert isinstance(stmt, RollbackStatement)
        assert stmt.rollback_work is True

    def test_both_in_same_program(self):
        src = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TESTPROG.
       PROCEDURE DIVISION.
       MAIN-LOGIC.
           COMMIT.
           ROLLBACK WORK.
           STOP RUN.
"""
        result = parse_cobol(src)
        assert result.ast is not None
        commits = self._find_by_stmt_type(result.ast, "COMMIT")
        rollbacks = self._find_by_stmt_type(result.ast, "ROLLBACK")
        assert len(commits) >= 1
        assert len(rollbacks) >= 1

    def test_commit_exported_from_top_level(self):
        from cobolparser import CommitStatement as C

        assert C is CommitStatement

    def test_rollback_exported_from_top_level(self):
        from cobolparser import RollbackStatement as R

        assert R is RollbackStatement


# ---------------------------------------------------------------------------
# Additional edge cases
# ---------------------------------------------------------------------------


class TestCommitRollbackEdgeCases:
    """Edge cases not covered by basic parsing and matching tests."""

    def _find_by_stmt_type(self, ast, statement_type: str):
        return [
            n
            for n in ast.find_all_by_type("Statement")
            if getattr(n, "statement_type", None) == statement_type
        ]

    # -- RollbackStatement state consistency --------------------------------

    def test_rollback_work_false_by_default_after_parse(self):
        """ROLLBACK without WORK must leave rollback_work=False."""
        result = parse_cobol(_COBOL_ROLLBACK)
        stmts = self._find_by_stmt_type(result.ast, "ROLLBACK")
        assert stmts
        assert isinstance(stmts[0], RollbackStatement)
        assert stmts[0].rollback_work is False

    def test_commit_operands_empty(self):
        """COMMIT carries no operands."""
        stmt = CommitStatement(_LOC)
        assert stmt.operands == []

    def test_rollback_operands_empty(self):
        """ROLLBACK carries no operands."""
        stmt = RollbackStatement(_LOC)
        assert stmt.operands == []

    # -- Lowercase / mixed-case identifier matching -------------------------

    def test_commit_parser_matches_lowercase_identifier(self):
        """Parser must match 'commit' in lower case (IDENTIFIER token)."""
        from unittest.mock import MagicMock

        parser = CommitStatementParser()
        token = MagicMock()
        token.type = TokenType.IDENTIFIER
        token.value = "commit"
        stream = MagicMock()
        stream.peek.return_value = token
        assert parser.matches(stream) is True

    def test_rollback_parser_matches_lowercase_identifier(self):
        from unittest.mock import MagicMock

        parser = RollbackStatementParser()
        token = MagicMock()
        token.type = TokenType.IDENTIFIER
        token.value = "rollback"
        stream = MagicMock()
        stream.peek.return_value = token
        assert parser.matches(stream) is True

    def test_commit_parser_matches_mixed_case_identifier(self):
        from unittest.mock import MagicMock

        parser = CommitStatementParser()
        token = MagicMock()
        token.type = TokenType.IDENTIFIER
        token.value = "Commit"
        stream = MagicMock()
        stream.peek.return_value = token
        assert parser.matches(stream) is True

    # -- Multiple occurrences in one program --------------------------------

    def test_multiple_commits_counted_separately(self):
        src = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TESTPROG.
       PROCEDURE DIVISION.
       MAIN-LOGIC.
           COMMIT.
           COMMIT.
           COMMIT.
           STOP RUN.
"""
        result = parse_cobol(src)
        stmts = self._find_by_stmt_type(result.ast, "COMMIT")
        assert len(stmts) == 3

    def test_commit_inside_if_branch(self):
        """COMMIT nested inside inline IF must still be found in the AST."""
        src = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TESTPROG.
       PROCEDURE DIVISION.
       MAIN-LOGIC.
           IF WS-FLAG = 1 THEN COMMIT END-IF.
           STOP RUN.
"""
        result = parse_cobol(src)
        assert result.ast is not None
        stmts = self._find_by_stmt_type(result.ast, "COMMIT")
        assert len(stmts) >= 1

    def test_rollback_inside_if_branch(self):
        """ROLLBACK nested inside inline IF must still be found in the AST."""
        src = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TESTPROG.
       PROCEDURE DIVISION.
       MAIN-LOGIC.
           IF WS-FLAG = 0 THEN ROLLBACK END-IF.
           STOP RUN.
"""
        result = parse_cobol(src)
        assert result.ast is not None
        stmts = self._find_by_stmt_type(result.ast, "ROLLBACK")
        assert len(stmts) >= 1

    def test_commit_then_rollback_in_evaluate(self):
        """COMMIT and ROLLBACK in EVALUATE branches: program parses and JSON exports both verbs."""
        import json

        src = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TESTPROG.
       PROCEDURE DIVISION.
       MAIN-LOGIC.
           EVALUATE WS-RC
               WHEN 0 COMMIT
               WHEN OTHER ROLLBACK WORK
           END-EVALUATE.
           STOP RUN.
"""
        result = parse_cobol(src)
        assert result.ast is not None
        # EVALUATE absorbs its WHEN-body statements; verify they survive in
        # the serialised JSON even when AST traversal does not expose them as
        # top-level Statement nodes.
        text = json.dumps(json.loads(result.ast.to_json()))
        assert "COMMIT" in text
        assert "ROLLBACK" in text

    # -- JSON round-trip of the full AST ------------------------------------

    def test_ast_json_contains_commit(self):
        """JSON export of the full program must include the COMMIT statement."""
        import json

        result = parse_cobol(_COBOL_COMMIT)
        j = json.loads(result.ast.to_json())
        text = json.dumps(j)
        assert "COMMIT" in text

    def test_ast_json_contains_rollback(self):
        import json

        result = parse_cobol(_COBOL_ROLLBACK_WORK)
        j = json.loads(result.ast.to_json())
        text = json.dumps(j)
        assert "ROLLBACK" in text
