"""Regression tests for the 2026-09-09 preprocessing/lexer review findings.

One test class per finding. Every normalize_fixed_format test runs against
both the pure-Python implementation and whichever implementation the package
exposes (the Cython accelerator when compiled, the same function otherwise).
"""

from __future__ import annotations

import os
import re
import time

import pytest

from cobolparser import (
    CobolParser,
    ErrorRecoveryMode,
    expand_copybooks,
    parse_cobol,
    parse_cobol_with_expansion,
    tokenize_cobol,
)
from cobolparser.lexer import TokenType, _CobolLexerPure
from cobolparser.preprocess import (
    _normalize_fixed_format_pure,
    normalize_fixed_format,
    preprocess_conditional_compilation,
)
from cobolparser.preprocess.copy_statement_parser import (
    CopyStatementLexer,
    normalize_continuation_lines,
)
from cobolparser.preprocess.replace_statement import _ReplaceScanner

NORMALIZERS = [
    pytest.param(_normalize_fixed_format_pure, id="pure"),
    pytest.param(normalize_fixed_format, id="package"),
]


def _prog(*body: str) -> str:
    return "\n".join(body) + "\n"


def _to_72(record: str) -> str:
    """The blanks a record stopping short of column 72 is missing -- part of
    a literal left open on it."""
    return " " * (72 - len(record))


# ---------------------------------------------------------------------------
# Finding 1 -- continuation lines must not collapse the physical line count
# ---------------------------------------------------------------------------


