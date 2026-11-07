"""Regression tests for the MEDIUM-severity findings in reports/open-findings.md.

Mirrors tests/regression/test_open_findings_high_regressions.py's convention:
one TestM<N>... class per finding, named for direct traceability.
"""

from __future__ import annotations

import textwrap

from cobolparser import parse_cobol
from cobolparser.models.statements import DisplayStatement
from cobolparser.preprocess import normalize_fixed_format


def _data_program(data_item_line: str) -> str:
    """Wrap a single WORKING-STORAGE data-item line in a minimal program."""
    return textwrap.dedent(f"""\
        IDENTIFICATION DIVISION.
        PROGRAM-ID. REGTEST.
        DATA DIVISION.
        WORKING-STORAGE SECTION.
        {data_item_line}
        PROCEDURE DIVISION.
        MAIN-PARA.
            DISPLAY "OK".
            STOP RUN.
        """)


def _proc_program(procedure_body: str) -> str:
    """Wrap bare PROCEDURE DIVISION statements in a minimal COBOL program."""
    return textwrap.dedent(f"""\
        IDENTIFICATION DIVISION.
        PROGRAM-ID. REGTEST.
        DATA DIVISION.
        WORKING-STORAGE SECTION.
        01 WS-X PIC X(20).
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


class TestM16SlashEditedPicture:
    """M16 -- PIC 99/99/99 corrupted DATA DIVISION structure.

    _PICTURE_SYMBOL_TOKEN_TYPES used TokenType.DIVIDE/MULTIPLY (the DIVIDE/
    MULTIPLY *statement* keywords) instead of TokenType.DIVIDE_OP/
    MULTIPLY_OP (what '/' and '*' actually lex to), so picture pattern
    collection stopped at the first edit symbol and the remainder was
    misparsed as phantom level-99 data items.
    """

    def test_slash_edited_picture_pattern_is_not_truncated(self):
        result = parse_cobol(_data_program("    05 WS-FIELD PIC 99/99/99."))
        assert result.errors == []
        items = result.ast.find_all_by_type("CobolDataItem")
        names = [i.name for i in items]
        assert "WS-FIELD" in names
        assert not any(n.startswith("ANONYMOUS-99") for n in names), names
        field = next(i for i in items if i.name == "WS-FIELD")
        assert field.picture_clause.pattern == "99/99/99"
        assert not any("Unparsed token" in w for w in result.warnings), result.warnings

    def test_check_protect_asterisk_picture_pattern_is_not_truncated(self):
        result = parse_cobol(_data_program("    01 WS-AMT PIC $***,**9.99."))
        assert result.errors == []
        items = result.ast.find_all_by_type("CobolDataItem")
        field = next(i for i in items if i.name == "WS-AMT")
        assert field.picture_clause.pattern == "$***,**9.99"
        assert not any("Unparsed token" in w for w in result.warnings), result.warnings


class TestM14CacheHitBytesAccounting:
    """M14 -- copybook cache hits bypassed total_bytes accounting.

    context.total_bytes was only incremented on a cache miss; a copybook
    served from the intra-expansion cache (diamond dependency: the same
    member COPYd multiple times) contributed zero bytes to the running
    total, so max_total_size was never enforced against the true expanded
    content size.
    """

    def test_repeated_copy_of_same_member_counts_every_inclusion(self, tmp_path):
        from cobolparser.preprocess import (
            TotalExpansionSizeExceededError,
            expand_copybooks,
        )

        copybook_dir = tmp_path / "copybooks"
        copybook_dir.mkdir()
        payload = "01 WS-FIELD-" + "X" * 60 + " PIC X.\n"
        content_size = len(payload.encode("utf-8"))
        (copybook_dir / "MEMBER.cpy").write_text(payload)

        source = (
            "IDENTIFICATION DIVISION.\n"
            "PROGRAM-ID. REGTEST.\n"
            "DATA DIVISION.\n"
            "WORKING-STORAGE SECTION.\n"
            "       COPY MEMBER.\n"
            "       COPY MEMBER.\n"
            "       COPY MEMBER.\n"
        )
        # Limit set strictly between 1x and 3x the single-copybook size:
        # under the M14 bug, only the first (cache-miss) inclusion counted,
        # so 3 inclusions never tripped a limit sized for ~1.5 copies.
        limit = int(content_size * 1.5)

        raised = False
        try:
            expand_copybooks(
                source,
                copybook_paths=[str(copybook_dir)],
                max_total_size=limit,
            )
        except TotalExpansionSizeExceededError:
            raised = True
        assert raised, (
            "3x inclusion of a copybook whose combined size exceeds "
            "max_total_size must raise, even when later inclusions are "
            "served from the intra-expansion cache"
        )


class TestM9NestedStatementSwallowedException:
    """M9 -- try_parse_nested_statement's bare except Exception had no
    trace at all (not even a warning) for exceptions that bypass
    report_or_raise, e.g. TokenMismatch/UnexpectedEndOfInput raised
    directly by token_stream.expect().
    """

    def test_unrecorded_exception_surfaces_as_warning(self, monkeypatch):
        from cobolparser.parsers.statements import _utils

        class _FakeRegistry:
            def find_parser(self, stream):
                return self

            def parse(self, stream):
                raise ValueError("boom -- not routed through report_or_raise")

        class _FakeStream:
            _registry = _FakeRegistry()
            context = None

        collected_warnings = []

        class _FakeHost:
            def add_warning(self, message):
                collected_warnings.append(message)

        class _FakeContext:
            host = _FakeHost()

        monkeypatch.setattr(_utils, "get_parse_context", lambda stream: _FakeContext())

        result = _utils.try_parse_nested_statement(_FakeStream())

        assert result is None
        assert len(collected_warnings) == 1
        assert "boom" in collected_warnings[0]

    def test_already_recorded_exception_does_not_double_warn(self, monkeypatch):
        from cobolparser.parsers.statements import _utils

        class _AlreadyRecordedError(Exception):
            _already_recorded = True

        class _FakeRegistry:
            def find_parser(self, stream):
                return self

            def parse(self, stream):
                raise _AlreadyRecordedError("already handled by report_or_raise")

        class _FakeStream:
            _registry = _FakeRegistry()
            context = None

        collected_warnings = []

        class _FakeHost:
            def add_warning(self, message):
                collected_warnings.append(message)

        class _FakeContext:
            host = _FakeHost()

        monkeypatch.setattr(_utils, "get_parse_context", lambda stream: _FakeContext())

        result = _utils.try_parse_nested_statement(_FakeStream())

        assert result is None
        assert collected_warnings == []


class TestM7TypedLiteralHexValidation:
    """M7 -- typed X'..'/NX'..' literals had no hex-validity or
    even-length check; malformed hex was accepted with no diagnostic.
    """

    def test_odd_length_hex_literal_warns(self):
        result = parse_cobol(_proc_program("    MOVE X'ABC' TO WS-X.\n"))
        assert any(
            "odd" in w.lower() or "hex" in w.lower() for w in result.warnings
        ), result.warnings

    def test_invalid_hex_digit_warns(self):
        result = parse_cobol(_proc_program("    MOVE X'ZZ' TO WS-X.\n"))
        assert any("hex" in w.lower() for w in result.warnings), result.warnings

    def test_valid_hex_literal_does_not_warn(self):
        result = parse_cobol(_proc_program("    MOVE X'1F2A' TO WS-X.\n"))
        assert not any("hex" in w.lower() for w in result.warnings), result.warnings


class TestM4DebugLineHandling:
    """M4 -- D/d in column 7 fell through as live code in
    normalize_fixed_format, disagreeing with copy_statement_parser's
    is_comment_line() (which already treats D/d as comment). Default
    behavior now matches is_comment_line(); a debug_lines_as_comments=False
    override is available for callers that need D-lines compiled as code.
    """

    def _line(self, indicator: str, text: str) -> str:
        # cols 1-6 seq area, col 7 indicator, cols 8+ text
        return " " * 6 + indicator + text

    def test_d_line_is_dropped_by_default(self):
        lines = [
            self._line(" ", "       DISPLAY 'BEFORE'."),
            self._line("D", "       DISPLAY 'DEBUG-ONLY'."),
            self._line(" ", "       DISPLAY 'AFTER'."),
        ]
        out = normalize_fixed_format(lines)
        assert "DEBUG-ONLY" not in out
        assert "BEFORE" in out
        assert "AFTER" in out

    def test_d_line_kept_as_code_when_opted_in(self):
        lines = [
            self._line(" ", "       DISPLAY 'BEFORE'."),
            self._line("D", "       DISPLAY 'DEBUG-ONLY'."),
        ]
        out = normalize_fixed_format(lines, debug_lines_as_comments=False)
        assert "DEBUG-ONLY" in out


class TestM5ContinuedLiteralTrailingBlanks:
    """M5 -- trailing blanks that are part of a literal's value (per
    fixed-format continuation rules) were stripped from the opening line
    before we knew the literal would continue.
    """

    def _line(self, indicator: str, text: str) -> str:
        return " " * 6 + indicator + text

    def test_opening_line_trailing_blanks_preserved_when_continued(self):
        lines = [
            self._line(" ", '       VALUE "ABC   '),
            self._line("-", '           "DEF".'),
        ]
        out = normalize_fixed_format(lines)
        # The three written blanks, then the ones the record stops short of
        # column 72 by: all of them lie inside the literal.
        assert '"ABC' + " " * (72 - len(lines[0]) + 3) + 'DEF"' in out, out

    def test_trailing_blanks_still_stripped_when_not_continued(self):
        lines = [
            self._line(" ", "       DISPLAY 'X'          "),
        ]
        out = normalize_fixed_format(lines)
        first_line = out.splitlines()[0]
        assert first_line == "       DISPLAY 'X'"


class TestM8TabHandling:
    """M8 -- no tab-expansion logic in normalize_fixed_format; a leading
    tab shifted every subsequent column.
    """

    def test_leading_tab_does_not_shift_columns(self):
        # A literal tab at column 1 expands to exactly 8 spaces (the next
        # tab stop from position 0) before column-sensitive slicing, so it
        # must produce the same result as those 8 spaces written literally.
        untabbed = normalize_fixed_format([" " * 8 + "       DISPLAY 'OK'."])
        tabbed = normalize_fixed_format(["\t" + "       DISPLAY 'OK'."])
        assert tabbed == untabbed


class TestM1DisplayFigurativeConstants:
    """M1 -- DISPLAY SPACE / DISPLAY SPACES (and other figurative
    constants) were not accepted as display items.
    """

    def test_display_space_is_captured(self):
        result = parse_cobol(_proc_program("    DISPLAY SPACE.\n"))
        stmts = [s for s in _statements(result) if isinstance(s, DisplayStatement)]
        assert len(stmts) == 1
        assert stmts[0].display_items == ["SPACE"]
        assert not any("Unparsed tokens" in w for w in result.warnings), result.warnings

    def test_display_spaces_mixed_with_identifier(self):
        result = parse_cobol(_proc_program("    DISPLAY WS-X SPACES.\n"))
        stmts = [s for s in _statements(result) if isinstance(s, DisplayStatement)]
        assert stmts[0].display_items == ["WS-X", "SPACES"]


class TestM2DisplayWithNoAdvancing:
    """M2 -- DISPLAY ... WITH NO ADVANCING was silently dropped; the
    display item before WITH survived but the clause itself vanished.
    """

    def test_with_no_advancing_is_captured(self):
        result = parse_cobol(
            _proc_program('    DISPLAY "PROMPT: " WITH NO ADVANCING.\n')
        )
        stmts = [s for s in _statements(result) if isinstance(s, DisplayStatement)]
        assert len(stmts) == 1
        assert stmts[0].display_items == ['"PROMPT: "']
        assert stmts[0].with_no_advancing is True
        assert not any("Unparsed tokens" in w for w in result.warnings), result.warnings

    def test_bare_no_advancing_without_with_is_captured(self):
        result = parse_cobol(_proc_program('    DISPLAY "X" NO ADVANCING.\n'))
        stmts = [s for s in _statements(result) if isinstance(s, DisplayStatement)]
        assert stmts[0].with_no_advancing is True

    def test_display_without_the_clause_defaults_false(self):
        result = parse_cobol(_proc_program('    DISPLAY "X".\n'))
        stmts = [s for s in _statements(result) if isinstance(s, DisplayStatement)]
        assert stmts[0].with_no_advancing is False


class TestM3aDisplayAtPositioning:
    """M3a -- DISPLAY ... AT LINE/COLUMN (and the corpus-dominant bare
    combined-numeric AT nnnn form) were dropped entirely.
    """

    def test_combined_numeric_at_form_decodes_line_and_column(self):
        # AT 0330 -> line 3, column 30 (confirmed real-world form, e.g.
        # examples/cobol/shamrice/accept.cbl's `AT 0330`).
        result = parse_cobol(_proc_program('    DISPLAY "X" AT 0330.\n'))
        stmts = [s for s in _statements(result) if isinstance(s, DisplayStatement)]
        assert stmts[0].at_line == 3
        assert stmts[0].at_column == 30
        assert not any("Unparsed tokens" in w for w in result.warnings), result.warnings

    def test_at_line_column_keyword_form(self):
        result = parse_cobol(_proc_program('    DISPLAY "X" AT LINE 5 COLUMN 10.\n'))
        stmts = [s for s in _statements(result) if isinstance(s, DisplayStatement)]
        assert stmts[0].at_line == 5
        assert stmts[0].at_column == 10

    def test_at_line_only(self):
        result = parse_cobol(_proc_program('    DISPLAY "X" AT LINE 5.\n'))
        stmts = [s for s in _statements(result) if isinstance(s, DisplayStatement)]
        assert stmts[0].at_line == 5
        assert stmts[0].at_column is None

    def test_multiple_items_each_with_their_own_at_clause(self):
        # examples/cobol/shamrice/accept_from.cbl-style:
        # DISPLAY "a" AT 0201 ws-input AT 0214.
        # Only the LAST AT clause's position is retained on the single
        # DisplayStatement node (the AST models one position per
        # statement, matching IOAcceptStatement's existing shape).
        result = parse_cobol(_proc_program('    DISPLAY "a" AT 0201 WS-X AT 0214.\n'))
        stmts = [s for s in _statements(result) if isinstance(s, DisplayStatement)]
        assert stmts[0].display_items == ['"a"', "WS-X"]
        assert stmts[0].at_line == 2
        assert stmts[0].at_column == 14
        assert not any("Unparsed tokens" in w for w in result.warnings), result.warnings


class TestM3bAcceptExtendedClauses:
    """M3b -- ACCEPT's AT positioning and extended clauses (SECURE,
    NO-ECHO, TIMEOUT, AUTO-SKIP, UPPER) were dropped. Grammar shapes below
    are taken verbatim from examples/cobol/shamrice/accept.cbl and
    accept-secure.cbl, the corpus the original audit's hit-counts came
    from.
    """

    def test_combined_numeric_at_form(self):
        result = parse_cobol(_proc_program("    ACCEPT WS-X AT 0117.\n"))
        stmts = [
            s
            for s in _statements(result)
            if s.__class__.__name__ == "IOAcceptStatement"
        ]
        assert stmts[0].at_line == 1
        assert stmts[0].at_column == 17
        assert not any("Unparsed tokens" in w for w in result.warnings), result.warnings

    def test_secure_is_distinct_from_no_echo(self):
        result = parse_cobol(_proc_program("    ACCEPT WS-X SECURE AT 0117.\n"))
        stmts = [
            s
            for s in _statements(result)
            if s.__class__.__name__ == "IOAcceptStatement"
        ]
        assert stmts[0].secure is True
        assert stmts[0].with_no_echo is False

    def test_no_echo_hyphenated_token(self):
        result = parse_cobol(_proc_program("    ACCEPT WS-X NO-ECHO AT 0526.\n"))
        stmts = [
            s
            for s in _statements(result)
            if s.__class__.__name__ == "IOAcceptStatement"
        ]
        assert stmts[0].with_no_echo is True
        assert stmts[0].secure is False

    def test_timeout_with_numeric_value(self):
        result = parse_cobol(_proc_program("    ACCEPT WS-X TIMEOUT 3 AT 0132.\n"))
        stmts = [
            s
            for s in _statements(result)
            if s.__class__.__name__ == "IOAcceptStatement"
        ]
        assert stmts[0].timeout_value == 3
        assert stmts[0].at_line == 1
        assert stmts[0].at_column == 32

    def test_auto_skip(self):
        result = parse_cobol(_proc_program("    ACCEPT WS-X AUTO-SKIP AT 0330.\n"))
        stmts = [
            s
            for s in _statements(result)
            if s.__class__.__name__ == "IOAcceptStatement"
        ]
        assert stmts[0].auto_skip is True

    def test_upper(self):
        result = parse_cobol(_proc_program("    ACCEPT WS-X UPPER AT 0716.\n"))
        stmts = [
            s
            for s in _statements(result)
            if s.__class__.__name__ == "IOAcceptStatement"
        ]
        assert stmts[0].upper is True

    def test_combined_with_prefix_form(self):
        # examples/cobol/shamrice/mouse_example.cbl: `with auto-skip no-echo`
        result = parse_cobol(_proc_program("    ACCEPT WS-X WITH AUTO-SKIP NO-ECHO.\n"))
        stmts = [
            s
            for s in _statements(result)
            if s.__class__.__name__ == "IOAcceptStatement"
        ]
        assert stmts[0].auto_skip is True
        assert stmts[0].with_no_echo is True
        assert not any("Unparsed tokens" in w for w in result.warnings), result.warnings
