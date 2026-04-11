"""Unit tests for CobolCheckGenerator.

Tests the CobolCheck .cut file emitter that takes a TestPlan
and produces valid CobolCheck syntax.
"""

from cobolparser.analysis.test_plan import (
    DataSetup,
    ExpectedOutcome,
    TestCase,
    TestPlan,
    TestSuite,
)
from cobolparser.generators.cobolcheck import CobolCheckGenerator


def _make_plan(
    program_name: str = "TESTPROG",
    suites: list[TestSuite] | None = None,
) -> TestPlan:
    """Build a TestPlan with optional suites."""
    plan = TestPlan(program_name=program_name)
    if suites:
        plan.test_suites = suites
        plan.total_test_cases = sum(len(s.test_cases) for s in suites)
    return plan


def _make_suite(
    name: str = "Test Suite",
    cases: list[TestCase] | None = None,
) -> TestSuite:
    return TestSuite(name=name, test_cases=cases or [])


def _make_case(
    name: str = "test case",
    paragraph: str = "MAIN-PARA",
    setup: list[DataSetup] | None = None,
    outcomes: list[ExpectedOutcome] | None = None,
    comment: str | None = None,
) -> TestCase:
    return TestCase(
        name=name,
        target_paragraph=paragraph,
        strategy="paragraph",
        data_setup=setup or [],
        expected_outcomes=outcomes or [],
        comment=comment,
    )


class TestGeneratorEmpty:
    """Tests for empty or minimal plans."""

    def test_empty_plan_no_suites(self):
        plan = _make_plan()
        gen = CobolCheckGenerator()
        output = gen.generate(plan)
        assert "No test suites generated" in output

    def test_empty_plan_no_comments(self):
        plan = _make_plan()
        gen = CobolCheckGenerator(include_comments=False)
        output = gen.generate(plan)
        assert output.strip() == ""


class TestGeneratorOutput:
    """Tests for generated CobolCheck syntax."""

    def test_testsuite_keyword(self):
        suite = _make_suite(
            "Paragraph coverage",
            [_make_case("Should execute P", "P")],
        )
        plan = _make_plan(suites=[suite])
        gen = CobolCheckGenerator()
        output = gen.generate(plan)
        assert 'TESTSUITE "Paragraph coverage"' in output

    def test_testcase_keyword(self):
        suite = _make_suite(
            "Suite",
            [_make_case("Should execute MAIN", "MAIN")],
        )
        plan = _make_plan(suites=[suite])
        gen = CobolCheckGenerator()
        output = gen.generate(plan)
        assert 'TESTCASE "Should execute MAIN"' in output

    def test_perform_emitted(self):
        suite = _make_suite(
            "Suite",
            [_make_case("test", "CALC-INTEREST")],
        )
        plan = _make_plan(suites=[suite])
        gen = CobolCheckGenerator()
        output = gen.generate(plan)
        assert "PERFORM CALC-INTEREST" in output

    def test_data_setup_move(self):
        tc = _make_case(setup=[DataSetup(target_variable="WS-NUM", value="ZEROS")])
        suite = _make_suite("S", [tc])
        plan = _make_plan(suites=[suite])
        gen = CobolCheckGenerator()
        output = gen.generate(plan)
        assert "MOVE ZEROS TO WS-NUM" in output

    def test_expected_outcome_expect(self):
        tc = _make_case(
            outcomes=[
                ExpectedOutcome(
                    variable="WS-RESULT",
                    expected_value="NUMERIC",
                    comparison="TO BE",
                )
            ]
        )
        suite = _make_suite("S", [tc])
        plan = _make_plan(suites=[suite])
        gen = CobolCheckGenerator()
        output = gen.generate(plan)
        assert "EXPECT WS-RESULT TO BE NUMERIC" in output

    def test_comment_emitted(self):
        tc = _make_case(comment="This is a note")
        suite = _make_suite("S", [tc])
        plan = _make_plan(suites=[suite])
        gen = CobolCheckGenerator()
        output = gen.generate(plan)
        assert "*> This is a note" in output

    def test_no_comment_when_disabled(self):
        tc = _make_case(comment="Should not appear")
        suite = _make_suite("S", [tc])
        plan = _make_plan(suites=[suite])
        gen = CobolCheckGenerator(include_comments=False)
        output = gen.generate(plan)
        assert "*>" not in output

    def test_header_comment(self):
        suite = _make_suite("S", [_make_case()])
        plan = _make_plan(program_name="MYPROG", suites=[suite])
        gen = CobolCheckGenerator()
        output = gen.generate(plan)
        assert "Generated CobolCheck tests for MYPROG" in output

    def test_no_header_when_comments_disabled(self):
        suite = _make_suite("S", [_make_case()])
        plan = _make_plan(program_name="MYPROG", suites=[suite])
        gen = CobolCheckGenerator(include_comments=False)
        output = gen.generate(plan)
        assert "Generated CobolCheck" not in output


