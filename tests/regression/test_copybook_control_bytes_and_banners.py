"""Copybooks with raw control bytes, and copybooks that open with a banner.

Two shapes from a real mainframe checkout that broke copybook expansion:

* NUL and other C0 control bytes typed into VALUE literals (a low-value,
  a printer control code) survive the EBCDIC -> ASCII transfer as raw
  bytes. Any NUL used to make ``validate_copybook_content`` refuse the
  member as binary, so expansion of the whole program stopped. IBM
  compiles such members; they now draw a warning naming the lines.
* A member whose first lines are an asterisk banner typed from column 1
  (``*******...``) was judged free-form, because those lines have no blank
  or numeric sequence area. Its column-7 comment lines were then spliced in
  as code, and a comment such as ``* MOVE THE TOTAL`` failed with
  "MOVE statement requires TO". The same banner at the top of a program
  sent the whole program down the free-form path.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from cobolparser import CobolParser, ErrorRecoveryMode
from cobolparser.parser import parse_cobol_with_expansion
from cobolparser.preprocess import CopybookSyntaxError, expand_copybooks


def _rec(text: str, indicator: str = " ", seq: str = "      ") -> str:
    """One 72-column fixed-format record."""
    return (seq + indicator + text).ljust(72)[:72]


def _program(copy_line: str, *, procedure: bool = False) -> str:
    lines = [
        _rec("IDENTIFICATION DIVISION."),
        _rec("PROGRAM-ID. CTLBYTES."),
        _rec("DATA DIVISION."),
        _rec("WORKING-STORAGE SECTION."),
        _rec("01  A  PIC 9(4)."),
        _rec("01  B  PIC 9(4)."),
    ]
    if not procedure:
        lines.append(_rec(copy_line))
    lines += [_rec("PROCEDURE DIVISION."), _rec("MAIN-PARA.")]
    if procedure:
        lines.append(_rec(copy_line))
    lines.append(_rec("    GOBACK."))
    return "\n".join(lines) + "\n"


def _write(path: Path, records: list[str]) -> None:
    path.write_text("\n".join(records) + "\n", encoding="utf-8", newline="")


def _parse(tmp_path: Path, source: str):  # type: ignore[no-untyped-def]
    return parse_cobol_with_expansion(
        source,
        "CTLBYTES.cbl",
        copybook_paths=[str(tmp_path)],
        error_recovery=ErrorRecoveryMode.COLLECT_ALL,
    )


class TestControlBytesInLiterals:
    def test_nul_bytes_in_a_value_literal_do_not_stop_expansion(
        self, tmp_path: Path
    ) -> None:
        _write(
            tmp_path / "NULREC.cpy",
            [
                _rec("01  WS-NULREC."),
                _rec("    05  WS-LOW  PIC X(2) VALUE '\x00\x00'."),
                _rec("    05  WS-B    PIC X."),
            ],
        )
        expansion = expand_copybooks(
            _program("    COPY NULREC."), [str(tmp_path)], validate_content=True
        )
        assert "WS-LOW" in expansion.expanded_source
        assert any(
            "2 NUL or control byte(s) on line(s) 2" in w
            for w in expansion.statistics.warnings
        )

    def test_control_bytes_keep_their_values(self, tmp_path: Path) -> None:
        _write(
            tmp_path / "CTLREC.cpy",
            [
                _rec("01  WS-CTL."),
                _rec("    05  WS-C1  PIC X(3) VALUE '\x01\x1f\x00'."),
                _rec("    05  WS-C2  PIC X    VALUE '\x0e'."),
            ],
        )
        result = _parse(tmp_path, _program("    COPY CTLREC."))
        assert result.errors == []
        items = {i.name: i for i in result.ast.find_all_by_type("DataItem")}
        assert items["WS-C1"].value_clause == '"\x01\x1f\x00"'
        assert items["WS-C2"].value_clause == '"\x0e"'

    def test_a_binary_file_is_still_refused(self, tmp_path: Path) -> None:
        (tmp_path / "LOADMOD.cpy").write_bytes(b"\x00\x01\x02\x03" * 64 + b"AB")
        with pytest.raises(CopybookSyntaxError, match="Binary content"):
            expand_copybooks(
                _program("    COPY LOADMOD."), [str(tmp_path)], validate_content=True
            )


BANNER = "*" * 72


class TestColumnOneBanner:
    def test_member_comment_lines_after_a_banner_stay_comments(
        self, tmp_path: Path
    ) -> None:
        _write(
            tmp_path / "CCSRTN.cpy",
            [
                BANNER,
                "*******  COMMON ROUTINE".ljust(71) + "*",
                BANNER,
                _rec(" MOVE THE AMOUNT INTO TOTALS", "*"),
                _rec(" MULTIPLY RATE FIRST", "*"),
                _rec("    MOVE 1 TO A."),
                _rec("    MOVE 2 TO B."),
            ],
        )
        result = _parse(tmp_path, _program("    COPY CCSRTN.", procedure=True))
        assert result.errors == []
        assert result.warnings == []
        assert len(result.ast.find_all_by_type("MoveStatement")) == 2

    def test_member_comment_with_blanks_in_its_sequence_area(
        self, tmp_path: Path
    ) -> None:
        _write(
            tmp_path / "TAGGED.cpy",
            [
                _rec("    MOVE 1 TO A.", seq="000100"),
                _rec(" MOVE THE AMOUNT INTO TOTALS", "*", seq="CR 12 "),
                _rec(" MULTIPLY RATE FIRST", "*", seq="CR 12 "),
                _rec("    MOVE 2 TO B.", seq="000200"),
            ],
        )
        result = _parse(tmp_path, _program("    COPY TAGGED.", procedure=True))
        assert result.errors == []
        assert result.warnings == []
        assert len(result.ast.find_all_by_type("MoveStatement")) == 2

    def test_program_opening_with_a_banner_is_fixed_format(self) -> None:
        source = "\n".join(
            [
                BANNER,
                "*******  PROGRAM BANNER".ljust(71) + "*",
                BANNER,
                "*******  AUTHOR".ljust(71) + "*",
                BANNER,
                "*******".ljust(71) + "*",
                _rec("IDENTIFICATION DIVISION."),
                _rec("PROGRAM-ID. BANNER."),
                _rec("PROCEDURE DIVISION."),
                _rec(" MOVE THE COMMENT", "*"),
                _rec("    GOBACK."),
            ]
        )
        result = CobolParser(error_recovery=ErrorRecoveryMode.COLLECT_ALL).parse(
            source + "\n"
        )
        assert result.errors == []

    def test_free_format_star_greater_banner_is_still_free(self) -> None:
        from cobolparser._source_text.source_format import detect_fixed_format

        source = "\n".join(
            [
                "*>" + "*" * 40,
                "*>****** PROGRAM BANNER",
                "*>" + "*" * 40,
                "IDENTIFICATION DIVISION.",
                "PROGRAM-ID. FREEPGM.",
                "PROCEDURE DIVISION.",
                "    DISPLAY 'HI'.",
            ]
        )
        assert detect_fixed_format(source) is False
