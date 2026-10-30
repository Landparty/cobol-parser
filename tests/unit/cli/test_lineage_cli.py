"""The ``lineage`` and ``field-impact`` subcommands.

Analysis behaviour is covered in tests/unit/analysis/test_field_lineage.py
and test_lineage_graph.py; this pins the command-line surface.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from cobolparser.cli.parse import main

SAMPLES = Path(__file__).resolve().parents[2] / "samples" / "lineage"


def _argv(argv: tuple[str, ...]) -> list[str]:
    # field-impact parses through scan's process pool; one worker keeps it
    # in-process (as the scan tests do), which is what coverage can see.
    extra = (
        ["--workers", "1"]
        if argv[0] == "field-impact" and "--workers" not in argv
        else []
    )
    return ["cobol-parser", "--no-config", *argv, *extra]


def _run(monkeypatch, capsys, *argv: str) -> str:
    monkeypatch.setattr(sys, "argv", _argv(argv))
    main()
    return capsys.readouterr().out


def _fails(monkeypatch, capsys, *argv: str) -> str:
    monkeypatch.setattr(sys, "argv", _argv(argv))
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code != 0
    return capsys.readouterr().err


class TestLineage:
    def test_json(self, monkeypatch, capsys) -> None:
        data = json.loads(
            _run(monkeypatch, capsys, "lineage", str(SAMPLES / "WRITER.cbl"))
        )
        assert data["program_id"] == "WRITER"
        assert data["lineage_version"] == "2"
        assert {p["kind"] for p in data["ports"]} == {"file", "call", "sql", "console"}

    def test_summary_limit(self, monkeypatch, capsys) -> None:
        path = str(SAMPLES / "WRITER.cbl")
        full = json.loads(
            _run(monkeypatch, capsys, "lineage", path, "--summary-limit", "all")
        )
        assert full["summary"] and not full["statistics"]["summary_truncated"]
        one = json.loads(
            _run(monkeypatch, capsys, "lineage", path, "--summary-limit", "1")
        )
        assert len(one["summary"]) == 1
        assert one["statistics"]["summary_truncated"]
        none = json.loads(
            _run(monkeypatch, capsys, "lineage", path, "--summary-limit", "0")
        )
        assert none["summary"] == []
        assert "--summary-limit" in _fails(
            monkeypatch, capsys, "lineage", path, "--summary-limit", "-1"
        )
        assert "--summary-limit" in _fails(
            monkeypatch, capsys, "lineage", path, "--summary-limit", "many"
        )

    def test_text(self, monkeypatch, capsys) -> None:
        out = _run(
            monkeypatch,
            capsys,
            "lineage",
            str(SAMPLES / "WRITER.cbl"),
            "--format",
            "text",
        )
        assert out.startswith("Field lineage: WRITER")

    def test_field_forward_and_backward(self, monkeypatch, capsys) -> None:
        path = str(SAMPLES / "WRITER.cbl")
        data = json.loads(
            _run(monkeypatch, capsys, "lineage", path, "--field", "WS-FEE")
        )
        assert data["start"] == ["WRITER:WS-FEE"]
        assert "WRITER" in data["programs"]
        out = _run(
            monkeypatch,
            capsys,
            "lineage",
            path,
            "--field",
            "WS-FEE",
            "--direction",
            "backward",
            "--format",
            "text",
        )
        assert "WRITER:WS-FEE is fed by:" in out
        assert "WS-REC.WS-AMT" in out

    def test_output_file(self, monkeypatch, capsys, tmp_path) -> None:
        target = tmp_path / "out.json"
        _run(
            monkeypatch,
            capsys,
            "lineage",
            str(SAMPLES / "SUBPGM.cbl"),
            "-o",
            str(target),
        )
        assert json.loads(target.read_text())["program_id"] == "SUBPGM"


class TestFieldImpact:
    def test_field_across_a_directory(self, monkeypatch, capsys) -> None:
        data = json.loads(
            _run(
                monkeypatch,
                capsys,
                "field-impact",
                "IN-AMT",
                str(SAMPLES),
                "--program",
                "WRITER",
            )
        )
        assert "SUBPGM" in data["programs"]
        assert data["graph"]["programs"] == ["MISC", "READER", "SUBPGM", "WRITER"]
        assert data["problems"] == []

    def test_table_backward_text(self, monkeypatch, capsys) -> None:
        out = _run(
            monkeypatch,
            capsys,
            "field-impact",
            "--table",
            "ACCOUNT.BALANCE",
            str(SAMPLES),
            "--direction",
            "backward",
            "--format",
            "text",
        )
        assert out.startswith("ACCOUNT.BALANCE is fed by:")
        assert "WRITER" in out

    def test_dataset_with_bindings_file(self, monkeypatch, capsys, tmp_path) -> None:
        bindings = tmp_path / "bindings.json"
        bindings.write_text(
            json.dumps(
                {
                    "bindings": [
                        {"program": "WRITER", "ddname": "INFILE", "dataset": "PROD.IN"},
                        {
                            "program": "WRITER",
                            "ddname": "OUTFILE",
                            "dataset": "PROD.MID",
                        },
                        {"program": "READER", "ddname": "FEEIN", "dataset": "PROD.MID"},
                        {"program": "READER", "ddname": "MASTER", "dataset": "PROD.M"},
                    ]
                }
            )
        )
        data = json.loads(
            _run(
                monkeypatch,
                capsys,
                "field-impact",
                "--dataset",
                "PROD.IN",
                str(SAMPLES / "WRITER.cbl"),
                str(SAMPLES / "READER.cbl"),
                "--bindings",
                str(bindings),
                "--key-relationships",
                "--depth",
                "2",
            )
        )
        assert "READER" in data["programs"]
        assert "PROD.MID" in data["datasets"]
        # PROD.IN -> WRITER is one join, PROD.MID -> READER the second
        assert data["depth"] == 2
        assert any(k["key"] == "PROD.M@0+10" for k in data["key_relationships"])

    def test_jcl(self, monkeypatch, capsys) -> None:
        pytest.importorskip("jclparser")
        out = _run(
            monkeypatch,
            capsys,
            "field-impact",
            "WS-FEE",
            str(SAMPLES),
            "--program",
            "WRITER",
            "--jcl",
            str(SAMPLES / "FEEJOB.jcl"),
            "--key-relationships",
            "--format",
            "text",
        )
        assert "PROD.FEE.SUMMARY" in out
        assert "aggregate" in out or "derived" in out
        assert "Key relationships:" in out

    def test_jcl_without_jcl_parser(self, monkeypatch, capsys) -> None:
        monkeypatch.setitem(sys.modules, "jclparser", None)
        err = _fails(
            monkeypatch,
            capsys,
            "field-impact",
            "WS-FEE",
            str(SAMPLES / "WRITER.cbl"),
            "--jcl",
            str(SAMPLES / "FEEJOB.jcl"),
        )
        assert "pip install jcl-parser" in err

    @pytest.mark.parametrize(
        ("argv", "message"),
        [
            (["--table", "A.B", "--dataset", "X", "p.cbl"], "at most one"),
            (["WS-FEE"], "no COBOL sources"),
            (["WS-FEE", "p.cbl", "--workers", "0"], "--workers"),
            (["WS-FEE", "p.cbl", "--depth", "-1"], "--depth"),
        ],
    )
    def test_argument_errors(self, monkeypatch, capsys, argv, message) -> None:
        assert message in _fails(monkeypatch, capsys, "field-impact", *argv)

    def test_bad_bindings_file(self, monkeypatch, capsys, tmp_path) -> None:
        bad = tmp_path / "b.json"
        bad.write_text("[1]")
        err = _fails(
            monkeypatch,
            capsys,
            "field-impact",
            "WS-FEE",
            str(SAMPLES / "WRITER.cbl"),
            "--bindings",
            str(bad),
        )
        assert "JSON object" in err
        err = _fails(
            monkeypatch,
            capsys,
            "field-impact",
            "WS-FEE",
            str(SAMPLES / "WRITER.cbl"),
            "--bindings",
            str(tmp_path / "missing.json"),
        )
        assert "could not be read" in err

    def test_nothing_parsed_exits_1(self, monkeypatch, capsys, tmp_path) -> None:
        missing = str(tmp_path / "MISSING.cbl")
        err = _fails(monkeypatch, capsys, "field-impact", "WS-FEE", missing)
        assert "produced a lineage report" in err
        assert "MISSING.cbl" in err

    def test_unknown_start_exits_1_after_the_report(self, monkeypatch, capsys) -> None:
        monkeypatch.setattr(
            sys,
            "argv",
            _argv(("field-impact", "NO-SUCH-FIELD", str(SAMPLES / "WRITER.cbl"))),
        )
        with pytest.raises(SystemExit) as exc:
            main()
        assert exc.value.code == 1
        captured = capsys.readouterr()
        assert json.loads(captured.out)["start_found"] is False
        assert "no such field" in captured.err

    def test_text_lists_unjoined_and_problems(self, monkeypatch, capsys) -> None:
        out = _run(
            monkeypatch,
            capsys,
            "field-impact",
            "WS-FEE",
            str(SAMPLES / "WRITER.cbl"),
            str(SAMPLES / "MISSING.cbl"),
            "--format",
            "text",
        )
        assert "Unjoined:\n  - WRITER: DD INFILE is not bound to any dataset" in out
        assert "Problems:\n  - " in out and "MISSING.cbl" in out
