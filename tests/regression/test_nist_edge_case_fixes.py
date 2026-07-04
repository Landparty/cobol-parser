"""Regression tests for parser edge cases found via the NIST COBOL-85 corpus.

Each test pins a fix with a minimal reproduction so the corpus-level tests
(`tests/integration/test_nist_cobol85_support.py`) are backed by focused
unit-level coverage:

* NC113M — division headers split across source lines
* OBNC1M — comment-entries containing division keywords
* NC252A — COMPUTE with multiple / subscripted / ROUNDED receivers
* NC252A — a trailing period after a numeric literal is a sentence
  terminator, not a decimal point
* K1WKA/K1WKY — copybook validator vs. continued string literals
* SM207A — library-qualified COPY falls back to the plain search path
"""

from pathlib import Path

import pytest

from cobolparser import parse_cobol
from cobolparser.preprocess import validate_copybook_content
from cobolparser.preprocess.copybook_expander import expand_copybooks


def _parse_clean(source: str):
    result = parse_cobol(source, filename="test.cbl")
    assert result.ast is not None, "AST is None"
    assert result.errors == [], "parse errors:\n" + "\n".join(
        str(e) for e in result.errors
    )
    return result.ast


class TestSplitDivisionHeaders:
    """NC113M: COBOL words may be separated by newlines, so a division
    header may span source lines."""

    def test_data_division_header_split_across_two_lines(self):
        ast = _parse_clean(
            "       IDENTIFICATION DIVISION.\n"
            "       PROGRAM-ID. SPLITHDR.\n"
            "       DATA\n"
            "        DIVISION.\n"
            "       WORKING-STORAGE SECTION.\n"
            "       01 WS-A PIC 9.\n"
            "       PROCEDURE DIVISION.\n"
            "       P1.\n"
            "           STOP RUN.\n"
        )
        names = [d.division_name for d in ast.divisions]
        assert "DATA" in names
        assert "PROCEDURE" in names

    def test_procedure_division_header_split_across_three_lines(self):
        ast = _parse_clean(
            "       IDENTIFICATION DIVISION.\n"
            "       PROGRAM-ID. SPLITHDR.\n"
            "       DATA DIVISION.\n"
            "       WORKING-STORAGE SECTION.\n"
            "       01 WS-A PIC 9.\n"
            "       PROCEDURE\n"
            "         DIVISION\n"
            "                  .\n"
            "       P1.\n"
            "           MOVE 1 TO WS-A.\n"
            "           STOP RUN.\n"
        )
        assert ast.procedure_division is not None
        assert len(ast.get_all_statements()) == 2


class TestCommentEntryContainingDivisionKeyword:
    """OBNC1M: IDENTIFICATION DIVISION comment-entries are free text and may
    contain words like DATA or PROCEDURE."""

    def test_installation_comment_entry_containing_data(self):
        ast = _parse_clean(
            "       IDENTIFICATION DIVISION.\n"
            "       PROGRAM-ID. CMTDATA.\n"
            "       INSTALLATION.\n"
            "           GENERAL SERVICES ADMINISTRATION\n"
            "           AUTOMATIC DATA AND TELECOMMUNICATION SERVICE.\n"
            "       DATA DIVISION.\n"
            "       WORKING-STORAGE SECTION.\n"
            "       01 WS-A PIC 9.\n"
            "       PROCEDURE DIVISION.\n"
            "       P1.\n"
            "           STOP RUN.\n"
        )
        installation = ast.identification_division.metadata.get("installation")
        assert "AUTOMATIC DATA AND TELECOMMUNICATION SERVICE" in installation

    def test_author_comment_entry_containing_procedure(self):
        ast = _parse_clean(
            "       IDENTIFICATION DIVISION.\n"
            "       PROGRAM-ID. CMTPROC.\n"
            "       AUTHOR.\n"
            "           THE PROCEDURE COMPLIANCE TEAM.\n"
            "       PROCEDURE DIVISION.\n"
            "       P1.\n"
            "           STOP RUN.\n"
        )
        assert "PROCEDURE COMPLIANCE TEAM" in ast.identification_division.metadata.get(
            "author"
        )


class TestComputeMultipleReceivers:
    """NC252A: COMPUTE {identifier [ROUNDED]}... = expression."""

    def _compute_statements(self, ast):
        return [
            s
            for s in ast.get_all_statements()
            if type(s).__name__ == "ComputeStatement"
        ]

    def test_multiple_targets_with_rounded_and_subscript(self):
        ast = _parse_clean(
            "       IDENTIFICATION DIVISION.\n"
            "       PROGRAM-ID. MULTITGT.\n"
            "       DATA DIVISION.\n"
            "       WORKING-STORAGE SECTION.\n"
            "       01 A PIC 9(4).\n"
            "       01 B PIC 9(4)V9.\n"
            "       01 T PIC 9 OCCURS 3 TIMES.\n"
            "       PROCEDURE DIVISION.\n"
            "       P1.\n"
            "           COMPUTE  A\n"
            "                    B   ROUNDED\n"
            "                    T (2)  =  174 / 16.\n"
            "           STOP RUN.\n"
        )
        computes = self._compute_statements(ast)
        assert len(computes) == 1
        assert computes[0].targets == ["A", "B", "T ( 2 )"]
        assert computes[0].to_dict()["expression"].strip() == "174 / 16"

    def test_single_target_still_works(self):
        ast = _parse_clean(
            "       IDENTIFICATION DIVISION.\n"
            "       PROGRAM-ID. ONETGT.\n"
            "       DATA DIVISION.\n"
            "       WORKING-STORAGE SECTION.\n"
            "       01 A PIC 9(4).\n"
            "       PROCEDURE DIVISION.\n"
            "       P1.\n"
            "           COMPUTE A ROUNDED = 1 + 2.\n"
            "           STOP RUN.\n"
        )
        computes = self._compute_statements(ast)
        assert computes[0].targets == ["A"]


