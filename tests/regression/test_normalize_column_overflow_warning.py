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
