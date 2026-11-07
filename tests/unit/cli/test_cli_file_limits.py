"""The ``--timeout`` / ``--max-file-bytes`` flags of ``batch`` and ``scan``.

Covers:
- Each flag reaches the library call (``parse_files`` / ``ScanOptions``)
- ``cobol.yml``'s ``limits:`` section fills both when the flag is absent,
  and an explicit flag wins over it
- An oversize file is reported as a per-file failure end to end, the other
  file still gets its result
- Non-positive values are a clean exit-1 error
- ``config --json`` shows the ``limits`` section
The timeout's enforcement itself is pinned in ``tests/unit/test_file_limits.py``.
"""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from cobolparser.cli.parse import main

SMALL = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. SMALL.
       PROCEDURE DIVISION.
           STOP RUN.
"""

BIG = SMALL.replace("SMALL", "BIGGER") + "      *" + "X" * 64 + "\n" * 50


@pytest.fixture
def sources(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "SMALL.cbl").write_text(SMALL)
    (tmp_path / "BIG.cbl").write_text(BIG)
    return tmp_path


def _main(argv: list[str]) -> int:
    """Run the CLI; return its exit code (0 when it returns normally)."""
    with patch("sys.argv", ["cobol-parser", *argv]):
        try:
            main()
        except SystemExit as exc:
            return exc.code if isinstance(exc.code, int) else 1
    return 0


def _run(argv: list[str]) -> int:
    return _main(["--no-config", *argv])


def _limit_from_size(path) -> int:
    # Between the two files' sizes: SMALL passes, BIG is skipped.
    return path.stat().st_size + 1


def test_batch_passes_limits_to_parse_files(sources):
    with patch("cobolparser.batch.parse_files", return_value=[]) as fake:
        _run(["batch", "SMALL.cbl", "--timeout", "2.5", "--max-file-bytes", "99"])
    kwargs = fake.call_args.kwargs
    assert kwargs["timeout_seconds"] == 2.5
    assert kwargs["max_file_bytes"] == 99


def test_batch_defaults_are_no_limit(sources):
    with patch("cobolparser.batch.parse_files", return_value=[]) as fake:
        _run(["batch", "SMALL.cbl"])
    kwargs = fake.call_args.kwargs
    assert kwargs["timeout_seconds"] is None
    assert kwargs["max_file_bytes"] is None


def test_scan_passes_limits_to_scan_options(sources):
    from cobolparser.scan import ScanOptions

    seen: list[ScanOptions] = []

    def fake_scan(files, options, workers=None):
        seen.append(options)
        raise SystemExit(0)

    with patch("cobolparser.scan.scan_files", side_effect=fake_scan):
        _run(["scan", "SMALL.cbl", "--timeout", "7", "--max-file-bytes", "123"])
    assert seen[0].timeout_seconds == 7.0
    assert seen[0].max_file_bytes == 123


def test_scan_reports_an_oversize_file_and_scans_the_other(sources, capsys):
    limit = _limit_from_size(sources / "SMALL.cbl")
    _run(["scan", "SMALL.cbl", "BIG.cbl", "--max-file-bytes", str(limit)])
    out = capsys.readouterr().out
    report = json.loads(out)
    failed = json.dumps(report.get("failures"))
    assert "BIG.cbl" in failed
    assert "max_file_bytes" in failed
    assert "SMALL.cbl" not in failed


def test_batch_reports_an_oversize_file_and_parses_the_other(sources, capsys):
    limit = _limit_from_size(sources / "SMALL.cbl")
    _run(["batch", "SMALL.cbl", "BIG.cbl", "--max-file-bytes", str(limit)])
    out = capsys.readouterr().out
    assert "skipped: file is" in out
    assert "SMALL" in out


@pytest.mark.parametrize(
    ("flag", "value", "message"),
    [
        ("--timeout", "0", "--timeout must be a finite number greater than 0"),
        ("--timeout", "-1", "--timeout must be a finite number greater than 0"),
        ("--timeout", "nan", "--timeout must be a finite number greater than 0"),
        ("--timeout", "inf", "--timeout must be a finite number greater than 0"),
        ("--timeout", "1e308", "--timeout must be at most 604800"),
        ("--max-file-bytes", "0", "--max-file-bytes must be >= 1"),
    ],
)
@pytest.mark.parametrize("sub", ["batch", "scan"])
def test_non_positive_limits_are_rejected(sources, capsys, sub, flag, value, message):
    assert _run([sub, "SMALL.cbl", flag, value]) == 1
    assert message in capsys.readouterr().err


LIMITS_CONFIG = """\
limits:
  timeout_seconds: 30
  max_file_bytes: 4096
"""


def test_cobol_yml_limits_fill_the_flags_and_a_flag_wins(sources):
    (sources / "cobol.yml").write_text(LIMITS_CONFIG)
    with patch("cobolparser.batch.parse_files", return_value=[]) as fake:
        _main(["batch", "SMALL.cbl"])
    assert fake.call_args.kwargs["timeout_seconds"] == 30
    assert fake.call_args.kwargs["max_file_bytes"] == 4096

    with patch("cobolparser.batch.parse_files", return_value=[]) as fake:
        _main(["batch", "SMALL.cbl", "--timeout", "5"])
    assert fake.call_args.kwargs["timeout_seconds"] == 5
    assert fake.call_args.kwargs["max_file_bytes"] == 4096


def test_config_text_shows_limits(sources, capsys):
    (sources / "cobol.yml").write_text(LIMITS_CONFIG)
    _main(["config"])
    out = capsys.readouterr().out
    assert "[limits]" in out
    assert "timeout_seconds: 30" in out
    assert "max_file_bytes: 4096" in out


INFINITE_TIMEOUT_CONFIG = """\
limits:
  timeout_seconds: 1e999
"""


def test_cobol_yml_infinite_timeout_is_a_clean_error(sources, capsys):
    (sources / "cobol.yml").write_text(INFINITE_TIMEOUT_CONFIG)
    assert _main(["config", "--json"]) != 0
    assert "limits.timeout_seconds" in capsys.readouterr().err


def test_config_json_shows_limits(sources, capsys):
    (sources / "cobol.yml").write_text(LIMITS_CONFIG)
    _main(["config", "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert payload["limits"] == {"timeout_seconds": 30, "max_file_bytes": 4096}
