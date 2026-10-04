"""Regression (#251): a quote in a comment-entry no longer derails COPY/REPLACE.

``AUTHOR. JOHN O'BRIEN.`` is comment-entry text. The COPY and REPLACE
text scanners used to read its apostrophe as the start of a literal with no
end-of-line bound, so the "literal" swallowed everything up to the next
quote anywhere in the file (or EOF):

* a COPY after it was never expanded and a REPLACE never applied -- with no
  warning;
* the parity flipped on the next literal, so ``VALUE 'COPY NO. 1 OF 2'``
  was scanned as program text: ``parse_cobol`` blanked "COPY NO." out of
  the value and ``parse_cobol_with_expansion`` raised
  ``CopybookNotFoundError`` for member ``NO``.

Both scanners now end a literal at the end of its line (they run after
continuation records are merged, so no real literal spans a newline), and
skip comment-entry text altogether: a ``COPY`` written in a REMARKS
paragraph is prose and is never expanded (the option #251 recommends).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from cobolparser import parse_cobol, parse_cobol_with_expansion
from cobolparser.preprocess.copy_statement_parser import CopyStatementLexer
from cobolparser.preprocess.replace_statement import apply_replace_statements

NIST_DIR = Path(__file__).parent.parent.parent / "examples" / "cobol"


def _fixed(lines: list[str]) -> str:
    return "".join(f"000000 {line}\n" for line in lines)


_HEAD = [
    "IDENTIFICATION DIVISION.",
    "PROGRAM-ID. T1.",
    "AUTHOR. JOHN O'BRIEN.",
]
_TAIL = [
    "PROCEDURE DIVISION.",
    "MAIN-PARA.",
    "    DISPLAY A",
    "    STOP RUN.",
]


def _data_items(result) -> dict[str, object]:
    assert result.ast is not None
    return {
        item.name: item.value_clause
        for item in result.ast.find_all_by_type("CobolDataItem")
    }


@pytest.fixture
def copybooks(tmp_path: Path) -> Path:
    (tmp_path / "CBX.cpy").write_text("       01 FROM-COPYBOOK PIC X.\n")
    return tmp_path


def test_copy_after_apostrophe_in_author_is_expanded(copybooks: Path) -> None:
    source = _fixed(
        _HEAD
        + ["DATA DIVISION.", "WORKING-STORAGE SECTION.", "01 A PIC X.", "COPY CBX."]
        + _TAIL
    )
    result = parse_cobol_with_expansion(source, "x.cbl", [str(copybooks)])
    assert result.success
    assert "FROM-COPYBOOK" in _data_items(result)


def test_replace_after_apostrophe_in_author_is_applied() -> None:
    source = _fixed(
        _HEAD
        + [
            "REPLACE ==WS-X== BY ==WS-Y==.",
            "DATA DIVISION.",
            "WORKING-STORAGE SECTION.",
            "01 A PIC X.",
            "01 WS-X PIC X.",
        ]
        + _TAIL
    )
    items = _data_items(parse_cobol(source))
    assert "WS-Y" in items
    assert "WS-X" not in items


_LITERAL_SOURCE = _fixed(
    _HEAD
    + [
        "DATA DIVISION.",
        "WORKING-STORAGE SECTION.",
        "01 A PIC X.",
        "01 HDR PIC X(20) VALUE 'COPY NO. 1 OF 2'.",
    ]
    + _TAIL
)


def test_copy_text_inside_a_later_literal_is_not_blanked() -> None:
    result = parse_cobol(_LITERAL_SOURCE)
    assert "COPY NO. 1 OF 2" in str(_data_items(result)["HDR"])
    assert not [w for w in result.warnings if "COPY" in w]


def test_copy_text_inside_a_later_literal_is_not_expanded(copybooks: Path) -> None:
    result = parse_cobol_with_expansion(_LITERAL_SOURCE, "x.cbl", [str(copybooks)])
    assert "COPY NO. 1 OF 2" in str(_data_items(result)["HDR"])


@pytest.mark.parametrize(
    "entry",
    [
        "INSTALLATION. BOB'S SHOP.",
        "REMARKS. IT'S A TEST.",
        "DATE-WRITTEN. JAN'99.",
        'SECURITY. SAY "HI.',
    ],
)
def test_other_comment_entries(entry: str, copybooks: Path) -> None:
    source = _fixed(
        ["IDENTIFICATION DIVISION.", "PROGRAM-ID. T1.", entry]
        + ["DATA DIVISION.", "WORKING-STORAGE SECTION.", "01 A PIC X.", "COPY CBX."]
        + _TAIL
    )
    result = parse_cobol_with_expansion(source, "x.cbl", [str(copybooks)])
    assert "FROM-COPYBOOK" in _data_items(result)


def test_copy_written_in_a_comment_entry_is_prose(copybooks: Path) -> None:
    source = _fixed(
        ["IDENTIFICATION DIVISION.", "PROGRAM-ID. T1.", "REMARKS. SEE COPY PAYREC."]
        + ["DATA DIVISION.", "WORKING-STORAGE SECTION.", "01 A PIC X.", "COPY CBX."]
        + _TAIL
    )
    result = parse_cobol_with_expansion(source, "x.cbl", [str(copybooks)])
    assert result.success
    assert "FROM-COPYBOOK" in _data_items(result)
    assert not [w for w in result.warnings if "PAYREC" in w]


def test_unterminated_literal_ends_at_end_of_line() -> None:
    source = "       DISPLAY 'ABC\n       COPY CBX.\n"
    statements = CopyStatementLexer(source).tokenize_copy_statements()
    assert [s.member_name for s in statements] == ["CBX"]


def test_replace_scanner_literal_ends_at_end_of_line() -> None:
    source = (
        "       DISPLAY 'ABC\n       REPLACE ==A== BY ==B==.\n       MOVE A TO C.\n"
    )
    assert "MOVE B TO C." in apply_replace_statements(source)


def test_nist_sg104a_has_no_phantom_copy_warning() -> None:
    source = (NIST_DIR / "SG104A.CBL").read_text(errors="replace")
    result = parse_cobol(source, filename="SG104A.CBL")
    assert not [w for w in result.warnings if "COPY NOT" in w]
    expanded = parse_cobol_with_expansion(source, "SG104A.CBL", [str(NIST_DIR)])
    assert not [w for w in expanded.warnings if "COPY NOT" in w]
