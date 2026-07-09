"""Regression tests for the HIGH-severity findings in reports/open-findings.md.

Each test class documents exactly what was broken (per the finding) and
locks down the corrected behavior so future refactors cannot silently
re-introduce the same gap. Test class names carry the finding ID (H1-H8)
for direct traceability back to the report.
"""

from __future__ import annotations

import logging
import os
import tempfile
import textwrap

import pytest

from cobolparser import ErrorRecoveryMode, parse_cobol
from cobolparser.analysis import MoveTypeChecker
from cobolparser.core.exceptions import ParseError
from cobolparser.models.statements import (
    ComputeStatement,
    IOCloseStatement,
    PerformStatement,
    SetStatement,
)
from cobolparser.preprocess import PathTraversalError
from cobolparser.preprocess.models import CopybookSearchPath
from cobolparser.preprocess.path_resolver import (
    PathResolver,
    validate_path_within_directory,
)


def _proc_program(procedure_body: str) -> str:
    """Wrap bare PROCEDURE DIVISION statements in a minimal COBOL program."""
    return textwrap.dedent(f"""\
        IDENTIFICATION DIVISION.
        PROGRAM-ID. REGTEST.
        DATA DIVISION.
        WORKING-STORAGE SECTION.
        01 WS-X PIC X.
        01 WS-PTR USAGE POINTER.
        01 WS-TARGET USAGE POINTER.
        PROCEDURE DIVISION.
        MAIN-PARA.
        {procedure_body}
        """)


def _compute_program(procedure_body: str) -> str:
    """Wrap bare PROCEDURE DIVISION statements with numeric data items for COMPUTE tests."""
    return textwrap.dedent(f"""\
        IDENTIFICATION DIVISION.
        PROGRAM-ID. REGTEST.
        DATA DIVISION.
        WORKING-STORAGE SECTION.
        01 X PIC 9(4).
        01 A PIC 9(4).
        01 B PIC 9(4).
        PROCEDURE DIVISION.
        MAIN-PARA.
        {procedure_body}
        """)


def _statements(result):
    proc = result.ast.procedure_division
    if proc.paragraphs:
        return proc.paragraphs[0].statements
    if proc.sections and proc.sections[0].paragraphs:
        return proc.sections[0].paragraphs[0].statements
    return []


class TestH1SetAddressOf:
    """H1 — SET ADDRESS OF x TO y produced an empty SetStatement.

    OF lexes as its own dedicated TokenType (not IDENTIFIER), so the
    target-collection loop's ``else: break`` fired immediately on OF and
    never reached the pointer/TO/target tokens that followed.
    """

    def test_set_address_of_populates_target_and_value(self):
        result = parse_cobol(
            _proc_program("    SET ADDRESS OF WS-PTR TO WS-TARGET.\n")
        )
        set_stmts = [s for s in _statements(result) if isinstance(s, SetStatement)]
        assert len(set_stmts) == 1
        stmt = set_stmts[0]
        assert stmt.targets == ["WS-PTR"]
        assert stmt.set_type == "TO"
        assert stmt.value == "WS-TARGET"
        assert not any(
            "Unparsed tokens" in w for w in result.warnings
        ), result.warnings


class TestH2ComputeUnbalancedParens:
    """H2 — COMPUTE with unbalanced parentheses was silently accepted and
    could swallow the following statement.

    ``paren_depth`` was only used to gate the statement-boundary check
    (which fired only at ``paren_depth == 0``); once left non-zero by a
    stray '(' it never returned to zero, so a well-formed statement
    immediately following the malformed COMPUTE got folded into the
    expression string instead of being parsed on its own.
    """

    def test_unbalanced_parens_reported_as_error(self):
        result = parse_cobol(
            _compute_program("    COMPUTE X = ((A + B)\n    DISPLAY 'DONE'.\n")
        )
        assert result.success is False
        assert any(
            "unbalanced parentheses" in str(e).lower() for e in result.errors
        ), result.errors

    def test_unbalanced_parens_does_not_swallow_following_statement(self):
        result = parse_cobol(
            _compute_program("    COMPUTE X = ((A + B)\n    DISPLAY 'DONE'.\n"),
            error_recovery=ErrorRecoveryMode.COLLECT_ALL,
        )
        stmts = _statements(result)
        display_stmts = [s for s in stmts if type(s).__name__ == "DisplayStatement"]
        assert len(display_stmts) == 1
        assert display_stmts[0].display_items == ['"DONE"']
        compute_stmts = [s for s in stmts if isinstance(s, ComputeStatement)]
        assert not any(
            "DISPLAY" in (c.expression or "") for c in compute_stmts
        ), compute_stmts

    def test_balanced_parens_still_parse_cleanly(self):
        result = parse_cobol(
            _compute_program("    COMPUTE X = ((A + B) * 2).\n")
        )
        assert result.success is True
        assert result.errors == []


