"""Regression coverage for two ``expand_copybooks`` output defects found in
a real mainframe corpus retry.

**1. REPLACING column overflow.** A ``COPY ... REPLACING`` whose
replacement text is longer than what it replaces (``==:LKPCB:== BY
==LKPCB-PCB1==``, +3 characters per occurrence) lengthens the lines it
lands on; the expander's 6-space re-pad then leaves the tail -- typically
a data item's terminating period -- past column 72, where the final
parse's fixed-format slice silently drops it ("content beyond column 72
was dropped mid-token: '.'", 38x across the corpus). The raw copybook is
perfectly valid; only the re-assembled expansion output overflows. Fixed
by ``_fit_fixed_format_width``: interior multi-blank runs (outside quoted
literals) are squeezed, rightmost first, until the line fits -- keeping
the line count unchanged -- with a word-boundary wrap onto a fresh Area-B
line as fallback when squeezing alone cannot fit it.

**2. Change-tag lines in columns 1-6.** Shops stamp a short change tag
(``P2P``, ``M1005``, ``E1A``, ... -- any prefix, unlike the column-7
V-convention) into columns 1-6 of its own line, with nothing after it: the
physical line is under 7 characters long. ``strip_sequence_area`` passed
short lines through verbatim ("might be free-format"), so the tag survived
the strip; the 6-space re-pad then shifted its first letter into the
indicator column and the rest into columns 8+ as live code -- surfacing as
"Unparsed tokens" (or silently swallowed garbage) in the final parse.
Fixed in ``strip_sequence_area`` by blanking short *tag-shaped* lines --
a single blank-free token with no terminating period that is not a
compiler-directing word. Blanking every short line (the first version of
the fix) was too eager: flush-left copybooks without sequence numbers
carry short code lines like ``01 A.`` or ``EXIT.`` that the old
passthrough kept working, and blanking those silently deleted code.

**3. Flush-left PROCESS/CBL directive mangled.** A PROCESS/CBL
compiler-directing statement must start in column 1 per the COBOL
standard, even inside an otherwise strictly fixed-format program that
carries real sequence numbers on every other line. ``strip_sequence_area``
unconditionally strips columns 1-6 from every full-width line, so
``PROCESS &CICS-31& &HAUTE-PERFORM-DB2&`` was mangled into
``S &CICS-31& &HAUTE-PERFORM-DB2&`` before any later PROCESS-stripping
pass ever saw it intact -- surfacing downstream as a missing PROGRAM-ID
header. Fixed by exempting a line from the strip when its own columns 1-6
do not already look like a real sequence area (blank or all-digit) AND the
line is a PROCESS/CBL directive; ordinary numbered/tagged source is
unaffected.
"""

from cobolparser import parse_cobol
from cobolparser.preprocess import expand_copybooks
from cobolparser.preprocess.copy_statement_parser import strip_sequence_area
from cobolparser.preprocess.copybook_expander import _fit_fixed_format_width


def _pad72(text: str) -> str:
    return ("       " + text).ljust(72)[:72]


class TestReplacingColumnOverflow:
    def _expand(self, tmp_path, cpy_lines, src_lines):
        cpy = tmp_path / "PCBCO100.CPY"
        cpy.write_text("\n".join(cpy_lines) + "\n")
        src = "\n".join(src_lines) + "\n"
        return expand_copybooks(src, copybook_paths=[str(tmp_path)])

    def test_lengthening_replacing_keeps_period_within_column_72(self, tmp_path):
        # Copybook line built so its terminating period sits at column 70:
        # the +3 replacement would push it to column 73 without the fix.
        prefix = "05  :LKPCB:-PTR"
        suffix = "PIC S9(9) COMP-5."
        pad = 70 - (7 + len(prefix) + len(suffix))
        cpy_line = " " * 7 + prefix + " " * pad + suffix
        assert len(cpy_line) == 70 and cpy_line.endswith(".")

        result = self._expand(
            tmp_path,
            ["       01  :LKPCB:-AREA.", cpy_line],
            [
                _pad72("IDENTIFICATION DIVISION."),
                _pad72("PROGRAM-ID. REPLTEST."),
                _pad72("DATA DIVISION."),
                _pad72("WORKING-STORAGE SECTION."),
                _pad72("COPY PCBCO100 REPLACING ==:LKPCB:== BY ==LKPCB-PCB1==."),
                _pad72("PROCEDURE DIVISION."),
                _pad72("    DISPLAY LKPCB-PCB1-PTR."),
                _pad72("    STOP RUN."),
            ],
        )
        for line in result.expanded_source.splitlines():
            assert len(line.rstrip()) <= 72, repr(line)

        parse = parse_cobol(result.expanded_source, filename="repltest.cbl")
        assert parse.success, parse.errors
        assert parse.warnings == [], parse.warnings
        names = [i.name for i in parse.ast.find_all_by_type("CobolDataItem")]
        assert "LKPCB-PCB1-PTR" in names


