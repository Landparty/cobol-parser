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
