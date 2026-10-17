"""A line break inside an INITIALIZE phrase must not drop it (issue #575).

``InitializeStatementParser`` looked ahead with raw ``peek(1)`` /
``peek(2)``, which see the NEWLINE token rather than the next word, so a
line break inside ``ALL TO VALUE``, ``THEN REPLACING`` or ``THEN TO
DEFAULT`` lost the phrase -- silently for ``THEN`` / ``TO DEFAULT``. Every
form below is split at every token gap and must parse exactly as it does on
one line, with no warnings.
"""

from __future__ import annotations

from typing import Any

import pytest

from cobolparser import parse_cobol
from cobolparser.analysis.field_lineage import FieldFlowAnalyzer

FORMS = [
    "INITIALIZE WS-G1 WITH FILLER ALL TO VALUE THEN TO DEFAULT",
    "INITIALIZE WS-G1 ALL TO VALUE",
    "INITIALIZE WS-G1 NUMERIC TO VALUE",
    "INITIALIZE WS-G1 THEN REPLACING NUMERIC DATA BY 1",
    "INITIALIZE WS-G1 WITH FILLER ALL TO VALUE THEN REPLACING NUMERIC DATA BY 0 "
    "THEN TO DEFAULT",
    "INITIALIZE WS-G1 REPLACING ALPHANUMERIC DATA BY WS-DEF NUMERIC BY 7",
    "INITIALIZE WS-G1 THEN TO DEFAULT",
]

_LOCATION_KEYS = {"location", "line", "column", "end_line", "end_column"}


def _strip(node: Any) -> Any:
    if isinstance(node, dict):
        return {k: _strip(v) for k, v in node.items() if k not in _LOCATION_KEYS}
    if isinstance(node, list):
        return [_strip(v) for v in node]
    return node


def _program(statement: str) -> str:
    return (
        "IDENTIFICATION DIVISION.\n"
        "PROGRAM-ID. INIT1.\n"
        "DATA DIVISION.\n"
        "WORKING-STORAGE SECTION.\n"
        "01 WS-DEF PIC X(4).\n"
        "01 WS-G1.\n"
        "   05 WS-X PIC X(4) VALUE 'AB'.\n"
        "   05 WS-N PIC 9(3) VALUE 5.\n"
        "PROCEDURE DIVISION.\n"
        "MAIN-PARA.\n"
        "    ACCEPT WS-DEF\n"
        f"    {statement}\n"
        "    DISPLAY WS-G1\n"
        "    STOP RUN.\n"
    )


def _initialize(statement: str) -> dict[str, Any]:
    result = parse_cobol(_program(statement), filename="init1.cbl")
    assert result.ast is not None and result.errors == [], result.errors
    assert result.warnings == [], result.warnings
    (stmt,) = result.ast.find_all_by_type("InitializeStatement")
    return _strip(stmt.to_dict())


def _splits(form: str) -> list[str]:
    words = form.split(" ")
    return [
        " ".join(words[:i]) + "\n        " + " ".join(words[i:])
        for i in range(1, len(words))
    ]


@pytest.mark.parametrize("form", FORMS)
def test_line_break_at_every_gap_keeps_the_phrase(form: str) -> None:
    expected = _initialize(form)
    for split in _splits(form):
        assert _initialize(split) == expected, split


def test_one_line_forms_parse_every_phrase() -> None:
    full = _initialize(FORMS[4])
    assert full["with_filler"] is True
    assert full["to_value_category"] == "ALL"
    assert full["replacing_clauses"] == [{"category": "NUMERIC", "by_value": "0"}]
    assert full["to_default"] is True


def test_lineage_keeps_replacing_by_source_across_a_line_break() -> None:
    source = _program(
        "INITIALIZE WS-G1 ALL TO VALUE THEN\n"
        "        REPLACING ALPHANUMERIC DATA BY WS-DEF"
    )
    ast = parse_cobol(source, filename="init1.cbl").ast
    edges = FieldFlowAnalyzer().analyze(ast).to_dict()["edges"]
    moved = {
        e["target"]["name"]
        for e in edges
        if e["source"]["name"] == "WS-DEF" and e["statement"] == "INITIALIZE"
    }
    assert "WS-G1.WS-X" in moved, edges
