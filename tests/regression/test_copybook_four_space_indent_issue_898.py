"""Issue #898: a free-form copybook member indented exactly four spaces put
its level numbers in columns 5-6 and its data names from column 8, and was
read as fixed format: the levels were cut off and every field came out
``ANONYMOUS-n-7``."""

from __future__ import annotations

import pytest

from cobolparser import parse_cobol_with_expansion
from cobolparser._source_text.source_format import detect_member_fixed_format

PROGRAM = """\
identification division.
program-id. p.
data division.
working-storage section.
01 ws-rec.
    copy rec.
procedure division.
    move 'abc' to ws-a
    display ws-a ws-b
    goback.
"""


def _member(indent: int) -> str:
    pad = " " * indent
    return f"{pad}05 WS-A PIC X(3).\n{pad}05 WS-B PIC 9(4).\n"


@pytest.mark.parametrize("indent", [0, 1, 2, 3, 4, 5, 6])
@pytest.mark.parametrize("default", [False, True])
def test_free_form_indents_detected_free(indent, default):
    assert detect_member_fixed_format(_member(indent), default=default) is False


def test_level_at_column_8_stays_fixed():
    assert detect_member_fixed_format(_member(7), default=False) is True


@pytest.mark.parametrize(
    "member",
    [
        # A six-digit sequence number before the level number.
        "000100 05 WS-A PIC X.\n000200 05 WS-B PIC X.\n",
        # A short sequence number, then a level number in Area A.
        "    10 01 REC.\n    20     05 A PIC X.\n",
    ],
)
def test_sequence_numbers_keep_fixed(member):
    assert detect_member_fixed_format(member, default=False) is True


def test_fields_keep_their_names_and_levels(tmp_path):
    books = tmp_path / "cb"
    books.mkdir()
    (books / "REC.cpy").write_text(_member(4))
    result = parse_cobol_with_expansion(PROGRAM, "P.cbl", copybook_paths=[str(books)])
    items = [
        (i.to_dict()["level"], i.to_dict()["name"])
        for i in result.ast.find_all_by_type("DataItem")
    ]
    assert items == [(1, "ws-rec"), (5, "WS-A"), (5, "WS-B")]
    assert not result.warnings
