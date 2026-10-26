"""Bug hunt round 11: JCL, copybook path resolution, scan.

Each test reproduces a defect found in this round and pins the fix.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest

from cobolparser.cli.parse import _cmd_jcl
from cobolparser.jcl import parse_jcl
from cobolparser.preprocess.models import CopybookSearchPath
from cobolparser.preprocess.path_resolver import PathResolver, find_copybook_file
from cobolparser.scan import ScanOptions, scan_files

# -- JCL --------------------------------------------------------------------


def test_job_card_ends_an_unterminated_in_stream_proc() -> None:
    # A PROC missing its PEND swallowed every later card -- the next JOB and
    # all of its steps vanished from `jobs`.
    result = parse_jcl("""\
//J1 JOB
//P PROC
//S1 EXEC PGM=A
//IN DD DSN=X.Y
//J2 JOB
//S2 EXEC PGM=B
//OUT DD DSN=Y.Z
""")
    assert [job.name for job in result.jobs] == ["J1", "J2"]
    assert result.jobs[1].step("S2").program == "B"
    assert result.dd_map()["OUT"] == ["Y.Z"]
    assert any("PROC P has no PEND" in note for note in result.unresolved)
    assert result.errors == []


def test_in_stream_procedures_are_local_to_their_job() -> None:
    # Two jobs in one deck each defining their own `P`: the second was an
    # error ("defined more than once") and job 2 ran job 1's procedure.
    result = parse_jcl("""\
//J1 JOB
//P PROC
//S1 EXEC PGM=FIRST
// PEND
//RUN EXEC P
//J2 JOB
//P PROC
//S1 EXEC PGM=SECOND
// PEND
//RUN EXEC P
""")
    assert result.errors == []
    assert result.jobs[0].step("RUN.S1").program == "FIRST"
    assert result.jobs[1].step("RUN.S1").program == "SECOND"


def test_in_stream_procedure_is_not_visible_to_a_later_job() -> None:
    result = parse_jcl("""\
//J1 JOB
//P PROC
//S1 EXEC PGM=FIRST
// PEND
//RUN EXEC P
//J2 JOB
//RUN EXEC P
""")
    assert result.jobs[1].step("RUN.S1") is None
    assert any("PROC P (line 7)" in note for note in result.unresolved)


def test_procedure_defined_before_the_first_job_still_expands() -> None:
    result = parse_jcl("""\
//P PROC
//S1 EXEC PGM=A
// PEND
//J JOB
//RUN EXEC P
""")
    assert result.jobs[0].step("RUN.S1").program == "A"


def test_set_values_do_not_leak_into_the_next_job() -> None:
    result = parse_jcl("""\
//J1 JOB
// SET HLQ=PROD
//S1 EXEC PGM=A
//IN DD DSN=&HLQ..X
//J2 JOB
//S1 EXEC PGM=A
//IN DD DSN=&HLQ..X
""")
    assert result.jobs[0].steps[0].dd("IN").dataset == "PROD.X"
    # Job 2 never SET HLQ: the name stays as coded and is reported.
    assert result.jobs[1].steps[0].dd("IN").dataset == "&HLQ..X"
    assert any("(line 7): DSN=&HLQ..X keeps &HLQ" in n for n in result.unresolved)
    assert result.symbols == {"HLQ": "PROD"}


def test_delimiter_with_comment_is_not_a_jes_statement() -> None:
    # `/* END OF DATA` is a delimiter whose remainder is a comment; it was
    # reported as a JES control statement named "END".
    result = parse_jcl("""\