class TestFinding1ContinuationLinesKeepLineCount:
    SRC = _prog(
        "       IDENTIFICATION DIVISION.",  # 1
        "       PROGRAM-ID. T1.",  # 2
        "       DATA DIVISION.",  # 3
        "       WORKING-STORAGE SECTION.",  # 4
        '       01  WS-A   PIC X(30) VALUE "ABCDEFGHIJ',  # 5
        '      -    "KLMNOPQRST',  # 6
        '      -    "UVWXYZ".',  # 7
        "       01  WS-B   PIC X.",  # 8
        "       PROCEDURE DIVISION.",  # 9
        '           MOVE "X" TO WS-B.',  # 10
        "           STOP RUN.",  # 11
    )

    @pytest.mark.parametrize("normalize", NORMALIZERS)
    def test_one_output_line_per_physical_line(self, normalize):
        lines = self.SRC.splitlines()
        out = normalize(lines)
        assert out.count("\n") == len(lines)
        rows = out.split("\n")
        assert rows[4] == (
            '01  WS-A   PIC X(30) VALUE "ABCDEFGHIJ'
            + _to_72(lines[4])
            + "KLMNOPQRST"
            + _to_72(lines[5])
            + 'UVWXYZ".'
        )
        assert rows[5] == "" and rows[6] == ""
        assert rows[9] == '    MOVE "X" TO WS-B.'

    def test_statement_after_continuation_reports_physical_line(self):
        result = parse_cobol(self.SRC)
        assert not result.errors
        (move,) = result.ast.find_all_by_type("MoveStatement")
        assert move.location.line == 10

    @pytest.mark.parametrize("normalize", NORMALIZERS)
    def test_non_literal_continuation_also_keeps_count(self, normalize):
        lines = [
            "       01  WS-N PIC S9(3)V999 VALUE -9",
            "      -    99.777.",
            "       01  WS-M PIC X.",
        ]
        out = normalize(lines)
        assert out == "01  WS-N PIC S9(3)V999 VALUE -999.777.\n\n01  WS-M PIC X.\n"

    @pytest.mark.parametrize("normalize", NORMALIZERS)
    def test_orphan_continuation_is_still_one_line(self, normalize):
        lines = ["      * banner", '      -    "DEF".', "       STOP RUN."]
        out = normalize(lines)
        assert out.count("\n") == 3
        assert out.split("\n")[1] == '"DEF".'

    @pytest.mark.parametrize("normalize", NORMALIZERS)
    def test_comment_between_literal_pieces_does_not_sever_it(self, normalize):
        # Known-LOW r8: a comment line interrupting an open continued literal
        lines = [
            '       01  WS-A PIC X(20) VALUE "ABC',
            "      * interrupting comment",
            '      -    "DEF".',
        ]
        out = normalize(lines)
        assert out == '01  WS-A PIC X(20) VALUE "ABC' + _to_72(lines[0]) + 'DEF".\n\n\n'

    @pytest.mark.parametrize("normalize", NORMALIZERS)
    def test_blank_line_between_literal_pieces_does_not_sever_it(self, normalize):
        lines = ['       01  WS-A PIC X(20) VALUE "ABC', "", '      -    "DEF".']
        assert normalize(lines) == (
            '01  WS-A PIC X(20) VALUE "ABC' + _to_72(lines[0]) + 'DEF".\n\n\n'
        )

    @pytest.mark.parametrize("normalize", NORMALIZERS)
    def test_literal_open_before_trailing_comment_keeps_old_verdict(self, normalize):
        # Historically the comment closed the literal silently (the lexer
        # warns later); that must not escalate into a hard ValueError.
        lines = ['           DISPLAY "oops', "      * end of program"]
        assert normalize(lines) == '    DISPLAY "oops\n\n'

    @pytest.mark.parametrize("normalize", NORMALIZERS)
    def test_literal_open_on_last_code_line_still_raises(self, normalize):
        with pytest.raises(ValueError, match="Unterminated string literal"):
            normalize(['           DISPLAY "oops'])

    def test_comment_tokens_after_continuation_keep_physical_lines(self):
        src = _prog(
            "       IDENTIFICATION DIVISION.",  # 1
            "       PROGRAM-ID. T1C.",  # 2
            "       DATA DIVISION.",  # 3
            "       WORKING-STORAGE SECTION.",  # 4
            '       01  WS-A   PIC X(20) VALUE "ABC',  # 5
            '      -    "DEF".',  # 6
            "      * AFTER CONTINUATION",  # 7
            "       PROCEDURE DIVISION.",  # 8
            "           STOP RUN.",  # 9
        )
        comments = [t for t in tokenize_cobol(src) if t.type == TokenType.COMMENT]
        assert [(t.location.line, t.value) for t in comments] == [
            (7, "* AFTER CONTINUATION")
        ]

    def test_expansion_source_map_agrees_with_normalizer(self, tmp_path):
        (tmp_path / "CPY1.cpy").write_text("       01  CPY-ITEM PIC X.\n")
        src = _prog(
            "       IDENTIFICATION DIVISION.",  # 1
            "       PROGRAM-ID. T1D.",  # 2
            "       DATA DIVISION.",  # 3
            "       WORKING-STORAGE SECTION.",  # 4
            "       COPY CPY1.",  # 5
            '       01  WS-A   PIC X(10) VALUE "ABC',  # 6
            '      -    "DEF".',  # 7
            "       PROCEDURE DIVISION.",  # 8
            "           STOP RUN.",  # 9
        )
        result = parse_cobol_with_expansion(src, "t1d.cbl", [str(tmp_path)])
        assert not result.errors
        (stop,) = result.ast.find_all_by_type("StopStatement")
        source_map = result.expansion_source_map
        assert source_map is not None
        # The expander merged lines 6-7 itself, so the expanded text is one
        # line shorter; the map must still lead the STOP back to line 9.
        assert source_map[stop.location.line] == ("t1d.cbl", 9)


# ---------------------------------------------------------------------------
# Finding 2 -- `*>` inline comment holding an apostrophe
# ---------------------------------------------------------------------------


class TestFinding2InlineCommentApostrophe:
    SRC = _prog(
        "       IDENTIFICATION DIVISION.",
        "       PROGRAM-ID. T2.",
        "       PROCEDURE DIVISION.",
        "           MOVE 1 TO WS-A.",
        "           STOP RUN. *> that's all folks",
    )

    @pytest.mark.parametrize("normalize", NORMALIZERS)
    def test_normalize_does_not_raise(self, normalize):
        out = normalize(self.SRC.splitlines())
        assert out.endswith("STOP RUN. *> that's all folks\n")

    @pytest.mark.parametrize("normalize", NORMALIZERS)
    def test_quote_inside_open_literal_is_not_a_comment(self, normalize):
        lines = ['       01  WS-A PIC X(9) VALUE "A *> B', '      -    "C".']
        assert normalize(lines) == (
            '01  WS-A PIC X(9) VALUE "A *> B' + _to_72(lines[0]) + 'C".\n\n'
        )

    def test_parses_under_both_recovery_modes(self):
        for mode in (ErrorRecoveryMode.FAIL_FAST, ErrorRecoveryMode.COLLECT_ALL):
            result = parse_cobol(self.SRC, error_recovery=mode)
            assert result.ast is not None
            assert result.errors == []


