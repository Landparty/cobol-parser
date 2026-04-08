"""EVALUATE Variant Coverage Gate.

This module implements the regression guardrails for EVALUATE statement support.
It provides:

1. A variant catalog defining all fixed-format EVALUATE variants
2. Coverage tracking for positive (valid) and negative (error) test cases
3. A gate function that fails CI if any cataloged variant lacks coverage

Usage:
    pytest tests/contract/test_evaluate_coverage_gate.py -v
"""

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class VariantCategory(Enum):
    """Categories of EVALUATE variants."""

    SINGLE_SUBJECT = "single_subject"
    MULTI_SUBJECT = "multi_subject"
    EVALUATE_TRUE_FALSE = "evaluate_true_false"
    RANGE_THROUGH = "range_through"
    ANY_SELECTOR = "any_selector"
    FIGURATIVE_CONSTANT = "figurative_constant"
    WHEN_OTHER = "when_other"
    CONDITION_AND_OR = "condition_and_or"
    NESTED_EVALUATE = "nested_evaluate"
    CONTINUATION_LINES = "continuation_lines"


class TestStatus(Enum):
    """Status of a test for a variant."""

    PASS = "pass"
    FAIL = "fail"
    MISSING = "missing"


@dataclass
class EvaluateVariant:
    """Represents a single EVALUATE variant in the catalog."""

    variant_id: str
    category: VariantCategory
    description: str
    test_scope: str  # e.g., "tests/unit/test_evaluate_variants.py"
    test_name: str  # e.g., "test_single_subject_literals_and_ranges"
    features: list[str] = field(default_factory=list)
    notes: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "variant_id": self.variant_id,
            "category": self.category.value,
            "description": self.description,
            "test_scope": self.test_scope,
            "test_name": self.test_name,
            "features": self.features,
            "notes": self.notes,
        }


