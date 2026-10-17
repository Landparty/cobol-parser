"""#338: an IDCAMS REPRO was dropped when a DSN qualifier is a command word.

``_IDCAMS_COMMAND_RE`` used ``\\b``, and ``.`` is a word boundary, so the
``DELETE`` in ``PROD.DELETE.MASTER`` was read as the start of a new command:
the REPRO ended there, never saw its OUTDATASET, and the pass-through
vanished without a caveat. A command word now starts a command only at the
start of a statement (or after ``THEN`` / ``ELSE`` / ``DO``), outside
parentheses, and not as a qualifier.
"""

from __future__ import annotations

from types import SimpleNamespace as NS

import pytest

from cobolparser.analysis.lineage_jcl import bindings_from_jobs


def idcams(control: str) -> list[tuple[str, str, str]]:
    step = NS(
        name="S1",
        program="IDCAMS",
        dd_statements=[
            NS(name="IN", dataset_name="DD.IN", inline_data=None),
            NS(name="OUT", dataset_name="DD.OUT", inline_data=None),
            NS(name="SYSIN", dataset_name=None, inline_data=control),
        ],
    )
    _, passthroughs = bindings_from_jobs([NS(name="J", steps=[step])])
    return [(p.input, p.output, p.kind) for p in passthroughs]


@pytest.mark.parametrize(
    "word",
    ["DELETE", "PRINT", "SET", "IF", "ALTER", "DEFINE", "EXPORT", "REPRO", "LISTCAT"],
)
def test_command_word_qualifier_keeps_the_repro(word: str) -> None:
    assert idcams(
        f"  REPRO INDATASET(PROD.{word}.MASTER) OUTDATASET(PROD.BACKUP)\n"
    ) == [(f"PROD.{word}.MASTER", "PROD.BACKUP", "copy")]


def test_quoted_and_trailing_qualifiers() -> None:
    assert idcams(
        "  REPRO INDATASET('PROD.MASTER.DELETE') -\n    OUTDATASET(SET.BACKUP)\n"
    ) == [("PROD.MASTER.DELETE", "SET.BACKUP", "copy")]


def test_commands_still_end_a_repro() -> None:
    assert idcams(
        "  DELETE PROD.OLD PURGE\n"
        "  SET MAXCC = 0\n"
        "  REPRO INFILE(IN) OUTFILE(OUT)\n"
        "  IF LASTCC = 0 THEN REPRO INDATASET(A.PRINT) OUTDATASET(B.SET)\n"
        "  ELSE REPRO INDATASET(C.IN) OUTDATASET(C.OUT); PRINT INDATASET(C.OUT)\n"
    ) == [
        ("DD.IN", "DD.OUT", "copy"),
        ("A.PRINT", "B.SET", "copy"),
        ("C.IN", "C.OUT", "copy"),
    ]


@pytest.mark.parametrize(
    "control",
    [
        "  /* COPY THE MASTER */ REPRO INFILE(IN) OUTFILE(OUT)\n",
        "  /* A COMMENT THAT\n     SPANS LINES */ REPRO INFILE(IN) -\n    OUTFILE(OUT)\n",
        "  REPRO INFILE(IN) /* THEN DELETE */ -\n    OUTFILE(OUT)\n",
    ],
)
def test_a_comment_before_a_command_does_not_hide_it(control: str) -> None:
    assert idcams(control) == [("DD.IN", "DD.OUT", "copy")]
