"""Regression tests for the 2026-09-09 analysis review.

One class per finding, each pinning the corrected behaviour on a small
inline program (fixed format, Area A at column 8). Where a finding was a
false positive the test also carries a positive control -- a nearby real
defect that must still be reported -- so the fix cannot pass by silencing
the analyzer.
"""

from cobolparser import parse_cobol
from cobolparser.analysis import (
    DeadCodeAnalyzer,
    IOLogger,
    IOSequenceAnalyzer,
    LinkageChecker,
    MoveTypeChecker,
    ProgramFlowAnalyzer,
    RecursionRiskAnalyzer,
    UnusedVariableAnalyzer,
)
from cobolparser.analysis.io_sequence import IOViolationKind
from cobolparser.analysis.linkage_checker import LinkageViolationKind
from cobolparser.analysis.lint import _SEVERITY_LINKAGE, LintAnalyzer
from cobolparser.analysis.move_type_checker import MoveViolationKind


def _fixed(body: str) -> str:
    return "".join(f"       {line}\n" for line in body.strip("\n").splitlines())


def _parse(body: str):
    result = parse_cobol(_fixed(body), filename="review.cbl")
    assert not result.errors, [str(e) for e in result.errors]
    assert result.ast is not None
    return result.ast


# ---------------------------------------------------------------------------
# 1. recursion-check: the priming-read idiom is not an infinite loop
# ---------------------------------------------------------------------------


class TestFinding1RecursionPrimingRead:
    PRIMING_READ = """
IDENTIFICATION DIVISION.
PROGRAM-ID. PRIME.
ENVIRONMENT DIVISION.
INPUT-OUTPUT SECTION.
FILE-CONTROL.
    SELECT IN-FILE ASSIGN TO INFILE.
DATA DIVISION.
FILE SECTION.
FD  IN-FILE.
01  IN-REC            PIC X(80).
WORKING-STORAGE SECTION.
01  WS-EOF            PIC X VALUE 'N'.
PROCEDURE DIVISION.
0000-MAIN.
    OPEN INPUT IN-FILE.
    PERFORM 1000-READ.
    PERFORM 2000-PROCESS UNTIL WS-EOF = 'Y'.
    CLOSE IN-FILE.
    STOP RUN.
1000-READ.
    READ IN-FILE AT END MOVE 'Y' TO WS-EOF.
2000-PROCESS.
    DISPLAY IN-REC.
    PERFORM 1000-READ.
"""

    def test_priming_read_is_not_a_cycle_risk(self):
        ast = _parse(self.PRIMING_READ)
        flow = ProgramFlowAnalyzer().analyze(ast)
        # 1000-READ is only ever PERFORMed, so its end returns to the
        # performer: no fall-through edge into 2000-PROCESS, and no MIXED
        # cycle through it (cobol-test run on PAYMAIN, 2026-11-06).
        assert not any(
            e.source == "1000-READ" and e.edge_type.value == "FALL_THROUGH"
            for e in flow.edges
        )
        assert flow.cycle_details == []
        # A PERFORM returns from the end of its range: not a runtime loop.
        report = RecursionRiskAnalyzer().analyze(ast, flow_report=flow)
        assert report.risks == []
        lint = LintAnalyzer(["recursion-check"]).analyze(ast)
        assert lint.findings == []

    def test_fall_through_into_performed_paragraph_still_reported(self):
        # A-PARA performs B-PARA, *and* falls into it; C-PARA jumps back.
        # B-PARA is entered by fall-through, so leaving it by fall-through is
        # real and the loop is real.
        ast = _parse("""
IDENTIFICATION DIVISION.
PROGRAM-ID. LOOPA.
PROCEDURE DIVISION.
A-PARA.
    PERFORM B-PARA.
    DISPLAY 'A'.
B-PARA.
    DISPLAY 'B'.
C-PARA.
    GO TO A-PARA.
""")
        report = RecursionRiskAnalyzer().analyze(ast)
        assert [r.mechanism for r in report.risks] == ["MIXED"]
        assert report.risks[0].severity == "HIGH"

    def test_goto_out_of_thru_range_still_reported(self):
        ast = _parse("""
IDENTIFICATION DIVISION.
PROGRAM-ID. LOOPB.
PROCEDURE DIVISION.
X-PARA.
    PERFORM A-PARA THRU C-PARA.
    STOP RUN.
A-PARA.
    DISPLAY 'A'.
B-PARA.
    DISPLAY 'B'.
C-PARA.
    GO TO X-PARA.
""")
        report = RecursionRiskAnalyzer().analyze(ast)
        assert [r.mechanism for r in report.risks] == ["MIXED"]


