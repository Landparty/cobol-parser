"""Regression coverage for normalize_fixed_format's column-73+ overflow
warning (added 2026-08-03).

Found during a whole-branch review of mocky-mock's ``mockymock export``
command: a hand-written 77-character source line (a ``DISPLAY "X"
WS-FIELD.`` statement indented 56 columns) was silently chopped to 72
columns -- ``line[TEXT_START_COL - 1 : TEXT_END_COL]`` never bounds-checks
the line length -- producing ``DISPLAY "X" WS-F`` (no closing quote, no
period) with no warning, no error, and no indication to the caller that
truncation occurred. mockymock still wrote the corrupted line to its
"durable deliverable" output and exited 0.

Columns 73-80 are the identification area; real fixed-format compilers
ignore them regardless of content, and traditional 80-column source
legitimately puts non-blank sequence/identification text there (e.g. NIST
CCVS85's ``IC1014.2``, repeated on every line of
``examples/nist-cobol85/*.CBL``). Flagging every such line would be noise,
not signal, and would break parsing of real, currently-working COBOL. The
fix instead flags only a line whose columns 72 and 73 are *both*
non-blank -- content actually split mid-token, not merely followed by an
unrelated identification field -- confirmed against a real corruption case
in ``legacy-application/cobol/ACCTMNT.cbl`` (splits the identifier
``WS-PARM-DORM-DAYS`` into ``WS-PARM-DORM-D`` + dropped ``AYS``) and
against the NIST corpus (must NOT fire there).

Also pins that the Cython ``_preprocess_fast`` accelerated path stays
behaviorally identical to the pure-Python fallback for both the returned
text *and* the new `warnings` channel -- a divergence here means the
compiled build silently reports different diagnostics than the
non-accelerated build.

**Word-boundary overflow (2026-08-14):** the mid-token check above requires
columns 72 *and* 73 to both be non-blank, so it never fires when the
overflow happens to break right after a word -- e.g. ``OCCURS 1 TO 10
TIMES DEPENDING ON WS-COUNT.`` written on one line keeps ``DEPENDING``
(it fits by column 72) but silently drops its `` ON WS-COUNT.`` operand
(column 72 is a space, column 73 is "O"), producing a silently *fixed*
``OCCURS 10 TIMES`` with no ODO clause and no diagnostic at all -- the
mid-token rule treats it exactly like the traditional 80-column
identification-area case, which it isn't.
Distinguishing signal: a real 80-column punch-card line can never exceed
80 columns by construction (72 code + 8 identification), so any non-comment
line whose real content -- after trailing-whitespace is stripped -- extends
past column 80 cannot be legitimate identification-area text, regardless of
whether the column-72/73 boundary itself falls on a word break. See
``TestWordBoundaryOverflowWarns`` below.

**Sequence-numbered decks gate the whole check (2026-08-14):** wiring this
warning into the real parse pipeline for the first time (previously
``warnings=None`` everywhere -- see
``tests/regression/test_fixed_format_word_boundary_overflow.py``) surfaced
that the *original* mid-token rule above is far noisier on real 80-column
source than its own tests suggested: measured against the vendored NIST
CCVS85 corpus, 4434 of 4438 raw column-72/73 "mid-token" hits turned out to
be lines like ``examples/cobol/IX209A.CBL:292`` --
``029100          "...".IX2094.2`` -- where the statement's own closing
period genuinely lands on column 72 and the file's own per-line
identification code starts immediately at column 73 with zero authoring
mistake; nothing was actually split. The `` "020100 ..." IC1014.2`` example
this file's docstring already cited happens to leave a padding blank before
its identification field, but that's not true fixed-format COBOL in
general -- plenty of real 80-column decks don't bother with the padding,
relying only on the compiler's blanket columns-73-80 ignore rule. A numeric
sequence number in columns 1-6 is independent, reliable evidence that a
line belongs to exactly that convention (hand-typed modern source never
bothers with sequence numbers), so both the mid-token and word-boundary
rules above now skip entirely whenever columns 1-6 hold one. See
``test_numeric_sequence_area_does_not_warn_even_when_mid_token`` and
``test_blank_sequence_area_with_same_shape_still_warns`` below, which
isolate the sequence number as the deciding factor rather than the
period-then-letter shape itself.

**Bare terminal period does not warn (2026-08-24):** a corpus sweep found a
banner-style ``VALUE`` literal (e.g. ``VALUE '**** REPORT TITLE ****'.``)
whose closing quote lands exactly on column 72, immediately followed by the
statement-terminating period at column 73 with no separating blank --
satisfying the mid-token shape (both columns non-blank) even though nothing
was split: the string closed cleanly, and the dropped tail is *only* the
period, a single-character token the parser already tolerates missing
entirely. See ``TestBareTerminalPeriodDoesNotWarn`` below.
"""

