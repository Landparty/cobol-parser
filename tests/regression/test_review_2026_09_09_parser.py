"""Regression tests for the 2026-09-09 parser review findings.

One test class per finding. Each pins the AST shape a reviewer reproduced
as wrong before the fix, so the defect cannot quietly return.
"""

from cobolparser import ErrorRecoveryMode, parse_cobol
from cobolparser.models.program import CobolDivision, CobolParagraph, CobolSection


def _program(data: str = "", proc: str = "", env: str = "", file_section: str = ""):
    env_block = f"{env}\n" if env else ""
    fs_block = f"FILE SECTION.\n{file_section}\n" if file_section else ""
    return (
        "IDENTIFICATION DIVISION.\n"
        "PROGRAM-ID. T.\n"
        f"{env_block}"
        "DATA DIVISION.\n"
        f"{fs_block}"
        "WORKING-STORAGE SECTION.\n"
        f"{data}\n"
        "PROCEDURE DIVISION.\n"
        "MAIN-PARA.\n"
        f"{proc}\n"
        "    STOP RUN.\n"
    )


def _parse(source: str):
    return parse_cobol(
        source, free_form=True, error_recovery=ErrorRecoveryMode.COLLECT_ALL
    )


def _ws_items(result):
    for div in result.ast.divisions:
        for sec in div.sections:
            if getattr(sec, "section_name", "").upper().startswith("WORKING"):
                return sec.data_items
    raise AssertionError("no WORKING-STORAGE section")


def _top_statements(result):
    out = []
    for s in result.ast.get_all_statements():
        if s.parent is None or isinstance(
            s.parent, (CobolParagraph, CobolSection, CobolDivision)
        ):
            out.append(s)
    return out


def _stmt(result, statement_type: str):
    matches = [s for s in _top_statements(result) if s.statement_type == statement_type]
    assert matches, f"no top-level {statement_type} statement"
    return matches[0]


_DATA = (
    "01 A PIC 9.\n01 B PIC 9.\n01 C PIC 9.\n01 D PIC X(10).\n"
    "01 I PIC 9.\n01 J PIC 9.\n01 X PIC X.\n01 FLAG PIC X.\n"
    "   88 FLAG-ON VALUE 'Y'.\n"
    "01 TBL.\n   05 TE OCCURS 5 INDEXED BY TI PIC X.\n"
)

_FILES_ENV = (
    "ENVIRONMENT DIVISION.\nINPUT-OUTPUT SECTION.\nFILE-CONTROL.\n"
    "    SELECT F1 ASSIGN TO F1.\n    SELECT F2 ASSIGN TO F2.\n"
    "    SELECT SF ASSIGN TO SF."
)
_FILES_FS = (
    "FD F1.\n01 R1 PIC X(80).\nFD F2.\n01 R2 PIC X(80).\nSD SF.\n01 SR PIC X(80)."
)


def _proc(proc: str):
    return _parse(_program(_DATA, "    " + proc, _FILES_ENV, _FILES_FS))


class TestFinding01Level77IsTopLevel:
    def test_77_after_group_is_a_sibling_not_a_grandchild(self):
        result = _parse(
            _program(
                "01 REC.\n   05 Y1 PIC X(10).\n"
                "77 STANDALONE PIC 9(3) VALUE 5.\n77 S2 PIC X.\n01 NEXT-ONE PIC X."
            )
        )
        items = _ws_items(result)
        assert [(i.name, i.level) for i in items] == [
            ("REC", 1),
            ("STANDALONE", 77),
            ("S2", 77),
            ("NEXT-ONE", 1),
        ]
        y1 = items[0].children[0]
        assert y1.name == "Y1"
        assert [c.name for c in y1.children if hasattr(c, "level")] == []

    def test_88_after_77_attaches_to_the_77(self):
        result = _parse(
            _program("01 REC.\n   05 Y1 PIC X.\n77 SW PIC X.\n   88 SW-ON VALUE 'Y'.")
        )
        items = _ws_items(result)
        sw = items[1]
        assert sw.level == 77
        assert [c["name"] for c in sw.to_dict()["condition_names"]] == ["SW-ON"]