def _perform_program(perform_stmt: str) -> str:
    return textwrap.dedent(f"""\
        IDENTIFICATION DIVISION.
        PROGRAM-ID. REGTEST.
        DATA DIVISION.
        WORKING-STORAGE SECTION.
        01 WS-COUNT PIC 9(2).
        PROCEDURE DIVISION.
        MAIN-PARA.
        {perform_stmt}
        PARA-1.
            DISPLAY 'X'.
        """)


class TestH3PerformTrailingIdentifier:
    """H3 — PERFORM para-name JUNK-TOKEN. silently dropped the trailing
    identifier: no set_times_clause() call, no warning at all
    (errors=[], warnings=[]), times_count stayed None. The dangling
    identifier + period was then left for the procedure-division parser to
    misread as the start of a new (empty) paragraph.
    """

    def test_trailing_junk_identifier_reported_not_silently_dropped(self):
        result = parse_cobol(_perform_program("    PERFORM PARA-1 JUNK-TOKEN.\n"))
        perform_stmts = [
            s for s in _statements(result) if isinstance(s, PerformStatement)
        ]
        assert len(perform_stmts) == 1
        assert perform_stmts[0].times_count is None
        assert any("JUNK-TOKEN" in w for w in result.warnings), result.warnings
        paragraph_names = [
            p.paragraph_name for p in result.ast.procedure_division.paragraphs
        ]
        assert "JUNK-TOKEN" not in paragraph_names

    def test_numeric_times_clause_still_parses(self):
        result = parse_cobol(_perform_program("    PERFORM PARA-1 5 TIMES.\n"))
        perform_stmts = [
            s for s in _statements(result) if isinstance(s, PerformStatement)
        ]
        assert perform_stmts[0].times_count == 5
        assert result.warnings == []

    def test_variable_times_clause_still_parses(self):
        result = parse_cobol(_perform_program("    PERFORM PARA-1 WS-COUNT TIMES.\n"))
        perform_stmts = [
            s for s in _statements(result) if isinstance(s, PerformStatement)
        ]
        assert perform_stmts[0].times_count == "WS-COUNT"
        assert result.warnings == []

    def test_missing_period_before_real_verb_not_swallowed(self):
        # PURGE lexes as a plain IDENTIFIER (no dedicated TokenType); it
        # must not be absorbed as a bogus TIMES candidate just because it
        # follows a PERFORM target with no separating period.
        result = parse_cobol(
            _perform_program("    PERFORM PARA-1\n    PURGE WS-COUNT.\n")
        )
        stmts = _statements(result)
        assert any(type(s).__name__ == "PerformStatement" for s in stmts)
        assert any("PURGE" in w for w in result.warnings), result.warnings


class TestH4PerformBareExceptLogging:
    """H4 — perform_parser.py had 5 bare ``except ParseError: pass`` sites
    with zero logging (not even DEBUG), unlike the shared
    ``try_parse_nested_statement`` helper in _utils.py. A VARYING/UNTIL/
    inline-body parse failure could vanish completely untraceable.
    """

    def test_inline_statement_parse_failure_is_logged_at_debug(
        self, monkeypatch, caplog
    ):
        from cobolparser.parsers.statements import perform_parser as perform_parser_module

        def _raise(*args, **kwargs):
            raise ParseError("synthetic failure for H4 regression test")

        monkeypatch.setattr(
            perform_parser_module, "try_parse_nested_statement", _raise
        )

        caplog.set_level(logging.DEBUG, logger=perform_parser_module.__name__)

        program = textwrap.dedent("""\
            IDENTIFICATION DIVISION.
            PROGRAM-ID. REGTEST.
            PROCEDURE DIVISION.
            MAIN-PARA.
                PERFORM 3 TIMES
                    DISPLAY 'X'
                END-PERFORM.
                STOP RUN.
            """)
        # Must not raise/crash despite the injected nested-parse failure.
        parse_cobol(program)
        assert any(
            "PERFORM inline statement body parse suppressed" in rec.message
            for rec in caplog.records
        ), [rec.message for rec in caplog.records]


