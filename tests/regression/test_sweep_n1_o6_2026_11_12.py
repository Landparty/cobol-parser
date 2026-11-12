"""Regression tests from Samuel's 2026-11-12 sweep table ("Still open or
new", N1-N4 and O1-O6), reproduced on small fixtures because the real files
are private:

* N1 -- standalone ``call-check`` cited the line of the copybook-expanded
  text, not the line on disk (``lint --callee-path`` was right);
* N2 -- a short argument passed to a ``PIC X(32767)`` maximum-size buffer was
  a length error;
* N3 -- gen-data gave an ODO counter declared in another 01 any value its
  PICTURE holds (640 against a table of at most 15);
* N4 -- a procedure-code copybook whose blank lines carry only a
  sequence-area tag was read as free-form, so gen-data wrote 0-byte records
  instead of refusing it;
* O1 -- io-sequence did not fork AT END / INVALID KEY, so ``READ ... AT END
  CLOSE f GOBACK END-READ`` then ``CLOSE f`` was a duplicate CLOSE;
* O2 -- every GO TO loop with a way out was a lint ``recursion-check`` info;
* O3 -- comment-only lines past column 80 were ``line-length`` warnings;
* O4 -- a LINKAGE item used only in ``PROCEDURE DIVISION USING`` was "never
  referenced in the PROCEDURE DIVISION";
* O5 -- the MCP answer budget never trimmed the caveats or its own record of
  cuts, so a small budget was missed by twice its size;
* O6 -- a FILE STATUS guard after OPEN (``IF NOT FS-OK GOBACK``) left every
  branch scenario below it "could not be verified".
"""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

from cobolparser import parse_cobol
from cobolparser.analysis.call_interface import CallInterfaceChecker
from cobolparser.analysis.io_sequence import IOSequenceAnalyzer, IOViolationKind
from cobolparser.analysis.lint import LintAnalyzer, line_length_findings
from cobolparser.analysis.sarif import call_check_results
from cobolparser.generators import CopybookDataGenerator, DataGeneratorOptions
from cobolparser.generators.program_fixtures import ProgramFixtureGenerator
from cobolparser.layout.copybook import procedure_code_start
from cobolparser.layout.errors import CopybookLayoutError
from cobolparser.mcp.envelope import fit_budget, wire_size

CALLEE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. CALLEE.
       DATA DIVISION.
       LINKAGE SECTION.
       01  LK-BUF PIC X(20).
       PROCEDURE DIVISION USING LK-BUF.
           MOVE SPACES TO LK-BUF
           GOBACK.
"""

CALLER = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. CALLER.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       COPY BIGCPY.
       01  SHORT-BUF PIC X(5).
       PROCEDURE DIVISION.
           CALL 'CALLEE' USING SHORT-BUF
           GOBACK.
"""

BIGCPY = "       01  BIG-AREA.\n" + "".join(
    f"           05  B{n:<3d} PIC X(10).\n" for n in range(1, 11)
)


class TestN1CallCheckLinesOnDisk:
    def _report(self, tmp_path: Path, caller: str = CALLER) -> Any:
        (tmp_path / "cpy").mkdir()
        (tmp_path / "cpy" / "BIGCPY.cpy").write_text(BIGCPY)
        (tmp_path / "CALLER.cbl").write_text(caller)
        (tmp_path / "CALLEE.cbl").write_text(CALLEE)
        return CallInterfaceChecker(copybook_paths=[str(tmp_path / "cpy")]).check_files(
            [str(tmp_path / "CALLER.cbl"), str(tmp_path / "CALLEE.cbl")]
        )

    def test_the_call_line_is_the_line_in_the_file(self, tmp_path: Path) -> None:
        [finding] = self._report(tmp_path).findings
        assert finding.line == 8  # 18 in the expanded text
        assert finding.origin_file is None
        assert "origin_file" not in finding.to_dict()

    def test_text_and_sarif_agree(self, tmp_path: Path) -> None:
        report = self._report(tmp_path)
        assert "CALLER.cbl:8: error" in report.to_text()
        [result] = call_check_results(report)
        assert result.line == 8

    def test_a_call_inside_a_copybook_names_the_copybook(self, tmp_path: Path) -> None:
        (tmp_path / "cpy").mkdir()
        (tmp_path / "cpy" / "BIGCPY.cpy").write_text(BIGCPY)
        (tmp_path / "cpy" / "CALLIT.cpy").write_text(
            "      * shared call\n           CALL 'CALLEE' USING SHORT-BUF\n"
        )
        caller = CALLER.replace(
            "           CALL 'CALLEE' USING SHORT-BUF\n", "           COPY CALLIT.\n"
        )
        (tmp_path / "CALLER.cbl").write_text(caller)
        (tmp_path / "CALLEE.cbl").write_text(CALLEE)
        report = CallInterfaceChecker(
            copybook_paths=[str(tmp_path / "cpy")]
        ).check_files([str(tmp_path / "CALLER.cbl"), str(tmp_path / "CALLEE.cbl")])
        [finding] = report.findings
        assert finding.origin_file is not None
        assert Path(finding.origin_file).name == "CALLIT.cpy"
        assert finding.line == 2
        assert finding.path.endswith("CALLER.cbl")
        assert "CALLIT.cpy:2: error" in report.to_text()


