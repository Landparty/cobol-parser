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

**Short change-tracking stamps are a whole-file property (2026-09-21):** the
numeric-stamp gate above only excuses a tail that fills columns 73-80
*exactly*, because per line a shorter all-digit tail is indistinguishable
from a data name's own trailing digits getting cut. Reported against a real
mainframe program whose change-control tool (Panvalet/Librarian/Endevor
style) stamps a **5-digit** code at column 73 -- non-sequential
(``00551``, ``00257``, ``01641``), columns 1-6 blank -- so every line whose
statement happened to end exactly on column 72 warned
``content beyond column 72 was dropped mid-token``. Nothing was split:
column 73 was always the stamp. Those warnings are load-bearing downstream
(mockymock refuses fail-closed on any ``ParseResult.warnings`` entry), so
the whole program was rejected.

Per line the shape is genuinely ambiguous; across the file it is not. A file
that uses the convention also carries lines where the stamp is preceded by a
blank at column 72 -- there nothing *could* have been split, so the tail is
provably identification-area content. ``_has_identification_stamp_convention``
counts those, and ``MIN_ID_STAMP_EVIDENCE_LINES`` (3) of them let the
shorter all-digit tails be read the same way. See
``TestShortIdentificationStampConvention`` below.
"""

from cobolparser.preprocess import normalize_fixed_format
from cobolparser.preprocess._normalize import (
    MIN_ID_STAMP_EVIDENCE_LINES,
    _has_identification_stamp_convention,
    _is_numeric_id_stamp_text,
)

IMPLS = [("normalize", normalize_fixed_format)]


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


def _stamped(text: str, stamp: str, *, start_col: int = 8) -> str:
    """A fixed-format line holding *text* from *start_col*, blank-padded to
    column 72, with *stamp* in the identification area from column 73."""
    body = " " * (start_col - 1) + text
    assert len(body) <= 72, len(body)
    return body.ljust(72) + stamp


def _stamped_flush(text: str, stamp: str) -> str:
    """The ambiguous shape: *text* ends exactly on column 72, so *stamp*
    abuts it with no separating blank (columns 72 and 73 both non-blank)."""
    body = " " * (72 - len(text)) + text
    assert len(body) == 72, len(body)
    return body + stamp


class TestShortIdentificationStampConvention:
    """A shop change-tracking stamp shorter than the full 8-column
    identification field: excused when the *file* proves it uses one, still
    flagged when it doesn't."""

    # Three unambiguous stamped lines (column 72 blank, so nothing could
    # have been split) establish the convention for the file.
    EVIDENCE = [
        _stamped("IDENTIFICATION DIVISION.", "00100"),
        _stamped("PROGRAM-ID. HY11301.", "00110"),
        _stamped("DATA DIVISION.", "00120"),
    ]

    def test_reported_repro_does_not_warn(self):
        # The reported program's three shapes, each ending exactly on
        # column 72 with a 5-digit stamp at column 73: a PICTURE clause's
        # period, a VALUE literal's closing quote + period, and a MOVE's
        # receiving field name.
        lines = self.EVIDENCE + [
            _stamped_flush(
                "10  WS-FORM-DATE-MM REDEFINES WS-FORM-DATE-MM-X PIC 9(2).", "00551"
            ),
            _stamped_flush(
                "05  CST-ABEND-MSG-1BB PIC X(24) VALUE 'COMMUNIQUEZ AU SAC'.", "00257"
            ),
            _stamped_flush("MOVE ZEROES TO COM-HY11301-ECHEANCE-REELLE", "01641"),
        ]
        for name, impl in IMPLS:
            warnings: list[str] = []
            out = impl(lines, warnings=warnings)
            assert warnings == [], name
            # The truncation itself is unchanged -- only the diagnostic is.
            assert "PIC 9(2)." in out, name
            assert "COM-HY11301-ECHEANCE-REELLE" in out, name
            assert "00551" not in out, name

    def test_below_evidence_threshold_still_warns(self):
        # One fewer unambiguous stamped line than the threshold: a couple of
        # numbers dangling past column 72 is an authoring accident, not a
        # convention, so the mid-token rule stands.
        lines = self.EVIDENCE[: MIN_ID_STAMP_EVIDENCE_LINES - 1] + [
            _stamped_flush("MOVE ZEROES TO COM-HY11301-ECHEANCE-REELLE", "01641")
        ]
        for name, impl in IMPLS:
            warnings: list[str] = []
            impl(lines, warnings=warnings)
            assert len(warnings) == 1, name
            assert "01641" in warnings[0], name

    def test_non_numeric_tail_still_warns_in_a_stamped_file(self):
        # The gate is shaped on the file's own stamp: a dropped tail that is
        # not a stamp at all (the reviewer's WS-PARM-DORM-DAYS split) is a
        # real truncation and must still be flagged, stamped file or not.
        lines = self.EVIDENCE + [_stamped_flush("MOVE SPACES TO WS-PARM-DORM-D", "AYS")]
        for name, impl in IMPLS:
            warnings: list[str] = []
            impl(lines, warnings=warnings)
            assert len(warnings) == 1, name
            assert "'AYS'" in warnings[0], name

    def test_tail_past_column_80_still_warns_in_a_stamped_file(self):
        # A numeric tail that overruns the 8-column identification area is
        # not the file's stamp either: the line is 81 columns wide, past the
        # traditional punch-card maximum, so it still warns.
        lines = self.EVIDENCE + [_stamped_flush("MOVE 1 TO WS-A", "012345678")]
        assert len(lines[-1]) == 81
        for name, impl in IMPLS:
            warnings: list[str] = []
            impl(lines, warnings=warnings)
            assert len(warnings) == 1, name
            assert "'012345678'" in warnings[0], name

    def test_evidence_requires_a_blank_column_72(self):
        # Lines of the ambiguous shape can never vouch for themselves: a
        # file made only of them has no evidence at all and every line warns.
        lines = [
            _stamped_flush("MOVE ZEROES TO COM-HY11301-ECHEANCE-REELLE", "01641"),
            _stamped_flush("MOVE ZEROES TO COM-HY11301-ECHEANCE-REELLF", "01642"),
            _stamped_flush("MOVE ZEROES TO COM-HY11301-ECHEANCE-REELLG", "01643"),
            _stamped_flush("MOVE ZEROES TO COM-HY11301-ECHEANCE-REELLH", "01644"),
        ]
        for name, impl in IMPLS:
            warnings: list[str] = []
            impl(lines, warnings=warnings)
            assert len(warnings) == 4, name

    def test_helper_counts_only_unambiguous_stamped_lines(self):
        assert _has_identification_stamp_convention(self.EVIDENCE) is True
        assert _has_identification_stamp_convention(self.EVIDENCE[:-1]) is False
        # Non-numeric identification text (NIST's per-line test-case id) is
        # not the numeric-stamp convention this gate recognizes.
        assert (
            _has_identification_stamp_convention(
                [_stamped("DISPLAY 'X'.", "IX2094.2")] * 5
            )
            is False
        )
        # Content past column 80 is not identification-area text at all.
        assert (
            _has_identification_stamp_convention(
                [_stamped("DISPLAY 'X'.", "012345678")] * 5
            )
            is False
        )


