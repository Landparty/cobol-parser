"""Tests for BusinessRuleExtractor (business_rules.py).

Every program here is a real parse, so what is pinned is what the extractor
makes of the AST the parser actually builds -- selector literals arriving
unquoted, level-88 values stored with their quotes stripped, and so on.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from cobolparser.analysis.business_rules import (
    RULE_CALCULATION,
    RULE_DECISION,
    RULE_VALIDATION,
    BusinessRuleExtractor,
    BusinessRuleReport,
)
from cobolparser.parser import parse_cobol

HEADER = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. RULES.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT POLICY-FILE ASSIGN TO POLFILE
               FILE STATUS IS WS-POLICY-STATUS.
       DATA DIVISION.
       FILE SECTION.
       FD  POLICY-FILE.
       01  POLICY-REC.
           05  POL-ID              PIC X(10).
           05  POL-AGE             PIC 9(3).
           05  POL-TYPE            PIC X.
               88  POL-AUTO        VALUE 'A'.
               88  POL-HOME        VALUE 'H'.
               88  POL-COMMERCIAL  VALUE 'C' 'D'.
               88  POL-SPECIAL     VALUE 'P' THRU 'S'.
           05  POL-TIER            PIC 9.
               88  POL-TIER-LOW    VALUE 1 THRU 3.
           05  POL-PREMIUM         PIC 9(7)V99.
           05  POL-CLAIMS          PIC 9(3).
       WORKING-STORAGE SECTION.
       01  WS-POLICY-STATUS        PIC XX.
       01  WS-READ-SW              PIC X VALUE 'N'.
           88  NO-MORE-POLICIES    VALUE 'Y'.
       01  WS-COUNT                PIC 9(7) VALUE 0.
       01  WS-RATE                 PIC V999.
       01  WS-DISCOUNT             PIC 9(7)V99.
       01  WS-TOTAL                PIC 9(9)V99.
       01  WS-NET                  PIC 9(7)V99.
       01  WS-SHARE                PIC 9(7)V99.
       01  WS-LEFT                 PIC 9(7)V99.
       01  WS-MSG                  PIC X(40).
       01  WS-CLASS                PIC X(6).
       01  WS-FLAG                 PIC X.
       01  RATE-TABLE.
           05  RATE-ENTRY OCCURS 5 INDEXED BY RX.
               10  RATE-CODE       PIC X.
               10  RATE-PCT        PIC V999.
       PROCEDURE DIVISION.
"""


def _report(body: str, *, extra_data: str = "", **options: bool) -> BusinessRuleReport:
    """Parse HEADER + *body*; *extra_data* adds WORKING-STORAGE entries."""
    header = HEADER.replace(
        "       PROCEDURE DIVISION.\n", extra_data + "       PROCEDURE DIVISION.\n"
    )
    result = parse_cobol(header + body, filename="rules.cbl")
    assert result.ast is not None, result.errors
    assert not result.errors, result.errors
    return BusinessRuleExtractor(**options).analyze(result.ast)


def _only(report: BusinessRuleReport, statement: str):
    matches = [r for r in report.rules if r.statement == statement]
    assert len(matches) == 1, [r.to_dict() for r in report.rules]
    return matches[0]


