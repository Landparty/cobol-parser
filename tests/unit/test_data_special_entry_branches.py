"""Level-88, level-66 and data-division EXEC SQL entries: branch gaps.

``SpecialEntryParser`` (``parsers/divisions/data_special_entries``) driven
through ``CobolParser`` with real WORKING-STORAGE entries. Each test checks
the resulting ``ConditionNameItem`` / ``RenamesItem`` / ``ExecSQLStatement``
and the warnings: VALUE ALL forms, figurative and signed values and range
ends, ``;`` separators, the ``WHEN SET TO FALSE`` phrase in its short and
split-across-lines forms (and the forms it must not take), the
dropped-content warnings, RENAMES qualifiers and line breaks, and EXEC SQL
blocks that hold nothing. Three behaviours that lose source content are
pinned as strict xfails.
"""

import pytest

from cobolparser import CobolParser, ErrorRecoveryMode

PRE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. SPECIAL.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
"""
POST = """\
       PROCEDURE DIVISION.
       MAIN-PARA.
           STOP RUN.
"""


def _parse(body: str, post: str = POST):
    parser = CobolParser(error_recovery=ErrorRecoveryMode.COLLECT_ALL)
    result = parser.parse(PRE + body + post, "special.cbl")
    assert result.ast is not None
    assert result.errors == []
    return result


def _conditions(result) -> dict:
    return {c.name: c for c in result.ast.find_all_by_type("ConditionNameItem")}


def _renames(result) -> dict:
    return {r.name: r for r in result.ast.find_all_by_type("RenamesItem")}


def _ws_names(result) -> list[str]:
    section = result.ast.data_division.get_section_by_name("WORKING-STORAGE")
    return [item.name for item in section.data_items]


def _values(cond) -> list[tuple[str, str | None]]:
    return list(zip(cond.values, cond.value_kinds, strict=True))


class TestConditionValues:
    def test_value_all_and_figurative_values(self):
        result = _parse("""\
       01  A                   PIC X(4).
           88  A-STARS         VALUE ALL '*'.
           88  A-BLANK         VALUE ALL SPACES.
           88  A-EMPTY         VALUE SPACES LOW-VALUE.
""")
        assert result.warnings == []
        conds = _conditions(result)
        assert _values(conds["A-STARS"]) == [('ALL "*"', "all")]
        assert _values(conds["A-BLANK"]) == [("ALL SPACES", "all")]
        assert _values(conds["A-EMPTY"]) == [
            ("SPACES", "figurative"),
            ("LOW-VALUE", "figurative"),
        ]

    def test_hex_literal_keeps_its_prefix(self):
        result = _parse("       01  A PIC X.\n           88  A-HEX VALUE X'C1'.\n")
        assert result.warnings == []
        assert _values(_conditions(result)["A-HEX"]) == [("X'C1'", "string")]

    def test_bare_all_is_kept_as_one_value(self):
        # ``VALUE ALL`` with no operand: ALL is recorded as written rather
        # than pairing with something that is not its operand.
        conds = _conditions(
            _parse("       01  A PIC X.\n           88  A1 VALUE ALL.\n")
        )
        assert conds["A1"].values == ["ALL"]

    def test_semicolon_and_comma_separate_values(self):
        result = _parse(
            "       01  A PIC X.\n           88  A1 VALUES ARE 'A'; 'B', 'C'.\n"
        )
        assert result.warnings == []
        assert _conditions(result)["A1"].values == ["A", "B", "C"]

    def test_figurative_range(self):
        result = _parse(
            "       01  A PIC X.\n           88  A1 VALUE LOW-VALUE THRU HIGH-VALUE.\n"
        )
        assert result.warnings == []
        assert _values(_conditions(result)["A1"]) == [
            ("LOW-VALUE", "figurative"),
            ("THROUGH:HIGH-VALUE", "figurative"),
        ]

    def test_signed_values_and_signed_range_end(self):
        result = _parse("""\
       01  N                   PIC S99.
           88  N-NEG           VALUE -5.
           88  N-RANGE         VALUE -9 THRU -1.
           88  N-SPLIT         VALUE 1 THRU
                               5.