from cobolparser.preprocess import _normalize_fixed_format_pure, normalize_fixed_format

IMPLS = [
    ("fast", normalize_fixed_format),
    ("pure", _normalize_fixed_format_pure),
]


class TestMidTokenOverflowWarns:
    # The reviewer's exact repro: 56 columns of indentation + a DISPLAY
    # statement that runs to column 77.
    REPRO_LINE = " " * 56 + 'DISPLAY "X" WS-FIELD.'
    # Columns 1-7 (sequence area + indicator) are always stripped, so the
    # 56 columns of source indentation become 49 leading spaces in the
    # normalized text area before the truncated statement.
    REPRO_EXPECTED_OUTPUT = " " * 49 + 'DISPLAY "X" WS-F\n'

    def test_reviewer_repro_warns_with_line_number_and_dropped_text(self):
        for name, impl in IMPLS:
            warnings: list[str] = []
            out = impl([self.REPRO_LINE], warnings=warnings)
            assert out == self.REPRO_EXPECTED_OUTPUT, name
            assert warnings == [
                "Line 1: content beyond column 72 was dropped mid-token: 'IELD.'"
            ], name

    def test_continuation_line_mid_token_overflow_warns(self):
        # Column 7 '-' (continuation indicator); text runs unbroken through
        # column 73 with no separating blank.
        line = "      -" + "X" * 66
        for name, impl in IMPLS:
            warnings: list[str] = []
            impl([line], warnings=warnings)
            assert warnings == [
                "Line 1: content beyond column 72 was dropped mid-token: 'X'"
            ], name

    def test_line_number_tracks_physical_position(self):
        lines = [
            "       DISPLAY 'FIRST'.\n",
            "       DISPLAY 'SECOND'.\n",
            self.REPRO_LINE,
        ]
        for name, impl in IMPLS:
            warnings: list[str] = []
            impl(lines, warnings=warnings)
            assert warnings == [
                "Line 3: content beyond column 72 was dropped mid-token: 'IELD.'"
            ], name


