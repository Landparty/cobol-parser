"""Regression pins for the 2026-09-17 preprocessing audit.

Nine defects in the text-manipulation stages that sit in front of the lexer
(record splitting, fixed-format continuation, COPY ... REPLACING, REPLACE,
``>>IF`` and EBCDIC copybook decoding). Each test reproduces the original
report and asserts the IBM Enterprise COBOL outcome. See .okf/log.md
(2026-09-17) for the write-up.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from cobolparser import parse_cobol
from cobolparser._lines import split_source_lines
from cobolparser.preprocess import (
    expand_copybooks,
    normalize_fixed_format,
    preprocess_conditional_compilation,
    validate_copybook_content,
)
from cobolparser.preprocess.copy_statement_parser import apply_replacing_clauses
from cobolparser.preprocess.copybook_expander import convert_to_utf8
from cobolparser.preprocess.models import ReplacingClause
from cobolparser.preprocess.replace_statement import apply_replace_statements

FIXED_HEADER = (
    "       IDENTIFICATION DIVISION.\n"
    "       PROGRAM-ID. AUDIT.\n"
    "       DATA DIVISION.\n"
    "       WORKING-STORAGE SECTION.\n"
    "       01 X PIC X(10).\n"
    "       01 WS-COUNT PIC 9(3).\n"
    "       PROCEDURE DIVISION.\n"
)


def _statement_lines(source: str) -> list[int]:
    result = parse_cobol(source, filename="audit.cbl")
    assert result.success, result.errors
    return [s.location.line for s in result.ast.get_all_statements()]


# --------------------------------------------------------------------------
# 1. Only a record boundary is a line: FF / NEL inside a record must not
#    shift every later location.line.


class TestRecordOnlyLineSplitting:
    def test_split_source_lines_matches_splitlines_on_real_terminators(self):
        assert split_source_lines("") == []
        assert split_source_lines("a") == ["a"]
        assert split_source_lines("a\n") == ["a"]
        assert split_source_lines("a\n\n") == ["a", ""]
        assert split_source_lines("a\r\nb\rc\nd") == ["a", "b", "c", "d"]
        assert split_source_lines("a\r\nb\n", keepends=True) == ["a\r\n", "b\n"]
        assert split_source_lines("a\nb", keepends=True) == ["a\n", "b"]

    @pytest.mark.parametrize("separator", ["\x0c", "\x85", "\x0b", "\x1c", "\u2028"])
    def test_other_unicode_line_boundaries_stay_inside_the_record(self, separator):
        assert split_source_lines(f"a{separator}b\nc") == [f"a{separator}b", "c"]

    @pytest.mark.parametrize("separator", ["\x0c", "\x85"])
    def test_page_eject_in_a_comment_does_not_shift_line_numbers(self, separator):
        source = (
            "       IDENTIFICATION DIVISION.\n"
            "       PROGRAM-ID. T.\n"
            f"      *{separator}\n"
            "       PROCEDURE DIVISION.\n"
            "           STOP RUN.\n"
        )
        assert _statement_lines(source) == [5]


# --------------------------------------------------------------------------
# 2. EBCDIC copybooks whose records end in NL (0x15).


class TestEbcdicNewlineRecords:
    COPYBOOK = (
        "       01 EBC-REC.\n"
        "           05 EBC-A PIC X(10).\n"
        "           05 EBC-B PIC 9(5).\n"
    )

    def test_nl_records_decode_to_one_line_each(self):
        raw = self.COPYBOOK.replace("\n", "\x85").encode("cp037")
        assert b"\x15" in raw  # cp037 maps U+0085 to the NL byte
        assert convert_to_utf8(raw, "cp037") == self.COPYBOOK
        assert convert_to_utf8(raw, "cp037", errors="strict") == self.COPYBOOK

    def test_cr_nl_pair_is_one_record_boundary(self):
        raw = self.COPYBOOK.replace("\n", "\r\x85").encode("cp037")
        assert convert_to_utf8(raw, "cp037") == self.COPYBOOK

    def test_ascii_text_is_never_rewritten(self):
        assert convert_to_utf8("a\x85b\n".encode("latin-1"), "latin-1") == "a\x85b\n"

    def test_nl_record_copybook_expands_whole(self, tmp_path: Path):
        member = tmp_path / "EBCNL.cpy"
        member.write_bytes(self.COPYBOOK.replace("\n", "\x85").encode("cp037"))
        expansion = expand_copybooks("       COPY EBCNL.\n", copybook_paths=[tmp_path])
        assert "EBC-B PIC 9(5)." in expansion.expanded_source
        assert expansion.expanded_source.count("\n") == 3


# --------------------------------------------------------------------------
# 3. The expander validates STRIPPED content (indicator at index 0).


class TestContinuedLiteralQuoteDiscount:
    RAW = (
        "       01 REC.\n"
        "           05 A PIC X(30) VALUE 'ABC\n"
        "      -    'DEF'.\n"
    )

    def test_raw_source_position(self):
        assert validate_copybook_content(self.RAW, "CONT.cpy") == []

    def test_stripped_source_position(self):
        stripped = "\n".join(line[6:] for line in self.RAW.split("\n"))
        assert validate_copybook_content(stripped, "CONT.cpy") != []  # old default
        assert (
            validate_copybook_content(stripped, "CONT.cpy", indicator_position=0) == []
        )

    def test_expander_no_longer_warns_on_a_continued_literal(self, tmp_path: Path):
        (tmp_path / "CONT.cpy").write_text(self.RAW)
        expansion = expand_copybooks("       COPY CONT.\n", copybook_paths=[tmp_path])
        assert not [w for w in expansion.statistics.warnings if "unbalanced" in w]


# --------------------------------------------------------------------------
# 4 + 6. COPY ... REPLACING compares text words, once per word.


class TestCopyReplacingTextWords:
    def test_blank_runs_between_words_are_one_blank(self):
        content = "       05 A PIC  X(10).\n       05 C PIC X (10).\n"
        clauses = [ReplacingClause("PIC X(10)", "PIC X(20)")]
        assert apply_replacing_clauses(content, clauses, indicator_position=6) == (
            "       05 A PIC X(20).\n       05 C PIC X(20).\n"
        )

    def test_pseudo_text_leading_and_trailing_blanks_are_not_part_of_it(self):
        clauses = [ReplacingClause(" A ", " Z ")]
        assert apply_replacing_clauses("       01 A.\n", clauses) == "       01  Z .\n"

    def test_lexer_path_strips_pseudo_text(self, tmp_path: Path):
        (tmp_path / "SUBS.cpy").write_text("       01 A.\n           05 B PIC X.\n")
        expansion = expand_copybooks(
            "       COPY SUBS REPLACING == A == BY == Z ==.\n",
            copybook_paths=[tmp_path],
        )
        assert "01 Z." in expansion.expanded_source

    def test_pairs_swap_instead_of_cascading(self):
        content = "       01 A.\n           05 B PIC X.\n"
        clauses = [ReplacingClause("A", "B"), ReplacingClause("B", "A")]
        assert apply_replacing_clauses(content, clauses) == (
            "       01 B.\n           05 A PIC X.\n"
        )

    def test_replacement_text_is_never_rescanned(self):
        clauses = [ReplacingClause("A", "A-B"), ReplacingClause("A-B", "C")]
        assert apply_replacing_clauses("       01 A.\n", clauses) == "       01 A-B.\n"

    def test_literal_protection_survives_the_single_pass(self):
        content = "       01 A PIC X VALUE 'A'.\n"
        assert apply_replacing_clauses(content, [ReplacingClause("A", "Z")]) == (
            "       01 Z PIC X VALUE 'A'.\n"
        )
        assert apply_replacing_clauses(content, [ReplacingClause("'A'", "'Z'")]) == (
            "       01 A PIC X VALUE 'Z'.\n"
        )

    def test_backslash_in_replacement_is_literal(self):
        clauses = [ReplacingClause("PATH", "'C:\\TEMP\\1'")]
        assert apply_replacing_clauses("       MOVE PATH TO X.\n", clauses) == (
            "       MOVE 'C:\\TEMP\\1' TO X.\n"
        )


# --------------------------------------------------------------------------
# 5. REPLACE: a parenthesis is a text word of its own.


class TestReplaceParenthesesAreTextWords:
    @pytest.mark.parametrize(
        "statement",
        ["MOVE WS-A(1) TO X.", "MOVE WS-A(1:2) TO X.", "MOVE WS-A (1) TO X."],
    )
    def test_subscripted_reference_is_replaced(self, statement):
        source = f"REPLACE ==WS-A== BY ==WS-B==.\n{statement}\n"
        out = apply_replace_statements(source)
        assert out.splitlines()[1] == statement.replace("WS-A", "WS-B")

    def test_parenthesised_pseudo_text_matches_regardless_of_blanks(self):
        source = "REPLACE ==WS-A(1)== BY ==WS-B==.\nMOVE WS-A (1) TO X.\n"
        assert apply_replace_statements(source).splitlines()[1] == "MOVE WS-B TO X."

    def test_replacement_keeps_its_parentheses_attached(self):
        source = "REPLACE ==WS-A== BY ==WS-B(2)==.\nMOVE WS-A TO X.\n"
        assert apply_replace_statements(source).splitlines()[1] == "MOVE WS-B(2) TO X."

    def test_partial_word_form_still_works(self):
        source = "REPLACE ==:TAG:== BY ==WS==.\nMOVE :TAG:-A(1) TO :TAG:-B.\n"
        assert apply_replace_statements(source).splitlines()[1] == (
            "MOVE WS-A(1) TO WS-B."
        )


# --------------------------------------------------------------------------
# 7. >>IF name [IS] [NOT] DEFINED -- IS is optional.


class TestConditionalCompilationDefinedWithoutIs:
    @pytest.mark.parametrize(
        ("condition", "included"),
        [
            ("DEBUG IS DEFINED", True),
            ("DEBUG DEFINED", True),
            ("DEBUG IS NOT DEFINED", False),
            ("DEBUG NOT DEFINED", False),
            ("OTHER DEFINED", False),
            ("OTHER NOT DEFINED", True),
        ],
    )
    def test_defined_forms(self, condition, included):
        warnings: list[str] = []
        out = preprocess_conditional_compilation(
            f">>DEFINE DEBUG\n>>IF {condition}\n       DISPLAY 'IN'.\n>>END-IF\n",
            warnings=warnings,
        )
        assert warnings == []
        assert ("DISPLAY 'IN'" in out) is included

    def test_dangling_is_or_not_is_still_a_syntax_error(self):
        warnings: list[str] = []
        preprocess_conditional_compilation(
            ">>DEFINE DEBUG\n>>IF DEBUG NOT\n       DISPLAY 'IN'.\n>>END-IF\n",
            warnings=warnings,
        )
        assert warnings and "after NOT" in warnings[0]


# --------------------------------------------------------------------------
# 8. A continuation line is the next line that is neither a comment nor
#    blank -- for any continued text, not only an open literal.


class TestNonLiteralContinuationAcrossComment:
    LINES = [
        "           MOVE WS-CO",
        "      * a comment between the two halves of the word",
        "",
        "      -         UNT TO X.",
        "           STOP RUN.",
    ]

    def test_word_rejoins_and_line_count_is_preserved(self):
        out = normalize_fixed_format(self.LINES)
        assert out.count("\n") == len(self.LINES)
        assert out.splitlines() == [
            "    MOVE WS-COUNT TO X.",
            "",
            "",
            "",
            "    STOP RUN.",
        ]

    def test_parse_sees_one_operand(self):
        source = FIXED_HEADER + "\n".join(self.LINES) + "\n"
        result = parse_cobol(source, filename="cont.cbl")
        assert result.success, result.errors
        move = result.ast.find_all_by_type("MoveStatement")[0]
        assert move.operands == ["WS-COUNT", "X"]
        assert [s.location.line for s in result.ast.get_all_statements()] == [8, 12]

    def test_comment_before_a_plain_line_still_flushes(self):
        lines = ["           MOVE A TO B", "      * note", "           MOVE C TO D."]
        assert normalize_fixed_format(lines).splitlines() == [
            "    MOVE A TO B",
            "",
            "    MOVE C TO D.",
        ]


# --------------------------------------------------------------------------
# 9. A quotation mark in column 72 followed by a continuation starting with
#    two quotation marks: the literal did not close.


class TestQuoteInColumn72Rule:
    @staticmethod
    def _line_ending_in_quote_at_72(prefix: str, quote: str) -> str:
        line = prefix + " " * (71 - len(prefix)) + quote
        assert len(line) == 72 and line[71] == quote
        return line

    @pytest.mark.parametrize("quote", ["'", '"'])
    def test_pair_is_one_quote_and_the_literal_continues(self, quote):
        first = self._line_ending_in_quote_at_72(
            f"       01 A PIC X(50) VALUE {quote}AB", quote
        )
        out = normalize_fixed_format([first, f"      -    {quote}{quote}CD{quote}."])
        assert out.count("\n") == 2
        logical = out.splitlines()[0]
        assert logical.endswith(f"{quote}{quote}CD{quote}.")
        assert logical.startswith(f"01 A PIC X(50) VALUE {quote}AB")

    def test_program_parses_with_the_doubled_quote_in_the_value(self):
        first = self._line_ending_in_quote_at_72("       01 A PIC X(50) VALUE 'AB", "'")
        source = (
            "       IDENTIFICATION DIVISION.\n"
            "       PROGRAM-ID. Q72.\n"
            "       DATA DIVISION.\n"
            "       WORKING-STORAGE SECTION.\n"
            f"{first}\n"
            "      -    ''CD'.\n"
            "       PROCEDURE DIVISION.\n"
            "           STOP RUN.\n"
        )
        result = parse_cobol(source, filename="q72.cbl")
        assert result.success, result.errors
        assert not [w for w in result.warnings if "Unterminated" in w]
        item = result.ast.find_all_by_type("CobolDataItem")[0]
        # The pair is ONE quotation mark in the value (the lexer un-escapes
        # it and re-renders the literal with the other quote kind).
        assert item.value_clause is not None
        assert item.value_clause.startswith('"AB')
        assert item.value_clause.endswith("'CD\"")

    def test_closing_quote_at_72_without_the_pair_stays_closed(self):
        first = self._line_ending_in_quote_at_72("       01 A PIC X(50) VALUE 'AB", "'")
        out = normalize_fixed_format([first, "      -    'CD'."])
        # A new literal on the continuation line, exactly as before.
        assert out.splitlines()[0] == first[7:] + "'CD'."
