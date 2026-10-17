"""COPY ... REPLACING across line boundaries (#560) and the source map of a
REPLACING that changes the copybook's line count (#561).

#560: the REPLACING alternation ran over the copybook one line at a time,
so pseudo-text whose words the copybook splits across two lines was never
found -- silently. COBOL compares pseudo-text on the text-word stream, where
a line break is just a separator (the REPLACE statement already did).

#561: the replaced text was then expanded as if it *were* the copybook,
numbered from line 1, so a BY text holding more lines than the text it
replaced pushed every later copybook line to a higher number (past the end
of the file), and lint / xref / ``expand --source-map`` cited it.
"""

from __future__ import annotations

from pathlib import Path

from cobolparser import LintAnalyzer, expand_copybooks, parse_cobol_with_expansion
from cobolparser.analysis.lint import apply_source_map
from cobolparser.preprocess.copy_statement_parser import (
    apply_replacing_clauses,
    extract_copy_statements,
)
from cobolparser.preprocess.models import ReplacingClause

_ML = (
    "           05  ML-A     PIC X(5).\n"
    "           05  ML-B     PIC X(5).\n"
    "           05  ML-C     PIC X(5).\n"
)
_ML2 = _ML + "           05  ML-D     PIC X(5).\n"


def _program(copy: str, procedure: str = "           DISPLAY ML-A ML-B\n") -> str:
    return (
        "       IDENTIFICATION DIVISION.\n"
        "       PROGRAM-ID. ML.\n"
        "       DATA DIVISION.\n"
        "       WORKING-STORAGE SECTION.\n"
        "       01  REC.\n"
        f"{copy}"
        "       01  WS-UNUSED PIC X.\n"
        "       PROCEDURE DIVISION.\n"
        f"{procedure}"
        "           GOBACK.\n"
    )


_GROWING_COPY = (
    "           COPY ML REPLACING ==PIC X(5).== BY\n"
    "               ==PIC X(5).\n"
    "                 88 FLAG-ON VALUE 'Y'.==.\n"
)
_SPANNING_COPY = (
    "           COPY ML2 REPLACING ==ML-B PIC X(5). 05 ML-C==\n"
    "                           BY ==ML-BC PIC X(10). 05 ML-Z==.\n"
)


def _clauses(copy: str):  # type: ignore[no-untyped-def]
    [statement] = extract_copy_statements(copy)
    return statement.replacing_clauses


def _expanded(tmp_path: Path, copy: str, member: str, text: str):  # type: ignore[no-untyped-def]
    (tmp_path / f"{member}.cpy").write_text(text)
    source = _program(copy)
    result = expand_copybooks(
        source,
        copybook_paths=[str(tmp_path)],
        preserve_source_locations=True,
        source_file="ml.cbl",
    )
    lines = result.expanded_source.split("\n")
    return lines, result.source_location_map, result.statistics.warnings


def _member_lines(lines: list[str]) -> list[tuple[int, str]]:
    """The expanded copybook's lines (every ``05`` entry and its 88s)."""
    return [
        (number, line)
        for number, line in enumerate(lines, 1)
        if line.split()[:1] in (["05"], ["88"])
    ]