# ---------------------------------------------------------------------------
# 2. dead-code: GO TO onto a THRU range end does not fall out of the range
# ---------------------------------------------------------------------------


class TestFinding2DeadCodeAfterThruExit:
    PROGRAM = """
IDENTIFICATION DIVISION.
PROGRAM-ID. DEADX.
DATA DIVISION.
WORKING-STORAGE SECTION.
01  WS-FLAG           PIC X VALUE 'N'.
PROCEDURE DIVISION.
0000-MAIN.
    PERFORM 1000-INIT THRU 1000-EXIT.
    STOP RUN.
1000-INIT.
    IF WS-FLAG = 'Y'
        GO TO 1000-EXIT
    END-IF.
    DISPLAY 'INIT'.
1000-EXIT.
    EXIT.
9999-NEVER-CALLED.
    DISPLAY 'DEAD'.
9998-ALSO-DEAD.
    DISPLAY 'DEAD 2'.
"""

    def test_paragraphs_after_exit_are_dead(self):
        report = DeadCodeAnalyzer().analyze(_parse(self.PROGRAM))
        assert [d.name for d in report.dead_items] == [
            "9999-NEVER-CALLED",
            "9998-ALSO-DEAD",
        ]

    def test_goto_onto_plain_paragraph_still_falls_through(self):
        # Same shape without the PERFORM THRU: the GO TO target is an
        # ordinary paragraph, control keeps running from it.
        ast = _parse("""
IDENTIFICATION DIVISION.
PROGRAM-ID. DEADY.
DATA DIVISION.
WORKING-STORAGE SECTION.
01  WS-FLAG           PIC X VALUE 'N'.
PROCEDURE DIVISION.
0000-MAIN.
    IF WS-FLAG = 'Y'
        GO TO 2000-LATER
    END-IF.
    STOP RUN.
1000-SKIPPED.
    DISPLAY 'SKIPPED'.
2000-LATER.
    DISPLAY 'LATER'.
3000-REACHED.
    DISPLAY 'REACHED BY FALL-THROUGH'.
""")
        report = DeadCodeAnalyzer().analyze(ast)
        assert [d.name for d in report.dead_items] == ["1000-SKIPPED"]


# ---------------------------------------------------------------------------
# 3. io-sequence: WRITE/REWRITE resolve their record to its FD
# ---------------------------------------------------------------------------


class TestFinding3WriteBeforeOpen:
    HEADER = """
IDENTIFICATION DIVISION.
PROGRAM-ID. IOW.
ENVIRONMENT DIVISION.
INPUT-OUTPUT SECTION.
FILE-CONTROL.
    SELECT OUT-FILE ASSIGN TO OUTFILE.
    SELECT UPD-FILE ASSIGN TO UPDFILE
        ORGANIZATION IS INDEXED
        ACCESS IS RANDOM
        RECORD KEY IS UPD-KEY.
DATA DIVISION.
FILE SECTION.
FD  OUT-FILE.
01  OUT-REC           PIC X(80).
FD  UPD-FILE.
01  UPD-REC.
    05 UPD-KEY        PIC X(5).
    05 UPD-DATA       PIC X(75).
PROCEDURE DIVISION.
0000-MAIN.
"""

    def test_write_and_rewrite_before_open_are_reported(self):
        ast = _parse(self.HEADER + """
    WRITE OUT-REC.
    REWRITE UPD-REC.
    CLOSE OUT-FILE UPD-FILE.
    STOP RUN.
""")
        report = IOSequenceAnalyzer().analyze(ast)
        found = {(v.kind, v.file_name.upper()) for v in report.violations}
        assert (IOViolationKind.WRITE_BEFORE_OPEN, "OUT-FILE") in found
        assert (IOViolationKind.REWRITE_BEFORE_OPEN, "UPD-FILE") in found

    def test_write_and_rewrite_after_open_are_clean(self):
        ast = _parse(self.HEADER + """
    OPEN OUTPUT OUT-FILE I-O UPD-FILE.
    WRITE OUT-REC.
    REWRITE UPD-REC.
    CLOSE OUT-FILE UPD-FILE.
    STOP RUN.
""")
        assert IOSequenceAnalyzer().analyze(ast).violations == []