# ---------------------------------------------------------------------------
# Finding 3 -- free-form programs and tab-indented copybooks through expansion
# ---------------------------------------------------------------------------


class TestFinding3ExpanderFormatDetectionAndTabs:
    FREE = _prog(
        "IDENTIFICATION DIVISION.",
        "PROGRAM-ID. FF2.",
        "DATA DIVISION.",
        "WORKING-STORAGE SECTION.",
        "           COPY FFCPY.",
        "01 WS-A PIC X.",
        "PROCEDURE DIVISION.",
        "    MOVE 'X' TO WS-A.",
        "    STOP RUN.",
    )

    def test_free_form_program_is_not_sliced_at_column_7(self, tmp_path):
        (tmp_path / "FFCPY.cpy").write_text("01 CPY-ITEM PIC X.\n")
        exp = expand_copybooks(self.FREE, [str(tmp_path)])
        rows = exp.expanded_source.split("\n")
        assert rows[0] == "IDENTIFICATION DIVISION."
        assert rows[4] == "01 CPY-ITEM PIC X."
        result = parse_cobol_with_expansion(self.FREE, "ff2.cbl", [str(tmp_path)])
        assert result.success, result.errors
        names = [it.name for it in result.ast.find_all_by_type("CobolDataItem")]
        assert names == ["CPY-ITEM", "WS-A"]

    def test_flush_left_copy_in_free_form_is_expanded(self, tmp_path):
        (tmp_path / "FFCPY.cpy").write_text("01 CPY-ITEM PIC X.\n")
        src = self.FREE.replace("           COPY FFCPY.", "COPY FFCPY.")
        result = parse_cobol_with_expansion(src, "ff3.cbl", [str(tmp_path)])
        assert result.success
        assert result.warnings == []
        names = [it.name for it in result.ast.find_all_by_type("CobolDataItem")]
        assert names == ["CPY-ITEM", "WS-A"]

    def test_tab_indented_copybook_in_fixed_program(self, tmp_path):
        (tmp_path / "TABBED.cpy").write_text(
            "\t01  TAB-REC.\n\t    05  TAB-A   PIC X(5).\n\t    05  TAB-B   PIC 9(3).\n"
        )
        src = _prog(
            "       IDENTIFICATION DIVISION.",
            "       PROGRAM-ID. TA.",
            "       DATA DIVISION.",
            "       WORKING-STORAGE SECTION.",
            "       COPY TABBED.",
            "       PROCEDURE DIVISION.",
            "           STOP RUN.",
        )
        exp = expand_copybooks(src, [str(tmp_path)])
        assert "\t" not in exp.expanded_source
        result = parse_cobol_with_expansion(src, "ta.cbl", [str(tmp_path)])
        assert not result.errors
        names = [it.name for it in result.ast.find_all_by_type("CobolDataItem")]
        assert names == ["TAB-REC", "TAB-A", "TAB-B"]

    def test_free_form_member_in_fixed_program_gets_indicator_column(self, tmp_path):
        (tmp_path / "FFCPY.cpy").write_text("01 CPY-ITEM PIC X.\n")
        src = _prog(
            "       IDENTIFICATION DIVISION.",
            "       PROGRAM-ID. TF.",
            "       DATA DIVISION.",
            "       WORKING-STORAGE SECTION.",
            "       COPY FFCPY.",
            "       PROCEDURE DIVISION.",
            "           STOP RUN.",
        )
        result = parse_cobol_with_expansion(src, "tf.cbl", [str(tmp_path)])
        assert not result.errors
        names = [it.name for it in result.ast.find_all_by_type("CobolDataItem")]
        assert names == ["CPY-ITEM"]


# ---------------------------------------------------------------------------
# Finding 4 -- expansion path corrupts continued literals
# ---------------------------------------------------------------------------


