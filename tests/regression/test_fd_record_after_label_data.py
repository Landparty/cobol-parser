"""Regression: RECORD CONTAINS after LABEL RECORDS / DATA RECORD (issue #401).

The FD clause scanner kept a RECORD that follows LABEL or DATA from starting a
new clause, so the RECORD of "LABEL RECORDS" / "DATA RECORD" stayed part of
that clause. The guard applied to *every* later RECORD too, so a RECORD
CONTAINS written after either clause was swallowed and the record length lost.
"""

from __future__ import annotations

from typing import Any

import pytest

from cobolparser import parse_cobol
from cobolparser.generators import ProgramLayoutIndex


def _program(fd_clauses: str) -> str:
    return (
        "       IDENTIFICATION DIVISION.\n"
        "       PROGRAM-ID. R401.\n"
        "       ENVIRONMENT DIVISION.\n"
        "       INPUT-OUTPUT SECTION.\n"
        "       FILE-CONTROL.\n"
        "           SELECT F1 ASSIGN TO DD1.\n"
        "       DATA DIVISION.\n"
        "       FILE SECTION.\n"
        "       FD  F1\n"
        f"{fd_clauses}"
        "       01  F1-REC PIC X(30).\n"
        "       PROCEDURE DIVISION.\n"
        "           STOP RUN.\n"
    )


def _fd(fd_clauses: str) -> tuple[dict[str, Any], ProgramLayoutIndex]:
    result = parse_cobol(_program(fd_clauses))
    assert result.ast is not None
    record = result.ast.get_division("DATA").sections[0].data_items[0]
    return record.get_metadata("fd_clauses"), ProgramLayoutIndex.build(result.ast)


@pytest.mark.parametrize(
    "fd_clauses",
    [
        "           LABEL RECORDS ARE STANDARD\n"
        "           RECORD CONTAINS 30 CHARACTERS.\n",
        "           LABEL RECORD IS OMITTED RECORD CONTAINS 30.\n",
        "           DATA RECORD IS F1-REC RECORD CONTAINS 30.\n",
        "           DATA RECORDS ARE F1-REC\n" "           RECORD CONTAINS 30.\n",
        "           LABEL RECORDS ARE STANDARD\n"
        "           DATA RECORD IS F1-REC\n"
        "           RECORD CONTAINS 30 CHARACTERS.\n",
        # The order that already worked must keep working.
        "           RECORD CONTAINS 30 CHARACTERS\n"
        "           LABEL RECORDS ARE STANDARD.\n",
    ],
)
def test_record_contains_survives_any_clause_order(fd_clauses: str) -> None:
    clauses, index = _fd(fd_clauses)
    assert clauses["record"] == {"varying": False, "min": None, "max": 30}
    facts = index.file_facts("F1")
    assert facts is not None
    assert facts.record_contains == 30


def test_data_records_do_not_absorb_a_following_record_clause() -> None:
    clauses, _ = _fd("           DATA RECORD IS F1-REC RECORD CONTAINS 30.\n")
    assert clauses["data_records"] == ["F1-REC"]


def test_label_records_value_is_unchanged() -> None:
    clauses, _ = _fd(
        "           LABEL RECORDS ARE STANDARD\n"
        "           RECORD CONTAINS 30 CHARACTERS.\n"
    )
    assert clauses["label_records"] == "STANDARD"


def test_record_varying_after_label_records() -> None:
    clauses, index = _fd(
        "           LABEL RECORDS ARE STANDARD\n"
        "           RECORD VARYING IN SIZE FROM 10 TO 30\n"
        "           DEPENDING ON WS-LEN.\n"
    )
    assert clauses["record"]["varying"] is True
    assert (clauses["record"]["min"], clauses["record"]["max"]) == (10, 30)
    facts = index.file_facts("F1")
    assert facts is not None
    assert (facts.record_contains_min, facts.record_contains_max) == (10, 30)
