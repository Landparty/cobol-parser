"""Gaps AWS CardDemo exposed when the MCP server was benchmarked on it.

CardDemo (aws-samples/aws-mainframe-modernization-carddemo) is a credit-card
application written to look like a real mainframe shop. Running the tools
over it found three things a synthetic corpus had not:

- ``ADD 8 TO ZERO GIVING APPL-RESULT`` -- a literal TO operand in the GIVING
  format, valid IBM COBOL and used by every CardDemo batch program's file
  status routine -- failed to parse, so six programs only parsed in part.
- ``cobol.yml`` had no way to name a folder of cataloged JCL PROCs, so the
  MCP server could not expand ``EXEC PROC=REPROC`` and every flow through
  those jobs stopped there.
- An IDCAMS step whose commands come from a dataset (``SYSIN DD
  DSN=...CNTL(REPROCT)``) dropped the flow without saying so.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from cobolparser import CobolParser, ErrorRecoveryMode
from cobolparser.analysis.lineage_jcl import bindings_from_jobs, load_jobs
from cobolparser.analysis.xref import XrefAnalyzer
from cobolparser.config.project import ProjectConfig, load_project_config
from cobolparser.mcp import CobolTools, Workspace
from cobolparser.models.statements import AddStatement, SubtractStatement

LINEAGE = Path(__file__).resolve().parents[1] / "samples" / "lineage"


def _parse(body: str):
    source = (
        "       IDENTIFICATION DIVISION.\n"
        "       PROGRAM-ID. T.\n"
        "       DATA DIVISION.\n"
        "       WORKING-STORAGE SECTION.\n"
        "       01 R PIC S9(4).\n"
        "       PROCEDURE DIVISION.\n" + body + "           STOP RUN.\n"
    )
    return CobolParser(error_recovery=ErrorRecoveryMode.COLLECT_ALL).parse(source)


# -- ADD ... TO <literal> GIVING ------------------------------------------------


@pytest.mark.parametrize(
    "statement, operand",
    [
        ("ADD 8 TO ZERO GIVING R.", "ZERO"),
        ("ADD 12 TO ZERO\n               GIVING R", "ZERO"),
        ("ADD 1 TO 2 GIVING R ROUNDED", "2"),
        ("ADD R TO -5 GIVING R", "-5"),
    ],
)
def test_add_to_a_literal_in_the_giving_format(statement: str, operand: str) -> None:
    result = _parse(f"           {statement}\n")
    assert result.errors == []
    (add,) = result.ast.find_all_by_type("AddStatement")
    assert isinstance(add, AddStatement)
    assert add.target == operand
    assert add.giving == "R"


def test_the_literal_operand_is_read_and_only_the_giving_item_written() -> None:
    result = _parse("           ADD 8 TO ZERO GIVING R.\n")
    roles = {
        ref.role
        for entry in XrefAnalyzer().analyze(result.ast).entries
        if entry.name == "R"
        for ref in entry.references
    }
    assert roles == {"write"}


def test_a_literal_is_still_no_receiver_without_giving() -> None:
    result = _parse("           ADD 8 TO ZERO.\n")
    assert len(result.errors) == 1
    assert "ADD ... TO requires a target identifier" in str(result.errors[0])


def test_subtract_from_a_literal_still_parses() -> None:
    result = _parse("           SUBTRACT 1 FROM -100 GIVING R.\n")
    assert result.errors == []
    (sub,) = result.ast.find_all_by_type("SubtractStatement")
    assert isinstance(sub, SubtractStatement)
    assert sub.target == "-100"


# -- project.proc_path -----------------------------------------------------------


def test_proc_path_resolves_against_the_config_file(tmp_path: Path) -> None:
    (tmp_path / "proc").mkdir()
    (tmp_path / "cobol.yml").write_text("project:\n  proc_path: [proc, gone]\n")
    config = load_project_config(tmp_path)
    assert config.proc_path == (str(tmp_path / "proc"), str(tmp_path / "gone"))
    assert config.missing_directories() == [
        ("project.proc_path", str(tmp_path / "gone"))
    ]


def _proc_job(root: Path) -> None:
    """FEEJOB with its READER step moved into a cataloged PROC."""
    (root / "FEEJOB.jcl").write_text(
        (LINEAGE / "FEEJOB.jcl")
        .read_text()
        .replace(
            "//STEP030  EXEC PGM=READER\n"
            "//FEEIN    DD  DSN=PROD.FEE.SUMMARY(+1),DISP=SHR\n"
            "//MASTER   DD  DSN=PROD.ACCT.MASTER,DISP=SHR\n",
            "//STEP030  EXEC READPROC\n",
        )
    )
    (root / "proc").mkdir()
    (root / "proc" / "READPROC.prc").write_text(
        "//READPROC PROC\n"
        "//RUN      EXEC PGM=READER\n"
        "//FEEIN    DD  DSN=PROD.FEE.SUMMARY(+1),DISP=SHR\n"
        "//MASTER   DD  DSN=PROD.ACCT.MASTER,DISP=SHR\n"
    )


def test_load_jobs_searches_several_proc_folders_in_order(tmp_path: Path) -> None:
    pytest.importorskip("jclparser")
    _proc_job(tmp_path)
    first = tmp_path / "first"
    first.mkdir()
    (first / "READPROC.prc").write_text(
        "//READPROC PROC\n//RUN      EXEC PGM=OVERRIDE\n"
        "//FEEIN    DD  DSN=PROD.OTHER,DISP=SHR\n"
    )
    jobs, problems = load_jobs(
        [tmp_path / "FEEJOB.jcl"], proc_path=[first, tmp_path / "proc"]
    )
    assert problems == []
    bindings, _ = bindings_from_jobs(jobs)
    assert ("OVERRIDE", "FEEIN", "PROD.OTHER") in {
        (b.program, b.ddname, b.dataset) for b in bindings
    }


def test_the_mcp_server_expands_procs_from_proc_path(tmp_path: Path) -> None:
    pytest.importorskip("jclparser")
    root = tmp_path / "lineage"
    shutil.copytree(LINEAGE, root)
    _proc_job(root)

    without = CobolTools(Workspace(root, ProjectConfig())).impact_of_change(
        "WS-FEE", "WRITER.cbl"
    )
    assert "READER" not in without["answer"]["programs"]
    details = " ".join(c["detail"] for c in without["caveats"])
    assert "project.proc_path" in details

    tools = CobolTools(Workspace(root, ProjectConfig(proc_path=(str(root / "proc"),))))
    answer = tools.impact_of_change("WS-FEE", "WRITER.cbl")["answer"]
    assert "READER" in answer["programs"]


def test_a_proc_folder_outside_the_root_is_not_read(tmp_path: Path) -> None:
    pytest.importorskip("jclparser")
    root = tmp_path / "lineage"
    shutil.copytree(LINEAGE, root)
    _proc_job(root)
    outside = tmp_path / "outside"
    shutil.move(str(root / "proc"), outside)
    result = CobolTools(
        Workspace(root, ProjectConfig(proc_path=(str(outside),)))
    ).impact_of_change("WS-FEE", "WRITER.cbl")
    assert "READER" not in result["answer"]["programs"]
    details = " ".join(c["detail"] for c in result["caveats"])
    assert "outside the workspace were not searched" in details


# -- IDCAMS commands from a dataset -------------------------------------------------


def test_idcams_commands_read_from_a_dataset_are_named() -> None:
    from types import SimpleNamespace as NS

    def dd(name: str, dsn: str) -> NS:
        return NS(name=name, dataset_name=dsn, inline_data=None, parameters={})

    step = NS(
        name="PRC001",
        program="IDCAMS",
        dd_statements=[
            dd("FILEIN", "A.KSDS"),
            dd("FILEOUT", "A.BKUP"),
            dd("SYSIN", "A.CNTL(REPROCT)"),
        ],
    )
    job = NS(name="TRANBKP", steps=[step])
    notes: list[str] = []
    _, passthroughs = bindings_from_jobs([job], notes)
    assert passthroughs == []
    assert any("A.CNTL(REPROCT)" in note and "not traced" in note for note in notes)
