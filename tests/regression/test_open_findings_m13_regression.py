"""Regression tests for open-findings M13.

M13: ``apply_replacing_clauses`` was a blind regex substitution over the whole
copybook text — a ``REPLACING FOO BY BAR`` clause rewrote ``FOO`` inside
fixed-format comment lines and inside alphanumeric string literals. Separately,
the ``:...:`` pseudo-text delimiter form was silently broken in the
``expand_copybooks()`` code path: ``CopyStatementLexer`` captured ``:ABC:``
with the colons attached, so ``REPLACING :ABC: BY :XYZ:`` never matched
anything in the copybook body.

These tests pin the fixed behavior:
- substitution skips comment lines (column-7 ``*`` / ``/``),
- substitution skips string literals (including doubled-quote escapes),
- normal code occurrences are still rewritten,
- ``:ABC: BY :XYZ:`` works end-to-end through ``expand_copybooks()``,
- ``==pseudo-text==`` replacement still works.
"""

from pathlib import Path

from cobolparser.preprocess import expand_copybooks
from cobolparser.preprocess.copy_statement_parser import (
    apply_replacing_clauses,
    extract_copy_statements,
)
from cobolparser.preprocess.models import ReplacingClause

_HEADER = (
    "       IDENTIFICATION DIVISION.\n"
    "       PROGRAM-ID. M13TEST.\n"
    "       DATA DIVISION.\n"
    "       WORKING-STORAGE SECTION.\n"
)

_FOOTER = "       PROCEDURE DIVISION.\n" "       MAIN-PARA.\n" "           STOP RUN.\n"


def _write_copybook(directory: Path, name: str, content: str) -> None:
    (directory / name).write_text(content, encoding="utf-8")