# ---------------------------------------------------------------------------
# 4. io-sequence: SORT/MERGE INPUT/OUTPUT PROCEDUREs are walked
# ---------------------------------------------------------------------------


class TestFinding4SortProcedures:
    PROGRAM = """
IDENTIFICATION DIVISION.
PROGRAM-ID. SRTP.
ENVIRONMENT DIVISION.
INPUT-OUTPUT SECTION.
FILE-CONTROL.
    SELECT IN-FILE ASSIGN TO INFILE.
    SELECT OUT-FILE ASSIGN TO OUTFILE.
    SELECT SORT-FILE ASSIGN TO SORTWK.
DATA DIVISION.
FILE SECTION.
FD  IN-FILE.
01  IN-REC            PIC X(80).
FD  OUT-FILE.
01  OUT-REC           PIC X(80).
SD  SORT-FILE.
01  SORT-REC.
    05 SORT-KEY       PIC X(10).
    05 FILLER         PIC X(70).
WORKING-STORAGE SECTION.
01  WS-EOF            PIC X VALUE 'N'.
PROCEDURE DIVISION.
0000-MAIN.
    SORT SORT-FILE ON ASCENDING KEY SORT-KEY
        INPUT PROCEDURE IS 1000-INPUT
        OUTPUT PROCEDURE IS 2000-OUTPUT.
    STOP RUN.
1000-INPUT.
    OPEN INPUT IN-FILE.
    PERFORM UNTIL WS-EOF = 'Y'
        READ IN-FILE
            AT END MOVE 'Y' TO WS-EOF
            NOT AT END RELEASE SORT-REC FROM IN-REC
        END-READ
    END-PERFORM.
    CLOSE IN-FILE.
2000-OUTPUT.
    OPEN OUTPUT OUT-FILE.
    MOVE 'N' TO WS-EOF.
    PERFORM UNTIL WS-EOF = 'Y'
        RETURN SORT-FILE INTO OUT-REC
            AT END MOVE 'Y' TO WS-EOF
            NOT AT END WRITE OUT-REC
        END-RETURN
    END-PERFORM.
    CLOSE OUT-FILE.
"""

    def test_well_formed_procedures_are_clean(self):
        assert IOSequenceAnalyzer().analyze(_parse(self.PROGRAM)).violations == []

    def test_missing_open_inside_input_procedure_is_reported(self):
        ast = _parse(self.PROGRAM.replace("    OPEN INPUT IN-FILE.\n", ""))
        kinds = {
            (v.kind, v.file_name.upper())
            for v in IOSequenceAnalyzer().analyze(ast).violations
        }
        assert (IOViolationKind.READ_BEFORE_OPEN, "IN-FILE") in kinds
        assert (IOViolationKind.CLOSE_NOT_OPEN, "IN-FILE") in kinds

    def test_close_inside_input_procedure_is_seen(self):
        ast = _parse("""
IDENTIFICATION DIVISION.
PROGRAM-ID. SRTB.
ENVIRONMENT DIVISION.
INPUT-OUTPUT SECTION.
FILE-CONTROL.
    SELECT IN-FILE ASSIGN TO INFILE.
    SELECT SORT-FILE ASSIGN TO SORTWK.
DATA DIVISION.
FILE SECTION.
FD  IN-FILE.
01  IN-REC            PIC X(80).
SD  SORT-FILE.
01  SORT-REC          PIC X(80).
WORKING-STORAGE SECTION.
01  WS-EOF            PIC X VALUE 'N'.
PROCEDURE DIVISION.
0000-MAIN.
    OPEN INPUT IN-FILE.
    SORT SORT-FILE ON ASCENDING KEY SORT-REC
        INPUT PROCEDURE IS 1000-INPUT
        GIVING IN-FILE.
    STOP RUN.
1000-INPUT.
    READ IN-FILE AT END MOVE 'Y' TO WS-EOF.
    RELEASE SORT-REC FROM IN-REC.
    CLOSE IN-FILE.
""")
        assert IOSequenceAnalyzer().analyze(ast).violations == []


