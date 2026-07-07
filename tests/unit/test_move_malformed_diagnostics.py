"""Regression tests for audit finding H3 — the MOVE parser must not silently
accept malformed/incomplete input.

Before the fix, ``MOVE A TO.`` (and friends) parsed to a ``MoveStatement`` with
``targets: []`` and ``errors == 0``. A malformed MOVE must now surface at least
one diagnostic, while every well-formed MOVE must stay error-free.
"""

import pytest

from cobolparser import parse_cobol


def _program(procedure_body: str) -> str:
    """Wrap a PROCEDURE DIVISION body in a minimal free-form program."""
    return (
        "       IDENTIFICATION DIVISION.\n"
        "       PROGRAM-ID. TEST.\n"
        "       PROCEDURE DIVISION.\n"
        "       MAIN.\n"
        f"{procedure_body}"
    )


# --- malformed MOVE must report an error -----------------------------------


@pytest.mark.parametrize(
    "body",
    [
        "           MOVE A TO.\n",  # TO present, zero targets (the headline case)
        "           MOVE A TO\n",  # truncated at EOF after TO
        "           MOVE A.\n",  # no TO keyword at all
        "           MOVE A\n",  # no TO, truncated at EOF
        "           MOVE.\n",  # bare MOVE (caught via the missing-TO path)
    ],
)
def test_malformed_move_reports_error(body):
    result = parse_cobol(_program(body), filename="malformed.cob")
    assert (
        len(result.errors) >= 1
    ), f"malformed MOVE should report an error, got none for body: {body!r}"


# --- well-formed MOVE must stay clean (the real regression guard) ----------


@pytest.mark.parametrize(
    "body",
    [
        "           MOVE A TO B.\n",  # single target
        "           MOVE A TO B C.\n",  # multiple targets
        "           MOVE A TO B(I).\n",  # subscripted target
        "           MOVE 5 TO A.\n",  # numeric literal source
        '           MOVE "HELLO" TO A.\n',  # string literal source
        "           MOVE SPACES TO A.\n",  # figurative constant source
        "           MOVE CORRESPONDING R1 TO R2.\n",  # MOVE CORRESPONDING
        "           MOVE CORR R1 TO R2.\n",  # MOVE CORR abbreviation
    ],
)
def test_valid_move_stays_error_free(body):
    result = parse_cobol(_program(body), filename="valid.cob")
    assert len(result.errors) == 0, (
        f"valid MOVE must not report errors, got "
        f"{[str(e) for e in result.errors]} for body: {body!r}"
    )


def test_malformed_move_does_not_block_following_statements():
    """A malformed MOVE records an error but recovery keeps parsing going."""
    src = (
        "       IDENTIFICATION DIVISION.\n"
        "       PROGRAM-ID. TEST.\n"
        "       PROCEDURE DIVISION.\n"
        "       PARA-ONE.\n"
        "           MOVE A TO.\n"
        "           MOVE C TO D.\n"
    )
    result = parse_cobol(src, filename="recover.cob")
    assert result.ast is not None
    assert result.ast.program_name == "TEST"
    assert len(result.errors) >= 1
    # The following well-formed MOVE must still land in the AST.
    moves = result.ast.find_all_by_type("MoveStatement")
    assert any(getattr(m, "targets", None) == ["D"] for m in moves)
