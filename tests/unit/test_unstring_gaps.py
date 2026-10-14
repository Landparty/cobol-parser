"""Regression tests for UNSTRING parser gaps (audit 2026-07-22).

Covers three previously-confirmed bugs in
``cobolparser/parsers/statements/string_unstring_parsers.py``:

1. A comma between INTO targets used to terminate target-list parsing,
   silently dropping every subsequent target (and its DELIMITER IN /
   COUNT IN clauses).
2. ``DELIMITED BY x OR y [OR z ...]`` only kept the first delimiter;
   ``OR`` and everything after it were discarded.
3. ``TALLYING IN tally-var`` was documented but never implemented --
   ``UnstringStatement`` had no field for it and the parser silently
   consumed the clause token-by-token via the catch-all.

Also re-verifies (does not regress) the previously-working single-target,
WITH POINTER, and ON OVERFLOW / NOT ON OVERFLOW cases.
"""

from cobolparser import parse_cobol


def _prog(procedure_stmts: str) -> str:
    return f"""\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TESTPROG.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-SRC      PIC X(30).
       01  WS-TGT-B    PIC X(10).
       01  WS-TGT-C    PIC X(10).
       01  WS-DELIM-B  PIC X(1).
       01  WS-COUNT-B  PIC 9(2).
       01  WS-DELIM-C  PIC X(1).
       01  WS-COUNT-C  PIC 9(2).
       01  WS-PTR      PIC 9(4).
       01  WS-TALLY    PIC 9(4).
       PROCEDURE DIVISION.
{procedure_stmts}
"""


class TestUnstringIntoTargetComma:
    """Bug 1: comma between INTO targets must not truncate the list."""

    def test_comma_separated_targets_each_keep_own_clauses(self):
        result = parse_cobol(
            _prog(
                '           UNSTRING WS-SRC DELIMITED BY ","\n'
                "               INTO WS-TGT-B DELIMITER IN WS-DELIM-B "
                "COUNT IN WS-COUNT-B,\n"
                "                    WS-TGT-C DELIMITER IN WS-DELIM-C "
                "COUNT IN WS-COUNT-C\n"
                "           END-UNSTRING."
            )
        )
        assert result.errors == []
        stmts = result.ast.find_statements("UNSTRING")
        assert len(stmts) == 1
        targets = stmts[0].into_targets
        assert len(targets) == 2
        assert targets[0] == {
            "target": "WS-TGT-B",
            "delimiter_var": "WS-DELIM-B",
            "count_var": "WS-COUNT-B",
        }
        assert targets[1] == {
            "target": "WS-TGT-C",
            "delimiter_var": "WS-DELIM-C",
            "count_var": "WS-COUNT-C",
        }

    def test_comma_separated_targets_without_clauses(self):
        result = parse_cobol(
            _prog(
                "           UNSTRING WS-SRC DELIMITED BY SPACE\n"
                "               INTO WS-TGT-B, WS-TGT-C\n"
                "           END-UNSTRING."
            )
        )
        assert result.errors == []
        stmts = result.ast.find_statements("UNSTRING")
        targets = stmts[0].into_targets
        assert [t["target"] for t in targets] == ["WS-TGT-B", "WS-TGT-C"]


class TestUnstringMultiDelimiter:
    """Bug 2: DELIMITED BY x OR y OR z must keep every delimiter."""

    def test_two_delimiters(self):
        result = parse_cobol(
            _prog(
                '           UNSTRING WS-SRC DELIMITED BY "," OR ";"\n'
                "               INTO WS-TGT-B\n"
                "           END-UNSTRING."
            )
        )
        assert result.errors == []
        stmts = result.ast.find_statements("UNSTRING")
        assert stmts[0].delimiters == ['","', '";"']

    def test_three_delimiters_with_all(self):
        result = parse_cobol(
            _prog(
                '           UNSTRING WS-SRC DELIMITED BY ALL "," OR ";" OR "-"\n'
                "               INTO WS-TGT-B\n"
                "           END-UNSTRING."
            )
        )
        assert result.errors == []
        stmts = result.ast.find_statements("UNSTRING")
        assert stmts[0].delimiters == ['","', '";"', '"-"']
        # The INTO target must still be reachable after the OR chain --
        # a regression here would mean OR consumed INTO too.
        assert stmts[0].into_targets[0]["target"] == "WS-TGT-B"


