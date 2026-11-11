"""Missing COPY members in `batch`, `expand` and `gen-fixtures`.

`batch` took no copybook path at all, so every COPY of a multi-file run was
left out (1,077 "not expanded" warnings over one codebase); `expand` and
`gen-fixtures` failed a whole program (exit 1) on one missing member, where
the analyzers finish without it and say so. All three now follow the
analyzers: lenient by default, the missing members named in the output, and
`--strict-copybooks` for the old failure.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from cobolparser.cli import main

HAVE = "       01  HAVE-REC.\n           05  HAVE-A   PIC X(5).\n"

PROGRAM = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. P.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT IN-FILE ASSIGN TO INFILE.
       DATA DIVISION.
       FILE SECTION.
       FD  IN-FILE.
       COPY HAVE.
       WORKING-STORAGE SECTION.
       COPY MISSING.
       PROCEDURE DIVISION.
           OPEN INPUT IN-FILE
           READ IN-FILE AT END DISPLAY 'E' END-READ
           DISPLAY HAVE-A
           CLOSE IN-FILE
           STOP RUN.
"""

COMPLETE = PROGRAM.replace("       COPY MISSING.\n", "")


def _run(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture, *argv: str
) -> tuple[int, str, str]:
    monkeypatch.setattr(sys, "argv", ["cobol-parser", "--no-config", *argv])
    try:
        main()
        code = 0
    except SystemExit as exc:
        code = int(exc.code or 0)
    captured = capsys.readouterr()
    return code, captured.out, captured.err


@pytest.fixture
def estate(tmp_path: Path) -> Path:
    (tmp_path / "cpy").mkdir()
    (tmp_path / "cpy" / "HAVE.cpy").write_text(HAVE)
    (tmp_path / "P.cbl").write_text(PROGRAM)
    (tmp_path / "Q.cbl").write_text(COMPLETE)
    return tmp_path


class TestBatch:
    def _batch(self, monkeypatch, capsys, estate: Path, *flags: str):
        code, out, err = _run(
            monkeypatch,
            capsys,
            "batch",
            str(estate / "P.cbl"),
            str(estate / "Q.cbl"),
            "--workers",
            "1",
            *flags,
        )
        return code, {Path(e["path"]).name: e for e in json.loads(out)}, err

    def test_without_a_path_every_copy_is_named_and_hinted(
        self, monkeypatch, capsys, estate: Path
    ) -> None:
        code, entries, err = self._batch(monkeypatch, capsys, estate)
        assert code == 0
        assert entries["P.cbl"]["unexpanded_copybooks"] == ["HAVE", "MISSING"]
        assert entries["Q.cbl"]["unexpanded_copybooks"] == ["HAVE"]
        assert "2 of 2 file(s) have copybooks that were not expanded" in err
        assert "--copybook-path" in err

    def test_copybook_path_expands_and_names_only_the_missing_member(
        self, monkeypatch, capsys, estate: Path
    ) -> None:
        code, entries, err = self._batch(
            monkeypatch, capsys, estate, "--copybook-path", str(estate / "cpy")
        )
        assert code == 0
        assert entries["P.cbl"]["unexpanded_copybooks"] == ["MISSING"]
        assert "unexpanded_copybooks" not in entries["Q.cbl"]
        # HAVE was expanded into the AST.
        assert "HAVE-A" in json.dumps(entries["Q.cbl"]["ast"])
        assert "1 of 2 file(s)" in err

    def test_strict_copybooks_fails_the_file(
        self, monkeypatch, capsys, estate: Path
    ) -> None:
        code, entries, err = self._batch(
            monkeypatch,
            capsys,
            estate,
            "--copybook-path",
            str(estate / "cpy"),
            "--strict-copybooks",
        )
        assert code == 2
        assert "MISSING" in entries["P.cbl"]["copybook_error"]
        assert "copybook_error" not in entries["Q.cbl"]

    def test_copybook_path_comes_from_cobol_yml(
        self, monkeypatch, capsys, estate: Path
    ) -> None:
        (estate / "cobol.yml").write_text("project:\n  copybook_path: [cpy]\n")
        monkeypatch.chdir(estate)
        monkeypatch.setattr(
            sys, "argv", ["cobol-parser", "batch", "Q.cbl", "--workers", "1"]
        )
        try:
            main()
        except SystemExit as exc:
            assert not exc.code
        [entry] = json.loads(capsys.readouterr().out)
        assert "unexpanded_copybooks" not in entry