# ---------------------------------------------------------------------------
# 5. linkage-check: CALL ... USING BY VALUE linkage-item is legal
# ---------------------------------------------------------------------------


class TestFinding5ByValueLinkageIsLegal:
    PROGRAM = """
IDENTIFICATION DIVISION.
PROGRAM-ID. OUTER.
DATA DIVISION.
LINKAGE SECTION.
01  LK-N              PIC S9(9) COMP.
PROCEDURE DIVISION USING LK-N.
0000-MAIN.
    CALL 'INNER' USING BY VALUE LK-N.
    GOBACK.
IDENTIFICATION DIVISION.
PROGRAM-ID. INNER.
DATA DIVISION.
LINKAGE SECTION.
01  IN-N              PIC S9(9) COMP.
PROCEDURE DIVISION USING BY VALUE IN-N.
0000-INNER.
    DISPLAY IN-N.
    GOBACK.
END PROGRAM INNER.
END PROGRAM OUTER.
"""

    def test_no_violation_and_rule_is_gone(self):
        report = LinkageChecker().check(_parse(self.PROGRAM))
        assert report.violations == []
        assert not hasattr(LinkageViolationKind, "VALUE_TO_LINKAGE")
        assert "VALUE_TO_LINKAGE" not in _SEVERITY_LINKAGE

    def test_argument_count_mismatch_still_reported(self):
        # Both arguments stay BY VALUE, matching INNER's own BY VALUE IN-N
        # for the one position it declares -- isolates the count mismatch
        # this test is about from the (separately tested) passing-mode
        # check below, which the extra argument has no declared mode to
        # disagree with anyway.
        ast = _parse(
            self.PROGRAM.replace("USING BY VALUE LK-N.", "USING BY VALUE LK-N LK-N.")
        )
        kinds = [v.kind for v in LinkageChecker().check(ast).violations]
        assert kinds == [LinkageViolationKind.TOO_MANY_ARGS]


# ---------------------------------------------------------------------------
# 6. move-type-check: integer vs non-integer numeric, alphanumeric-edited
# ---------------------------------------------------------------------------


class TestFinding6MoveIntegerDistinction:
    PROGRAM = """
IDENTIFICATION DIVISION.
PROGRAM-ID. MOVX.
DATA DIVISION.
WORKING-STORAGE SECTION.
01  WS-AMT            PIC 9(5)V99 VALUE 123.45.
01  WS-INT            PIC 9(5).
01  WS-TXT            PIC X(7).
01  WS-AEDIT          PIC XXBXX.
01  WS-NUM            PIC 9(4).
01  WS-NEDIT          PIC ZZ9.99.
01  WS-FLOAT          COMP-1.
01  WS-NUM2           PIC S9(3) COMP-3.
01  WS-SCALED         PIC PPP9.
PROCEDURE DIVISION.
0000-MAIN.
    MOVE WS-AMT TO WS-TXT.
    MOVE WS-AMT TO WS-AEDIT.
    MOVE WS-AEDIT TO WS-NUM.
    MOVE WS-AEDIT TO WS-NEDIT.
    MOVE WS-INT TO WS-TXT.
    MOVE WS-FLOAT TO WS-TXT.
    MOVE WS-NUM2 TO WS-TXT.
    MOVE WS-NEDIT TO WS-TXT.
    MOVE WS-SCALED TO WS-TXT.
    MOVE 1.5 TO WS-TXT.
    MOVE 15 TO WS-TXT.
    MOVE WS-AMT TO WS-NUM.
    STOP RUN.
"""

    def _violations(self):
        report = MoveTypeChecker().check(_parse(self.PROGRAM))
        return {
            (v.source_name, v.target_name): v.kind for v in report.violations
        }, report

    def test_non_integer_numeric_to_alphanumeric_is_an_error(self):
        by_pair, _ = self._violations()
        assert by_pair[("WS-AMT", "WS-TXT")] == MoveViolationKind.ERROR
        assert by_pair[("WS-AMT", "WS-AEDIT")] == MoveViolationKind.ERROR
        assert by_pair[("WS-FLOAT", "WS-TXT")] == MoveViolationKind.ERROR
        assert by_pair[("WS-SCALED", "WS-TXT")] == MoveViolationKind.ERROR
        assert by_pair[("1.5", "WS-TXT")] == MoveViolationKind.ERROR

    def test_alphanumeric_edited_to_numeric_is_an_error(self):
        by_pair, _ = self._violations()
        assert by_pair[("WS-AEDIT", "WS-NUM")] == MoveViolationKind.ERROR
        assert by_pair[("WS-AEDIT", "WS-NEDIT")] == MoveViolationKind.ERROR

    def test_integer_numeric_to_alphanumeric_stays_legal(self):
        by_pair, report = self._violations()
        for pair in [
            ("WS-INT", "WS-TXT"),
            ("WS-NUM2", "WS-TXT"),
            ("WS-NEDIT", "WS-TXT"),
            ("15", "WS-TXT"),
            ("WS-AMT", "WS-NUM"),
        ]:
            assert pair not in by_pair, pair
        assert report.unresolved_count == 0


