"""Tests for the ``--source-format`` layout flag.

Auto-detection is the default and now understands change-tracking tags in
columns 1-6 (see
``tests/regression/test_tagged_sequence_area_detection.py``). This flag is the
escape hatch for the cases the heuristic cannot infer, in both directions.
``--free-form`` is retained with its historical, weaker semantics: a hint
that auto-detection may still override by normalizing source it classifies
as fixed-format -- scripts that always passed it against conventional
fixed-format members relied on exactly that. ``--source-format=free`` is the
strict spelling that disables normalization outright.
"""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from cobolparser.cli.parse import main


def _run_main(argv: list[str]) -> None:
    with patch("sys.argv", ["cobol-parser", *argv]):
        main()


_TAGS = ("SAPR24", "28486 ", "GART  ", "JSINT ")

_BODY = [
    "IDENTIFICATION DIVISION.",
    "PROGRAM-ID. HYTEST.",
    "DATA DIVISION.",
    "WORKING-STORAGE SECTION.",
    "01  WS-A  PIC X(10).",
    "PROCEDURE DIVISION.",
    "MAIN-PARA.",
    "    MOVE SPACES TO WS-A.",
    "    STOP RUN.",
]


def _write(tmp_path, name, seq_areas):
    text = "\n".join(
        f"{seq_areas[i % len(seq_areas)]:<6} {line}" for i, line in enumerate(_BODY)
    )
    path = tmp_path / name
    path.write_text(text + "\n", encoding="utf-8")
    return str(path)


def _run(capsys, *argv):
    """Run the CLI and return its JSON document.

    ``parse`` exits 2 when the source had errors, which several cases here
    deliberately provoke; the JSON is still written to stdout first, so the
    exit is swallowed and the document returned either way.
    """
    try:
        _run_main(list(argv))
    except SystemExit as exc:
        assert exc.code in (0, 2, None), exc.code
    return json.loads(capsys.readouterr().out)


@pytest.fixture
def tagged(tmp_path):
    return _write(tmp_path, "tagged.cbl", _TAGS)


class TestParseSubcommand:
    @pytest.mark.parametrize("extra", ([], ["--source-format=auto"]))
    def test_tagged_source_parses_by_default(self, capsys, tagged, extra):
        out = _run(capsys, "parse", tagged, "--errors", "--compact", *extra)
        assert out["errors"] == []
        assert out["program_id"] == "HYTEST"

    def test_forced_fixed_parses_tagged_source(self, capsys, tagged):
        out = _run(
            capsys, "parse", tagged, "--errors", "--compact", "--source-format=fixed"
        )
        assert out["errors"] == []
        assert out["program_id"] == "HYTEST"

    def test_forced_free_form_does_not_strip_columns(self, capsys, tagged):
        """``--source-format=free`` must be honored, tags and all."""
        out = _run(
            capsys, "parse", tagged, "--errors", "--compact", "--source-format=free"
        )
        assert out["errors"] != []
        assert "SAPR24" in out["errors"][0]

    def test_legacy_free_form_stays_advisory(self, capsys, tmp_path, tagged):
        """``--free-form`` keeps its pre-``--source-format`` semantics.

        The old CLI passed only ``free_form=True`` and ``parse_cobol``'s
        auto-detection still normalized source it classified as fixed --
        scripts that always passed ``--free-form`` against conventional
        fixed-format members relied on that lenience, so the flag must not
        silently become a hard override (that is ``--source-format=free``'s
        job). Detection now classifies tagged members as fixed too, so both
        layouts parse cleanly under the legacy flag.
        """
        numbered = _write(
            tmp_path, "numbered.cbl", ("000100", "000200", "000300", "000400")
        )
        out = _run(capsys, "parse", numbered, "--errors", "--compact", "--free-form")
        assert out["errors"] == []
        assert out["program_id"] == "HYTEST"

        out = _run(capsys, "parse", tagged, "--errors", "--compact", "--free-form")
        assert out["errors"] == []
        assert out["program_id"] == "HYTEST"

    def test_forced_fixed_overrides_a_declining_detector(self, capsys, tmp_path):
        """A sequence area with an internal space is deliberately not inferred."""
        spacey = _write(tmp_path, "spacey.cbl", ("AB 24", "CD 25", "EF 26"))

        auto = _run(capsys, "parse", spacey, "--errors", "--compact")
        assert auto["errors"] != []

        forced = _run(
            capsys, "parse", spacey, "--errors", "--compact", "--source-format=fixed"
        )
        assert forced["errors"] == []
        assert forced["program_id"] == "HYTEST"

    def test_source_format_and_free_form_are_mutually_exclusive(self, tagged):
        with pytest.raises(SystemExit):
            _run_main(["parse", tagged, "--free-form", "--source-format=fixed"])


