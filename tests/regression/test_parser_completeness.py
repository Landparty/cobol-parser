"""Regression tests for data-division completeness fixes.

Each class documents a gap where the parser previously discarded information,
and locks down the corrected behavior so a future refactor cannot silently
re-introduce the same drop.

Gaps closed here:
    * EXTERNAL / GLOBAL data-item clauses were tokenized but never recorded on
      ``CobolDataItem`` (no ``is_external`` / ``is_global`` fields).
    * FD/SD file-description clauses (BLOCK CONTAINS, RECORD, LABEL RECORDS,
      RECORDING MODE, CODE-SET, DATA RECORDS, RECORD VARYING ...) were skipped
      wholesale; only the file name survived.
    * Edited PICTURE clauses with embedded decimal points and currency / sign /
      check-protect symbols (``$$$,$$9.99``, ``ZZ,ZZ9.99-``) were truncated at
      the first interior period or dropped entirely.
"""

import textwrap

from cobolparser import parse_cobol
from cobolparser.models.ast_base import SourceLocation
from cobolparser.models.data_items import PictureClause


def _ws_program(items: str) -> str:
    return textwrap.dedent(f"""\
        IDENTIFICATION DIVISION.
        PROGRAM-ID. REGTEST.
        DATA DIVISION.
        WORKING-STORAGE SECTION.
        {items}
        PROCEDURE DIVISION.
        STOP RUN.
        """)


def _file_program(file_section: str) -> str:
    return textwrap.dedent(f"""\
        IDENTIFICATION DIVISION.
        PROGRAM-ID. REGTEST.
        DATA DIVISION.
        FILE SECTION.
        {file_section}
        WORKING-STORAGE SECTION.
        01  WS-FLAG PIC X.
        PROCEDURE DIVISION.
        STOP RUN.
        """)


def _find_item(result, name: str):
    for item in result.ast.find_all_by_type("DataItem"):
        if getattr(item, "name", "").upper() == name.upper():
            return item
    return None


# ===========================================================================
# EXTERNAL / GLOBAL clauses
# ===========================================================================


class TestExternalGlobalClauses:
    """EXTERNAL/GLOBAL were dropped: the data item carried no record of them."""

    def test_external_stored(self):
        result = parse_cobol(
            _ws_program("01  WS-SHARED IS EXTERNAL.\n           05 WS-N PIC 9(4)."),
            filename="reg.cbl",
        )
        assert result.success
        item = _find_item(result, "WS-SHARED")
        assert item is not None
        assert item.is_external is True
        assert item.is_global is False

    def test_global_stored(self):
        result = parse_cobol(
            _ws_program("01  WS-VIS PIC X(10) IS GLOBAL."),
            filename="reg.cbl",
        )
        assert result.success
        item = _find_item(result, "WS-VIS")
        assert item is not None
        assert item.is_global is True

    def test_external_as_literal_does_not_break_parse(self):
        result = parse_cobol(
            _ws_program('01  WS-NAMED IS EXTERNAL AS "SHARED-AREA".'),
            filename="reg.cbl",
        )
        assert result.success
        item = _find_item(result, "WS-NAMED")
        assert item is not None
        assert item.is_external is True

    def test_flags_serialized_in_to_dict(self):
        result = parse_cobol(
            _ws_program("01  WS-SHARED IS EXTERNAL."),
            filename="reg.cbl",
        )
        item = _find_item(result, "WS-SHARED")
        assert item.to_dict()["is_external"] is True


# ===========================================================================
# FD / SD file-description clauses
# ===========================================================================