class TestFitFixedFormatWidth:
    def test_short_line_unchanged(self):
        line = "      " + " 01  WS-A PIC X."
        assert _fit_fixed_format_width(line) == [line]

    def test_squeeze_compresses_rightmost_blank_run_first(self):
        # 7-char prefix + name + wide gap + PIC: a few chars over.
        content = "05  FIELD-NAME" + " " * 45 + "PIC X(10)."
        line = " " * 7 + content
        overflow = len(line) - 72
        assert overflow > 0
        out = _fit_fixed_format_width(line)
        assert len(out) == 1
        assert len(out[0]) == 72
        # Same tokens, only separator width changed.
        assert out[0].split() == line.split()

    def test_blanks_inside_literals_never_squeezed(self):
        literal = "'A    B'"  # interior blanks are literal content
        content = "05  F PIC X(8) VALUE " + literal + "." + " " * 30
        line = (" " * 7 + content).rstrip() + " " * 30 + "X" * 10
        out = _fit_fixed_format_width(line)
        joined = "\n".join(out)
        assert literal in joined

    def test_wrap_fallback_moves_whole_words_to_area_b_line(self):
        # No multi-blank run to squeeze: single blanks everywhere.
        words = ["W" + str(i) for i in range(20)]
        line = " " * 7 + " ".join(words)
        assert len(line) > 72
        out = _fit_fixed_format_width(line)
        assert len(out) > 1
        for piece in out:
            assert len(piece.rstrip()) <= 72
        # Continuation lines start in Area B (column 12 = index 11).
        for cont in out[1:]:
            assert cont.startswith(" " * 11)
            assert cont[11] != " "
        # Token stream preserved exactly.
        assert " ".join(" ".join(out).split()) == " ".join(words)

    def test_unbreakable_line_left_untouched(self):
        line = " " * 7 + "X" * 80  # one giant token: no safe break point
        assert _fit_fixed_format_width(line) == [line]

    def test_short_head_before_unbreakable_tail_terminates(self):
        # The first fix shipped an infinite loop here: a small head followed
        # by an unbreakable 62+-char token. The wrapped tail's fresh
        # 11-space prefix re-created a "safe blank" inside the pad every
        # iteration, emitting an empty head forever. Must terminate, and
        # every emitted piece must carry real content.
        line = " " * 7 + "A " + "X" * 80
        out = _fit_fixed_format_width(line)
        assert all(piece.strip() for piece in out)
        assert "".join(out).count("X") == 80


class TestSequenceAreaChangeTags:
    def test_short_tag_only_lines_blanked_by_strip(self):
        src = "P2P\n       01  WS-A PIC X.\nM1005"
        out = strip_sequence_area(src).split("\n")
        assert out[0] == ""
        assert out[2] == ""
        assert "01  WS-A PIC X." in out[1]

    def test_tags_do_not_leak_into_expanded_output(self, tmp_path):
        (tmp_path / "MYFLD.CPY").write_text("       01  WS-FIELD PIC X(5).\n")
        src = (
            "\n".join(
                [
                    _pad72("IDENTIFICATION DIVISION."),
                    _pad72("PROGRAM-ID. TAGTEST."),
                    _pad72("DATA DIVISION."),
                    _pad72("WORKING-STORAGE SECTION."),
                    "P2P",  # tag-only line: cols 1-3, nothing else
                    _pad72("COPY MYFLD."),
                    "M1005",  # tag-only line: cols 1-5
                    _pad72("PROCEDURE DIVISION."),
                    _pad72("    DISPLAY WS-FIELD."),
                    _pad72("    STOP RUN."),
                ]
            )
            + "\n"
        )
        result = expand_copybooks(src, copybook_paths=[str(tmp_path)])
        assert "P2P" not in result.expanded_source
        assert "M1005" not in result.expanded_source

        parse = parse_cobol(result.expanded_source, filename="tagtest.cbl")
        assert parse.success, parse.errors
        assert parse.warnings == [], parse.warnings

    def test_line_count_preserved_for_tag_lines(self, tmp_path):
        # The blanked tag line must stay a line so later locations hold.
        src = "P2P\n       01  WS-A PIC X."
        assert strip_sequence_area(src).count("\n") == src.count("\n")