class TestDecisions:
    def test_an_if_with_else_is_a_two_branch_decision(self) -> None:
        report = _report("""\
       MAIN-PARA.
           IF POL-AGE < 25
               MOVE .250 TO WS-RATE
           ELSE
               MOVE .100 TO WS-RATE
           END-IF
           STOP RUN.
""")
        rule = _only(report, "IF")
        assert rule.kind == RULE_DECISION
        assert rule.rule_id == "BR-001"
        assert rule.procedure == "MAIN-PARA"
        assert rule.condition == "POL-AGE < 25"
        assert [(b.label, b.condition) for b in rule.branches] == [
            ("THEN", "POL-AGE < 25"),
            ("ELSE", "NOT (POL-AGE < 25)"),
        ]
        assert [a.text for a in rule.branches[1].actions] == ["MOVE .100 TO WS-RATE"]
        assert rule.inputs == ["POL-AGE"]
        assert rule.outputs == ["WS-RATE"]

    def test_an_if_without_else_has_one_branch(self) -> None:
        report = _report("""\
       MAIN-PARA.
           IF POL-CLAIMS > 3
               MOVE 'HIGH' TO WS-CLASS
           END-IF
           STOP RUN.
""")
        rule = _only(report, "IF")
        assert [b.label for b in rule.branches] == ["THEN"]

    def test_else_of_a_negated_condition_is_not_double_negated(self) -> None:
        report = _report("""\
       MAIN-PARA.
           IF NOT (POL-AGE = 1 AND POL-CLAIMS = 2)
               MOVE 'X' TO WS-CLASS
           ELSE
               MOVE 'Y' TO WS-CLASS
           END-IF
           STOP RUN.
""")
        rule = _only(report, "IF")
        assert rule.branches[1].condition == "POL-AGE = 1 AND POL-CLAIMS = 2"

    def test_evaluate_subject_arms_become_readable_conditions(self) -> None:
        report = _report("""\
       MAIN-PARA.
           EVALUATE POL-CLAIMS
               WHEN 0
                   MOVE .150 TO WS-RATE
               WHEN 1 THRU 2
                   MOVE .050 TO WS-RATE
               WHEN OTHER
                   MOVE ZERO TO WS-RATE
           END-EVALUATE
           STOP RUN.
""")
        rule = _only(report, "EVALUATE")
        assert rule.condition == "POL-CLAIMS"
        assert [(b.label, b.condition) for b in rule.branches] == [
            ("WHEN", "POL-CLAIMS = 0"),
            ("WHEN", "POL-CLAIMS >= 1 AND POL-CLAIMS <= 2"),
            (
                "WHEN OTHER",
                "NOT (POL-CLAIMS = 0) AND NOT (POL-CLAIMS >= 1 AND POL-CLAIMS <= 2)",
            ),
        ]

    def test_an_unquoted_selector_literal_is_quoted_back(self) -> None:
        # Selector values arrive from the parser with their quotes stripped;
        # the rule must not read 'A' as a data name A.
        report = _report("""\
       MAIN-PARA.
           EVALUATE POL-TYPE ALSO POL-TIER
               WHEN 'A' ALSO 1
                   MOVE 'AUTO1' TO WS-CLASS
               WHEN 'H' ALSO ANY
                   MOVE 'HOME' TO WS-CLASS
           END-EVALUATE
           STOP RUN.
""")
        rule = _only(report, "EVALUATE")
        assert rule.condition == "POL-TYPE ALSO POL-TIER"
        assert rule.branches[0].condition == "POL-TYPE = 'A' AND POL-TIER = 1"
        assert rule.branches[1].condition == "POL-TYPE = 'H'"

    def test_evaluate_true_uses_the_condition_itself(self) -> None:
        report = _report("""\
       MAIN-PARA.
           EVALUATE TRUE
               WHEN POL-AGE > 70 AND POL-CLAIMS > 0
                   MOVE 'SENIOR' TO WS-CLASS
               WHEN POL-AUTO
                   MOVE 'AUTO' TO WS-CLASS
           END-EVALUATE
           STOP RUN.
""")
        rule = _only(report, "EVALUATE")
        assert [b.condition for b in rule.branches] == [
            "POL-AGE > 70 AND POL-CLAIMS > 0",
            "POL-AUTO",
        ]
        assert "POL-AUTO" in rule.condition_names
        # Testing a condition name reads the item it is defined on.
        assert {"POL-AGE", "POL-CLAIMS", "POL-AUTO", "POL-TYPE"} <= set(rule.inputs)

    def test_search_is_a_lookup_decision_with_an_at_end_arm(self) -> None:
        report = _report("""\
       MAIN-PARA.
           SET RX TO 1
           SEARCH RATE-ENTRY
               AT END MOVE ZERO TO WS-RATE
               WHEN RATE-CODE (RX) = POL-TYPE
                   MOVE RATE-PCT (RX) TO WS-RATE
           END-SEARCH
           STOP RUN.
""")
        rule = _only(report, "SEARCH")
        assert rule.kind == RULE_DECISION
        assert rule.condition == "RATE-ENTRY"
        assert [(b.label, b.condition) for b in rule.branches] == [
            ("WHEN", "RATE-CODE(RX) = POL-TYPE"),
            ("AT END", "NOT (RATE-CODE(RX) = POL-TYPE)"),
        ]
        assert "POL-TYPE" in rule.inputs
        assert rule.outputs == ["WS-RATE"]
        assert any("best-effort" in caveat for caveat in report.caveats)


