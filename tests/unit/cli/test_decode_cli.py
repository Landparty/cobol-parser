"""Tests for the ``cobol-parser decode`` and ``dclgen-check`` subcommands."""

from __future__ import annotations

import csv
import io
import json

import pytest

from cobolparser.cli.parse import main

COPYBOOK = """       01  CUST-REC.
           05  CUST-ID         PIC 9(6).
           05  CUST-NAME       PIC X(12).
           05  CUST-BAL        PIC S9(5)V99 COMP-3.
           05  ADDR-HOME.
               10  HOME-STREET PIC X(9).
               10  HOME-ZIP    PIC 9(5).
           05  ADDR-OVERSEAS REDEFINES ADDR-HOME.
               10  OS-COUNTRY  PIC X(4).
               10  OS-LINE     PIC X(10).
"""

DCLGEN = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. DCLTEST.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
           EXEC SQL DECLARE CUSTOMER TABLE
               (CUST_NAME CHAR(30) NOT NULL)
           END-EXEC.
       01  DCLCUSTOMER.
           05  CUST-NAME       PIC X(20).
       PROCEDURE DIVISION.
       MAIN-PARA.
           EXEC SQL
               SELECT CUST_NAME INTO :CUST-NAME FROM CUSTOMER
           END-EXEC.
           GOBACK.
