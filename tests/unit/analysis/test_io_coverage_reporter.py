"""Unit tests for IO coverage reporter.

Tests the io_coverage_reporter module for correct aggregation
logic and artifact generation per the coverage schema.
"""

import json

import pytest

from cobolparser.analysis.io_coverage_reporter import (
    CoverageStatus,
    IoCoverageArtifact,
    IOCoverageReporter,
    IoVariationCoverage,
    TestType,
)


class TestIOCoverageReporter:
    """Test cases for IOCoverageReporter class."""

    @pytest.fixture
    def sample_pytest_results(self, tmp_path) -> str:
        """Create sample pytest results JSON file."""
        results = {
            "version": "1.0",
            "tests": [
                {
                    "id": "tests/unit/io_statements/test_io_clause_variations.py::TestIOClauseVariations::READ-NEXT-AT-END",
                    "nodeid": "tests/unit/io_statements/test_io_clause_variations.py::TestIOClauseVariations::READ-NEXT-AT-END",
                    "status": "passed",
                    "duration": 0.012,
                    "file": "tests/unit/io_statements/test_io_clause_variations.py",
                    "line_number": 42,
                    "description": "Test READ AT END clause",
                },
                {
                    "id": "tests/unit/io_statements/test_io_clause_variations.py::TestIOClauseVariations::WRITE-ADVANCING",
                    "nodeid": "tests/unit/io_statements/test_io_clause_variations.py::TestIOClauseVariations::WRITE-ADVANCING",
                    "status": "passed",
                    "duration": 0.008,
                    "file": "tests/unit/io_statements/test_io_clause_variations.py",
                    "line_number": 67,
                    "description": "Test WRITE ADVANCING",
                },
                {
                    "id": "tests/unit/io_statements/test_io_errors.py::TestIOErrorHandling::READ-NEXT-SEQUENTIAL",
                    "nodeid": "tests/unit/io_statements/test_io_errors.py::TestIOErrorHandling::READ-NEXT-SEQUENTIAL",
                    "status": "passed",
                    "duration": 0.015,
                    "file": "tests/unit/io_statements/test_io_errors.py",
                    "line_number": 23,
                    "description": "Test READ INVALID KEY",
                },
                {
                    "id": "tests/integration/io_statements/test_io_statement_parsing.py::TestIOStatementParsing::OPEN-EXTEND-SEQUENTIAL",
                    "nodeid": "tests/integration/io_statements/test_io_statement_parsing.py::TestIOStatementParsing::OPEN-EXTEND-SEQUENTIAL",
                    "status": "passed",
                    "duration": 0.025,
                    "file": "tests/integration/io_statements/test_io_statement_parsing.py",
                    "line_number": 15,
                    "description": "Test OPEN EXTEND",
                },
                {
                    "id": "tests/unit/io_statements/test_io_clause_variations.py::TestIOClauseVariations::CLOSE-NO-REWIND",
                    "nodeid": "tests/unit/io_statements/test_io_clause_variations.py::TestIOClauseVariations::CLOSE-NO-REWIND",
                    "status": "failed",
                    "duration": 0.005,
                    "file": "tests/unit/io_statements/test_io_clause_variations.py",
                    "line_number": 89,
                    "description": "Test CLOSE NO REWIND",
                },
                {
                    "id": "tests/contracts/io_statements/test_io_statements_contract.py::OPEN-INPUT-SEQUENTIAL",
                    "nodeid": "tests/contracts/io_statements/test_io_statements_contract.py::OPEN-INPUT-SEQUENTIAL",
                    "status": "passed",
                    "duration": 0.018,
                    "file": "tests/contracts/io_statements/test_io_statements_contract.py",
                    "line_number": 10,
                    "description": "Contract test for OPEN INPUT",
                },
            ],
        }

        file_path = tmp_path / "pytest_results.json"
        with open(file_path, "w") as f:
            json.dump(results, f)

        return str(file_path)

    @pytest.fixture
    def sample_catalog(self, tmp_path) -> str:
        """Create sample IO variation catalog CSV."""
        csv_content = """id,verb,file_organization,access_mode,qualifiers,requires_fd_clauses,ibm_reference,status,notes
OPEN-INPUT-SEQUENTIAL,OPEN,SEQUENTIAL,INPUT,,N/A,SC27-8949-30,PENDING,Basic sequential file open
OPEN-OUTPUT-SEQUENTIAL,OPEN,SEQUENTIAL,OUTPUT,,N/A,SC27-8949-30,PENDING,Create or truncate sequential file
OPEN-EXTEND-SEQUENTIAL,OPEN,SEQUENTIAL,EXTEND,,N/A,SC27-8949-30,PENDING,Open sequential file for append
CLOSE-SIMPLE,CLOSE,N/A,N/A,,N/A,SC27-8949-30,PENDING,Basic file close
CLOSE-NO-REWIND,CLOSE,SEQUENTIAL,N/A,NO REWIND,N/A,SC27-8949-30,PENDING,Close without tape rewind
READ-NEXT-SEQUENTIAL,READ,SEQUENTIAL,SEQUENTIAL,,N/A,SC27-8949-30,PENDING,Read next sequential record
READ-NEXT-AT-END,READ,SEQUENTIAL,SEQUENTIAL,AT END,N/A,SC27-8949-30,PENDING,Sequential read with end-of-file check
WRITE-NEXT,WRITE,SEQUENTIAL,OUTPUT,,N/A,SC27-8949-30,PENDING,Write next sequential record
WRITE-ADVANCING,WRITE,SEQUENTIAL,OUTPUT,ADVANCING,N/A,SC27-8949-30,PENDING,Write with page/line advancing
DISPLAY-TO-CONSOLE,DISPLAY,N/A,N/A,,N/A,SC27-8949-30,PENDING,Display output to console
"""

        file_path = tmp_path / "io-variation-catalog.csv"
        with open(file_path, "w") as f:
            f.write(csv_content)

        return str(file_path)

    def test_load_catalog(self, sample_catalog):
        """Test loading IO variation catalog."""
        reporter = IOCoverageReporter(catalog_path=sample_catalog)
        reporter.load_catalog()

        assert len(reporter.variations) == 10
        assert reporter.variations[0].verb == "OPEN"
        assert reporter.variations[0].variation_id == "OPEN-INPUT-SEQUENTIAL"

    def test_load_catalog_missing_file(self, tmp_path):
        """Test error handling when catalog is missing."""
        reporter = IOCoverageReporter(catalog_path=str(tmp_path / "missing.csv"))

        with pytest.raises(FileNotFoundError):
            reporter.load_catalog()

    def test_load_pytest_results(self, sample_pytest_results, sample_catalog):
        """Test loading pytest results."""
        reporter = IOCoverageReporter(catalog_path=sample_catalog)
        reporter.load_catalog()
        reporter.load_pytest_results(sample_pytest_results)

        assert len(reporter.test_results) > 0

    def test_load_pytest_results_missing_file(self, sample_catalog):
        """Test error handling when pytest results are missing."""
        reporter = IOCoverageReporter(catalog_path=sample_catalog)
        reporter.load_catalog()

        with pytest.raises(FileNotFoundError):
            reporter.load_pytest_results("/nonexistent/results.json")

    def test_determine_test_type_unit(self):
        """Test unit test type detection."""
        reporter = IOCoverageReporter()
        test_type = reporter._determine_test_type(
            "tests/unit/io_statements/test_io.py::test_case"
        )
        assert test_type == TestType.UNIT.value

    def test_determine_test_type_integration(self):
        """Test integration test type detection."""
        reporter = IOCoverageReporter()
        test_type = reporter._determine_test_type(
            "tests/integration/io/test_io.py::test_case"
        )
        assert test_type == TestType.INTEGRATION.value

    def test_determine_test_type_contract(self):
        """Test contract test type detection."""
        reporter = IOCoverageReporter()
        test_type = reporter._determine_test_type(
            "tests/contracts/io_statements/test_io_statements_contract.py::OPEN-INPUT-SEQUENTIAL"
        )
        assert test_type == TestType.CONTRACT.value

    def test_extract_io_variation_id(self, sample_catalog):
        """Test extraction of variation ID from test ID."""
        reporter = IOCoverageReporter(catalog_path=sample_catalog)
        reporter.load_catalog()

        var_id = reporter._extract_io_variation(
            "tests/unit/io_statements/test_io_clause_variations.py::TestIOClauseVariations::READ-NEXT-AT-END"
        )
        assert var_id == "READ-NEXT-AT-END"

    def test_extract_io_variation_id_from_catalog(self, sample_catalog):
        """Test extraction when variation ID is in test name."""
        reporter = IOCoverageReporter(catalog_path=sample_catalog)
        reporter.load_catalog()

        var_id = reporter._extract_io_variation("OPEN-INPUT-SEQUENTIAL test case")
        assert var_id == "OPEN-INPUT-SEQUENTIAL"

    def test_generate_artifact(self, sample_pytest_results, sample_catalog):
        """Test generating coverage artifact."""
        reporter = IOCoverageReporter(catalog_path=sample_catalog)
        reporter.load_catalog()
        reporter.load_pytest_results(sample_pytest_results)

        artifact = reporter.generate_artifact()

        assert artifact.total_variations == 10
        assert artifact.coverage_percent > 0
        assert len(artifact.variations) == 10

    def test_generate_artifact_with_covered_variations(
        self, sample_pytest_results, sample_catalog
    ):
        """Test that covered variations are correctly counted."""
        reporter = IOCoverageReporter(catalog_path=sample_catalog)
        reporter.load_catalog()
        reporter.load_pytest_results(sample_pytest_results)

        artifact = reporter.generate_artifact()

        # OPEN-INPUT-SEQUENTIAL has a contract test
        open_variation = next(
            (v for v in artifact.variations if v["id"] == "OPEN-INPUT-SEQUENTIAL"),
            None,
        )
        assert open_variation is not None
        assert open_variation["status"] == "covered"
        assert len(open_variation["tests"]) > 0

    def test_generate_artifact_with_gap_variations(
        self, sample_pytest_results, sample_catalog
    ):
        """Test that gap variations are correctly identified."""
        reporter = IOCoverageReporter(catalog_path=sample_catalog)
        reporter.load_catalog()
        reporter.load_pytest_results(sample_pytest_results)

        artifact = reporter.generate_artifact()

        # OPEN-OUTPUT-SEQUENTIAL has no tests
        output_variation = next(
            (v for v in artifact.variations if v["id"] == "OPEN-OUTPUT-SEQUENTIAL"),
            None,
        )
        assert output_variation is not None
        assert output_variation["status"] == CoverageStatus.GAP.value

    def test_generate_artifact_partial_status(
        self, sample_pytest_results, sample_catalog
    ):
        """Test partial coverage status for failed tests."""
        reporter = IOCoverageReporter(catalog_path=sample_catalog)
        reporter.load_catalog()
        reporter.load_pytest_results(sample_pytest_results)

        artifact = reporter.generate_artifact()

        # CLOSE-NO-REWIND has a failed test
        close_variation = next(
            (v for v in artifact.variations if v["id"] == "CLOSE-NO-REWIND"),
            None,
        )
        assert close_variation is not None
        assert close_variation["status"] == CoverageStatus.PARTIAL.value

    def test_save_artifact(self, sample_pytest_results, sample_catalog, tmp_path):
        """Test saving artifact to file."""
        reporter = IOCoverageReporter(catalog_path=sample_catalog)
        reporter.load_catalog()
        reporter.load_pytest_results(sample_pytest_results)

        artifact = reporter.generate_artifact()
        output_path = tmp_path / "io-coverage.json"

        reporter.save_artifact(artifact, str(output_path))

        assert output_path.exists()
        with open(output_path) as f:
            saved = json.load(f)
        assert saved["version"] == "1.0.0"

    def test_validate_artifact_valid(self, sample_pytest_results, sample_catalog):
        """Test validation of valid artifact."""
        reporter = IOCoverageReporter(catalog_path=sample_catalog)
        reporter.load_catalog()
        reporter.load_pytest_results(sample_pytest_results)

        artifact = reporter.generate_artifact()
        errors = reporter.validate_artifact(artifact)

        assert len(errors) == 0

    def test_validate_artifact_missing_generated_at(self):
        """Test validation fails when generated_at is missing."""
        artifact = IoCoverageArtifact(
            version="1.0.0",
            generated_at="",
            total_variations=10,
            covered_variations=5,
            variations=[],
        )

        reporter = IOCoverageReporter()
        errors = reporter.validate_artifact(artifact)

        assert len(errors) > 0

    def test_validate_artifact_invalid_status(self):
        """Test validation fails for invalid status value."""
        artifact = IoCoverageArtifact(
            version="1.0.0",
            generated_at="2024-01-01T00:00:00Z",
            total_variations=1,
            covered_variations=0,
            variations=[
                {
                    "id": "TEST-VARIATION",
                    "verb": "TEST",
                    "status": "invalid-status",
                    "tests": [],
                }
            ],
        )

        reporter = IOCoverageReporter()
        errors = reporter.validate_artifact(artifact)

        assert len(errors) > 0

    def test_validate_artifact_inconsistent_counts(self):
        """Test validation fails for inconsistent variation counts."""
        artifact = IoCoverageArtifact(
            version="1.0.0",
            generated_at="2024-01-01T00:00:00Z",
            total_variations=10,
            covered_variations=10,
            partial_variations=0,
            gap_variations=0,
            unsupported_variations=0,
            variations=[],
        )

        reporter = IOCoverageReporter()
        errors = reporter.validate_artifact(artifact)

        assert len(errors) > 0

    def test_generate_report_full_workflow(
        self, sample_pytest_results, sample_catalog, tmp_path
    ):
        """Test complete report generation workflow."""
        output_path = tmp_path / "output" / "io-coverage.json"

        reporter = IOCoverageReporter(catalog_path=sample_catalog)
        result = reporter.generate_report(sample_pytest_results, str(output_path))

        assert result["success"]
        assert result["total_variations"] == 10
        assert result["covered_variations"] > 0
        assert result["gap_variations"] > 0

    def test_get_parser_version(self):
        """Test parser version detection."""
        reporter = IOCoverageReporter()
        version = reporter._get_parser_version()

        assert version is not None
        assert version != ""


