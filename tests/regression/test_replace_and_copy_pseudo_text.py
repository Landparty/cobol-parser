"""Regression tests for COBOL source-text pseudo-text substitution:

* the ``REPLACE`` compiler-directing statement
  (:func:`cobolparser.preprocess.replace_statement.apply_replace_statements`),
  and
* stripping of un-expanded ``COPY ... REPLACING ==pseudo-text==`` statements
  (:func:`cobolparser.preprocess.replace_statement.strip_unexpanded_copy_statements`)

both applied before lexing in the standalone (non-copybook-expanding) parse
pipeline.

These pin the fixes that let the NIST COBOL-85 programs ``SM208A`` (30x
``REPLACE`` + ``==...==`` pseudo-text) and ``SM206A`` (``COPY ... REPLACING``
with pseudo-text containing a bare ``MOVE`` token) parse error-free — see
``tests/integration/test_nist_cobol85_support.py``. The synthetic inputs below
exercise the behaviour independently of the NIST corpus.
"""

from cobolparser import CobolParser
from cobolparser.plugins.core import ErrorRecoveryMode
from cobolparser.preprocess.replace_statement import (
    _tokenize_text_words,
    apply_replace_statements,
    strip_unexpanded_copy_statements,
)


def _words(text: str) -> list[str]:
    return [w[0] for w in _tokenize_text_words(text)]


def _parse(source: str):
    return CobolParser(error_recovery=ErrorRecoveryMode.COLLECT_ALL).parse(source)


class TestTextWordTokenizer:
    """The text-word split underpins whitespace-insensitive matching."""

    def test_trailing_period_is_a_separate_word(self) -> None:
        assert _words("MOVE WS-A TO WS-B.") == ["MOVE", "WS-A", "TO", "WS-B", "."]

    def test_comma_and_semicolon_are_separators_not_words(self) -> None:
        assert _words("MOVE;  A  , TO") == ["MOVE", "A", "TO"]

    def test_literal_is_one_word_including_spaces(self) -> None:
        assert _words('MOVE "A B C" TO X') == ["MOVE", '"A B C"', "TO", "X"]

    def test_decimal_point_stays_in_numeric_literal(self) -> None:
        assert _words("PIC 9V99 VALUE 3.14.") == [
            "PIC",
            "9V99",
            "VALUE",
            "3.14",
            ".",
        ]

    def test_bare_equals_is_a_word(self) -> None:
        assert _words("A = B") == ["A", "=", "B"]


class TestApplyReplaceStatements:
    """Unit-level behaviour of the REPLACE substitution pass."""

    def test_single_pair_applies_after_statement(self) -> None:
        src = "REPLACE ==FOO== BY ==BAR==.\nMOVE FOO TO X.\n"
        out = apply_replace_statements(src)
        assert "BAR" in out
        assert "FOO" not in out.replace("REPLACE", "")  # only in the removed stmt

    def test_replace_off_cancels(self) -> None:
        src = (
            "REPLACE ==FOO== BY ==BAR==.\n"
            "MOVE FOO TO X.\n"
            "REPLACE OFF.\n"
            "MOVE FOO TO Y.\n"
        )
        out = apply_replace_statements(src)
        lines = out.split("\n")
        assert "MOVE BAR TO X." in lines[1]
        assert "MOVE FOO TO Y." in lines[3]

    def test_multiple_operand_pairs_in_one_statement(self) -> None:
        src = "REPLACE ==AO== BY ==TO== ==IE== BY ==IF==.\nIE A AO B.\n"
        out = apply_replace_statements(src)
        assert "IF A TO B." in out

    def test_empty_replacement_deletes_the_word(self) -> None:
        src = "REPLACE ==NOT== BY ====.\nIF A NOT EQUAL B.\n"
        out = apply_replace_statements(src)
        assert "IF A  EQUAL B." in out or "IF A EQUAL B." in out.replace("  ", " ")

    def test_trailing_period_preserved_when_last_word_matches(self) -> None:
        # find is `MOVE WS-A TO WS-B` (no period); the source's sentence period
        # is a separate text word and must survive the replacement.
        src = (
            "REPLACE ==MOVE WS-A TO WS-B== BY ==MOVE WS-C TO WS-B==.\n"
            "MOVE WS-A TO WS-B.\n"
        )
        out = apply_replace_statements(src)
        assert "MOVE WS-C TO WS-B." in out

    def test_separators_are_equivalent_to_spaces(self) -> None:
        src = (
            'REPLACE ==MOVE;  "FAIL"  , TO== BY ==MOVE "PASS" TO==.\n'
            'MOVE  , "FAIL";  TO  P.\n'
        )
        out = apply_replace_statements(src)
        assert 'MOVE "PASS" TO  P.' in out or 'MOVE "PASS" TO P.' in out.replace(
            "  ", " "
        )

    def test_pseudo_text_with_embedded_period_and_keyword(self) -> None:
        # The pseudo-text itself contains a period and the AO->TO fix word.
        src = (
            "REPLACE ==MOVE A AO B. IE C== BY ==MOVE A TO B. IF C==.\n"
            "MOVE A AO B. IE C\n"
        )
        out = apply_replace_statements(src)
        assert "AO" not in out.split("BY")[-1]
        assert "MOVE A TO B" in out

    def test_multiline_pseudo_text_match_across_newlines(self) -> None:
        src = (
            "REPLACE ==MOVE FAIL TO== BY ==MOVE PASS TO==.\n"
            "MOVE\n"
            "\n"
            "FAIL\n"
            "TO P.\n"
        )
        out = apply_replace_statements(src)
        assert "PASS" in out
        # Line count preserved.
        assert out.count("\n") == src.count("\n")

    def test_literal_containing_keyword_not_replaced(self) -> None:
        src = 'REPLACE ==FAIL== BY ==PASS==.\nMOVE "FAIL MESSAGE" TO X.\n'
        out = apply_replace_statements(src)
        assert '"FAIL MESSAGE"' in out

    def test_replace_keyword_inside_literal_ignored(self) -> None:
        src = 'DISPLAY "REPLACE FAILED".\nMOVE A TO B.\n'
        out = apply_replace_statements(src)
        assert out == src

    def test_no_replace_keyword_is_noop(self) -> None:
        src = "MOVE A TO B.\nDISPLAY X.\n"
        assert apply_replace_statements(src) is src

    def test_line_count_preserved(self) -> None:
        src = (
            "REPLACE ==FOO== BY ==BAR==.\n"
            "MOVE FOO TO A.\n"
            "MOVE FOO TO B.\n"
            "REPLACE OFF.\n"
        )
        out = apply_replace_statements(src)
        assert out.count("\n") == src.count("\n")

    def test_unterminated_active_set_warns(self) -> None:
        src = "REPLACE ==FOO== BY ==BAR==.\nMOVE FOO TO X.\n"
        warnings: list[str] = []
        apply_replace_statements(src, warnings=warnings)
        assert any("still active at end of source" in w for w in warnings)


