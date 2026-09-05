"""Smoke tests over every COBOL sample program, plus a manual test runner.

The module used to hold only the ``run_sample_tests``-style helpers below.
None of them is named ``test_*``, so pytest collected **zero** tests from
this file even though the project documents it as the thing that
"smoke-tests all sample COBOL programs" -- nothing checked the corpus in
``tests/samples/`` as a corpus at all.

That gap let a whole class of fixture rot through: 32 lines across 13
sample programs ran past column 72, the end of Area B in fixed-format
COBOL. The preprocessor drops those columns exactly as a real compiler
does, so the parser silently saw truncated identifiers
(``WS-EXCEPTION-MSG`` arriving as ``WS-EXCEPTION-M``), data items missing
their terminating period, and -- in one case -- an unterminated literal
that failed to parse outright. Every one of those samples is an input to
the wider suite, so thousands of tests were asserting against programs
that were not the programs on disk.

:class:`TestSampleCorpus` closes that gap: the column check catches the
cause, the parse check catches the effect.
"""

import sys
from pathlib import Path

import pytest

from cobolparser import parse_cobol

SAMPLES_DIR = Path(__file__).parent / "samples"

#: Samples that are *expected* to produce parse errors, with the reason.
#: Anything else reporting an error is a regression, in the parser or in
#: the fixture.
EXPECTED_PARSE_ERRORS = {
    # Purpose-built malformed input for the error-recovery tests.
    "error_recovery_tests.cbl",
    # Uses a non-ASCII currency symbol in a PICTURE. The lexer rejects the
    # character; see the audit note in the repository's open findings.
    "special_names_config.cbl",
}

#: Last column of Area B. Columns 73-80 are the identification area and are
#: discarded by ``normalize_fixed_format`` before the lexer runs.
LAST_CODE_COLUMN = 72


def _sample_programs() -> list[Path]:
    return sorted(SAMPLES_DIR.rglob("*.cbl"))


class TestSampleCorpus:
    """Corpus-wide invariants for the COBOL samples in ``tests/samples/``."""

    @pytest.mark.parametrize("sample", _sample_programs(), ids=lambda p: p.name)
    def test_sample_respects_fixed_format_columns(self, sample: Path) -> None:
        """No sample line may extend past column 72.

        Anything there is silently discarded as the identification area, so
        a line that overflows does not fail loudly -- it quietly changes the
        program the rest of the suite is testing against.
        """
        overflowing = [
            (number, len(line))
            for number, line in enumerate(
                sample.read_text(encoding="utf-8", errors="replace").splitlines(), 1
            )
            if len(line) > LAST_CODE_COLUMN
        ]
        assert not overflowing, (
            f"{sample.name}: lines past column {LAST_CODE_COLUMN} "
            f"(line, length): {overflowing}"
        )

    @pytest.mark.parametrize("sample", _sample_programs(), ids=lambda p: p.name)
    def test_sample_parses_without_errors(self, sample: Path) -> None:
        """Every sample parses to an AST, with no errors unless expected."""
        result = parse_cobol(
            sample.read_text(encoding="utf-8", errors="replace"),
            filename=str(sample),
        )
        if sample.name in EXPECTED_PARSE_ERRORS:
            pytest.skip(f"{sample.name} is a known-bad fixture by design")
        assert result.ast is not None, f"{sample.name} produced no AST"
        assert not result.errors, f"{sample.name}: " + "; ".join(
            str(e) for e in result.errors[:5]
        )


def run_sample_tests():
    """Run all tests for COBOL samples."""

    # Configure pytest arguments
    pytest_args = [
        "tests/integration/test_sample_programs.py",
        "tests/unit/test_sample_features.py",
        "tests/contracts/test_sample_api_contracts.py",
        "-v",  # Verbose output
        "--tb=short",  # Short traceback format
        "--color=yes",  # Colored output
        "-ra",  # Show all test summary info
    ]

    # Run tests
    print("=" * 70)
    print("Running COBOL Sample Tests")
    print("=" * 70)
    print()

    exit_code = pytest.main(pytest_args)

    return exit_code


def run_sample_tests_with_coverage():
    """Run all sample tests with code coverage."""

    pytest_args = [
        "tests/integration/test_sample_programs.py",
        "tests/unit/test_sample_features.py",
        "tests/contracts/test_sample_api_contracts.py",
        "-v",
        "--cov=cobolparser",
        "--cov-report=html",
        "--cov-report=term",
        "--cov-fail-under=90",
    ]

    print("=" * 70)
    print("Running COBOL Sample Tests with Coverage")
    print("=" * 70)
    print()

    exit_code = pytest.main(pytest_args)

    return exit_code


def run_specific_sample_category(category: str):
    """Run tests for a specific category of samples."""

    category_map = {
        "basic": ["test_basic_samples", "test_figurative_constants", "test_picture"],
        "files": ["test_file_operations", "test_sort_merge"],
        "control": ["test_control_flow", "test_arithmetic"],
        "strings": ["test_string_operations"],
        "ibm": ["test_ibm_extensions"],
        "advanced": [
            "test_declaratives",
            "test_special_names",
            "test_report",
            "test_communication",
            "test_screen",
        ],
        "errors": ["test_error_recovery"],
        "contracts": ["test_sample_api_contracts"],
    }

    if category not in category_map:
        print(f"Unknown category: {category}")
        print(f"Available categories: {', '.join(category_map.keys())}")
        return 1

    # Run tests matching the category keywords
    pytest_args = [
        "tests/",
        "-v",
        "-k",
        " or ".join(category_map[category]),
    ]

    print(f"Running tests for category: {category}")
    exit_code = pytest.main(pytest_args)

    return exit_code


if __name__ == "__main__":
    if len(sys.argv) > 1:
        if sys.argv[1] == "coverage":
            exit_code = run_sample_tests_with_coverage()
        elif sys.argv[1] == "category":
            if len(sys.argv) > 2:
                exit_code = run_specific_sample_category(sys.argv[2])
            else:
                print("Usage: python test_all_samples.py category <category_name>")
                exit_code = 1
        else:
            print("Usage: python test_all_samples.py [coverage|category <name>]")
            exit_code = 1
    else:
        exit_code = run_sample_tests()

    sys.exit(exit_code)