class TestNonMidTokenOverflowDoesNotWarn:
    def test_traditional_identification_area_does_not_warn(self):
        # Classic 80-column punch-card convention: real code ends with a
        # blank gap before the identification field starts at column 73 --
        # exactly the shape every line of examples/nist-cobol85/*.CBL uses.
        code = "000100 IDENTIFICATION DIVISION."
        line = code + " " * (72 - len(code)) + "IC1014.2"
        assert len(line) == 80
        for name, impl in IMPLS:
            warnings: list[str] = []
            out = impl([line], warnings=warnings)
            assert out == "IDENTIFICATION DIVISION.\n", name
            assert warnings == [], name

    def test_comment_line_overflow_does_not_warn(self):
        # Column 7 '*': the entire line is discarded regardless of the
        # column-72 boundary, so truncating it changes nothing.
        line = "      *" + "Y" * 66
        for name, impl in IMPLS:
            warnings: list[str] = []
            out = impl([line], warnings=warnings)
            assert out == "\n", name
            assert warnings == [], name

    def test_debug_line_as_comment_by_default_does_not_warn(self):
        line = "      D" + "Z" * 66
        for name, impl in IMPLS:
            warnings: list[str] = []
            impl([line], warnings=warnings)  # debug_lines_as_comments=True (default)
            assert warnings == [], name

    def test_debug_line_as_code_when_flag_disabled_warns(self):
        # debug_lines_as_comments=False flips a 'D'-indicator line from
        # comment to live code -- the overflow check must follow that same
        # comment/code determination, not a hardcoded indicator check.
        line = "      D" + "Z" * 66
        for name, impl in IMPLS:
            warnings: list[str] = []
            impl([line], warnings=warnings, debug_lines_as_comments=False)
            assert warnings == [
                "Line 1: content beyond column 72 was dropped mid-token: 'Z'"
            ], name

    def test_exactly_72_columns_does_not_warn(self):
        line = " " * 65 + "A" * 7  # 72 chars, nothing beyond the boundary
        assert len(line) == 72
        for name, impl in IMPLS:
            warnings: list[str] = []
            impl([line], warnings=warnings)
            assert warnings == [], name

    def test_numeric_sequence_area_does_not_warn_even_when_mid_token(self):
        # A real per-line sequence number in columns 1-6 is deck-format
        # evidence this file deliberately uses the full 80-column
        # convention, where the identification field may abut column 72
        # with no separating blank -- even when the resulting column-72/73
        # pair happens to both be non-blank. Reconstructs the exact shape
        # found in the vendored NIST CCVS85 corpus (examples/cobol/
        # IX209A.CBL:292): a statement whose closing period lands exactly
        # on column 72, immediately followed (no gap) by the file's own
        # per-line test-case id "IX2094.2" in the identification area.
        # Before this gate, this shape alone accounted for 4434 of 4438
        # "mid-token" false positives across the vendored example corpus.
        code = (
            '029100          "BBBBBBBBBC002EEEEEEEEEF002ALTKEY1WWWWWWWWWV398ALTKEY2".'
        )
        line = code + "IX2094.2"
        assert len(code) == 72
        assert line[71] == "."  # column 72: the statement's own period
        assert line[72] == "I"  # column 73: unrelated identification text
        for name, impl in IMPLS:
            warnings: list[str] = []
            impl([line], warnings=warnings)
            assert warnings == [], name

    def test_blank_sequence_area_with_same_shape_still_warns(self):
        # Same column-72/73 shape as the sequence-numbered case above, but
        # with a blank (not numeric) sequence area -- modern hand-typed
        # source, where this shape is a genuine authoring mistake and must
        # still be flagged. Isolates the sequence-number gate as the
        # deciding factor, not the period-then-letter shape itself.
        code = " " * 65 + "A" * 6 + "."
        line = code + "IX2094.2"
        assert len(code) == 72
        assert line[:6].strip() == ""
        for name, impl in IMPLS:
            warnings: list[str] = []
            impl([line], warnings=warnings)
            assert len(warnings) == 1, name
            assert "IX2094.2" in warnings[0], name

    def test_numeric_identification_stamp_does_not_warn_with_blank_seq_area(self):
        # Real-world shape found in a vendored mainframe program: columns 1-6
        # are blank (this file does not use the traditional cols-1-6
        # sequence-number convention the gate above recognizes), but every
        # line carries an 8-digit, purely-numeric change/sequence stamp in
        # columns 73-80 (e.g. IBM Z Open Editor/ISPF-style auto numbering:
        # 03040000, 03050009, 03060000, ... incrementing per line). A
        # VALUE clause's closing quote and statement-terminating period land
        # exactly on column 72, immediately followed by that stamp with no
        # separating blank -- satisfying the mid-token shape by column
        # position alone, but the dropped tail is unambiguously an
        # identification-area stamp, not split code.
        prefix = "10  WS000-D0000022-X   PIC X(008)   VALUE"
        suffix = "'D0000022'."
        pad = 65 - len(prefix) - len(suffix)
        text = prefix + " " * pad + suffix  # cols 8-72
        line = " " * 7 + text + "03050009"  # cols 1-7 blank, then cols 73-80
        assert len(text) == 65
        assert len(line) == 80
        assert line[:6].strip() == ""  # no sequence number in columns 1-6
        assert line[71] == "."  # column 72: the VALUE clause's own period
        assert line[72] == "0"  # column 73: first digit of the stamp
        for name, impl in IMPLS:
            warnings: list[str] = []
            out = impl([line], warnings=warnings)
            assert warnings == [], name
            assert out == text + "\n", name

    def test_numeric_identification_stamp_still_warns_past_traditional_width(self):
        # The numeric-tail gate only excuses drops that still fit within the
        # traditional 80-column width (columns 73-80). A longer purely-
        # numeric tail spilling past column 80 is no longer plausible
        # identification-area content and must still warn (via the
        # word-boundary/exceeds-traditional-width rule).
        prefix = "10  WS000-D0000022-X   PIC X(008)   VALUE"
        suffix = "'D0000022'."
        pad = 65 - len(prefix) - len(suffix)
        text = prefix + " " * pad + suffix  # cols 8-72
        line = " " * 7 + text + "030500091"  # 9 digits: one past the 8-col ID area
        assert len(text) == 65
        assert len(line) == 81
        for name, impl in IMPLS:
            warnings: list[str] = []
            impl([line], warnings=warnings)
            assert len(warnings) == 1, name
            assert "030500091" in warnings[0], name