//J JOB
//S1 EXEC PGM=A
//IN DD *
DATA1
/* END OF DATA
/* ALSO A COMMENT
/*JOBPARM SYSAFF=SYS2
""")
    assert result.jobs[0].steps[0].dd("IN").instream_lines == ["DATA1"]
    assert not any("END" in note or "ALSO" in note for note in result.unresolved)


def test_dd_star_data_may_end_at_end_of_file() -> None:
    # `DD *` without DLM= ends at the next `//` card or at the end of the
    # input; a member ending in its SYSIN control cards is not an error.
    result = parse_jcl("""\
//J JOB
//S EXEC PGM=SORT
//SYSIN DD *
  SORT FIELDS=COPY
""")
    assert result.errors == []
    assert result.jobs[0].steps[0].dd("SYSIN").instream_lines == ["  SORT FIELDS=COPY"]


def test_jcl_bindings_program_filter_is_per_job(tmp_path: Path, capsys) -> None:
    # `--bindings --program INVUPDT` also returned the DDs of a same-named
    # step (`S1`) in another job running a different program.
    path = tmp_path / "TWO.jcl"
    path.write_text(
        "//J1 JOB\n//S1 EXEC PGM=INVUPDT\n//IN DD DSN=A.B,DISP=SHR\n"
        "//J2 JOB\n//S1 EXEC PGM=OTHER\n//IN DD DSN=C.D,DISP=SHR\n",
        encoding="utf-8",
    )
    _cmd_jcl(
        argparse.Namespace(
            file=str(path),
            compact=True,
            dd_map=False,
            bindings=True,
            program="INVUPDT",
            strict=False,
            output=None,
        )
    )
    payload = json.loads(capsys.readouterr().out)
    assert [(b["job"], b["dataset"]) for b in payload["bindings"]] == [("J1", "A.B")]


# -- copybook path resolution -----------------------------------------------


def _layout(tmp_path: Path) -> Path:
    root = tmp_path / "copy"
    (root / "mylib").mkdir(parents=True)
    (root / "mylib" / "MEM.cpy").write_text("       01 X PIC X.\n", encoding="utf-8")
    (root / "LIB2").mkdir()
    (root / "LIB2" / "M2.cpy").write_text("       01 Y PIC X.\n", encoding="utf-8")
    (tmp_path / "src").mkdir()
    return root


def test_relative_search_directory_with_dotdot_is_not_a_traversal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # `--copybook-path ../copy` (or a cobol.yml entry resolved against the
    # config file's directory) made every Tier-3 hit -- any `COPY m OF lib`
    # -- raise PathTraversalError: the ".." check judged the configured
    # directory, not what the COPY statement contributed.
    root = _layout(tmp_path)
    monkeypatch.chdir(tmp_path / "src")
    resolver = PathResolver(CopybookSearchPath(directories=["../copy"]))
    assert resolver.resolve("M2", "LIB2") == str(root / "LIB2" / "M2.cpy")


def test_dotdot_in_the_member_name_is_still_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from cobolparser.preprocess import PathTraversalError

    _layout(tmp_path)
    monkeypatch.chdir(tmp_path / "src")
    config = CopybookSearchPath(directories=["../copy"])
    with pytest.raises(PathTraversalError):
        find_copybook_file("../copy/LIB2/M2", config)


def test_library_directory_matches_case_insensitively_when_search_does(
    tmp_path: Path,
) -> None:
    # With case_sensitive=False the member name was tried in several
    # casings but the library subdirectory only as written, so
    # `COPY MEM OF MYLIB` missed `mylib/MEM.cpy`.
    root = _layout(tmp_path)
    insensitive = CopybookSearchPath(directories=[str(root)], case_sensitive=False)
    assert find_copybook_file("MEM", insensitive, "MYLIB") == str(
        root / "mylib" / "MEM.cpy"
    )
    from cobolparser.preprocess import CopybookNotFoundError

    sensitive = CopybookSearchPath(directories=[str(root)], case_sensitive=True)
    with pytest.raises(CopybookNotFoundError):
        find_copybook_file("MEM", sensitive, "MYLIB")


# -- scan -------------------------------------------------------------------


def test_scan_isolates_an_undecodable_file_under_strict_errors(
    tmp_path: Path,
) -> None:
    # scan_one caught only OSError, so under errors="strict" one file's
    # UnicodeDecodeError aborted the whole scan.
    bad = tmp_path / "BAD.cbl"
    bad.write_bytes(b"\xff\xfe\x81 not utf-8")
    good = tmp_path / "GOOD.cbl"
    good.write_text(
        "       IDENTIFICATION DIVISION.\n"
        "       PROGRAM-ID. GOOD.\n"
        "       PROCEDURE DIVISION.\n"
        "           STOP RUN.\n",
        encoding="utf-8",
    )
    # The encoding is named: since #522 an unnamed one is detected, and these
    # bytes decode cleanly as cp1252, so nothing would be undecodable.
    report = scan_files(
        [bad, good], ScanOptions(encoding="utf-8", errors="strict"), workers=1
    )
    summary = report.to_dict()["summary"]
    assert summary["scanned_file_count"] == 1
    assert summary["failed_file_count"] == 1
    assert "could not read" in (report.failed_files[0].error or "")