class TestH5MoveTypeCheckerUnresolvedCount:
    """H5 — MoveTypeChecker silently skipped every unresolvable MOVE with
    no count: UNKNOWN/FIGURATIVE source category -> return; UNKNOWN target
    category -> continue. A MoveTypeReport with violations=[] gave a false
    all-clear indistinguishable from "everything was actually checked".
    """

    def test_undeclared_identifiers_are_counted_as_unresolved(self):
        program = textwrap.dedent("""\
            IDENTIFICATION DIVISION.
            PROGRAM-ID. REGTEST.
            DATA DIVISION.
            WORKING-STORAGE SECTION.
            01 WS-X PIC X.
            PROCEDURE DIVISION.
            MAIN-PARA.
                MOVE UNDECLARED-1 TO WS-X.
                MOVE UNDECLARED-2 TO WS-X.
                MOVE UNDECLARED-3 TO WS-X.
            """)
        result = parse_cobol(program)
        report = MoveTypeChecker().check(result.ast)
        assert report.violations == []
        assert report.unresolved_count == 3
        assert report.to_dict()["unresolved_count"] == 3

    def test_resolvable_moves_do_not_inflate_unresolved_count(self):
        program = textwrap.dedent("""\
            IDENTIFICATION DIVISION.
            PROGRAM-ID. REGTEST.
            DATA DIVISION.
            WORKING-STORAGE SECTION.
            01 WS-A PIC X(5).
            01 WS-B PIC X(5).
            PROCEDURE DIVISION.
            MAIN-PARA.
                MOVE WS-A TO WS-B.
            """)
        result = parse_cobol(program)
        report = MoveTypeChecker().check(result.ast)
        assert report.unresolved_count == 0


def _close_program(close_stmt: str) -> str:
    return textwrap.dedent(f"""\
        IDENTIFICATION DIVISION.
        PROGRAM-ID. REGTEST.
        PROCEDURE DIVISION.
        MAIN-PARA.
        {close_stmt}
        """)


class TestH8CloseCombinedOptions:
    """H8 — CLOSE used an if/elif chain across REEL/UNIT/WITH (one branch
    per file, applied only once), and the outer per-file loop required the
    next token to be a plain IDENTIFIER to continue -- so once one option
    was consumed, a following non-IDENTIFIER clause token (e.g. WITH)
    ended the whole loop. ``CLOSE F REEL WITH NO REWIND.`` kept only
    ``reel: true`` and silently dropped ``no_rewind``, only warn-masked.
    """

    def test_reel_with_no_rewind_both_survive(self):
        result = parse_cobol(_close_program("    CLOSE F REEL WITH NO REWIND.\n"))
        assert result.warnings == []
        close_stmts = [
            s for s in _statements(result) if isinstance(s, IOCloseStatement)
        ]
        assert len(close_stmts) == 1
        options = close_stmts[0].close_options["F"]
        assert options["reel"] is True
        assert options["no_rewind"] is True

    def test_multiple_files_with_distinct_combined_options(self):
        program = _close_program(
            "    CLOSE F1 REEL WITH NO REWIND F2 WITH LOCK.\n"
        )
        result = parse_cobol(program)
        assert result.warnings == []
        close_stmts = [
            s for s in _statements(result) if isinstance(s, IOCloseStatement)
        ]
        options = close_stmts[0].close_options
        assert options["F1"]["reel"] is True
        assert options["F1"]["no_rewind"] is True
        assert options["F2"]["with_lock"] is True
        assert options["F2"]["reel"] is False

    def test_plain_close_still_parses(self):
        result = parse_cobol(_close_program("    CLOSE F.\n"))
        assert result.warnings == []
        close_stmts = [
            s for s in _statements(result) if isinstance(s, IOCloseStatement)
        ]
        options = close_stmts[0].close_options["F"]
        assert options == {
            "reel": False,
            "unit": False,
            "no_rewind": False,
            "with_lock": False,
        }