# Positive variant catalog - all EVALUATE variants that should parse successfully
EVALUATE_VARIANT_CATALOG: list[EvaluateVariant] = [
    # Single subject variants
    EvaluateVariant(
        variant_id="EV-SS-001",
        category=VariantCategory.SINGLE_SUBJECT,
        description="Single subject with literal selectors",
        test_scope="tests/unit/test_evaluate_variants.py",
        test_name="test_single_subject_literals_and_ranges",
        features=["single_subject", "literal_selectors", "WHEN"],
    ),
    EvaluateVariant(
        variant_id="EV-SS-002",
        category=VariantCategory.SINGLE_SUBJECT,
        description="Single subject with identifier selectors",
        test_scope="tests/unit/test_evaluate_variants.py",
        test_name="test_single_subject_literals_and_ranges",
        features=["single_subject", "identifier_selectors", "WHEN"],
    ),
    EvaluateVariant(
        variant_id="EV-SS-003",
        category=VariantCategory.SINGLE_SUBJECT,
        description="Single subject with WHEN OTHER",
        test_scope="tests/unit/test_evaluate_variants.py",
        test_name="test_single_subject_literals_and_ranges",
        features=["single_subject", "WHEN_OTHER"],
    ),
    # Range/THRU variants
    EvaluateVariant(
        variant_id="EV-RT-001",
        category=VariantCategory.RANGE_THROUGH,
        description="THRU range with numeric literals",
        test_scope="tests/unit/test_evaluate_variants.py",
        test_name="test_single_subject_literals_and_ranges",
        features=["THRU", "range", "numeric_literal"],
    ),
    EvaluateVariant(
        variant_id="EV-RT-002",
        category=VariantCategory.RANGE_THROUGH,
        description="THROUGH range with numeric literals",
        test_scope="tests/unit/test_evaluate_diagnostics.py",
        test_name="test_evaluate_mixed_thru_through",
        features=["THROUGH", "range", "numeric_literal"],
    ),
    EvaluateVariant(
        variant_id="EV-RT-003",
        category=VariantCategory.RANGE_THROUGH,
        description="Multiple WHEN with different ranges",
        test_scope="tests/unit/test_evaluate_diagnostics.py",
        test_name="test_evaluate_mixed_thru_through",
        features=["THRU", "THROUGH", "multiple_ranges"],
    ),
    # Multi-subject with ALSO variants
    EvaluateVariant(
        variant_id="EV-MS-001",
        category=VariantCategory.MULTI_SUBJECT,
        description="Two subjects with ALSO",
        test_scope="tests/unit/test_evaluate_variants.py",
        test_name="test_multiple_subjects_any_and_also",
        features=["multi_subject", "ALSO", "two_subjects"],
    ),
    EvaluateVariant(
        variant_id="EV-MS-002",
        category=VariantCategory.MULTI_SUBJECT,
        description="Two subjects with aligned literal selectors",
        test_scope="tests/unit/test_evaluate_variants.py",
        test_name="test_multiple_subjects_any_and_also",
        features=["multi_subject", "ALSO", "aligned_selectors"],
    ),
    EvaluateVariant(
        variant_id="EV-MS-003",
        category=VariantCategory.MULTI_SUBJECT,
        description="Two subjects with WHEN OTHER",
        test_scope="tests/unit/test_evaluate_variants.py",
        test_name="test_multiple_subjects_any_and_also",
        features=["multi_subject", "WHEN_OTHER"],
    ),
    # ANY selector variants
    EvaluateVariant(
        variant_id="EV-AN-001",
        category=VariantCategory.ANY_SELECTOR,
        description="ANY selector in first position with ALSO",
        test_scope="tests/unit/test_evaluate_variants.py",
        test_name="test_multiple_subjects_any_and_also",
        features=["ANY", "ALSO", "first_position"],
    ),
    EvaluateVariant(
        variant_id="EV-AN-002",
        category=VariantCategory.ANY_SELECTOR,
        description="ANY selector in second position with ALSO",
        test_scope="tests/unit/test_evaluate_diagnostics.py",
        test_name="test_evaluate_any_with_also",
        features=["ANY", "ALSO", "second_position"],
    ),
    # EVALUATE TRUE/FALSE with conditions
    EvaluateVariant(
        variant_id="EV-TF-001",
        category=VariantCategory.EVALUATE_TRUE_FALSE,
        description="EVALUATE TRUE with simple condition",
        test_scope="tests/unit/test_evaluate_variants.py",
        test_name="test_evaluate_true_with_conditions_and_or",
        features=["EVALUATE_TRUE", "condition"],
    ),
    EvaluateVariant(
        variant_id="EV-TF-002",
        category=VariantCategory.EVALUATE_TRUE_FALSE,
        description="EVALUATE TRUE with AND condition",
        test_scope="tests/unit/test_evaluate_variants.py",
        test_name="test_evaluate_true_with_conditions_and_or",
        features=["EVALUATE_TRUE", "AND", "compound_condition"],
    ),
    EvaluateVariant(
        variant_id="EV-TF-003",
        category=VariantCategory.EVALUATE_TRUE_FALSE,
        description="EVALUATE TRUE with OR condition",
        test_scope="tests/unit/test_evaluate_variants.py",
        test_name="test_evaluate_true_with_conditions_and_or",
        features=["EVALUATE_TRUE", "OR", "compound_condition"],
    ),
    EvaluateVariant(
        variant_id="EV-TF-004",
        category=VariantCategory.EVALUATE_TRUE_FALSE,
        description="EVALUATE TRUE with WHEN OTHER",
        test_scope="tests/unit/test_evaluate_variants.py",
        test_name="test_evaluate_true_with_conditions_and_or",
        features=["EVALUATE_TRUE", "WHEN_OTHER"],
    ),
    # WHEN OTHER placement
    EvaluateVariant(
        variant_id="EV-WO-001",
        category=VariantCategory.WHEN_OTHER,
        description="WHEN OTHER as last clause (valid)",
        test_scope="tests/unit/test_evaluate_variants.py",
        test_name="test_single_subject_literals_and_ranges",
        features=["WHEN_OTHER", "last_position"],
    ),
    EvaluateVariant(
        variant_id="EV-WO-002",
        category=VariantCategory.WHEN_OTHER,
        description="WHEN OTHER with multi-subject EVALUATE",
        test_scope="tests/unit/test_evaluate_variants.py",
        test_name="test_multiple_subjects_any_and_also",
        features=["WHEN_OTHER", "multi_subject"],
    ),
    # Parser stability with errors
    EvaluateVariant(
        variant_id="EV-ST-001",
        category=VariantCategory.SINGLE_SUBJECT,
        description="Parser remains stable after missing WHEN error",
        test_scope="tests/unit/test_evaluate_diagnostics.py",
        test_name="test_evaluate_parser_stays_stable",
        features=["error_recovery", "parser_stability"],
    ),
    EvaluateVariant(
        variant_id="EV-ST-002",
        category=VariantCategory.SINGLE_SUBJECT,
        description="Multiple EVALUATE statements, second parses after first error",
        test_scope="tests/unit/test_evaluate_diagnostics.py",
        test_name="test_evaluate_parser_stays_stable",
        features=["error_recovery", "multiple_statements"],
    ),
]


