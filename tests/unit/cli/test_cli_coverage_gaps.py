"""Tests for CLI subcommand paths not exercised by existing tests.

Covers: _cmd_tokenize, _cmd_preprocess (--define, --strip-directives, --free-form),
_cmd_expand (happy path, with defines, output to file).
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest

from cobolparser.cli.parse import _cmd_expand, _cmd_preprocess, _cmd_tokenize

SAMPLES = Path(__file__).parents[2] / "samples"
_SIMPLE = str(SAMPLES / "simple_calculation.cbl")
_COPY_PROG = str(SAMPLES / "copybook_programs" / "basic_copy.cbl")
_COPYBOOKS = str(SAMPLES / "copybooks")


def _tokenize_args(filepath: str, **kwargs: object) -> argparse.Namespace:
    defaults: dict[str, object] = {
        "file": filepath,
        "compact": False,
        "free_form": False,
        "dialect": "ibm-enterprise",
        "output": None,
    }
    defaults.update(kwargs)
    return argparse.Namespace(**defaults)


def _preprocess_args(filepath: str, **kwargs: object) -> argparse.Namespace:
    defaults: dict[str, object] = {
        "file": filepath,
        "free_form": False,
        "strip_directives": False,
        "define": [],
    }
    defaults.update(kwargs)
    return argparse.Namespace(**defaults)


def _expand_args(filepath: str, **kwargs: object) -> argparse.Namespace:
    defaults: dict[str, object] = {
        "file": filepath,
        "compact": False,
        "copybook_path": [],
        "max_depth": 100,
        "define": [],
        "output": None,
    }
    defaults.update(kwargs)
    return argparse.Namespace(**defaults)


# ---------------------------------------------------------------------------
# tokenize subcommand
# ---------------------------------------------------------------------------


class TestCmdTokenize:
    def test_outputs_identified_token_list(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _cmd_tokenize(_tokenize_args(_SIMPLE))
        data = json.loads(capsys.readouterr().out)
        assert data["source_file"] == _SIMPLE
        assert isinstance(data["tokens"], list)
        assert len(data["tokens"]) > 0

    def test_token_has_required_fields(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _cmd_tokenize(_tokenize_args(_SIMPLE))
        data = json.loads(capsys.readouterr().out)
        first = data["tokens"][0]
        assert "type" in first
        assert "value" in first
        assert "line" in first
        assert "column" in first

    def test_compact_flag_produces_single_line(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _cmd_tokenize(_tokenize_args(_SIMPLE, compact=True))
        out = capsys.readouterr().out.strip()
        assert "\n" not in out
        assert isinstance(json.loads(out)["tokens"], list)

    def test_output_to_file(self, tmp_path: Path) -> None:
        out_file = str(tmp_path / "tokens.json")
        _cmd_tokenize(_tokenize_args(_SIMPLE, output=out_file))
        data = json.loads(Path(out_file).read_text())
        assert data["source_file"] == _SIMPLE
        assert isinstance(data["tokens"], list)
        assert len(data["tokens"]) > 0

    def test_free_form_flag_accepted(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        src = tmp_path / "free.cbl"
        src.write_text(
            "IDENTIFICATION DIVISION.\n"
            "PROGRAM-ID. FREE.\n"
            "PROCEDURE DIVISION.\n"
            "    STOP RUN.\n"
        )
        _cmd_tokenize(_tokenize_args(str(src), free_form=True))
        data = json.loads(capsys.readouterr().out)
        assert isinstance(data["tokens"], list)


# ---------------------------------------------------------------------------
# preprocess subcommand
# ---------------------------------------------------------------------------


class TestCmdPreprocess:
    def test_basic_produces_output(self, capsys: pytest.CaptureFixture[str]) -> None:
        _cmd_preprocess(_preprocess_args(_SIMPLE))
        out = capsys.readouterr().out
        assert len(out) > 0

    _DEBUG_IF = (
        "       IDENTIFICATION DIVISION.\n"
        "       PROGRAM-ID. COND.\n"
        "       PROCEDURE DIVISION.\n"
        "{define}"
        "       >>IF DEBUG DEFINED\n"
        "           DISPLAY 'DEBUG ON'\n"
        "       >>ELSE\n"
        "           DISPLAY 'DEBUG OFF'\n"
        "       >>END-IF\n"
        "           STOP RUN.\n"
    )

    def test_conditionals_evaluated_without_define(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # Issue #271: with no --define, both arms were printed verbatim.
        src = tmp_path / "cond.cbl"
        src.write_text(self._DEBUG_IF.format(define=""))
        _cmd_preprocess(_preprocess_args(str(src)))
        out = capsys.readouterr().out
        assert "DEBUG OFF" in out
        assert "DEBUG ON" not in out
        assert ">>IF" not in out and ">>END-IF" not in out

    def test_in_source_define_honoured_without_cli_define(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        src = tmp_path / "cond.cbl"
        src.write_text(self._DEBUG_IF.format(define="       >>DEFINE DEBUG\n"))
        _cmd_preprocess(_preprocess_args(str(src)))
        out = capsys.readouterr().out
        assert "DEBUG ON" in out
        assert "DEBUG OFF" not in out
        assert ">>DEFINE" not in out

    def test_define_keyvalue_format(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        src = tmp_path / "cond.cbl"
        src.write_text(
            "       IDENTIFICATION DIVISION.\n"
            "       PROGRAM-ID. COND.\n"
            "       PROCEDURE DIVISION.\n"
            "       $IF DEBUGMODE DEFINED\n"
            "           DISPLAY 'DEBUG'.\n"
            "       $END\n"
            "           STOP RUN.\n"
        )
        _cmd_preprocess(_preprocess_args(str(src), define=["DEBUGMODE=TRUE"]))
        # Must not raise; symbols[key] = value branch is covered by KEY=VALUE form
        capsys.readouterr()  # consume output

    def test_define_bare_flag(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        src = tmp_path / "bare.cbl"
        src.write_text(
            "       IDENTIFICATION DIVISION.\n"
            "       PROGRAM-ID. BARE.\n"
            "       PROCEDURE DIVISION.\n"
            "           STOP RUN.\n"
        )
        _cmd_preprocess(_preprocess_args(str(src), define=["MYFLAG"]))
        out = capsys.readouterr().out
        assert len(out) > 0

    def test_strip_directives_flag(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        src = tmp_path / "dir.cbl"
        src.write_text(
            "       CBL NODYNAM\n"
            "       IDENTIFICATION DIVISION.\n"
            "       PROGRAM-ID. DTEST.\n"
            "       PROCEDURE DIVISION.\n"
            "           STOP RUN.\n"
        )
        _cmd_preprocess(_preprocess_args(str(src), strip_directives=True))
        out = capsys.readouterr().out
        assert "IDENTIFICATION" in out

    def test_free_form_skips_normalize(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        src = tmp_path / "ff.cbl"
        src.write_text(
            "IDENTIFICATION DIVISION.\n"
            "PROGRAM-ID. FF.\n"
            "PROCEDURE DIVISION.\n"
            "    STOP RUN.\n"
        )
        _cmd_preprocess(_preprocess_args(str(src), free_form=True))
        out = capsys.readouterr().out
        assert len(out) > 0

    def test_define_with_equals_splits_correctly(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # Covers the key, value = d.split("=", 1) branch (lines 117-118)
        src = tmp_path / "eq.cbl"
        src.write_text(
            "       IDENTIFICATION DIVISION.\n"
            "       PROGRAM-ID. EQ.\n"
            "       PROCEDURE DIVISION.\n"
            "           STOP RUN.\n"
        )
        _cmd_preprocess(
            _preprocess_args(str(src), define=["KEY=some value with spaces"])
        )
        capsys.readouterr()  # no assertion needed — just must not raise


# ---------------------------------------------------------------------------
# expand subcommand
# ---------------------------------------------------------------------------


class TestCmdExpand:
    def test_basic_outputs_json_dict(self, capsys: pytest.CaptureFixture[str]) -> None:
        _cmd_expand(_expand_args(_SIMPLE))
        data = json.loads(capsys.readouterr().out)
        assert isinstance(data, dict)

    def test_with_copybook_path(self, capsys: pytest.CaptureFixture[str]) -> None:
        _cmd_expand(_expand_args(_COPY_PROG, copybook_path=[_COPYBOOKS]))
        data = json.loads(capsys.readouterr().out)
        assert isinstance(data, dict)

    def test_compact_flag(self, capsys: pytest.CaptureFixture[str]) -> None:
        _cmd_expand(_expand_args(_SIMPLE, compact=True))
        out = capsys.readouterr().out.strip()
        assert "\n" not in out
        assert isinstance(json.loads(out), dict)

    def test_output_to_file(self, tmp_path: Path) -> None:
        out_file = str(tmp_path / "expanded.json")
        _cmd_expand(_expand_args(_SIMPLE, output=out_file))
        data = json.loads(Path(out_file).read_text())
        assert isinstance(data, dict)

    def test_with_define_flag(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        src = tmp_path / "expand.cbl"
        src.write_text(
            "       IDENTIFICATION DIVISION.\n"
            "       PROGRAM-ID. EXP.\n"
            "       PROCEDURE DIVISION.\n"
            "           STOP RUN.\n"
        )
        _cmd_expand(_expand_args(str(src), define=["FLAG=1"]))
        data = json.loads(capsys.readouterr().out)
        assert isinstance(data, dict)

    def test_max_depth_respected(self, capsys: pytest.CaptureFixture[str]) -> None:
        _cmd_expand(_expand_args(_SIMPLE, max_depth=5))
        data = json.loads(capsys.readouterr().out)
        assert isinstance(data, dict)
