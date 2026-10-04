"""Regression (#254): a REPLACE ahead of the IDENTIFICATION DIVISION applies.

COBOL-85 and IBM Enterprise COBOL allow REPLACE as the first statement of a
compilation unit; it stays in effect until REPLACE OFF or end of source.
``CobolParser._skip_to_identification_division`` blanked every line before
the header (bar ``>>`` / CBL / PROCESS) *before* REPLACE was applied, so the
statement vanished without a warning and the parser saw ``WS-X`` where the
compiler sees ``WS-Y``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from cobolparser import CobolParser, parse_cobol, parse_cobol_with_expansion

_BODY = [
    "IDENTIFICATION DIVISION.",
    "PROGRAM-ID. T1.",
    "DATA DIVISION.",
    "WORKING-STORAGE SECTION.",
    "01 WS-X PIC X.",
    "PROCEDURE DIVISION.",
    "MAIN-PARA.",
    "    MOVE 'A' TO WS-X",
    "    STOP RUN.",
]


def _free(prefix: list[str]) -> str:
    return "".join(f"       {line}\n" for line in prefix + _BODY)


def _fixed(prefix: list[str]) -> str:
    return "".join(
        f"{n * 100:06d} {line}\n" for n, line in enumerate(prefix + _BODY, 1)
    )


def _data_names(result) -> list[str]:
    assert result.ast is not None
    return [item.name for item in result.ast.find_all_by_type("CobolDataItem")]


_PARSERS = {
    "parse_cobol": parse_cobol,
    "CobolParser.parse": lambda src: CobolParser().parse(src),
    "parse_cobol_with_expansion": lambda src: parse_cobol_with_expansion(
        src, "x.cbl", [str(Path(__file__).parent)]
    ),
}


@pytest.mark.parametrize("layout", [_free, _fixed], ids=["free", "fixed"])
@pytest.mark.parametrize("entry", list(_PARSERS))
def test_leading_replace_is_applied(entry: str, layout) -> None:
    result = _PARSERS[entry](layout(["REPLACE ==WS-X== BY ==WS-Y==."]))
    assert _data_names(result) == ["WS-Y"]
    assert result.errors == []
    targets = [m.targets for m in result.ast.find_all_by_type("MoveStatement")]
    assert targets == [["WS-Y"]]


def test_leading_replace_spanning_lines_after_junk() -> None:
    source = _free(
        [
            "THIS IS A LISTING HEADER, NOT COBOL",
            "REPLACE ==WS-X==",
            "     BY ==WS-Y==.",
        ]
    )
    assert _data_names(parse_cobol(source)) == ["WS-Y"]


def test_junk_before_the_header_is_still_dropped() -> None:
    source = _free(["//JOBCARD JOB (ACCT),'NAME'"])
    result = parse_cobol(source)
    assert result.errors == []
    assert _data_names(result) == ["WS-X"]


def test_skip_keeps_line_count() -> None:
    source = _free(["JUNK", "REPLACE ==WS-X== BY ==WS-Y==.", "JUNK"])
    cleaned = CobolParser._skip_to_identification_division(source)
    assert cleaned.count("\n") == source.count("\n")
    assert "JUNK" not in cleaned
    assert "REPLACE ==WS-X== BY ==WS-Y==." in cleaned
