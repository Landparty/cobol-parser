"""End-to-end regression coverage for the fixed-format column-72 overflow
diagnostic actually reaching ``ParseResult.warnings`` (2026-08-14).

``normalize_fixed_format``'s ``warnings=`` parameter (added 2026-08-03) was
never passed by any of the library's real entry points -- ``CobolParser.
parse()``, the module-level ``parse_cobol()`` convenience function, and
``tokenize_cobol()`` all called ``normalize_fixed_format(...)`` with no
``warnings`` argument, so the diagnostic channel existed but was completely
unreachable from a normal parse. On top of that, the existing mid-token
detection (columns 72 *and* 73 both non-blank) doesn't fire when the drop
lands on a word boundary -- see
``tests/regression/test_normalize_column_overflow_warning.py::
TestWordBoundaryOverflowWarns`` for that half of the fix.

Found via a data-item-layout test fixture: writing
``OCCURS 1 TO 10 TIMES DEPENDING ON WS-COUNT.`` on one line (rather than
wrapping the ``DEPENDING ON`` clause onto a continuation line) silently
dropped the entire ODO clause -- no parse error, no warning -- and the
parser happily produced a *fixed* ``OCCURS 10 TIMES`` item instead. Pins
that a real ``parse_cobol()``/``CobolParser.parse()`` call now surfaces
this in ``ParseResult.warnings`` instead of staying silent.
"""

from __future__ import annotations

from cobolparser import CobolParser, ErrorRecoveryMode, parse_cobol

_PROGRAM = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. ODOOVERFLOW.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-REC.
           05  WS-COUNT         PIC 9(3).
           05  WS-TABLE         PIC X(2) OCCURS 1 TO 10 TIMES DEPENDING ON WS-COUNT.
           05  WS-AFTER         PIC X(4).
       PROCEDURE DIVISION.
           STOP RUN.
