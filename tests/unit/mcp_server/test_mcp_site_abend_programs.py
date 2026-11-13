"""Issue #900: the MCP workspace applies ``cobol.yml``'s
``project.abend_programs`` as the CLI does, so a static CALL of a site abend
routine ends the paragraph for ``lint`` (and every other tool) too."""

from __future__ import annotations

import threading
from pathlib import Path

from cobolparser.analysis import (
    set_site_abend_programs,
    site_abend_programs,
    using_site_abend_programs,
)
from cobolparser.mcp import CobolTools, Workspace
from cobolparser.mcp.facts import FactsStore

SOURCE = """\
IDENTIFICATION DIVISION.
PROGRAM-ID. S.
DATA DIVISION.
WORKING-STORAGE SECTION.
01 WS-A PIC 9 VALUE 0.
PROCEDURE DIVISION.
MAIN-PARA.
    PERFORM P1
    CALL 'MYABEND'.
P1.
    MOVE 1 TO WS-A.
ABEND-PARA.
    CALL 'CEE3ABD'.
"""


def _workspace(tmp_path: Path, config: str | None) -> Workspace:
    (tmp_path / "S.cbl").write_text(SOURCE)
    if config is not None:
        (tmp_path / "cobol.yml").write_text(config)
    return Workspace(tmp_path)


def _perform_range(tools: CobolTools) -> list[dict]:
    findings = tools.lint("S.cbl")["answer"]["findings"]
    return [f for f in findings if f["rule"] == "perform-range"]


def test_lint_honours_abend_programs(tmp_path):
    ws = _workspace(tmp_path, "project:\n  abend_programs: [MYABEND]\n")
    assert _perform_range(CobolTools(ws)) == []
    # Nothing leaks out of the tool call into the process.
    assert site_abend_programs() == frozenset()


def test_without_the_setting_the_fall_through_is_reported(tmp_path):
    ws = _workspace(tmp_path, None)
    assert len(_perform_range(CobolTools(ws))) == 1


def test_a_cobol_yml_edit_is_followed(tmp_path):
    ws = _workspace(tmp_path, None)
    tools = CobolTools(ws)
    assert len(_perform_range(tools)) == 1
    config = tmp_path / "cobol.yml"
    config.write_text("project:\n  abend_programs: [MYABEND]\n")
    assert _perform_range(tools) == []


def test_facts_key_follows_abend_programs(tmp_path):
    ws = _workspace(tmp_path, None)
    before = FactsStore(ws)._config_key()
    (tmp_path / "cobol.yml").write_text("project:\n  abend_programs: [MYABEND]\n")
    assert FactsStore(ws)._config_key() != before


def test_scoped_list_is_per_thread():
    seen: list[frozenset[str]] = []
    try:
        set_site_abend_programs(["GLOBAL"])
        with using_site_abend_programs(["MINE"]):
            thread = threading.Thread(target=lambda: seen.append(site_abend_programs()))
            thread.start()
            thread.join()
            assert site_abend_programs() == {"MINE"}
        assert site_abend_programs() == {"GLOBAL"}
    finally:
        set_site_abend_programs(None)
    assert seen == [frozenset({"GLOBAL"})]
