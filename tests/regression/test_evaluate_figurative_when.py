"""EVALUATE ``WHEN SPACES`` / ``WHEN ZERO`` / ``WHEN LOW-VALUES`` keep the
figurative constant (issue #313).

The selector dict for ``WHEN SPACES`` and ``WHEN 'SPACES'`` used to be the
same ``{"type": "Literal", "value": "SPACES"}``. gen-fixtures then wrote the
six characters ``SPACES`` as data for the figurative arm (and marked the
scenario verified), reported ``WHEN ZERO`` / ``WHEN LOW-VALUES`` as literals
that do not fit the field, and business-rules rendered the quoted literal
as the figurative constant.
"""

from __future__ import annotations

from cobolparser import parse_cobol
from cobolparser.analysis.boundary_inventory import BoundaryInventoryAnalyzer
from cobolparser.analysis.business_rules import BusinessRuleExtractor
from cobolparser.analysis.constraints import ConstraintExtractor
from cobolparser.generators import ProgramFixtureGenerator, ProgramLayoutIndex

_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. EVFIG.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT IN-FILE ASSIGN TO INFILE.
       DATA DIVISION.
       FILE SECTION.
       FD  IN-FILE.
       01  IN-REC.
           05 IN-CODE PIC X(6).
           05 IN-AMT  PIC 9(5).
       WORKING-STORAGE SECTION.
       01  WS-EOF PIC X VALUE 'N'.
       PROCEDURE DIVISION.
       MAIN-PARA.
           OPEN INPUT IN-FILE
           READ IN-FILE AT END MOVE 'Y' TO WS-EOF END-READ
{body}
           CLOSE IN-FILE
           STOP RUN.
"""


def _parse(body: str):
    result = parse_cobol(_SOURCE.format(body=body), filename="evfig.cbl")
    assert result.ast is not None, result.errors
    assert result.errors == []
    return result.ast


def _arms(body: str):
    ast = _parse(body)
    index = ProgramLayoutIndex.build(ast)
    boundaries = BoundaryInventoryAnalyzer().analyze(ast, index)
    report = ConstraintExtractor().extract(ast, index, boundaries)
    assert len(report.branches) == 1, report.branches
    return report.branches[0].arms


_CODE_EVALUATE = """\
           EVALUATE IN-CODE
             WHEN SPACES DISPLAY 'BLANK'
             WHEN 'SPACES' DISPLAY 'WORD'
             WHEN OTHER DISPLAY 'OTHER'
           END-EVALUATE"""


class TestSelectorMarkers:
    def test_figurative_and_quoted_selectors_are_told_apart(self):
        ast = _parse(_CODE_EVALUATE)
        (evaluate,) = ast.find_all_by_type("EvaluateStatement")
        figurative = evaluate.when_clauses[0].selectors[0]
        quoted = evaluate.when_clauses[1].selectors[0]
        assert figurative == {
            "type": "Literal",
            "value": "SPACES",
            "figurative": True,
        }
        assert quoted == {"type": "Literal", "value": "SPACES", "quoted": True}


class TestConstraints:
    def test_when_spaces_is_a_figurative_constraint(self):
        arms = _arms(_CODE_EVALUATE)
        assert [(c.op, c.values, c.negated) for c in arms["WHEN_1"]] == [
            ("figurative", ("SPACES",), False)
        ]
        # The quoted literal is the six characters, and excludes the blank arm.
        assert [(c.op, c.values, c.negated) for c in arms["WHEN_2"]] == [
            ("eq", ("SPACES",), False),
            ("figurative", ("SPACES",), True),
        ]

    def test_when_zero_and_low_values_are_figurative(self):
        arms = _arms("""\
           EVALUATE IN-AMT
             WHEN ZERO DISPLAY 'ZERO'
             WHEN OTHER DISPLAY 'NZ'
           END-EVALUATE""")
        assert [(c.op, c.values) for c in arms["WHEN_1"]] == [("figurative", ("ZERO",))]
        arms = _arms("""\
           EVALUATE IN-CODE
             WHEN LOW-VALUES DISPLAY 'LOW'
           END-EVALUATE""")
        assert [(c.op, c.values) for c in arms["WHEN_1"]] == [
            ("figurative", ("LOW-VALUES",))
        ]


class TestGenFixtures:
    def test_when_spaces_scenario_gets_blank_data(self, tmp_path):
        path = tmp_path / "evfig.cbl"
        path.write_text(_SOURCE.format(body=_CODE_EVALUATE))
        bundle = ProgramFixtureGenerator().generate_with_scenarios_from_file(
            str(path), mode="branches", seed=1
        )
        data = bundle.to_dict()
        codes_by_scenario = {
            scenario["name"]: {
                row["IN-CODE"]
                for fixture in scenario["fixtures"]
                if fixture["category"] == "READ"
                for row in fixture["sequence"]
            }
            for scenario in data["scenarios"]
        }
        arm_codes = [
            codes for name, codes in codes_by_scenario.items() if "WHEN SPACES" in name
        ]
        # One arm is the figurative (blank), the other the quoted word.
        assert sorted(arm_codes, key=sorted) == [{""}, {"SPACES"}], codes_by_scenario
        missed = [
            detail
            for detail in data["scenario_coverage"]["details"]
            if detail["status"] == "missed"
        ]
        # Both WHEN SPACES arms are targeted, and so is WHEN OTHER: NOT
        # SPACES conjoined with NOT 'SPACES' (bug hunt 2026-11-05, round 2;
        # it used to be missed as "not modeled").
        assert missed == []
        (other,) = [
            codes for name, codes in codes_by_scenario.items() if "WHEN OTHER" in name
        ]
        assert other and not other & {"", "SPACES"}, other


class TestBusinessRules:
    def test_quoted_literal_keeps_its_quotes(self):
        report = BusinessRuleExtractor().analyze(_parse(_CODE_EVALUATE))
        (rule,) = [r for r in report.rules if r.condition.startswith("IN-CODE")]
        assert rule.branches[0].condition == "IN-CODE = SPACES"
        assert rule.branches[1].condition == "IN-CODE = 'SPACES'"

    def test_blank_literal_is_not_quoted_twice(self):
        report = BusinessRuleExtractor().analyze(_parse("""\
           EVALUATE IN-CODE
             WHEN '  ' DISPLAY 'BLANK'
           END-EVALUATE"""))
        (rule,) = [r for r in report.rules if r.condition.startswith("IN-CODE")]
        assert rule.branches[0].condition == "IN-CODE = '  '"