""")
        assert result.warnings == []
        conds = _conditions(result)
        assert conds["N-NEG"].values == ["-5"]
        assert conds["N-RANGE"].values == ["-9", "THROUGH:-1"]
        assert conds["N-SPLIT"].values == ["1", "THROUGH:5"]

    def test_sign_without_a_number_ends_the_list_and_warns(self):
        result = _parse("       01  A PIC X.\n           88  A1 VALUE - 'A'.\n")
        assert _conditions(result)["A1"].values == []
        assert any("Unparsed token '-'" in w and "'A1'" in w for w in result.warnings)

    def test_signed_range_end_without_a_number_is_reported(self):
        result = _parse("       01  N PIC S9.\n           88  N1 VALUE -1 THRU - X.\n")
        assert _conditions(result)["N1"].values == ["-1"]
        assert any("Unparsed token" in w and "'N1'" in w for w in result.warnings)

    def test_non_literal_range_end_is_reported(self):
        result = _parse("       01  N PIC 9.\n           88  N1 VALUE 1 THRU X.\n")
        assert _conditions(result)["N1"].values == ["1"]
        assert any("Unparsed token 'X'" in w for w in result.warnings)

    def test_every_word_on_its_own_line(self):
        result = _parse("""\
       01  A PIC X.
           88
               A1
               VALUE
               IS 'Y'.
""")
        assert result.warnings == []
        assert _conditions(result)["A1"].values == ["Y"]

    def test_condition_name_without_value_clause(self):
        result = _parse(
            "       01  A PIC X.\n           88  A1.\n           88  A2 VALUE 'N'.\n"
        )
        conds = _conditions(result)
        assert conds["A1"].values == []
        assert conds["A2"].values == ["N"]


class TestWhenSetToFalse:
    def test_bare_false_phrase(self):
        result = _parse("       01  N PIC 9.\n           88  N1 VALUE 1 FALSE 0.\n")
        assert result.warnings == []
        assert _conditions(result)["N1"].false_value == "0"

    def test_phrase_split_across_lines_with_signed_literal(self):
        result = _parse("""\
       01  N                   PIC S9.
           88  N1              VALUE 1
                               WHEN
                               SET TO FALSE IS -1.
""")
        assert result.warnings == []
        assert _conditions(result)["N1"].false_value == "-1"

    def test_when_false_without_set_to_and_figurative_literal(self):
        result = _parse(
            "       01  A PIC X.\n           88  A1 VALUE 'Y' WHEN FALSE IS SPACES.\n"
        )
        assert result.warnings == []
        assert _conditions(result)["A1"].false_value == "SPACES"

    def test_sign_without_a_number_is_not_a_false_value(self):
        result = _parse(
            "       01  N PIC S9.\n           88  N1 VALUE 1 WHEN SET TO FALSE - X.\n"
        )
        assert _conditions(result)["N1"].false_value is None
        assert any("Unparsed token 'WHEN'" in w for w in result.warnings)

    def test_data_name_is_not_a_false_value(self):
        result = _parse(
            "       01  N PIC 9.\n           88  N1 VALUE 1 WHEN SET TO FALSE IS X.\n"
        )
        assert _conditions(result)["N1"].false_value is None
        assert any("Unparsed token 'WHEN'" in w for w in result.warnings)

    def test_when_not_followed_by_false(self):
        result = _parse("       01  N PIC 9.\n           88  N1 VALUE 1 WHEN SET X.\n")
        assert _conditions(result)["N1"].false_value is None
        assert any("Unparsed token 'WHEN'" in w for w in result.warnings)


class TestDroppedContentWarnings:
    def test_unparsed_word_after_values(self):
        result = _parse("       01  A PIC X.\n           88  A1 VALUE 'Y' FOO.\n")
        assert _conditions(result)["A1"].values == ["Y"]
        assert any(
            "Unparsed token 'FOO' at line 6 in condition-name 'A1'" in w
            for w in result.warnings
        )

    def test_unparsed_symbol_on_the_next_line(self):
        result = _parse(
            "       01  A PIC X.\n           88  A1 VALUE 'Y'\n           =.\n"
        )
        assert _conditions(result)["A1"].values == ["Y"]
        assert any("Unparsed token '='" in w for w in result.warnings)

    def test_missing_period_before_section_header(self):
        result = _parse("""\
       01  A PIC X.
           88  A1 VALUE 'Y'
       LINKAGE SECTION.
       01  L PIC X.
