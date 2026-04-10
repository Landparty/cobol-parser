"""Unit tests for TestPlanGenerator.

Tests the test plan generator that takes a CoverageMap and produces
a structured TestPlan with paragraph, branch, and boundary coverage.
"""

from cobolparser.analysis.coverage_analyzer import (
    BranchPoint,
    BranchType,
    CoverageMap,
    DataItemInfo,
    ParagraphCoverage,
)
from cobolparser.analysis.test_plan import (
    CoverageStrategy,
    DataSetup,
    ExpectedOutcome,
    TestCase,
    TestPlan,
    TestPlanGenerator,
    TestSuite,
)


def _make_coverage_map(
    program_name: str = "TESTPROG",
    has_procedure: bool = True,
) -> CoverageMap:
    """Build a minimal CoverageMap."""
    cmap = CoverageMap(program_name=program_name)
    cmap.has_procedure_division = has_procedure
    return cmap


def _make_paragraph(
    name: str,
    stmt_count: int = 1,
    branch_points: list[BranchPoint] | None = None,
    reads: set[str] | None = None,
    writes: set[str] | None = None,
    has_stop_run: bool = False,
    has_goback: bool = False,
    is_empty: bool = False,
) -> ParagraphCoverage:
    """Build a ParagraphCoverage with defaults."""
    return ParagraphCoverage(
        paragraph_name=name,
        statement_count=stmt_count,
        branch_points=branch_points or [],
        reads_variables=reads or set(),
        writes_variables=writes or set(),
        has_stop_run=has_stop_run,
        has_goback=has_goback,
        is_empty=is_empty,
    )


class TestTestPlanGeneratorBasic:
    """Tests for basic TestPlanGenerator behavior."""

    def test_no_procedure_division_empty_plan(self):
        cmap = _make_coverage_map(has_procedure=False)
        gen = TestPlanGenerator()
        plan = gen.generate(cmap)
        assert plan.program_name == "TESTPROG"
        assert plan.test_suites == []
        assert plan.total_test_cases == 0

    def test_default_all_strategies(self):
        cmap = _make_coverage_map()
        cmap.paragraphs = [_make_paragraph("MAIN-LOGIC")]
        gen = TestPlanGenerator()
        plan = gen.generate(cmap)
        assert CoverageStrategy.PARAGRAPH in plan.coverage_strategies_used

    def test_custom_strategies(self):
        cmap = _make_coverage_map()
        cmap.paragraphs = [_make_paragraph("MAIN-LOGIC")]
        gen = TestPlanGenerator(strategies=["paragraph"])
        plan = gen.generate(cmap)
        assert CoverageStrategy.PARAGRAPH in plan.coverage_strategies_used
        assert CoverageStrategy.BRANCH not in plan.coverage_strategies_used

    def test_total_test_cases_counted(self):
        cmap = _make_coverage_map()
        cmap.paragraphs = [
            _make_paragraph("PARA-A"),
            _make_paragraph("PARA-B"),
        ]
        gen = TestPlanGenerator(strategies=["paragraph"])
        plan = gen.generate(cmap)
        assert plan.total_test_cases == 2