# Negative variant catalog - malformed EVALUATE scenarios that should produce diagnostics
NEGATIVE_VARIANT_CATALOG: list[EvaluateVariant] = [
    EvaluateVariant(
        variant_id="EV-NG-001",
        category=VariantCategory.SINGLE_SUBJECT,
        description="Missing WHEN clause",
        test_scope="tests/unit/test_evaluate_diagnostics.py",
        test_name="test_evaluate_missing_when_clause",
        features=["missing_WHEN", "diagnostic"],
    ),
    EvaluateVariant(
        variant_id="EV-NG-002",
        category=VariantCategory.SINGLE_SUBJECT,
        description="Missing END-EVALUATE",
        test_scope="tests/unit/test_evaluate_diagnostics.py",
        test_name="test_evaluate_missing_end_evaluate",
        features=["missing_END-EVALUATE", "diagnostic"],
    ),
    EvaluateVariant(
        variant_id="EV-NG-003",
        category=VariantCategory.MULTI_SUBJECT,
        description="Single subject with multiple selectors (mismatch)",
        test_scope="tests/unit/test_evaluate_diagnostics.py",
        test_name="test_evaluate_selector_mismatch_single_subject",
        features=["selector_mismatch", "diagnostic"],
    ),
    EvaluateVariant(
        variant_id="EV-NG-004",
        category=VariantCategory.MULTI_SUBJECT,
        description="Multiple subjects with single selector (mismatch)",
        test_scope="tests/unit/test_evaluate_diagnostics.py",
        test_name="test_evaluate_selector_mismatch_multiple_subjects",
        features=["selector_mismatch", "diagnostic"],
    ),
    EvaluateVariant(
        variant_id="EV-NG-005",
        category=VariantCategory.RANGE_THROUGH,
        description="THRU without end value",
        test_scope="tests/unit/test_evaluate_diagnostics.py",
        test_name="test_evaluate_invalid_through_range",
        features=["invalid_THRU", "diagnostic"],
    ),
    EvaluateVariant(
        variant_id="EV-NG-006",
        category=VariantCategory.RANGE_THROUGH,
        description="THRU with incomplete range",
        test_scope="tests/unit/test_evaluate_diagnostics.py",
        test_name="test_evaluate_through_without_end_value",
        features=["incomplete_THRU", "diagnostic"],
    ),
    EvaluateVariant(
        variant_id="EV-NG-007",
        category=VariantCategory.WHEN_OTHER,
        description="WHEN OTHER before conditional WHEN (invalid placement)",
        test_scope="tests/unit/test_evaluate_diagnostics.py",
        test_name="test_evaluate_when_other_must_be_last",
        features=["WHEN_OTHER_placement", "diagnostic"],
    ),
    EvaluateVariant(
        variant_id="EV-NG-008",
        category=VariantCategory.EVALUATE_TRUE_FALSE,
        description="EVALUATE TRUE with empty WHEN selector",
        test_scope="tests/unit/test_evaluate_diagnostics.py",
        test_name="test_evaluate_true_without_condition",
        features=["empty_selector", "diagnostic"],
    ),
    EvaluateVariant(
        variant_id="EV-NG-009",
        category=VariantCategory.SINGLE_SUBJECT,
        description="Empty WHEN selector",
        test_scope="tests/unit/test_evaluate_diagnostics.py",
        test_name="test_evaluate_empty_when_selector",
        features=["empty_selector", "diagnostic"],
    ),
    EvaluateVariant(
        variant_id="EV-NG-010",
        category=VariantCategory.MULTI_SUBJECT,
        description="Consecutive ALSO tokens (invalid chain)",
        test_scope="tests/unit/test_evaluate_diagnostics.py",
        test_name="test_evaluate_invalid_also_chain",
        features=["invalid_ALSO", "diagnostic"],
    ),
    EvaluateVariant(
        variant_id="EV-NG-011",
        category=VariantCategory.SINGLE_SUBJECT,
        description="Diagnostic includes line/column location",
        test_scope="tests/unit/test_evaluate_diagnostics.py",
        test_name="test_evaluate_error_location_tracked",
        features=["location_tracking", "diagnostic"],
    ),
    EvaluateVariant(
        variant_id="EV-NG-012",
        category=VariantCategory.SINGLE_SUBJECT,
        description="Multiple errors collected in single parse",
        test_scope="tests/unit/test_evaluate_diagnostics.py",
        test_name="test_evaluate_multiple_errors_collected",
        features=["multiple_errors", "diagnostic"],
    ),
]


