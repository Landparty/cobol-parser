"""Parser-level tests for SPECIAL-NAMES paragraph in CONFIGURATION SECTION.

Prior to the fix, _parse_configuration_section() skipped all content and
returned only {"type": "configuration"}.
"""

import textwrap

from cobolparser import parse_cobol


def _program_with_special_names(special_names_body: str) -> str:
    return textwrap.dedent(f"""\
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TESTPROG.
        ENVIRONMENT DIVISION.
        CONFIGURATION SECTION.
        SPECIAL-NAMES.
        {special_names_body}
        DATA DIVISION.
        WORKING-STORAGE SECTION.
        01 WS-X PIC X.
        PROCEDURE DIVISION.
        STOP RUN.
        """)


def _get_env_div(result):
    """Return the ENVIRONMENT CobolDivision node, or None."""
    for div in result.ast.children:
        if getattr(div, "division_name", None) == "ENVIRONMENT":
            return div
    return None


def _get_config_special_names(result) -> dict:
    """Return the special_names dict from the CONFIGURATION section metadata."""
    env_div = _get_env_div(result)
    if env_div is None:
        return {}
    config_section = env_div.get_section_by_name("CONFIGURATION")
    if config_section is None:
        return {}
    return config_section.get_metadata("special_names") or {}


# ---------------------------------------------------------------------------
# CURRENCY SIGN
# ---------------------------------------------------------------------------


def test_currency_sign_is_parsed():
    src = _program_with_special_names("    CURRENCY SIGN IS 'E'.")
    result = parse_cobol(src, filename="test.cbl")
    assert result.success, f"Parse errors: {result.errors}"

    env_div = _get_env_div(result)
    assert env_div is not None, "ENVIRONMENT division not found"

    config_section = env_div.get_section_by_name("CONFIGURATION")
    assert config_section is not None, "CONFIGURATION section not found"

    sn = _get_config_special_names(result)
    assert sn.get("currency_sign") == "E", f"Expected currency_sign='E', got: {sn}"


def test_program_with_currency_sign_parses_successfully():
    src = _program_with_special_names("    CURRENCY SIGN IS 'E'.")
    result = parse_cobol(src, filename="test.cbl")
    assert result.success
    assert not result.errors


def test_decimal_point_is_comma_parses_successfully():
    src = _program_with_special_names("    DECIMAL-POINT IS COMMA.")
    result = parse_cobol(src, filename="test.cbl")
    assert result.success
    assert not result.errors


def test_multiple_special_names_clauses():
    src = _program_with_special_names(
        "    CURRENCY SIGN IS 'E'.\n    DECIMAL-POINT IS COMMA."
    )
    result = parse_cobol(src, filename="test.cbl")
    assert result.success
    assert not result.errors


def test_class_definition_parses_successfully():
    src = _program_with_special_names("    CLASS NUMERIC-CLASS IS '0' THRU '9'.")
    result = parse_cobol(src, filename="test.cbl")
    assert result.success


# ---------------------------------------------------------------------------
# Mnemonic names
# ---------------------------------------------------------------------------


def test_mnemonic_name_is_parsed():
    src = _program_with_special_names("    C01 IS TOP-OF-PAGE.")
    result = parse_cobol(src, filename="test.cbl")
    assert result.success, f"Parse errors: {result.errors}"

    sn = _get_config_special_names(result)
    assert sn.get("mnemonic_definitions") == [
        {"environment_name": "C01", "mnemonic_name": "TOP-OF-PAGE"}
    ]


def test_multiple_mnemonic_names_are_parsed():
    src = _program_with_special_names("    C01 IS TOP-OF-PAGE\n    CONSOLE IS CRT.")
    result = parse_cobol(src, filename="test.cbl")
    assert result.success, f"Parse errors: {result.errors}"

    sn = _get_config_special_names(result)
    assert sn.get("mnemonic_definitions") == [
        {"environment_name": "C01", "mnemonic_name": "TOP-OF-PAGE"},
        {"environment_name": "CONSOLE", "mnemonic_name": "CRT"},
    ]


def test_mnemonic_name_with_on_off_status():
    src = _program_with_special_names(
        "    UPSI-0 IS SWITCH-1 ON STATUS IS SW1-ON OFF STATUS IS SW1-OFF."
    )
    result = parse_cobol(src, filename="test.cbl")
    assert result.success, f"Parse errors: {result.errors}"

    sn = _get_config_special_names(result)
    assert sn.get("mnemonic_definitions") == [
        {
            "environment_name": "UPSI-0",
            "mnemonic_name": "SWITCH-1",
            "on_status": "SW1-ON",
            "off_status": "SW1-OFF",
        }
    ]


def test_mnemonic_name_mixed_with_currency_and_class():
    src = _program_with_special_names(
        "    CURRENCY SIGN IS '$'.\n"
        "    C01 IS TOP-OF-PAGE.\n"
        "    CLASS NUMERIC-CLASS IS '0' THRU '9'."
    )
    result = parse_cobol(src, filename="test.cbl")
    assert result.success, f"Parse errors: {result.errors}"

    sn = _get_config_special_names(result)
    assert sn.get("currency_sign") == "$"
    assert sn.get("mnemonic_definitions") == [
        {"environment_name": "C01", "mnemonic_name": "TOP-OF-PAGE"}
    ]
    assert len(sn.get("class_definitions", [])) == 1


def test_special_names_then_input_output():
    """SPECIAL-NAMES must not prevent INPUT-OUTPUT from being parsed."""
    src = textwrap.dedent("""\
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TESTPROG.
        ENVIRONMENT DIVISION.
        CONFIGURATION SECTION.
        SPECIAL-NAMES.
            CURRENCY SIGN IS '$'.
        INPUT-OUTPUT SECTION.
        FILE-CONTROL.
            SELECT EMPFILE ASSIGN TO 'EMP.DAT'.
        DATA DIVISION.
        WORKING-STORAGE SECTION.
        01 WS-X PIC X.
        PROCEDURE DIVISION.
        STOP RUN.
        """)
    result = parse_cobol(src, filename="test.cbl")
    assert result.success

    env_div = _get_env_div(result)
    assert env_div is not None, "ENVIRONMENT division not found"

    # Both sections should be present
    assert env_div.has_section("CONFIGURATION"), "CONFIGURATION section missing"
    assert env_div.has_section("INPUT-OUTPUT"), "INPUT-OUTPUT section missing"