class TestParagraphStrategy:
    """Tests for the PARAGRAPH coverage strategy."""

    def test_one_test_per_paragraph(self):
        cmap = _make_coverage_map()
        cmap.paragraphs = [
            _make_paragraph("PARA-A"),
            _make_paragraph("PARA-B"),
        ]
        gen = TestPlanGenerator(strategies=["paragraph"])
        plan = gen.generate(cmap)
        suite = plan.test_suites[0]
        assert len(suite.test_cases) == 2

    def test_empty_paragraph_skipped(self):
        cmap = _make_coverage_map()
        cmap.paragraphs = [
            _make_paragraph("EMPTY", is_empty=True),
            _make_paragraph("NOT-EMPTY"),
        ]
        gen = TestPlanGenerator(strategies=["paragraph"])
        plan = gen.generate(cmap)
        suite = plan.test_suites[0]
        assert len(suite.test_cases) == 1
        assert suite.test_cases[0].target_paragraph == "NOT-EMPTY"

    def test_stop_run_only_paragraph_skipped(self):
        cmap = _make_coverage_map()
        cmap.paragraphs = [
            _make_paragraph("STOP-ONLY", stmt_count=1, has_stop_run=True),
            _make_paragraph("REGULAR"),
        ]
        gen = TestPlanGenerator(strategies=["paragraph"])
        plan = gen.generate(cmap)
        targets = [tc.target_paragraph for tc in plan.test_suites[0].test_cases]
        assert "STOP-ONLY" not in targets

    def test_goback_only_paragraph_skipped(self):
        cmap = _make_coverage_map()
        cmap.paragraphs = [
            _make_paragraph("GOBACK-ONLY", stmt_count=1, has_goback=True),
            _make_paragraph("REGULAR"),
        ]
        gen = TestPlanGenerator(strategies=["paragraph"])
        plan = gen.generate(cmap)
        targets = [tc.target_paragraph for tc in plan.test_suites[0].test_cases]
        assert "GOBACK-ONLY" not in targets

    def test_stop_run_with_other_stmts_not_skipped(self):
        cmap = _make_coverage_map()
        cmap.paragraphs = [
            _make_paragraph("STOP-PLUS", stmt_count=3, has_stop_run=True),
        ]
        gen = TestPlanGenerator(strategies=["paragraph"])
        plan = gen.generate(cmap)
        assert len(plan.test_suites[0].test_cases) == 1

    def test_paragraph_test_name(self):
        cmap = _make_coverage_map()
        cmap.paragraphs = [_make_paragraph("COMPUTE-INTEREST")]
        gen = TestPlanGenerator(strategies=["paragraph"])
        plan = gen.generate(cmap)
        tc = plan.test_suites[0].test_cases[0]
        assert "COMPUTE-INTEREST" in tc.name

    def test_paragraph_suite_name_contains_program(self):
        cmap = _make_coverage_map(program_name="MYPROG")
        cmap.paragraphs = [_make_paragraph("P")]
        gen = TestPlanGenerator(strategies=["paragraph"])
        plan = gen.generate(cmap)
        assert "MYPROG" in plan.test_suites[0].name

    def test_no_paragraphs_no_suite(self):
        cmap = _make_coverage_map()
        gen = TestPlanGenerator(strategies=["paragraph"])
        plan = gen.generate(cmap)
        assert plan.test_suites == []


class TestBranchStrategy:
    """Tests for the BRANCH coverage strategy."""

    def test_one_test_per_branch_point(self):
        bps = [
            BranchPoint(
                branch_type=BranchType.IF_TRUE,
                parent_statement_type="IF",
                paragraph_name="P",
            ),
            BranchPoint(
                branch_type=BranchType.IF_FALSE,
                parent_statement_type="IF",
                paragraph_name="P",
            ),
        ]
        cmap = _make_coverage_map()
        cmap.paragraphs = [_make_paragraph("P", branch_points=bps)]
        gen = TestPlanGenerator(strategies=["branch"])
        plan = gen.generate(cmap)
        suite = plan.test_suites[0]
        assert len(suite.test_cases) == 2

    def test_branch_test_name_contains_type(self):
        bp = BranchPoint(
            branch_type=BranchType.EVALUATE_WHEN,
            parent_statement_type="EVALUATE",
            paragraph_name="EVAL-PARA",
        )
        cmap = _make_coverage_map()
        cmap.paragraphs = [_make_paragraph("EVAL-PARA", branch_points=[bp])]
        gen = TestPlanGenerator(strategies=["branch"])
        plan = gen.generate(cmap)
        tc = plan.test_suites[0].test_cases[0]
        assert "EVALUATE WHEN" in tc.name

    def test_io_branch_adds_comment(self):
        bp = BranchPoint(
            branch_type=BranchType.IO_AT_END,
            parent_statement_type="READ",
            paragraph_name="READ-PARA",
        )
        cmap = _make_coverage_map()
        cmap.paragraphs = [_make_paragraph("READ-PARA", branch_points=[bp])]
        gen = TestPlanGenerator(strategies=["branch"])
        plan = gen.generate(cmap)
        tc = plan.test_suites[0].test_cases[0]
        assert tc.comment is not None
        assert "file setup" in tc.comment.lower()

    def test_call_exception_adds_comment(self):
        bp = BranchPoint(
            branch_type=BranchType.CALL_ON_EXCEPTION,
            parent_statement_type="CALL",
            paragraph_name="CALL-PARA",
        )
        cmap = _make_coverage_map()
        cmap.paragraphs = [_make_paragraph("CALL-PARA", branch_points=[bp])]
        gen = TestPlanGenerator(strategies=["branch"])
        plan = gen.generate(cmap)
        tc = plan.test_suites[0].test_cases[0]
        assert tc.comment is not None

    def test_no_branch_points_no_suite(self):
        cmap = _make_coverage_map()
        cmap.paragraphs = [_make_paragraph("P")]
        gen = TestPlanGenerator(strategies=["branch"])
        plan = gen.generate(cmap)
        assert plan.test_suites == []