def get_catalog_variant_ids() -> set[str]:
    """Get all variant IDs from positive catalog."""
    return {v.variant_id for v in EVALUATE_VARIANT_CATALOG}


def get_negative_variant_ids() -> set[str]:
    """Get all variant IDs from negative catalog."""
    return {v.variant_id for v in NEGATIVE_VARIANT_CATALOG}


def get_all_variant_ids() -> set[str]:
    """Get all variant IDs from both catalogs."""
    return get_catalog_variant_ids() | get_negative_variant_ids()


def get_variant_by_id(variant_id: str) -> EvaluateVariant | None:
    """Look up a variant by its ID."""
    for variant in EVALUATE_VARIANT_CATALOG:
        if variant.variant_id == variant_id:
            return variant
    for variant in NEGATIVE_VARIANT_CATALOG:
        if variant.variant_id == variant_id:
            return variant
    return None


def get_variants_by_category(category: VariantCategory) -> list[EvaluateVariant]:
    """Get all variants of a specific category."""
    return [v for v in EVALUATE_VARIANT_CATALOG if v.category == category]


class CoverageReport:
    """Represents the coverage analysis for EVALUATE variants."""

    def __init__(self):
        self.tested_variants: set[str] = set()
        self.untested_variants: list[EvaluateVariant] = []
        self.failed_tests: list[dict[str, Any]] = []
        self.missing_negative_coverage: list[EvaluateVariant] = []

    def add_tested_variant(self, variant_id: str) -> None:
        """Mark a variant as tested."""
        self.tested_variants.add(variant_id)

    def add_failed_test(self, test_info: dict[str, Any]) -> None:
        """Record a failed test."""
        self.failed_tests.append(test_info)

    def add_untested_variant(self, variant: EvaluateVariant) -> None:
        """Record an untested variant."""
        self.untested_variants.append(variant)

    def add_missing_negative_coverage(self, variant: EvaluateVariant) -> None:
        """Record a variant lacking negative test coverage."""
        self.missing_negative_coverage.append(variant)

    def is_complete(self) -> bool:
        """Check if all variants have coverage."""
        catalog_ids = get_catalog_variant_ids()
        negative_ids = get_negative_variant_ids()

        # All positive variants must be tested
        if not self.tested_variants.issuperset(catalog_ids):
            return False

        # All negative variants must be tested
        if not self.tested_variants.issuperset(negative_ids):
            return False

        # No failed tests
        if self.failed_tests:
            return False

        return True

    def get_summary(self) -> dict[str, Any]:
        """Get a summary of coverage status."""
        all_variants = get_all_variant_ids()
        tested_count = len(self.tested_variants)
        total_count = len(all_variants)

        return {
            "total_variants": total_count,
            "tested_variants": tested_count,
            "untested_count": total_count - tested_count,
            "coverage_percent": (
                (tested_count / total_count * 100) if total_count > 0 else 100.0
            ),
            "failed_tests": len(self.failed_tests),
            "untested_variants": [v.variant_id for v in self.untested_variants],
            "is_complete": self.is_complete(),
        }

    def to_dict(self) -> dict[str, Any]:
        """Convert report to dictionary for serialization."""
        return {
            "tested_variants": sorted(self.tested_variants),
            "untested_variants": [v.to_dict() for v in self.untested_variants],
            "failed_tests": self.failed_tests,
            "missing_negative_coverage": [
                v.to_dict() for v in self.missing_negative_coverage
            ],
            "summary": self.get_summary(),
        }