class TestFdClauseCapture:
    """FD clauses were skipped to the next level number; now captured."""

    def test_fixed_record_and_block(self):
        result = parse_cobol(
            _file_program(
                "FD  INFILE\n"
                "           BLOCK CONTAINS 0 RECORDS\n"
                "           RECORD CONTAINS 80 CHARACTERS\n"
                "           RECORDING MODE IS F\n"
                "           LABEL RECORDS ARE STANDARD\n"
                "           CODE-SET IS EBCDIC\n"
                "           DATA RECORD IS IN-REC.\n"
                "       01  IN-REC PIC X(80)."
            ),
            filename="reg.cbl",
        )
        assert result.success
        rec = _find_item(result, "IN-REC")
        assert rec is not None
        clauses = (rec._metadata or {}).get("fd_clauses")
        assert clauses is not None
        assert clauses["block_contains"]["max"] == 0
        assert clauses["block_contains"]["unit"] == "RECORDS"
        assert clauses["record"]["max"] == 80
        assert clauses["record"]["varying"] is False
        assert clauses["recording_mode"] == "F"
        assert clauses["label_records"] == "STANDARD"
        assert clauses["code_set"] == "EBCDIC"
        assert clauses["data_records"] == ["IN-REC"]

    def test_record_varying(self):
        result = parse_cobol(
            _file_program(
                "FD  VARFILE\n"
                "           RECORD IS VARYING IN SIZE FROM 10 TO 100 CHARACTERS\n"
                "               DEPENDING ON REC-LEN.\n"
                "       01  VAR-REC PIC X(100)."
            ),
            filename="reg.cbl",
        )
        assert result.success
        rec = _find_item(result, "VAR-REC")
        clauses = (rec._metadata or {}).get("fd_clauses")
        assert clauses["record"]["varying"] is True
        assert clauses["record"]["min"] == 10
        assert clauses["record"]["max"] == 100
        assert clauses["record"]["depending_on"] == "REC-LEN"

    def test_following_sections_still_parsed(self):
        """Capturing FD clauses must not swallow the following sections."""
        result = parse_cobol(
            _file_program("FD  MYFILE.\n       01  FILE-REC PIC X(80)."),
            filename="reg.cbl",
        )
        assert result.success
        # WORKING-STORAGE item from the wrapper must survive.
        assert _find_item(result, "WS-FLAG") is not None

    def test_numeric_operands_one_and_77_are_not_record_levels(self):
        """Operands like 1 and 77 are lexed as LEVEL_NUMBER but must be captured
        as clause operands, not mistaken for 01/77 record entries."""
        result = parse_cobol(
            _file_program(
                "FD  INFILE\n"
                "           BLOCK CONTAINS 1 RECORDS\n"
                "           RECORD CONTAINS 77 CHARACTERS.\n"
                "       01  IN-REC PIC X(77)."
            ),
            filename="reg.cbl",
        )
        assert result.success
        # No bogus ANONYMOUS-1 / ANONYMOUS-77 items leaked from the operands.
        names = [d.name for d in result.ast.find_all_by_type("DataItem")]
        assert not any(n.startswith("ANONYMOUS") for n in names)
        assert "IN-REC" in names
        clauses = (_find_item(result, "IN-REC")._metadata or {})["fd_clauses"]
        assert clauses["block_contains"]["max"] == 1
        assert clauses["record"]["max"] == 77


# ===========================================================================
# Edited PICTURE clauses
# ===========================================================================


class TestEditedPictureExtraction:
    """Edited pictures with decimals / currency / sign were truncated."""

    def test_floating_currency_picture(self):
        result = parse_cobol(
            _ws_program("01  WS-AMT PIC $$$,$$9.99."),
            filename="reg.cbl",
        )
        assert result.success
        item = _find_item(result, "WS-AMT")
        pic = item.picture_clause
        assert pic.pattern == "$$$,$$9.99"
        assert pic.is_numeric_edited is True
        assert pic.size == 10
        assert pic.decimal_digits == 2

    def test_zero_suppression_with_trailing_sign(self):
        result = parse_cobol(
            _ws_program("01  WS-BAL PIC ZZ,ZZ9.99-."),
            filename="reg.cbl",
        )
        assert result.success
        pic = _find_item(result, "WS-BAL").picture_clause
        assert pic.pattern == "ZZ,ZZ9.99-"
        assert pic.is_numeric_edited is True
        assert pic.size == 10

    def test_plain_numeric_not_edited(self):
        result = parse_cobol(
            _ws_program("01  WS-CNT PIC 9(5)."),
            filename="reg.cbl",
        )
        pic = _find_item(result, "WS-CNT").picture_clause
        assert pic.is_edited is False
        assert pic.size == 5


class TestEditedPictureModel:
    """Unit-level checks of PictureClause edited-pattern classification."""

    loc = SourceLocation(1, 1)

    def test_check_protect(self):
        pic = PictureClause("**,**9.99", self.loc)
        assert pic.is_numeric_edited is True
        assert pic.size == 9
        assert pic.decimal_digits == 2

    def test_alphanumeric_edited(self):
        pic = PictureClause("XXX/XXX", self.loc)
        assert pic.is_alphanumeric_edited is True
        assert pic.is_numeric_edited is False
        assert pic.size == 7

    def test_credit_symbol_two_positions(self):
        pic = PictureClause("9(5)CR", self.loc)
        assert pic.is_numeric_edited is True
        # five digits + CR (two positions)
        assert pic.size == 7

    def test_repeat_factor_digits_not_mistaken_for_insertion(self):
        # The 0 inside 9(10) must not flag the item as edited.
        pic = PictureClause("9(10)", self.loc)
        assert pic.is_edited is False
        assert pic.size == 10
