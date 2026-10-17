"""Regression (#513): COPY REPLACING LEADING + TRAILING replace a word once.

Every REPLACING clause went into one regex alternation. A LEADING pattern
matches a word's start and a TRAILING one its end, so a word carrying both
(``XX-NAME-XX``) was rewritten twice (``CUST-NAME-END``). The standard
compares each word against the clauses in order and the first that fits
replaces it -- which is what REPLACE already did.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from cobolparser.preprocess import expand_copybooks
from cobolparser.preprocess.replace_statement import apply_replace_statements

LEADING = "LEADING ==XX== BY ==CUST=="
TRAILING = "TRAILING ==XX== BY ==END=="
HEAD = [
    "       IDENTIFICATION DIVISION.",
    "       PROGRAM-ID. RP.",
    "       DATA DIVISION.",
    "       WORKING-STORAGE SECTION.",
]


@pytest.fixture
def library(tmp_path: Path) -> str:
    (tmp_path / "LT.cpy").write_text(
        "       01 XX-REC.\n"
        "          05 XX-ID PIC 9(3).\n"
        "          05 XX-NAME-XX PIC X(5).\n"
        "          05 NAME-XX PIC X(5).\n"
    )
    return str(tmp_path)


def _names(text: str) -> list[str]:
    return re.findall(r"\b0[15] ([A-Z0-9-]+)", text)


def _via_copy(library: str, first: str, second: str) -> list[str]:
    source = "\n".join(
        [
            *HEAD,
            f"       COPY LT REPLACING {first}",
            f"                         {second}.",
            "       PROCEDURE DIVISION.",
        ]
    )
    return _names(expand_copybooks(source, [library]).expanded_source)


def _via_replace(library: str, first: str, second: str) -> list[str]:
    source = "\n".join(
        [
            *HEAD,
            f"       REPLACE {first}",
            f"               {second}.",
            "       COPY LT.",
            "       PROCEDURE DIVISION.",
        ]
    )
    expanded = expand_copybooks(source, [library]).expanded_source
    return _names(apply_replace_statements(expanded))


def test_leading_first_replaces_only_the_start(library: str) -> None:
    assert _via_copy(library, LEADING, TRAILING) == [
        "CUST-REC",
        "CUST-ID",
        "CUST-NAME-XX",
        "NAME-END",
    ]


def test_trailing_first_replaces_only_the_end(library: str) -> None:
    assert _via_copy(library, TRAILING, LEADING) == [
        "CUST-REC",
        "CUST-ID",
        "XX-NAME-END",
        "NAME-END",
    ]


@pytest.mark.parametrize(
    ("first", "second"), [(LEADING, TRAILING), (TRAILING, LEADING)]
)
def test_copy_and_replace_agree(library: str, first: str, second: str) -> None:
    assert _via_copy(library, first, second) == _via_replace(library, first, second)


@pytest.mark.parametrize(
    ("first", "second", "expected"),
    [
        # Clause order, not search-text length, decides: the longer
        # TRAILING ==XX== written second must not beat LEADING ==X==.
        ("LEADING ==X== BY ==A==", "TRAILING ==XX== BY ==B==", "AX-NAME-XX"),
        ("TRAILING ==X== BY ==B==", "LEADING ==XX== BY ==A==", "XX-NAME-XB"),
    ],
)
def test_written_order_decides_between_different_lengths(
    library: str, first: str, second: str, expected: str
) -> None:
    copied = _via_copy(library, first, second)
    assert copied[2] == expected
    assert copied == _via_replace(library, first, second)