class TestCoverageStatus:
    """Test CoverageStatus enum."""

    def test_coverage_status_values(self):
        """Test that all expected status values exist."""
        assert CoverageStatus.COVERED.value == "covered"
        assert CoverageStatus.PARTIAL.value == "partial"
        assert CoverageStatus.GAP.value == "gap"
        assert CoverageStatus.UNSUPPORTED.value == "unsupported"


class TestIoVariationCoverage:
    """Test IoVariationCoverage dataclass."""

    def test_create_variation_coverage(self):
        """Test creating a variation coverage entry."""
        variation = IoVariationCoverage(
            variation_id="OPEN-INPUT-SEQUENTIAL",
            verb="OPEN",
            organization="SEQUENTIAL",
            access_mode="INPUT",
            qualifiers="",
            status=CoverageStatus.COVERED.value,
            requires_fd=False,
            ibm_reference="SC27-8949-30",
            tests=[{"test_id": "test_case"}],
            last_tested="2024-01-01T00:00:00Z",
            notes="Basic sequential file open",
        )

        assert variation.variation_id == "OPEN-INPUT-SEQUENTIAL"
        assert variation.verb == "OPEN"
        assert variation.status == "covered"
        assert len(variation.tests) == 1

    def test_variation_coverage_defaults(self):
        """Test variation coverage with default values."""
        variation = IoVariationCoverage(
            variation_id="TEST",
            verb="TEST",
            organization="",
            access_mode="",
            qualifiers="",
            status=CoverageStatus.GAP.value,
            requires_fd=False,
            ibm_reference="",
        )

        assert variation.tests == []
        assert variation.last_tested is None
        assert variation.notes is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
