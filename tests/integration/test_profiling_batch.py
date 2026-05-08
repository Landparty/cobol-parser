"""Integration tests: batch profiling support."""
from pathlib import Path

import pytest

from cobolparser.batch import BatchResult, parse_files, parse_files_with_copybooks
from cobolparser.profiling import ProfilingResult

_HELLO = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. HELLO.
       PROCEDURE DIVISION.
           DISPLAY 'Hello World'.
           STOP RUN.
"""


@pytest.fixture
def cobol_files(tmp_path):
    """Create two temporary COBOL files."""
    files = []
    for i in range(2):
        p = tmp_path / f"prog{i}.cbl"
        p.write_text(_HELLO, encoding="utf-8")
        files.append(str(p))
    return files


def test_batch_result_has_profiling_field():
    br = BatchResult(path=Path("x.cbl"), result=None, read_error=None)
    assert br.profiling is None


def test_parse_files_no_profiling_default(cobol_files):
    results = parse_files(cobol_files, workers=1)
    assert all(r.profiling is None for r in results)


def test_parse_files_profiling_returns_profiling_result(cobol_files):
    results = parse_files(cobol_files, workers=1, enable_profiling=True)
    assert all(isinstance(r.profiling, ProfilingResult) for r in results)


def test_parse_files_profiling_metrics_positive(cobol_files):
    results = parse_files(cobol_files, workers=1, enable_profiling=True)
    for r in results:
        assert r.profiling.wall_clock_s > 0.0
        assert r.profiling.peak_memory_mb >= 0.0


def test_parse_files_profiling_top_n_respected(cobol_files):
    results = parse_files(cobol_files, workers=1, enable_profiling=True, top_n=3)
    for r in results:
        assert 0 < len(r.profiling.top_functions) <= 3


def test_parse_files_profiling_writes_prof_files(cobol_files, tmp_path):
    prof_dir = str(tmp_path / "profiles")
    results = parse_files(cobol_files, workers=1, enable_profiling=True, prof_output=prof_dir)
    for r in results:
        expected = Path(prof_dir) / (Path(str(r.path)).stem + ".prof")
        assert expected.exists()


def test_parse_files_prof_output_dot_prof_raises(cobol_files):
    with pytest.raises(ValueError, match=r"\.prof"):
        parse_files(cobol_files, workers=1, enable_profiling=True, prof_output="out.prof")


def test_parse_files_with_copybooks_no_profiling(cobol_files):
    results = parse_files_with_copybooks(cobol_files, copybook_paths=[])
    assert all(r.profiling is None for r in results)


def test_parse_files_with_copybooks_profiling(cobol_files):
    results = parse_files_with_copybooks(
        cobol_files, copybook_paths=[], enable_profiling=True
    )
    assert all(isinstance(r.profiling, ProfilingResult) for r in results)


def test_parse_files_with_copybooks_prof_output_dot_prof_raises(cobol_files):
    with pytest.raises(ValueError, match=r"\.prof"):
        parse_files_with_copybooks(
            cobol_files, copybook_paths=[], enable_profiling=True, prof_output="out.prof"
        )


def test_parse_files_with_copybooks_writes_prof_files(cobol_files, tmp_path):
    prof_dir = str(tmp_path / "cb_profiles")
    results = parse_files_with_copybooks(
        cobol_files, copybook_paths=[], enable_profiling=True, prof_output=prof_dir
    )
    for r in results:
        expected = Path(prof_dir) / (Path(str(r.path)).stem + ".prof")
        assert expected.exists()


def test_parse_files_profiling_parallel(cobol_files):
    results = parse_files(cobol_files, workers=2, enable_profiling=True)
    assert all(isinstance(r.profiling, ProfilingResult) for r in results)


def test_parse_files_no_profiling_parallel(cobol_files):
    results = parse_files(cobol_files, workers=2)
    assert all(r.profiling is None for r in results)
