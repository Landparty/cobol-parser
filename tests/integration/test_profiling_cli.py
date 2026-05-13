"""Integration tests: CLI profiling flags."""

import contextlib
import io
import json
from pathlib import Path

import pytest

_HELLO = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. HELLO.
       PROCEDURE DIVISION.
           DISPLAY 'Hello World'.
           STOP RUN.
"""


@pytest.fixture
def cobol_file(tmp_path):
    p = tmp_path / "hello.cbl"
    p.write_text(_HELLO, encoding="utf-8")
    return str(p)


def _run_cli(argv: list[str]) -> str:
    """Run cobol-parser CLI and capture stdout."""
    from cobolparser.cli.parse import _build_parser

    parser = _build_parser()
    args = parser.parse_args(argv)
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        args.func(args)
    return buf.getvalue()


def test_parse_no_profile_no_profiling_key(cobol_file):
    out = _run_cli(["parse", cobol_file])
    data = json.loads(out)
    assert "profiling" not in data


def test_parse_with_profile_has_profiling_key(cobol_file):
    out = _run_cli(["parse", cobol_file, "--profile"])
    data = json.loads(out)
    assert "profiling" in data
    assert data["profiling"]["wall_clock_s"] > 0.0
    assert data["profiling"]["peak_memory_mb"] >= 0.0


def test_parse_profile_top_n_respected(cobol_file):
    out = _run_cli(["parse", cobol_file, "--profile", "--profile-top-n", "3"])
    data = json.loads(out)
    assert 0 < len(data["profiling"]["top_functions"]) <= 3


def test_parse_profile_writes_prof_file(cobol_file, tmp_path):
    prof_path = str(tmp_path / "out.prof")
    _run_cli(["parse", cobol_file, "--profile", "--profile-output", prof_path])
    assert Path(prof_path).exists()


def test_analyze_with_profile_has_profiling_key(cobol_file):
    out = _run_cli(["analyze", cobol_file, "--profile"])
    data = json.loads(out)
    assert "profiling" in data
    assert data["profiling"]["wall_clock_s"] > 0.0


def test_dead_code_with_profile_has_profiling_key(cobol_file):
    out = _run_cli(["dead-code", cobol_file, "--profile"])
    data = json.loads(out)
    assert "profiling" in data


def test_program_flow_with_profile_has_profiling_key(cobol_file):
    out = _run_cli(["program-flow", cobol_file, "--profile"])
    data = json.loads(out)
    assert "profiling" in data


def test_batch_with_profile_has_profiling_per_file(tmp_path):
    p = tmp_path / "prog.cbl"
    p.write_text(_HELLO, encoding="utf-8")
    out = _run_cli(["batch", str(p), "--profile"])
    data = json.loads(out)
    assert len(data) == 1
    assert "profiling" in data[0]
    assert data[0]["profiling"]["wall_clock_s"] > 0.0


def test_batch_no_profile_no_profiling_key(tmp_path):
    p = tmp_path / "prog.cbl"
    p.write_text(_HELLO, encoding="utf-8")
    out = _run_cli(["batch", str(p)])
    data = json.loads(out)
    assert "profiling" not in data[0]


def test_parse_find_type_with_profile_includes_profiling_key(cobol_file):
    out = _run_cli(
        ["parse", cobol_file, "--profile", "--find-type", "DisplayStatement"]
    )
    data = json.loads(out)
    assert "profiling" in data
    assert isinstance(data["result"], list)


def test_parse_path_with_profile_includes_profiling_key(cobol_file):
    out = _run_cli(["parse", cobol_file, "procedure", "--profile"])
    data = json.loads(out)
    assert "profiling" in data


def test_batch_profile_output_dot_prof_raises(tmp_path):
    p = tmp_path / "prog.cbl"
    p.write_text(_HELLO, encoding="utf-8")
    with pytest.raises(SystemExit):
        _run_cli(["batch", str(p), "--profile", "--profile-output", "out.prof"])
