"""Regression tests: defects found by the 2026-10-08 bug hunt.

1. ``PIC X(3) VALUES ARE 'ABC'`` / ``PIC X(3) FOO``: a word the picture
   scan's terminator list did not know was glued onto the pattern
   (``X(3)VALUES`` sized 0, ``X(3)FOO`` sized 1). A PICTURE character-string
   has no embedded spaces, so a same-line word after a gap ends the scan
   and is reported as an unparsed token instead.
"""

from cobolparser import parse_cobol

HEADER = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. REG1008.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
"""

FOOTER = """\
       PROCEDURE DIVISION.
       MAIN.
           GOBACK.
"""


def _item(decl: str, name: str = "M"):
    result = parse_cobol(HEADER + "       01  REC.\n           " + decl + "\n" + FOOTER)
    assert result.errors == []
    items = [i for i in result.ast.find_all_by_type("CobolDataItem") if i.name == name]
    assert len(items) == 1, items
    return items[0], result.warnings


class TestPictureScanStopsAtAGap:
    def test_unknown_word_after_a_space_is_not_picture(self):
        item, warnings = _item("05  M PIC X(3) FOO.")
        assert item.picture_clause.pattern == "X(3)"
        assert item.calculate_size() == 3
        assert any("FOO" in str(w) for w in warnings)

    def test_values_are_on_an_elementary_item(self):
        item, warnings = _item("05  M PIC X(3) VALUES ARE 'ABC'.")
        assert item.picture_clause.pattern == "X(3)"
        assert item.calculate_size() == 3
        assert any("VALUES" in str(w) for w in warnings)

    def test_edited_picture_with_symbol_tokens_is_whole(self):
        item, warnings = _item("05  M PIC $$,$$9.99CR.")
        assert item.picture_clause.pattern == "$$,$$9.99CR"
        assert item.calculate_size() == 11
        assert warnings == []

    def test_continued_picture_keeps_both_halves(self):
        src = HEADER + ("       01  M PIC 9(3)\n" "      -    V99.\n") + FOOTER
        result = parse_cobol(src)
        item = [
            i for i in result.ast.find_all_by_type("CobolDataItem") if i.name == "M"
        ][0]
        assert item.picture_clause.pattern == "9(3)V99"
        assert item.calculate_size() == 5

    def test_picture_on_the_next_line_still_tolerated(self):
        src = HEADER + "       01  M PIC\n              X(4).\n" + FOOTER
        result = parse_cobol(src)
        item = [
            i for i in result.ast.find_all_by_type("CobolDataItem") if i.name == "M"
        ][0]
        assert item.picture_clause.pattern == "X(4)"


# ---------------------------------------------------------------------------
# 2. Abbreviated combined conditions nested under a further AND/OR are pinned
#    in tests/regression/test_review_2026_09_09_parser.py
#    (TestFinding08ConditionTrees).
# ---------------------------------------------------------------------------


def _program(ws: str, proc: str, extra_header: str = "") -> str:
    return (
        "       IDENTIFICATION DIVISION.\n"
        "       PROGRAM-ID. REG1008.\n"
        + extra_header
        + "       DATA DIVISION.\n"
        + ws
        + "       PROCEDURE DIVISION.\n"
        + proc
    )


class TestRecursionRiskEscape:
    """3. A GO TO loop whose body holds an IF/EVALUATE was graded MEDIUM
    ("has another way out"): the synthetic IF_BRANCH / EVALUATE_BRANCH edges
    leave the cycle set (their target is a branch node), and counted as an
    escape. Only a transfer to a paragraph outside the cycle, or a
    program-terminating statement, is one."""

    def _risks(self, body: str):
        from cobolparser import RecursionRiskAnalyzer

        src = _program(
            "       WORKING-STORAGE SECTION.\n       01  WS-X PIC X.\n",
            "       MAIN.\n           GO TO L1.\n       L1.\n" + body,
        )
        result = parse_cobol(src)
        assert result.errors == []
        return [r.to_dict() for r in RecursionRiskAnalyzer().analyze(result.ast).risks]

    def test_if_inside_the_loop_is_not_an_escape(self):
        risks = self._risks(
            "           IF WS-X = 'Y' DISPLAY 'HI' END-IF\n           GO TO L1.\n"
        )
        assert [r["severity"] for r in risks] == ["HIGH"]
        assert risks[0]["has_escape"] is False

    def test_evaluate_inside_the_loop_is_not_an_escape(self):
        risks = self._risks(
            "           EVALUATE WS-X\n              WHEN 'A' DISPLAY 'A'\n"
            "           END-EVALUATE\n           GO TO L1.\n"
        )
        assert [r["severity"] for r in risks] == ["HIGH"]

    def test_go_to_out_of_the_loop_is_an_escape(self):
        risks = self._risks(
            "           IF WS-X = 'Y' GO TO L2 END-IF\n           GO TO L1.\n"
            "       L2.\n           STOP RUN.\n"
        )
        assert [r["severity"] for r in risks] == ["MEDIUM"]
        assert risks[0]["has_escape"] is True


UNUSED_WS = """\
       FILE SECTION.
       FD  OUT-F.
       01  OUT-REC PIC X(80).
       WORKING-STORAGE SECTION.
       01  WS-T PIC 9.
       01  WS-ADV PIC 9.
       01  WS-ZERO PIC 9.
       01  WS-G1.
           05 WS-A PIC 9.
           05 WS-B PIC 9.
       01  WS-G2.
           05 WS-A PIC 9.
           05 WS-C PIC 9.
       01  WS-G3.
           05 WS-D PIC 9.
       01  WS-DOC PIC X(100).
       01  WS-GRP.
           05 WS-F1 PIC X.
       01  WS-JGRP.
           05 WS-J1 PIC X.
       01  WS-UNUSED PIC X.
       01  1ST-NAME PIC X(5).
       01  2ND-NAME PIC X(5).