class TestExpand:
    def test_lenient_by_default(self, monkeypatch, capsys, estate: Path) -> None:
        code, out, err = _run(
            monkeypatch,
            capsys,
            "expand",
            str(estate / "P.cbl"),
            "--copybook-path",
            str(estate / "cpy"),
        )
        assert code == 0
        data = json.loads(out)
        assert data["unexpanded_copybooks"] == ["MISSING"]
        assert "HAVE-A" in data["expanded_source"]
        assert "COPY MISSING." in data["expanded_source"]
        assert "1 copybook(s) not found on the copybook path (MISSING)" in err

    def test_complete_program_has_no_unexpanded_key(
        self, monkeypatch, capsys, estate: Path
    ) -> None:
        code, out, err = _run(
            monkeypatch,
            capsys,
            "expand",
            str(estate / "Q.cbl"),
            "--copybook-path",
            str(estate / "cpy"),
        )
        assert code == 0
        assert "unexpanded_copybooks" not in json.loads(out)
        assert err == ""

    def test_strict_copybooks_keeps_the_clean_error(
        self, monkeypatch, capsys, estate: Path
    ) -> None:
        code, out, err = _run(
            monkeypatch,
            capsys,
            "expand",
            str(estate / "P.cbl"),
            "--copybook-path",
            str(estate / "cpy"),
            "--strict-copybooks",
        )
        assert code == 1
        assert "Copybook expansion failed" in err


class TestGenFixtures:
    def _gen(self, monkeypatch, capsys, estate: Path, *flags: str):
        return _run(
            monkeypatch,
            capsys,
            "gen-fixtures",
            str(estate / "P.cbl"),
            "--seed",
            "1",
            *flags,
        )

    def test_lenient_by_default_with_the_member_in_unresolved(
        self, monkeypatch, capsys, estate: Path
    ) -> None:
        code, out, err = self._gen(
            monkeypatch, capsys, estate, "--copybook-path", str(estate / "cpy")
        )
        assert code == 0
        unresolved = json.loads(out)["unresolved"]
        assert unresolved == [
            "COPY MISSING was not expanded; fields it declares are missing "
            "from the layout"
        ]
        assert "1 copybook(s) not expanded" in err

    def test_strict_exits_two_on_the_missing_member(
        self, monkeypatch, capsys, estate: Path
    ) -> None:
        code, _, err = self._gen(
            monkeypatch,
            capsys,
            estate,
            "--copybook-path",
            str(estate / "cpy"),
            "--strict",
        )
        assert code == 2
        assert "COPY MISSING was not expanded" in err

    def test_strict_copybooks_keeps_exit_one(
        self, monkeypatch, capsys, estate: Path
    ) -> None:
        code, _, err = self._gen(
            monkeypatch,
            capsys,
            estate,
            "--copybook-path",
            str(estate / "cpy"),
            "--strict-copybooks",
        )
        assert code == 1
        assert "unresolved copybook dependency" in err

    def test_list_boundaries_is_lenient_too(
        self, monkeypatch, capsys, estate: Path
    ) -> None:
        code, out, _ = self._gen(
            monkeypatch,
            capsys,
            estate,
            "--copybook-path",
            str(estate / "cpy"),
            "--list-boundaries",
        )
        assert code == 0
        assert json.loads(out)["boundaries"]

    def test_without_a_path_each_copy_is_a_caveat(
        self, monkeypatch, capsys, estate: Path
    ) -> None:
        code, out, err = self._gen(monkeypatch, capsys, estate)
        assert code == 0
        unresolved = json.loads(out)["unresolved"]
        assert any(u.startswith("COPY HAVE was not expanded") for u in unresolved)
        assert any(u.startswith("COPY MISSING was not expanded") for u in unresolved)
        assert "--copybook-path DIR" in err