class TestFinding02ReturnAtEndStopsAtSentencePeriod:
    def test_following_statements_are_not_swallowed(self):
        result = _proc("RETURN SF AT END MOVE 'Y' TO A.\n    DISPLAY 'AFTER'.")
        ret = _stmt(result, "RETURN")
        assert [s.statement_type for s in ret.at_end_clause] == ["MOVE"]
        assert [s.statement_type for s in _top_statements(result)] == [
            "RETURN",
            "DISPLAY",
            "STOP",
        ]

    def test_not_at_end_and_end_return(self):
        result = _proc(
            "RETURN SF INTO D AT END MOVE 'Y' TO A NOT AT END MOVE 'N' TO A\n"
            "    END-RETURN\n    DISPLAY 'AFTER'."
        )
        ret = _stmt(result, "RETURN")
        assert [s.statement_type for s in ret.at_end_clause] == ["MOVE"]
        assert [s.statement_type for s in ret.not_at_end_clause] == ["MOVE"]
        assert [s.statement_type for s in _top_statements(result)][:2] == [
            "RETURN",
            "DISPLAY",
        ]


class TestFinding03UsageDisplay:
    def test_usage_is_display_usage_display_and_bare_display(self):
        result = _parse(
            _program(
                "01 Q2 PIC X(3) USAGE IS DISPLAY.\n"
                "01 Q3 PIC X(3) USAGE DISPLAY.\n"
                "01 Q4 PIC X(3) DISPLAY.\n"
                "01 Q5 PIC S9(4) USAGE IS DISPLAY SIGN IS LEADING SEPARATE."
            )
        )
        assert result.warnings == []
        items = {i.name: i for i in _ws_items(result)}
        for name in ("Q2", "Q3", "Q4", "Q5"):
            assert items[name].usage == "DISPLAY", name
            assert items[name].picture_clause.pattern.startswith(("X", "S9"))
        assert items["Q5"].sign_clause == "LEADING SEPARATE"


class TestFinding04SignClauseWithoutSignWord:
    def test_leading_separate_is_a_sign_clause_not_picture(self):
        result = _parse(
            _program(
                "01 M1 PIC S999 LEADING SEPARATE.\n"
                "01 M2 PIC S999 TRAILING.\n"
                "01 M3 PIC S999 SIGN LEADING.\n"
                "01 M4 LEADING SEPARATE.\n   05 M4A PIC S9."
            )
        )
        assert result.warnings == []
        items = {i.name: i for i in _ws_items(result)}
        assert items["M1"].picture_clause.pattern == "S999"
        assert items["M1"].sign_clause == "LEADING SEPARATE"
        assert items["M2"].picture_clause.pattern == "S999"
        assert items["M2"].sign_clause == "TRAILING"
        assert items["M3"].sign_clause == "LEADING"
        assert items["M4"].sign_clause == "LEADING SEPARATE"
        assert items["M4"].children[0].name == "M4A"


class TestFinding05InspectSubscriptedTarget:
    def test_reference_modified_target_keeps_tallying(self):
        result = _proc("INSPECT D(1:5) TALLYING A FOR ALL 'X'.")
        ins = _stmt(result, "INSPECT")
        assert ins.target == "D ( 1 : 5 )"
        assert ins.inspect_type == "TALLYING"
        assert ins.tallying_clauses == [
            {
                "counter": "A",
                "for_type": "ALL",
                "value": "X",
                "before": None,
                "after": None,
            }
        ]

    def test_subscripted_target_keeps_replacing(self):
        result = _proc("INSPECT D(I) REPLACING ALL 'A' BY 'B'.")
        ins = _stmt(result, "INSPECT")
        assert ins.target == "D ( I )"
        assert ins.inspect_type == "REPLACING"
        assert [(c["from_value"], c["to_value"]) for c in ins.replacing_clauses] == [
            ("A", "B")
        ]