class TestBoundaryStrategy:
    """Tests for the BOUNDARY coverage strategy."""

    def test_boundary_tests_for_numeric_data(self):
        cmap = _make_coverage_map()
        cmap.paragraphs = [
            _make_paragraph("P", writes={"WS-AMOUNT"}, reads={"WS-INPUT"})
        ]
        cmap.data_items = [
            DataItemInfo(
                name="WS-AMOUNT",
                level=1,
                is_numeric=True,
                integer_digits=5,
                decimal_digits=2,
            ),
            DataItemInfo(
                name="WS-INPUT",
                level=1,
                is_numeric=True,
                integer_digits=5,
            ),
        ]
        gen = TestPlanGenerator(strategies=["boundary"])
        plan = gen.generate(cmap)
        suite = plan.test_suites[0]
        # 3 boundary types: zero, max, min
        assert len(suite.test_cases) == 3

    def test_non_numeric_excluded(self):
        cmap = _make_coverage_map()
        cmap.paragraphs = [_make_paragraph("P", writes={"WS-NAME"})]
        cmap.data_items = [DataItemInfo(name="WS-NAME", level=1, is_numeric=False)]
        gen = TestPlanGenerator(strategies=["boundary"])
        plan = gen.generate(cmap)
        assert plan.test_suites == []

    def test_boundary_zero_value(self):
        cmap = _make_coverage_map()
        cmap.paragraphs = [_make_paragraph("P", writes={"WS-NUM"})]
        cmap.data_items = [
            DataItemInfo(
                name="WS-NUM",
                level=1,
                is_numeric=True,
                integer_digits=3,
            )
        ]
        gen = TestPlanGenerator(strategies=["boundary"])
        plan = gen.generate(cmap)
        names = [tc.name for tc in plan.test_suites[0].test_cases]
        assert any("zero" in n for n in names)

    def test_boundary_max_value(self):
        cmap = _make_coverage_map()
        cmap.paragraphs = [_make_paragraph("P", writes={"WS-NUM"})]
        cmap.data_items = [
            DataItemInfo(
                name="WS-NUM",
                level=1,
                is_numeric=True,
                integer_digits=3,
            )
        ]
        gen = TestPlanGenerator(strategies=["boundary"])
        plan = gen.generate(cmap)
        names = [tc.name for tc in plan.test_suites[0].test_cases]
        assert any("max" in n for n in names)


