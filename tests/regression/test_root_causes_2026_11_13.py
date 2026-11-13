"""Regression tests from the 2026-11-13 AI_arena root-cause table (N3, N4,
O2, O3, O5, O6), reproduced on small fixtures because the real files are
private:

* N3 -- an ODO table whose only child is FILLER was left out of the CSV
  layout, so its counter got any value its PICTURE holds;
* N4 -- a procedure copybook opening with the tail of a statement
  (``USING WS-A WS-B.``) was read as a data copybook (0-byte FILLER);
* O2 -- ``21500. PERFORM 21510.`` just above 21510, falling on to a
  paragraph that PERFORMs 21500, was reported as a PERFORM/GO TO cycle;
* O3 -- text past column 72 after the statement's period in column 72 said
  "the word it ends is cut short";
* O5 -- the MCP budget emptied one-item lists only when emptying all of
  them fit, so 2,000 bytes asked got 2,184;
* O6 -- a guard on a WORKING-STORAGE flag set by a PERFORMed check left
  every branch scenario below it unverified.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from cobolparser import parse_cobol
from cobolparser.analysis.lint import line_length_findings
from cobolparser.analysis.program_flow import ProgramFlowAnalyzer
from cobolparser.analysis.recursion_risk import RecursionRiskAnalyzer
from cobolparser.generators import CopybookDataGenerator, DataGeneratorOptions
from cobolparser.generators.program_fixtures import ProgramFixtureGenerator
from cobolparser.layout.copybook import procedure_code_start
from cobolparser.layout.errors import CopybookLayoutError
from cobolparser.mcp.envelope import fit_budget, wire_size


class TestN3FillerOnlyOdoTable:
    COPYBOOK = """\
       01  WSPD4-REC.
           05  WSPD4-KEY       PIC X(4).
           05  WSPD4-FRNSFR    PIC 9(3).
           05  WSPD4-TAB OCCURS 1 TO 15 TIMES DEPENDING ON WSPD4-FRNSFR.
               10  FILLER      PIC X(2).
"""

    def test_the_counter_stays_within_the_table(self) -> None:
        dataset = CopybookDataGenerator(
            DataGeneratorOptions(rows=60, seed=1)
        ).generate_from_source(self.COPYBOOK, filename="N3.cpy")
        column = [f.column for f in dataset.fields].index("WSPD4-FRNSFR")
        counts = [int(row[column]) for row in dataset.rows]
        assert counts and all(1 <= n <= 15 for n in counts), counts


class TestN4StatementTailMember:
    MEMBER = """\
      * P1CKBADR
           USING WS-NB-LIGNES-NOM
                 WS010-JJ-PRES.
       0000-DEBUT.
           MOVE 8 TO RETURN-CODE.
"""

    def test_detected_as_procedure_code(self) -> None:
        assert procedure_code_start(self.MEMBER) == "USING WS-NB-LIGNES-NOM"

    def test_end_scope_word_is_procedure_code(self) -> None:
        assert procedure_code_start("           END-IF.\n") == "END-IF."

    def test_a_data_member_is_not(self) -> None:
        assert procedure_code_start("       01  A PIC X.\n") is None

    def test_gen_data_refuses_it(self) -> None:
        generator = CopybookDataGenerator(DataGeneratorOptions(rows=1, seed=1))
        try:
            generator.generate_from_source(self.MEMBER, filename="P1CKBADR.cpy")
        except CopybookLayoutError as exc:
            assert "PROCEDURE DIVISION code" in str(exc)
        else:
            raise AssertionError("a procedure copybook was read as a record")


O2_HEAD = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. O2.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-I PIC 9(3) VALUE 0.
       PROCEDURE DIVISION.
       0000-MAIN.
"""


def _risks(source: str) -> list[Any]:
    ast = parse_cobol(source).ast
    flow = ProgramFlowAnalyzer().analyze(ast)
    return RecursionRiskAnalyzer().analyze(ast, flow).risks


class TestO2PerformOfTheNextParagraph:
    def test_fall_through_into_the_performing_paragraph(self) -> None:
        source = O2_HEAD + """\
           CONTINUE.
       21500.
           ADD 1 TO WS-I
           PERFORM 21510.
       21510.
           ADD 1 TO WS-I.
       22203.
           IF WS-I < 5
              PERFORM 21500
           END-IF.
       22299.
           STOP RUN.
"""
        assert _risks(source) == []

    def test_a_real_loop_through_the_same_hop_is_kept(self) -> None:
        source = O2_HEAD + """\
           CONTINUE.
       21500.
           ADD 1 TO WS-I
           PERFORM 21510.
       21510.
           IF WS-I > 100
              STOP RUN
           END-IF
           GO TO 21500.
"""
        assert [r.procedures for r in _risks(source)] == [["21500", "21510"]]


