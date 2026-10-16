"""Issue #592: ``gen-data`` / ``decode`` / ``compare`` expand ``COPY``.

A record layout built from a copybook that nests another (``COPY INNER.``
inside the 01), or from a whole program whose FD record is ``COPY CUSTREC.``,
used to lose the nested member's fields without a word: the parse was run
without copybook expansion, its "COPY X was not expanded" warning was
discarded, and none of the three subcommands took ``--copybook-path``. The
record came out too short, so ``decode`` framed every record wrongly.
"""

from __future__ import annotations

import csv
import io
import sys
from pathlib import Path

import pytest

from cobolparser.cli.parse import main
from cobolparser.generators.data.copybook import (
    CopybookDataGenerator,
    parse_copybook_records,
)
from cobolparser.generators.data.decoding import RecordDecoder
from cobolparser.generators.data.errors import CopybookLayoutError
from cobolparser.generators.data.options import DataGeneratorOptions

OUTER = (
    "       01 OUT-REC.\n"
    "          05 O-ID PIC 9(4).\n"
    "          COPY INNER.\n"
    "          05 O-END PIC X(2).\n"
)
INNER = "          05 I-NAME PIC X(10).\n          05 I-AMT PIC 9(5).\n"
PROGRAM = (
    "       IDENTIFICATION DIVISION.\n"
    "       PROGRAM-ID. PROG.\n"
    "       ENVIRONMENT DIVISION.\n"
    "       INPUT-OUTPUT SECTION.\n"
    "       FILE-CONTROL.\n"
    "           SELECT F ASSIGN TO FDD.\n"
    "       DATA DIVISION.\n"
    "       FILE SECTION.\n"
    "       FD F.\n"
    "       COPY OUTER.\n"
    "       WORKING-STORAGE SECTION.\n"
    "       01 WS-X PIC X.\n"
    "       PROCEDURE DIVISION.\n"
    "           STOP RUN.\n"
)
DATA = b"0001ABCDEFGHIJ12345ZZ0002KLMNOPQRST67890YY"
FULL_COLUMNS = ["O-ID", "I-NAME", "I-AMT", "O-END"]
UNEXPANDED = "COPY INNER was not expanded"


@pytest.fixture
def tree(tmp_path: Path) -> Path:
    (tmp_path / "cpy").mkdir()
    (tmp_path / "cpy" / "OUTER.cpy").write_text(OUTER, encoding="utf-8")
    (tmp_path / "cpy" / "INNER.cpy").write_text(INNER, encoding="utf-8")
    (tmp_path / "PROG.cbl").write_text(PROGRAM, encoding="utf-8")
    (tmp_path / "data.bin").write_bytes(DATA)
    (tmp_path / "data2.bin").write_bytes(DATA)
    return tmp_path


def _run(monkeypatch: pytest.MonkeyPatch, *argv: str) -> int:
    monkeypatch.setattr(sys, "argv", ["cobol-parser", *argv])
    try:
        main()
    except SystemExit as exc:
        return int(exc.code or 0)
    return 0


def _header(out: str) -> list[str]:
    return next(csv.reader(io.StringIO(out)))


# -- library ------------------------------------------------------------------


class TestParseCopybookRecords:
    def test_nested_copy_expanded_from_copybook_paths(self, tree: Path) -> None:
        warnings: list[str] = []
        (record,) = parse_copybook_records(
            OUTER, copybook_paths=[str(tree / "cpy")], warnings=warnings
        )
        assert record.calculate_size() == 21
        assert [c.name for c in record.children] == FULL_COLUMNS
        assert warnings == []

    def test_unexpanded_copy_is_reported_not_silent(self) -> None:
        warnings: list[str] = []
        (record,) = parse_copybook_records(OUTER, warnings=warnings)
        assert record.calculate_size() == 6
        assert len(warnings) == 1 and UNEXPANDED in warnings[0]

    def test_member_missing_from_paths_is_reported(self, tmp_path: Path) -> None:
        warnings: list[str] = []
        parse_copybook_records(OUTER, copybook_paths=[str(tmp_path)], warnings=warnings)
        assert any(UNEXPANDED in w for w in warnings)

    def test_fd_copy_in_whole_program(self, tree: Path) -> None:
        records = parse_copybook_records(PROGRAM, copybook_paths=[str(tree / "cpy")])
        assert [r.name for r in records] == ["OUT-REC", "WS-X"]
        assert records[0].get_metadata("fd_file_name")

    def test_circular_copy_is_a_layout_error(self, tmp_path: Path) -> None:
        (tmp_path / "LOOP.cpy").write_text("          COPY LOOP.\n", encoding="utf-8")
        with pytest.raises(CopybookLayoutError, match="could not expand"):
            parse_copybook_records(
                "       01 R.\n          COPY LOOP.\n",
                copybook_paths=[str(tmp_path)],
            )


def test_generator_threads_copybook_paths_and_caveats(tree: Path) -> None:
    generator = CopybookDataGenerator(DataGeneratorOptions(rows=1, seed=1))
    full = generator.generate_from_file(
        tree / "cpy" / "OUTER.cpy", copybook_paths=[str(tree / "cpy")]
    )
    assert [f.name for f in full.fields] == FULL_COLUMNS
    assert not any(UNEXPANDED in c for c in full.caveats)
    short = generator.generate_from_file(tree / "cpy" / "OUTER.cpy")
    assert any(UNEXPANDED in c for c in short.caveats)