class TestDataSetupInference:
    """Tests for _infer_data_setup logic."""

    def test_numeric_read_gets_zeros(self):
        cmap = _make_coverage_map()
        cmap.paragraphs = [_make_paragraph("P", reads={"WS-NUM"})]
        cmap.data_items = [DataItemInfo(name="WS-NUM", level=1, is_numeric=True)]
        gen = TestPlanGenerator(strategies=["paragraph"])
        plan = gen.generate(cmap)
        tc = plan.test_suites[0].test_cases[0]
        setups = {s.target_variable: s.value for s in tc.data_setup}
        assert setups["WS-NUM"] == "ZEROS"

    def test_alphanumeric_read_gets_spaces(self):
        cmap = _make_coverage_map()
        cmap.paragraphs = [_make_paragraph("P", reads={"WS-NAME"})]
        cmap.data_items = [DataItemInfo(name="WS-NAME", level=1, is_numeric=False)]
        gen = TestPlanGenerator(strategies=["paragraph"])
        plan = gen.generate(cmap)
        tc = plan.test_suites[0].test_cases[0]
        setups = {s.target_variable: s.value for s in tc.data_setup}
        assert setups["WS-NAME"] == "SPACES"

    def test_if_true_branch_gets_nonzero(self):
        bp = BranchPoint(
            branch_type=BranchType.IF_TRUE,
            parent_statement_type="IF",
            paragraph_name="P",
        )
        cmap = _make_coverage_map()
        cmap.paragraphs = [_make_paragraph("P", reads={"WS-FLAG"}, branch_points=[bp])]
        cmap.data_items = [DataItemInfo(name="WS-FLAG", level=1, is_numeric=True)]
        gen = TestPlanGenerator(strategies=["branch"])
        plan = gen.generate(cmap)
        # Find the IF TRUE test case
        tc_true = None
        for tc in plan.test_suites[0].test_cases:
            if tc.branch_point and tc.branch_point.branch_type == BranchType.IF_TRUE:
                tc_true = tc
                break
        assert tc_true is not None
        setups = {s.target_variable: s.value for s in tc_true.data_setup}
        assert setups["WS-FLAG"] == "1"

    def test_size_error_branch_gets_max(self):
        bp = BranchPoint(
            branch_type=BranchType.ARITH_SIZE_ERROR,
            parent_statement_type="ADD",
            paragraph_name="P",
        )
        cmap = _make_coverage_map()
        cmap.paragraphs = [_make_paragraph("P", reads={"WS-BIG"}, branch_points=[bp])]
        cmap.data_items = [
            DataItemInfo(
                name="WS-BIG",
                level=1,
                is_numeric=True,
                integer_digits=5,
            )
        ]
        gen = TestPlanGenerator(strategies=["branch"])
        plan = gen.generate(cmap)
        tc = plan.test_suites[0].test_cases[0]
        setups = {s.target_variable: s.value for s in tc.data_setup}
        assert setups["WS-BIG"] == "99999"


class TestExpectedOutcomeInference:
    """Tests for _infer_expected_outcomes logic."""

    def test_numeric_write_expects_numeric(self):
        cmap = _make_coverage_map()
        cmap.paragraphs = [_make_paragraph("P", writes={"WS-RESULT"})]
        cmap.data_items = [DataItemInfo(name="WS-RESULT", level=1, is_numeric=True)]
        gen = TestPlanGenerator(strategies=["paragraph"])
        plan = gen.generate(cmap)
        tc = plan.test_suites[0].test_cases[0]
        assert len(tc.expected_outcomes) == 1
        assert tc.expected_outcomes[0].variable == "WS-RESULT"
        assert tc.expected_outcomes[0].expected_value == "NUMERIC"
        assert tc.expected_outcomes[0].comparison == "TO BE"

    def test_non_numeric_write_no_outcome(self):
        cmap = _make_coverage_map()
        cmap.paragraphs = [_make_paragraph("P", writes={"WS-NAME"})]
        cmap.data_items = [DataItemInfo(name="WS-NAME", level=1, is_numeric=False)]
        gen = TestPlanGenerator(strategies=["paragraph"])
        plan = gen.generate(cmap)
        tc = plan.test_suites[0].test_cases[0]
        assert len(tc.expected_outcomes) == 0


