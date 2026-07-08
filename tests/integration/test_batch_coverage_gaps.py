"""Integration tests covering batch.py paths not reached by existing tests.

Targets:
- parse_files_with_copybooks() happy path, OSError per file, expansion failure
- _parse_one() OSError path (lines 78-79)
- parse_files() with caller-managed executor (lines 167-170)
- parse_files() with workers > 1 (ProcessPoolExecutor path)
"""

from __future__ import annotations

import logging
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from unittest.mock import patch

import pytest

from cobolparser.batch import (
    BatchResult,
    _parse_one,
    parse_files,
    parse_files_with_copybooks,
)
from cobolparser.plugins.core import DialectType, ErrorRecoveryMode

pytestmark = pytest.mark.integration

SAMPLES_DIR = Path(__file__).parent.parent / "samples"

_MINIMAL = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TEST.
       PROCEDURE DIVISION.
           STOP RUN.
"""


# ---------------------------------------------------------------------------
# _parse_one() OSError path
# ---------------------------------------------------------------------------


class TestParseOneOSError:
    def test_oserror_returns_batch_result_with_read_error(self, tmp_path):
        p = tmp_path / "no.cbl"
        # File does not exist — read_text raises OSError / FileNotFoundError
        result = _parse_one(
            str(p),
            "utf-8",
            "replace",
            ErrorRecoveryMode.COLLECT_ALL,
            DialectType.IBM_ENTERPRISE,
            False,
            10,
            None,
        )
        assert result.read_error is not None
        assert result.result is None

    def test_oserror_path_is_preserved(self, tmp_path):
        p = tmp_path / "ghost.cbl"
        result = _parse_one(
            str(p),
            "utf-8",
            "replace",
            ErrorRecoveryMode.COLLECT_ALL,
            DialectType.IBM_ENTERPRISE,
            False,
            10,
            None,
        )
        assert result.path == p


# ---------------------------------------------------------------------------
# parse_files() with caller-managed ProcessPoolExecutor
# ---------------------------------------------------------------------------


class TestParseFilesCallerExecutor:
    def test_caller_executor_returns_results(self, tmp_path):
        f1 = tmp_path / "a.cbl"
        f2 = tmp_path / "b.cbl"
        f1.write_text(_MINIMAL)
        f2.write_text(_MINIMAL)

        with ProcessPoolExecutor(max_workers=1) as executor:
            results = parse_files([f1, f2], executor=executor)

        assert len(results) == 2
        for r in results:
            assert isinstance(r, BatchResult)
            assert r.read_error is None

    def test_caller_executor_preserves_order(self, tmp_path):
        files = []
        for i in range(3):
            p = tmp_path / f"f{i}.cbl"
            p.write_text(_MINIMAL)
            files.append(p)

        with ProcessPoolExecutor(max_workers=1) as executor:
            results = parse_files(files, executor=executor)

        for i, r in enumerate(results):
            assert r.path == Path(files[i])


# ---------------------------------------------------------------------------
# parse_files_with_copybooks() — happy path
# ---------------------------------------------------------------------------


class TestParseFilesWithCopybooksHappy:
    def test_empty_list_returns_empty(self):
        results = parse_files_with_copybooks([], copybook_paths=[])
        assert results == []

    def test_single_file_no_copy(self, tmp_path):
        f = tmp_path / "prog.cbl"
        f.write_text(_MINIMAL)
        results = parse_files_with_copybooks([f], copybook_paths=[])
        assert len(results) == 1
        assert results[0].read_error is None
        assert results[0].result is not None

    def test_multiple_files_all_parsed(self, tmp_path):
        files = []
        for i in range(3):
            p = tmp_path / f"prog{i}.cbl"
            p.write_text(_MINIMAL)
            files.append(p)

        results = parse_files_with_copybooks(files, copybook_paths=[str(tmp_path)])
        assert len(results) == 3
        for r in results:
            assert r.read_error is None

    def test_results_in_input_order(self, tmp_path):
        files = []
        for i in range(4):
            p = tmp_path / f"x{i}.cbl"
            p.write_text(_MINIMAL)
            files.append(p)

        results = parse_files_with_copybooks(files, copybook_paths=[])
        for i, r in enumerate(results):
            assert r.path == Path(files[i])


# ---------------------------------------------------------------------------
# parse_files_with_copybooks() — OSError per-file recovery
# ---------------------------------------------------------------------------


class TestParseFilesWithCopybooksOSError:
    def test_missing_file_recorded_as_read_error(self, tmp_path):
        missing = tmp_path / "absent.cbl"
        results = parse_files_with_copybooks([missing], copybook_paths=[])
        assert len(results) == 1
        assert results[0].read_error is not None
        assert results[0].result is None

    def test_partial_failure_continues(self, tmp_path):
        good = tmp_path / "good.cbl"
        good.write_text(_MINIMAL)
        missing = tmp_path / "gone.cbl"

        results = parse_files_with_copybooks([good, missing], copybook_paths=[])
        assert len(results) == 2
        assert results[0].read_error is None
        assert results[1].read_error is not None


# ---------------------------------------------------------------------------
# parse_files_with_copybooks() — expansion failure falls back to raw source
# ---------------------------------------------------------------------------


class TestParseFilesWithCopybooksExpansionFallback:
    def test_expansion_exception_falls_back_to_raw(self, tmp_path, caplog):
        f = tmp_path / "prog.cbl"
        f.write_text(_MINIMAL)

        # Patch expand_copybooks to raise so the except branch fires
        with (
            patch(
                "cobolparser.preprocess.copybook_expander.expand_copybooks",
                side_effect=RuntimeError("boom"),
            ),
            caplog.at_level(logging.WARNING, logger="cobolparser.batch"),
        ):
            results = parse_files_with_copybooks([f], copybook_paths=[])

        # Should still get a result (parsed from raw source)
        assert len(results) == 1
        assert results[0].read_error is None
        # AST may or may not be None depending on the raw source — just confirm no crash

        # The silent fallback must now be observable via a warning log.
        assert any(
            "Copybook expansion failed" in rec.message and "boom" in rec.message
            for rec in caplog.records
        )


# ---------------------------------------------------------------------------
# parse_files_with_copybooks() — a poisoned file must not abort the batch
# ---------------------------------------------------------------------------


class TestParseFilesWithCopybooksParseException:
    def test_parse_exception_recorded_per_file_not_raised(self, tmp_path):
        """Audit finding: unlike parse_files()/_parse_one(), the copybook-aware
        path called parser.parse() with no exception guard, so one file
        raising during parse aborted the whole batch and lost every other
        file's already-computed result."""
        good = tmp_path / "good.cbl"
        bad = tmp_path / "bad.cbl"
        good.write_text(_MINIMAL)
        bad.write_text(_MINIMAL)

        real_parse = None
        calls = {"n": 0}

        def flaky_parse(self, source, **kwargs):
            calls["n"] += 1
            if calls["n"] == 2:
                raise RuntimeError("boom")
            return real_parse(self, source, **kwargs)

        from cobolparser.parser import CobolParser

        real_parse = CobolParser.parse
        with patch.object(CobolParser, "parse", flaky_parse):
            results = parse_files_with_copybooks([good, bad], copybook_paths=[])

        assert len(results) == 2
        assert results[0].read_error is None
        assert results[0].result is not None
        assert results[1].read_error is not None
        assert "boom" in results[1].read_error


