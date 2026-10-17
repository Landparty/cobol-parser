"""#522: a non-UTF-8 (cp1252 / Latin-1) program is read, not refused or mangled.

``parse``, ``lint``, every analyzer subcommand and the MCP server used to
refuse such a program ("not valid UTF-8"), while ``batch``, ``scan`` and
``codebase-graph`` silently replaced each accented byte with U+FFFD. A
program's source is now decoded the way a copybook's always was
(``read_program_source``): the encoding detected unless named with
``--encoding``, and a lossy decode reported, never silent.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from cobolparser.analysis.codebase import CodebaseGraphBuilder
from cobolparser.batch import parse_files, parse_files_with_copybooks
from cobolparser.cli.parse import main
from cobolparser.mcp import CobolTools, Workspace
from cobolparser.preprocess import PreprocessingError
from cobolparser.preprocess.copybook_expander import read_program_source
from cobolparser.scan import ScanOptions, scan_files

SOURCE = (
    "       IDENTIFICATION DIVISION.\n"
    "       PROGRAM-ID. ENC1.\n"
    "      * Programme de facturation - révision 3\n"
    "       DATA DIVISION.\n"
    "       WORKING-STORAGE SECTION.\n"
    "       01  WS-A PIC X(5) VALUE 'CAFÉ'.\n"
    "       PROCEDURE DIVISION.\n"
    "           DISPLAY WS-A\n"
    "           STOP RUN.\n"
)


@pytest.fixture
def latin1(tmp_path: Path) -> Path:
    path = tmp_path / "ENC1.cbl"
    path.write_bytes(SOURCE.encode("cp1252"))
    return path


def _run(argv: list[str], capsys: pytest.CaptureFixture[str]) -> tuple[str, str]:
    with patch("sys.argv", ["cobol-parser", *argv]):
        try:
            main()
        except SystemExit as exc:
            assert exc.code in (0, None), capsys.readouterr().err
    captured = capsys.readouterr()
    return captured.out, captured.err


class TestSharedReader:
    def test_detected_like_a_copybook(self, latin1: Path) -> None:
        warnings: list[str] = []
        assert read_program_source(str(latin1), warnings=warnings) == SOURCE
        assert warnings == []

    def test_a_lossy_decode_is_reported(self, latin1: Path) -> None:
        warnings: list[str] = []
        text = read_program_source(str(latin1), "ascii", warnings=warnings)
        assert "CAF�" in text
        (warning,) = warnings
        assert "Lossy decode" in warning and "--encoding" in warning

    def test_an_unknown_encoding_is_an_error_not_ascii(self, latin1: Path) -> None:
        with pytest.raises(PreprocessingError, match="unknown encoding"):
            read_program_source(str(latin1), "no-such-codec")


class TestCli:
    def test_parse_reads_the_program(
        self, latin1: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        out, err = _run(["parse", str(latin1), "--compact"], capsys)
        assert "CAFÉ" in json.dumps(json.loads(out), ensure_ascii=False)
        assert "warning" not in err

    def test_encoding_can_be_named(
        self, latin1: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        out, _ = _run(
            ["parse", str(latin1), "--compact", "--encoding", "latin-1"], capsys
        )
        assert "CAFÉ" in json.dumps(json.loads(out), ensure_ascii=False)

    def test_a_wrong_encoding_warns(
        self, latin1: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _, err = _run(
            ["parse", str(latin1), "--compact", "--encoding", "ascii"], capsys
        )
        assert "warning: Lossy decode" in err

    def test_lint_and_analyzers_no_longer_refuse_it(
        self, latin1: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        out, _ = _run(["lint", str(latin1)], capsys)
        assert json.loads(out)
        out, _ = _run(["dead-code", str(latin1)], capsys)
        assert json.loads(out)["program_id"] == "ENC1"


class TestBatchScanGraph:
    def test_batch_decodes_instead_of_mangling(self, latin1: Path) -> None:
        for (result,) in (
            parse_files([latin1], workers=1),
            parse_files_with_copybooks([latin1], copybook_paths=[], workers=1),
        ):
            assert result.result is not None and result.result.ast is not None
            dumped = json.dumps(result.result.ast.to_dict(), ensure_ascii=False)
            assert "CAFÉ" in dumped
            assert "�" not in dumped

    def test_batch_lossy_decode_is_a_warning(self, latin1: Path) -> None:
        (result,) = parse_files([latin1], encoding="ascii", workers=1)
        assert result.result is not None
        assert any("Lossy decode" in str(w) for w in result.result.warnings)

    def test_scan_records_lossy_decodes(self, latin1: Path) -> None:
        clean = scan_files([latin1], ScanOptions(analyzers=("health",)), workers=1)
        assert clean.files[0].decode_warnings == []
        assert "decode_warnings" not in clean.files[0].to_dict()
        lossy = scan_files(
            [latin1], ScanOptions(analyzers=("health",), encoding="ascii"), workers=1
        )
        assert lossy.files[0].to_dict()["decode_warnings"]

    def test_codebase_graph_notes_a_lossy_decode(self, latin1: Path) -> None:
        graph = CodebaseGraphBuilder().build([str(latin1)])
        assert [p.program_id for p in graph.programs] == ["ENC1"]
        assert not any("Lossy decode" in n for n in graph.unresolved)
        lossy = CodebaseGraphBuilder(encoding="ascii").build([str(latin1)])
        assert any("Lossy decode" in n for n in lossy.unresolved)


class TestMcp:
    def test_the_program_is_parsed_and_its_lines_match(self, latin1: Path) -> None:
        tools = CobolTools(Workspace(latin1.parent))
        assert tools.workspace.program("ENC1.cbl").ast is not None
        lines = tools.read_source("ENC1.cbl", line=6, before=0, after=0)
        assert "CAFÉ" in lines["answer"]["lines"][0]["text"]
