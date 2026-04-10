"""Integration tests for the CobolCheck generation pipeline.

End-to-end tests that parse real COBOL samples and verify
the generated .cut output has valid CobolCheck syntax.
"""

from pathlib import Path

import pytest

from cobolparser import generate_cobolcheck_tests, parse_cobol
from cobolparser.analysis.coverage_analyzer import CoverageAnalyzer
from cobolparser.analysis.test_plan import TestPlanGenerator
from cobolparser.generators.cobolcheck import CobolCheckGenerator


@pytest.fixture
def samples_dir() -> Path:
    return Path(__file__).parent.parent / "samples"


def _validate_cut_syntax(output: str) -> None:
    """Basic syntax validation of CobolCheck .cut output."""
    lines = output.strip().splitlines()
    if not lines:
        return  # Empty output is valid for no-procedure programs

    testsuite_count = 0
    testcase_count = 0

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("TESTSUITE"):
            testsuite_count += 1
            # Must be followed by a quoted string
            assert '"' in stripped, f"TESTSUITE missing quoted name: {stripped}"
        elif stripped.startswith("TESTCASE"):
            testcase_count += 1
            assert '"' in stripped, f"TESTCASE missing quoted name: {stripped}"
        elif stripped.startswith("EXPECT"):
            # EXPECT <var> <comparison> <value>
            parts = stripped.split()
            assert len(parts) >= 4, f"EXPECT too few parts: {stripped}"
        elif stripped.startswith("MOVE"):
            assert " TO " in stripped, f"MOVE missing TO: {stripped}"
        elif stripped.startswith("PERFORM"):
            parts = stripped.split()
            assert len(parts) >= 2, f"PERFORM missing target: {stripped}"

    # If there are testcases, there must be at least one testsuite
    if testcase_count > 0:
        assert testsuite_count >= 1


class TestEndToEndArithmetic:
    """End-to-end tests with arithmetic COBOL programs."""

    def test_arithmetic_operations_sample(self, samples_dir: Path):
        source = (samples_dir / "arithmetic_operations.cbl").read_text()
        output = generate_cobolcheck_tests(source)
        _validate_cut_syntax(output)
        assert "TESTSUITE" in output
        assert "TESTCASE" in output
        assert "PERFORM" in output

    def test_arithmetic_has_paragraph_tests(self, samples_dir: Path):
        source = (samples_dir / "arithmetic_operations.cbl").read_text()
        output = generate_cobolcheck_tests(source, strategies=["paragraph"])
        # Should generate tests for ADD-TESTS, SUBTRACT-TESTS, etc.
        assert "PERFORM" in output
        _validate_cut_syntax(output)


class TestEndToEndPipeline:
    """Tests that verify the individual pipeline steps work together."""

    def test_full_pipeline_manual(self, samples_dir: Path):
        source = (samples_dir / "arithmetic_operations.cbl").read_text()
        result = parse_cobol(source)
        assert result.ast is not None

        analyzer = CoverageAnalyzer()
        cmap = analyzer.analyze(result.ast)
        assert cmap.has_procedure_division is True
        assert cmap.total_paragraphs > 0

        planner = TestPlanGenerator()
        plan = planner.generate(cmap)
        assert plan.total_test_cases > 0

        generator = CobolCheckGenerator()
        output = generator.generate(plan)
        _validate_cut_syntax(output)
        assert len(output) > 0

    def test_pipeline_branch_strategy(self, samples_dir: Path):
        source = (samples_dir / "arithmetic_operations.cbl").read_text()
        result = parse_cobol(source)
        assert result.ast is not None

        analyzer = CoverageAnalyzer()
        cmap = analyzer.analyze(result.ast)

        planner = TestPlanGenerator(strategies=["branch"])
        plan = planner.generate(cmap)

        if plan.total_test_cases > 0:
            generator = CobolCheckGenerator()
            output = generator.generate(plan)
            _validate_cut_syntax(output)
            assert "TESTSUITE" in output

    def test_pipeline_boundary_strategy(self, samples_dir: Path):
        source = (samples_dir / "arithmetic_operations.cbl").read_text()
        result = parse_cobol(source)
        assert result.ast is not None

        analyzer = CoverageAnalyzer()
        cmap = analyzer.analyze(result.ast)

        planner = TestPlanGenerator(strategies=["boundary"])
        plan = planner.generate(cmap)

        generator = CobolCheckGenerator()
        output = generator.generate(plan)
        _validate_cut_syntax(output)


class TestEndToEndCallPrograms:
    """End-to-end tests with CALL-based COBOL programs."""

    def test_call_banking_sample(self, samples_dir: Path):
        path = samples_dir / "call_banking_system.cbl"
        if not path.exists():
            pytest.skip("Sample not available")
        source = path.read_text()
        output = generate_cobolcheck_tests(source)
        _validate_cut_syntax(output)
        assert "TESTSUITE" in output

    def test_call_exception_handlers(self, samples_dir: Path):
        path = samples_dir / "call_exception_handlers_complete.cbl"
        if not path.exists():
            pytest.skip("Sample not available")
        source = path.read_text()
        output = generate_cobolcheck_tests(source)
        _validate_cut_syntax(output)


class TestEndToEndNoComments:
    """Test generation without comments."""

    def test_no_comments_mode(self, samples_dir: Path):
        source = (samples_dir / "arithmetic_operations.cbl").read_text()
        result = parse_cobol(source)
        assert result.ast is not None

        analyzer = CoverageAnalyzer()
        cmap = analyzer.analyze(result.ast)

        planner = TestPlanGenerator()
        plan = planner.generate(cmap)

        generator = CobolCheckGenerator(include_comments=False)
        output = generator.generate(plan)
        assert "*>" not in output
        _validate_cut_syntax(output)


class TestEndToEndCoverageMap:
    """Integration tests for coverage analysis of real programs."""

    def test_arithmetic_data_items_extracted(self, samples_dir: Path):
        source = (samples_dir / "arithmetic_operations.cbl").read_text()
        result = parse_cobol(source)
        assert result.ast is not None

        analyzer = CoverageAnalyzer()
        cmap = analyzer.analyze(result.ast)

        # Should have numeric data items from WORKING-STORAGE
        assert len(cmap.data_items) > 0
        numeric_items = [d for d in cmap.data_items if d.is_numeric]
        assert len(numeric_items) > 0

    def test_arithmetic_branch_points_detected(self, samples_dir: Path):
        source = (samples_dir / "arithmetic_operations.cbl").read_text()
        result = parse_cobol(source)
        assert result.ast is not None

        analyzer = CoverageAnalyzer()
        cmap = analyzer.analyze(result.ast)

        # The arithmetic sample has ON SIZE ERROR clauses
        assert cmap.total_branch_points > 0

    def test_program_name_extracted(self, samples_dir: Path):
        source = (samples_dir / "arithmetic_operations.cbl").read_text()
        result = parse_cobol(source)
        assert result.ast is not None

        analyzer = CoverageAnalyzer()
        cmap = analyzer.analyze(result.ast)
        assert cmap.program_name == "ARITHOPS"
