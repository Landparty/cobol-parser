"""#328: ``--profile-output`` / ``--profile-top-n`` without ``--profile``,
and a ``--profile-output`` path of the wrong kind.

Both used to fail quietly or loudly: the flags alone did nothing and said
nothing, and a directory path crashed with ``IsADirectoryError`` from
``cProfile.dump_stats()`` after the whole parse had run.
"""

from __future__ import annotations

import json

import pytest

from cobolparser.cli.parse import _build_parser

_HELLO = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. HELLO.
       PROCEDURE DIVISION.
           DISPLAY 'Hello World'.
           STOP RUN.
"""


@pytest.fixture
def cobol_file(tmp_path):
    path = tmp_path / "hello.cbl"
    path.write_text(_HELLO, encoding="utf-8")
    return str(path)


def _run(argv: list[str]) -> None:
    args = _build_parser().parse_args(argv)
    args.func(args)


class TestProfileOutputImpliesProfile:
    def test_profile_output_alone_writes_the_prof_file(
        self, cobol_file, tmp_path, capsys
    ):
        prof = tmp_path / "x.prof"

        _run(["parse", cobol_file, "--profile-output", str(prof)])

        assert prof.is_file() and prof.stat().st_size > 0
        assert "profiling" in json.loads(capsys.readouterr().out)

    def test_non_default_top_n_alone_turns_profiling_on(self, cobol_file, capsys):
        _run(["parse", cobol_file, "--profile-top-n", "3"])

        data = json.loads(capsys.readouterr().out)
        assert 0 < len(data["profiling"]["top_functions"]) <= 3

    def test_no_profiling_flag_still_means_no_profiling(self, cobol_file, capsys):
        _run(["parse", cobol_file])

        assert "profiling" not in json.loads(capsys.readouterr().out)

    def test_analyzer_subcommand_honours_profile_output_alone(
        self, cobol_file, tmp_path, capsys
    ):
        prof = tmp_path / "dead.prof"

        _run(["dead-code", cobol_file, "--profile-output", str(prof)])

        assert prof.is_file()

    def test_batch_profile_output_alone_writes_per_file_profs(
        self, cobol_file, tmp_path, capsys
    ):
        out_dir = tmp_path / "profs"

        _run(["batch", cobol_file, "--workers", "1", "--profile-output", str(out_dir)])

        assert list(out_dir.glob("*.prof"))


class TestProfileOutputPathKind:
    def test_directory_path_is_a_one_line_error(self, cobol_file, tmp_path, capsys):
        pdir = tmp_path / "pdir"
        pdir.mkdir()

        with pytest.raises(SystemExit) as exc:
            _run(["parse", cobol_file, "--profile", "--profile-output", str(pdir)])

        assert exc.value.code == 1
        err = capsys.readouterr().err
        assert err.startswith("error: --profile-output ")
        assert "is a directory" in err
        assert len(err.strip().splitlines()) == 1

    def test_batch_existing_regular_file_is_a_one_line_error(
        self, cobol_file, tmp_path, capsys
    ):
        existing = tmp_path / "not-a-dir"
        existing.write_text("", encoding="utf-8")

        with pytest.raises(SystemExit) as exc:
            _run(["batch", cobol_file, "--profile", "--profile-output", str(existing)])

        assert exc.value.code == 1
        assert "is a file" in capsys.readouterr().err
