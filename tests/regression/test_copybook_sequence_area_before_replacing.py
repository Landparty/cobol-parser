"""Regression tests: sequence-number/identification columns must be ignored
in copybook content *before* REPLACING, conditional compilation, and
validation run — not only in the final parsed output.

``_expand_source_recursive`` used to run ``apply_replacing_clauses``,
``preprocess_conditional_compilation``, ``validate_copybook_content``, and
``validate_level_numbers`` on the raw copybook file content (sequence-number
area in columns 1-6 and identification area in columns 73-80 still present),
and only stripped those columns *afterwards*, immediately before recursing.
Two concrete failures resulted:

1. A length-changing ``REPLACING`` clause shifted every character after the
   match point on that raw (80-column) line. Since the column-72 boundary was
   then applied to the *shifted* line, a shrinking replacement pulled
   identification-area text (columns 73-80) into the kept code window, and a
   growing replacement pushed real code — including its terminating period —
   past column 72, silently truncating it.
2. ``>>IF``/``>>END-IF`` compiler-directing lines in a copybook with real
   (non-blank) sequence numbers were never recognized as directives at all,
   because the directive check (`line.strip().startswith(">>")`) saw the
   sequence-number digits first.

Fixed by stripping the sequence/identification areas and blanking comment
lines immediately after reading the copybook file, before REPLACING,
conditional compilation, or validation ever see the content.
"""

from pathlib import Path

from cobolparser.preprocess import expand_copybooks

_HEADER = (
    "       IDENTIFICATION DIVISION.\n"
    "       PROGRAM-ID. SEQAREATEST.\n"
    "       DATA DIVISION.\n"
    "       WORKING-STORAGE SECTION.\n"
)
_FOOTER = "       PROCEDURE DIVISION.\n" "           STOP RUN.\n"


def _fixed_line(seq6: str, indicator: str, code: str, ident: str = "") -> str:
    """Build one 80-column fixed-format line with explicit column control."""
    assert len(seq6) == 6
    assert len(indicator) == 1
    code_area = code.ljust(65)[:65]
    return seq6 + indicator + code_area + ident.ljust(8)[:8]


def _write(directory: Path, name: str, lines: list[str]) -> Path:
    path = directory / name
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


class TestReplacingDoesNotCrossColumn72Boundary:
    """A length-changing REPLACING must never leak or truncate columns
    relative to the *original* line's 1-6/73-80 boundaries."""

    def test_shrinking_replacement_does_not_leak_identification_area(self, tmp_path):
        # The replaced token sits flush against column 72; identification
        # area ("IDSTAMP1") occupies columns 73-80 on the same line.
        _write(
            tmp_path,
            "DECTEST.CPY",
            [
                _fixed_line(
                    "000100",
                    " ",
                    "     05 FIELD-X       PIC X(10) VALUE         "
                    "LONGPLACEHOLDERTAG ",
                    "IDSTAMP1",
                )
            ],
        )
        source = (
            _HEADER
            + "       01 REC-A.\n"
            + "       COPY DECTEST REPLACING ==LONGPLACEHOLDERTAG== BY ==X==.\n"
            + _FOOTER
        )
        result = expand_copybooks(source, copybook_paths=[str(tmp_path)])
        expanded = result.expanded_source
        assert "IDSTAMP1" not in expanded
        assert "FIELD-X" in expanded and "VALUE         X" in expanded

    def test_growing_replacement_does_not_truncate_code(self, tmp_path):
        # The replaced token (plus its terminating period) sits flush
        # against column 72.
        _write(
            tmp_path,
            "INCTEST.CPY",
            [
                _fixed_line(
                    "000200",
                    " ",
                    "     05 FIELD-Y       PIC X(5) VALUE                   "
                    "SHORTTAG. ",
                    "IDSTAMP2",
                )
            ],
        )
        source = (
            _HEADER
            + "       01 REC-B.\n"
            + "       COPY INCTEST REPLACING ==SHORTTAG==\n"
            + "      -    BY ==MUCHLONGERREPLACEMENTVALUE==.\n"
            + _FOOTER
        )
        result = expand_copybooks(source, copybook_paths=[str(tmp_path)])
        expanded = result.expanded_source
        # The full replacement text, including the terminating period, must
        # survive -- a truncated period would silently merge this statement
        # with the next one.
        assert "MUCHLONGERREPLACEMENTVALUE." in expanded
        assert "IDSTAMP2" not in expanded


class TestConditionalCompilationInCopybookIgnoresSequenceArea:
    """>>IF/>>END-IF inside a copybook must be recognized regardless of
    whether the copybook uses real (numeric) sequence numbers."""

    def test_if_directive_recognized_with_real_sequence_numbers(self, tmp_path):
        _write(
            tmp_path,
            "COND.CPY",
            [
                _fixed_line("000100", " ", ">>IF DEBUGMODE"),
                _fixed_line("000200", " ", "01 DEBUG-FIELD PIC X(10)."),
                _fixed_line("000300", " ", ">>END-IF"),
                _fixed_line("000400", " ", "01 REAL-FIELD PIC X(5)."),
            ],
        )
        source = _HEADER + "       COPY COND.\n" + _FOOTER
        result = expand_copybooks(
            source,
            copybook_paths=[str(tmp_path)],
            process_conditionals=True,
            defined_symbols={},
        )
        expanded = result.expanded_source
        assert "DEBUG-FIELD" not in expanded
        assert "REAL-FIELD" in expanded
