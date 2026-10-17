"""A separator comma / semicolon is a space in COBOL (issue #569).

MOVE kept it in its source (``MOVE 'ABC', TO X`` -> source ``"ABC",``),
INSPECT stopped at it and silently dropped every later TALLYING counter /
REPLACING pair / CONVERTING operand, and INITIALIZE REPLACING and ACCEPT
stopped at it with an "Unparsed tokens" warning. Each statement below must
parse exactly as its separator-free form, with no warnings.
"""

from __future__ import annotations

from typing import Any

import pytest

from cobolparser import parse_cobol
from cobolparser.analysis.const_fold import ConstantFolder
from cobolparser.generators.data.program_layout import ProgramLayoutIndex

_LOCATION_KEYS = {"location", "line", "column", "end_line", "end_column"}


def _strip(node: Any) -> Any:
    if isinstance(node, dict):
        return {k: _strip(v) for k, v in node.items() if k not in _LOCATION_KEYS}
    if isinstance(node, list):
        return [_strip(v) for v in node]
    return node


def _program(body: str) -> str:
    return (
        "IDENTIFICATION DIVISION.\n"
        "PROGRAM-ID. SEP.\n"
        "DATA DIVISION.\n"
        "WORKING-STORAGE SECTION.\n"
        "01 WS-TEXT PIC X(10) VALUE 'BANANA'.\n"
        "01 WS-CNT-A PIC 9(3).\n"
        "01 WS-CNT-N PIC 9(3).\n"
        "01 WS-A PIC X(3).\n"
        "01 WS-B PIC 9(3).\n"
        "01 WS-T PIC X(3) OCCURS 5.\n"
        "01 REC.\n"
        "   05 R-N PIC 9(3).\n"
        "   05 R-X PIC X(3).\n"
        "PROCEDURE DIVISION.\n"
        "MAIN-PARA.\n"
        + "".join(f"    {line}\n" for line in body.strip().splitlines())
        + "    GOBACK.\n"
    )


def _statements(body: str) -> list[dict[str, Any]]:
    result = parse_cobol(_program(body), filename="sep.cbl")
    assert result.ast is not None and result.errors == [], result.errors
    assert result.warnings == [], result.warnings
    return [_strip(s.to_dict()) for s in result.ast.get_all_statements()]


# (with separators, without)
CASES = {
    "move-literal": ("MOVE 'ABC', TO WS-A", "MOVE 'ABC' TO WS-A"),
    "move-number-semicolon": ("MOVE 42; TO WS-B", "MOVE 42 TO WS-B"),
    "move-identifier": ("MOVE WS-A, TO WS-TEXT", "MOVE WS-A TO WS-TEXT"),
    "inspect-tallying": (
        "INSPECT WS-TEXT TALLYING WS-CNT-A FOR ALL 'A',\n" "    WS-CNT-N FOR ALL 'N'",
        "INSPECT WS-TEXT TALLYING WS-CNT-A FOR ALL 'A'\n" "    WS-CNT-N FOR ALL 'N'",
    ),
    "inspect-replacing-pairs": (
        "INSPECT WS-TEXT REPLACING ALL 'A' BY 'O', ALL 'N' BY 'M'",
        "INSPECT WS-TEXT REPLACING ALL 'A' BY 'O' ALL 'N' BY 'M'",
    ),
    "inspect-replacing-same-type": (
        "INSPECT WS-TEXT REPLACING ALL 'A', BY 'O', 'N'; BY 'M'",
        "INSPECT WS-TEXT REPLACING ALL 'A' BY 'O' 'N' BY 'M'",
    ),
    "inspect-target": (
        "INSPECT WS-TEXT, REPLACING ALL 'A' BY 'B'",
        "INSPECT WS-TEXT REPLACING ALL 'A' BY 'B'",
    ),
    "inspect-converting": (
        "INSPECT WS-TEXT CONVERTING 'ABC', TO 'XYZ', BEFORE INITIAL 'N'",
        "INSPECT WS-TEXT CONVERTING 'ABC' TO 'XYZ' BEFORE INITIAL 'N'",
    ),
    "inspect-tallying-replacing": (
        "INSPECT WS-TEXT; TALLYING WS-CNT-A FOR CHARACTERS;\n"
        "    REPLACING ALL 'A' BY 'B'",
        "INSPECT WS-TEXT TALLYING WS-CNT-A FOR CHARACTERS\n"
        "    REPLACING ALL 'A' BY 'B'",
    ),
    "initialize-replacing": (
        "INITIALIZE REC REPLACING NUMERIC BY 0, ALPHANUMERIC BY SPACES",
        "INITIALIZE REC REPLACING NUMERIC BY 0 ALPHANUMERIC BY SPACES",
    ),
    "accept-from": ("ACCEPT WS-A, FROM DATE", "ACCEPT WS-A FROM DATE"),
}


@pytest.mark.parametrize("name", sorted(CASES))
def test_separator_parses_like_a_space(name: str) -> None:
    with_sep, without = CASES[name]
    assert _statements(with_sep) == _statements(without)


def test_move_source_keeps_commas_inside_parentheses() -> None:
    move = _statements("MOVE FUNCTION MAX(WS-B, 3), TO WS-B")[0]
    assert move["source"] == "FUNCTION MAX(WS-B, 3)"


def test_constant_folding_sees_every_inspect_phrase_and_move() -> None:
    result = parse_cobol(
        _program(
            "MOVE 0 TO WS-CNT-A WS-CNT-N\n"
            "INSPECT WS-TEXT TALLYING WS-CNT-A FOR ALL 'A',\n"
            "    WS-CNT-N FOR ALL 'N'\n"
            "MOVE 'ABC', TO WS-A\n"
            "MOVE 42, TO WS-B\n"
            "DISPLAY WS-TEXT ' ' WS-CNT-A ' ' WS-CNT-N ' ' WS-A ' ' WS-B"
        ),
        filename="sep.cbl",
    )
    ast = result.ast
    known = ConstantFolder().fold(ast, ProgramLayoutIndex.build(ast)).known
    # The INSPECT writes WS-CNT-N: it no longer reads as still holding 0.
    assert "WS-CNT-N" not in known
    assert known.get("WS-A") == "ABC"
    assert known.get("WS-B") == "42"
