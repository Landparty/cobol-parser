"""Regression coverage for fixed-format continuation of *literals*.

COBOL continuation lines (``-`` in column 7) join the first non-blank
character of the continuation line directly onto the last non-blank
character of the continued line, **without an intervening space**. This
applies to numeric literals and words split mid-token, and (via the
already-handled open-quote path) to alphanumeric literals.

The numeric case used to be mishandled: ``normalize_fixed_format`` inserted
a space before every non-literal continuation chunk, so ``-999.777`` split
across continuation lines normalised to ``- 9  9  9  .  7  7  7`` — spaced
digits plus a free-standing ``.`` that the lexer then treated as a statement
terminator, truncating the MOVE. See NIST ``NC205A.CBL``.
"""

import pytest

from cobolparser import parse_cobol

# The pure-Python implementation, kept reachable even when the Cython
# ``_preprocess_fast`` extension overrides the public name (mirrors
# ``cobolparser.lexer._CobolLexerPure``).
from cobolparser.preprocess import _normalize_fixed_format_pure, normalize_fixed_format

# ``-999.777`` written one character per continuation line, exactly as it
# appears in NIST NC205A. Column 7 ('-') marks each continuation line.
NUMERIC_CONT_LINES = [
    "000100 IDENTIFICATION DIVISION.",
    "000200 PROGRAM-ID. CONTNUM.",
    "000300 DATA DIVISION.",
    "000400 WORKING-STORAGE SECTION.",
    "000500 01  CONT-B PIC S9(3)V9(3) VALUE ZERO.",
    "000600 PROCEDURE DIVISION.",
    "000700     MOVE     -",
    "000800-             9",
    "000900-             9",
    "001000-             9",
    "001100-             .",
    "001200-             7",
    "001300-             7",
    "001400-             7 TO CONT-B.",
    "001500     STOP RUN.",
]

# An alphanumeric literal split across a continuation line (open-quote path).
ALPHA_CONT_LINES = [
    "000100 IDENTIFICATION DIVISION.",
    "000200 PROGRAM-ID. CONTALPHA.",
    "000300 DATA DIVISION.",
    "000400 WORKING-STORAGE SECTION.",
    # The literal runs to column 72 exactly, so no blanks join the pieces.
    ("000500 01  MSG PIC X(10) VALUE" + ' "ABCDE'.rjust(72 - 30)),
    '000600-    "FGHIJ".',
    "000700 PROCEDURE DIVISION.",
    "000800     DISPLAY MSG.",
    "000900     STOP RUN.",
]


def _move_line(text: str) -> str:
    """Return the single normalised line carrying the continued MOVE."""
    lines = [ln for ln in text.splitlines() if "MOVE" in ln and "CONT-B" in ln]
    assert len(lines) == 1, f"expected exactly one MOVE...CONT-B line, got {lines}"
    return lines[0]


@pytest.mark.parametrize(
    "normalize",
    [normalize_fixed_format, _normalize_fixed_format_pure],
    ids=["active", "pure"],
)
def test_numeric_continued_literal_joins_without_spaces(normalize):
    """``-999.777`` split over continuation lines rejoins with no interior
    spaces and no free-standing period."""
    move_line = _move_line(normalize(NUMERIC_CONT_LINES))
    assert "-999.777 TO CONT-B." in move_line
    # The digits/point must be contiguous — no spaced-out mangling.
    assert "9  9" not in move_line
    assert "999.  7" not in move_line
    assert ". " not in move_line.split("CONT-B")[0]


@pytest.mark.parametrize(
    "normalize",
    [normalize_fixed_format, _normalize_fixed_format_pure],
    ids=["active", "pure"],
)
def test_alphanumeric_continued_literal_joins_without_spaces(normalize):
    """An alphanumeric literal split with '-' rejoins into one token."""
    text = normalize(ALPHA_CONT_LINES)
    assert '"ABCDEFGHIJ"' in text
    assert "ABCDE FGHIJ" not in text


def test_numeric_continued_literal_parses_to_correct_move():
    """After normalisation the MOVE reaches the parser intact: a single
    MoveStatement with source ``-999.777`` and target ``CONT-B``."""
    source = "\n".join(NUMERIC_CONT_LINES) + "\n"
    result = parse_cobol(source)
    matches = [
        m
        for m in result.ast.find_all_by_type("MoveStatement")
        if getattr(m, "source", None) == "-999.777"
        and "CONT-B" in (getattr(m, "targets", None) or [])
    ]
    assert len(matches) == 1, (
        "expected one MOVE -999.777 TO CONT-B, "
        f"got sources={[getattr(m, 'source', None) for m in result.ast.find_all_by_type('MoveStatement')]}"
    )


def test_nist_nc205a_numeric_continuation_normalises_cleanly():
    """The real NIST program that surfaced the bug normalises correctly.

    NC205A splits two numeric literals across continuation lines: the
    signed decimal ``-999.777`` and the integer ``45678`` (one digit per
    line). Both must rejoin without interior spaces.
    """
    from pathlib import Path

    nc205a = Path(__file__).parent.parent.parent / "examples" / "cobol" / "NC205A.CBL"
    raw = nc205a.read_text(encoding="utf-8", errors="ignore").splitlines()
    text = normalize_fixed_format(raw)
    assert "-999.777 TO CONT-B." in text
    assert "45678 TO CONT-B." in text