class TestFinding4ExpanderContinuedLiterals:
    def _value(self, result, name):
        for item in result.ast.find_all_by_type("CobolDataItem"):
            if item.name == name:
                return item.value_clause
        raise AssertionError(name)

    def test_open_literal_keeps_trailing_blanks(self, tmp_path):
        (tmp_path / "CPY1.cpy").write_text("       01  CPY-ITEM PIC X.\n")
        src = _prog(
            "       IDENTIFICATION DIVISION.",
            "       PROGRAM-ID. T4.",
            "       DATA DIVISION.",
            "       WORKING-STORAGE SECTION.",
            "       COPY CPY1.",
            '       01  WS-A   PIC X(10) VALUE "ABC   ',
            '      -    "DEF".',
            "       PROCEDURE DIVISION.",
            "           STOP RUN.",
        )
        direct = parse_cobol(src.replace("       COPY CPY1.\n", ""))
        expanded = parse_cobol_with_expansion(src, "t4.cbl", [str(tmp_path)])
        opener = '       01  WS-A   PIC X(10) VALUE "ABC   '
        want = '"ABC   ' + _to_72(opener) + 'DEF"'
        assert self._value(direct, "WS-A") == want
        assert self._value(expanded, "WS-A") == want

    def test_quote_state_not_quote_parity(self):
        # An apostrophe literal holding a double quote is still open on the
        # first line -- counting quotes said otherwise.
        opener = "           DISPLAY 'IT\"S"
        src = opener + '\n      -    "MORE".\n'
        out = normalize_continuation_lines(src)
        assert out == opener + _to_72(opener) + '"MORE".\n'
        # ...and a doubled quote is an escape, not a close.
        opener = "           DISPLAY 'IT''S "
        src = opener + "\n      -    'MORE'.\n"
        assert normalize_continuation_lines(src) == (
            opener + _to_72(opener) + "MORE'.\n"
        )

    def test_crlf_source_keeps_the_literal_whole(self, tmp_path):
        (tmp_path / "LFCPY.cpy").write_text("       01  LF-ITEM PIC X.\n")
        crlf = (
            "       IDENTIFICATION DIVISION.\r\n"
            "       PROGRAM-ID. TF.\r\n"
            "       DATA DIVISION.\r\n"
            "       WORKING-STORAGE SECTION.\r\n"
            "       COPY LFCPY.\r\n"
            "       01  WS-A PIC X(5) VALUE 'AB\r\n"
            "      -    'CD'.\r\n"
            "       PROCEDURE DIVISION.\r\n"
            "           STOP RUN.\r\n"
        )
        result = parse_cobol_with_expansion(crlf, "tf.cbl", [str(tmp_path)])
        assert not result.errors
        opener = "       01  WS-A PIC X(5) VALUE 'AB"
        assert self._value(result, "WS-A") == '"AB' + _to_72(opener) + 'CD"'


# ---------------------------------------------------------------------------
# Finding 5 -- COPY / REPLACE inside a `*>` inline comment
# ---------------------------------------------------------------------------


class TestFinding5CopyInInlineComment:
    def test_copy_in_inline_comment_is_not_a_statement(self):
        src = "       01  WS-X PIC X. *> was COPY OLDBOOK. before\n       COPY REAL.\n"
        stmts = CopyStatementLexer(src).tokenize_copy_statements()
        assert [s.member_name for s in stmts] == ["REAL"]

    def test_expansion_ignores_commented_copy(self, tmp_path):
        (tmp_path / "REAL.cpy").write_text("       01  REAL-ITEM PIC X.\n")
        (tmp_path / "OLD.cpy").write_text("       01  OLD-ITEM PIC X.\n")
        src = _prog(
            "       IDENTIFICATION DIVISION.",
            "       PROGRAM-ID. T6.",
            "       DATA DIVISION.",
            "       WORKING-STORAGE SECTION.",
            "       COPY REAL.",
            "       01  WS-X PIC X. *> was COPY OLDBOOK. before",
            "       01  WS-Y PIC X. *> replaced COPY OLD.",
            "       PROCEDURE DIVISION.",
            "           STOP RUN.",
        )
        exp = expand_copybooks(src, [str(tmp_path)])
        assert [os.path.basename(p) for p in exp.included_copybooks] == ["REAL.cpy"]
        assert "OLD-ITEM" not in exp.expanded_source
        assert "*> was COPY OLDBOOK. before" in exp.expanded_source

    def test_replace_in_inline_comment_is_not_a_statement(self):
        src = "       MOVE A TO B. *> REPLACE ==A== BY ==B==.\n       REPLACE ==X== BY ==Y==.\n"
        stmts = _ReplaceScanner(src).scan()
        assert len(stmts) == 1
        assert src[stmts[0].start :].lstrip().startswith("REPLACE ==X==")