class TestBareTerminalPeriodDoesNotWarn:
    """A dropped tail that is only the statement-terminating period must not
    warn -- the token before it (almost always a string literal's closing
    quote) closed cleanly on column 72, so nothing was actually split."""

    def test_value_clause_quote_at_column_72_then_period_does_not_warn(self):
        prefix = "01  WS-BANNER PIC X(40) VALUE "
        # Pad so the closing quote lands exactly on column 72 (1-based).
        content_len = 72 - (7 + len(prefix) + 1) - 1
        line = " " * 7 + prefix + "'" + "*" * content_len + "'" + "."
        assert len(line) == 73
        assert line[71] == "'"  # column 72: the literal's own closing quote
        assert line[72] == "."  # column 73: the statement period, dropped
        for name, impl in IMPLS:
            warnings: list[str] = []
            out = impl([line], warnings=warnings)
            assert warnings == [], name
            assert out.rstrip("\n").endswith("'"), name

    def test_dropped_period_plus_more_content_still_warns(self):
        # Guard against over-correcting: a dropped tail that happens to
        # START with a period but carries more than just that one character
        # is a genuine mid-token split and must still warn.
        line = " " * 65 + "A" * 7 + ".B"
        assert len(line) == 74
        assert line[71] == "A"  # column 72
        assert line[72:74] == ".B"  # dropped tail, columns 73-74
        for name, impl in IMPLS:
            warnings: list[str] = []
            impl([line], warnings=warnings)
            assert len(warnings) == 1, name
            assert ".B" in warnings[0], name