class TestM13ReplacingContextAware:
    """REPLACING must be comment- and literal-aware, and :...: must work."""

    # ------------------------------------------------------------------
    # (a) Comment lines are never rewritten
    # ------------------------------------------------------------------
    def test_replacing_does_not_rewrite_comment_lines(self):
        content = (
            "      * FOO IS DOCUMENTED IN THIS COMMENT LINE\n"
            "      / FOO PAGE-EJECT COMMENT LINE\n"
            "       01 FOO PIC X(10).\n"
        )
        clauses = [ReplacingClause(find_text="FOO", replace_text="BAR", mode="ALL")]
        result = apply_replacing_clauses(content, clauses)
        lines = result.split("\n")
        # Comment lines untouched
        assert lines[0] == "      * FOO IS DOCUMENTED IN THIS COMMENT LINE"
        assert lines[1] == "      / FOO PAGE-EJECT COMMENT LINE"
        # Code line rewritten
        assert "01 BAR PIC X(10)." in lines[2]
        assert "FOO" not in lines[2]

    # ------------------------------------------------------------------
    # (b) String literals are never rewritten
    # ------------------------------------------------------------------
    def test_replacing_does_not_rewrite_string_literals(self, tmp_path):
        _write_copybook(
            tmp_path,
            "GREETCPY.CPY",
            "       01 GREETING PIC X(20) VALUE 'SAY FOO NOW'.\n"
            '       01 MOTTO PIC X(20) VALUE "FOO ""FOO"" DAY".\n'
            "       01 FOO PIC X(10).\n",
        )
        source = (
            _HEADER + "       COPY GREETCPY REPLACING ==FOO== BY ==BAR==.\n" + _FOOTER
        )
        result = expand_copybooks(source, copybook_paths=[str(tmp_path)])
        expanded = result.expanded_source
        # Literal content preserved verbatim (single-quoted, and
        # double-quoted with doubled-quote escapes)
        assert "'SAY FOO NOW'" in expanded
        assert '"FOO ""FOO"" DAY"' in expanded
        # (c) The real code occurrence WAS rewritten
        assert "01 BAR PIC X(10)." in expanded
        assert "01 FOO PIC X(10)." not in expanded

    def test_replacing_does_not_rewrite_literals_unit_level(self):
        content = "       01 A PIC X(9) VALUE 'FOO BAR'.\n" "       01 FOO PIC X.\n"
        clauses = [ReplacingClause(find_text="FOO", replace_text="ZZZ", mode="ALL")]
        result = apply_replacing_clauses(content, clauses)
        assert "'FOO BAR'" in result
        assert "01 ZZZ PIC X." in result

    # ------------------------------------------------------------------
    # (c) Normal code occurrences are still rewritten
    # ------------------------------------------------------------------
    def test_replacing_still_rewrites_code_occurrences(self, tmp_path):
        _write_copybook(
            tmp_path,
            "BASEREC.CPY",
            "       01 OLD-NAME PIC X(10).\n" "           88 OLD-NAME-SET VALUE 'Y'.\n",
        )
        source = (
            _HEADER
            + "       COPY BASEREC REPLACING ==OLD-NAME== BY ==NEW-NAME==.\n"
            + _FOOTER
        )
        result = expand_copybooks(source, copybook_paths=[str(tmp_path)])
        expanded = result.expanded_source
        assert "01 NEW-NAME PIC X(10)." in expanded
        # Whole-word semantics: OLD-NAME-SET is a different (longer) word and
        # must not be partially rewritten by the OLD-NAME clause.
        assert "OLD-NAME-SET" in expanded

    # ------------------------------------------------------------------
    # (d) :ABC: BY :XYZ: works end-to-end through expand_copybooks()
    # ------------------------------------------------------------------
    def test_colon_delimited_replacing_end_to_end(self, tmp_path):
        _write_copybook(
            tmp_path,
            "COLONREC.CPY",
            "       01 ABC PIC X(10).\n" "       01 ABC-COUNT PIC 9(4).\n",
        )
        source = _HEADER + "       COPY COLONREC REPLACING :ABC: BY :XYZ:.\n" + _FOOTER
        result = expand_copybooks(source, copybook_paths=[str(tmp_path)])
        expanded = result.expanded_source
        # The delimiters are stripped and the substitution actually happens
        # (previously this silently no-oped because find_text was ':ABC:').
        assert "01 XYZ PIC X(10)." in expanded
        # Whole-word semantics: ABC-COUNT is a different identifier.
        assert "ABC-COUNT" in expanded

    def test_colon_delimited_matches_inside_colon_placeholder(self, tmp_path):
        # ':' is not an identifier character, so :TAG: also matches the TAG
        # inside a ':TAG:-FIELD' placeholder (whole-token-substring
        # semantics, mirroring parse_replacing_clause which strips colons).
        _write_copybook(
            tmp_path,
            "TAGREC.CPY",
            "       01 :TAG:-RECORD PIC X(10).\n",
        )
        source = _HEADER + "       COPY TAGREC REPLACING :TAG: BY :EMP:.\n" + _FOOTER
        result = expand_copybooks(source, copybook_paths=[str(tmp_path)])
        assert "EMP" in result.expanded_source
        assert "TAG" not in result.expanded_source

    def test_colon_operands_tokenized_without_delimiters(self):
        source = "       COPY CUSTREC REPLACING :ABC: BY :XYZ:.\n"
        statements = extract_copy_statements(source)
        assert len(statements) == 1
        clauses = statements[0].replacing_clauses
        assert clauses is not None and len(clauses) == 1
        assert clauses[0].find_text == "ABC"
        assert clauses[0].replace_text == "XYZ"
        assert clauses[0].mode == "ALL"

    # ------------------------------------------------------------------
    # (e) ==pseudo-text== replacement still works
    # ------------------------------------------------------------------
    def test_pseudo_text_replacing_still_works(self, tmp_path):
        _write_copybook(
            tmp_path,
            "PSEUDREC.CPY",
            "       01 :TAG:-RECORD.\n" "           05 :TAG:-ID PIC 9(6).\n",
        )
        source = (
            _HEADER + "       COPY PSEUDREC REPLACING ==:TAG:== BY ==EMP==.\n" + _FOOTER
        )
        result = expand_copybooks(source, copybook_paths=[str(tmp_path)])
        expanded = result.expanded_source
        assert "EMP-RECORD" in expanded
        assert "EMP-ID" in expanded
        assert ":TAG:" not in expanded
