"""
Test plan generator for CobolCheck test suites.

Takes a CoverageMap produced by CoverageAnalyzer and generates a structured
TestPlan with test cases targeting paragraph, branch, and boundary coverage.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum

from .coverage_analyzer import BranchPoint, BranchType, CoverageMap, DataItemInfo


class CoverageStrategy(StrEnum):
    """Strategy for generating test cases."""

    PARAGRAPH = "paragraph"
    BRANCH = "branch"
    BOUNDARY = "boundary"


@dataclass
class DataSetup:
    """A single MOVE statement to set up test data."""

    target_variable: str
    value: str
    comment: str | None = None


@dataclass
class ExpectedOutcome:
    """An EXPECT assertion for the test case."""

    variable: str
    expected_value: str
    comparison: str = "TO BE"


@dataclass
class TestCase:
    """A single CobolCheck test case."""

    name: str
    target_paragraph: str
    strategy: str
    data_setup: list[DataSetup] = field(default_factory=list)
    expected_outcomes: list[ExpectedOutcome] = field(default_factory=list)
    branch_point: BranchPoint | None = None
    comment: str | None = None


@dataclass
class TestSuite:
    """A named group of test cases (TESTSUITE)."""

    name: str
    test_cases: list[TestCase] = field(default_factory=list)


@dataclass
class TestPlan:
    """Complete test plan for a COBOL program."""

    program_name: str
    test_suites: list[TestSuite] = field(default_factory=list)
    total_test_cases: int = 0
    coverage_strategies_used: list[str] = field(default_factory=list)


_ALL_STRATEGIES = [
    CoverageStrategy.PARAGRAPH,
    CoverageStrategy.BRANCH,
    CoverageStrategy.BOUNDARY,
]


class TestPlanGenerator:
    """Generates a TestPlan from a CoverageMap."""

    def __init__(
        self,
        strategies: list[str] | None = None,
    ) -> None:
        if strategies is None:
            self._strategies = list(_ALL_STRATEGIES)
        else:
            self._strategies = [CoverageStrategy(s) for s in strategies]

    def generate(self, coverage_map: CoverageMap) -> TestPlan:
        """Generate a test plan from a coverage map."""
        plan = TestPlan(program_name=coverage_map.program_name)

        if not coverage_map.has_procedure_division:
            return plan

        if CoverageStrategy.PARAGRAPH in self._strategies:
            suite = self._generate_paragraph_tests(coverage_map)
            if suite.test_cases:
                plan.test_suites.append(suite)
                plan.coverage_strategies_used.append(CoverageStrategy.PARAGRAPH)

        if CoverageStrategy.BRANCH in self._strategies:
            suite = self._generate_branch_tests(coverage_map)
            if suite.test_cases:
                plan.test_suites.append(suite)
                plan.coverage_strategies_used.append(CoverageStrategy.BRANCH)

        if CoverageStrategy.BOUNDARY in self._strategies:
            suite = self._generate_boundary_tests(coverage_map)
            if suite.test_cases:
                plan.test_suites.append(suite)
                plan.coverage_strategies_used.append(CoverageStrategy.BOUNDARY)

        plan.total_test_cases = sum(len(s.test_cases) for s in plan.test_suites)
        return plan

    def _generate_paragraph_tests(self, coverage_map: CoverageMap) -> TestSuite:
        """Generate one test case per paragraph for basic execution coverage."""
        suite = TestSuite(name=f"Paragraph coverage for {coverage_map.program_name}")

        for para in coverage_map.paragraphs:
            if para.is_empty:
                continue
            if not para.paragraph_name.strip():
                continue
            if (para.has_stop_run or para.has_goback) and para.statement_count == 1:
                continue

            data_setup = self._infer_data_setup(para.paragraph_name, coverage_map)
            expected = self._infer_expected_outcomes(para.paragraph_name, coverage_map)

            tc = TestCase(
                name=f"Should execute {para.paragraph_name}",
                target_paragraph=para.paragraph_name,
                strategy=CoverageStrategy.PARAGRAPH,
                data_setup=data_setup,
                expected_outcomes=expected,
            )
            suite.test_cases.append(tc)

        return suite

    def _generate_branch_tests(self, coverage_map: CoverageMap) -> TestSuite:
        """Generate test cases targeting each branch point."""
        suite = TestSuite(name=f"Branch coverage for {coverage_map.program_name}")
        used_names: dict[str, int] = {}

        for para in coverage_map.paragraphs:
            if not para.paragraph_name.strip():
                continue
            for bp in para.branch_points:
                name = self._branch_test_name(bp)
                # Deduplicate: paragraphs with many IFs produce
                # identical branch names; append a counter.
                count = used_names.get(name, 0) + 1
                used_names[name] = count
                if count > 1:
                    name = f"{name} {count}"
                data_setup = self._infer_data_setup(
                    para.paragraph_name, coverage_map, target_branch=bp
                )
                expected = self._infer_expected_outcomes(
                    para.paragraph_name, coverage_map, target_branch=bp
                )
                comment = None
                if bp.branch_type in (
                    BranchType.IO_AT_END,
                    BranchType.IO_INVALID_KEY,
                    BranchType.IO_NOT_AT_END,
                    BranchType.IO_NOT_INVALID_KEY,
                    BranchType.IO_AT_EOP,
                ):
                    comment = (
                        "NOTE: Requires file setup for "
                        f"{bp.branch_type.upper()} condition"
                    )
                elif bp.branch_type in (
                    BranchType.CALL_ON_EXCEPTION,
                    BranchType.CALL_NOT_ON_EXCEPTION,
                ):
                    comment = (
                        "NOTE: Requires called program to be "
                        "absent/present for exception testing"
                    )

                tc = TestCase(
                    name=name,
                    target_paragraph=para.paragraph_name,
                    strategy=CoverageStrategy.BRANCH,
                    data_setup=data_setup,
                    expected_outcomes=expected,
                    branch_point=bp,
                    comment=comment,
                )
                suite.test_cases.append(tc)

        return suite

    def _generate_boundary_tests(self, coverage_map: CoverageMap) -> TestSuite:
        """Generate boundary value tests for numeric data items."""
        suite = TestSuite(name=f"Boundary value tests for {coverage_map.program_name}")

        # Find paragraphs that write to numeric items
        tested_items: set[str] = set()
        for para in coverage_map.paragraphs:
            if para.is_empty or not para.paragraph_name.strip():
                continue
            for var_name in para.writes_variables:
                if var_name in tested_items:
                    continue
                item = coverage_map.get_data_item(var_name)
                if item is None or not item.is_numeric:
                    continue
                tested_items.add(var_name)

                for boundary_type in ("zero", "max", "min"):
                    boundary_val = self._generate_boundary_value(item, boundary_type)
                    if boundary_val is None:
                        continue

                    # Set up all reads for the paragraph with the boundary value
                    data_setup: list[DataSetup] = []
                    for read_var in para.reads_variables:
                        read_item = coverage_map.get_data_item(read_var)
                        if read_item is not None and read_item.is_numeric:
                            data_setup.append(
                                DataSetup(
                                    target_variable=read_var,
                                    value=boundary_val,
                                    comment=f"Boundary: {boundary_type}",
                                )
                            )
                        elif read_item is not None:
                            data_setup.append(
                                DataSetup(
                                    target_variable=read_var,
                                    value="SPACES",
                                )
                            )

                    tc = TestCase(
                        name=(
                            f"Should handle {boundary_type} value "
                            f"for {var_name} in {para.paragraph_name}"
                        ),
                        target_paragraph=para.paragraph_name,
                        strategy=CoverageStrategy.BOUNDARY,
                        data_setup=data_setup,
                        expected_outcomes=[
                            ExpectedOutcome(
                                variable=var_name,
                                expected_value="NUMERIC",
                                comparison="TO BE",
                            )
                        ],
                    )
                    suite.test_cases.append(tc)

        return suite

    def _infer_data_setup(
        self,
        paragraph_name: str,
        coverage_map: CoverageMap,
        target_branch: BranchPoint | None = None,
    ) -> list[DataSetup]:
        """Infer what data setup is needed to execute a paragraph."""
        para = coverage_map.get_paragraph(paragraph_name)
        if para is None:
            return []

        setup: list[DataSetup] = []
        for var_name in sorted(para.reads_variables):
            item = coverage_map.get_data_item(var_name)
            if item is None:
                continue
            if item.is_numeric:
                value = "ZEROS"
                if (
                    target_branch is not None
                    and target_branch.branch_type == BranchType.IF_TRUE
                ):
                    value = "1"
                elif (
                    target_branch is not None
                    and target_branch.branch_type == BranchType.IF_FALSE
                ):
                    value = "ZEROS"
                elif (
                    target_branch is not None
                    and target_branch.branch_type == BranchType.ARITH_SIZE_ERROR
                ):
                    value = self._generate_boundary_value(item, "max") or "99999"
                setup.append(DataSetup(target_variable=var_name, value=value))
            else:
                setup.append(DataSetup(target_variable=var_name, value="SPACES"))

        return setup

    def _infer_expected_outcomes(
        self,
        paragraph_name: str,
        coverage_map: CoverageMap,
        target_branch: BranchPoint | None = None,
    ) -> list[ExpectedOutcome]:
        """Infer expected outcomes after performing a paragraph."""
        para = coverage_map.get_paragraph(paragraph_name)
        if para is None:
            return []

        outcomes: list[ExpectedOutcome] = []
        for var_name in sorted(para.writes_variables):
            item = coverage_map.get_data_item(var_name)
            if item is not None and item.is_numeric:
                outcomes.append(
                    ExpectedOutcome(
                        variable=var_name,
                        expected_value="NUMERIC",
                        comparison="TO BE",
                    )
                )

        return outcomes

    def _generate_boundary_value(
        self, data_item: DataItemInfo, boundary_type: str
    ) -> str | None:
        """Generate a boundary value for a numeric data item."""
        int_digits = data_item.integer_digits or 5
        dec_digits = data_item.decimal_digits or 0

        if boundary_type == "zero":
            return "0"
        elif boundary_type == "max":
            int_part = "9" * int_digits
            if dec_digits > 0:
                return f"{int_part}.{'9' * dec_digits}"
            return int_part
        elif boundary_type == "min":
            if data_item.is_signed:
                int_part = "9" * int_digits
                if dec_digits > 0:
                    return f"-{int_part}.{'9' * dec_digits}"
                return f"-{int_part}"
            else:
                if dec_digits > 0:
                    return f"0.{'0' * (dec_digits - 1)}1"
                return "0"
        return None

    def _branch_test_name(self, bp: BranchPoint) -> str:
        """Generate a descriptive test name for a branch point."""
        type_labels = {
            BranchType.IF_TRUE: "IF true branch",
            BranchType.IF_FALSE: "IF false branch",
            BranchType.EVALUATE_WHEN: "EVALUATE WHEN",
            BranchType.EVALUATE_DEFAULT: "EVALUATE WHEN OTHER",
            BranchType.SEARCH_WHEN: "SEARCH WHEN",
            BranchType.SEARCH_AT_END: "SEARCH AT END",
            BranchType.IO_AT_END: "AT END",
            BranchType.IO_NOT_AT_END: "NOT AT END",
            BranchType.IO_INVALID_KEY: "INVALID KEY",
            BranchType.IO_NOT_INVALID_KEY: "NOT INVALID KEY",
            BranchType.IO_AT_EOP: "AT END-OF-PAGE",
            BranchType.ARITH_SIZE_ERROR: "ON SIZE ERROR",
            BranchType.ARITH_NOT_SIZE_ERROR: "NOT ON SIZE ERROR",
            BranchType.CALL_ON_EXCEPTION: "ON EXCEPTION",
            BranchType.CALL_NOT_ON_EXCEPTION: "NOT ON EXCEPTION",
            BranchType.STRING_ON_OVERFLOW: "ON OVERFLOW",
            BranchType.STRING_NOT_ON_OVERFLOW: "NOT ON OVERFLOW",
            BranchType.PERFORM_BODY: "PERFORM body",
        }
        label = type_labels.get(bp.branch_type, bp.branch_type.value)
        name = f"Should take {label} in {bp.paragraph_name}"
        return self._sanitize_test_name(name)

    def _sanitize_test_name(self, name: str) -> str:
        """Sanitize a string for use in a TESTCASE description."""
        # Replace any characters that aren't safe in COBOL string literals
        cleaned = re.sub(r"[^\w\s\-./]", "", name)
        # Collapse multiple spaces
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        # Truncate to reasonable length
        if len(cleaned) > 120:
            cleaned = cleaned[:117] + "..."
        return cleaned
