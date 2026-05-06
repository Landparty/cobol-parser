"""Integration tests: parse_cobol / CobolParser.parse() with enable_profiling=True."""
import pytest
from cobolparser import CobolParser, parse_cobol
from cobolparser.profiling import ProfilingResult

_HELLO = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. HELLO.
       PROCEDURE DIVISION.
           DISPLAY 'Hello World'.
           STOP RUN.
"""


def test_parse_method_profiling_returns_tuple():
    parser = CobolParser()
    result = parser.parse(_HELLO, enable_profiling=True)
    assert isinstance(result, tuple)
    assert len(result) == 2


def test_parse_method_profiling_result_type():
    parser = CobolParser()
    _, prof = parser.parse(_HELLO, enable_profiling=True)
    assert isinstance(prof, ProfilingResult)


def test_parse_method_no_profiling_returns_parse_result():
    from cobolparser.parser import ParseResult
    parser = CobolParser()
    result = parser.parse(_HELLO)
    assert isinstance(result, ParseResult)


def test_parse_method_profiling_metrics_positive():
    parser = CobolParser()
    _, prof = parser.parse(_HELLO, enable_profiling=True)
    assert prof.wall_clock_s >= 0.0
    assert prof.peak_memory_mb >= 0.0


def test_parse_method_profiling_top_functions_non_empty():
    parser = CobolParser()
    _, prof = parser.parse(_HELLO, enable_profiling=True)
    assert len(prof.top_functions) > 0


def test_parse_method_profiling_top_n_respected():
    parser = CobolParser()
    _, prof = parser.parse(_HELLO, enable_profiling=True, top_n=3)
    assert len(prof.top_functions) <= 3


def test_parse_method_profiling_prof_file(tmp_path):
    import os
    prof_path = str(tmp_path / "parse.prof")
    parser = CobolParser()
    parser.parse(_HELLO, enable_profiling=True, prof_output=prof_path)
    assert os.path.exists(prof_path)


def test_parse_method_profiling_ast_still_valid():
    parser = CobolParser()
    parse_result, _ = parser.parse(_HELLO, enable_profiling=True)
    assert parse_result.ast is not None
    assert parse_result.ast.program_name == "HELLO"
