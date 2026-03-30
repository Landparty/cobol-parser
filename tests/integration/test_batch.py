"""Integration tests for the batch parsing API."""
import pytest
from pathlib import Path
from unittest.mock import patch

from cobolparser import parse_cobol
from cobolparser.batch import BatchResult, parse_files, _parse_one
from cobolparser.plugins.core import ErrorRecoveryMode, DialectType


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

pytestmark = pytest.mark.integration


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

    @pytest.mark.parametrize("workers", [1, 2, None])
    def test_worker_count_variants_produce_same_results(self, workers):
        """Results should be identical regardless of worker count."""
        files = sorted(SAMPLES_DIR.glob("*.cbl"))[:4]
        if not files:
            pytest.skip("No sample files found")

        baseline = parse_files(files, workers=1)
        results = parse_files(files, workers=workers)

        assert len(results) == len(baseline)
        for a, b in zip(results, baseline):
            assert a.path == b.path
            assert (a.result is None) == (b.result is None)
            if a.result is not None:
                assert a.result.ast.to_dict() == b.result.ast.to_dict()


class TestParseFilesEncoding:
    def test_latin1_encoded_file(self, tmp_path):
        """parse_files() reads latin-1 encoded files when encoding is specified."""
        # Write minimal COBOL content encoded as latin-1
        content = "IDENTIFICATION DIVISION.\nPROGRAM-ID. LATIN1.\n"
        latin1_file = tmp_path / "latin1.cbl"
        latin1_file.write_bytes(content.encode("latin-1"))

        results = parse_files([latin1_file], workers=1, encoding="latin-1")

        assert len(results) == 1
        assert results[0].read_error is None
        assert results[0].result is not None

    def test_utf8_default_encoding(self, tmp_path):
        """parse_files() defaults to utf-8 encoding."""
        content = "IDENTIFICATION DIVISION.\nPROGRAM-ID. UTF8TEST.\n"
        utf8_file = tmp_path / "utf8.cbl"
        utf8_file.write_text(content, encoding="utf-8")

        results = parse_files([utf8_file], workers=1)

        assert len(results) == 1
        assert results[0].read_error is None


class TestParseOneInternal:
    def test_parse_cobol_exception_propagates(self, tmp_path):
        """If parse_cobol() raises unexpectedly, the exception surfaces from _parse_one."""
        cobl = tmp_path / "boom.cbl"
        cobl.write_text("IDENTIFICATION DIVISION.\nPROGRAM-ID. BOOM.\n")

        with patch("cobolparser.batch.parse_cobol", side_effect=RuntimeError("unexpected")):
            with pytest.raises(RuntimeError, match="unexpected"):
                _parse_one(
                    str(cobl), "utf-8", "replace",
                    ErrorRecoveryMode.COLLECT_ALL, DialectType.IBM_ENTERPRISE,
                )