class TestWordBoundaryOverflowWarns:
    """Overflow that breaks exactly on a space at column 72/73 -- the
    mid-token rule alone misses these, but a line that survives past column
    80 (the traditional punch-card width) can never be legitimate
    identification-area content."""

    # Reconstructs the exact one-line form of the OCCURS ... DEPENDING ON
    # fixture from tests/unit/generators/data/test_layout_offsets.py before
    # it was manually wrapped onto a continuation line to work around this
    # bug. "DEPENDING" itself fits by column 72; column 73 is "O" of
    # "ON" -- a word boundary (column 72 is a space), not a mid-token split,
    # so it still drops the ODO clause's operand entirely.
    ODO_LINE = (
        "           05  WS-TABLE         PIC X(2) OCCURS 1 TO 10 TIMES "
        "DEPENDING ON WS-COUNT."
    )

    def test_occurs_depending_on_word_boundary_drop_warns(self):
        assert self.ODO_LINE[71] == " "  # column 72
        assert self.ODO_LINE[72] == "O"  # column 73 -- proves it's not mid-token
        for name, impl in IMPLS:
            warnings: list[str] = []
            out = impl([self.ODO_LINE], warnings=warnings)
            # "DEPENDING" survives (it fits by column 72); its operand doesn't.
            assert "DEPENDING" in out, name
            assert "ON WS-COUNT" not in out, name
            assert len(warnings) == 1, name
            assert "Line 1" in warnings[0], name
            assert "ON WS-COUNT." in warnings[0], name

    def test_exactly_80_columns_at_word_boundary_does_not_warn(self):
        # 71 code columns + 1 boundary space + 8 identification columns = 80,
        # the traditional maximum -- must NOT warn even though column 72 is
        # blank and column 73 starts real-looking text.
        line = "A" * 71 + " " + "B" * 8
        assert len(line) == 80
        for name, impl in IMPLS:
            warnings: list[str] = []
            impl([line], warnings=warnings)
            assert warnings == [], name

    def test_81_columns_at_word_boundary_warns(self):
        # One character past the traditional 80-column width, still landing
        # on a space at column 72/73 -- pins the exact boundary the fix adds.
        line = "A" * 71 + " " + "B" * 9
        assert len(line) == 81
        for name, impl in IMPLS:
            warnings: list[str] = []
            impl([line], warnings=warnings)
            assert warnings == [
                "Line 1: content beyond column 72 was dropped -- line is 81 "
                "columns wide, past the traditional 80-column "
                "identification-area width: 'BBBBBBBBB'"
            ], name


class TestBackwardCompatibility:
    def test_no_warnings_argument_behaves_as_before(self):
        """Omitting `warnings` entirely must not raise and must produce the
        same (silently truncated) output as before this change -- existing
        callers that don't opt in are unaffected."""
        for name, impl in IMPLS:
            out = impl([TestMidTokenOverflowWarns.REPRO_LINE])
            assert out == TestMidTokenOverflowWarns.REPRO_EXPECTED_OUTPUT, name


class TestFastAndPureParity:
    """Both implementations must agree on the *warnings* list, not just the
    returned text -- the parity guarantee is hollow for this new channel
    otherwise."""

    CASES = [
        TestMidTokenOverflowWarns.REPRO_LINE,
        "      -" + "X" * 66,
        "000100 IDENTIFICATION DIVISION." + " " * 39 + "IC1014.2",
        "      *" + "Y" * 66,
        "      D" + "Z" * 66,
        " " * 65 + "A" * 7,
        TestWordBoundaryOverflowWarns.ODO_LINE,
        "A" * 71 + " " + "B" * 8,
        "A" * 71 + " " + "B" * 9,
        '029100          "BBBBBBBBBC002EEEEEEEEEF002ALTKEY1WWWWWWWWWV398ALTKEY2".IX2094.2',
        " " * 65 + "A" * 6 + "." + "IX2094.2",
        (
            "       10  WS000-D0000022-X   PIC X(008)   VALUE             "
            "'D0000022'.03050009"
        ),
        (
            "       10  WS000-D0000022-X   PIC X(008)   VALUE             "
            "'D0000022'.030500091"
        ),
        " " * 7 + "01  WS-BANNER PIC X(40) VALUE " + "'" + "*" * 32 + "'" + ".",
        " " * 65 + "A" * 7 + ".B",
    ]

    def test_fast_and_pure_produce_identical_warnings(self):
        for line in self.CASES:
            fast_warnings: list[str] = []
            pure_warnings: list[str] = []
            fast_out = normalize_fixed_format([line], warnings=fast_warnings)
            pure_out = _normalize_fixed_format_pure([line], warnings=pure_warnings)
            assert fast_out == pure_out, line
            assert fast_warnings == pure_warnings, line

    def test_fast_and_pure_agree_with_debug_lines_as_comments_false(self):
        line = "      D" + "Z" * 66
        fast_warnings: list[str] = []
        pure_warnings: list[str] = []
        fast_out = normalize_fixed_format(
            [line], warnings=fast_warnings, debug_lines_as_comments=False
        )
        pure_out = _normalize_fixed_format_pure(
            [line], warnings=pure_warnings, debug_lines_as_comments=False
        )
        assert fast_out == pure_out
        assert fast_warnings == pure_warnings
