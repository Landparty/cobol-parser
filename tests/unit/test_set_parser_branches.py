"""SET statement parsing: the branches the other SET test files leave open.

Each case is a real SET statement parsed through ``CobolParser`` and checked
on the resulting ``SetStatement`` (targets, set_type, value, groups,
metadata) and on the parse warnings: action keywords with no operand
(``TO.``, ``UP.``, ``TO ADDRESS.``, ``TO ENTRY.``), optional ``BY`` / ``OF``
words left out, later target/value groups using UP/DOWN/ENTRY, and the
places where a missing period meets the next statement or paragraph.
"""

import pytest

from cobolparser import CobolParser, ErrorRecoveryMode
from cobolparser.models.statements import SetStatement

PROGRAM = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. SETBR.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  IX-1                PIC 9(4) COMP.
       01  IX-2                PIC 9(4) COMP.
       01  PTR                 USAGE POINTER.
       01  PPTR                USAGE PROCEDURE-POINTER.
       01  TBL.
           05  TBL-IX          PIC 9(4) COMP OCCURS 3.
       LINKAGE SECTION.
       01  LK-REC              PIC X(10).
       PROCEDURE DIVISION.
       MAIN-PARA.
"""


def _parse(body: str):
    parser = CobolParser(error_recovery=ErrorRecoveryMode.COLLECT_ALL)
    result = parser.parse(PROGRAM + body, "setbr.cbl")
    assert result.ast is not None
    assert result.errors == []
    return result


def _sets(result) -> list[SetStatement]:
    return result.ast.find_all_by_type("SetStatement")


def _one_set(body: str):
    result = _parse(body)
    stmts = _sets(result)
    assert len(stmts) == 1, stmts
    return result, stmts[0]


def _paragraph_names(result) -> list[str]:
    return [p.paragraph_name for p in result.ast.procedure_division.paragraphs]


class TestActionWithoutOperand:
    def test_to_with_no_value(self):
        result, stmt = _one_set("           SET IX-1 TO.\n")
        assert result.warnings == []
        assert stmt.targets == ["IX-1"]
        assert stmt.set_type == "TO"
        assert stmt.value is None

    def test_down_with_no_by_and_no_value(self):
        result, stmt = _one_set("           SET IX-1 DOWN.\n")
        assert result.warnings == []
        assert stmt.set_type == "DOWN_BY"
        assert stmt.value is None

    def test_to_address_with_no_operand(self):
        result, stmt = _one_set("           SET PTR TO ADDRESS.\n")
        assert result.warnings == []
        assert stmt.set_type == "TO"
        assert stmt.value is None

    def test_to_entry_with_no_operand_still_marks_the_entry_form(self):
        result, stmt = _one_set("           SET PPTR TO ENTRY.\n")
        assert result.warnings == []
        assert stmt.set_type == "TO"
        assert stmt.value is None
        assert stmt.get_metadata("value_is_entry") is True

    def test_targets_with_no_action_at_all(self):
        result, stmt = _one_set("           SET IX-1 IX-2.\n")
        assert result.warnings == []
        assert stmt.targets == ["IX-1", "IX-2"]
        assert stmt.set_type is None
        assert stmt.value is None


class TestOptionalWordsOmitted:
    def test_up_without_by(self):
        result, stmt = _one_set("           SET IX-1 UP 2.\n")
        assert result.warnings == []
        assert stmt.set_type == "UP_BY"
        assert stmt.value == "2"

    def test_to_address_without_of(self):
        result, stmt = _one_set("           SET PTR TO ADDRESS LK-REC.\n")
        assert result.warnings == []
        assert stmt.set_type == "TO"
        assert stmt.value == "LK-REC"
        assert stmt.to_dict()["value_is_address_of"] is True


class TestLaterGroups:
    def test_later_group_with_up_and_no_value(self):
        result, stmt = _one_set("           SET IX-1 TO 1 IX-2 UP.\n")
        assert result.warnings == []
        assert stmt.value == "1"
        assert stmt.to_dict()["groups"] == [
            {
                "targets": ["IX-2"],
                "set_type": "UP_BY",
                "value": None,
                "value_is_address_of": False,
                "value_is_entry": False,
            }
        ]

    def test_entry_flag_is_per_group(self):
        result, stmt = _one_set(
            "           SET IX-1 TO 1 IX-2 TO ENTRY 'B' IX-1 TO 3.\n"
        )
        assert result.warnings == []
        groups = stmt.to_dict()["groups"]
        assert [(g["targets"], g["value"], g["value_is_entry"]) for g in groups] == [
            (["IX-2"], '"B"', True),
            (["IX-1"], "3", False),
        ]
        # The first group never said ENTRY.
        assert stmt.get_metadata("value_is_entry") is None

    def test_later_group_with_qualified_subscripted_target(self):
        result, stmt = _one_set("           SET IX-1 TO 1 TBL-IX OF TBL (2) TO 2.\n")
        assert result.warnings == []
        groups = stmt.to_dict()["groups"]
        assert len(groups) == 1
        assert groups[0]["targets"][0].startswith("TBL-IX OF TBL")
        assert groups[0]["value"] == "2"

    def test_group_lookahead_rejects_a_non_identifier_and_warns(self):
        # ``+`` cannot be part of a target list, so ``IX-2 + TO 2`` is not
        # another group; the leftover is reported, not silently dropped.
        result, stmt = _one_set("           SET IX-1 TO 1 IX-2 + TO 2.\n")
        assert stmt.to_dict()["groups"] == []
        assert any("Unparsed tokens starting at 'IX-2'" in w for w in result.warnings)

    def test_group_with_a_stray_paren_has_no_action(self):
        # ``IX-2 ) TO 2``: the lookahead steps over the paren and finds TO,
        # but the target list stops at the paren, so the group is recorded
        # with no action and the rest is reported.
        result, stmt = _one_set("           SET IX-1 TO 1 IX-2 ) TO 2.\n")
        assert stmt.to_dict()["groups"] == [
            {
                "targets": ["IX-2"],
                "set_type": None,
                "value": None,
                "value_is_address_of": False,
                "value_is_entry": False,
            }
        ]
        assert any("Unparsed tokens starting at ')'" in w for w in result.warnings)

    def test_group_of_twenty_targets(self):
        targets_line = "               " + "IX-2 " * 10 + "\n"
        result, stmt = _one_set(
            "           SET IX-1 TO 1\n" + targets_line * 2 + "               TO 2.\n"
        )
        assert result.warnings == []
        (group,) = stmt.to_dict()["groups"]
        assert group["targets"] == ["IX-2"] * 20
        assert group["value"] == "2"

    @pytest.mark.xfail(
        strict=True,
        reason=(
            "SetStatementParser._starts_another_group looks at most 24 tokens "
            "ahead for TO/UP/DOWN, so a valid later group with more than 24 "
            "targets is not recognised and is dropped as unparsed tokens"
        ),
    )
    def test_group_of_thirty_targets(self):
        targets_line = "               " + "IX-2 " * 10 + "\n"
        result, stmt = _one_set(
            "           SET IX-1 TO 1\n" + targets_line * 3 + "               TO 2.\n"
        )
        assert result.warnings == []
        (group,) = stmt.to_dict()["groups"]
        assert group["targets"] == ["IX-2"] * 30

    def test_group_lookahead_stops_at_a_statement_verb(self):
        # ``IX-1 IX-2 DISPLAY`` reaches a verb before any TO/UP/DOWN.
        result, stmt = _one_set(
            "           SET IX-1 TO 1 IX-2 TO 2 IX-1 IX-2 DISPLAY 'A'.\n"
        )
        assert [g["targets"] for g in stmt.to_dict()["groups"]] == [["IX-2"]]
        assert any("Unparsed tokens starting at 'IX-1'" in w for w in result.warnings)


class TestTargetListEnds:
    def test_equals_sign_is_not_an_action(self):
        # ``SET X = 5`` is not COBOL: the target list ends at ``=``, there is
        # no action, and the rest is reported rather than dropped silently.
        result, stmt = _one_set("           SET IX-1 = 5.\n")
        assert stmt.targets == ["IX-1"]
        assert stmt.set_type is None
        assert any("Unparsed tokens starting at '='" in w for w in result.warnings)

    def test_identifier_lexed_verb_ends_the_target_list(self):
        # RESUME has no TokenType of its own (it lexes as IDENTIFIER); it
        # must start the next statement, not become a SET target.
        result = _parse("           SET IX-1\n           RESUME.\n")
        assert result.warnings == []
        (stmt,) = _sets(result)
        assert stmt.targets == ["IX-1"]
        main = result.ast.procedure_division.paragraphs[0]
        assert [s.to_dict()["statement_type"] for s in main.statements] == [
            "SET",
            "RESUME",
        ]

    def test_identifier_lexed_verb_is_not_another_group(self):
        result, stmt = _one_set("           SET IX-1 TO 1 IX-2 RESUME.\n")
        assert stmt.value == "1"
        assert stmt.to_dict()["groups"] == []
        assert any("Unparsed tokens starting at 'IX-2'" in w for w in result.warnings)


class TestMissingPeriod:
    def test_next_statement_on_the_following_line(self):
        result = _parse("           SET IX-1 TO 1\n           DISPLAY 'A'.\n")
        assert result.warnings == []
        (stmt,) = _sets(result)
        assert stmt.value == "1"
        assert len(result.ast.find_all_by_type("DisplayStatement")) == 1

    def test_next_paragraph_after_a_complete_set(self):
        result = _parse(
            "           SET IX-1 TO 1\n       NEXT-PARA.\n           DISPLAY 'A'.\n"
        )
        (stmt,) = _sets(result)
        assert stmt.value == "1"
        assert _paragraph_names(result) == ["MAIN-PARA", "NEXT-PARA"]

    def test_next_paragraph_after_the_target_list(self):
        result = _parse(
            "           SET IX-1\n       NEXT-PARA.\n           DISPLAY 'A'.\n"
        )
        (stmt,) = _sets(result)
        assert stmt.targets == ["IX-1"]
        assert stmt.set_type is None
        assert _paragraph_names(result) == ["MAIN-PARA", "NEXT-PARA"]
        assert any(
            "missing its terminating period" in w and "NEXT-PARA" in w
            for w in result.warnings
        )