class TestBoundaryValueGeneration:
    """Tests for boundary value computation."""

    def test_zero_boundary(self):
        gen = TestPlanGenerator()
        item = DataItemInfo(name="X", level=1, is_numeric=True, integer_digits=5)
        result = gen._generate_boundary_value(item, "zero")
        assert result == "0"

    def test_max_boundary_integer(self):
        gen = TestPlanGenerator()
        item = DataItemInfo(name="X", level=1, is_numeric=True, integer_digits=3)
        result = gen._generate_boundary_value(item, "max")
        assert result == "999"

    def test_max_boundary_with_decimals(self):
        gen = TestPlanGenerator()
        item = DataItemInfo(
            name="X",
            level=1,
            is_numeric=True,
            integer_digits=5,
            decimal_digits=2,
        )
        result = gen._generate_boundary_value(item, "max")
        assert result == "99999.99"

    def test_min_boundary_signed(self):
        gen = TestPlanGenerator()
        item = DataItemInfo(
            name="X",
            level=1,
            is_numeric=True,
            is_signed=True,
            integer_digits=3,
        )
        result = gen._generate_boundary_value(item, "min")
        assert result == "-999"

    def test_min_boundary_signed_with_decimals(self):
        gen = TestPlanGenerator()
        item = DataItemInfo(
            name="X",
            level=1,
            is_numeric=True,
            is_signed=True,
            integer_digits=3,
            decimal_digits=2,
        )
        result = gen._generate_boundary_value(item, "min")
        assert result == "-999.99"

    def test_min_boundary_unsigned(self):
        gen = TestPlanGenerator()
        item = DataItemInfo(name="X", level=1, is_numeric=True, integer_digits=3)
        result = gen._generate_boundary_value(item, "min")
        assert result == "0"

    def test_min_boundary_unsigned_with_decimals(self):
        gen = TestPlanGenerator()
        item = DataItemInfo(
            name="X",
            level=1,
            is_numeric=True,
            integer_digits=3,
            decimal_digits=2,
        )
        result = gen._generate_boundary_value(item, "min")
        assert result == "0.01"

    def test_unknown_boundary_type_returns_none(self):
        gen = TestPlanGenerator()
        item = DataItemInfo(name="X", level=1, is_numeric=True, integer_digits=3)
        result = gen._generate_boundary_value(item, "invalid")
        assert result is None


class TestSanitizeTestName:
    """Tests for _sanitize_test_name."""

    def test_normal_name_unchanged(self):
        gen = TestPlanGenerator()
        result = gen._sanitize_test_name("Should execute MAIN-LOGIC")
        assert result == "Should execute MAIN-LOGIC"

    def test_special_chars_removed(self):
        gen = TestPlanGenerator()
        result = gen._sanitize_test_name("Test with (parens) and {braces}")
        assert "(" not in result
        assert "{" not in result

    def test_long_name_truncated(self):
        gen = TestPlanGenerator()
        long_name = "A" * 200
        result = gen._sanitize_test_name(long_name)
        assert len(result) <= 120

    def test_multiple_spaces_collapsed(self):
        gen = TestPlanGenerator()
        result = gen._sanitize_test_name("Too   many   spaces")
        assert "  " not in result


class TestDataModels:
    """Tests for the data model classes."""

    def test_data_setup_defaults(self):
        ds = DataSetup(target_variable="WS-X", value="ZEROS")
        assert ds.comment is None

    def test_expected_outcome_default_comparison(self):
        eo = ExpectedOutcome(variable="WS-X", expected_value="NUMERIC")
        assert eo.comparison == "TO BE"

    def test_test_case_defaults(self):
        tc = TestCase(name="test", target_paragraph="P", strategy="paragraph")
        assert tc.data_setup == []
        assert tc.expected_outcomes == []
        assert tc.branch_point is None
        assert tc.comment is None

    def test_test_suite_defaults(self):
        ts = TestSuite(name="suite")
        assert ts.test_cases == []

    def test_test_plan_defaults(self):
        tp = TestPlan(program_name="PROG")
        assert tp.test_suites == []
        assert tp.total_test_cases == 0
        assert tp.coverage_strategies_used == []

    def test_coverage_strategy_values(self):
        assert CoverageStrategy.PARAGRAPH == "paragraph"
        assert CoverageStrategy.BRANCH == "branch"
        assert CoverageStrategy.BOUNDARY == "boundary"