class TestH7UnterminatedStringWarns:
    """H7 — an unterminated string literal in the default (free-form-lexed)
    parse path was fully silent: lexer.py's error was gated on
    ``if not self.free_form``, and ``parse_cobol()`` always lexes with
    ``free_form=True`` after normalization, so the literal was silently
    closed at the line boundary with no error and no warning. The lexer
    now records a warning (surfaced via ``ParseResult.warnings``) instead
    of staying silent, without promoting it to a hard error -- a lone
    quote can legitimately appear in a free-form comment.
    """

    def test_unclosed_quote_in_default_path_produces_warning(self):
        program = textwrap.dedent("""\
            IDENTIFICATION DIVISION.
            PROGRAM-ID. REGTEST.
            PROCEDURE DIVISION.
            MAIN-PARA.
                DISPLAY "UNCLOSED
                DISPLAY "AFTER".
            """)
        result = parse_cobol(program, error_recovery=ErrorRecoveryMode.COLLECT_ALL)
        assert result.errors == []
        assert any(
            "Unterminated string literal" in w for w in result.warnings
        ), result.warnings

    def test_well_formed_strings_produce_no_warning(self):
        program = textwrap.dedent("""\
            IDENTIFICATION DIVISION.
            PROGRAM-ID. REGTEST.
            PROCEDURE DIVISION.
            MAIN-PARA.
                DISPLAY "CLOSED".
                DISPLAY "ALSO CLOSED".
            """)
        result = parse_cobol(program)
        assert result.warnings == []

    def test_following_statement_still_parses_after_unclosed_literal(self):
        program = textwrap.dedent("""\
            IDENTIFICATION DIVISION.
            PROGRAM-ID. REGTEST.
            PROCEDURE DIVISION.
            MAIN-PARA.
                DISPLAY "UNCLOSED
                DISPLAY "AFTER".
            """)
        result = parse_cobol(program, error_recovery=ErrorRecoveryMode.COLLECT_ALL)
        stmts = _statements(result)
        display_stmts = [s for s in stmts if type(s).__name__ == "DisplayStatement"]
        assert len(display_stmts) == 2


class TestH6PathResolverContainment:
    """H6 — the Tier-2 (directory-index) copybook resolver fast path
    returned an indexed path with only an ``os.path.getsize()`` check --
    never ``validate_path_within_directory()``. Since the index is built via
    ``os.scandir()`` + ``entry.is_file()`` (which follows symlinks), a
    symlink inside a search directory pointing outside it would be served
    with no containment check. A live Windows symlink needs elevated
    privilege to create in CI, so this test drives the same code path by
    seeding ``_dir_index`` directly with an escaping absolute path -- this
    is exactly what a followed symlink would produce.

    Separately, the naive ``".." in file_path`` substring guard flagged
    filenames merely containing "..", e.g. "weird..name.cpy", as traversal
    attempts despite not being one.
    """

    def test_tier2_fast_path_rejects_index_entry_outside_search_dir(self):
        with tempfile.TemporaryDirectory() as outside, tempfile.TemporaryDirectory() as inside:
            outside_file = os.path.join(outside, "SECRET.CPY")
            with open(outside_file, "w") as f:
                f.write("01 SECRET PIC X.\n")

            cfg = CopybookSearchPath(directories=[inside], extensions=[".CPY"])
            resolver = PathResolver(cfg)
            # Simulate what _build_directory_index() would produce if
            # os.scandir() had followed a symlink pointing outside `inside`.
            resolver._dir_index = {"SECRET": os.path.abspath(outside_file)}

            with pytest.raises(PathTraversalError):
                resolver.resolve("SECRET")

    def test_tier2_fast_path_still_resolves_legitimate_entries(self):
        with tempfile.TemporaryDirectory() as inside:
            member_file = os.path.join(inside, "MEMBER.CPY")
            with open(member_file, "w") as f:
                f.write("01 MEMBER PIC X.\n")

            cfg = CopybookSearchPath(directories=[inside], extensions=[".CPY"])
            resolver = PathResolver(cfg)
            resolved = resolver.resolve("MEMBER")
            assert os.path.abspath(resolved) == os.path.abspath(member_file)

    def test_filename_containing_dotdot_substring_is_not_a_false_positive(self):
        with tempfile.TemporaryDirectory() as base:
            weird = os.path.join(base, "weird..name.cpy")
            with open(weird, "w") as f:
                f.write("x")
            assert validate_path_within_directory(weird, base) is True

    def test_real_traversal_segment_is_still_rejected(self):
        with tempfile.TemporaryDirectory() as base:
            traversal_path = os.path.join(base, "..", "etc", "passwd")
            with pytest.raises(PathTraversalError):
                validate_path_within_directory(traversal_path, base)
