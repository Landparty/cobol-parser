"""Regression (#502): a file opening with ``>>SOURCE FORMAT FREE``.

1. The directive was applied, yet the parse warned "unknown compiler
   directive '>>SOURCE FORMAT FREE' ignored": the conditional-compilation
   pass only recognised ``>>SOURCE`` when asked to keep it.
2. Written in column 1 above 7-space-indented lines, the directive sat in
   the fixed-format sequence area: format detection said fixed, the
   directive was never seen and was sliced to ``E FORMAT FREE``, a literal
   past column 72 was cut, and the whole parse failed with "No recognizable
   COBOL division found near 'E'". Option (a) of the issue: a ``>>SOURCE ...
   FREE`` that is the first non-blank line is decisive in any column.
"""

from __future__ import annotations

import pytest

from cobolparser import parse_cobol
from cobolparser.plugins.core import ErrorRecoveryMode
from cobolparser.preprocess import preprocess_conditional_compilation
from cobolparser.preprocess.source_format import detect_fixed_format

LITERAL = "THIS LITERAL RUNS PAST COLUMN SEVENTY TWO OF THE LINE - XYZ"
BODY = [
    "       IDENTIFICATION DIVISION.",
    "       PROGRAM-ID. FREE5.",
    "       DATA DIVISION.",
    "       WORKING-STORAGE SECTION.",
    f"       01 WS-A PIC X(80) VALUE '{LITERAL}'.",
    "       PROCEDURE DIVISION.",
    "           DISPLAY WS-A.",
    "           STOP RUN.",
]


@pytest.mark.parametrize(
    "directive",
    [
        ">>SOURCE FORMAT FREE",  # column 1
        "       >>SOURCE FORMAT FREE",  # column 8
        "      >>SOURCE FORMAT IS FREE",  # column 7
    ],
    ids=["column-1", "column-8", "column-7"],
)
def test_parses_clean_with_no_warning(directive: str) -> None:
    result = parse_cobol(
        "\n".join([directive, *BODY]) + "\n",
        error_recovery=ErrorRecoveryMode.COLLECT_ALL,
    )

    assert result.errors == []
    assert result.warnings == []
    assert result.ast is not None
    assert result.ast.program_name == "FREE5"
    item = result.ast.find_all_by_type("DataItem")[0]
    assert LITERAL in str(item.value_clause)


def test_first_line_free_directive_decides_free_form() -> None:
    assert not detect_fixed_format("\n".join([">>SOURCE FORMAT FREE", *BODY]))


def test_a_later_column_1_directive_does_not_decide() -> None:
    # Only the opening line is decisive; a fixed file stays fixed.
    source = "\n".join([*BODY[:2], ">>SOURCE FORMAT FREE", *BODY[2:4]])
    assert detect_fixed_format(source)


def test_conditional_pass_does_not_call_source_unknown() -> None:
    warnings: list[str] = []
    out = preprocess_conditional_compilation(
        ">>SOURCE FORMAT FREE\nDISPLAY 'X'.\n", warnings=warnings
    )

    assert warnings == []
    assert ">>SOURCE" not in out


def test_other_unknown_directives_still_warn() -> None:
    warnings: list[str] = []
    preprocess_conditional_compilation(">>CALLINTERFACE DLL\n", warnings=warnings)

    assert any("unknown compiler directive" in w for w in warnings)