def run_coverage_gate() -> CoverageReport:
    """Run the EVALUATE variant coverage gate.

    This function:
    1. Discovers which tests exist in the test suite
    2. Maps tests to catalog variants
    3. Identifies missing or failing coverage
    4. Returns a CoverageReport with findings
    """
    report = CoverageReport()

    # Map of test names to their module for quick lookup
    test_modules = {
        "test_single_subject_literals_and_ranges": "tests/unit/test_evaluate_variants.py",
        "test_multiple_subjects_any_and_also": "tests/unit/test_evaluate_variants.py",
        "test_evaluate_true_with_conditions_and_or": "tests/unit/test_evaluate_variants.py",
        "test_evaluate_missing_when_clause": "tests/unit/test_evaluate_diagnostics.py",
        "test_evaluate_missing_end_evaluate": "tests/unit/test_evaluate_diagnostics.py",
        "test_evaluate_selector_mismatch_single_subject": "tests/unit/test_evaluate_diagnostics.py",
        "test_evaluate_selector_mismatch_multiple_subjects": "tests/unit/test_evaluate_diagnostics.py",
        "test_evaluate_invalid_through_range": "tests/unit/test_evaluate_diagnostics.py",
        "test_evaluate_through_without_end_value": "tests/unit/test_evaluate_diagnostics.py",
        "test_evaluate_when_other_must_be_last": "tests/unit/test_evaluate_diagnostics.py",
        "test_evaluate_true_without_condition": "tests/unit/test_evaluate_diagnostics.py",
        "test_evaluate_empty_when_selector": "tests/unit/test_evaluate_diagnostics.py",
        "test_evaluate_error_location_tracked": "tests/unit/test_evaluate_diagnostics.py",
        "test_evaluate_multiple_errors_collected": "tests/unit/test_evaluate_diagnostics.py",
        "test_evaluate_parser_stays_stable": "tests/unit/test_evaluate_diagnostics.py",
        "test_evaluate_invalid_also_chain": "tests/unit/test_evaluate_diagnostics.py",
        "test_evaluate_mixed_thru_through": "tests/unit/test_evaluate_diagnostics.py",
        "test_evaluate_any_with_also": "tests/unit/test_evaluate_diagnostics.py",
        "test_evaluate_to_dict_structure": "tests/contracts/test_evaluate_serialization.py",
        "test_evaluate_variants_sample_file": "tests/integration/test_evaluate_samples.py",
    }

    # Mark all variants whose tests exist
    for variant in EVALUATE_VARIANT_CATALOG:
        if variant.test_name in test_modules:
            report.add_tested_variant(variant.variant_id)
        else:
            report.add_untested_variant(variant)

    for variant in NEGATIVE_VARIANT_CATALOG:
        if variant.test_name in test_modules:
            report.add_tested_variant(variant.variant_id)
        else:
            report.add_untested_variant(variant)

    return report


