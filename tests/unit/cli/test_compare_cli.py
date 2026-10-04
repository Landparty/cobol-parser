"""Tests for the ``cobol-parser compare`` subcommand.

Every fixture is written by the record encoder from hand-picked rows, so each
file is a real EBCDIC record image -- COMP-3 included -- the same kind of file
a batch run leaves behind.
"""

from __future__ import annotations

import json
import sys

import pytest

from cobolparser.cli.parse import main
from cobolparser.generators.data.copybook import parse_copybook_records
from cobolparser.generators.data.encoding import (
    Charset,
    EncodingOptions,
    encode_record,
)
from cobolparser.generators.data.layout import flatten_record
from cobolparser.generators.data.options import DataGeneratorOptions

COPYBOOK = """       01  CUST-REC.
           05  CUST-ID         PIC 9(6).
           05  CUST-NAME       PIC X(12).
           05  CUST-BAL        PIC S9(5)V99 COMP-3.
           05  UPD-TS          PIC X(8).
"""

ROWS = [
    ["1", "ALICE", "100.00", "20260101"],
    ["2", "BOB", "-5.25", "20260101"],
    ["3", "CAROL", "0.00", "20260101"],
]


def _run(argv: list[str]) -> int:
    saved = sys.argv
    sys.argv = ["cobol-parser", *argv]
    try:
        main()
    except SystemExit as exc:
        return int(exc.code or 0)
    finally:
        sys.argv = saved
    return 0


def _write(path, rows):
    record = parse_copybook_records(COPYBOOK)[0]
    specs = flatten_record(record, DataGeneratorOptions(rows=1).for_record_image())
    opts = EncodingOptions(charset=Charset.EBCDIC)
    path.write_bytes(b"".join(encode_record(specs, row, opts) for row in rows))
    return str(path)


@pytest.fixture
def files(tmp_path):
    copybook = tmp_path / "CUST.cpy"
    copybook.write_text(COPYBOOK, encoding="utf-8")
    return tmp_path, str(copybook)


def _args(copybook, expected, actual, *extra):
    return [
        "compare",
        expected,
        actual,
        "--copybook",
        copybook,
        "--charset",
        "ebcdic",
        *extra,
    ]


def test_equal_files_exit_zero(files, capsys):
    tmp, copybook = files
    expected = _write(tmp / "E.DAT", ROWS)
    actual = _write(tmp / "A.DAT", ROWS)
    assert _run(_args(copybook, expected, actual)) == 0
    assert "files are equal" in capsys.readouterr().out


def test_a_changed_field_exits_one_and_is_named(files, capsys):
    tmp, copybook = files
    changed = [list(r) for r in ROWS]
    changed[1][2] = "-5.26"
    expected = _write(tmp / "E.DAT", ROWS)
    actual = _write(tmp / "A.DAT", changed)

    assert _run(_args(copybook, expected, actual, "--key", "CUST-ID")) == 1
    out = capsys.readouterr().out
    assert "changed 1" in out
    assert "CUST-BAL" in out and "'-5.25'" in out and "'-5.26'" in out


def test_ignore_turns_a_timestamp_difference_into_equal(files):
    tmp, copybook = files
    later = [[*r[:3], "20261231"] for r in ROWS]
    expected = _write(tmp / "E.DAT", ROWS)
    actual = _write(tmp / "A.DAT", later)
    assert _run(_args(copybook, expected, actual)) == 1
    assert _run(_args(copybook, expected, actual, "--ignore", "UPD-TS")) == 0


def test_json_output(files, capsys):
    tmp, copybook = files
    expected = _write(tmp / "E.DAT", ROWS)
    actual = _write(tmp / "A.DAT", ROWS[:2])
    code = _run(
        _args(copybook, expected, actual, "--key", "CUST-ID", "--format", "json")
    )
    data = json.loads(capsys.readouterr().out)
    assert code == 1
    assert data["missing_count"] == 1
    assert data["differences"][0]["key"] == ["3"]
    assert data["expected_file"] == expected


def test_output_file(files, tmp_path):
    tmp, copybook = files
    expected = _write(tmp / "E.DAT", ROWS)
    report = tmp_path / "report.txt"
    assert _run(_args(copybook, expected, expected, "-o", str(report))) == 0
    assert "files are equal" in report.read_text(encoding="utf-8")


