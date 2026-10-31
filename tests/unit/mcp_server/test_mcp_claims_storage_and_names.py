"""``check_claims`` judges ``flows_to`` by whole names (#776) and
``writes_field`` / ``sets_only_in`` by storage, not only by the name a
statement spells (#778): the records of one FD / SD share storage, and a
READ / RETURN fills them (#788)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from cobolparser.mcp import CobolTools, Workspace

FLOW = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. FLOW.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-SRC          PIC X(10).
       01  WS-OTHER        PIC X(10).
       01  WS-CUSTOMER-ID  PIC X(10).
       01  CUSTOMER-ID     PIC X(10).
       PROCEDURE DIVISION.
       MAIN-PARA.
           MOVE WS-SRC TO WS-CUSTOMER-ID
           MOVE WS-OTHER TO CUSTOMER-ID
           GOBACK.
"""

WRT = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. WRT.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT OUT-FILE ASSIGN TO OUTDD.
       DATA DIVISION.
       FILE SECTION.
       FD  OUT-FILE.
       01  OUT-REC         PIC X(10).
       WORKING-STORAGE SECTION.
       01  WS-AMT          PIC X(10).
       PROCEDURE DIVISION.
       MAIN-PARA.
           OPEN OUTPUT OUT-FILE
           MOVE WS-AMT TO OUT-REC
           WRITE OUT-REC
           CLOSE OUT-FILE
           GOBACK.
"""

JOB = """\
//J        JOB (ACCT),'X'
//S1       EXEC PGM=WRT
//OUTDD    DD DSN=BANK.CUST.HIST,DISP=(NEW,CATLG)
"""

SO = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. SO.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  GRP.
           05  CHILD        PIC 9(5).
           05  OTHER-F      PIC X(5).
       01  GRP2 REDEFINES GRP PIC X(10).
       01  HALF REDEFINES GRP.
           05  HALF-A       PIC X(3).
           05  HALF-B       PIC X(7).
       01  SRC              PIC X(10).
       PROCEDURE DIVISION.
       P-MAIN.  PERFORM P-SET  PERFORM P-GROUP  PERFORM P-INIT
                PERFORM P-REDEF  PERFORM P-ACCEPT  PERFORM P-PART
                PERFORM P-REPL  GOBACK.
       P-SET.    MOVE 1 TO CHILD.
       P-GROUP.  MOVE SRC TO GRP.
       P-INIT.   INITIALIZE GRP.
       P-REDEF.  MOVE SRC TO GRP2.
       P-ACCEPT. ACCEPT CHILD FROM DATE.
       P-PART.   MOVE 'ABC' TO HALF-A.
       P-REPL.   INITIALIZE GRP REPLACING ALPHANUMERIC BY SPACES.
"""

FDR = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. FDR.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT IN-FILE ASSIGN TO INFILE.
           SELECT OUT-FILE ASSIGN TO OUTDD.
           SELECT SRT-FILE ASSIGN TO SORTWK.
       DATA DIVISION.
       FILE SECTION.
       FD  IN-FILE.
       01  REC-A.
           05  A-FLD        PIC X(5).
           05  A-REST       PIC X(5).
       01  REC-B            PIC X(10).
       01  REC-S            PIC X(3).
       FD  OUT-FILE.
       01  OUT-REC          PIC X(10).
       SD  SRT-FILE.
       01  SRT-REC.
           05  S-KEY        PIC X(4).
           05  S-REST       PIC X(6).
       WORKING-STORAGE SECTION.
       01  SRC              PIC X(10).
       PROCEDURE DIVISION.
       P-MAIN.  PERFORM P-X PERFORM P-Y PERFORM P-Z PERFORM P-S
                PERFORM P-W GOBACK.
       P-X.  MOVE 'X' TO A-FLD.
       P-Y.  MOVE SRC TO REC-B.
       P-Z.  OPEN INPUT IN-FILE  READ IN-FILE  CLOSE IN-FILE.
       P-S.  MOVE 'AB' TO REC-S.
       P-W.  OPEN OUTPUT OUT-FILE  WRITE OUT-REC FROM SRC
             CLOSE OUT-FILE.
       P-SORT SECTION.
       P-IN.   RELEASE SRT-REC FROM SRC.
       P-OUT.  RETURN SRT-FILE AT END CONTINUE END-RETURN.
