"""Lint policy: inline suppressions, severity overrides, the baseline, and
the noise cuts of 2026-11-06 (what lint grades info rather than warning).

Each noise cut is pinned on the shape it was measured on: CardDemo's FILE
STATUS halves (``ACCTFILE-STAT1`` under ``ACCTFILE-STATUS``), NIST's GO TO
loops, CardDemo's ``0000-MAIN-EXIT. EXIT.`` paragraphs and ``MOVE '05' TO
TRAN-CAT-CD``.
"""

from __future__ import annotations

import pytest

from cobolparser.analysis.lint import (
    LintAnalyzer,
    LintFinding,
    LintReport,
    apply_baseline,
    apply_severity_overrides,
    apply_suppressions,
    baseline_document,
    baseline_fingerprint,
    load_baseline,
    parse_suppressions,
)
from cobolparser.analysis.move_type_checker import MoveTypeChecker
from cobolparser.models.ast_base import SourceLocation
from cobolparser.parser import parse_cobol
from cobolparser.preprocess._system_copybooks import (
    SYSTEM_COPYBOOK_DIR,
    SYSTEM_COPYBOOKS,
    with_system_copybooks,
)


def _finding(
    rule: str = "dead-code",
    line: int | None = 1,
    kind: str | None = "PARAGRAPH",
    symbol: str | None = "P1",
    severity: str = "warning",
    message: str = "paragraph P1 can never be reached",
) -> LintFinding:
    return LintFinding(
        rule=rule,
        severity=severity,
        message=message,
        location=SourceLocation(line, 1) if line is not None else None,
        symbol=symbol,
        kind=kind,
    )


def _ast(source: str):
    result = parse_cobol(source)
    assert result.ast is not None, result.errors
    return result.ast


# -- inline suppressions -------------------------------------------------------


SUPPRESSED = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. SUP.
      * cobol-lint: disable-next-line=dead-code
      *  (a second comment line in between)

       PARA-3.
           DISPLAY 'X'.  *> cobol-lint: disable=unused-variables
      * cobol-lint: disable=move-type-check/WARNING
           MOVE A TO B.
      * cobol-lint: enable=move-type-check
           MOVE C TO D.
           DISPLAY '*> cobol-lint: disable'.