class TestNumericLiteralTrailingPeriod:
    """A period after a numeric literal is only a decimal point when
    followed by a digit; otherwise it terminates the sentence."""

    def test_expression_ending_in_integer_does_not_swallow_next_statement(self):
        ast = _parse_clean(
            "       IDENTIFICATION DIVISION.\n"
            "       PROGRAM-ID. NUMDOT.\n"
            "       DATA DIVISION.\n"
            "       WORKING-STORAGE SECTION.\n"
            "       01 A PIC 9(4).\n"
            "       PROCEDURE DIVISION.\n"
            "       P1.\n"
            "           COMPUTE A = 174 / 16.\n"
            "           MOVE 5 TO A.\n"
            "           STOP RUN.\n"
        )
        names = [type(s).__name__ for s in ast.get_all_statements()]
        assert names == ["ComputeStatement", "MoveStatement", "StopStatement"]
        compute = ast.get_all_statements()[0]
        assert compute.to_dict()["expression"].strip() == "174 / 16"

    def test_real_decimal_literals_still_parse(self):
        ast = _parse_clean(
            "       IDENTIFICATION DIVISION.\n"
            "       PROGRAM-ID. NUMDEC.\n"
            "       DATA DIVISION.\n"
            "       WORKING-STORAGE SECTION.\n"
            "       01 A PIC 9(4)V99.\n"
            "       PROCEDURE DIVISION.\n"
            "       P1.\n"
            "           COMPUTE A = 3.14 * 2.5.\n"
            "           STOP RUN.\n"
        )
        compute = ast.get_all_statements()[0]
        assert compute.to_dict()["expression"].strip() == "3.14 * 2.5"


class TestCopybookValidatorContinuedLiterals:
    """K1WKA/K1WKY: fixed-format string continuation re-opens the literal
    with an extra quote — not an unbalanced-quote problem."""

    def test_continued_double_quoted_literal_is_valid(self):
        content = (
            '000100     02 WSTR-2A PICTURE X(3) VALUE                              "A\n'
            '000200-    "BC".\n'
        )
        assert validate_copybook_content(content, "k1wka.cpy") == []

    def test_genuinely_unbalanced_quotes_still_flagged(self):
        issues = validate_copybook_content('01 X PIC X VALUE "A.\n', "bad.cpy")
        assert any("unbalanced double quotes" in i for i in issues)


class TestLibraryQualifiedCopy:
    """SM207A: COPY member OF library resolves via a library subdirectory
    when present, falling back to the plain search path otherwise."""

    def _program(self, copy_line: str) -> str:
        return (
            "       IDENTIFICATION DIVISION.\n"
            "       PROGRAM-ID. LIBCOPY.\n"
            "       DATA DIVISION.\n"
            "       WORKING-STORAGE SECTION.\n"
            "       01  WSTR-1.\n"
            f"           {copy_line}\n"
            "       PROCEDURE DIVISION.\n"
            "       P1.\n"
            "           STOP RUN.\n"
        )

    def test_falls_back_to_plain_search_path(self, tmp_path: Path):
        (tmp_path / "MEM.CPY").write_text("           02 FROM-ROOT PIC X.\n")
        result = expand_copybooks(
            self._program("COPY MEM OF NOSUCHLIB."), copybook_paths=[str(tmp_path)]
        )
        assert str(tmp_path / "MEM.CPY") in result.included_copybooks

    def test_library_subdirectory_takes_precedence(self, tmp_path: Path):
        (tmp_path / "MEM.CPY").write_text("           02 FROM-ROOT PIC X.\n")
        libdir = tmp_path / "MYLIB"
        libdir.mkdir()
        (libdir / "MEM.CPY").write_text("           02 FROM-LIB PIC X.\n")
        result = expand_copybooks(
            self._program("COPY MEM OF MYLIB."), copybook_paths=[str(tmp_path)]
        )
        assert str(libdir / "MEM.CPY") in result.included_copybooks


@pytest.mark.integration
class TestFixedNistFilesStayFixed:
    """The concrete NIST programs behind these fixes parse error-free."""

    NIST_DIR = Path(__file__).parent.parent.parent / "examples" / "cobol"

    @pytest.mark.parametrize("name", ["NC113M.CBL", "NC252A.CBL"])
    def test_parses_error_free(self, name: str):
        source = (self.NIST_DIR / name).read_text(encoding="utf-8", errors="ignore")
        result = parse_cobol(source, filename=name)
        assert result.ast is not None
        assert result.errors == []