class TestStripUnexpandedCopy:
    """Un-expanded COPY statements (with pseudo-text REPLACING) are removed so
    nothing leaks into the token stream."""

    def test_copy_with_pseudo_text_move_operand_is_blanked(self) -> None:
        src = (
            "COPY KP004 REPLACING ==SOME TEXT SHOVE== BY MOVE\n"
            "    == DELETE== BY DE-LETE.\n"
            "DISPLAY X.\n"
        )
        warnings: list[str] = []
        out = strip_unexpanded_copy_statements(src, warnings=warnings)
        assert "COPY" not in out
        assert "MOVE" not in out
        assert "DISPLAY X." in out
        assert out.count("\n") == src.count("\n")
        assert any("KP004" in w for w in warnings)

    def test_plain_copy_is_blanked(self) -> None:
        src = "COPY MYBOOK.\nDISPLAY X.\n"
        out = strip_unexpanded_copy_statements(src)
        assert "COPY" not in out
        assert "DISPLAY X." in out

    def test_no_copy_keyword_is_noop(self) -> None:
        src = "MOVE A TO B.\n"
        assert strip_unexpanded_copy_statements(src) is src

    def test_copy_with_period_in_pseudo_text_fully_removed(self) -> None:
        # A REPLACING pseudo-text containing a sentence period must not
        # terminate the COPY prematurely — the whole statement is removed.
        src = (
            "COPY KP007 REPLACING ==FAIL. SUBTRACT 1. == BY ==PASS. ==.\n" "STOP RUN.\n"
        )
        out = strip_unexpanded_copy_statements(src)
        assert "SUBTRACT" not in out
        assert "STOP RUN." in out


class TestEndToEndParsing:
    """The passes are wired into the standard parse pipeline."""

    def test_replace_statement_program_parses_clean(self) -> None:
        source = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. REPTEST.
       PROCEDURE DIVISION.
       MAIN-PARA.
       REPLACE ==AO== BY ==TO==.
           MOVE "*" AO WS-X.
       REPLACE OFF.
           STOP RUN.
"""
        result = _parse(source)
        assert result.success, result.errors
        moves = result.ast.find_all_by_type("MoveStatement")
        assert len(moves) == 1

    def test_unexpanded_copy_replacing_pseudo_text_parses_clean(self) -> None:
        # Without stripping, `BY MOVE ==DELETE==` leaks as a MOVE with no TO.
        source = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. CPYTEST.
       PROCEDURE DIVISION.
       MAIN-PARA.
           COPY KP004 REPLACING ==NOT REAL SYNTAX SHOVE== BY MOVE
               == DELETE== BY DE-LETE.
           STOP RUN.
"""
        result = _parse(source)
        assert result.success, result.errors
        assert result.ast.find_all_by_type("StopStatement")
