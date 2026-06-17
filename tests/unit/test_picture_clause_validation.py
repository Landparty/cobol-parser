"""Tests for PICTURE clause validation.

``PictureClause`` parses the pattern leniently (it never raises) but now also
validates it, exposing ``is_valid`` / ``validation_errors`` and surfacing both
in ``to_dict()``. The checks flag only unambiguously illegal pictures so valid
-- including unusual but legal -- pictures are never rejected.
"""

import pytest

from cobolparser import parse_cobol
from cobolparser.models.ast_base import SourceLocation
from cobolparser.models.data_items import PictureClause

_LOC = SourceLocation(1, 1)


def _pic(pattern: str) -> PictureClause:
    return PictureClause(pattern, _LOC)


class TestValidPictures:
    """Legal pictures must be reported as valid with no errors."""

    @pytest.mark.parametrize(
        "pattern",
        [
            "X",
            "X(10)",
            "A(15)",
            "9",
            "9(5)",
            "S9(7)",
            "S9(5)V99",
            "9(7)V99",
            "S9V99",
            "PPP9",
            "9PPP",
            "ZZ9.99-",
            "$$,$$9.99",
            "-ZZZ9",
            "99/99/99",
            "99(3)",  # repeat factor following a digit symbol
            "N(4)",  # national
            "G(3)",  # DBCS
            "999CR",
            "999DB",
        ],
    )
    def test_valid_pattern(self, pattern):
        pic = _pic(pattern)
        assert pic.is_valid is True
        assert pic.validation_errors == []


class TestInvalidPictures:
    """Illegal pictures must be flagged with a descriptive reason."""

    @pytest.mark.parametrize(
        ("pattern", "needle"),
        [
            ("", "empty"),
            ("   ", "empty"),
            ("9(0)", "repeat count"),
            ("9(A)", "repeat count"),
            ("9(3", "unbalanced"),
            ("9V9V9", "more than one 'V'"),
            ("99.9V9", "both 'V' and a decimal point"),
            ("9.9.9", "more than one decimal point"),
            ("9S9", "leftmost"),
            ("S9S9", "more than one 'S'"),
            ("X(10)Q", "invalid character 'Q'"),
            ("(5)9", "must follow a picture symbol"),
        ],
    )
    def test_invalid_pattern(self, pattern, needle):
        pic = _pic(pattern)
        assert pic.is_valid is False
        assert pic.validation_errors
        assert any(
            needle in msg for msg in pic.validation_errors
        ), pic.validation_errors


class TestValidationDoesNotBreakParsing:
    """A bad picture is flagged but still parsed and never aborts the parse."""

    def test_lenient_size_still_computed(self):
        pic = _pic("9V9V9")
        assert pic.is_valid is False
        # Lenient parse still produced size/digit info.
        assert pic.size is not None

    def test_to_dict_exposes_validity(self):
        pic = _pic("X(10)Q")
        d = pic.to_dict()
        assert d["is_valid"] is False
        assert d["validation_errors"]

    def test_to_dict_valid_picture(self):
        d = _pic("S9(5)V99").to_dict()
        assert d["is_valid"] is True
        assert d["validation_errors"] == []


class TestValidationThroughFullParse:
    """Validation is reachable on the AST produced by ``parse_cobol``."""

    def test_invalid_picture_flagged_on_ast(self):
        source = """
               IDENTIFICATION DIVISION.
               PROGRAM-ID. PICTEST.
               DATA DIVISION.
               WORKING-STORAGE SECTION.
               01 WS-GOOD PIC S9(5)V99.
               01 WS-BAD  PIC 9V9V9.
               PROCEDURE DIVISION.
                   STOP RUN.
        """
        result = parse_cobol(source)
        assert result.ast is not None
        # The bad picture does not prevent a successful parse.
        pics = {
            item.name: item.picture_clause
            for item in result.ast.find_all_by_type("DataItem")
            if getattr(item, "picture_clause", None) is not None
        }
        assert pics["WS-GOOD"].is_valid is True
        assert pics["WS-BAD"].is_valid is False
