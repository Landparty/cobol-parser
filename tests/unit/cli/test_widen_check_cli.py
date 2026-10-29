"""The ``widen-check`` subcommand.

Analysis behaviour is covered in tests/unit/analysis/test_field_widening.py;
this pins the command-line surface.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from cobolparser.cli.parse import main

SAMPLES = Path(__file__).resolve().parents[2] / "samples" / "widening"


def _argv(argv: tuple[str, ...]) -> list[str]:
    # One worker keeps the scan in-process, where coverage can see it.
    return ["cobol-parser", "--no-config", "widen-check", *argv, "--workers", "1"]


def _run(monkeypatch, capsys, *argv: str) -> str:
    monkeypatch.setattr(sys, "argv", _argv(argv))
    main()
    return capsys.readouterr().out


def _exit(monkeypatch, capsys, *argv: str) -> tuple[int, str, str]:
    monkeypatch.setattr(sys, "argv", _argv(argv))
    with pytest.raises(SystemExit) as exc:
        main()
    captured = capsys.readouterr()
    return int(exc.value.code or 0), captured.out, captured.err


def _bindings(tmp_path: Path) -> str:
    path = tmp_path / "bindings.json"
    path.write_text(
        json.dumps(
            {
                "bindings": [
                    {"program": "CUSTWRT", "ddname": "CUSTOUT", "dataset": "PROD.CUST"},
                    {"program": "CUSTRD", "ddname": "CUSTIN", "dataset": "PROD.CUST"},
                ]
            }
        )
    )
    return str(path)


class TestWidenCheck:
    def test_json(self, monkeypatch, capsys, tmp_path) -> None:
        data = json.loads(
            _run(
                monkeypatch,
                capsys,
                "CUST-ID",
                str(SAMPLES),
                "--to",
                "PIC 9(9)",
                "--program",
                "CUSTWRT",
                "--bindings",
                _bindings(tmp_path),
            )
        )
        assert data["widening_version"] == "1"
        assert data["starts"][0]["new_bytes"] == 9
        assert data["problems"] == []
        kinds = {(f["kind"], f["program"], f["field"]) for f in data["findings"]}
        assert ("layout", "CUSTRD", "dataset:PROD.CUST") in kinds
        assert ("truncation", "CUSTWRT", "WS-ID-TEXT") in kinds

    def test_text_and_min_severity(self, monkeypatch, capsys) -> None:
        out = _run(
            monkeypatch,
            capsys,
            "CUST-ID",
            "--to",
            "9(9)",
            str(SAMPLES / "CUSTWRT.cbl"),
            "--min-severity",
            "error",
            "--format",
            "text",
        )
        assert out.startswith("CUST-ID -> PIC 9(9)")
        assert "ERROR" in out
        assert "INFO" not in out and "WARNING" not in out

    def test_fail_on(self, monkeypatch, capsys) -> None:
        code, out, _err = _exit(
            monkeypatch,
            capsys,
            "CUST-ID",
            str(SAMPLES / "CUSTWRT.cbl"),
            "--to",
            "9(9)",
            "--fail-on",
            "error",
        )
        assert code == 3
        assert json.loads(out)["summary"]["error"] >= 1

    def test_same_size_change_passes_fail_on(self, monkeypatch, capsys) -> None:
        # 9(6) -> X(6): same bytes; only pre-existing (info) findings remain.
        out = _run(
            monkeypatch,
            capsys,
            "CUST-ID",
            str(SAMPLES / "CUSTWRT.cbl"),
            "--to",
            "X(6)",
            "--fail-on",
            "warning",
        )
        assert json.loads(out)["summary"]["error"] == 0

    def test_usage(self, monkeypatch, capsys) -> None:
        data = json.loads(
            _run(
                monkeypatch,
                capsys,
                "CUST-ID",
                str(SAMPLES / "CUSTWRT.cbl"),
                "--to",
                "9(9)",
                "--usage",
                "COMP-3",
            )
        )
        assert data["starts"][0]["new_bytes"] == 5
        assert data["new_usage"] == "COMP-3"

    def test_no_such_field(self, monkeypatch, capsys) -> None:
        code, out, err = _exit(
            monkeypatch, capsys, "NOPE", str(SAMPLES), "--to", "9(9)"
        )
        assert code == 1
        assert "no such field" in err
        assert json.loads(out)["start_found"] is False

    def test_nothing_to_check(self, monkeypatch, capsys) -> None:
        code, out, err = _exit(
            monkeypatch, capsys, "CUST-REC", str(SAMPLES), "--to", "X(40)"
        )
        assert code == 1
        assert "nothing to check" in err

    @pytest.mark.parametrize(
        ("flag", "value", "message"),
        [("--depth", "-1", "--depth"), ("--workers", "0", "--workers")],
    )
    def test_bad_numbers(self, monkeypatch, capsys, flag, value, message) -> None:
        monkeypatch.setattr(
            sys,
            "argv",
            [
                "cobol-parser",
                "--no-config",
                "widen-check",
                "CUST-ID",
                str(SAMPLES),
                "--to",
                "9(9)",
                flag,
                value,
            ],
        )
        with pytest.raises(SystemExit) as exc:
            main()
        assert exc.value.code == 1
        assert message in capsys.readouterr().err

    def test_no_report(self, monkeypatch, capsys, tmp_path) -> None:
        empty = tmp_path / "none"
        empty.mkdir()
        code, _out, err = _exit(
            monkeypatch, capsys, "CUST-ID", str(empty), "--to", "9(9)"
        )
        assert code == 1
        assert "no COBOL program" in err
