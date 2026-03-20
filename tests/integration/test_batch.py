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
