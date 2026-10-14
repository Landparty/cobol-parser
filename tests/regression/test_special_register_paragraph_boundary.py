"""Regression tests for issue #390: a special register (``RETURN-CODE``,
``TALLY``, ...) or a reserved word (``RUN``) alone on its own line was read
as a paragraph header by
:func:`cobolparser.parsers.statements._utils.looks_like_paragraph_boundary`.

The boundary check only ruled out names declared in the DATA DIVISION. A
special register is never declared there, so ``MOVE 0`` / ``TO`` /
``RETURN-CODE.`` with every word at the verb's column produced a MOVE with
no target, an error, and a phantom paragraph named ``RETURN-CODE``.

Three exclusions now apply: special registers, reserved words that lex as
plain identifiers, and -- in fixed-format source -- any token in Area B,
where no paragraph header can begin.
"""

import pytest

from cobolparser import parse_cobol
from cobolparser.parsers.statements._utils import (
    NON_PARAGRAPH_RESERVED_WORDS,
    SPECIAL_REGISTERS,
)
from cobolparser.plugins.core import ErrorRecoveryMode


def _parse(source: str, free_form: bool = False):
    return parse_cobol(
        source, error_recovery=ErrorRecoveryMode.COLLECT_ALL, free_form=free_form
    )


def _paragraph_names(result) -> list[str]:
    return [p.paragraph_name for p in result.ast.find_all_by_type("CobolParagraph")]


def _program(body: str, data: str = "") -> str:
    return (
        "       IDENTIFICATION DIVISION.\n"
        "       PROGRAM-ID. REG390.\n"
        "       DATA DIVISION.\n"
        "       WORKING-STORAGE SECTION.\n"
        "       01 WS-X PIC 9.\n"
        f"{data}"
        "       PROCEDURE DIVISION.\n"
        "       MAIN-PARA.\n"
        f"{body}"
        "           STOP RUN.\n"
    )


class TestSpecialRegisterOnOwnLine:
    """The reproduction from the issue, and its siblings."""

    @pytest.mark.parametrize(
        "register",
        [
            "RETURN-CODE",
            "TALLY",
            "SORT-RETURN",
            "LINAGE-COUNTER",
            "XML-CODE",
            "JSON-CODE",
        ],
    )
    def test_move_to_register_on_own_line(self, register: str) -> None:
        source = _program(
            "           MOVE 0\n" "           TO\n" f"           {register}.\n"
        )
        result = _parse(source)
        assert result.errors == []
        assert result.warnings == []
        assert _paragraph_names(result) == ["MAIN-PARA"]
        moves = result.ast.find_all_by_type("MoveStatement")
        assert [m.targets for m in moves] == [[register]]

    def test_register_alone_in_free_format(self) -> None:
        # No Area A/B in free format: the register exclusion carries it.
        source = (
            "IDENTIFICATION DIVISION.\n"
            "PROGRAM-ID. REG390.\n"
            "PROCEDURE DIVISION.\n"
            "MAIN-PARA.\n"
            "MOVE 0\n"
            "TO\n"
            "RETURN-CODE.\n"
            "STOP RUN.\n"
        )
        result = _parse(source, free_form=True)
        assert result.errors == []
        assert _paragraph_names(result) == ["MAIN-PARA"]
        moves = result.ast.find_all_by_type("MoveStatement")
        assert [m.targets for m in moves] == [["RETURN-CODE"]]

    def test_display_register_on_own_line(self) -> None:
        source = _program("           DISPLAY 'RC='\n           RETURN-CODE.\n")
        result = _parse(source)
        assert result.errors == []
        assert result.warnings == []
        assert _paragraph_names(result) == ["MAIN-PARA"]

    def test_sets_cover_the_issue_names(self) -> None:
        for name in ("RETURN-CODE", "SORT-RETURN", "TALLY", "WHEN-COMPILED"):
            assert name in SPECIAL_REGISTERS
        assert "RUN" in NON_PARAGRAPH_RESERVED_WORDS
        # These open a real structural unit at the paragraph-header shape.
        for name in ("DECLARATIVES", "FACTORY", "OBJECT"):
            assert name not in NON_PARAGRAPH_RESERVED_WORDS


class TestReservedWordOnOwnLine:
    def test_set_to_true_on_own_line(self) -> None:
        source = _program(
            "           SET WS-FLAG\n" "           TO\n" "           TRUE.\n",
            data="       01 WS-SW PIC X.\n           88 WS-FLAG VALUE 'Y'.\n",
        )
        result = _parse(source)
        assert result.errors == []
        assert _paragraph_names(result) == ["MAIN-PARA"]


class TestFixedFormatAreaB:
    """In fixed format a paragraph header must start in Area A."""

    def test_undeclared_operand_in_area_b_is_not_a_paragraph(self) -> None:
        # CUST-ID is not declared (as if from an unexpanded COPY), so only
        # the Area B rule keeps it an operand.
        source = _program("           MOVE 0\n           TO\n           CUST-ID.\n")
        result = _parse(source)
        assert _paragraph_names(result) == ["MAIN-PARA"]
        moves = result.ast.find_all_by_type("MoveStatement")
        assert [m.targets for m in moves] == [["CUST-ID"]]

    def test_area_a_paragraph_after_missing_period_still_caught(self) -> None:
        # Control: a real header in Area A still ends the period-less MOVE.
        source = _program(
            "           MOVE 0 TO WS-X\n" "       NEXT-PARA.\n" "           CONTINUE.\n"
        )
        result = _parse(source)
        assert _paragraph_names(result) == ["MAIN-PARA", "NEXT-PARA"]
        assert any("NEXT-PARA" in w for w in result.warnings)

    def test_free_format_indented_name_is_still_a_boundary(self) -> None:
        # Free format has no Area B, so an indented undeclared name in the
        # header shape stays a boundary, as before.
        source = (
            "IDENTIFICATION DIVISION.\n"
            "PROGRAM-ID. REG390.\n"
            "PROCEDURE DIVISION.\n"
            "MAIN-PARA.\n"
            "    DISPLAY 'A'\n"
            "    NEXT-PARA.\n"
            "    STOP RUN.\n"
        )
        result = _parse(source, free_form=True)
        assert "NEXT-PARA" in _paragraph_names(result)
