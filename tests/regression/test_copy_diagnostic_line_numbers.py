"""Regression (#256): COPY diagnostics name the line of the original file.

The copybook expander scans for COPY statements *after* merging fixed-format
continuation records, and counted lines in that merged text: two continued
literals above a broken ``COPY QR REPLACING X BY Y`` (no period) at file line
12 made it report line 10. The parser's own un-expanded-COPY strip pass,
run over the expanded text, reported a third coordinate system, labelled
``<main>`` rather than the file. NIST SM202A put one COPY at 497 and 513
(file line 501).

Both now report the line in the original file, and the two diagnostics
collapse into one. (SM202A itself expands cleanly since #253, so the
synthetic repro below stands in for it.)
"""

from __future__ import annotations

import re
from pathlib import Path

from cobolparser import expand_copybooks, parse_cobol_with_expansion

_CONTINUED = "       01 W{n} PIC X(50) VALUE '" + "A" * 42
_LINES = [
    "       IDENTIFICATION DIVISION.",
    "       PROGRAM-ID. T1.",
    "       DATA DIVISION.",
    "       WORKING-STORAGE SECTION.",
    _CONTINUED.format(n=1),
    "      -    'BBBB'.",
    _CONTINUED.format(n=2),
    "      -    'BBBB'.",
    "       01 X PIC 9.",
    "       PROCEDURE DIVISION.",
    "       MAIN-PARA.",
    "           COPY QR REPLACING X BY Y",
    "           STOP RUN.",
]
_SOURCE = "\n".join(_LINES) + "\n"
_COPY_WARNING = re.compile(r"COPY (\S+) at line (\d+) has no terminating period")


def _copy_warnings(warnings: list[str]) -> list[tuple[str, int]]:
    found = []
    for warning in warnings:
        match = _COPY_WARNING.search(warning)
        if match:
            found.append((warning.split(":", 1)[0], int(match.group(2))))
    return found


def _copybooks(tmp_path: Path) -> Path:
    (tmp_path / "QR.cpy").write_text("           MOVE 1 TO X\n")
    return tmp_path


def test_source_has_the_copy_on_line_12() -> None:
    assert _LINES[11].strip().startswith("COPY QR")


def test_expander_reports_the_original_line(tmp_path: Path) -> None:
    expansion = expand_copybooks(
        _SOURCE, copybook_paths=[_copybooks(tmp_path)], source_file="x.cbl"
    )
    assert _copy_warnings(expansion.statistics.warnings) == [("x.cbl", 12)]


def test_parse_with_expansion_reports_line_12_once(tmp_path: Path) -> None:
    result = parse_cobol_with_expansion(_SOURCE, "x.cbl", [str(_copybooks(tmp_path))])
    assert _copy_warnings(result.warnings) == [("x.cbl", 12)]