class TestFinding06InspectFigurativesAndRepeatedPairs:
    def test_figurative_constant_operands(self):
        result = _proc("INSPECT D REPLACING LEADING SPACES BY ZEROS.")
        ins = _stmt(result, "INSPECT")
        clause = ins.replacing_clauses[0]
        assert (clause["replace_type"], clause["from_value"], clause["to_value"]) == (
            "LEADING",
            "SPACES",
            "ZEROS",
        )
        result = _proc("INSPECT D TALLYING A FOR LEADING SPACES.")
        assert _stmt(result, "INSPECT").tallying_clauses[0]["value"] == "SPACES"

    def test_second_pair_under_the_same_all(self):
        result = _proc("INSPECT D REPLACING ALL 'A' BY 'B' 'C' BY 'D'.")
        ins = _stmt(result, "INSPECT")
        assert [
            (c["replace_type"], c["from_value"], c["to_value"])
            for c in ins.replacing_clauses
        ] == [("ALL", "A", "B"), ("ALL", "C", "D")]

    def test_tallying_second_counter_still_a_counter(self):
        result = _proc("INSPECT D TALLYING A FOR ALL 'X' B FOR ALL 'Y'.")
        ins = _stmt(result, "INSPECT")
        assert [(c["counter"], c["value"]) for c in ins.tallying_clauses] == [
            ("A", "X"),
            ("B", "Y"),
        ]


class TestFinding07StringUnstringOperands:
    def test_string_reference_modified_operands(self):
        result = _proc("STRING A(1:2) DELIMITED BY SIZE INTO D(3:5).")
        st = _stmt(result, "STRING")
        assert st.operands == ["A ( 1 : 2 )"]
        assert st.into_target == "D ( 3 : 5 )"
        assert st.delimiters == ["SIZE"]

    def test_string_subscripted_operand_and_with_pointer(self):
        result = _proc("STRING A(I) DELIMITED BY SIZE INTO D WITH POINTER J.")
        st = _stmt(result, "STRING")
        assert st.operands == ["A ( I )"]
        assert st.pointer_variable == "J"

    def test_string_bare_pointer(self):
        result = _proc("STRING A DELIMITED BY ',' INTO D POINTER I.")
        st = _stmt(result, "STRING")
        assert st.operands == ["A"]
        assert st.into_target == "D"
        assert st.pointer_variable == "I"

    def test_unstring_subscripted_targets_and_source(self):
        result = _proc("UNSTRING D(1:5) DELIMITED BY ',' INTO A B.")
        un = _stmt(result, "UNSTRING")
        assert un.source_operand == "D ( 1 : 5 )"
        assert [t["target"] for t in un.into_targets] == ["A", "B"]
        result = _proc("UNSTRING D INTO A(I) B(1:2).")
        un = _stmt(result, "UNSTRING")
        assert [t["target"] for t in un.into_targets] == ["A ( I )", "B ( 1 : 2 )"]


def _condition(result):
    return _stmt(result, "IF").condition.to_dict()


def _strip(d):
    if isinstance(d, dict):
        return {
            k: _strip(v)
            for k, v in d.items()
            if k not in ("node_type", "location", "metadata", "operands")
            and v not in (None, [], {})
        }
    return d


def _cmp(op, left, right):
    return {
        "expression_type": "COMPARISON",
        "operator": op,
        "left_operand": left,
        "right_operand": right,
        "condition_type": "COMPARISON",
    }