# ---------------------------------------------------------------------------
# Finding 6 -- file cache never invalidated
# ---------------------------------------------------------------------------


class TestFinding6FileCacheInvalidation:
    def test_edited_copybook_is_re_read(self, tmp_path):
        member = tmp_path / "REC.cpy"
        member.write_text("       01  REC-V1 PIC X.\n")
        src = "       COPY REC.\n"
        assert "REC-V1" in expand_copybooks(src, [str(tmp_path)]).expanded_source
        time.sleep(0.02)
        member.write_text("       01  REC-V2 PIC X(99).\n")
        # Force a distinct mtime even on coarse-grained filesystems.
        stat = member.stat()
        os.utime(member, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000))
        assert "REC-V2" in expand_copybooks(src, [str(tmp_path)]).expanded_source


# ---------------------------------------------------------------------------
# Finding 7 -- REPLACING text used as an re template
# ---------------------------------------------------------------------------


class TestFinding7ReplacingBackslash:
    @pytest.mark.parametrize(
        "replacement",
        ["'C:\\TEMP\\1'", "'\\g<0>'", "'A\\'"],
    )
    def test_replacement_is_literal_text(self, tmp_path, replacement):
        (tmp_path / "PATHS.cpy").write_text(
            "       01  WS-PATH PIC X(20) VALUE :DIR:.\n"
        )
        src = _prog(
            "       IDENTIFICATION DIVISION.",
            "       PROGRAM-ID. T5.",
            "       DATA DIVISION.",
            "       WORKING-STORAGE SECTION.",
            f"       COPY PATHS REPLACING ==:DIR:== BY =={replacement}==.",
            "       PROCEDURE DIVISION.",
            "           STOP RUN.",
        )
        exp = expand_copybooks(src, [str(tmp_path)])
        (line,) = [ln for ln in exp.expanded_source.splitlines() if "WS-PATH" in ln]
        assert line.strip() == f"01  WS-PATH PIC X(20) VALUE {replacement}."


# ---------------------------------------------------------------------------
# Finding 8 -- directives in sequence-numbered programs; DEFINE suffixes
# ---------------------------------------------------------------------------


class TestFinding8ConditionalDirectives:
    SRC = _prog(
        "000100 IDENTIFICATION DIVISION.",
        "000200 PROGRAM-ID. T9.",
        "000300 PROCEDURE DIVISION.",
        "000400     >>IF DEBUG IS DEFINED",
        "000500     DISPLAY 'DEBUG'.",
        "000600     >>END-IF",
        "000700     STOP RUN.",
    )

    def test_sequence_numbered_directives_are_honored(self):
        warnings: list[str] = []
        out = preprocess_conditional_compilation(self.SRC, {}, warnings=warnings)
        assert "DISPLAY" not in out
        assert ">>IF" not in out
        assert warnings == []
        assert out.count("\n") == self.SRC.count("\n") - 1
        out = preprocess_conditional_compilation(self.SRC, {"DEBUG": "TRUE"})
        assert "DISPLAY 'DEBUG'" in out

    def test_expansion_path_honors_them_too(self):
        exp = expand_copybooks(self.SRC, [], process_conditionals=True)
        assert "DISPLAY" not in exp.expanded_source
        assert exp.statistics.warnings == []

    def test_define_override_suffix_is_not_part_of_the_value(self):
        src = ">>DEFINE LVL AS 2 OVERRIDE\n>>IF LVL = 2\n       DISPLAY 'TWO'.\n>>END-IF\n"
        warnings: list[str] = []
        out = preprocess_conditional_compilation(src, warnings=warnings)
        assert out == "\n\n       DISPLAY 'TWO'.\n"
        assert warnings == []

    def test_define_without_as_and_bare_override(self):
        src = ">>DEFINE LVL 3\n>>DEFINE FLAG OVERRIDE\n>>IF LVL = 3 AND FLAG\n       DISPLAY 'Y'.\n>>END-IF\n"
        out = preprocess_conditional_compilation(src)
        assert "DISPLAY 'Y'" in out

    def test_define_off_undefines(self):
        src = ">>DEFINE DEBUG AS OFF\n>>IF DEBUG IS DEFINED\n       DISPLAY 'D'.\n>>END-IF\n"
        out = preprocess_conditional_compilation(src, {"DEBUG": "TRUE"})
        assert "DISPLAY" not in out

    def test_define_parameter_takes_caller_value(self):
        src = ">>DEFINE LVL AS PARAMETER\n>>IF LVL = 7\n       DISPLAY 'P'.\n>>END-IF\n"
        assert "DISPLAY" in preprocess_conditional_compilation(src, {"LVL": 7})
        warnings: list[str] = []
        out = preprocess_conditional_compilation(src, {}, warnings=warnings)
        assert "DISPLAY" not in out
        assert any("PARAMETER" in w for w in warnings)


