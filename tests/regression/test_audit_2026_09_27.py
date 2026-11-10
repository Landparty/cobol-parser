"""Regressions for the patch-release batch from the 2026-09-27 audit (reports/audit-2026-09-27.md).

- 2.1: a typed literal in a VALUE clause lost its prefix, so ``VALUE X"4142"``
  generated the text ``41`` instead of the two bytes ``AB``.
- S1: the COPY statement scanner stepped through whitespace one character at
  a time, re-skipping the whole run at every step -- quadratic, so a file of
  a few thousand blank lines took minutes.
- S2: ``max_total_size`` was charged before REPLACING, so a REPLACING BY text
  longer than its operand could multiply a member past the limit unchecked.

Each test names the thing that used to be silently wrong, so a reappearance
is legible from the failure alone rather than from a diff.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from cobolparser import parse_cobol
from cobolparser._literals import typed_literal_content
from cobolparser.generators import CopybookDataGenerator, DataGeneratorOptions
from cobolparser.parser import parse_cobol_with_expansion
from cobolparser.preprocess import TotalExpansionSizeExceededError
from cobolparser.preprocess.copy_statement_parser import CopyStatementLexer
from cobolparser.preprocess.copybook_expander import expand_copybooks

_PROGRAM = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. HEXV.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-REC.
           05  WS-HEX   PIC X(2) VALUE X"4142".
           05  WS-ALL   PIC X(4) VALUE ALL X"41".
           05  WS-TXT   PIC X(4) VALUE "4142".
       PROCEDURE DIVISION.
           STOP RUN.
"""


def _item(name: str):
    result = parse_cobol(_PROGRAM, filename="hexv.cbl")
    assert result.success, result.errors
    for item in result.ast.find_all_by_type("CobolDataItem"):
        if item.name == name:
            return item
    raise AssertionError(f"{name} not found")


# ---------------------------------------------------------------------------
# 2.1 -- typed literals in VALUE clauses
# ---------------------------------------------------------------------------


class TestTypedValueLiteral:
    def test_hex_value_clause_keeps_its_prefix(self):
        assert _item("WS-HEX").value_clause == 'X"4142"'

    def test_all_hex_value_clause_keeps_its_prefix(self):
        assert _item("WS-ALL").value_clause == 'ALL X"41"'

    def test_plain_literal_value_clause_is_unchanged(self):
        # The hex literal must stay distinguishable from this one.
        assert _item("WS-TXT").value_clause == '"4142"'

    def test_gen_data_writes_the_bytes_a_hex_value_stands_for(self, tmp_path: Path):
        cpy = tmp_path / "HEXV.cpy"
        cpy.write_text(
            "       01  REC.\n"
            '           05  A  PIC X(2) VALUE X"4142".\n'
            '           05  B  PIC X(4) VALUE ALL X"41".\n'
            '           05  C  PIC X(4) VALUE "4142".\n'
        )
        dataset = CopybookDataGenerator(
            DataGeneratorOptions(rows=1, seed=1)
        ).generate_from_file(str(cpy))
        assert dataset.rows[0] == ["AB", "AAAA", "4142"]

    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ('X"4142"', "AB"),
            ("x'41'", "A"),
            ('NX"00410042"', "AB"),
            ('UX"C3A9"', "é"),
            ('Z"AB"', "AB\x00"),
            ('N"AB"', "AB"),
            ('X"4G"', "4G"),  # not hex: the lexer already warned
            ('"4142"', None),  # not a typed literal
            ("WS-X", None),
        ],
    )
    def test_typed_literal_content(self, text: str, expected: str | None):
        assert typed_literal_content(text) == expected


# ---------------------------------------------------------------------------
# S1 -- COPY scanner is linear in whitespace runs
# ---------------------------------------------------------------------------


class TestCopyScannerLinear:
    def test_long_whitespace_run_scans_quickly(self):
        # 4,000 blank lines took ~170 s before the fix; linear, it is ms.
        source = "       COPY OK.\n" + "      \n" * 4000 + "       COPY TWO.\n"
        start = time.perf_counter()
        statements = CopyStatementLexer(source).tokenize_copy_statements()
        elapsed = time.perf_counter() - start
        assert [s.member_name for s in statements] == ["OK", "TWO"]
        assert elapsed < 2.0, f"scan took {elapsed:.2f}s"

    @pytest.mark.parametrize(
        "source",
        [
            "GOODCOPY. COPY A.",
            "X-COPY COPYRIGHT COPY B.",
            "MOVE 'COPY Z.' TO X. COPY C.",
            "*> COPY Y.\n COPY D.",
            ",;,; COPY E.",
        ],
    )
    def test_run_skipping_keeps_word_boundaries(self, source: str):
        statements = CopyStatementLexer(source).tokenize_copy_statements()
        assert len(statements) == 1
        assert statements[0].member_name in {"A", "B", "C", "D", "E"}

    def test_expansion_of_blank_heavy_program_is_fast(self, tmp_path: Path):
        (tmp_path / "OK.cpy").write_text("       01  X PIC X.\n")
        source = (
            "       IDENTIFICATION DIVISION.\n"
            "       PROGRAM-ID. T.\n"
            "       DATA DIVISION.\n"
            "       WORKING-STORAGE SECTION.\n"
            "       COPY OK.\n" + "      \n" * 2000 + "       PROCEDURE DIVISION.\n"
            "           STOP RUN.\n"
        )
        start = time.perf_counter()
        result = parse_cobol_with_expansion(
            source, "t.cbl", copybook_paths=[str(tmp_path)]
        )
        elapsed = time.perf_counter() - start
        assert result.ast is not None
        assert elapsed < 5.0, f"expansion took {elapsed:.2f}s (was ~40 s)"


# ---------------------------------------------------------------------------
# S2 -- REPLACING growth counts toward max_total_size
# ---------------------------------------------------------------------------


class TestReplacingGrowthIsCharged:
    def _setup(self, tmp_path: Path) -> str:
        lines = ["       01  G."] + ["           05  XX PIC X."] * 500
        (tmp_path / "BIG.cpy").write_text("\n".join(lines) + "\n")
        long_text = "A" * 40  # the line stays inside columns 8-72
        return (
            "       IDENTIFICATION DIVISION.\n"
            "       PROGRAM-ID. T.\n"
            "       DATA DIVISION.\n"
            "       WORKING-STORAGE SECTION.\n"
            "       COPY BIG REPLACING\n"
            f"           ==XX== BY =={long_text}==.\n"
            "       PROCEDURE DIVISION.\n"
            "           STOP RUN.\n"
        )

    def test_growth_past_the_limit_raises(self, tmp_path: Path):
        source = self._setup(tmp_path)
        # The raw member is ~13 KB and fits; after REPLACING it is ~32 KB.
        with pytest.raises(TotalExpansionSizeExceededError):
            expand_copybooks(source, [str(tmp_path)], max_total_size=20_000)

    def test_growth_within_the_limit_is_counted(self, tmp_path: Path):
        source = self._setup(tmp_path)
        result = expand_copybooks(source, [str(tmp_path)], max_total_size=1_000_000)
        raw = (tmp_path / "BIG.cpy").stat().st_size
        assert result.statistics.total_bytes_processed > raw + len(source)
