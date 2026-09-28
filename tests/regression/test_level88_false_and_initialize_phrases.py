"""Regression: two IBM Enterprise COBOL clauses that were silently dropped.

- Level-88 ``VALUE ... WHEN SET TO FALSE [IS] literal`` -- skipped to the
  period with no warning; now recorded as ``ConditionNameItem.false_value``.
- ``INITIALIZE ... {ALL | category} TO VALUE [THEN REPLACING ...]
  [THEN TO DEFAULT]`` (Enterprise COBOL 6) -- warned "Unparsed tokens" and
  dropped; now recorded as ``InitializeStatement.to_value_category`` /
  ``.to_default``.
"""

from __future__ import annotations

import pytest

from cobolparser import parse_cobol


def _program(ws: list[str], proc: list[str]) -> str:
    return "\n".join(
        [
            "       IDENTIFICATION DIVISION.",
            "       PROGRAM-ID. T.",
            "       DATA DIVISION.",
            "       WORKING-STORAGE SECTION.",
            *ws,
            "       PROCEDURE DIVISION.",
            *proc,
            "           STOP RUN.",
            "",
        ]
    )


class TestLevel88WhenSetToFalse:
    def _conditions(self, ws: list[str]) -> dict[str, dict]:
        result = parse_cobol(_program(ws, ["           SET OK TO FALSE"]))
        assert result.errors == []
        assert result.warnings == []
        return {
            c.name: c.to_dict()
            for c in result.ast.find_all_by_type("ConditionNameItem")
        }

    @pytest.mark.parametrize(
        ("clause", "values", "false_value"),
        [
            ("VALUE 'Y' WHEN SET TO FALSE IS 'N'", ["Y"], "N"),
            ("VALUE 'Y' 'Z' WHEN SET TO FALSE 'N'", ["Y", "Z"], "N"),
            ("VALUES ARE 'Y' WHEN FALSE IS SPACE", ["Y"], "SPACE"),
            ("VALUE 'Y' WHEN TO FALSE 'N'", ["Y"], "N"),
        ],
    )
    def test_alphanumeric(self, clause, values, false_value):
        conds = self._conditions(["       01 F PIC X.", f"          88 OK {clause}."])
        assert conds["OK"]["values"] == values
        assert conds["OK"]["false_value"] == false_value

    def test_numeric_signed_and_following_entry_intact(self):
        conds = self._conditions(
            [
                "       01 G PIC S9.",
                "          88 OK VALUE -1 THRU -9 WHEN SET TO FALSE IS -0.",
                "          88 ZERO-VAL VALUE 0.",
            ]
        )
        assert conds["OK"]["values"] == ["-1", "THROUGH:-9"]
        assert conds["OK"]["false_value"] == "-0"
        assert conds["ZERO-VAL"]["values"] == ["0"]
        assert conds["ZERO-VAL"]["false_value"] is None

    def test_absent_phrase_is_none(self):
        conds = self._conditions(["       01 F PIC X.", "          88 OK VALUE 'Y'."])
        assert conds["OK"]["false_value"] is None


class TestInitializeEnterprise6Phrases:
    def _initialize(self, proc: list[str]) -> tuple[dict, int]:
        result = parse_cobol(
            _program(
                [
                    "       01 G.",
                    "          05 H PIC X VALUE 'Z'.",
                    "          05 N PIC 9 VALUE 1.",
                ],
                proc,
            )
        )
        assert result.errors == []
        assert result.warnings == []
        (stmt,) = result.ast.find_all_by_type("InitializeStatement")
        return stmt.to_dict(), len(result.ast.find_all_by_type("DisplayStatement"))

    def test_all_to_value_then_to_default(self):
        d, _ = self._initialize(
            ["           INITIALIZE G ALL TO VALUE THEN TO DEFAULT"]
        )
        assert d["targets"] == ["G"]
        assert d["to_value_category"] == "ALL"
        assert d["to_default"] is True

    def test_full_form(self):
        d, _ = self._initialize(
            [
                "           INITIALIZE G WITH FILLER NUMERIC TO VALUE",
                "               THEN REPLACING ALPHANUMERIC DATA BY SPACE",
                "               THEN TO DEFAULT.",
            ]
        )
        assert d["targets"] == ["G"]
        assert d["with_filler"] is True
        assert d["to_value_category"] == "NUMERIC"
        assert d["replacing_clauses"] == [
            {"category": "ALPHANUMERIC", "by_value": "SPACE"}
        ]
        assert d["to_default"] is True

    def test_several_targets_to_value_only(self):
        d, _ = self._initialize(["           INITIALIZE G, H ALL TO VALUE."])
        assert d["targets"] == ["G", "H"]
        assert d["to_value_category"] == "ALL"
        assert d["to_default"] is False

    def test_to_default_without_then_and_next_statement(self):
        d, displays = self._initialize(
            ["           INITIALIZE G TO DEFAULT", "           DISPLAY 'X'"]
        )
        assert d["to_value_category"] is None
        assert d["to_default"] is True
        assert displays == 1

    def test_plain_form_unchanged(self):
        d, _ = self._initialize(["           INITIALIZE G REPLACING NUMERIC BY 0."])
        assert d["replacing_clauses"] == [{"category": "NUMERIC", "by_value": "0"}]
        assert d["to_value_category"] is None
        assert d["to_default"] is False
