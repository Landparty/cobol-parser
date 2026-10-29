"""Regression tests: a ``#`` in a comment line of a copybook whose blank lines
kept only their sequence numbers.

A mainframe export that strips trailing blanks turns each empty record of a
numbered member into ``000200``: the sequence area and nothing else. The
fixed-format detector skipped those lines without crediting them, yet still
counted them in its ten-line sample, so a copybook with a few blank lines in
its banner fell under the 60% bar and was judged free-form. Its column-7
comment lines were then spliced into the program as code, and the first
``#`` in one failed the parse (TPRC5083 / FICHPTVT in a corpus sweep):

    Lexer error: Invalid character: #
"""

from __future__ import annotations

from pathlib import Path

import pytest

from cobolparser import parse_cobol, parse_cobol_with_expansion
from cobolparser.parser import _detect_fixed_format
from cobolparser.preprocess import expand_copybooks

_PROGRAM = "\n".join(
    [
        "000100 IDENTIFICATION DIVISION.",
        "000200 PROGRAM-ID. TESTP.",
        "000300 DATA DIVISION.",
        "000400 WORKING-STORAGE SECTION.",
        "000500     COPY FICHPTVT.",
        "000600 PROCEDURE DIVISION.",
        "000700     DISPLAY FPT-ID.",
        "000800     GOBACK.",
    ]
)

_FICHPTVT = "\n".join(
    [
        "000100*----------------------------------------------------------*",
        "000200",
        "000300* COPYBOOK FICHPTVT",
        "000400",
        "000500",
        "000600",
        "000700",
        "000800* # NUMERO DE COMPTE",
        "000900 01  FICHPTVT-REC.",
        "001000     05  FPT-ID          PIC X(10).",
        "001100",
        "001200     05  FPT-NUM         PIC 9(5).",
        "001300",
        "001400     05  FPT-LIB         PIC X(30).",
        "001500",
        "001600*#########################################################",
    ]
)


def _data_names(result) -> list[str]:
    return [item.name for item in result.ast.find_all_by_type("CobolDataItem")]


@pytest.fixture
def copylib(tmp_path: Path) -> Path:
    (tmp_path / "FICHPTVT.cpy").write_text(_FICHPTVT + "\n")
    return tmp_path


class TestNumberedBlankLines:
    def test_expand_then_parse(self, copylib):
        expansion = expand_copybooks(_PROGRAM + "\n", copybook_paths=[str(copylib)])
        assert "#" not in expansion.expanded_source
        result = parse_cobol(expansion.expanded_source, filename="TESTP.cbl")
        assert result.success, [str(e) for e in result.errors]
        assert _data_names(result) == ["FICHPTVT-REC", "FPT-ID", "FPT-NUM", "FPT-LIB"]

    def test_parse_with_expansion(self, copylib):
        result = parse_cobol_with_expansion(
            _PROGRAM + "\n", "TESTP.cbl", copybook_paths=[str(copylib)]
        )
        assert result.success, [str(e) for e in result.errors]

    def test_short_member_with_numbered_blank_line(self, tmp_path):
        """Under three non-blank lines the member is judged line by line."""
        (tmp_path / "FICHPTVT.cpy").write_text("000100*# SHORT\n000200\n")
        expansion = expand_copybooks(_PROGRAM + "\n", copybook_paths=[str(tmp_path)])
        assert "#" not in expansion.expanded_source

    def test_whole_program_with_numbered_blank_lines(self):
        source = "\n".join(
            [
                "000100*# BANNER #",
                "000200",
                "000300",
                "000400",
                "000500",
                "000600 IDENTIFICATION DIVISION.",
                "000700 PROGRAM-ID. TESTP.",
                "000800*# MORE #",
                "000900",
                "001000 PROCEDURE DIVISION.",
                "001100     GOBACK.",
            ]
        )
        result = parse_cobol(source, filename="TESTP.cbl")
        assert result.success, [str(e) for e in result.errors]


class TestDetection:
    def test_numbered_blank_lines_count_as_fixed(self):
        assert _detect_fixed_format(_FICHPTVT) is True

    def test_short_free_form_words_are_not_numbered_blanks(self):
        """A short non-numeric line is still no fixed-format evidence."""
        source = "\n".join(["MOVE A", "TO B.", "GOBACK.", "EXIT.", "STOP"])
        assert _detect_fixed_format(source) is False