# ---------------------------------------------------------------------------
# 7. unused-variables: SELECT / FD clause references count as uses
# ---------------------------------------------------------------------------


class TestFinding7SelectAndFdReferences:
    PROGRAM = """
IDENTIFICATION DIVISION.
PROGRAM-ID. UNU.
ENVIRONMENT DIVISION.
INPUT-OUTPUT SECTION.
FILE-CONTROL.
    SELECT IN-FILE ASSIGN TO INFILE
        ORGANIZATION IS INDEXED ACCESS IS DYNAMIC
        RECORD KEY IS IN-KEY
        ALTERNATE RECORD KEY IS IN-ALT WITH DUPLICATES
        FILE STATUS IS WS-FS.
    SELECT REL-FILE ASSIGN TO RELFILE
        ORGANIZATION IS RELATIVE ACCESS IS RANDOM
        RELATIVE KEY IS WS-RELKEY.
DATA DIVISION.
FILE SECTION.
FD  IN-FILE
    RECORD VARYING FROM 10 TO 80 DEPENDING ON WS-RECLEN.
01  IN-REC.
    05 IN-KEY         PIC X(5).
    05 IN-ALT         PIC X(5).
    05 IN-DATA        PIC X(70).
FD  REL-FILE.
01  REL-REC           PIC X(20).
WORKING-STORAGE SECTION.
01  WS-FS             PIC XX.
01  WS-RECLEN         PIC 9(4).
01  WS-RELKEY         PIC 9(4).
01  WS-UNUSED-REAL    PIC X.
PROCEDURE DIVISION.
0000-MAIN.
    OPEN INPUT IN-FILE.
    READ IN-FILE.
    DISPLAY IN-DATA.
    READ REL-FILE.
    DISPLAY REL-REC.
    GOBACK.
"""

    def test_clause_referenced_items_are_used(self):
        report = UnusedVariableAnalyzer().analyze(_parse(self.PROGRAM))
        unused = {item.name for item in report.unused_items}
        for name in ("WS-FS", "WS-RECLEN", "WS-RELKEY", "IN-KEY", "IN-ALT"):
            assert name not in unused, name
        # Positive control: an item nothing names is still reported.
        assert "WS-UNUSED-REAL" in unused


# ---------------------------------------------------------------------------
# 8. IOLogger: per-file OPEN mode, WRITE/REWRITE target
# ---------------------------------------------------------------------------


class TestFinding8IOLoggerModesAndTargets:
    PROGRAM = """
IDENTIFICATION DIVISION.
PROGRAM-ID. IOL.
ENVIRONMENT DIVISION.
INPUT-OUTPUT SECTION.
FILE-CONTROL.
    SELECT IN-FILE ASSIGN TO INFILE.
    SELECT OUT-FILE ASSIGN TO OUTFILE.
DATA DIVISION.
FILE SECTION.
FD  IN-FILE.
01  IN-REC            PIC X(80).
FD  OUT-FILE.
01  OUT-REC           PIC X(80).
PROCEDURE DIVISION.
0000-MAIN.
    OPEN INPUT IN-FILE OUTPUT OUT-FILE.
    READ IN-FILE.
    WRITE OUT-REC FROM IN-REC.
    REWRITE OUT-REC.
    CLOSE IN-FILE OUT-FILE.
    STOP RUN.
"""

    def test_open_mode_is_per_file(self):
        report = IOLogger().analyze(_parse(self.PROGRAM))
        opens = {
            op.target: (op.operation, op.direction)
            for op in report.operations
            if op.operation.startswith("OPEN")
        }
        assert opens == {
            "IN-FILE": ("OPEN INPUT", "INPUT"),
            "OUT-FILE": ("OPEN OUTPUT", "OUTPUT"),
        }

    def test_write_and_rewrite_target_the_record_file(self):
        report = IOLogger().analyze(_parse(self.PROGRAM))
        targets = {
            op.operation: op.target
            for op in report.operations
            if op.operation in ("WRITE", "REWRITE")
        }
        assert targets == {"WRITE": "OUT-FILE", "REWRITE": "OUT-FILE"}


