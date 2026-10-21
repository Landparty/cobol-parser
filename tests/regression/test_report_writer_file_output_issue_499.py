"""Regression tests for issue #499: Report Writer output reaches the I/O analyzers.

A report file (``FD f REPORT IS r``) has no record description and is written
only by INITIATE / GENERATE / TERMINATE, which no file-I/O analyzer handled:
the CRUD matrix showed ``----``, IOLogger logged only OPEN/CLOSE, the boundary
inventory had no OUT boundary, field lineage had no port, and io-sequence let
a GENERATE on an unopened report file pass.
"""

from pathlib import Path

from cobolparser import (
    CRUDMatrixGenerator,
    IOLogger,
    IOSequenceAnalyzer,
    parse_cobol,
)
from cobolparser.analysis.boundary_inventory import BoundaryInventoryAnalyzer
from cobolparser.analysis.field_lineage import FieldFlowAnalyzer
from cobolparser.generators import ProgramLayoutIndex

_SAMPLE = Path(__file__).parent.parent / "samples" / "enterprise" / "RPTWRTR.cbl"

_RW = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. RW1.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT RPT-FILE ASSIGN TO RPTF.
       DATA DIVISION.
       FILE SECTION.
       FD RPT-FILE REPORT IS SALES-RPT.
       WORKING-STORAGE SECTION.
       01 WS-AMT PIC 9(5)V99 VALUE 10.
       01 WS-REGION PIC X(4) VALUE 'EAST'.
       REPORT SECTION.
       RD SALES-RPT CONTROLS ARE WS-REGION PAGE LIMIT 60 LINES.
       01 DET-LINE TYPE IS DETAIL.
          05 LINE PLUS 1.
             10 COLUMN 1 PIC X(4) SOURCE WS-REGION.
             10 COLUMN 10 PIC ZZ,ZZ9.99 SOURCE WS-AMT.
       PROCEDURE DIVISION.
           OPEN OUTPUT RPT-FILE
           INITIATE SALES-RPT
           GENERATE DET-LINE
           TERMINATE SALES-RPT
           CLOSE RPT-FILE
           GOBACK.
"""


def _ast(source: str = _RW):
    result = parse_cobol(source)
    assert result.errors == []
    return result.ast


def test_fd_report_is_is_kept_in_the_ast():
    file_section = _ast().get_division("DATA")._sections["FILE"]
    assert file_section.get_metadata("report_files") == {"SALES-RPT": "RPT-FILE"}


def test_crud_marks_the_report_file_created():
    matrix = CRUDMatrixGenerator().analyze(_ast())
    assert {e.file_name: e.crud.as_string() for e in matrix.file_entries} == {
        "RPT-FILE": "C---"
    }


def test_crud_on_the_enterprise_sample():
    matrix = CRUDMatrixGenerator().analyze(_ast(_SAMPLE.read_text()))
    crud = {e.file_name: e.crud.as_string() for e in matrix.file_entries}
    assert crud["REPORT-FILE"] == "C---"


def test_iologger_logs_each_verb_as_a_write():
    ops = [
        (o.operation, o.target, o.details.get("verb"))
        for o in IOLogger().analyze(_ast()).operations
        if o.category == "FILE-IO"
    ]
    assert ("WRITE", "RPT-FILE", "INITIATE") in ops
    assert ("WRITE", "RPT-FILE", "GENERATE") in ops
    assert ("WRITE", "RPT-FILE", "TERMINATE") in ops


def test_io_sequence_flags_report_verbs_on_an_unopened_file():
    source = _RW.replace("           OPEN OUTPUT RPT-FILE\n", "").replace(
        "           CLOSE RPT-FILE\n", ""
    )
    violations = IOSequenceAnalyzer().analyze(_ast(source)).violations
    assert [(v.kind.name, v.file_name) for v in violations] == [
        ("WRITE_BEFORE_OPEN", "RPT-FILE")
    ] * 3
    assert IOSequenceAnalyzer().analyze(_ast()).violations == []


def test_generate_is_an_out_boundary():
    ast = _ast()
    report = BoundaryInventoryAnalyzer().analyze(ast, ProgramLayoutIndex.build(ast))
    outs = [
        (b.ref.category, b.ref.key) for b in report.boundaries if b.direction == "OUT"
    ]
    assert outs == [("WRITE", "DET-LINE")]


def test_lineage_carries_source_operands_to_the_report_file():
    report = FieldFlowAnalyzer().analyze(_ast())
    assert report.port("file", "RPTF") is not None
    flows = {
        (e.source.label(), e.target.label())
        for e in report.edges
        if e.statement == "GENERATE"
    }
    assert flows == {("WS-AMT", "file:RPTF"), ("WS-REGION", "file:RPTF")}


def test_lineage_sample_input_reaches_the_report():
    report = FieldFlowAnalyzer().analyze(_ast(_SAMPLE.read_text()))
    sources = {
        e.source.label()
        for e in report.edges
        if e.statement in ("GENERATE", "TERMINATE")
    }
    assert "SALES-REC.SR-AMOUNT" in sources