def test_unknown_key_exits_two(files, capsys):
    tmp, copybook = files
    expected = _write(tmp / "E.DAT", ROWS)
    assert _run(_args(copybook, expected, expected, "--key", "CUST-NUM")) == 2
    err = capsys.readouterr().err
    assert "CUST-NUM" in err and "CUST-ID" in err


def test_missing_file_exits_two(files, capsys):
    tmp, copybook = files
    expected = _write(tmp / "E.DAT", ROWS)
    assert _run(_args(copybook, expected, str(tmp / "NOPE.DAT"))) == 2
    assert "Cannot read file" in capsys.readouterr().err


def test_bad_copybook_exits_two(files, capsys):
    tmp, _ = files
    expected = _write(tmp / "E.DAT", ROWS)
    empty = tmp / "EMPTY.cpy"
    empty.write_text("      * nothing here\n", encoding="utf-8")
    assert _run(_args(str(empty), expected, expected)) == 2


def test_negative_max_differences_exits_two(files):
    tmp, copybook = files
    expected = _write(tmp / "E.DAT", ROWS)
    assert _run(_args(copybook, expected, expected, "--max-differences", "-1")) == 2


@pytest.mark.parametrize("length", ["0", "-4"])
def test_non_positive_record_length_exits_two(files, capsys, length):
    tmp, copybook = files
    expected = _write(tmp / "E.DAT", ROWS)
    assert _run(_args(copybook, expected, expected, "--record-length", length)) == 2
    assert "--record-length must be a positive" in capsys.readouterr().err


def test_unwritable_output_exits_two_not_one(files, capsys):
    tmp, copybook = files
    expected = _write(tmp / "E.DAT", ROWS)
    target = tmp / "no-such-dir" / "report.txt"
    assert _run(_args(copybook, expected, expected, "-o", str(target))) == 2


def test_missing_config_file_exits_two_not_one(files, capsys):
    # Exit 1 means "the files differ"; a config error is trouble (2).
    tmp, copybook = files
    expected = _write(tmp / "E.DAT", ROWS)
    argv = _args(copybook, expected, expected, "--config", str(tmp / "nope.yml"))
    assert _run(argv) == 2
    assert "config file not found" in capsys.readouterr().err


def test_malformed_project_config_exits_two_not_one(files, capsys, monkeypatch):
    tmp, copybook = files
    expected = _write(tmp / "E.DAT", ROWS)
    (tmp / "cobol.yml").write_text("copybook_paths: [\n", encoding="utf-8")
    monkeypatch.chdir(tmp)
    assert _run(_args(copybook, expected, expected)) == 2
    assert "cobol.yml" in capsys.readouterr().err


def test_binary_copybook_exits_two_not_one(files, capsys):
    tmp, _copybook = files
    expected = _write(tmp / "E.DAT", ROWS)
    bad = tmp / "BAD.cpy"
    bad.write_bytes(b"\xff\xfe\x00\x81")
    assert _run(_args(str(bad), expected, expected)) == 2
    assert "Cannot read copybook" in capsys.readouterr().err


def test_different_trailing_partial_records_exit_one(files, capsys):
    # Issue #250: 'files are equal' and exit 0 although the tails differ.
    tmp, copybook = files
    expected = _write(tmp / "E.DAT", ROWS)
    actual = _write(tmp / "A.DAT", ROWS)
    with open(expected, "ab") as handle:
        handle.write(b"XYZ")
    with open(actual, "ab") as handle:
        handle.write(b"QQQ")

    for extra in ([], ["--compare-bytes"]):
        assert _run(_args(copybook, expected, actual, *extra)) == 1
        out = capsys.readouterr().out
        assert "files are equal" not in out
        assert "trailing bytes differ" in out


def test_one_sided_trailing_partial_record_exits_one_only_by_bytes(files, capsys):
    tmp, copybook = files
    expected = _write(tmp / "E.DAT", ROWS)
    actual = _write(tmp / "A.DAT", ROWS)
    with open(actual, "ab") as handle:
        handle.write(b"QQQ")

    assert _run(_args(copybook, expected, actual)) == 0
    assert "files are equal" in capsys.readouterr().out
    assert _run(_args(copybook, expected, actual, "--compare-bytes")) == 1