# ---------------------------------------------------------------------------
# parse_files_with_copybooks() — non-OSError read failures (strict decoding)
# ---------------------------------------------------------------------------


class TestParseFilesWithCopybooksDecodeError:
    def test_invalid_utf8_with_strict_errors_recorded_not_raised(self, tmp_path):
        """Audit finding: the file-read except clause only caught OSError, so
        a UnicodeDecodeError under errors='strict' (a documented use of the
        errors= parameter) propagated out of the function instead of being
        recorded as a per-file read_error."""
        bad = tmp_path / "bad_encoding.cbl"
        bad.write_bytes(b"\xff\xfe not valid utf-8 \x80\x81")

        results = parse_files_with_copybooks([bad], copybook_paths=[], errors="strict")

        assert len(results) == 1
        assert results[0].read_error is not None
        assert results[0].result is None


# ---------------------------------------------------------------------------
# parse_files_with_copybooks() — with actual sample files
# ---------------------------------------------------------------------------


class TestParseFilesWithCopybooks_Samples:
    def test_sample_files_parse_successfully(self):
        files = sorted(SAMPLES_DIR.glob("*.cbl"))[:5]
        if not files:
            pytest.skip("No sample COBOL files found")

        results = parse_files_with_copybooks(
            files,
            copybook_paths=[str(SAMPLES_DIR)],
            error_recovery=ErrorRecoveryMode.COLLECT_ALL,
        )
        assert len(results) == len(files)
        for r in results:
            assert r.read_error is None