"""


class TestParseSuppressions:
    def test_disable_next_line_skips_comments_and_blank_lines(self) -> None:
        directives = parse_suppressions(SUPPRESSED)
        assert directives.covers(6, _finding(line=6))
        assert not directives.covers(7, _finding(line=7))

    def test_a_trailing_directive_covers_its_own_line(self) -> None:
        directives = parse_suppressions(SUPPRESSED)
        unused = _finding(rule="unused-variables", kind="WORKING-STORAGE")
        assert directives.covers(7, unused)
        assert not directives.covers(9, unused)

    def test_a_block_runs_to_the_enable_and_honours_kind(self) -> None:
        directives = parse_suppressions(SUPPRESSED)
        warning = _finding(rule="move-type-check", kind="WARNING")
        error = _finding(rule="move-type-check", kind="ERROR")
        assert directives.covers(9, warning)
        assert not directives.covers(9, error)  # only the KIND it names
        # `enable=move-type-check` closes the `move-type-check/WARNING` block
        assert not directives.covers(11, warning)

    def test_a_directive_inside_a_literal_is_not_a_directive(self) -> None:
        directives = parse_suppressions(SUPPRESSED)
        assert not directives.covers(12, _finding(line=12))

    def test_disable_file_and_bare_disable_cover_every_rule(self) -> None:
        text = "      * cobol-lint: disable-file\n       PROCEDURE DIVISION.\n"
        directives = parse_suppressions(text)
        assert directives.covers(None, _finding(line=None))
        assert directives.covers(2, _finding(rule="complexity", kind="HIGH"))

    def test_an_unclosed_block_runs_to_the_end_of_the_file(self) -> None:
        text = "      * cobol-lint: disable=dead-code,complexity\n" + "\n" * 50
        directives = parse_suppressions(text)
        assert directives.covers(40, _finding(line=40))
        assert directives.covers(40, _finding(rule="complexity", kind="HIGH"))
        assert not directives.covers(40, _finding(rule="io-sequence", kind=None))

    def test_free_format_comment_line(self) -> None:
        text = "*> cobol-lint: disable-next-line=dead-code\nPARA.\n"
        assert parse_suppressions(text).covers(2, _finding(line=2))


class TestApplySuppressions:
    def test_judged_in_the_origin_file_when_there_is_one(self, tmp_path) -> None:
        member = tmp_path / "MEMBER.cpy"
        member.write_text(
            "      * cobol-lint: disable-next-line=unused-variables\n"
            "       01  FIELD-A  PIC X.\n"
        )
        report = LintReport(
            findings=[
                LintFinding(
                    rule="unused-variables",
                    severity="warning",
                    message="unused",
                    location=SourceLocation(40, 1),
                    symbol="FIELD-A",
                    origin_file=str(member),
                    origin_line=2,
                ),
                _finding(line=2),  # in the program, which has no directive
            ]
        )
        program = tmp_path / "PROG.cbl"
        program.write_text("       IDENTIFICATION DIVISION.\n")
        apply_suppressions(report, str(program))
        assert [f.rule for f in report.findings] == ["dead-code"]
        assert report.suppressed == 1

    def test_unreadable_file_suppresses_nothing(self, tmp_path) -> None:
        report = LintReport(findings=[_finding()])
        apply_suppressions(report, str(tmp_path / "gone.cbl"))
        assert len(report.findings) == 1 and report.suppressed == 0

    def test_custom_reader(self) -> None:
        report = LintReport(findings=[_finding(line=2)])
        apply_suppressions(
            report,
            "P.cbl",
            read_text=lambda _p: "      * cobol-lint: disable-next-line\n       P1.\n",
        )
        assert report.findings == [] and report.suppressed == 1


# -- severity overrides --------------------------------------------------------


class TestSeverityOverrides:
    def test_rule_slash_kind_wins_over_rule(self) -> None:
        report = LintReport(
            findings=[
                _finding(rule="io-sequence", kind="FILE_LEFT_OPEN"),
                _finding(rule="io-sequence", kind="DOUBLE_OPEN", severity="error"),
            ]
        )
        apply_severity_overrides(
            report, {"io-sequence": "info", "io-sequence/file_left_open": "error"}
        )
        assert [f.severity for f in report.findings] == ["error", "info"]

    def test_nothing_to_do(self) -> None:
        report = LintReport(findings=[_finding()])
        apply_severity_overrides(report, None)
        assert report.findings[0].severity == "warning"

    def test_unknown_level_is_rejected(self) -> None:
        with pytest.raises(ValueError):
            apply_severity_overrides(
                LintReport(findings=[_finding()]), {"dead-code": "fatal"}
            )


# -- baseline ----------------------------------------------------------------


class TestBaseline:
    def test_round_trip_ignores_line_moves(self, tmp_path) -> None:
        program = str(tmp_path / "P.cbl")
        before = LintReport(findings=[_finding(line=10)])
        document = baseline_document([(program, before)], str(tmp_path))
        assert document["findings"][0]["file"] == "P.cbl"
        baseline = load_baseline(document)

        after = LintReport(findings=[_finding(line=25), _finding(symbol="P2")])
        apply_baseline(after, program, baseline, str(tmp_path))
        assert [f.symbol for f in after.findings] == ["P2"]  # only the new one
        assert after.baselined == 1

    def test_a_second_occurrence_beyond_the_count_is_new(self, tmp_path) -> None:
        baseline = load_baseline(
            baseline_document([("P.cbl", LintReport(findings=[_finding()]))], ".")
        )
        report = LintReport(findings=[_finding(), _finding(line=9)])
        apply_baseline(report, "P.cbl", baseline, ".")
        assert len(report.findings) == 1

    def test_a_copybook_finding_counts_once_per_program(self, tmp_path) -> None:
        def in_member() -> LintFinding:
            finding = _finding(rule="unused-variables", kind="WORKING-STORAGE")
            finding.origin_file = str(tmp_path / "CUST.cpy")
            finding.origin_line = 3
            return finding

        document = baseline_document(
            [
                ("A.cbl", LintReport(findings=[in_member()])),
                ("B.cbl", LintReport(findings=[in_member()])),
            ],
            str(tmp_path),
        )
        assert [e["count"] for e in document["findings"]] == [1]
        baseline = load_baseline(document)
        for program in ("A.cbl", "B.cbl"):
            report = LintReport(findings=[in_member()])
            apply_baseline(report, program, baseline, str(tmp_path))
            assert report.findings == []

    def test_a_finding_without_symbol_matches_on_its_message(self) -> None:
        one = _finding(rule="line-length", symbol=None, message="line is 81 long")
        two = _finding(rule="line-length", symbol=None, message="line is 95 long")
        assert baseline_fingerprint(one, "P.cbl", ".") == baseline_fingerprint(
            two, "P.cbl", "."
        )

    def test_wrong_version_is_rejected(self) -> None:
        with pytest.raises(ValueError):
            load_baseline({"version": 99, "findings": []})


# -- noise cuts ----------------------------------------------------------------


GROUP_PROGRAM = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. GRP.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT IN-FILE ASSIGN TO INFILE
               FILE STATUS IS IN-STATUS.
       DATA DIVISION.
       FILE SECTION.
       FD  IN-FILE.
       01  IN-REC.
           05  IN-KEY            PIC X(5).
           05  IN-DATA           PIC X(75).
       WORKING-STORAGE SECTION.
       01  IN-STATUS.
           05  IN-STAT1          PIC X.
           05  IN-STAT2          PIC X.
       01  WS-REC                PIC X(80).
       01  WS-LONELY             PIC X.
       PROCEDURE DIVISION.
       0000-MAIN.
           OPEN INPUT IN-FILE
           READ IN-FILE INTO WS-REC
           IF IN-STATUS = '00'
               DISPLAY WS-REC
           END-IF
           CLOSE IN-FILE
           GOBACK.
       0000-MAIN-EXIT.
           EXIT.
       9999-UNUSED.
           DISPLAY 'NEVER'.
"""


