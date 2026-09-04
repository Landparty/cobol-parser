"""ProgramLayoutIndex.condition_values(): one level-88's OWN values.

`resolve()` deliberately maps a level-88 condition name to its *parent*
field, and `FieldSpec.condition_values` is deliberately the union of every
88 declared under that field ("any value that could apply to this field" --
what the value factory wants). Neither answers "what does THIS condition
name require", which is what constraint extraction needs; reading the union
instead made every arm of an `EVALUATE TRUE / WHEN <88>` chain produce an
identical constraint.
"""

from __future__ import annotations

from cobolparser import parse_cobol
from cobolparser.generators import ProgramLayoutIndex

_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. COND88.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT F1 ASSIGN TO 'F1.DAT'.
       DATA DIVISION.
       FILE SECTION.
       FD  F1.
       01  F1-REC.
           05  F1-TYPE         PIC X(02).
              88  F1-TYPE-M    VALUE '05'.
              88  F1-TYPE-F    VALUE '09'.
           05  F1-CODE         PIC 9(2).
              88  F1-CODE-LOW  VALUE 1 THRU 3.
       WORKING-STORAGE SECTION.
       01  WS-EOF              PIC X VALUE 'N'.
       PROCEDURE DIVISION.
       MAIN-PARA.
           READ F1
               AT END MOVE 'Y' TO WS-EOF
           END-READ.
"""


def _index():
    result = parse_cobol(_SOURCE, filename="cond88.cbl")
    assert result.ast is not None, result.errors
    return ProgramLayoutIndex.build(result.ast)


def test_each_condition_name_reports_only_its_own_values():
    index = _index()
    assert index.condition_values("F1-TYPE-M") == ("05",)
    assert index.condition_values("F1-TYPE-F") == ("09",)


def test_parent_field_still_reports_the_union():
    """The union is not wrong, it just answers a different question -- and
    the value factory still depends on it. Both must stay available."""
    index = _index()
    resolved = index.resolve("F1-TYPE-M")
    assert resolved is not None
    assert resolved.spec.name == "F1-TYPE"  # 88 resolves to its parent
    assert list(resolved.spec.condition_values) == ["05", "09"]


def test_lookup_is_case_insensitive_and_whitespace_tolerant():
    index = _index()
    assert index.condition_values("  f1-type-f  ") == ("09",)


def test_thru_ranges_are_expanded_like_the_union_path():
    index = _index()
    assert index.condition_values("F1-CODE-LOW") == ("1", "2", "3")


def test_a_plain_field_name_is_not_a_condition_name():
    index = _index()
    assert index.condition_values("F1-TYPE") is None
    assert index.condition_values("NOPE") is None
    assert index.condition_values("") is None