# ---------------------------------------------------------------------------
# 9. dead-code: same-named paragraphs in different sections
# ---------------------------------------------------------------------------


class TestFinding9SameNamedParagraphs:
    PROGRAM = """
IDENTIFICATION DIVISION.
PROGRAM-ID. QPF.
PROCEDURE DIVISION.
0000-MAIN SECTION.
0000-START.
    PERFORM 100-DO OF SEC-A.
    PERFORM 100-DO IN SEC-B.
    STOP RUN.
SEC-A SECTION.
100-DO.
    DISPLAY 'A'.
SEC-B SECTION.
100-DO.
    DISPLAY 'B'.
SEC-C SECTION.
200-DEAD.
    DISPLAY 'DEAD'.
"""

    def test_every_section_holding_the_name_is_live(self):
        report = DeadCodeAnalyzer().analyze(_parse(self.PROGRAM))
        assert [d.name for d in report.dead_items] == ["SEC-C", "200-DEAD"]


# ---------------------------------------------------------------------------
# 10. lint: same-named LINKAGE items in two units are two findings
# ---------------------------------------------------------------------------


class TestFinding10LintProgramUnits:
    PROGRAM = """
IDENTIFICATION DIVISION.
PROGRAM-ID. OUTER.
PROCEDURE DIVISION.
0000-MAIN.
    CALL 'SUB1' USING RETURN-CODE.
    CALL 'SUB2' USING RETURN-CODE.
    GOBACK.
IDENTIFICATION DIVISION.
PROGRAM-ID. SUB1.
DATA DIVISION.
LINKAGE SECTION.
01  LK-PARM           PIC X(10).
01  LK-EXTRA          PIC X(10).
PROCEDURE DIVISION USING LK-PARM.
S1-MAIN.
    GOBACK.
END PROGRAM SUB1.
IDENTIFICATION DIVISION.
PROGRAM-ID. SUB2.
DATA DIVISION.
LINKAGE SECTION.
01  LK-PARM           PIC X(10).
01  LK-EXTRA          PIC X(10).
PROCEDURE DIVISION USING LK-PARM.
S2-MAIN.
    GOBACK.
END PROGRAM SUB2.
END PROGRAM OUTER.
"""

    def test_lint_reports_one_finding_per_unit_with_location(self):
        report = LintAnalyzer(["linkage-check"]).analyze(_parse(self.PROGRAM))
        assert len(report.findings) == 2
        assert {f.symbol for f in report.findings} == {"LK-EXTRA"}
        lines = [f.location.line for f in report.findings]
        assert all(lines) and len(set(lines)) == 2

    def test_standalone_checker_still_covers_contained_programs(self):
        ast = _parse(self.PROGRAM)
        report = LinkageChecker().check(ast)
        unreferenced = [
            v
            for v in report.violations
            if v.kind == LinkageViolationKind.UNREFERENCED_LINKAGE
        ]
        assert [v.item_name for v in unreferenced] == ["LK-EXTRA", "LK-EXTRA"]
        assert len({v.location.line for v in unreferenced}) == 2
        # The unit-scoped mode lint uses reports nothing for the outer
        # program, which declares no LINKAGE items of its own.
        scoped = LinkageChecker(include_contained_programs=False).check(ast)
        assert scoped.violations == []

    def test_unit_scoped_check_still_sees_sibling_interfaces(self):
        ast = _parse(
            self.PROGRAM.replace(
                "S1-MAIN.\n    GOBACK.",
                "S1-MAIN.\n    CALL 'SUB2' USING LK-PARM LK-EXTRA.\n    GOBACK.",
            )
        )
        report = LintAnalyzer(["linkage-check"]).analyze(ast)
        assert [f.kind for f in report.findings if f.symbol == "SUB2"] == [
            "TOO_MANY_ARGS"
        ]