class TestFinding08ConditionTrees:
    def test_not_before_parenthesised_compound(self):
        cond = _strip(_condition(_proc("IF NOT (A = 1 AND B = 2) DISPLAY 'X' END-IF.")))
        assert cond == {
            "expression_type": "LOGICAL",
            "operator": "NOT",
            "left_condition": {
                "expression_type": "LOGICAL",
                "operator": "AND",
                "left_condition": _cmp("EQUAL", "A", "1"),
                "right_condition": _cmp("EQUAL", "B", "2"),
            },
        }

    def test_not_before_simple_relation_folds_into_operator(self):
        cond = _strip(_condition(_proc("IF NOT A = 1 DISPLAY 'X' END-IF.")))
        assert cond == _cmp("NOT_EQUAL", "A", "1")
        cond = _strip(_condition(_proc("IF NOT A > B AND C = 1 DISPLAY 'X' END-IF.")))
        assert cond["operator"] == "AND"
        assert cond["left_condition"] == _cmp("LESS_OR_EQUAL", "A", "B")

    def test_not_before_condition_name_is_a_unary_node(self):
        cond = _strip(_condition(_proc("IF NOT FLAG-ON DISPLAY 'X' END-IF.")))
        assert cond["operator"] == "NOT"
        assert cond["left_condition"]["operator"] == "CONDITION_NAME"
        assert cond["left_condition"]["left_operand"] == "FLAG-ON"
        assert "right_condition" not in cond  # None, stripped

    def test_abbreviated_combined_condition_literals(self):
        cond = _strip(_condition(_proc("IF A = 1 OR 2 OR 3 DISPLAY 'X' END-IF.")))
        assert cond == {
            "expression_type": "LOGICAL",
            "operator": "OR",
            "left_condition": {
                "expression_type": "LOGICAL",
                "operator": "OR",
                "left_condition": _cmp("EQUAL", "A", "1"),
                "right_condition": _cmp("EQUAL", "A", "2"),
            },
            "right_condition": _cmp("EQUAL", "A", "3"),
        }

    def test_abbreviated_combined_condition_operator_led(self):
        cond = _strip(_condition(_proc("IF A > 1 AND < 5 DISPLAY 'X' END-IF.")))
        assert cond["left_condition"] == _cmp("GREATER", "A", "1")
        assert cond["right_condition"] == _cmp("LESS", "A", "5")

    def test_bare_identifier_leg_stays_a_condition_name(self):
        cond = _strip(_condition(_proc("IF A = 1 OR FLAG-ON DISPLAY 'X' END-IF.")))
        assert cond["right_condition"]["operator"] == "CONDITION_NAME"


class TestFinding09CloseForRemoval:
    def test_for_removal_is_an_option_not_a_file(self):
        result = _proc("CLOSE F1 REEL FOR REMOVAL F2 UNIT.")
        cl = _stmt(result, "CLOSE")
        assert cl.file_names == ["F1", "F2"]
        assert cl.close_options["F1"]["reel"] is True
        assert cl.close_options["F1"]["for_removal"] is True
        assert cl.close_options["F2"]["unit"] is True
        assert cl.close_options["F2"]["for_removal"] is False


class TestFinding10SelectorAndSearchConditionLiterals:
    def test_evaluate_identifier_selector_is_marked(self):
        result = _proc(
            "EVALUATE A WHEN B DISPLAY 'ID' WHEN 'B' DISPLAY 'LIT' "
            "WHEN 1 DISPLAY 'N' END-EVALUATE."
        )
        ev = _stmt(result, "EVALUATE")
        sels = [wc.selectors[0] for wc in ev.when_clauses]
        assert sels[0] == {"type": "Literal", "value": "B", "identifier": True}
        assert sels[1] == {"type": "Literal", "value": "B"}
        assert sels[2] == {"type": "Literal", "value": "1"}

    def test_search_when_condition_requotes_string_literals(self):
        result = _proc(
            "SEARCH TBL WHEN TE(I) = 'X' DISPLAY 'F' WHEN TE(I) = X DISPLAY 'G' "
            "END-SEARCH."
        )
        se = _stmt(result, "SEARCH")
        assert [wc["condition"] for wc in se.when_clauses] == [
            "TE ( I ) = 'X'",
            "TE ( I ) = X",
        ]


