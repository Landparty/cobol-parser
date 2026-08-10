"""Regression tests for a PROCEDURE-DIVISION-level recovery bug distinct
from H9 (``reports/open-findings.md``): H9's ``looks_like_paragraph_boundary``
fix only covers individual statement parsers' own operand-collection loops
(DISPLAY, MOVE, COMPUTE, STRING/UNSTRING, INSPECT). The PROCEDURE DIVISION's
own generic boundary check --
:func:`cobolparser.parsers.divisions.procedure_boundaries.is_paragraph_or_section_start`,
consulted both by ``ProcedureDivisionParser._parse_paragraph_statements`` and
by ``StatementRecoveryHandler.skip_to_next_statement`` -- was never updated to
match, and has no notion of "this IDENTIFIER-shaped token is the verb (or
trailing operand) of the unsupported statement I am *currently* discarding,
not a new paragraph header".

Two distinct, user-reported failures share this one root cause:

* **Hang:** a bare unsupported verb with no dedicated lexer ``TokenType``
  (``PURGE``, ``RAISE``, ``RESUME`` -- they lex as plain ``IDENTIFIER``,
  see ``tests/regression/test_tier7_unsupported_verb_boundary.py``'s
  ``IDENTIFIER_ONLY_VERBS``) immediately followed by its own terminating
  period is indistinguishable, by shape alone, from ``PARA-NAME.`` --
  ``is_paragraph_or_section_start`` returns ``True`` for the verb token
  itself. ``_parse_paragraph_statements`` breaks out without consuming
  anything; the outer ``_parse_procedure_content`` loop then re-dispatches
  the same unconsumed token through
  ``StatementRecoveryHandler.skip_to_next_statement``, which *also* breaks
  immediately on the same check without consuming anything -- zero forward
  progress, forever.

* **Spurious paragraph:** an unsupported verb *with* a bare trailing
  identifier operand (``PURGE WS-X.``) does make initial progress --
  ``skip_to_next_statement`` consumes the verb token (recognized as a
  statement keyword with no registered parser) -- but then re-evaluates
  ``is_paragraph_or_section_start`` on the *operand* token ``WS-X``, which is
  followed by the statement's own terminating period and so looks exactly
  like a paragraph header. The recovery loop stops there without consuming
  ``WS-X`` or the period; the enclosing paragraph's statement loop then also
  stops, and the outer loop reinterprets ``WS-X`` as a brand-new paragraph
  name -- silently truncating the real paragraph's body and inventing a
  paragraph that was never in the source.

Both are fixed by teaching the shared boundary predicate two COBOL grammar
facts it was missing:

1. A reserved statement verb (:data:`STATEMENT_KEYWORDS`) can never legally
   be a paragraph name -- mirrors the guard
   ``looks_like_paragraph_boundary`` (H9) already applies.
2. Once ``skip_to_next_statement`` has started discarding a statement's
   tokens, nothing between the verb and that statement's own terminating
   period can be a paragraph boundary -- COBOL never nests a paragraph
   header inside an unterminated statement. The paragraph-boundary check is
   therefore only meaningful on the *first* token examined in a given
   ``skip_to_next_statement`` call (covering the case where the cursor is
   already sitting at a genuine boundary when recovery is invoked, e.g.
   after ``handle_statement_error`` on a statement whose own terminating
   period was already consumed).
"""

from cobolparser import parse_cobol
from cobolparser.core.registry import StatementParserRegistry
from cobolparser.core.token_stream import TokenStream
from cobolparser.lexer import TokenType, tokenize_cobol
from cobolparser.parsers.divisions.procedure_recovery import (
    UNSUPPORTED_VERBS,
    StatementRecoveryHandler,
)
from cobolparser.plugins.core import ErrorRecoveryMode


def _lexes_as_plain_identifier(verb: str) -> bool:
    """True if *verb* has no dedicated lexer TokenType and lexes as a plain
    IDENTIFIER -- indistinguishable, by token type alone, from a data name."""
    tokens = tokenize_cobol(f"       P.\n           {verb}.\n")
    return any(t.value == verb and t.type == TokenType.IDENTIFIER for t in tokens)


# Computed, not hand-picked, so this stays correct as UNSUPPORTED_VERBS gains
# or loses entries (e.g. a verb getting a real registered parser).
HANG_CANDIDATE_VERBS = sorted(
    v for v in UNSUPPORTED_VERBS if _lexes_as_plain_identifier(v)
)


PROC_TEMPLATE = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. PROBE.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-X                PIC 9(2) VALUE 0.

       PROCEDURE DIVISION.
       CLEAN-PARA.
           MOVE 1 TO WS-X.

       DIRTY-PARA.
{body}
           DISPLAY "done".
"""


def _parse(body: str):
    return parse_cobol(
        PROC_TEMPLATE.format(body=body),
        filename="probe.cbl",
        error_recovery=ErrorRecoveryMode.COLLECT_ALL,
    )


def _paragraph_names(result):
    return [p.paragraph_name for p in result.ast.get_division("PROCEDURE").paragraphs]


def _dirty_para(result):
    paras = result.ast.get_division("PROCEDURE").paragraphs
    return next(p for p in paras if p.paragraph_name == "DIRTY-PARA")


class TestSkipToNextStatementMakesForwardProgress:
    """Direct, hang-proof unit test on the recovery primitive itself: given
    an unsupported bare verb immediately followed by its terminating period,
    skip_to_next_statement must consume both, never return with the cursor
    unchanged. This is the actual invariant whose violation causes H11's
    infinite loop -- pinning it here means a regression is caught by a fast,
    bounded test instead of a hung end-to-end parse."""

    @staticmethod
    def _make_handler():
        class _FakeDivisionParser:
            def __init__(self):
                self._statement_registry = StatementParserRegistry()
                self.host = None

        return StatementRecoveryHandler(_FakeDivisionParser())

    @staticmethod
    def _stream_from(verb: str):
        src = f"""       IDENTIFICATION DIVISION.
       PROGRAM-ID. PROBE.
       PROCEDURE DIVISION.
       P.
           {verb}.
           DISPLAY "AFTER".