class TestNoiseCuts:
    def _findings(self, source: str, rule: str) -> dict[str, LintFinding]:
        report = LintAnalyzer([rule]).analyze(_ast(source))
        return {f.symbol or "": f for f in report.findings}

    def test_a_field_of_a_group_used_whole_is_info(self) -> None:
        found = self._findings(GROUP_PROGRAM, "unused-variables")
        stat1 = found["IN-STAT1"]
        assert stat1.severity == "info"
        assert "its group IN-STATUS is used as a whole" in stat1.message
        assert found["WS-LONELY"].severity == "warning"

    def test_a_file_record_field_is_info(self) -> None:
        found = self._findings(GROUP_PROGRAM, "unused-variables")
        assert found["IN-KEY"].severity == "info"
        assert found["IN-KEY"].kind == "FILE"

    def test_an_exit_only_paragraph_is_info_and_real_dead_code_warns(self) -> None:
        found = self._findings(GROUP_PROGRAM, "dead-code")
        assert found["0000-MAIN-EXIT"].severity == "info"
        assert "only EXIT" in found["0000-MAIN-EXIT"].message
        assert found["9999-UNUSED"].severity == "warning"

    def test_a_go_to_loop_with_a_way_out_is_info_on_its_header(self) -> None:
        source = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. LOOP.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-N  PIC 9 VALUE 0.
       PROCEDURE DIVISION.
       WAIT-LOOP.
           ADD 1 TO WS-N
           IF WS-N < 5
               GO TO WAIT-LOOP.
           STOP RUN.