class TestUnstringTallying:
    """Bug 3: TALLYING IN tally-var must be captured, not swallowed."""

    def test_tallying_in_captured(self):
        result = parse_cobol(
            _prog(
                "           UNSTRING WS-SRC DELIMITED BY SPACE\n"
                "               INTO WS-TGT-B\n"
                "               TALLYING IN WS-TALLY\n"
                "           END-UNSTRING."
            )
        )
        assert result.errors == []
        stmts = result.ast.find_statements("UNSTRING")
        assert stmts[0].tallying_variable == "WS-TALLY"

    def test_no_tallying_leaves_field_none(self):
        result = parse_cobol(
            _prog(
                "           UNSTRING WS-SRC DELIMITED BY SPACE\n"
                "               INTO WS-TGT-B\n"
                "           END-UNSTRING."
            )
        )
        assert result.errors == []
        stmts = result.ast.find_statements("UNSTRING")
        assert stmts[0].tallying_variable is None
        assert "tallying_variable" not in stmts[0].to_dict()


class TestUnstringCombined:
    """All three fixes together, plus WITH POINTER and overflow clauses."""

    def test_full_combined_statement(self):
        result = parse_cobol(
            _prog(
                '           UNSTRING WS-SRC DELIMITED BY "," OR ";"\n'
                # 14 (not 15) leading spaces here: 15 pushed this line to 73
                # columns, one past the fixed-format code area (column 72),
                # which silently dropped the trailing comma -- see
                # tests/regression/test_fixed_format_word_boundary_overflow.py.
                "              INTO WS-TGT-B DELIMITER IN WS-DELIM-B "
                "COUNT IN WS-COUNT-B,\n"
                "                    WS-TGT-C DELIMITER IN WS-DELIM-C "
                "COUNT IN WS-COUNT-C\n"
                "               WITH POINTER WS-PTR\n"
                "               TALLYING IN WS-TALLY\n"
                "               ON OVERFLOW\n"
                '                   DISPLAY "OVERFLOW"\n'
                "               NOT ON OVERFLOW\n"
                '                   DISPLAY "OK"\n'
                "           END-UNSTRING."
            )
        )
        assert result.errors == []
        assert result.warnings == []
        stmts = result.ast.find_statements("UNSTRING")
        assert len(stmts) == 1
        stmt = stmts[0]

        assert stmt.source_operand == "WS-SRC"
        assert stmt.delimiters == ['","', '";"']

        targets = stmt.into_targets
        assert len(targets) == 2
        assert targets[0] == {
            "target": "WS-TGT-B",
            "delimiter_var": "WS-DELIM-B",
            "count_var": "WS-COUNT-B",
        }
        assert targets[1] == {
            "target": "WS-TGT-C",
            "delimiter_var": "WS-DELIM-C",
            "count_var": "WS-COUNT-C",
        }

        assert stmt.pointer_variable == "WS-PTR"
        assert stmt.tallying_variable == "WS-TALLY"

        assert stmt.on_overflow is not None
        assert len(stmt.on_overflow) == 1
        assert stmt.on_overflow[0].statement_type == "DISPLAY"

        assert stmt.not_on_overflow is not None
        assert len(stmt.not_on_overflow) == 1
        assert stmt.not_on_overflow[0].statement_type == "DISPLAY"

        d = stmt.to_dict()
        assert d["delimiters"] == ['","', '";"']
        assert len(d["into_targets"]) == 2
        assert d["pointer_variable"] == "WS-PTR"
        assert d["tallying_variable"] == "WS-TALLY"