class TestReplacingAcrossLines:
    def test_pseudo_text_spanning_two_copybook_lines_matches(
        self, tmp_path: Path
    ) -> None:
        lines, _, warnings = _expanded(tmp_path, _SPANNING_COPY, "ML2", _ML2)
        words = " ".join(" ".join(line for _n, line in _member_lines(lines)).split())
        assert "05 ML-BC PIC X(10). 05 ML-Z PIC X(5)." in words
        assert "ML-B " not in words and "ML-C" not in words
        assert "ML-A" in words and "ML-D" in words
        assert warnings == []

    def test_data_items_see_the_replaced_names(self, tmp_path: Path) -> None:
        (tmp_path / "ML2.cpy").write_text(_ML2)
        result = parse_cobol_with_expansion(
            _program(_SPANNING_COPY, "           DISPLAY ML-BC\n"),
            "ml3.cbl",
            copybook_paths=[str(tmp_path)],
        )
        assert result.ast is not None
        names = [
            item.name
            for item in result.ast.find_all_by_type("CobolDataItem")
            if getattr(item, "level", None) == 5
        ]
        assert names == ["ML-A", "ML-BC", "ML-Z", "ML-D"]

    def test_comma_separator_at_end_of_line(self) -> None:
        out = apply_replacing_clauses(
            " 05 A PIC X,\n VALUE 'Q'.\n",
            _clauses("       COPY M REPLACING ==X VALUE== BY ==Y VALUE==.\n"),
            indicator_position=0,
        )
        assert out == " 05 A PIC Y VALUE 'Q'.\n"

    def test_never_matches_into_a_comment_line(self) -> None:
        content = " 05 A PIC X.\n* 05 B PIC X.\n 05 C PIC X.\n"
        out = apply_replacing_clauses(
            content,
            _clauses("       COPY M REPLACING ==B PIC X.== BY ==Z PIC Y.==.\n"),
            indicator_position=0,
        )
        assert out == content

    def test_word_inside_a_literal_is_left_alone_across_lines(self) -> None:
        out = apply_replacing_clauses(
            " 05 A PIC X(4) VALUE\n 'ML-B'.\n 05 ML-B PIC X.\n",
            _clauses("       COPY M REPLACING ==ML-B== BY ==NEW==.\n"),
            indicator_position=0,
        )
        assert out == " 05 A PIC X(4) VALUE\n 'ML-B'.\n 05 NEW PIC X.\n"


class TestReplacingLineOrigins:
    def test_line_origins_follow_added_and_removed_lines(self) -> None:
        origins: list[int] = []
        out = apply_replacing_clauses(
            " A\n B\n C\n D\n",
            [ReplacingClause("B", "X\n Y"), ReplacingClause("C D", "Q")],
            indicator_position=0,
            line_origins=origins,
        )
        assert out == " A\n X\n Y\n Q\n"
        # X and Y came from line 2; Q replaced lines 3-4 and keeps 3.
        assert origins == [1, 2, 2, 3, 5]

    def test_no_match_gives_identity_origins(self) -> None:
        origins: list[int] = []
        apply_replacing_clauses(
            " A\n B\n",
            _clauses("       COPY M REPLACING ==Z== BY ==Q==.\n"),
            indicator_position=0,
            line_origins=origins,
        )
        assert origins == [1, 2, 3]

    def test_growing_by_text_keeps_copybook_line_numbers(self, tmp_path: Path) -> None:
        lines, source_map, _ = _expanded(tmp_path, _GROWING_COPY, "ML", _ML)
        by_text = {
            line.split()[1]: source_map[number]
            for number, line in _member_lines(lines)
            if line.split()[0] == "05"
        }
        assert {name: loc[1] for name, loc in by_text.items()} == {
            "ML-A": 1,
            "ML-B": 2,
            "ML-C": 3,
        }
        flag_lines = sorted(
            source_map[number][1]
            for number, line in enumerate(lines, 1)
            if "FLAG-ON" in line
        )
        assert flag_lines == [1, 2, 3]
        # Every program line after the COPY keeps its own number too.
        unused = next(n for n, line in enumerate(lines, 1) if "WS-UNUSED" in line)
        assert source_map[unused] == ("ml.cbl", 9)

    def test_spanning_replacement_maps_to_its_first_line(self, tmp_path: Path) -> None:
        lines, source_map, _ = _expanded(tmp_path, _SPANNING_COPY, "ML2", _ML2)
        located = {
            word: source_map[number][1]
            for number, line in _member_lines(lines)
            for word in ("ML-A", "ML-BC", "ML-D")
            if word in line.split()
        }
        assert located == {"ML-A": 1, "ML-BC": 2, "ML-D": 4}

    def test_lint_cites_the_real_copybook_line(self, tmp_path: Path) -> None:
        (tmp_path / "ML.cpy").write_text(_ML)
        result = parse_cobol_with_expansion(
            _program(_GROWING_COPY),
            str(tmp_path / "ml.cbl"),
            copybook_paths=[str(tmp_path)],
        )
        assert result.ast is not None
        report = apply_source_map(
            LintAnalyzer(["unused-variables"]).analyze(result.ast),
            result.expansion_source_map,
        )
        [finding] = [f for f in report.findings if f.symbol == "ML-C"]
        assert str(finding.origin_file).endswith("ML.cpy")
        assert finding.origin_line == 3