class TestNestingAndReachability:
    BODY = """\
       0000-MAIN.
           IF POL-AGE < 18
               MOVE 'UNDERAGE APPLICANT - INVALID' TO WS-MSG
           ELSE
               PERFORM 2000-RATE
           END-IF
           STOP RUN.
       2000-RATE.
           EVALUATE TRUE
               WHEN POL-AUTO
                   IF POL-AGE < 25
                       MOVE 'HIGH' TO WS-CLASS
                   END-IF
               WHEN OTHER
                   MOVE 'STD' TO WS-CLASS
           END-EVALUATE.
       9999-NEVER-CALLED.
           IF POL-CLAIMS > 9
               MOVE 'X' TO WS-CLASS
           END-IF.
"""

    def test_a_nested_decision_is_its_own_rule_with_guards(self) -> None:
        report = _report(self.BODY)
        evaluate = _only(report, "EVALUATE")
        nested = next(r for r in report.rules if r.condition == "POL-AGE < 25")

        assert nested.guards == ["POL-AUTO"]
        # The parent arm points at the nested rule rather than inlining it.
        action = evaluate.branches[0].actions[0]
        assert action.text == "IF POL-AGE < 25"
        assert action.rule_id == nested.rule_id
        # ...and the nested rule's writes are its own, not the parent's.
        assert "WS-CLASS" in nested.outputs
        assert evaluate.outputs == ["WS-CLASS"]

    def test_rules_are_numbered_in_source_order(self) -> None:
        report = _report(self.BODY)
        lines = [r.location.line for r in report.rules]
        assert lines == sorted(lines)
        assert [r.rule_id for r in report.rules] == [
            f"BR-{i:03d}" for i in range(1, len(report.rules) + 1)
        ]

    def test_reached_via_names_the_arm_that_performs_the_paragraph(self) -> None:
        report = _report(self.BODY)
        first = report.rules[0]
        for rule in report.rules:
            if rule.procedure == "2000-RATE":
                assert rule.reached_via == [f"{first.rule_id} ELSE"]

    def test_a_rule_in_unreachable_code_is_flagged(self) -> None:
        report = _report(self.BODY)
        dead = next(r for r in report.rules if r.procedure == "9999-NEVER-CALLED")
        assert dead.in_dead_code
        assert not report.rules[0].in_dead_code
        assert report.to_dict()["summary"]["rules_in_dead_code"] == 1

    def test_a_when_arm_invocation_names_its_condition(self) -> None:
        report = _report("""\
       0000-MAIN.
           EVALUATE POL-TYPE
               WHEN 'A'
                   PERFORM 2000-AUTO
               WHEN 'H'
                   PERFORM 2000-AUTO
           END-EVALUATE
           STOP RUN.
       2000-AUTO.
           IF POL-AGE < 25
               MOVE 'HIGH' TO WS-CLASS
           END-IF.
""")
        nested = _only(report, "IF")
        assert nested.reached_via == [
            "BR-001 WHEN POL-TYPE = 'A'",
            "BR-001 WHEN POL-TYPE = 'H'",
        ]