def check_variant_coverage() -> tuple[bool, str]:
    """Check that all EVALUATE variants have coverage.

    Returns:
        Tuple of (is_complete: bool, message: str)
    """
    report = run_coverage_gate()
    summary = report.get_summary()

    if summary["is_complete"]:
        return (
            True,
            f"Coverage complete: {summary['tested_variants']}/{summary['total_variants']} variants tested ({summary['coverage_percent']:.1f}%)",
        )

    message_parts = [
        f"Coverage incomplete: {summary['tested_variants']}/{summary['total_variants']} variants tested ({summary['coverage_percent']:.1f}%)",
    ]

    if summary["untested_variants"]:
        message_parts.append(
            f"Missing variants: {', '.join(summary['untested_variants'])}"
        )

    if report.failed_tests:
        message_parts.append(f"Failed tests: {len(report.failed_tests)}")

    return False, "\n".join(message_parts)


class TestEvaluateCoverageGate:
    """Tests for the EVALUATE coverage gate itself."""

    def test_coverage_gate_exists(self):
        """Coverage gate module should be importable."""
        from tests.contracts.test_evaluate_coverage_gate import (
            EVALUATE_VARIANT_CATALOG,
            NEGATIVE_VARIANT_CATALOG,
            run_coverage_gate,
        )

        assert EVALUATE_VARIANT_CATALOG is not None
        assert NEGATIVE_VARIANT_CATALOG is not None
        assert run_coverage_gate is not None

    def test_variant_catalog_is_populated(self):
        """Variant catalog should contain entries."""
        from tests.contracts.test_evaluate_coverage_gate import (
            EVALUATE_VARIANT_CATALOG,
            NEGATIVE_VARIANT_CATALOG,
        )

        assert len(EVALUATE_VARIANT_CATALOG) > 0
        assert len(NEGATIVE_VARIANT_CATALOG) > 0

    def test_positive_catalog_has_required_variants(self):
        """Positive catalog should cover main variant types."""
        from tests.contracts.test_evaluate_coverage_gate import (
            EVALUATE_VARIANT_CATALOG,
            VariantCategory,
        )

        categories = {v.category for v in EVALUATE_VARIANT_CATALOG}

        required_categories = {
            VariantCategory.SINGLE_SUBJECT,
            VariantCategory.MULTI_SUBJECT,
            VariantCategory.EVALUATE_TRUE_FALSE,
            VariantCategory.RANGE_THROUGH,
            VariantCategory.ANY_SELECTOR,
            VariantCategory.WHEN_OTHER,
        }

        missing = required_categories - categories
        assert not missing, f"Missing variant categories: {missing}"

    def test_negative_catalog_has_required_variants(self):
        """Negative catalog should cover main error types."""
        from tests.contracts.test_evaluate_coverage_gate import (
            NEGATIVE_VARIANT_CATALOG,
            VariantCategory,
        )

        categories = {v.category for v in NEGATIVE_VARIANT_CATALOG}

        required_categories = {
            VariantCategory.SINGLE_SUBJECT,
            VariantCategory.MULTI_SUBJECT,
            VariantCategory.RANGE_THROUGH,
            VariantCategory.WHEN_OTHER,
            VariantCategory.EVALUATE_TRUE_FALSE,
        }

        missing = required_categories - categories
        assert not missing, f"Missing negative variant categories: {missing}"

    def test_all_positive_variants_are_tested(self):
        """All positive catalog variants should have corresponding tests."""
        from tests.contracts.test_evaluate_coverage_gate import (
            run_coverage_gate,
        )

        report = run_coverage_gate()
        summary = report.get_summary()

        assert summary["is_complete"], (
            f"Coverage incomplete:\n"
            f"  Tested: {summary['tested_variants']}/{summary['total_variants']}\n"
            f"  Missing: {summary['untested_variants']}"
        )

    def test_coverage_report_structure(self):
        """Coverage report should have expected structure."""
        from tests.contracts.test_evaluate_coverage_gate import (
            run_coverage_gate,
        )

        report = run_coverage_gate()
        report_dict = report.to_dict()

        assert "tested_variants" in report_dict
        assert "untested_variants" in report_dict
        assert "failed_tests" in report_dict
        assert "summary" in report_dict
        assert "is_complete" in report_dict["summary"]

    def test_variant_lookup_function(self):
        """Variant lookup by ID should work."""
        from tests.contracts.test_evaluate_coverage_gate import (
            EVALUATE_VARIANT_CATALOG,
            get_variant_by_id,
        )

        first_variant = EVALUATE_VARIANT_CATALOG[0]
        found = get_variant_by_id(first_variant.variant_id)
        assert found is not None
        assert found.variant_id == first_variant.variant_id

    def test_nonexistent_variant_returns_none(self):
        """Lookup of non-existent variant should return None."""
        from tests.contracts.test_evaluate_coverage_gate import get_variant_by_id

        found = get_variant_by_id("EV-NONEXISTENT-001")
        assert found is None

    def test_check_variant_coverage_helper(self):
        """check_variant_coverage helper should return tuple."""
        from tests.contracts.test_evaluate_coverage_gate import check_variant_coverage

        is_complete, message = check_variant_coverage()
        assert isinstance(is_complete, bool)
        assert isinstance(message, str)
        assert "Coverage" in message

    def test_variant_to_dict(self):
        """Variants should serialize to dict."""
        from tests.contracts.test_evaluate_coverage_gate import EVALUATE_VARIANT_CATALOG

        variant = EVALUATE_VARIANT_CATALOG[0]
        variant_dict = variant.to_dict()

        assert "variant_id" in variant_dict
        assert "category" in variant_dict
        assert "description" in variant_dict
        assert "test_scope" in variant_dict
        assert "test_name" in variant_dict

    def test_gate_fails_when_variants_missing(self):
        """Gate should report incomplete when variants untested."""
        from tests.contracts.test_evaluate_coverage_gate import (
            CoverageReport,
        )

        report = CoverageReport()
        # Don't add any tested variants
        summary = report.get_summary()

        assert not summary["is_complete"]
        assert summary["coverage_percent"] == 0.0