"""


def _stamped_line(
    text: str, stamp: str, *, start_col: int = 8, flush: bool = False
) -> str:
    """A fixed-format line carrying *stamp* in the identification area from
    column 73. ``flush=True`` right-aligns *text* so it ends exactly on
    column 72, leaving no blank between it and the stamp."""
    body = " " * ((72 - len(text)) if flush else (start_col - 1)) + text
    assert len(body) <= 72, len(body)
    return body.ljust(72) + stamp


def _get_table_item(result):
    section = result.ast.get_division("DATA").get_section_by_name("WORKING-STORAGE")
    rec = section.data_items[0]
    return next(c for c in rec.children if c.name == "WS-TABLE")


class TestParseCobolSurfacesOverflowWarning:
    """Covers the module-level ``parse_cobol()`` entry point, whose own
    ``normalize_fixed_format`` call (parser.py's ``preprocess_fixed`` branch)
    runs before ``CobolParser.parse()`` is ever invoked."""

    def test_warns_on_overflowing_occurs_depending_on(self):
        result = parse_cobol(_PROGRAM, error_recovery=ErrorRecoveryMode.COLLECT_ALL)
        assert any(
            "content beyond column 72 was dropped" in w for w in result.warnings
        ), result.warnings

    def test_does_not_promote_to_a_hard_error(self):
        # The overflow is a warning, not a parse error -- FAIL_FAST must not
        # abort or lose the AST over it.
        result = parse_cobol(_PROGRAM, error_recovery=ErrorRecoveryMode.FAIL_FAST)
        assert result.ast is not None
        assert result.errors == []
        assert any("content beyond column 72 was dropped" in w for w in result.warnings)

    def test_ast_still_reflects_the_silently_truncated_source(self):
        # The fix surfaces a diagnostic; it does not change what the
        # compiler-equivalent behavior actually parses. The ODO clause is
        # still dropped from the AST -- that's the whole point of the
        # warning existing.
        result = parse_cobol(_PROGRAM, error_recovery=ErrorRecoveryMode.COLLECT_ALL)
        table = _get_table_item(result)
        assert table.occurs_clause.depending_on is None


class TestCobolParserParseSurfacesOverflowWarning:
    """Covers ``CobolParser.parse()``'s own fixed-format auto-detection path
    (``_parse_core``), used when a caller constructs ``CobolParser`` directly
    without going through the ``parse_cobol()`` convenience wrapper."""

    def test_warns_on_overflowing_occurs_depending_on(self):
        parser = CobolParser(error_recovery=ErrorRecoveryMode.COLLECT_ALL)
        result = parser.parse(_PROGRAM)
        assert any(
            "content beyond column 72 was dropped" in w for w in result.warnings
        ), result.warnings

    def test_no_false_positive_on_clean_source(self):
        parser = CobolParser(error_recovery=ErrorRecoveryMode.COLLECT_ALL)
        clean = (
            "       IDENTIFICATION DIVISION.\n"
            "       PROGRAM-ID. CLEAN.\n"
            "       PROCEDURE DIVISION.\n"
            "           STOP RUN.\n"
        )
        result = parser.parse(clean)
        assert result.warnings == []


class TestInitialWarningsConsumedOnce:
    """``CobolParser(initial_warnings=...)`` carries ``parse_cobol()``'s own
    pre-construction normalization warnings across the ``self.warnings.
    clear()`` at the top of ``parse()`` (see ``CobolParser.__init__``). It
    must not keep re-appending them on every subsequent ``parse()`` call if
    a caller reuses the same ``CobolParser`` instance for a second,
    unrelated source -- those warnings describe the *first* source only."""

    _CLEAN = (
        "       IDENTIFICATION DIVISION.\n"
        "       PROGRAM-ID. CLEAN.\n"
        "       PROCEDURE DIVISION.\n"
        "           STOP RUN.\n"
    )

    def test_initial_warnings_apply_only_to_the_first_parse_call(self):
        parser = CobolParser(
            error_recovery=ErrorRecoveryMode.COLLECT_ALL,
            initial_warnings=["Line 1: content beyond column 72 was dropped: 'X'"],
        )

        first = parser.parse(self._CLEAN)
        assert first.warnings == ["Line 1: content beyond column 72 was dropped: 'X'"]

        second = parser.parse(self._CLEAN)
        assert second.warnings == []


class TestShortChangeStampDeckParsesWarningFree:
    """A whole program stamped with a short (5-digit) change-tracking code in
    columns 73-77, columns 1-6 blank -- the 2026-09-21 report. Every line
    whose statement ended exactly on column 72 used to warn ``dropped
    mid-token`` even though column 73 was never anything but the stamp, and
    a single warning is enough for a downstream consumer to refuse the
    program outright (mockymock refuses fail-closed on any
    ``ParseResult.warnings`` entry). Pins the end-to-end outcome: no
    warnings, and the AST still holds what the source really said."""

    _PROGRAM = "\n".join(
        [
            _stamped_line("IDENTIFICATION DIVISION.", "00100"),
            _stamped_line("PROGRAM-ID. HY11301.", "00110"),
            _stamped_line("DATA DIVISION.", "00120"),
            _stamped_line("WORKING-STORAGE SECTION.", "00130"),
            _stamped_line("01  WS-FORM-DATE-MM-X       PIC X(2).", "00540"),
            _stamped_line(
                "10  WS-FORM-DATE-MM REDEFINES WS-FORM-DATE-MM-X PIC 9(2).",
                "00551",
                flush=True,
            ),
            _stamped_line("01  COM-HY11301-ECHEANCE-REELLE PIC 9(8).", "01600"),
            _stamped_line("PROCEDURE DIVISION.", "01700"),
            _stamped_line("MAIN-PARA.", "01800"),
            _stamped_line(
                "MOVE ZEROES TO COM-HY11301-ECHEANCE-REELLE", "01641", flush=True
            ),
            _stamped_line("STOP RUN.", "01900", start_col=12),
        ]
    )

    def test_parses_without_warnings_or_errors(self):
        result = parse_cobol(self._PROGRAM, error_recovery=ErrorRecoveryMode.FAIL_FAST)
        assert result.warnings == [], result.warnings
        assert result.errors == [], result.errors
        assert result.success

    def test_stamp_is_not_mistaken_for_code(self):
        result = parse_cobol(self._PROGRAM, error_recovery=ErrorRecoveryMode.FAIL_FAST)
        moves = result.ast.find_all_by_type("MoveStatement")
        assert len(moves) == 1
        # The receiving field ends exactly on column 72; the stamp that
        # abuts it at column 73 is identification-area text, not part of it.
        assert "01641" not in result.ast.to_json()


class TestSubfieldedChangeStampDeckParsesWarningFree:
    """The same deck, but with the identification field laid out in
    sub-fields -- a 5-digit change id, two blanks, a 1-digit level, filling
    columns 73-80 exactly. Three of the reported program's nineteen lines
    carried this shape and kept warning after the first fix, because the
    stamp test was a plain ``str.isdigit()`` and the embedded blanks failed
    it."""

    _PROGRAM = "\n".join(
        [
            _stamped_line("IDENTIFICATION DIVISION.", "01600  0"),
            _stamped_line("PROGRAM-ID. HY11301.", "01610  0"),
            _stamped_line("DATA DIVISION.", "01620  0"),
            _stamped_line("WORKING-STORAGE SECTION.", "01630  0"),
            _stamped_line("01  COM-HY11301-ECHEANCE-REELLE PIC 9(8).", "01634  0"),
            _stamped_line("PROCEDURE DIVISION.", "01635  0"),
            _stamped_line("MAIN-PARA.", "01636  0"),
            _stamped_line(
                "MOVE ZEROES TO COM-HY11301-ECHEANCE-REELLE", "01641  0", flush=True
            ),
            _stamped_line("STOP RUN.", "02124  0", start_col=12),
        ]
    )

    def test_parses_without_warnings_or_errors(self):
        # Every line is exactly 80 columns wide, stamp included.
        assert {len(line) for line in self._PROGRAM.splitlines()} == {80}
        result = parse_cobol(self._PROGRAM, error_recovery=ErrorRecoveryMode.FAIL_FAST)
        assert result.warnings == [], result.warnings
        assert result.errors == [], result.errors
        assert result.success

    def test_stamp_is_not_mistaken_for_code(self):
        result = parse_cobol(self._PROGRAM, error_recovery=ErrorRecoveryMode.FAIL_FAST)
        assert len(result.ast.find_all_by_type("MoveStatement")) == 1
        assert "01641" not in result.ast.to_json()