""")
        assert _conditions(result)["A1"].values == ["Y"]
        assert result.warnings == [
            "Data item 'A1' missing its terminating period: a period was "
            "assumed before 'LINKAGE SECTION' at line 7"
        ]
        linkage = result.ast.data_division.get_section_by_name("LINKAGE")
        assert [d.name for d in linkage.data_items] == ["L"]

    def test_missing_period_before_procedure_division(self):
        result = _parse("       01  A PIC X.\n           88  A1 VALUE 'Y'\n")
        assert result.warnings == [
            "Data item 'A1' missing its terminating period: a period was "
            "assumed before 'PROCEDURE DIVISION' at line 7"
        ]

    @pytest.mark.xfail(
        strict=True,
        reason=(
            "SpecialEntryParser.parse_condition_name_item skips every token "
            "before VALUE without a warning, so a misspelt VALUE keyword "
            "(88 A1 VALU 'Y'.) drops the value list silently"
        ),
    )
    def test_misspelt_value_keyword_is_reported(self):
        result = _parse(
            "       01  A PIC X.\n           88  A1 VALU 'Y'.\n           88  A2 VALUE 'N'.\n"
        )
        assert result.warnings, "the dropped 'VALU 'Y'' left no trace"

    @pytest.mark.xfail(
        strict=True,
        reason=(
            "a level-88 value list with no terminating period takes the next "
            "entry's level number (01/05/77, lexed as LEVEL_NUMBER) as a "
            "value, and that whole entry is then dropped"
        ),
    )
    def test_missing_period_does_not_swallow_the_next_entry(self):
        result = _parse(
            "       01  A PIC X.\n           88  A1 VALUE 'Y'\n       01  B PIC X.\n"
        )
        assert _conditions(result)["A1"].values == ["Y"]
        assert _ws_names(result) == ["A", "B"]


class TestRenames:
    BASE = """\
       01  REC.
           05  A               PIC X.
           05  B               PIC X.
"""

    def test_qualified_operands(self):
        result = _parse(self.BASE + "       66  R1 RENAMES A OF REC THRU B IN REC.\n")
        assert result.warnings == []
        r1 = _renames(result)["R1"]
        assert (r1.renames_from, r1.renames_through) == ("A", "B")
        assert r1.renames_from_qualifiers == ["REC"]
        assert r1.renames_through_qualifiers == ["REC"]

    def test_every_word_on_its_own_line(self):
        result = _parse(self.BASE + """\
       66
           R2
           RENAMES
           A
           OF
           REC
           THROUGH
           B.
""")
        assert result.warnings == []
        r2 = _renames(result)["R2"]
        assert (r2.renames_from, r2.renames_through) == ("A", "B")
        assert r2.renames_from_qualifiers == ["REC"]

    def test_thru_with_no_operand(self):
        result = _parse(self.BASE + "       66  R3 RENAMES A OF REC THRU.\n")
        r3 = _renames(result)["R3"]
        assert (r3.renames_from, r3.renames_through) == ("A", None)
        assert r3.renames_from_qualifiers == ["REC"]

    def test_of_not_followed_by_a_data_name_is_not_a_qualifier(self):
        result = _parse(self.BASE + "       66  R4 RENAMES A OF\n           'X'.\n")
        r4 = _renames(result)["R4"]
        assert r4.renames_from == "A"
        assert r4.renames_from_qualifiers == []

    def test_renames_with_no_operand_records_nothing(self):
        result = _parse(self.BASE + "       66  R5 RENAMES.\n       01  C PIC X.\n")
        assert "R5" not in _renames(result)
        assert _ws_names(result) == ["REC", "C"]

    @pytest.mark.xfail(
        strict=True,
        reason=(
            "SpecialEntryParser.parse_renames_item returns None without a "
            "warning when the RENAMES keyword is missing, so '66 R1 B.' "
            "vanishes from the AST with no trace"
        ),
    )
    def test_missing_renames_keyword_is_reported(self):
        result = _parse(self.BASE + "       66  R1 B.\n       01  C PIC X.\n")
        assert _ws_names(result) == ["REC", "C"]
        assert result.warnings, "the dropped level-66 entry left no trace"


class TestEntryCutOffAtEndOfSource:
    """A program that ends in the middle of a special entry still parses."""

    @pytest.mark.parametrize("tail", ["           88", "       66", "       66  R1"])
    def test_level_number_with_nothing_after_it(self, tail):
        result = _parse("       01  A PIC X.\n" + tail, post="")
        assert _ws_names(result) == ["A"]
        assert result.ast.find_all_by_type("ConditionNameItem") == []
        assert result.ast.find_all_by_type("RenamesItem") == []

    def test_exec_sql_with_nothing_after_it(self):
        result = _parse("       01  A PIC X.\n           EXEC", post="")
        assert _ws_names(result) == ["A"]
        assert result.ast.find_all_by_type("ExecSQLStatement") == []


class TestExecSqlInData:
    def test_empty_block_is_dropped_and_next_block_kept(self):
        result = _parse("""\
       01  A PIC X.
           EXEC SQL END-EXEC.
           EXEC
               SQL INCLUDE SQLCA
           END-EXEC.
       01  B PIC X.
""")
        sql = result.ast.find_all_by_type("ExecSQLStatement")
        assert [s.sql_text for s in sql] == ["INCLUDE SQLCA"]
        assert _ws_names(result) == ["A", "B"]