class TestN2MaximumSizeBuffer:
    def test_a_short_argument_to_x_32767_is_info(self, tmp_path: Path) -> None:
        (tmp_path / "CALLER.cbl").write_text(
            CALLER.replace("       COPY BIGCPY.\n", "").replace("CALLEE", "CSDOSS")
        )
        (tmp_path / "CSDOSS.cbl").write_text(
            CALLEE.replace("CALLEE", "CSDOSS").replace("X(20)", "X(32767)")
        )
        report = CallInterfaceChecker().check_files(
            [str(tmp_path / "CALLER.cbl"), str(tmp_path / "CSDOSS.cbl")]
        )
        [finding] = report.findings
        assert finding.kind == "length"
        assert finding.severity == "info"
        assert "maximum-size buffer" in finding.message

    def test_a_short_argument_to_an_ordinary_area_is_still_an_error(
        self, tmp_path: Path
    ) -> None:
        (tmp_path / "CALLER.cbl").write_text(
            CALLER.replace("       COPY BIGCPY.\n", "")
        )
        (tmp_path / "CALLEE.cbl").write_text(CALLEE)
        report = CallInterfaceChecker().check_files(
            [str(tmp_path / "CALLER.cbl"), str(tmp_path / "CALLEE.cbl")]
        )
        assert [f.severity for f in report.findings] == ["error"]


class TestN3OdoCounterInAnotherRecord:
    COPYBOOK = """\
       01  PDS-REC.
           05  PDS-KEY      PIC X(4).
           05  PDS-CNT      PIC S9(4) COMP.
           05  PDS-FILL     PIC X(2).
       01  PDS-REC2.
           05  PDS-TAB OCCURS 0 TO 15 TIMES DEPENDING ON PDS-CNT.
               10  PDS-ITEM PIC X(5).
"""

    def test_the_counter_stays_within_the_table(self) -> None:
        dataset = CopybookDataGenerator(
            DataGeneratorOptions(rows=60, seed=1)
        ).generate_from_source(self.COPYBOOK, filename="PDS.cpy")
        column = [f.column for f in dataset.fields].index("PDS-CNT")
        counts = [int(row[column]) for row in dataset.rows]
        assert counts and all(0 <= n <= 15 for n in counts), counts


class TestN4TagOnlyLines:
    MEMBER = (
        "P1CKBA     MOVE 8 TO RETURN-CODE.\n"
        "P1CKBA\n"
        "P1CKBA\n"
        "P1CKBA     PERFORM X.\n"
        "P1CKBA\n"
    )

    def test_detected_as_procedure_code(self) -> None:
        assert procedure_code_start(self.MEMBER) == "MOVE 8 TO RETURN-CODE."

    def test_gen_data_refuses_it(self) -> None:
        generator = CopybookDataGenerator(DataGeneratorOptions(rows=1, seed=1))
        try:
            generator.generate_from_source(self.MEMBER, filename="P1CKBADR.cpy")
        except CopybookLayoutError as exc:
            assert "PROCEDURE DIVISION code" in str(exc)
        else:
            raise AssertionError("a procedure copybook was read as a record")


FILE_PROGRAM = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. F.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT F1 ASSIGN TO F1DD FILE STATUS IS WS-FS.
       DATA DIVISION.
       FILE SECTION.
       FD  F1.
       01  F1-REC.
           05  IN-QTY  PIC S9(4).
           05  IN-CODE PIC X(2).
       WORKING-STORAGE SECTION.
       01  WS-FS PIC XX.
           88  FS-OK VALUE '00'.
       PROCEDURE DIVISION.
       MAIN-PARA.
"""


class TestO1HandlerArmsAreForked:
    def _kinds(self, body: str) -> list[IOViolationKind]:
        ast = parse_cobol(FILE_PROGRAM + body).ast
        return [v.kind for v in IOSequenceAnalyzer().analyze(ast).violations]

    def test_at_end_close_then_goback_is_no_double_close(self) -> None:
        body = """\
           OPEN INPUT F1
           READ F1
             AT END
               CLOSE F1
               GOBACK
           END-READ
           CLOSE F1
           GOBACK.
"""
        assert IOViolationKind.DOUBLE_CLOSE not in self._kinds(body)

    def test_close_in_both_arms_then_close_is_a_double_close(self) -> None:
        body = """\
           OPEN INPUT F1
           READ F1
             AT END
               CLOSE F1
             NOT AT END
               CLOSE F1
           END-READ
           CLOSE F1
           GOBACK.