def test_decoder_threads_copybook_paths_and_warnings(tree: Path) -> None:
    decoder = RecordDecoder.from_copybook_file(
        tree / "cpy" / "OUTER.cpy", copybook_paths=[str(tree / "cpy")]
    )
    result = decoder.decode_file(tree / "data.bin")
    assert [r.values()["I-NAME"] for r in result.records] == [
        "ABCDEFGHIJ",
        "KLMNOPQRST",
    ]
    assert decoder.layout_warnings == []
    short = RecordDecoder.from_copybook_file(tree / "cpy" / "OUTER.cpy")
    assert any(UNEXPANDED in w for w in short.layout_warnings)
    assert any(UNEXPANDED in c for c in short.decode_file(tree / "data.bin").caveats)


# -- CLI ----------------------------------------------------------------------


class TestGenData:
    def test_copybook_path_expands_nested_copy(self, tree, monkeypatch, capsys):
        cpy = str(tree / "cpy")
        code = _run(
            monkeypatch, "gen-data", f"{cpy}/OUTER.cpy", "--rows", "2",
            "--seed", "1", "--copybook-path", cpy,
        )  # fmt: skip
        captured = capsys.readouterr()
        assert code == 0
        assert _header(captured.out) == FULL_COLUMNS
        assert "warning" not in captured.err

    def test_without_path_warns_on_stderr(self, tree, monkeypatch, capsys):
        _run(monkeypatch, "gen-data", str(tree / "cpy" / "OUTER.cpy"), "--seed", "1")
        captured = capsys.readouterr()
        assert _header(captured.out) == ["O-ID", "O-END"]
        assert f"warning: {UNEXPANDED}" in captured.err

    def test_list_records_size_and_warning(self, tree, monkeypatch, capsys):
        outer = str(tree / "cpy" / "OUTER.cpy")
        _run(monkeypatch, "gen-data", outer, "--list-records", "--compact")
        captured = capsys.readouterr()
        assert '"size": 6' in captured.out and UNEXPANDED in captured.err
        _run(
            monkeypatch, "gen-data", outer, "--list-records", "--compact",
            "--copybook-path", str(tree / "cpy"),
        )  # fmt: skip
        assert '"size": 21' in capsys.readouterr().out

    def test_fd_copy_in_program(self, tree, monkeypatch, capsys):
        _run(
            monkeypatch, "gen-data", str(tree / "PROG.cbl"), "--rows", "1",
            "--seed", "1", "--copybook-path", str(tree / "cpy"),
        )  # fmt: skip
        assert _header(capsys.readouterr().out) == FULL_COLUMNS

    def test_cobol_yml_copybook_path(self, tree, monkeypatch, capsys):
        (tree / "cobol.yml").write_text(
            "project:\n  copybook_path:\n    - cpy\n", encoding="utf-8"
        )
        monkeypatch.chdir(tree)
        _run(monkeypatch, "gen-data", "cpy/OUTER.cpy", "--rows", "1", "--seed", "1")
        assert _header(capsys.readouterr().out) == FULL_COLUMNS


class TestDecode:
    def test_copybook_path_frames_records_right(self, tree, monkeypatch, capsys):
        cpy = str(tree / "cpy")
        code = _run(
            monkeypatch, "decode", str(tree / "data.bin"), "--copybook",
            f"{cpy}/OUTER.cpy", "--format", "csv", "--copybook-path", cpy,
        )  # fmt: skip
        captured = capsys.readouterr()
        assert code == 0
        rows = list(csv.reader(io.StringIO(captured.out)))
        assert rows == [
            FULL_COLUMNS,
            ["1", "ABCDEFGHIJ", "12345", "ZZ"],
            ["2", "KLMNOPQRST", "67890", "YY"],
        ]
        assert captured.err == ""

    def test_without_path_warns_once(self, tree, monkeypatch, capsys):
        _run(
            monkeypatch, "decode", str(tree / "data.bin"), "--copybook",
            str(tree / "cpy" / "OUTER.cpy"), "--format", "csv",
        )  # fmt: skip
        err = capsys.readouterr().err
        assert err.count(UNEXPANDED) == 1
        assert f"warning: {UNEXPANDED}" in err


class TestCompare:
    def test_copybook_path_accepted(self, tree, monkeypatch, capsys):
        cpy = str(tree / "cpy")
        code = _run(
            monkeypatch, "compare", str(tree / "data.bin"), str(tree / "data2.bin"),
            "--copybook", f"{cpy}/OUTER.cpy", "--copybook-path", cpy,
        )  # fmt: skip
        captured = capsys.readouterr()
        assert code == 0
        assert "expected: 2 records" in captured.out
        assert UNEXPANDED not in captured.err

    def test_without_path_warns(self, tree, monkeypatch, capsys):
        _run(
            monkeypatch, "compare", str(tree / "data.bin"), str(tree / "data2.bin"),
            "--copybook", str(tree / "cpy" / "OUTER.cpy"),
        )  # fmt: skip
        assert f"warning: {UNEXPANDED}" in capsys.readouterr().err
