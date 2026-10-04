"""Regression (#252): a change tag in columns 1-6 of the header line.

Shops stamp change tags (``CHG001``, ``PR1234``) into the sequence area. On
the IDENTIFICATION DIVISION line itself such a tag

* made ``CobolParser._skip_to_identification_division`` miss the header
  (its regex only allowed digits / blanks in columns 1-6), so it blanked
  everything up to the *nested* program's header: the outer program was
  silently lost through ``CobolParser.parse`` and ``parse_files(workers=1)``
  while ``parse_cobol`` / ``parse_files(workers=2)`` were right;
* kept ``strip_compiler_directives`` in its "directive section" for the
  whole file, so a PROCEDURE DIVISION line whose code starts with
  ``PROCESS`` (``PROCESS SECTION.``) was blanked as a PROCESS option card.

Whether a line has a sequence area is now decided from column 7, not from
what columns 1-6 hold.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from cobolparser import CobolParser, parse_cobol, parse_files
from cobolparser.plugins.core import ErrorRecoveryMode
from cobolparser.preprocess import strip_compiler_directives

_NESTED = (
    "CHG001 IDENTIFICATION DIVISION.\n"
    "000000 PROGRAM-ID. OUTER.\n"
    "000000 PROCEDURE DIVISION.\n"
    "000000 MAIN-PARA.\n"
    "000000     DISPLAY 'O'\n"
    "000000     STOP RUN.\n"
    "000000 IDENTIFICATION DIVISION.\n"
    "000000 PROGRAM-ID. INNER.\n"
    "000000 PROCEDURE DIVISION.\n"
    "000000 INNER-PARA.\n"
    "000000     DISPLAY 'I'\n"
    "000000     GOBACK.\n"
    "000000 END PROGRAM INNER.\n"
    "000000 END PROGRAM OUTER.\n"
)

_SECTIONS = (
    "CHG001 IDENTIFICATION DIVISION.\n"
    "000000 PROGRAM-ID. TSECT.\n"
    "000000 DATA DIVISION.\n"
    "000000 WORKING-STORAGE SECTION.\n"
    "000000 01 WS-A PIC X.\n"
    "000000 PROCEDURE DIVISION.\n"
    "000000 MAIN SECTION.\n"
    "000000 MAIN-PARA.\n"
    "000000     PERFORM PROCESS\n"
    "000000     STOP RUN.\n"
    "000000 PROCESS SECTION.\n"
    "000000 PROC-PARA.\n"
    "000000     DISPLAY WS-A.\n"
)


def _units(result) -> tuple[str, list[str]]:
    assert result.ast is not None
    return result.ast.program_name, [
        unit.program_name for unit in result.ast.contained_programs
    ]


def _section_names(result) -> list[str]:
    assert result.ast is not None
    return [
        section.section_name for section in result.ast.find_all_by_type("CobolSection")
    ]


@pytest.mark.parametrize(
    "mode", [ErrorRecoveryMode.COLLECT_ALL, ErrorRecoveryMode.FAIL_FAST]
)
def test_cobol_parser_keeps_outer_program(mode) -> None:
    result = CobolParser(error_recovery=mode).parse(_NESTED)
    assert _units(result) == ("OUTER", ["INNER"])


def test_parse_cobol_keeps_outer_program() -> None:
    assert _units(parse_cobol(_NESTED)) == ("OUTER", ["INNER"])


@pytest.mark.parametrize("workers", [1, 2])
def test_parse_files_keeps_outer_program(tmp_path: Path, workers: int) -> None:
    path = tmp_path / "nested.cbl"
    path.write_text(_NESTED)
    [batch] = parse_files([path], workers=workers)
    assert batch.result is not None
    assert _units(batch.result) == ("OUTER", ["INNER"])


@pytest.mark.parametrize(
    "parse",
    [parse_cobol, lambda src: CobolParser().parse(src)],
    ids=["parse_cobol", "CobolParser.parse"],
)
def test_process_section_header_is_not_a_directive(parse) -> None:
    names = _section_names(parse(_SECTIONS))
    assert "MAIN" in names
    assert "PROCESS" in names


@pytest.mark.parametrize("workers", [1, 2])
def test_parse_files_keeps_process_section(tmp_path: Path, workers: int) -> None:
    path = tmp_path / "sections.cbl"
    path.write_text(_SECTIONS)
    [batch] = parse_files([path], workers=workers)
    assert batch.result is not None
    assert "PROCESS" in _section_names(batch.result)


def test_strip_compiler_directives_ends_at_tagged_header() -> None:
    source = (
        "       CBL APOST\n"
        "CHG001 IDENTIFICATION DIVISION.\n"
        "000000 PROCEDURE DIVISION.\n"
        "000000 PROCESS SECTION.\n"
    )
    stripped = strip_compiler_directives(source)
    assert "CBL APOST" not in stripped
    assert "000000 PROCESS SECTION." in stripped
    assert stripped.count("\n") == source.count("\n")