class TestValidation:
    @pytest.mark.parametrize(
        ("arm", "reason"),
        [
            ("MOVE 'INVALID POLICY AGE' TO WS-MSG", "moves an error message"),
            ("PERFORM 9000-REJECT-POLICY", "performs 9000-REJECT-POLICY"),
            ("GO TO 9900-ABEND", "goes to 9900-ABEND"),
            ("CALL 'CEE3ABD'", "calls CEE3ABD"),
            ("DISPLAY 'POLICY NOT FOUND'", "displays an error"),
        ],
    )
    def test_an_arm_that_rejects_makes_a_validation(
        self, arm: str, reason: str
    ) -> None:
        report = _report(f"""\
       MAIN-PARA.
           IF POL-AGE > 99
               {arm}
           END-IF
           STOP RUN.
       9000-REJECT-POLICY.
           EXIT.
       9900-ABEND.
           STOP RUN.
""")
        rule = _only(report, "IF")
        assert rule.kind == RULE_VALIDATION
        assert any(reason in why for why in rule.classification), rule.classification

    def test_writing_an_error_named_item_is_a_validation(self) -> None:
        report = _report(
            """\
       MAIN-PARA.
           IF POL-PREMIUM = 0
               MOVE 'Y' TO WS-FLAG
           END-IF
           IF POL-CLAIMS > 50
               MOVE 'CLAIMS' TO WS-ERROR-FIELD
           END-IF
           STOP RUN.
""",
            extra_data="       01  WS-ERROR-FIELD PIC X(8).\n",
        )
        kinds = [r.kind for r in report.rules]
        assert kinds == [RULE_DECISION, RULE_VALIDATION]

    def test_a_class_test_is_a_validation(self) -> None:
        report = _report("""\
       MAIN-PARA.
           IF POL-PREMIUM IS NOT NUMERIC
               MOVE ZERO TO POL-PREMIUM
           END-IF
           STOP RUN.
""")
        rule = _only(report, "IF")
        assert rule.kind == RULE_VALIDATION
        assert "class test" in rule.classification[0]

    def test_an_ordinary_branch_is_not_a_validation(self) -> None:
        report = _report("""\
       MAIN-PARA.
           IF POL-HOME
               MOVE 'HOME' TO WS-CLASS
           END-IF
           STOP RUN.
""")
        assert _only(report, "IF").kind == RULE_DECISION


class TestTechnicalRules:
    BODY = """\
       0000-MAIN.
           OPEN INPUT POLICY-FILE
           IF WS-POLICY-STATUS NOT = '00'
               DISPLAY 'OPEN FAILED'
               STOP RUN
           END-IF
           PERFORM 1000-READ
           PERFORM UNTIL NO-MORE-POLICIES
               IF POL-AUTO
                   MOVE 'AUTO' TO WS-CLASS
               END-IF
               PERFORM 1000-READ
           END-PERFORM
           CLOSE POLICY-FILE
           STOP RUN.
       1000-READ.
           READ POLICY-FILE
               AT END SET NO-MORE-POLICIES TO TRUE
           END-READ
           IF NO-MORE-POLICIES
               DISPLAY 'DONE'
           END-IF.
"""

    def test_file_status_and_eof_checks_are_excluded_but_counted(self) -> None:
        report = _report(self.BODY)
        assert [r.condition for r in report.rules] == ["POL-AUTO"]
        assert report.technical_rules_excluded == 2
        assert report.to_dict()["summary"]["technical_rules_excluded"] == 2
        assert "2 technical rule(s) excluded" in report.to_text()

    def test_include_technical_keeps_them_and_says_why(self) -> None:
        report = _report(self.BODY, include_technical=True)
        assert report.technical_rules_excluded == 0
        technical = [r for r in report.rules if r.technical]
        assert [r.condition for r in technical] == [
            "WS-POLICY-STATUS <> '00'",
            "NO-MORE-POLICIES",
        ]
        # The EOF flag is recognised because the READ's AT END sets it, not
        # by its name.
        assert "NO-MORE-POLICIES" in technical[1].classification[0]
        assert [r.rule_id for r in report.rules] == ["BR-001", "BR-002", "BR-003"]

    def test_a_decision_in_a_loop_body_is_still_a_rule(self) -> None:
        report = _report(self.BODY)
        assert report.rules[0].procedure == "0000-MAIN"

    def test_sqlcode_checks_are_technical(self) -> None:
        report = _report("""\
       MAIN-PARA.
           IF SQLCODE NOT = 0
               MOVE 'SQL' TO WS-CLASS
           END-IF
           STOP RUN.
""")
        assert report.rules == []
        assert report.technical_rules_excluded == 1

    def test_a_link_to_an_excluded_rule_is_dropped_not_dangling(self) -> None:
        report = _report("""\
       MAIN-PARA.
           IF POL-AUTO
               IF WS-POLICY-STATUS = '10'
                   MOVE 'EOF' TO WS-CLASS
               END-IF
           END-IF
           STOP RUN.
""")
        (rule,) = report.rules
        action = rule.branches[0].actions[0]
        assert action.rule_id is None
        assert action.text == "IF WS-POLICY-STATUS = '10'"


