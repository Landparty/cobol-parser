"""Regression tests for the clause-continuation / SQL-special-register
refinement of :func:`cobolparser.parsers.statements._utils.
looks_like_paragraph_boundary`.

The H9 fix taught six operand-collection loops (DISPLAY, MOVE, COMPUTE,
STRING/UNSTRING, INSPECT) to stop when a line-starting bare ``IDENTIFIER``
looks like the start of the next statement rather than a trailing operand.
Two real-world shapes were being misclassified by that heuristic:

* **Clause-continuation keywords.** Reserved COBOL clause words that the
  lexer does not give a dedicated ``TokenType`` (``DELIMITED``, ``TALLYING``,
  ``POINTER``, ...) lex as plain ``IDENTIFIER``. In the layout IBM/GnuCOBOL
  style guides recommend -- each ``DELIMITED BY SIZE`` clause of a
  multi-source ``STRING`` on its own continuation line -- every
  ``DELIMITED`` past the first opens a new source line and so was at risk of
  being read as a new statement, silently truncating the ``STRING`` AST.

* **SQL special registers.** ``SQLCODE``/``SQLSTATE`` are provided by the
  DB2 precompiler and referenced without any ``WORKING-STORAGE``
  declaration, so the ``known_data_names`` cross-check cannot see them. A
  period-less ``DISPLAY`` followed by a bare ``SQLCODE`` on its own line
  (``DISPLAY WS-MSG`` / ``SQLCODE.``) had ``SQLCODE`` misread as a paragraph
  boundary.

Both are now excluded via ``CLAUSE_CONTINUATION_KEYWORDS`` /
``SQL_SPECIAL_REGISTERS``. The genuine-boundary control cases below confirm
the exclusions did not blind the heuristic to real missing-period recovery.
"""

from cobolparser import parse_cobol
from cobolparser.parsers.statements._utils import (
    CLAUSE_CONTINUATION_KEYWORDS,
    SQL_SPECIAL_REGISTERS,
)
from cobolparser.plugins.core import ErrorRecoveryMode


def _parse(source: str):
    return parse_cobol(source, error_recovery=ErrorRecoveryMode.COLLECT_ALL)


class TestClauseContinuationKeywords:
    """Reserved clause words on their own continuation line are operands,
    never a swallowed statement boundary."""

    def test_multi_clause_string_delimited_by_on_own_lines(self) -> None:
        source = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. STRTEST.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-A   PIC X(5) VALUE 'AAAAA'.
       01 WS-B   PIC X(5) VALUE 'BBBBB'.
       01 WS-OUT PIC X(20).
       PROCEDURE DIVISION.
       MAIN-PARA.
           STRING WS-A
               DELIMITED BY SIZE
               WS-B
               DELIMITED BY SIZE
               INTO WS-OUT
           END-STRING.
           STOP RUN.
"""
        result = _parse(source)
        assert result.success, result.errors
        assert result.warnings == []
        strings = result.ast.find_all_by_type("StringStatement")
        assert len(strings) == 1

    def test_delimited_is_excluded_from_boundary_set(self) -> None:
        # Guards the frozenset contents the fix relies on.
        assert "DELIMITED" in CLAUSE_CONTINUATION_KEYWORDS
        assert "TALLYING" in CLAUSE_CONTINUATION_KEYWORDS
        assert "POINTER" in CLAUSE_CONTINUATION_KEYWORDS


class TestSqlSpecialRegisters:
    """Bare SQLCODE/SQLSTATE references are not swallowed statement
    boundaries even when they open their own source line."""

    def test_period_less_display_then_bare_sqlcode(self) -> None:
        source = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. SQLTEST.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-MSG PIC X(20) VALUE 'ERR'.
       PROCEDURE DIVISION.
       MAIN-PARA.
           DISPLAY WS-MSG
           SQLCODE.
           STOP RUN.
"""
        result = _parse(source)
        assert result.success, result.errors
        assert result.warnings == []
        assert SQL_SPECIAL_REGISTERS == frozenset({"SQLCODE", "SQLSTATE"})


class TestGenuineBoundaryStillDetected:
    """Control: the exclusions must not blind the heuristic to a real
    missing-period paragraph boundary."""

    def test_period_less_display_before_real_paragraph_is_still_caught(
        self,
    ) -> None:
        # DISPLAY has no terminating period; NEXT-PARA is a genuine following
        # paragraph header that must not be absorbed as a DISPLAY operand.
        source = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. BNDTEST.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-MSG PIC X(10) VALUE 'HI'.
       PROCEDURE DIVISION.
       MAIN-PARA.
           DISPLAY WS-MSG
       NEXT-PARA.
           STOP RUN.
"""
        result = _parse(source)
        # The following paragraph header is recognized (not swallowed): the
        # parser recovers and both paragraphs are present in the AST.
        paragraphs = result.ast.find_all_by_type("CobolParagraph")
        para_names = {
            (p.to_dict().get("paragraph_name") or "").upper() for p in paragraphs
        }
        assert "MAIN-PARA" in para_names
        assert "NEXT-PARA" in para_names