class TestEvaluateVariantDocumentation:
    """Tests that verify variant catalog documentation."""

    def test_catalog_has_descriptions(self):
        """All variants should have meaningful descriptions."""
        from tests.contracts.test_evaluate_coverage_gate import EVALUATE_VARIANT_CATALOG

        for variant in EVALUATE_VARIANT_CATALOG:
            assert (
                variant.description
            ), f"Variant {variant.variant_id} missing description"
            assert (
                len(variant.description) > 10
            ), f"Variant {variant.variant_id} description too short"

    def test_catalog_has_features(self):
        """All variants should have feature tags."""
        from tests.contracts.test_evaluate_coverage_gate import EVALUATE_VARIANT_CATALOG

        for variant in EVALUATE_VARIANT_CATALOG:
            assert variant.features, f"Variant {variant.variant_id} missing features"
            assert (
                len(variant.features) > 0
            ), f"Variant {variant.variant_id} has no features"

    def test_variant_ids_are_unique(self):
        """All variant IDs should be unique."""
        from tests.contracts.test_evaluate_coverage_gate import (
            EVALUATE_VARIANT_CATALOG,
            NEGATIVE_VARIANT_CATALOG,
        )

        all_ids = [
            v.variant_id for v in EVALUATE_VARIANT_CATALOG + NEGATIVE_VARIANT_CATALOG
        ]
        unique_ids = set(all_ids)

        assert len(all_ids) == len(unique_ids), "Duplicate variant IDs found"

    def test_variant_ids_follow_naming_convention(self):
        """Variant IDs should follow naming convention."""
        from tests.contracts.test_evaluate_coverage_gate import (
            EVALUATE_VARIANT_CATALOG,
            NEGATIVE_VARIANT_CATALOG,
        )

        pattern = re.compile(r"^EV-[A-Z]{2}-\d{3}$")

        for variant in EVALUATE_VARIANT_CATALOG + NEGATIVE_VARIANT_CATALOG:
            assert pattern.match(
                variant.variant_id
            ), f"Variant {variant.variant_id} doesn't match pattern EV-XX-000"
