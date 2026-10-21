"""Issue #508: ``CobolProgram.to_dict()`` metadata.

``parser_version`` was hard-coded ``"1.0.0"``, ``created_at`` was a
placeholder timestamp that looked real, and ``procedure_count`` counted the
DATA DIVISION's WORKING-STORAGE / LOCAL-STORAGE / LINKAGE / FILE sections as
procedures.
"""

from __future__ import annotations

import pytest

import cobolparser
from cobolparser import parse_cobol

_DATA_SECTIONS_ONLY = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. SZ.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-A PIC X.
       LOCAL-STORAGE SECTION.
       01  LS-A PIC X.
       PROCEDURE DIVISION.
           GOBACK.
"""

_TWO_PARAGRAPHS = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TWO.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-A PIC X.
       LINKAGE SECTION.
       01  LK-A PIC X.
       PROCEDURE DIVISION.
       P1.
           PERFORM P2.
           GOBACK.
       P2.
           DISPLAY WS-A.
"""

_PROCEDURE_SECTION = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. SEC.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-A PIC X.
       PROCEDURE DIVISION.
       MAIN-SEC SECTION.
       P1.
           GOBACK.
"""


def _ast(source: str) -> cobolparser.CobolProgram:
    result = parse_cobol(source)
    assert result.ast is not None and not result.errors, result.errors
    return result.ast


def test_data_division_sections_are_not_procedures() -> None:
    assert _ast(_DATA_SECTIONS_ONLY).get_statistics()["procedure_count"] == 1


def test_procedure_count_matches_the_paragraphs() -> None:
    assert _ast(_TWO_PARAGRAPHS).get_statistics()["procedure_count"] == 2


def test_procedure_division_sections_still_count() -> None:
    # The section and its paragraph; WORKING-STORAGE does not.
    assert _ast(_PROCEDURE_SECTION).get_statistics()["procedure_count"] == 2


def test_parser_version_is_the_package_version() -> None:
    metadata = _ast(_TWO_PARAGRAPHS).to_dict()["metadata"]
    assert metadata["parser_version"] == cobolparser.__version__


def test_no_placeholder_timestamp_and_json_is_stable() -> None:
    ast = _ast(_TWO_PARAGRAPHS)
    assert "created_at" not in ast.to_dict()["metadata"]
    assert _ast(_TWO_PARAGRAPHS).to_json() == ast.to_json()


@pytest.mark.filterwarnings("ignore::UserWarning")  # lossy statement restore
def test_old_json_with_created_at_still_loads() -> None:
    import json

    from cobolparser.models.program import CobolProgram

    data = _ast(_TWO_PARAGRAPHS).to_dict()
    data["metadata"]["created_at"] = "2024-01-01T00:00:00Z"
    data["metadata"]["parser_version"] = "1.0.0"
    restored = CobolProgram.from_json(json.dumps(data))
    assert restored.to_dict()["metadata"]["parser_version"] == (cobolparser.__version__)
    assert "created_at" not in restored.to_dict()["metadata"]
