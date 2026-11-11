"""A missing ``EXEC SQL INCLUDE`` member is reported, not skipped silently.

The expander leaves an INCLUDE it cannot find as written, because SQLCA and
SQLDA come from the DB2 precompiler. Any other member (a DCLGEN, a shared
COMMAREA layout) used to vanish the same way: no warning, no caveat, and the
analyzers read the program without its declarations. Found on GenApp
``lgapdb01.cbl`` (``EXEC SQL INCLUDE LGCMAREA``), whose xref listed 54
undefined names.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from cobolparser.cli.parse import main
from cobolparser.parser import parse_cobol_with_expansion

PROGRAM = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. INCL.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
           EXEC SQL
             INCLUDE SQLCA
           END-EXEC.
       LINKAGE SECTION.
       01  DFHCOMMAREA.
           EXEC SQL
             INCLUDE {member}
           END-EXEC.
       PROCEDURE DIVISION.
           MOVE 1 TO CA-NUM.
           GOBACK.
"""

MEMBER = "           03 CA-NUM PIC 9(4).\n"


def _write(tmp_path: Path, member: str = "COMMAREA") -> Path:
    src = tmp_path / "incl.cbl"
    src.write_text(PROGRAM.format(member=member))
    return src


def _include_warnings(result: object) -> list[str]:
    return [
        w for w in getattr(result, "warnings", []) if w.startswith("EXEC SQL INCLUDE")
    ]


def test_a_missing_member_other_than_sqlca_is_a_warning(tmp_path: Path) -> None:
    src = _write(tmp_path)
    result = parse_cobol_with_expansion(
        src.read_text(), filename=str(src), copybook_paths=[str(tmp_path)]
    )
    warnings = _include_warnings(result)
    assert len(warnings) == 1
    assert warnings[0].startswith("EXEC SQL INCLUDE COMMAREA was not expanded")


def test_sqlca_and_sqlda_stay_silent(tmp_path: Path) -> None:
    src = _write(tmp_path, member="SQLDA")
    result = parse_cobol_with_expansion(
        src.read_text(), filename=str(src), copybook_paths=[str(tmp_path)]
    )
    assert _include_warnings(result) == []


def test_a_member_that_resolves_is_not_reported(tmp_path: Path) -> None:
    src = _write(tmp_path)
    (tmp_path / "COMMAREA.cpy").write_text(MEMBER)
    result = parse_cobol_with_expansion(
        src.read_text(), filename=str(src), copybook_paths=[str(tmp_path)]
    )
    assert _include_warnings(result) == []


@pytest.mark.parametrize("with_path", [True, False])
def test_analyzer_subcommands_say_so_on_stderr(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    with_path: bool,
) -> None:
    src = _write(tmp_path)
    argv = ["cobol-parser", "xref", str(src), "--no-config"]
    if with_path:
        argv += ["--copybook-path", str(tmp_path)]
    monkeypatch.setattr(sys, "argv", argv)
    try:
        main()
    except SystemExit as exc:
        assert exc.code in (0, None)
    err = capsys.readouterr().err
    if with_path:
        assert "1 EXEC SQL INCLUDE member(s) not found (COMMAREA)" in err
    else:
        # Without a copybook path nothing is expanded at all; the COPY hint
        # covers that case and the INCLUDE is not singled out.
        assert "EXEC SQL INCLUDE" not in err