"""
        assert IOViolationKind.DOUBLE_CLOSE in self._kinds(body)


class TestO2GoToLoopIsNotLinted:
    def test_a_read_loop_with_an_exit(self) -> None:
        source = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. G.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-I PIC 9(3) VALUE 0.
       PROCEDURE DIVISION.
       MAIN-PARA.
           PERFORM LOOP-PARA THRU LOOP-EXIT
           GOBACK.
       LOOP-PARA.
           ADD 1 TO WS-I
           IF WS-I > 10
              GO TO LOOP-EXIT
           END-IF
           GO TO LOOP-PARA.
       LOOP-EXIT.
           EXIT.
"""
        report = LintAnalyzer(["recursion-check"]).analyze(parse_cobol(source).ast)
        assert report.findings == []


class TestO3CommentPastColumn80:
    def test_comment_line(self) -> None:
        assert (
            line_length_findings("P.cbl", "      * a note".ljust(90, "x") + "\n") == []
        )

    def test_code_past_80_is_still_an_error(self) -> None:
        line = "           DISPLAY 'X'.".ljust(72) + "ABCDEFGHIJKL"
        [finding] = line_length_findings("P.cbl", line + "\n")
        assert finding.severity == "error"


class TestO4UsingOnlyLinkage:
    def test_reworded_and_info(self) -> None:
        source = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. K.
       DATA DIVISION.
       LINKAGE SECTION.
       01  LK-A PIC X(10).
       01  LK-B PIC X(10).
       PROCEDURE DIVISION USING LK-A LK-B.
           MOVE SPACES TO LK-A
           GOBACK.
"""
        report = LintAnalyzer(["unused-variables"]).analyze(parse_cobol(source).ast)
        [finding] = report.findings
        assert finding.symbol == "LK-B"
        assert finding.severity == "info"
        assert "received in the USING list but never used" in finding.message


class TestO5EnvelopeIsTrimmed:
    def _result(self) -> dict[str, Any]:
        return {
            "surface_version": "1",
            "answer": {
                "programs": [
                    {"program": f"PGM{n:03d}", "grade": "A"} for n in range(40)
                ],
                "copybooks": [f"MISS{n}" for n in range(20)],
            },
            "caveats": [
                {"kind": "unresolved-copybook", "message": f"MISS{n} not found " * 3}
                for n in range(12)
            ],
            "truncated": [],
            "next": ['program_brief(file="src/PGM000.cbl")'],
        }

    def test_a_small_budget_is_met(self) -> None:
        result = fit_budget(self._result(), 1500)
        assert wire_size(result) <= 1500
        assert "next" not in result
        assert len(result["caveats"]) >= 1

    def test_an_impossible_budget_keeps_one_item_per_list(self) -> None:
        result = fit_budget(self._result(), 10)
        assert len(result["answer"]["programs"]) == 1

    def test_a_roomy_budget_keeps_the_envelope(self) -> None:
        original = self._result()
        result = fit_budget(copy.deepcopy(original), 100_000)
        assert result == original


class TestO6FileStatusGuardIsPassed:
    def test_branch_scenarios_below_the_guard_are_verified(
        self, tmp_path: Path
    ) -> None:
        program = tmp_path / "F.cbl"
        program.write_text(FILE_PROGRAM + """\
           OPEN INPUT F1
           IF NOT FS-OK
              GOBACK
           END-IF
           READ F1
           IF WS-FS NOT = '00' AND WS-FS NOT = '04'
              GOBACK
           END-IF
           IF IN-CODE = 'AB'
              DISPLAY 'AB'
           ELSE
              DISPLAY 'OTHER'
           END-IF
           CLOSE F1
           GOBACK.
""")
        bundle = ProgramFixtureGenerator().generate_with_scenarios_from_file(
            str(program), mode="branches", seed=3
        )
        branch = [s for s in bundle.scenarios if "IF@" in s.name]
        assert branch
        for scenario in branch:
            assert scenario.verification is not None
            assert scenario.verification["status"] == "verified", scenario.name

    def test_a_guard_that_exits_on_success_still_counts(self, tmp_path: Path) -> None:
        program = tmp_path / "S.cbl"
        program.write_text(FILE_PROGRAM + """\
           OPEN INPUT F1
           IF FS-OK
              GOBACK
           END-IF
           READ F1
           IF IN-CODE = 'AB'
              DISPLAY 'AB'
           END-IF
           GOBACK.
""")
        bundle = ProgramFixtureGenerator().generate_with_scenarios_from_file(
            str(program), mode="branches", seed=3
        )
        branch = [
            s for s in bundle.scenarios if "IF@" in s.name and "@19" not in s.name
        ]
        assert branch
        assert all(
            s.verification is not None and s.verification["status"] == "unverified"
            for s in branch
        )