class TestCalculations:
    def test_compute_is_a_calculation_with_a_formula(self) -> None:
        report = _report("""\
       MAIN-PARA.
           COMPUTE WS-NET ROUNDED =
               POL-PREMIUM * (1 + WS-RATE) - WS-DISCOUNT
           STOP RUN.
""")
        rule = _only(report, "COMPUTE")
        assert rule.kind == RULE_CALCULATION
        assert rule.formula == (
            "WS-NET ROUNDED = POL-PREMIUM * (1 + WS-RATE) - WS-DISCOUNT"
        )
        assert rule.inputs == ["POL-PREMIUM", "WS-DISCOUNT", "WS-RATE"]
        assert rule.outputs == ["WS-NET"]
        assert rule.branches == []

    @pytest.mark.parametrize(
        ("statement", "formula"),
        [
            ("ADD POL-PREMIUM TO WS-TOTAL", "WS-TOTAL = WS-TOTAL + POL-PREMIUM"),
            (
                "ADD POL-PREMIUM WS-DISCOUNT GIVING WS-NET",
                "WS-NET = POL-PREMIUM + WS-DISCOUNT",
            ),
            (
                "SUBTRACT WS-DISCOUNT FROM POL-PREMIUM GIVING WS-NET",
                "WS-NET = POL-PREMIUM - WS-DISCOUNT",
            ),
            (
                "MULTIPLY POL-PREMIUM BY WS-RATE GIVING WS-DISCOUNT",
                "WS-DISCOUNT = POL-PREMIUM * WS-RATE",
            ),
            (
                "DIVIDE POL-PREMIUM BY 12 GIVING WS-SHARE REMAINDER WS-LEFT",
                "WS-SHARE = POL-PREMIUM / 12; REMAINDER WS-LEFT",
            ),
            (
                "DIVIDE 12 INTO POL-PREMIUM GIVING WS-SHARE",
                "WS-SHARE = POL-PREMIUM / 12",
            ),
        ],
    )
    def test_arithmetic_verbs_are_normalized_to_formulas(
        self, statement: str, formula: str
    ) -> None:
        report = _report(f"""\
       MAIN-PARA.
           {statement}
           STOP RUN.
""")
        (rule,) = report.rules
        assert rule.kind == RULE_CALCULATION
        assert rule.formula == formula

    def test_counters_are_not_rules(self) -> None:
        report = _report("""\
       MAIN-PARA.
           ADD 1 TO WS-COUNT
           SUBTRACT 1 FROM WS-COUNT
           COMPUTE WS-COUNT = WS-COUNT + 1
           STOP RUN.
""")
        assert report.rules == []
        assert report.technical_rules_excluded == 0

    def test_a_calculation_inside_an_arm_is_an_action_not_a_second_rule(
        self,
    ) -> None:
        report = _report("""\
       MAIN-PARA.
           IF POL-CLAIMS = 0
               COMPUTE WS-DISCOUNT = POL-PREMIUM * 0.15
           END-IF
           STOP RUN.
""")
        (rule,) = report.rules
        assert rule.statement == "IF"
        assert rule.branches[0].actions[0].text == (
            "COMPUTE WS-DISCOUNT = POL-PREMIUM * 0.15"
        )
        assert rule.inputs == ["POL-CLAIMS", "POL-PREMIUM"]
        assert rule.outputs == ["WS-DISCOUNT"]

    def test_a_calculation_under_a_size_error_guard_carries_it(self) -> None:
        report = _report("""\
       MAIN-PARA.
           COMPUTE WS-NET = POL-PREMIUM - WS-DISCOUNT
               ON SIZE ERROR
                   IF POL-AUTO
                       MOVE 'OVERFLOW' TO WS-CLASS
                   END-IF
           END-COMPUTE
           STOP RUN.
""")
        nested = _only(report, "IF")
        assert nested.guards == [
            "ON SIZE ERROR (COMPUTE WS-NET = POL-PREMIUM - WS-DISCOUNT)"
        ]