"""


def _run(argv: list[str]) -> None:
    import sys

    saved = sys.argv
    sys.argv = ["cobol-parser", *argv]
    try:
        main()
    finally:
        sys.argv = saved


@pytest.fixture
def sample(tmp_path):
    """A copybook, and an EBCDIC record image generated from it."""
    copybook = tmp_path / "CUST.cpy"
    copybook.write_text(COPYBOOK, encoding="utf-8")
    data = tmp_path / "CUST.DAT"
    _run(
        [
            "gen-data",
            str(copybook),
            "--rows",
            "4",
            "--seed",
            "3",
            "--format",
            "record",
            "--charset",
            "ebcdic",
            "-o",
            str(data),
        ]
    )
    return copybook, data


def test_decode_prints_the_records_as_csv(sample, capsys):
    copybook, data = sample
    capsys.readouterr()
    _run(["decode", str(data), "--copybook", str(copybook), "--charset", "ebcdic"])
    rows = list(csv.reader(io.StringIO(capsys.readouterr().out)))
    assert rows[0] == ["CUST-ID", "CUST-NAME", "CUST-BAL", "HOME-STREET", "HOME-ZIP"]
    assert len(rows) == 5  # header + 4 records


def test_decode_round_trips_the_generated_csv(sample, capsys):
    """The bytes gen-data wrote, read back, are the CSV gen-data would have
    written -- the two halves of the same layout, checked against each other
    through the CLI rather than only in the library."""
    copybook, data = sample
    capsys.readouterr()
    _run(["gen-data", str(copybook), "--rows", "4", "--seed", "3"])
    generated = capsys.readouterr().out
    _run(["decode", str(data), "--copybook", str(copybook), "--charset", "ebcdic"])
    assert capsys.readouterr().out == generated


def test_decode_switches_redefines_overlay(sample, capsys):
    copybook, data = sample
    capsys.readouterr()
    _run(
        [
            "decode",
            str(data),
            "--copybook",
            str(copybook),
            "--charset",
            "ebcdic",
            "--view",
            "ADDR-OVERSEAS",
        ]
    )
    rows = list(csv.reader(io.StringIO(capsys.readouterr().out)))
    assert "OS-COUNTRY" in rows[0] and "OS-LINE" in rows[0]
    assert "HOME-STREET" not in rows[0]
    assert len(rows) == 5


def test_list_views_reports_offsets_without_reading_the_data(tmp_path, capsys):
    """No data file at all -- this is what an editor asks for to draw a
    record map, and what a user runs to find out what --view accepts."""
    copybook = tmp_path / "CUST.cpy"
    copybook.write_text(COPYBOOK, encoding="utf-8")
    capsys.readouterr()
    _run(["decode", "--copybook", str(copybook), "--list-views"])
    payload = json.loads(capsys.readouterr().out)
    assert payload["record_name"] == "CUST-REC"
    assert [v["name"] for v in payload["views"]] == [
        "CUST-REC",
        "CUST-REC.ADDR-OVERSEAS",
    ]
    overlay = payload["views"][1]
    assert overlay["offset"] == payload["views"][0]["fields"][3]["offset"]


def test_json_format_carries_the_bytes_behind_every_value(sample, capsys):
    copybook, data = sample
    capsys.readouterr()
    _run(
        [
            "decode",
            str(data),
            "--copybook",
            str(copybook),
            "--charset",
            "ebcdic",
            "--format",
            "json",
            "--max-records",
            "1",
        ]
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["record_count"] == 1
    field = payload["records"][0]["fields"][2]
    assert field["name"] == "CUST-BAL"
    assert field["usage"] == "COMP-3"
    assert len(field["hex"].split()) == field["length"] == 4


def test_hex_format_annotates_the_bytes_field_by_field(sample, capsys):
    copybook, data = sample
    capsys.readouterr()
    _run(
        [
            "decode",
            str(data),
            "--copybook",
            str(copybook),
            "--charset",
            "ebcdic",
            "--format",
            "hex",
            "--max-records",
            "1",
        ]
    )
    out = capsys.readouterr().out
    assert "* record layout: CUST-REC" in out
    assert "CUST-BAL" in out and "COMP-3" in out
    assert "OFFSET" in out


def test_skip_and_max_records_page_through_the_file(sample, capsys):
    copybook, data = sample
    capsys.readouterr()
    _run(
        [
            "decode",
            str(data),
            "--copybook",
            str(copybook),
            "--charset",
            "ebcdic",
            "--skip",
            "2",
            "--max-records",
            "1",
        ]
    )
    rows = list(csv.reader(io.StringIO(capsys.readouterr().out)))
    assert len(rows) == 2  # header + the one record asked for


def test_trailing_bytes_are_warned_about_not_swallowed(sample, capsys, tmp_path):
    copybook, data = sample
    truncated = tmp_path / "SHORT.DAT"
    truncated.write_bytes(data.read_bytes() + b"\x40\x40")
    capsys.readouterr()
    _run(
        [
            "decode",
            str(truncated),
            "--copybook",
            str(copybook),
            "--charset",
            "ebcdic",
        ]
    )
    captured = capsys.readouterr()
    assert "trailing bytes" in captured.err
    assert len(list(csv.reader(io.StringIO(captured.out)))) == 5


def test_strict_exits_non_zero_on_a_mismatched_file(sample, capsys, tmp_path):
    copybook, data = sample
    truncated = tmp_path / "SHORT.DAT"
    truncated.write_bytes(data.read_bytes() + b"\x40\x40")
    with pytest.raises(SystemExit) as excinfo:
        _run(
            [
                "decode",
                str(truncated),
                "--copybook",
                str(copybook),
                "--charset",
                "ebcdic",
                "--strict",
            ]
        )
    assert excinfo.value.code == 1


def test_decoding_without_a_data_file_fails_cleanly(tmp_path, capsys):
    copybook = tmp_path / "CUST.cpy"
    copybook.write_text(COPYBOOK, encoding="utf-8")
    with pytest.raises(SystemExit) as excinfo:
        _run(["decode", "--copybook", str(copybook)])
    assert excinfo.value.code == 1
    assert "needs a data file" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("flags", "message"),
    [
        (["--record-length", "-2"], "--record-length must be a positive"),
        (["--record-length", "0"], "--record-length must be a positive"),
        (["--max-records", "-1"], "--max-records cannot be negative"),
        (["--skip", "-1"], "--skip cannot be negative"),
    ],
)
def test_out_of_range_paging_flags_fail_cleanly(sample, capsys, flags, message):
    # Before: a negative --record-length claimed the layout was zero bytes
    # long, 0 was silently swapped for the layout length, and a negative
    # --max-records printed a header and nothing else, exit 0.
    copybook, data = sample
    with pytest.raises(SystemExit) as excinfo:
        _run(["decode", str(data), "--copybook", str(copybook), *flags])
    assert excinfo.value.code == 1
    assert message in capsys.readouterr().err


def test_an_unreadable_copybook_fails_cleanly(tmp_path, capsys):
    with pytest.raises(SystemExit) as excinfo:
        _run(
            [
                "decode",
                str(tmp_path / "x.DAT"),
                "--copybook",
                str(tmp_path / "missing.cpy"),
            ]
        )
    assert excinfo.value.code == 1
    assert "Cannot read copybook" in capsys.readouterr().err


def test_output_file_gets_the_same_bytes_as_stdout(sample, capsys, tmp_path):
    copybook, data = sample
    out = tmp_path / "out.csv"
    capsys.readouterr()
    _run(["decode", str(data), "--copybook", str(copybook), "--charset", "ebcdic"])
    on_stdout = capsys.readouterr().out
    _run(
        [
            "decode",
            str(data),
            "--copybook",
            str(copybook),
            "--charset",
            "ebcdic",
            "-o",
            str(out),
        ]
    )
    assert out.read_text(encoding="utf-8") == on_stdout


# ---------------------------------------------------------------------------
# dclgen-check
# ---------------------------------------------------------------------------


def test_dclgen_check_reports_the_mismatch(tmp_path, capsys):
    source = tmp_path / "DCLTEST.cbl"
    source.write_text(DCLGEN, encoding="utf-8")
    capsys.readouterr()
    _run(["dclgen-check", str(source)])
    payload = json.loads(capsys.readouterr().out)
    assert payload["violation_count"] == 1
    violation = payload["violations"][0]
    assert violation["kind"] == "length"
    assert violation["severity"] == "error"
    assert violation["host_variable"] == "CUST-NAME"
    assert violation["column"] == "CUST_NAME"


def test_dclgen_check_is_a_lint_rule_too(tmp_path, capsys):
    source = tmp_path / "DCLTEST.cbl"
    source.write_text(DCLGEN, encoding="utf-8")
    capsys.readouterr()
    _run(["lint", str(source), "--rule", "dclgen-check", "--format", "json"])
    payload = json.loads(capsys.readouterr().out)
    assert payload["rules_run"] == ["dclgen-check"]
    assert payload["findings"][0]["rule"] == "dclgen-check"
    assert payload["findings"][0]["kind"] == "length"