"""
UNUSED_ENV = """\
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT OUT-F ASSIGN TO OUTFILE.
"""
UNUSED_PROC = """\
       MAIN.
           PERFORM P2 WS-T TIMES
           WRITE OUT-REC AFTER ADVANCING WS-ADV LINES
           INITIALIZE WS-G3 REPLACING NUMERIC DATA BY WS-ZERO
           MOVE CORRESPONDING WS-G1 TO WS-G2
           XML GENERATE WS-DOC FROM WS-GRP
           JSON PARSE WS-DOC INTO WS-JGRP
           MOVE 1ST-NAME TO 2ND-NAME
           GOBACK.
       P2.
           DISPLAY 'P2'.
"""


class TestUnusedVariableReferences:
    """4. References the unused-variable analyzer did not see: a ``PERFORM
    ... n TIMES`` count, a ``WRITE ... ADVANCING n LINES`` count, an
    ``INITIALIZE ... REPLACING ... BY item`` value, the same-named
    subordinates of a ``CORRESPONDING`` pair, the subordinates of an ``XML
    GENERATE ... FROM`` / ``JSON PARSE ... INTO`` group, and digit-led user
    words (``1ST-NAME``), which the identifier tokenizer cut to ``ST-NAME``."""

    def _unused(self):
        from cobolparser import UnusedVariableAnalyzer

        result = parse_cobol(_program(UNUSED_WS, UNUSED_PROC, UNUSED_ENV))
        assert result.errors == []
        report = UnusedVariableAnalyzer().analyze(result.ast)
        return sorted(item.name for item in report.unused_items), result

    def test_only_the_truly_unused_items_are_reported(self):
        unused, _ = self._unused()
        # WS-B / WS-C have no same-named twin, so CORRESPONDING skips them;
        # WS-D sits under an INITIALIZE target, which (like MOVE SPACES TO a
        # group) never names its fields.
        assert unused == ["WS-B", "WS-C", "WS-D", "WS-UNUSED"]

    def test_digit_led_names_resolve_in_xref(self):
        from cobolparser.analysis.xref import XrefAnalyzer

        _, result = self._unused()
        report = XrefAnalyzer().analyze(result.ast).to_dict()
        assert report["undefined"] in (None, [])
        by_name = {e["name"]: e for e in report["entries"]}
        assert by_name["1ST-NAME"]["references"]
        assert by_name["2ND-NAME"]["references"]
        assert any(
            r["role"] == "read" for r in by_name["WS-ADV"]["references"]
        ), by_name["WS-ADV"]


class TestIdentifierTokenRegex:
    def test_digit_led_word_and_float_literal(self):
        from cobolparser.analysis._names import IDENTIFIER_TOKEN_RE

        assert IDENTIFIER_TOKEN_RE.findall("MOVE 1ST-NAME TO 2ND-NAME") == [
            "MOVE",
            "1ST-NAME",
            "TO",
            "2ND-NAME",
        ]
        # ``5E`` inside a floating-point literal is not a word; a bare
        # number is not an identifier.
        assert IDENTIFIER_TOKEN_RE.findall("COMPUTE X = 1.5E+3 * 100") == [
            "COMPUTE",
            "X",
        ]


class TestCopybookExpansionLineEndings:
    """5. ``copy_statement_parser`` split on ``\\n`` only, so a bare-CR
    (``\\r``) source was one 72-column "record" and its COPY was silently
    not expanded. 6. A copybook wrapping alternative entries in ``>>IF`` /
    ``>>ELSE`` / ``>>END-IF`` had each entry reported as missing its period:
    the validator joined the directive line onto the entry."""

    def test_bare_cr_source_expands_its_copybook(self, tmp_path):
        from cobolparser.preprocess.copybook_expander import (
            parse_cobol_with_expansion,
        )

        (tmp_path / "REC.cpy").write_text("       01 REC.\n           05 R1 PIC X.\n")
        src = "\r".join(
            [
                "       IDENTIFICATION DIVISION.",
                "       PROGRAM-ID. T.",
                "       DATA DIVISION.",
                "       WORKING-STORAGE SECTION.",
                "       COPY REC.",
                "       PROCEDURE DIVISION.",
                "       MAIN.",
                "           DISPLAY R1.",
                "",
            ]
        )
        result = parse_cobol_with_expansion(
            src, "m.cbl", copybook_paths=[str(tmp_path)], process_conditionals=False
        )
        assert [i.name for i in result.ast.find_all_by_type("CobolDataItem")] == [
            "REC",
            "R1",
        ]
        assert not any("not expanded" in str(w) for w in result.warnings)

    def test_conditional_directives_in_a_copybook_are_not_entries(self, tmp_path):
        from cobolparser.preprocess.copybook_expander import (
            parse_cobol_with_expansion,
        )

        (tmp_path / "COND.cpy").write_text(
            "       01 COND.\n"
            "      >>IF DBG DEFINED\n"
            "           05 CO-DBG PIC X.\n"
            "      >>ELSE\n"
            "           05 CO-REL PIC X.\n"
            "      >>END-IF\n"
        )
        src = _program(
            "       WORKING-STORAGE SECTION.\n       COPY COND.\n",
            "       MAIN.\n           GOBACK.\n",
        )
        result = parse_cobol_with_expansion(
            src, "m.cbl", copybook_paths=[str(tmp_path)]
        )
        assert result.warnings == []
        assert [i.name for i in result.ast.find_all_by_type("CobolDataItem")] == [
            "COND",
            "CO-REL",
        ]


class TestSignedNationalWidth:
    """7. ``PIC S9(5) USAGE NATIONAL`` with no SIGN clause was 10 bytes: a
    national decimal item cannot hold an overpunched sign, so IBM assumes
    SIGN IS TRAILING SEPARATE CHARACTER and the sign costs 2 bytes."""

    def test_implicit_separate_sign(self):
        from cobolparser._storage import storage_size

        implicit = storage_size(
            "NATIONAL", picture_size=5, total_digits=5, is_signed=True
        )
        explicit = storage_size(
            "NATIONAL",
            picture_size=5,
            total_digits=5,
            is_signed=True,
            sign_clause="TRAILING SEPARATE",
        )
        unsigned = storage_size("NATIONAL", picture_size=5, total_digits=5)
        assert (implicit, explicit, unsigned) == (12, 12, 10)

    def test_data_items_offsets_follow(self):
        from cobolparser.generators.data.layout_offsets import (
            compute_program_data_items,
        )

        src = _program(
            "       WORKING-STORAGE SECTION.\n"
            "       01  R.\n"
            "           05 J PIC S9(5) USAGE NATIONAL.\n"
            "           05 K PIC X.\n",
            "       MAIN.\n           GOBACK.\n",
        )
        result = parse_cobol(src)
        items = compute_program_data_items(result.ast)
        flat = (
            {
                i["name"]: i
                for sec in items.get("sections", items.get("records", []))
                for i in (sec.get("items") or sec.get("data_items") or [])
            }
            if isinstance(items, dict)
            else {}
        )
        if "K" in flat:
            assert flat["K"]["byte_offset"] == 12
        else:
            text = str(items)
            assert "12" in text


class TestJclDdMapProgramFilter:
    """8. ``cobol-parser jcl --dd-map --program NAME`` ignored ``--program``
    and listed every step's DDs; 9. an omitted positional sub-parameter
    (``DISP=(OLD,,DELETE)``) was dropped from ``positional``, shifting the
    abnormal disposition into the normal slot (pinned in test_jcl.py)."""

    JCL = (
        "//J JOB A\n//S1 EXEC PGM=P\n//D1 DD DSN=X,DISP=SHR\n"
        "//S2 EXEC PGM=Q\n//D2 DD DSN=Y,DISP=SHR\n//\n"
    )

    def _dd_map(self, tmp_path, capsys, monkeypatch, *extra):
        import json

        from cobolparser.cli.parse import main

        path = tmp_path / "j.jcl"
        path.write_text(self.JCL)
        monkeypatch.setattr(
            "sys.argv", ["cobol-parser", "jcl", str(path), "--dd-map", *extra]
        )
        try:
            main()
        except SystemExit as exc:
            assert exc.code in (0, None)
        return json.loads(capsys.readouterr().out)["dd_map"]

    def test_dd_map_is_filtered_by_program(self, tmp_path, capsys, monkeypatch):
        assert self._dd_map(tmp_path, capsys, monkeypatch, "--program", "Q") == {
            "D2": ["Y"]
        }

    def test_dd_map_without_program_is_unfiltered(self, tmp_path, capsys, monkeypatch):
        assert self._dd_map(tmp_path, capsys, monkeypatch) == {
            "D1": ["X"],
            "D2": ["Y"],
        }

    def test_module_is_runnable(self):
        import subprocess
        import sys

        proc = subprocess.run(
            [sys.executable, "-m", "cobolparser.cli.parse", "le-info", "CEEDAYS"],
            capture_output=True,
            text=True,
            check=False,
        )
        assert proc.returncode == 0
        assert "CEEDAYS" in proc.stdout