class TestConditionNames:
    def test_the_glossary_spells_out_every_name_a_rule_uses(self) -> None:
        report = _report("""\
       MAIN-PARA.
           EVALUATE TRUE
               WHEN POL-AUTO
                   MOVE 'A' TO WS-CLASS
               WHEN POL-COMMERCIAL
                   MOVE 'C' TO WS-CLASS
               WHEN POL-SPECIAL
                   MOVE 'S' TO WS-CLASS
           END-EVALUATE
           IF POL-TIER-LOW
               MOVE .010 TO WS-RATE
           END-IF
           STOP RUN.
""")
        glossary = {c.name: c for c in report.condition_names}
        assert set(glossary) == {
            "POL-AUTO",
            "POL-COMMERCIAL",
            "POL-SPECIAL",
            "POL-TIER-LOW",
        }
        assert glossary["POL-AUTO"].condition == "POL-TYPE = 'A'"
        assert glossary["POL-COMMERCIAL"].condition == (
            "POL-TYPE = 'C' OR POL-TYPE = 'D'"
        )
        assert glossary["POL-SPECIAL"].values == ["'P' THRU 'S'"]
        assert glossary["POL-SPECIAL"].condition == (
            "POL-TYPE >= 'P' AND POL-TYPE <= 'S'"
        )
        # A numeric item's values are numbers, not quoted text.
        assert glossary["POL-TIER-LOW"].condition == ("POL-TIER >= 1 AND POL-TIER <= 3")
        assert glossary["POL-TIER-LOW"].data_item == "POL-TIER"

    def test_setting_a_condition_name_writes_its_item(self) -> None:
        report = _report("""\
       MAIN-PARA.
           IF POL-AGE > 60
               SET POL-SPECIAL TO TRUE
           END-IF
           STOP RUN.
""")
        (rule,) = report.rules
        assert rule.branches[0].actions[0].text == "SET POL-SPECIAL TO TRUE"
        assert rule.outputs == ["POL-SPECIAL", "POL-TYPE"]
        assert rule.condition_names == ["POL-SPECIAL"]


