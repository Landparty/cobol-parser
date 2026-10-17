"""Regression (#492): stacked compiler-directing ``>>WHEN`` phrases.

ISO 2014 ``>>EVALUATE`` (and IBM Enterprise COBOL's) lets several ``>>WHEN``
phrases share one text block, as stacked WHENs do in the procedural
EVALUATE. When the *first* phrase of a stack matched, the next ``>>WHEN``
switched the branch back off (a branch was already taken), the shared text
was blanked and ``>>WHEN OTHER`` was skipped too: the whole ``>>EVALUATE``
produced nothing, with no warning.
"""

from __future__ import annotations

import pytest

from cobolparser import parse_cobol
from cobolparser.preprocess import preprocess_conditional_compilation


def _evaluate(env: str, separator: str = "") -> tuple[str, list[str]]:
    warnings: list[str] = []
    out = preprocess_conditional_compilation(
        f">>DEFINE ENV AS '{env}'\n"
        ">>EVALUATE ENV\n"
        ">>WHEN 'PROD'\n"
        f"{separator}"
        ">>WHEN 'QA'\n"
        "DISPLAY 'LIVE-LIKE'.\n"
        ">>WHEN 'TEST'\n"
        "DISPLAY 'TEST'.\n"
        ">>WHEN OTHER\n"
        "DISPLAY 'DEV'.\n"
        ">>END-EVALUATE\n",
        None,
        warnings=warnings,
    )
    return out, warnings


@pytest.mark.parametrize(
    ("env", "shown"),
    [("PROD", "LIVE-LIKE"), ("QA", "LIVE-LIKE"), ("TEST", "TEST"), ("X", "DEV")],
)
def test_stacked_when_selects_shared_text(env: str, shown: str) -> None:
    out, warnings = _evaluate(env)
    displays = [line for line in out.splitlines() if line.startswith("DISPLAY")]
    assert displays == [f"DISPLAY '{shown}'."]
    assert warnings == []


@pytest.mark.parametrize("separator", ["\n", "      *> why\n", "      * note\n"])
def test_blank_and_comment_lines_keep_the_stack(separator: str) -> None:
    out, _ = _evaluate("PROD", separator)
    assert "DISPLAY 'LIVE-LIKE'." in out
    assert "DEV" not in out


def test_text_between_whens_ends_the_stack() -> None:
    # A WHEN followed by its own text is not stacked: the PROD arm keeps
    # its text only, and QA's text is not compiled in for PROD.
    out, _ = _evaluate("PROD", "DISPLAY 'PROD-ONLY'.\n")
    displays = [line for line in out.splitlines() if line.startswith("DISPLAY")]
    assert displays == ["DISPLAY 'PROD-ONLY'."]


def test_stacked_condition_whens_under_evaluate_true() -> None:
    out = preprocess_conditional_compilation(
        ">>DEFINE LVL AS 1\n"
        ">>EVALUATE TRUE\n"
        ">>WHEN LVL = 1\n"
        ">>WHEN LVL = 2\n"
        "DISPLAY 'LOW'.\n"
        ">>WHEN OTHER\n"
        "DISPLAY 'HIGH'.\n"
        ">>END-EVALUATE\n",
        None,
    )
    assert "DISPLAY 'LOW'." in out
    assert "HIGH" not in out


def test_stacked_when_before_other_shares_text() -> None:
    out = preprocess_conditional_compilation(
        ">>DEFINE ENV AS 'PROD'\n"
        ">>EVALUATE ENV\n"
        ">>WHEN 'QA'\n"
        "DISPLAY 'QA'.\n"
        ">>WHEN 'PROD'\n"
        ">>WHEN OTHER\n"
        "DISPLAY 'REST'.\n"
        ">>END-EVALUATE\n",
        None,
    )
    displays = [line for line in out.splitlines() if line.startswith("DISPLAY")]
    assert displays == ["DISPLAY 'REST'."]


def test_issue_repro_through_parse_cobol() -> None:
    result = parse_cobol(
        "       IDENTIFICATION DIVISION.\n"
        "       PROGRAM-ID. SW.\n"
        "       PROCEDURE DIVISION.\n"
        "       >>DEFINE ENV AS 'PROD'\n"
        "       >>EVALUATE ENV\n"
        "       >>WHEN 'PROD'\n"
        "       >>WHEN 'QA'\n"
        "           DISPLAY 'LIVE-LIKE'\n"
        "       >>WHEN OTHER\n"
        "           DISPLAY 'DEV'\n"
        "       >>END-EVALUATE\n"
        "           STOP RUN.\n"
    )
    assert result.success and result.ast is not None
    items = [
        item
        for node in result.ast.find_all_by_type("DisplayStatement")
        for item in node.to_dict()["display_items"]
    ]
    assert items == ['"LIVE-LIKE"']
    assert result.warnings == []