class TestSubfieldedNumericStamp:
    """A stamp whose identification field is laid out in sub-fields, so the
    tail holds blanks *between* digits (``01636  0``). Reported as the
    residue of the 2026-09-21 fix: 16 of one program's 19 lines went quiet,
    and the three that didn't all carried this shape, where a plain
    ``str.isdigit()`` reads the shop's own stamp as split code."""

    # The three residual lines, verbatim in shape: 5-digit change id, two
    # blanks, a 1-digit level -- columns 73-80 exactly, so each is settled
    # by the full-width gate alone, with no file-level evidence needed.
    REPRO = [
        _stamped_flush("MOVE ZEROES TO COM-HY11301-ECHEANCE-REELLE", "01636  0"),
        _stamped_flush("MOVE AT-ALP-HIGH-UNPR-UNM TO HY1-COD-RENOUV-AUTO", "01641  0"),
        _stamped_flush("TS-COD-OPTION (TS-NB-PRET-MULTICHOIX).", "02124  0"),
    ]

    def test_each_reported_line_alone_does_not_warn(self):
        for line in self.REPRO:
            assert len(line) == 80
            assert line[71] != " "  # column 72: real code
            assert line[72] != " "  # column 73: first digit of the stamp
            for name, impl in IMPLS:
                warnings: list[str] = []
                impl([line], warnings=warnings)
                assert warnings == [], (name, line)

    def test_short_subfielded_stamp_needs_file_evidence(self):
        # Below the full 8-column width the whole-file gate decides, exactly
        # as it does for an unbroken short stamp.
        flush = _stamped_flush("MOVE ZEROES TO COM-HY11301-ECHEANCE-REEL", "016 36")
        evidence = TestShortIdentificationStampConvention.EVIDENCE
        for name, impl in IMPLS:
            with_evidence: list[str] = []
            impl([*evidence, flush], warnings=with_evidence)
            assert with_evidence == [], name

            without: list[str] = []
            impl([*evidence[:1], flush], warnings=without)
            assert len(without) == 1, name
            assert "016 36" in without[0], name

    def test_letters_among_the_digits_still_warn(self):
        # The shape admits blanks, not arbitrary separators: anything that
        # is neither a digit nor a blank is real dropped text.
        line = _stamped_flush("MOVE ZEROES TO COM-HY11301-ECHEANCE-REELLE", "01636-A0")
        assert len(line) == 80
        for name, impl in IMPLS:
            warnings: list[str] = []
            impl([line], warnings=warnings)
            assert len(warnings) == 1, name
            assert "01636-A0" in warnings[0], name

    def test_subfielded_digits_past_column_80_still_warn(self):
        line = _stamped_flush("MOVE 1 TO WS-A", "01636  00")
        assert len(line) == 81
        for name, impl in IMPLS:
            warnings: list[str] = []
            impl([line], warnings=warnings)
            assert len(warnings) == 1, name

    def test_helper_shape(self):
        assert _is_numeric_id_stamp_text("01636  0") is True
        assert _is_numeric_id_stamp_text("03050009") is True
        assert _is_numeric_id_stamp_text("016 36") is True
        # No digit at all is not a stamp, however blank it looks.
        assert _is_numeric_id_stamp_text("") is False
        assert _is_numeric_id_stamp_text("   ") is False
        # Letters and punctuation are dropped program text, not a stamp.
        assert _is_numeric_id_stamp_text("IX2094.2") is False
        assert _is_numeric_id_stamp_text("AYS") is False
        assert _is_numeric_id_stamp_text("01636-A0") is False


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