class TestOtherSubcommands:
    def test_preprocess_honors_forced_free_form(self, capsys, tagged):
        _run_main(["preprocess", tagged, "--source-format=free"])
        assert "SAPR24" in capsys.readouterr().out

    def test_preprocess_strips_tags_by_default(self, capsys, tagged):
        _run_main(["preprocess", tagged])
        out = capsys.readouterr().out
        assert "SAPR24" not in out
        assert "IDENTIFICATION DIVISION." in out

    def test_preprocess_auto_leaves_free_form_source_alone(self, capsys, tmp_path):
        """Under ``auto`` (the default), ``preprocess`` must detect, not
        normalize unconditionally -- it used to slice the first 7 columns
        off genuine free-form input (``IDENTIFICATION DIVISION.`` came out
        as ``ICATION DIVISION.``) while ``parse`` on the same file
        correctly detected free-form."""
        path = tmp_path / "free.cbl"
        path.write_text("\n".join(_BODY) + "\n", encoding="utf-8")
        _run_main(["preprocess", str(path)])
        out = capsys.readouterr().out
        assert "IDENTIFICATION DIVISION." in out

    def test_preprocess_forced_fixed_still_normalizes_unconditionally(
        self, capsys, tmp_path
    ):
        """``--source-format=fixed`` keeps the force: columns are stripped
        even from input detection would call free-form."""
        path = tmp_path / "free.cbl"
        path.write_text("\n".join(_BODY) + "\n", encoding="utf-8")
        _run_main(["preprocess", str(path), "--source-format=fixed"])
        out = capsys.readouterr().out
        assert "IDENTIFICATION DIVISION." not in out

    def test_tokenize_forced_free_form_keeps_tag_tokens(self, capsys, tagged):
        out = _run(capsys, "tokenize", tagged, "--compact", "--source-format=free")
        assert "SAPR24" in [t["value"] for t in out["tokens"]]

    def test_tokenize_strips_tags_by_default(self, capsys, tagged):
        out = _run(capsys, "tokenize", tagged, "--compact")
        assert "SAPR24" not in [t["value"] for t in out["tokens"]]


class TestPreprocessRecordBoundaries:
    """`preprocess` split the source with ``str.splitlines()``, which also
    breaks on a form feed (a page eject inside a comment record), NEL and
    U+2028. One record became two, and the tail of a comment was emitted as
    code -- output `parse` itself, which splits on \\n/\\r\\n/\\r only, never
    sees."""

    @pytest.mark.parametrize("breaker", ["\x0c", "\x85", " "])
    def test_a_unicode_line_boundary_inside_a_comment_stays_a_comment(
        self, capsys, tmp_path, breaker
    ):
        path = tmp_path / "ff.cbl"
        path.write_text(
            "       IDENTIFICATION DIVISION.\n"
            "       PROGRAM-ID. FFTEST.\n"
            f"      *{breaker}PAGE EJECT COMMENT TEXT HERE\n"
            "       PROCEDURE DIVISION.\n"
            "       MAIN-PARA.\n"
            "           STOP RUN.\n",
            encoding="utf-8",
        )
        _run_main(["preprocess", str(path)])
        out = capsys.readouterr().out
        assert "COMMENT" not in out
        # One output line per input record: PROCEDURE DIVISION is still
        # the fourth.
        assert out.split("\n")[3] == "PROCEDURE DIVISION."


class TestPreprocessUnterminatedLiteral:
    """`preprocess` called ``normalize_fixed_format`` directly, so an
    unterminated literal at end of file -- a truncated upload -- escaped as
    a ``ValueError`` traceback (#372). It now recovers the way `parse` and
    `tokenize` do: a warning on stderr, the recovered text on stdout."""

    @pytest.fixture
    def truncated(self, tmp_path):
        literal_line = "           DISPLAY '"
        literal_line += "X" * (72 - len(literal_line))
        path = tmp_path / "trunc.cbl"
        path.write_text(
            "       IDENTIFICATION DIVISION.\n"
            "       PROGRAM-ID. TRUNC.\n"
            "       PROCEDURE DIVISION.\n"
            f"{literal_line}\n",
            encoding="utf-8",
        )
        return str(path)

    @pytest.mark.parametrize("fmt", ["auto", "fixed"])
    def test_reported_as_a_warning_not_a_traceback(self, capsys, truncated, fmt):
        _run_main(["preprocess", truncated, f"--source-format={fmt}"])
        captured = capsys.readouterr()
        assert "warning: Unterminated string literal at end of input" in (captured.err)
        assert "Traceback" not in captured.err
        lines = captured.out.split("\n")
        assert lines[2] == "PROCEDURE DIVISION."
        assert lines[3].strip().startswith("DISPLAY 'XXXX")

    def test_terminated_literal_gets_no_such_warning(self, capsys, tmp_path):
        path = tmp_path / "ok.cbl"
        path.write_text(
            "       IDENTIFICATION DIVISION.\n"
            "       PROGRAM-ID. OK.\n"
            "       PROCEDURE DIVISION.\n"
            "           DISPLAY 'XXXX'.\n",
            encoding="utf-8",
        )
        _run_main(["preprocess", str(path)])
        assert "Unterminated" not in capsys.readouterr().err