class TestReviewPassRefinements:
    """Refinements from a `/code-review` pass on the initial fixes."""

    def test_wrap_break_allowed_at_exactly_column_72(self):
        # head = stripped[:break_at] has length break_at, so break_at == 72
        # yields a 72-char head -- fully inside the code area. The old
        # <= 71 cap left a token ending exactly at column 72 unsplittable,
        # silently dropping its tail past the slice.
        line = " " * 7 + "X" * 65 + " Y."
        assert len(line.rstrip()) == 75
        out = _fit_fixed_format_width(line)
        assert len(out) == 2
        assert len(out[0].rstrip()) == 72
        assert "Y." in out[1]

    def test_total_lines_matches_output_after_wrap(self, tmp_path):
        # The wrap fallback adds physical lines; the documented "total
        # lines in the expanded output" stat must count the source that is
        # actually returned, not the pre-re-pad line list.
        long_line = "       88  :T:-OK VALUE 'AAAA' 'BBBB' 'CCCC' 'DDDD' 'EEEE' 'FFFF'."
        (tmp_path / "WRAP.CPY").write_text(
            "       01  :T:-FLAG PIC X.\n" + long_line + "\n"
        )
        src = (
            "\n".join(
                [
                    _pad72("IDENTIFICATION DIVISION."),
                    _pad72("PROGRAM-ID. WRAPSTAT."),
                    _pad72("DATA DIVISION."),
                    _pad72("WORKING-STORAGE SECTION."),
                    _pad72("COPY WRAP REPLACING ==:T:== BY ==LONG-RENAMED-PREFIX==."),
                    _pad72("PROCEDURE DIVISION."),
                    _pad72("    STOP RUN."),
                ]
            )
            + "\n"
        )
        result = expand_copybooks(src, copybook_paths=[str(tmp_path)])
        assert result.statistics.total_lines == len(result.expanded_source.splitlines())

    def test_short_code_lines_survive_strip(self):
        # Blanking every sub-7-char line silently deleted real code from
        # flush-left (sequence-number-less) copybooks -- `01 A.` vanished
        # from the AST with no warning. Only tag-shaped content (single
        # blank-free token, no terminating period, not a compiler
        # directive) is blanked now.
        out = strip_sequence_area("P2P\n01 A.\nEXIT.\nM1005\nEJECT").split("\n")
        assert out[0] == ""  # tag blanked
        assert out[1] == "01 A."  # short code kept
        assert out[2] == "EXIT."  # short statement kept
        assert out[3] == ""  # tag blanked
        assert out[4] == "EJECT"  # compiler directive kept


class TestFlushLeftCompilerDirective:
    def test_process_directive_survives_strip(self):
        line = "PROCESS &CICS-31& &HAUTE-PERFORM-DB2&"
        out = strip_sequence_area(line).split("\n")
        assert out[0] == line

    def test_cbl_directive_survives_strip(self):
        out = strip_sequence_area("CBL APOST").split("\n")
        assert out[0] == "CBL APOST"

    def test_numbered_sequence_area_still_stripped(self):
        # A real sequence-numbered line must still lose columns 1-6, even
        # when the code area happens to start with "PROCESS" as a data
        # name or similar -- only a flush-left directive is exempted.
        line = "012345 PROCESS-FLAG PIC X."
        out = strip_sequence_area(line).split("\n")
        assert out[0] == " PROCESS-FLAG PIC X."

    def test_process_directive_does_not_break_program_id(self, tmp_path):
        src = (
            "\n".join(
                [
                    "PROCESS &CICS-31& &HAUTE-PERFORM-DB2&",
                    _pad72("IDENTIFICATION DIVISION."),
                    _pad72("PROGRAM-ID. HY0900IC."),
                    _pad72("PROCEDURE DIVISION."),
                    _pad72("    STOP RUN."),
                ]
            )
            + "\n"
        )
        result = expand_copybooks(src, copybook_paths=[str(tmp_path)])
        assert "PROCESS &CICS-31& &HAUTE-PERFORM-DB2&" in result.expanded_source

        parse = parse_cobol(result.expanded_source, filename="hy0900ic.cbl")
        assert parse.success, parse.errors
        assert parse.ast.program_name == "HY0900IC"