"""
        report = LintAnalyzer(["recursion-check"]).analyze(_ast(source))
        [finding] = report.findings
        assert finding.severity == "info"
        assert finding.location is not None and finding.location.line == 7

    def test_an_all_digit_literal_moved_to_a_numeric_item_is_fine(self) -> None:
        source = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. MV.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-CD   PIC 9(4).
       01  WS-ED   PIC Z(4).
       PROCEDURE DIVISION.
           MOVE '05' TO WS-CD
           MOVE "12" TO WS-ED
           MOVE 'AB' TO WS-CD
           GOBACK.
"""
        violations = MoveTypeChecker().check(_ast(source)).violations
        assert [v.source_name.strip("'\"") for v in violations] == ["AB"]

    def test_a_file_left_open_is_reported_on_its_select(self) -> None:
        source = GROUP_PROGRAM.replace("           CLOSE IN-FILE\n", "")
        report = LintAnalyzer(["io-sequence"]).analyze(_ast(source))
        left_open = [f for f in report.findings if f.kind == "FILE_LEFT_OPEN"]
        # Every FILE_LEFT_OPEN has a line now (the STOP RUN / GOBACK it
        # reaches, else the file's SELECT), so annotations can place it.
        assert left_open and all(f.location is not None for f in left_open)

    @pytest.mark.parametrize(
        ("command", "severity"),
        [
            ("ENDBR FILE('F')", "info"),
            ("SYNCPOINT", "info"),
            ("READ FILE('F') INTO(WS-REC)", "warning"),
        ],
    )
    def test_low_risk_cics_commands_are_info(self, command, severity) -> None:
        source = f"""\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. ONL.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-REC  PIC X(80).
       PROCEDURE DIVISION.
           EXEC CICS {command} END-EXEC
           GOBACK.
"""
        report = LintAnalyzer(["sql-cics-check"]).analyze(_ast(source))
        no_resp = [f for f in report.findings if f.kind == "CICS_NO_RESP_HANDLING"]
        assert [f.severity for f in no_resp] == [severity]


# -- system copybooks ----------------------------------------------------------


class TestSystemCopybooks:
    def test_the_stand_ins_ship(self) -> None:
        assert {"DFHAID", "DFHBMSCA"} <= SYSTEM_COPYBOOKS
        assert (SYSTEM_COPYBOOK_DIR / "DFHAID.cpy").is_file()

    def test_appended_last_and_once(self) -> None:
        paths = with_system_copybooks(["cpy"])
        assert paths == ["cpy", str(SYSTEM_COPYBOOK_DIR)]
        assert with_system_copybooks(paths) == paths
        assert with_system_copybooks([]) == []

    def test_a_program_copying_dfhaid_parses(self, tmp_path) -> None:
        from cobolparser.parser import parse_cobol_with_expansion

        source = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. ONL.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       COPY DFHAID.
       COPY DFHBMSCA.
       01  WS-KEY  PIC X.
       PROCEDURE DIVISION.
           IF WS-KEY = DFHPF3 OR DFHENTER
               MOVE DFHBMPRO TO WS-KEY
           END-IF
           GOBACK.
"""
        result = parse_cobol_with_expansion(
            source, "ONL.cbl", copybook_paths=with_system_copybooks([str(tmp_path)])
        )
        assert result.ast is not None and not result.errors
        report = LintAnalyzer(["move-type-check"]).analyze(result.ast)
        assert report.findings == []


def test_a_file_open_at_the_end_of_the_text_is_reported_on_its_select() -> None:
    """With no STOP RUN / GOBACK to point at, the finding sits on the
    SELECT rather than having no line at all."""
    source = GROUP_PROGRAM.replace("           CLOSE IN-FILE\n", "").replace(
        "           GOBACK.\n", ""
    )
    report = LintAnalyzer(["io-sequence"]).analyze(_ast(source))
    left_open = [f for f in report.findings if f.kind == "FILE_LEFT_OPEN"]
    assert [f.location.line for f in left_open if f.location] == [6]
