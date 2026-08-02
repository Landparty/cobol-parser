"""Tests for the ``cobol-parser gen-data`` CLI subcommand."""

from __future__ import annotations

import csv
import io
import json
from pathlib import Path

import pytest

from cobolparser.cli.parse import _build_parser, main

SAMPLES = Path(__file__).parents[2] / "samples"
TXNDATA = str(SAMPLES / "copybooks" / "TXNDATA.cpy")
CUSTOMER = str(SAMPLES / "copybooks" / "CUSTOMER.cpy")


def _run(monkeypatch, *argv: str) -> None:
    monkeypatch.setattr("sys.argv", ["cobol-parser", "gen-data", *argv])
    main()


def _csv_out(capsys) -> list[list[str]]:
    return list(csv.reader(io.StringIO(capsys.readouterr().out)))


class TestGenDataParser:
    def test_subcommand_is_registered(self):
        args = _build_parser().parse_args(["gen-data", TXNDATA])
        assert args.command == "gen-data"
        assert args.rows == 10

    def test_defaults(self):
        args = _build_parser().parse_args(["gen-data", TXNDATA])
        assert args.seed is None
        assert args.header_style == "short"
        assert not args.include_filler
        assert not args.include_redefines
        assert args.blank_rate == 0.0

    def test_short_flags(self):
        args = _build_parser().parse_args(["gen-data", TXNDATA, "-n", "5"])
        assert args.rows == 5

    def test_repeatable_unique_flag(self):
        args = _build_parser().parse_args(
            ["gen-data", TXNDATA, "--unique", "A", "--unique", "B"]
        )
        assert args.unique == ["A", "B"]


class TestGenDataOutput:
    def test_emits_csv_on_stdout(self, monkeypatch, capsys):
        _run(monkeypatch, CUSTOMER, "--rows", "3", "--seed", "1")
        rows = _csv_out(capsys)
        assert rows[0] == [
            "CUSTOMER-ID",
            "CUSTOMER-NAME",
            "STREET",
            "CITY",
            "STATE",
            "ZIP",
        ]
        assert len(rows) == 4

    def test_output_is_reproducible_for_a_seed(self, monkeypatch, capsys):
        _run(monkeypatch, TXNDATA, "--rows", "6", "--seed", "99")
        first = capsys.readouterr().out
        _run(monkeypatch, TXNDATA, "--rows", "6", "--seed", "99")
        assert capsys.readouterr().out == first

    def test_writes_to_output_file(self, monkeypatch, capsys, tmp_path):
        target = tmp_path / "data.csv"
        _run(monkeypatch, CUSTOMER, "--rows", "4", "--seed", "2", "-o", str(target))
        assert capsys.readouterr().out == ""
        rows = list(csv.reader(target.open(newline="")))
        assert len(rows) == 5

    def test_rows_flag_controls_record_count(self, monkeypatch, capsys):
        _run(monkeypatch, CUSTOMER, "--rows", "17", "--seed", "3")
        assert len(_csv_out(capsys)) == 18

    def test_header_style_path(self, monkeypatch, capsys):
        _run(
            monkeypatch,
            CUSTOMER,
            "--rows",
            "1",
            "--seed",
            "4",
            "--header-style",
            "path",
        )
        assert _csv_out(capsys)[0][0] == "CUSTOMER-RECORD.CUSTOMER-ID"

    def test_include_filler_and_redefines(self, monkeypatch, capsys):
        _run(
            monkeypatch,
            TXNDATA,
            "--rows",
            "1",
            "--seed",
            "5",
            "--include-filler",
            "--include-redefines",
        )
        header = _csv_out(capsys)[0]
        assert "FILLER" in header
        assert "PART-A" in header

    def test_no_expand_occurs(self, monkeypatch, capsys):
        _run(monkeypatch, TXNDATA, "--rows", "1", "--seed", "6", "--no-expand-occurs")
        header = _csv_out(capsys)[0]
        assert "ITEM-CODE(1)" in header
        assert "ITEM-CODE(2)" not in header

    def test_max_occurs(self, monkeypatch, capsys):
        _run(monkeypatch, TXNDATA, "--rows", "1", "--seed", "7", "--max-occurs", "2")
        header = _csv_out(capsys)[0]
        assert "ITEM-CODE(2)" in header
        assert "ITEM-CODE(3)" not in header

    def test_blank_rate_one_blanks_everything(self, monkeypatch, capsys):
        _run(monkeypatch, CUSTOMER, "--rows", "2", "--seed", "8", "--blank-rate", "1.0")
        rows = _csv_out(capsys)
        assert all(cell == "" for row in rows[1:] for cell in row)

    def test_unique_flag_yields_distinct_values(self, monkeypatch, capsys):
        _run(
            monkeypatch,
            TXNDATA,
            "--rows",
            "25",
            "--seed",
            "9",
            "--unique",
            "TXN-ID",
        )
        rows = _csv_out(capsys)
        index = rows[0].index("TXN-ID")
        values = [row[index] for row in rows[1:]]
        assert len(values) == len(set(values))

    def test_ignore_values_widens_the_domain(self, monkeypatch, capsys):
        _run(monkeypatch, TXNDATA, "--rows", "40", "--seed", "10", "--ignore-values")
        rows = _csv_out(capsys)
        index = rows[0].index("TXN-TYPE")
        assert {row[index] for row in rows[1:]} - {"D", "W", "T"}