class TestO3StrayTextAfterPeriod:
    @staticmethod
    def _line(code: str, tail: str) -> str:
        return (code + " " * 72)[:71] + tail

    def _findings(self, *lines: str) -> list[Any]:
        source = "\n".join(
            [
                "       IDENTIFICATION DIVISION.",
                "       PROGRAM-ID. O3.",
                "       PROCEDURE DIVISION.",
                "       P1.",
                *lines,
                "           STOP RUN.",
            ]
        )
        return line_length_findings("O3.cbl", source + "\n")

    def test_period_in_column_72_is_info(self) -> None:
        (finding,) = self._findings(
            self._line("           MOVE 12345 TO RETURN-CODE", ".ATE")
        )
        assert finding.severity == "info"
        assert "nothing is cut" in finding.message

    def test_a_cut_word_is_still_a_warning(self) -> None:
        (finding,) = self._findings(self._line("           DISPLAY 'X'", "YHYCA"))
        assert finding.severity == "warning"
        assert "cut short" in finding.message

    def test_period_in_column_72_inside_a_literal_is_a_warning(self) -> None:
        # #908: the column-72 ``.`` is literal text, so ``50 USD'.`` is cut.
        (finding,) = self._findings(
            self._line("           DISPLAY 'AMOUNT IS 12." + "X" * 37, ".50 USD'.")
        )
        assert finding.severity == "warning"
        assert "cut short" in finding.message

    def test_closed_literal_before_period_in_column_72_is_info(self) -> None:
        (finding,) = self._findings(
            self._line("           DISPLAY 'IT''S' 'OK'", ".ATE")
        )
        assert finding.severity == "info"


class TestO5StrictBudget:
    def _result(self) -> dict[str, Any]:
        return {
            "surface_version": "1",
            "answer": {
                "root": "src",
                "programs": [
                    {"program": f"PGM{n:03d}", "grade": "A", "notes": "x" * 60}
                    for n in range(40)
                ],
                "copybooks": [f"MISSING-COPYBOOK-{n}" for n in range(40)],
                "jobs": [f"JOB{n:03d}" for n in range(40)],
            },
            "caveats": [
                {"kind": "unresolved-copybook", "message": f"MISS{n} not found " * 30}
                for n in range(12)
            ],
            "truncated": [],
            "next": ['program_brief(file="src/PGM000.cbl")'],
        }

    def test_a_budget_above_the_bare_answer_is_met(self) -> None:
        bare = self._result()
        for key in ("programs", "copybooks", "jobs"):
            bare["answer"][key] = []
        bare["caveats"] = []
        bare.pop("next")
        bare["truncated"] = [{"fields": 4, "reason": "answer budget"}]
        floor = wire_size(bare)
        for budget in range(floor + 10, floor + 1500, 37):
            result = fit_budget(self._result(), budget)
            assert wire_size(result) <= budget, budget
            assert result["truncated"][-1]["reason"] == "answer budget"

    def test_lists_go_before_the_record_of_cuts(self) -> None:
        result = fit_budget(self._result(), 900)
        assert wire_size(result) <= 900
        folded = result["truncated"][-1]
        assert folded["fields"] >= 1

    def test_below_the_bare_answer_the_one_item_lists_stay(self) -> None:
        result = fit_budget(self._result(), 50)
        assert len(result["answer"]["programs"]) == 1


O6_PROGRAM = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. F.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT F1 ASSIGN TO DD1
               FILE STATUS IS WS-FS.
       DATA DIVISION.
       FILE SECTION.
       FD  F1.
       01  F1-REC.
           05  IN-CODE PIC X(2).
       WORKING-STORAGE SECTION.
       01  WS-FS   PIC XX.
       01  WS-FLAGS.
           05  WS-ERR PIC X VALUE 'N'.
               88  ERR-ON VALUE 'Y'.
       PROCEDURE DIVISION.
       MAIN-PARA.
           OPEN INPUT F1
           READ F1
           PERFORM 1000-CHECK
           IF {guard}
              GOBACK
           END-IF
           IF IN-CODE = 'AB'
              DISPLAY 'AB'
           ELSE
              DISPLAY 'OTHER'
           END-IF
           CLOSE F1
           GOBACK.
       1000-CHECK.
           IF IN-CODE = SPACES
              {setter}
           END-IF.
"""


class TestO6FlagGuard:
    def _statuses(
        self, tmp_path: Path, guard: str, setter: str, extra: str = ""
    ) -> list[dict[str, Any]]:
        source = O6_PROGRAM.format(guard=guard, setter=setter)
        if extra:
            source = source.replace("           PERFORM 1000-CHECK\n", extra)
        program = tmp_path / "F.cbl"
        program.write_text(source)
        bundle = ProgramFixtureGenerator().generate_with_scenarios_from_file(
            str(program), mode="branches", seed=3
        )
        return [s.verification for s in bundle.scenarios if "IF@" in s.name]

    def test_move_and_compare(self, tmp_path: Path) -> None:
        checks = self._statuses(tmp_path, "WS-ERR = 'Y'", "MOVE 'Y' TO WS-ERR")
        assert checks and all(c["status"] == "verified" for c in checks)

    def test_set_and_condition_name(self, tmp_path: Path) -> None:
        checks = self._statuses(tmp_path, "ERR-ON", "SET ERR-ON TO TRUE")
        assert checks and all(c["status"] == "verified" for c in checks)

    def test_negated_guard(self, tmp_path: Path) -> None:
        checks = self._statuses(tmp_path, "NOT WS-ERR = 'N'", "MOVE 'Y' TO WS-ERR")
        assert checks and all(c["status"] == "verified" for c in checks)

    def test_a_second_write_keeps_it_unverified_and_says_why(
        self, tmp_path: Path
    ) -> None:
        checks = self._statuses(
            tmp_path,
            "WS-ERR = 'Y'",
            "MOVE 'Y' TO WS-ERR",
            extra="           PERFORM 1000-CHECK\n           INITIALIZE WS-FLAGS\n",
        )
        unverified = [c for c in checks if c["status"] == "unverified"]
        assert unverified
        assert any(
            "a value the program sets itself" in gap
            for c in unverified
            for gap in c["gaps"]
        )