class TestReportShape:
    BODY = """\
       MAIN-PARA.
           IF POL-AGE < 25
               MOVE .250 TO WS-RATE
           END-IF
           COMPUTE WS-NET = POL-PREMIUM * WS-RATE
           STOP RUN.
"""

    def test_to_dict_is_json_and_counts_by_kind(self) -> None:
        data = _report(self.BODY).to_dict()
        json.dumps(data)
        assert data["program_name"] == "RULES"
        assert data["summary"] == {
            "rule_count": 2,
            "decision_count": 1,
            "validation_count": 0,
            "calculation_count": 1,
            "technical_rules_excluded": 0,
            "rules_in_dead_code": 0,
        }
        rule = data["rules"][0]
        assert set(rule) >= {
            "rule_id",
            "kind",
            "condition",
            "branches",
            "guards",
            "reached_via",
            "inputs",
            "outputs",
            "condition_names",
            "technical",
            "classification",
            "in_dead_code",
            "location",
        }
        assert rule["branches"][0]["actions"][0]["rule_id"] is None

    def test_data_lineage_inverts_inputs_and_outputs(self) -> None:
        lineage = _report(self.BODY).data_lineage
        assert lineage["WS-RATE"] == {"read_by": ["BR-002"], "written_by": ["BR-001"]}
        assert lineage["WS-NET"] == {"read_by": [], "written_by": ["BR-002"]}
        assert list(lineage) == sorted(lineage)

    def test_to_text_reads_as_rules(self) -> None:
        text = _report(self.BODY).to_text()
        assert text.startswith("Business rules for RULES: 2 rule(s)")
        assert "BR-001  decision  MAIN-PARA  line" in text
        assert "  IF        POL-AGE < 25" in text
        assert "  compute   WS-NET = POL-PREMIUM * WS-RATE" in text

    def test_a_program_without_procedure_division_has_no_rules(self) -> None:
        result = parse_cobol(
            "       IDENTIFICATION DIVISION.\n       PROGRAM-ID. EMPTY.\n"
        )
        assert result.ast is not None
        report = BusinessRuleExtractor().analyze(result.ast)
        assert report.rules == []
        assert report.program_name == "EMPTY"

    def test_rule_lookup_by_id(self) -> None:
        report = _report(self.BODY)
        assert report.rule("BR-002") is report.rules[1]
        assert report.rule("BR-999") is None

    def test_contained_programs_are_not_walked(self) -> None:
        source = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. OUTER.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-A PIC 9.
       01 WS-B PIC 9.
       PROCEDURE DIVISION.
       MAIN-PARA.
           IF WS-A = 1
               MOVE 2 TO WS-B
           END-IF
           GOBACK.
       IDENTIFICATION DIVISION.
       PROGRAM-ID. INNER.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-C PIC 9.
       PROCEDURE DIVISION.
       INNER-PARA.
           IF WS-C = 3
               MOVE 4 TO WS-C
           END-IF
           GOBACK.
       END PROGRAM INNER.
       END PROGRAM OUTER.
"""
        result = parse_cobol(source)
        assert result.ast is not None
        report = BusinessRuleExtractor().analyze(result.ast)
        assert [r.condition for r in report.rules] == ["WS-A = 1"]


SAMPLES = Path(__file__).resolve().parents[2] / "samples"


@pytest.mark.parametrize(
    "path",
    sorted((SAMPLES / "enterprise").glob("*.cbl")),
    ids=lambda p: p.name,
)
def test_every_enterprise_program_type_extracts_cleanly(path: Path) -> None:
    result = parse_cobol(path.read_text(encoding="utf-8"), filename=path.name)
    assert result.ast is not None
    for unit in result.ast.program_units():
        report = BusinessRuleExtractor(include_technical=True).analyze(unit)
        json.dumps(report.to_dict())
        report.to_text()
        for rule in report.rules:
            assert rule.kind in (RULE_DECISION, RULE_VALIDATION, RULE_CALCULATION)
            assert rule.classification


class TestRenderingEdges:
    def test_evaluate_false_and_a_negated_selector(self) -> None:
        report = _report("""\
       MAIN-PARA.
           EVALUATE FALSE
               WHEN POL-AUTO
                   MOVE 'NOT-AUTO' TO WS-CLASS
           END-EVALUATE
           EVALUATE POL-TIER
               WHEN NOT 6
                   MOVE 'X' TO WS-CLASS
           END-EVALUATE
           STOP RUN.