# ---------------------------------------------------------------------------
# Finding 9 -- CobolParser().parse() on free-form source
# ---------------------------------------------------------------------------


class TestFinding9CobolParserFreeForm:
    FREE = _prog(
        "IDENTIFICATION DIVISION.",
        "PROGRAM-ID. FF1.",
        "DATA DIVISION.",
        "WORKING-STORAGE SECTION.",
        "01 WS-A PIC X.",
        "PROCEDURE DIVISION.",
        "    MOVE 'X' TO WS-A.",
        "    STOP RUN.",
    )

    def test_default_parser_matches_parse_cobol(self):
        result = CobolParser().parse(self.FREE)
        assert result.success, [str(e) for e in result.errors]
        assert CobolParser(free_form=True).parse(self.FREE).success
        assert parse_cobol(self.FREE).success
        (move,) = result.ast.find_all_by_type("MoveStatement")
        assert move.location.line == 7


# ---------------------------------------------------------------------------
# Finding 10 -- comment attribution after a full-width blank code line
# ---------------------------------------------------------------------------


class TestFinding10CommentTokensAfterFullWidthBlankLine:
    def test_comments_keep_their_lines(self):
        src = _prog(
            "       IDENTIFICATION DIVISION.",  # 1
            "       PROGRAM-ID. T3.",  # 2
            " " * 72,  # 3 full-width blank code line
            "      * FIRST COMMENT",  # 4
            "       PROCEDURE DIVISION.",  # 5
            "      * SECOND COMMENT",  # 6
            "           STOP RUN.",  # 7
        )
        comments = [t for t in tokenize_cobol(src) if t.type == TokenType.COMMENT]
        assert [(t.location.line, t.value) for t in comments] == [
            (4, "* FIRST COMMENT"),
            (6, "* SECOND COMMENT"),
        ]


# ---------------------------------------------------------------------------
# Finding 11 -- str input to normalize_fixed_format; typed literal warning
# ---------------------------------------------------------------------------


class TestFinding11Minor:
    @pytest.mark.parametrize("normalize", NORMALIZERS)
    def test_normalize_accepts_a_whole_string(self, normalize):
        src = "       IDENTIFICATION DIVISION.\n       PROGRAM-ID. TD.\n"
        assert normalize(src) == "IDENTIFICATION DIVISION.\nPROGRAM-ID. TD.\n"
        assert normalize(src) == normalize(src.splitlines())

    def test_unterminated_typed_literal_warns_in_free_form(self):
        plain = _CobolLexerPure('MOVE "AB TO X', free_form=True)
        plain.tokenize()
        typed = _CobolLexerPure('MOVE X"AB TO X', free_form=True)
        typed.tokenize()
        assert typed.get_errors() == []
        assert len(typed.get_warnings()) == 1
        assert re.match(
            r"Unterminated string literal at line 1, column \d+",
            typed.get_warnings()[0],
        )
        assert (
            plain.get_warnings()[0].split(":")[1]
            == typed.get_warnings()[0].split(":")[1]
        )