class TestGenDataJsonModes:
    def test_list_records(self, monkeypatch, capsys):
        _run(monkeypatch, TXNDATA, "--list-records")
        payload = json.loads(capsys.readouterr().out)
        assert payload["source_file"] == TXNDATA
        assert [r["name"] for r in payload["records"]] == ["TXN-RECORD"]

    def test_describe_emits_layout_and_rows(self, monkeypatch, capsys):
        _run(monkeypatch, CUSTOMER, "--rows", "2", "--seed", "11", "--describe")
        payload = json.loads(capsys.readouterr().out)
        assert payload["record_name"] == "CUSTOMER-RECORD"
        assert payload["seed"] == 11
        assert payload["row_count"] == 2
        assert payload["fields"][0]["picture"] == "9(8)"

    def test_describe_reports_the_seed_chosen_at_random(self, monkeypatch, capsys):
        _run(monkeypatch, CUSTOMER, "--rows", "1", "--describe")
        assert isinstance(json.loads(capsys.readouterr().out)["seed"], int)

    def test_compact_json(self, monkeypatch, capsys):
        _run(monkeypatch, TXNDATA, "--list-records", "--compact")
        assert "\n" not in capsys.readouterr().out.strip()


class TestGenDataErrors:
    def test_missing_file(self, monkeypatch, capsys):
        with pytest.raises(SystemExit) as exc:
            _run(monkeypatch, "does-not-exist.cpy")
        assert exc.value.code == 1
        assert "File not found" in capsys.readouterr().err

    def test_unknown_record(self, monkeypatch, capsys):
        with pytest.raises(SystemExit) as exc:
            _run(monkeypatch, CUSTOMER, "--record", "NOPE")
        assert exc.value.code == 1
        assert "CUSTOMER-RECORD" in capsys.readouterr().err

    def test_invalid_blank_rate(self, monkeypatch, capsys):
        with pytest.raises(SystemExit) as exc:
            _run(monkeypatch, CUSTOMER, "--blank-rate", "2.5")
        assert exc.value.code == 1
        assert "blank_rate" in capsys.readouterr().err

    def test_negative_rows(self, monkeypatch, capsys):
        with pytest.raises(SystemExit) as exc:
            _run(monkeypatch, CUSTOMER, "--rows", "-3")
        assert exc.value.code == 1
        assert "rows" in capsys.readouterr().err

    def test_copybook_with_no_record(self, monkeypatch, capsys, tmp_path):
        empty = tmp_path / "EMPTY.cpy"
        empty.write_text("      * nothing but a comment\n")
        with pytest.raises(SystemExit) as exc:
            _run(monkeypatch, str(empty))
        assert exc.value.code == 1
        assert "no level-01 record" in capsys.readouterr().err