"""
        tokens = tokenize_cobol(src)
        start = next(i for i, t in enumerate(tokens) if t.value == verb)
        return TokenStream(tokens[start:])

    def test_consumes_bare_verb_and_its_period(self):
        for verb in HANG_CANDIDATE_VERBS:
            stream = self._stream_from(verb)
            handler = self._make_handler()
            handler.skip_to_next_statement(stream)

            assert not stream.is_empty(), f"{verb}: stream exhausted, DISPLAY lost too"
            remaining = stream.peek(0)
            assert remaining is not None and remaining.value != verb, (
                f"{verb}: skip_to_next_statement returned without consuming "
                f"the verb token -- zero forward progress"
            )
            # Skip whitespace/newlines to find the next real token.
            offset = 0
            tok = stream.peek(offset)
            while tok is not None and tok.type in (
                TokenType.WHITESPACE,
                TokenType.NEWLINE,
                TokenType.COMMENT,
            ):
                offset += 1
                tok = stream.peek(offset)
            assert tok is not None and tok.value == "DISPLAY", (
                f"{verb}: expected recovery to stop right before DISPLAY, "
                f"found {tok!r} instead"
            )


class TestLeadingFillerTokensDoNotDisableTheBoundaryCheck:
    """skip_to_next_statement's paragraph-boundary heuristic must stay live
    across leading filler tokens (NEWLINE/WHITESPACE/COMMENT) at the start
    of a call, not just the literal first-peeked token. handle_statement_error
    invokes skip_to_next_statement right where a failing statement parser
    left the cursor -- which is not guaranteed to be a meaningful token --
    so if a run of filler tokens preceded a genuine next paragraph, consuming
    the filler must not flip the recovery loop into "mid-statement, boundary
    check disabled" before it has seen a real token at all."""

    def test_boundary_still_detected_after_leading_newline(self):
        src = (
            "       IDENTIFICATION DIVISION.\n"
            "       PROGRAM-ID. PROBE.\n"
            "       PROCEDURE DIVISION.\n"
            "       DUMMY.\n"
            "           MOVE 1 TO WS-X\n"
            "\n"
            "       NEXT-PARA.\n"
            '           DISPLAY "X".\n'
        )
        tokens = tokenize_cobol(src)
        start = next(i for i, t in enumerate(tokens) if t.value == "WS-X") + 1
        assert tokens[start].type == TokenType.NEWLINE, (
            "test fixture assumption broken: expected a leading NEWLINE "
            f"token, got {tokens[start]!r}"
        )
        stream = TokenStream(tokens[start:])

        handler = TestSkipToNextStatementMakesForwardProgress._make_handler()
        handler.skip_to_next_statement(stream)

        assert not stream.is_empty()
        remaining = stream.peek(0)
        assert remaining is not None and remaining.value == "NEXT-PARA", (
            "leading filler tokens flipped the boundary check off before "
            f"the real paragraph header was seen: stopped at {remaining!r}"
        )


class TestBareUnsupportedVerbDoesNotHangAndPreservesParagraph:
    """End-to-end: a bare unsupported verb (no operand) inside a named
    paragraph must not hang the parser, must warn, and must leave the
    paragraph structure intact -- no swallowed body, no spurious paragraph."""

    def test_bare_verb_parses_cleanly(self):
        for verb in HANG_CANDIDATE_VERBS:
            result = _parse(f"           {verb}.\n")
            assert result.success, f"{verb}: {result.errors!r}"
            assert any(verb in w for w in result.warnings), (
                f"{verb}: expected an 'unsupported statement' warning, "
                f"got {result.warnings!r}"
            )
            assert _paragraph_names(result) == ["CLEAN-PARA", "DIRTY-PARA"], (
                f"{verb}: spurious paragraph invented: " f"{_paragraph_names(result)!r}"
            )
            dirty = _dirty_para(result)
            assert [type(s).__name__ for s in dirty.statements] == [
                "DisplayStatement"
            ], (
                f"{verb}: DIRTY-PARA body wrong: "
                f"{[type(s).__name__ for s in dirty.statements]!r}"
            )


class TestUnsupportedVerbWithBareOperandDoesNotInventParagraph:
    """End-to-end: an unsupported verb with a bare trailing identifier
    operand (PURGE WS-X.) must discard the whole statement up to its own
    period -- not stop at the operand and reinterpret it as a new paragraph
    header, truncating the real paragraph's body."""

    def test_verb_with_bare_identifier_operand_fully_discarded(self):
        for verb in sorted(UNSUPPORTED_VERBS):
            result = _parse(f"           {verb} WS-X.\n")
            assert result.success, f"{verb}: {result.errors!r}"
            assert any(verb in w for w in result.warnings), (
                f"{verb}: expected an 'unsupported statement' warning, "
                f"got {result.warnings!r}"
            )
            assert _paragraph_names(result) == ["CLEAN-PARA", "DIRTY-PARA"], (
                f"{verb}: spurious paragraph invented from the trailing "
                f"operand: {_paragraph_names(result)!r}"
            )
            dirty = _dirty_para(result)
            assert [type(s).__name__ for s in dirty.statements] == [
                "DisplayStatement"
            ], (
                f"{verb}: DIRTY-PARA body wrong (operand not fully "
                f"discarded): "
                f"{[type(s).__name__ for s in dirty.statements]!r}"
            )