"""


@pytest.fixture(scope="module")
def tools(tmp_path_factory: pytest.TempPathFactory) -> CobolTools:
    root: Path = tmp_path_factory.mktemp("claims776")
    (root / "FLOW.cbl").write_text(FLOW)
    (root / "WRT.cbl").write_text(WRT)
    (root / "J.jcl").write_text(JOB)
    (root / "SO.cbl").write_text(SO)
    (root / "FDR.cbl").write_text(FDR)
    return CobolTools(Workspace(root))


def verdict(tools: CobolTools, **claim: Any) -> dict[str, Any]:
    (result,) = tools.check_claims([claim])["answer"]["results"]
    return result


class TestFlowsToWholeNames:
    def test_target_inside_a_reached_field_name_is_not_reached(
        self, tools: CobolTools
    ) -> None:
        for target in ("CUSTOMER-ID", "ID"):
            result = verdict(
                tools, kind="flows_to", subject="WS-SRC", object=target, file="FLOW.cbl"
            )
            assert result["verdict"] == "contradicted", target
        good = verdict(
            tools,
            kind="flows_to",
            subject="WS-SRC",
            object="WS-CUSTOMER-ID",
            file="FLOW.cbl",
        )
        assert good["verdict"] == "confirmed"

    def test_dataset_prefix_is_not_the_dataset(self, tools: CobolTools) -> None:
        pytest.importorskip("jclparser")
        claim = {"kind": "flows_to", "subject": "WS-AMT", "file": "WRT.cbl"}
        assert verdict(tools, object="BANK.CUST", **claim)["verdict"] == (
            "contradicted"
        )
        assert verdict(tools, object="BANK.CUST.HIST", **claim)["verdict"] == (
            "confirmed"
        )


class TestWritesThroughStorage:
    @pytest.mark.parametrize("paragraph", ["P-GROUP", "P-INIT", "P-REDEF"])
    def test_group_initialize_and_redefines_write_the_field(
        self, tools: CobolTools, paragraph: str
    ) -> None:
        result = verdict(
            tools, kind="writes_field", subject=paragraph, object="CHILD", file="SO.cbl"
        )
        assert result["verdict"] == "confirmed"
        assert "through" in result["why"]

    def test_partial_overlap_and_replacing_are_not_settled(
        self, tools: CobolTools
    ) -> None:
        for paragraph in ("P-PART", "P-REPL"):
            result = verdict(
                tools,
                kind="writes_field",
                subject=paragraph,
                object="CHILD",
                file="SO.cbl",
            )
            assert result["verdict"] == "not_checkable", paragraph

    def test_sets_only_in_sees_the_group_writes(self, tools: CobolTools) -> None:
        claim = {"kind": "sets_only_in", "object": "CHILD", "file": "SO.cbl"}
        wrong = verdict(tools, subject="P-SET,P-ACCEPT", **claim)
        assert wrong["verdict"] == "contradicted"
        assert "P-GROUP (through GRP)" in wrong["why"]
        assert "P-REDEF (through GRP2)" in wrong["why"]
        maybe = verdict(tools, subject="P-SET,P-ACCEPT,P-GROUP,P-INIT,P-REDEF", **claim)
        assert maybe["verdict"] == "not_checkable"
        right = verdict(
            tools,
            subject="P-SET,P-ACCEPT,P-GROUP,P-INIT,P-REDEF,P-PART,P-REPL",
            **claim,
        )
        assert right["verdict"] == "confirmed"


class TestFileRecordWrites:
    """#788: the 01 records of one FD / SD are one storage area, and a
    READ / RETURN of the file fills it."""

    def test_sibling_record_write_is_a_write_of_the_field(
        self, tools: CobolTools
    ) -> None:
        claim = {"kind": "writes_field", "object": "A-FLD", "file": "FDR.cbl"}
        result = verdict(tools, subject="P-Y", **claim)
        assert result["verdict"] == "confirmed"
        assert "through REC-B" in result["why"]
        # A shorter sibling covers only part of A-FLD's bytes.
        assert verdict(tools, subject="P-S", **claim)["verdict"] == "not_checkable"

    def test_read_without_into_may_write_the_record(self, tools: CobolTools) -> None:
        for name in ("A-FLD", "REC-A", "REC-B"):
            result = verdict(
                tools, kind="writes_field", object=name, subject="P-Z", file="FDR.cbl"
            )
            assert result["verdict"] == "not_checkable", name
            assert "record area of IN-FILE" in result["why"], name

    def test_sets_only_in_no_longer_confirms_a_false_claim(
        self, tools: CobolTools
    ) -> None:
        claim = {"kind": "sets_only_in", "object": "A-FLD", "file": "FDR.cbl"}
        wrong = verdict(tools, subject="P-X", **claim)
        assert wrong["verdict"] == "contradicted"
        assert "P-Y (through REC-B)" in wrong["why"]
        maybe = verdict(tools, subject="P-X,P-Y", **claim)
        assert maybe["verdict"] == "not_checkable"
        assert "record area of IN-FILE" in maybe["why"]
        right = verdict(tools, subject="P-X,P-Y,P-Z,P-S", **claim)
        assert right["verdict"] == "confirmed"

    def test_other_files_records_are_not_aliases(self, tools: CobolTools) -> None:
        result = verdict(
            tools, kind="sets_only_in", object="OUT-REC", subject="P-W", file="FDR.cbl"
        )
        assert result["verdict"] == "confirmed"

    def test_write_and_release_from_write_the_record(self, tools: CobolTools) -> None:
        out = verdict(
            tools, kind="writes_field", object="OUT-REC", subject="P-W", file="FDR.cbl"
        )
        assert out["verdict"] == "confirmed"
        key = verdict(
            tools, kind="writes_field", object="S-KEY", subject="P-IN", file="FDR.cbl"
        )
        assert key["verdict"] == "confirmed"
        assert "through SRT-REC" in key["why"]

    def test_return_may_write_the_sort_record(self, tools: CobolTools) -> None:
        result = verdict(
            tools, kind="writes_field", object="S-KEY", subject="P-OUT", file="FDR.cbl"
        )
        assert result["verdict"] == "not_checkable"
        assert "record area of SRT-FILE" in result["why"]