""")
        false_rule, not_rule = report.rules
        assert false_rule.branches[0].condition == "NOT (POL-AUTO)"
        assert not_rule.branches[0].condition == "POL-TIER <> 6"

    @pytest.mark.parametrize(
        ("statement", "formula"),
        [
            (
                "SUBTRACT WS-DISCOUNT FROM WS-NET WS-TOTAL",
                "WS-NET = WS-NET - WS-DISCOUNT; WS-TOTAL = WS-TOTAL - WS-DISCOUNT",
            ),
            ("MULTIPLY WS-RATE BY WS-NET", "WS-NET = WS-NET * WS-RATE"),
            ("DIVIDE 12 INTO WS-NET ROUNDED", "WS-NET ROUNDED = WS-NET / 12"),
        ],
    )
    def test_in_place_arithmetic(self, statement: str, formula: str) -> None:
        report = _report(f"""\
       MAIN-PARA.
           {statement}
           STOP RUN.
""")
        (rule,) = report.rules
        assert rule.formula == formula

    def test_action_texts_for_common_verbs(self) -> None:
        report = _report("""\
       MAIN-PARA.
           IF POL-AUTO
               SET RX UP BY 1
               SET RX TO 3
               PERFORM 2000-X 3 TIMES
               PERFORM 2000-X UNTIL POL-CLAIMS > 5
               PERFORM 2000-X VARYING WS-COUNT FROM 1 BY 1
                   UNTIL WS-COUNT > 3
               STRING 'POLICY ' POL-ID DELIMITED BY SIZE INTO WS-MSG
               UNSTRING WS-MSG DELIMITED BY SPACE INTO WS-CLASS WS-FLAG
               CALL 'RATESUB' USING POL-ID WS-RATE
               GO TO 2000-X
           END-IF.
       2000-X.
           EXIT.
""")
        texts = [a.text for a in report.rules[0].branches[0].actions]
        assert texts == [
            "SET RX UP BY 1",
            "SET RX TO 3",
            "PERFORM 2000-X 3 TIMES",
            "PERFORM 2000-X UNTIL POL-CLAIMS > 5",
            "PERFORM 2000-X VARYING WS-COUNT FROM 1 BY 1 UNTIL WS-COUNT > 3",
            "STRING 'POLICY ' POL-ID INTO WS-MSG",
            "UNSTRING WS-MSG INTO WS-CLASS WS-FLAG",
            "CALL 'RATESUB' USING POL-ID, WS-RATE",
            "GO TO 2000-X",
        ]

    def test_exec_sql_action_text(self) -> None:
        report = _report("""\
       MAIN-PARA.
           IF POL-AUTO
               EXEC SQL
                   UPDATE POLICY SET RATE = :WS-RATE WHERE ID = :POL-ID
               END-EXEC
           END-IF
           STOP RUN.
""")
        text = report.rules[0].branches[0].actions[0].text
        assert text.startswith("EXEC SQL UPDATE POLICY SET RATE =")
        assert ":POL-ID" in text

    def test_a_calculation_writing_only_a_technical_item_is_technical(self) -> None:
        report = _report(
            """\
       MAIN-PARA.
           COMPUTE WS-EOF-CTR = POL-CLAIMS * 2
           STOP RUN.
""",
            extra_data="       01  WS-EOF-CTR PIC 9(4).\n",
            include_technical=True,
        )
        (rule,) = report.rules
        assert rule.technical
        assert "WS-EOF-CTR" in rule.classification[0]

    def test_rules_in_sections_carry_the_section(self) -> None:
        report = _report("""\
       MAIN-SECTION SECTION.
       MAIN-PARA.
           PERFORM RATE-SECTION
           STOP RUN.
       RATE-SECTION SECTION.
       RATE-PARA.
           IF POL-AUTO
               MOVE .1 TO WS-RATE
           END-IF.
""")
        (rule,) = report.rules
        assert rule.section == "RATE-SECTION"
        assert rule.procedure == "RATE-PARA"
        assert "RATE-SECTION / RATE-PARA" in rule.to_text()