class TestFinding11DataEntryTolerance:
    def test_name_on_the_line_after_its_level_number(self):
        result = _parse(
            _program("01 SP1. 02 SP2. 03 SP3 PIC XX. 02\n   SP4. 03 SP5 PIC X(8).")
        )
        assert result.warnings == []
        sp1 = _ws_items(result)[0]
        assert [c.name for c in sp1.children] == ["SP2", "SP4"]
        assert [c.name for c in sp1.children[1].children] == ["SP5"]

    def test_comma_and_semicolon_separators(self):
        result = _parse(
            _program(
                "77 TEMP; PIC S999999.\n"
                "01 G.\n"
                "   02 X OCCURS 15 TIMES, INDEXED BY IN1, INDEX1, USAGE IS COMP PIC 9.\n"
                "   02 Y PIC X, VALUE 'A'.\n"
                "   02 Z PIC ZZ,ZZ9; OCCURS 10 TIMES."
            )
        )
        assert result.warnings == []
        items = {i.name: i for i in _ws_items(result)}
        assert items["TEMP"].picture_clause.pattern == "S999999"
        x, y, z = items["G"].children
        assert x.occurs_clause.index_names == ["IN1", "INDEX1"]
        assert x.usage == "COMP"
        assert x.picture_clause.pattern == "9"
        assert y.picture_clause.pattern == "X"
        assert y.value_clause == '"A"'
        assert z.picture_clause.pattern == "ZZ,ZZ9"
        assert z.occurs_clause.max_times == 10


class TestFinding12CheapExtras:
    def test_set_to_entry_keeps_the_entry_name(self):
        result = _proc("SET I TO ENTRY 'SUB1'.")
        assert result.warnings == []
        st = _stmt(result, "SET")
        assert st.targets == ["I"]
        assert st.value == "SUB1"
        assert st.get_metadata("value_is_entry") is True

    def test_set_entry_form_does_not_leak_into_a_later_group(self):
        # Regression: _entry_form used to be reset only before the FIRST
        # group's _parse_action call, so a later group in the same SET
        # statement inherited an earlier group's ENTRY-ness even when its
        # own value is an ordinary identifier.
        result = _proc("SET I TO ENTRY 'SUB1' J TO 2.")
        st = _stmt(result, "SET")
        assert st.value == "SUB1"
        assert st.get_metadata("value_is_entry") is True
        (group,) = st.groups
        assert group["targets"] == ["J"]
        assert group["value"] == "2"
        assert group["value_is_entry"] is False

    def test_set_entry_form_is_tracked_per_group_not_just_the_first(self):
        # The other direction: a SECOND group's own ENTRY value must be
        # recorded on that group, not silently dropped.
        result = _proc("SET I TO 1 J TO ENTRY 'SUB2'.")
        st = _stmt(result, "SET")
        assert st.value == "1"
        assert st.get_metadata("value_is_entry") is None
        (group,) = st.groups
        assert group["targets"] == ["J"]
        assert group["value"] == "SUB2"
        assert group["value_is_entry"] is True

    def test_perform_thru_qualifier(self):
        result = _proc("PERFORM P1 IN S1 THRU P2 OF S1.")
        assert result.warnings == []
        pf = _stmt(result, "PERFORM")
        assert (pf.target_paragraph, pf.thru_paragraph) == ("P1", "P2")
        assert pf.get_metadata("target_qualifier") == "S1"
        assert pf.get_metadata("thru_qualifier") == "S1"


class TestFinding13ConditionNameValues:
    def test_values_are_and_values(self):
        result = _parse(
            _program(
                "01 FLAG PIC X.\n"
                "   88 V1 VALUES ARE 'A' THRU 'F'.\n"
                "   88 V2 VALUES 'A' 'B'.\n"
                "   88 V3 VALUE IS 'A'."
            )
        )
        names = {
            c["name"]: c for c in _ws_items(result)[0].to_dict()["condition_names"]
        }
        assert names["V1"]["values"] == ["A", "THROUGH:F"]
        assert names["V2"]["values"] == ["A", "B"]
        assert names["V3"]["values"] == ["A"]
