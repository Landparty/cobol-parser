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
Fixed by blanking short lines in ``strip_sequence_area``: every character
of a sub-7-character line lies within columns 1-6, the exact area the
function exists to strip.
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
