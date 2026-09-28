"""Regression tests for the 2026-09-28 accelerator / fixed-format audit.

Each class covers one finding and runs against both implementations it
touches: the pure-Python normalizer and whichever one the package exposes
(the Cython ``_preprocess_fast`` when compiled), and the DATA DIVISION clause
loop with and without the Cython ``_data_fast`` helper.
"""

from __future__ import annotations

import json

import pytest

import cobolparser.parsers.divisions.data_clauses as data_clauses
from cobolparser import parse_cobol
from cobolparser.preprocess import _normalize_fixed_format_pure, normalize_fixed_format

NORMALIZERS = [
    pytest.param(_normalize_fixed_format_pure, id="pure"),
    pytest.param(normalize_fixed_format, id="package"),
]

# ``fast`` only differs from ``pure`` when the extension is compiled; it is
# still run otherwise (both then take the pure-Python loop).
DATA_PATHS = [pytest.param(True, id="fast"), pytest.param(False, id="pure")]


@pytest.fixture
def data_path(request, monkeypatch):
    monkeypatch.setattr(
        data_clauses,
        "_HAS_DATA_FAST",
        bool(request.param and data_clauses._fast_data_item_clauses is not None),
    )
    return request.param


def _prog(*ws: str) -> str:
    return (
        "       IDENTIFICATION DIVISION.\n"
        "       PROGRAM-ID. T.\n"
        "       DATA DIVISION.\n"
        "       WORKING-STORAGE SECTION.\n"
        + "".join(line + "\n" for line in ws)
        + "       PROCEDURE DIVISION.\n"
        "           STOP RUN.\n"
    )


def _items(result) -> dict[str, dict]:
    out = {}
    for item in result.ast.find_all_by_type("CobolDataItem"):
        out[item.name] = item.to_dict()
    return out


def _to_72(record: str) -> str:
    return " " * (72 - len(record))


# ---------------------------------------------------------------------------
# 1. _data_fast: an OCCURS count past INT_MAX raised OverflowError
# ---------------------------------------------------------------------------


class TestOccursCountBeyondCInt:
    """The compiled clause loop held OCCURS counts in C ``int``s. ``int()`` of
    a count past 2**31-1 then raised ``OverflowError`` -- not one of the
    ``TypeError``/``ValueError`` the loop guards against -- and the division
    loop recovered by abandoning the whole DATA DIVISION: every item gone,
    one "value too large to convert to int" error at line 1. The pure-Python
    walker keeps the count as a Python int."""

    SRC = _prog(
        "       01 WS-T.",
        "          05 WS-E PIC X OCCURS 3000000000 TIMES.",
        "          05 WS-F PIC X OCCURS 1 TO 2147483648 TIMES DEPENDING ON WS-N.",
        "       01 WS-N PIC 9(10).",
    )

    @pytest.mark.parametrize("data_path", DATA_PATHS, indirect=True)
    def test_large_counts_keep_the_division(self, data_path):
        result = parse_cobol(self.SRC)
        assert result.errors == []
        items = _items(result)
        assert set(items) == {"WS-T", "WS-E", "WS-F", "WS-N"}
        assert items["WS-E"]["occurs_clause"]["max_times"] == 3000000000
        assert items["WS-F"]["occurs_clause"]["min_times"] == 1
        assert items["WS-F"]["occurs_clause"]["max_times"] == 2147483648

    def test_fast_and_pure_agree(self, monkeypatch):
        dumps = []
        for fast in (True, False):
            monkeypatch.setattr(
                data_clauses,
                "_HAS_DATA_FAST",
                fast and data_clauses._fast_data_item_clauses is not None,
            )
            dumps.append(json.dumps(parse_cobol(self.SRC).ast.to_dict(), default=str))
        assert dumps[0] == dumps[1]
