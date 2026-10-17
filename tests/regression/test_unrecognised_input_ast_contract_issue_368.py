"""Regression for #368: what ``ParseResult.ast`` is when no division is found.

``interface-contract.md`` used to say ``ast is None`` only when nothing could
be parsed, while text with no recognisable division returns an empty
``CobolProgram("UNKNOWN")``. The contract was changed to match the code
(option (b)); these tests pin the documented shape so the two cannot drift
apart again.
"""

from pathlib import Path

import pytest

from cobolparser import CobolParser, ErrorRecoveryMode

CONTRACT = Path(__file__).resolve().parents[2] / "interface-contract.md"


@pytest.mark.parametrize("source", ["hello world", ""])
@pytest.mark.parametrize(
    "mode", [ErrorRecoveryMode.COLLECT_ALL, ErrorRecoveryMode.FAIL_FAST]
)
def test_no_division_gives_empty_unknown_program(
    source: str, mode: ErrorRecoveryMode
) -> None:
    result = CobolParser(error_recovery=mode).parse(source)

    assert result.success is False
    assert result.ast is not None
    assert result.ast.program_name == "UNKNOWN"
    assert result.ast.divisions == []
    assert any("No recognizable COBOL division found" in str(e) for e in result.errors)


def test_a_real_program_is_not_mistaken_for_the_empty_shape() -> None:
    result = CobolParser().parse(
        "IDENTIFICATION DIVISION.\nPROGRAM-ID. P368.\n"
        "PROCEDURE DIVISION.\n    STOP RUN.\n"
    )

    assert result.success
    assert result.ast is not None
    assert result.ast.divisions


def test_contract_documents_the_empty_unknown_program() -> None:
    text = CONTRACT.read_text(encoding="utf-8")

    assert "`ast is None` only when nothing could be parsed" not in text
    assert 'program_name == "UNKNOWN"' in text
    assert "ast.divisions" in text