class TestGeneratorMultipleSuites:
    """Tests for plans with multiple suites and cases."""

    def test_two_suites(self):
        s1 = _make_suite("Suite A", [_make_case("tc1")])
        s2 = _make_suite("Suite B", [_make_case("tc2")])
        plan = _make_plan(suites=[s1, s2])
        gen = CobolCheckGenerator()
        output = gen.generate(plan)
        assert 'TESTSUITE "Suite A"' in output
        assert 'TESTSUITE "Suite B"' in output

    def test_multiple_test_cases(self):
        cases = [
            _make_case("Test 1", "PARA-1"),
            _make_case("Test 2", "PARA-2"),
            _make_case("Test 3", "PARA-3"),
        ]
        suite = _make_suite("Big Suite", cases)
        plan = _make_plan(suites=[suite])
        gen = CobolCheckGenerator()
        output = gen.generate(plan)
        assert output.count("TESTCASE") == 3
        assert output.count("PERFORM") == 3

    def test_multiple_setup_and_expect(self):
        tc = _make_case(
            setup=[
                DataSetup(target_variable="WS-A", value="ZEROS"),
                DataSetup(target_variable="WS-B", value="SPACES"),
            ],
            outcomes=[
                ExpectedOutcome(
                    variable="WS-X",
                    expected_value="NUMERIC",
                    comparison="TO BE",
                ),
                ExpectedOutcome(
                    variable="WS-Y",
                    expected_value="100",
                    comparison="TO BE",
                ),
            ],
        )
        suite = _make_suite("S", [tc])
        plan = _make_plan(suites=[suite])
        gen = CobolCheckGenerator()
        output = gen.generate(plan)
        assert "MOVE ZEROS TO WS-A" in output
        assert "MOVE SPACES TO WS-B" in output
        assert "EXPECT WS-X TO BE NUMERIC" in output
        assert "EXPECT WS-Y TO BE 100" in output


class TestValueFormatting:
    """Tests for _format_cobol_value."""

    def test_figurative_zeros(self):
        gen = CobolCheckGenerator()
        assert gen._format_cobol_value("ZEROS") == "ZEROS"
        assert gen._format_cobol_value("zeros") == "ZEROS"
        assert gen._format_cobol_value("ZEROES") == "ZEROES"

    def test_figurative_spaces(self):
        gen = CobolCheckGenerator()
        assert gen._format_cobol_value("SPACES") == "SPACES"
        assert gen._format_cobol_value("SPACE") == "SPACE"

    def test_figurative_high_low_values(self):
        gen = CobolCheckGenerator()
        assert gen._format_cobol_value("HIGH-VALUE") == "HIGH-VALUE"
        assert gen._format_cobol_value("HIGH-VALUES") == "HIGH-VALUES"
        assert gen._format_cobol_value("LOW-VALUE") == "LOW-VALUE"

    def test_figurative_null(self):
        gen = CobolCheckGenerator()
        assert gen._format_cobol_value("NULL") == "NULL"
        assert gen._format_cobol_value("NULLS") == "NULLS"

    def test_numeric_literal_unquoted(self):
        gen = CobolCheckGenerator()
        assert gen._format_cobol_value("100") == "100"
        assert gen._format_cobol_value("0") == "0"
        assert gen._format_cobol_value("99999.99") == "99999.99"

    def test_negative_numeric(self):
        gen = CobolCheckGenerator()
        assert gen._format_cobol_value("-999") == "-999"

    def test_positive_sign_numeric(self):
        gen = CobolCheckGenerator()
        assert gen._format_cobol_value("+42") == "+42"

    def test_string_gets_quoted(self):
        gen = CobolCheckGenerator()
        assert gen._format_cobol_value("HELLO") == '"HELLO"'

    def test_already_quoted_single(self):
        gen = CobolCheckGenerator()
        assert gen._format_cobol_value("'HELLO'") == "'HELLO'"

    def test_already_quoted_double(self):
        gen = CobolCheckGenerator()
        assert gen._format_cobol_value('"WORLD"') == '"WORLD"'

    def test_numeric_keyword_not_quoted(self):
        gen = CobolCheckGenerator()
        assert gen._format_cobol_value("NUMERIC") == "NUMERIC"


class TestIndentation:
    """Tests for indentation control."""

    def test_default_indent_4(self):
        tc = _make_case(setup=[DataSetup(target_variable="WS-X", value="0")])
        suite = _make_suite("S", [tc])
        plan = _make_plan(suites=[suite])
        gen = CobolCheckGenerator(indent=4)
        output = gen.generate(plan)
        lines = output.splitlines()
        testsuite_line = [ln for ln in lines if "TESTSUITE" in ln][0]
        assert testsuite_line.startswith("    ")

    def test_custom_indent(self):
        tc = _make_case()
        suite = _make_suite("S", [tc])
        plan = _make_plan(suites=[suite])
        gen = CobolCheckGenerator(indent=2)
        output = gen.generate(plan)
        lines = output.splitlines()
        testsuite_line = [ln for ln in lines if "TESTSUITE" in ln][0]
        assert testsuite_line.startswith("  ")
        assert not testsuite_line.startswith("    ")

    def test_move_indented_deeper(self):
        tc = _make_case(setup=[DataSetup(target_variable="WS-A", value="0")])
        suite = _make_suite("S", [tc])
        plan = _make_plan(suites=[suite])
        gen = CobolCheckGenerator(indent=4)
        output = gen.generate(plan)
        lines = output.splitlines()
        move_line = [ln for ln in lines if "MOVE" in ln][0]
        # Body indent = 2 levels = 8 spaces
        assert move_line.startswith("        ")


class TestOutputEndsWithNewline:
    """Generated output should always end with a newline."""

    def test_ends_with_newline(self):
        suite = _make_suite("S", [_make_case()])
        plan = _make_plan(suites=[suite])
        gen = CobolCheckGenerator()
        output = gen.generate(plan)
        assert output.endswith("\n")

    def test_empty_plan_ends_with_newline(self):
        plan = _make_plan()
        gen = CobolCheckGenerator()
        output = gen.generate(plan)
        assert output.endswith("\n")