class TestUnstringPreviouslyWorkingCases:
    """Re-verify cases that already worked before this fix (no regressions)."""

    def test_single_into_target(self):
        result = parse_cobol(
            _prog(
                "           UNSTRING WS-SRC DELIMITED BY SPACE\n"
                "               INTO WS-TGT-B.\n"
            )
        )
        assert result.errors == []
        stmts = result.ast.find_statements("UNSTRING")
        assert len(stmts) == 1
        assert stmts[0].into_targets == [
            {"target": "WS-TGT-B", "delimiter_var": None, "count_var": None}
        ]

    def test_with_pointer(self):
        result = parse_cobol(
            _prog(
                "           UNSTRING WS-SRC DELIMITED BY SPACE\n"
                "               INTO WS-TGT-B\n"
                "               WITH POINTER WS-PTR\n"
                "           END-UNSTRING."
            )
        )
        assert result.errors == []
        stmts = result.ast.find_statements("UNSTRING")
        assert stmts[0].pointer_variable == "WS-PTR"

    def test_on_overflow_and_not_on_overflow(self):
        result = parse_cobol(
            _prog(
                "           UNSTRING WS-SRC DELIMITED BY SPACE\n"
                "               INTO WS-TGT-B\n"
                "               ON OVERFLOW\n"
                '                   DISPLAY "OVERFLOW"\n'
                "               NOT ON OVERFLOW\n"
                '                   DISPLAY "OK"\n'
                "           END-UNSTRING."
            )
        )
        assert result.errors == []
        stmts = result.ast.find_statements("UNSTRING")
        stmt = stmts[0]
        assert stmt.on_overflow is not None and len(stmt.on_overflow) == 1
        assert stmt.not_on_overflow is not None and len(stmt.not_on_overflow) == 1

    def test_single_delimiter_still_works(self):
        result = parse_cobol(
            _prog(
                "           UNSTRING WS-SRC DELIMITED BY SPACE\n"
                "               INTO WS-TGT-B\n"
                "           END-UNSTRING."
            )
        )
        assert result.errors == []
        stmts = result.ast.find_statements("UNSTRING")
        assert stmts[0].delimiters == ["SPACE"]


class TestUnstringDelimitedByAll:
    """`DELIMITED BY ALL x` was accepted but the ALL flag was discarded, so
    `ALL SPACE` read the same as `SPACE` (runs of blanks produce empty
    fields only without ALL)."""

    def _unstring(self, stmt: str):
        result = parse_cobol(_prog(stmt))
        assert not result.errors
        (node,) = result.ast.find_all_by_type("UnstringStatement")
        return node

    def test_all_flag_recorded_per_delimiter(self):
        node = self._unstring(
            "           UNSTRING WS-SRC DELIMITED BY ',' OR ALL SPACE\n"
            "               INTO WS-TGT-B WS-TGT-C.\n"
        )
        assert node.delimiters == ['","', "SPACE"]
        assert node.delimiter_all == [False, True]
        assert node.to_dict()["delimiter_all"] == [False, True]

    def test_key_absent_without_all(self):
        node = self._unstring(
            "           UNSTRING WS-SRC DELIMITED BY ',' OR SPACE\n"
            "               INTO WS-TGT-B WS-TGT-C.\n"
        )
        assert node.delimiter_all == [False, False]
        assert "delimiter_all" not in node.to_dict()


class TestUnstringDelimitedWithoutBy:
    """``BY`` is optional after ``DELIMITED``; without it every delimiter
    used to be dropped."""

    def test_delimiters_kept_without_by(self):
        result = parse_cobol(
            _prog(
                "           UNSTRING WS-SRC DELIMITED ',' OR ALL SPACE\n"
                "               INTO WS-TGT-B WS-TGT-C.\n"
            )
        )
        assert not result.errors
        assert not result.warnings
        (node,) = result.ast.find_all_by_type("UnstringStatement")
        assert node.delimiters == ['","', "SPACE"]
        assert node.delimiter_all == [False, True]
        assert [t["target"] for t in node.into_targets] == ["WS-TGT-B", "WS-TGT-C"]
