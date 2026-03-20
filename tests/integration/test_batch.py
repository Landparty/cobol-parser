"""Integration tests for the batch parsing API."""
import pytest
from pathlib import Path

from cobolparser import parse_cobol
from cobolparser.batch import BatchResult, parse_files
from cobolparser.plugins.core import ErrorRecoveryMode


SAMPLES_DIR = Path(__file__).parent.parent / "samples"


class TestBatchResult:
    def test_fields_success(self, tmp_path):
        p = tmp_path / "foo.cbl"
        br = BatchResult(path=p, result=object(), read_error=None)
        assert br.path == p
        assert br.read_error is None

    def test_fields_error(self, tmp_path):
        p = tmp_path / "missing.cbl"
        br = BatchResult(path=p, result=None, read_error="FileNotFoundError: no such file")
        assert br.result is None
        assert isinstance(br.read_error, str)

    def test_importable_from_package(self):
        from cobolparser import parse_files as pf, BatchResult as BR  # noqa: F401


class TestParseFilesCorrectness:
    """parse_files() must produce identical output to parse_cobol() per file."""

    def test_parity_with_parse_cobol(self):
        files = sorted(SAMPLES_DIR.glob("*.cbl"))
        if not files:
            pytest.skip("No sample files found")

        # Reference: parse each file individually with COLLECT_ALL
        # (parse_cobol defaults to FAIL_FAST, so we pass it explicitly here too)
        reference = {}
        for f in files:
            source = f.read_text(encoding="utf-8", errors="replace")
            reference[f] = parse_cobol(
                source,
                filename=str(f),
                error_recovery=ErrorRecoveryMode.COLLECT_ALL,
            )

        batch = parse_files(files, workers=2, error_recovery=ErrorRecoveryMode.COLLECT_ALL)

        assert len(batch) == len(files)
        for br in batch:
            assert br.read_error is None, f"{br.path}: unexpected read error"
            ref = reference[br.path]
            assert br.result.ast.to_dict() == ref.ast.to_dict(), f"{br.path}: AST mismatch"
            assert len(br.result.errors) == len(ref.errors), f"{br.path}: error count mismatch"

    def test_results_in_input_order(self):
        files = sorted(SAMPLES_DIR.glob("*.cbl"))[:8]
        if len(files) < 2:
            pytest.skip("Need at least 2 sample files")
        results = parse_files(files, workers=min(4, len(files)))
        for br, f in zip(results, files):
            assert br.path == f


class TestParseFilesErrorHandling:
    def test_missing_file_does_not_abort_batch(self, tmp_path):
        """One bad path should not abort the whole batch."""
        good_files = sorted(SAMPLES_DIR.glob("*.cbl"))[:3]
        if not good_files:
            pytest.skip("No sample files found")

        missing = tmp_path / "does_not_exist.cbl"
        mixed = [good_files[0], missing, good_files[1]]

        results = parse_files(mixed, workers=1)

        assert len(results) == 3
        assert results[0].read_error is None
        assert results[0].result is not None
        assert results[1].read_error is not None
        assert results[1].result is None
        assert results[2].read_error is None
        assert results[2].result is not None

    def test_empty_input_returns_empty_list(self):
        assert parse_files([]) == []

    def test_workers_zero_raises(self):
        with pytest.raises(ValueError, match="workers must be >= 1 or None"):
            parse_files([], workers=0)

    def test_workers_negative_raises(self):
        with pytest.raises(ValueError):
            parse_files([], workers=-1)


class TestParseFilesWorkersParity:
    def test_workers_1_matches_workers_gt_1(self):
        """Multi-worker results must match single-worker results exactly."""
        files = sorted(SAMPLES_DIR.glob("*.cbl"))[:6]
        if not files:
            pytest.skip("No sample files found")

        r1 = parse_files(files, workers=1)
        r4 = parse_files(files, workers=min(4, len(files)))

        assert len(r1) == len(r4)
        for a, b in zip(r1, r4):
            assert a.path == b.path
            assert (a.result is None) == (b.result is None)
            if a.result is not None:
                assert a.result.ast.to_dict() == b.result.ast.to_dict()
