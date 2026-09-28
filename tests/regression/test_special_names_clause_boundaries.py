"""Regression: SPECIAL-NAMES clauses end where the next clause starts.

IBM Enterprise COBOL writes SPECIAL-NAMES as one sentence with a single
closing period. CLASS and ALPHABET used to collect operands until the next
CURRENCY / DECIMAL-POINT / CLASS / ALPHABET word or a period, so

* a following ``SYMBOLIC CHARACTERS`` clause or mnemonic-name clause
  (``C01 IS TOP-OF-PAGE``) was swallowed into the class ranges / alphabet
  values, together with the NEWLINE tokens (``"\\n"``) between them, and
  the mnemonic names were lost;
* ``SYMBOLIC CHARACTERS NUL IS 1`` was misread as a mnemonic-name clause;
* a following ``REPOSITORY.`` paragraph's ``CLASS name IS 'java.Class'``
  entries became SPECIAL-NAMES class conditions;
* only the last ``CURRENCY SIGN`` clause was kept, and its ``PICTURE
  SYMBOL`` was dropped.
"""

from cobolparser import parse_cobol
from cobolparser.plugins.core import ErrorRecoveryMode


def _program(config_body: str) -> str:
    return (
        "       IDENTIFICATION DIVISION.\n"
        "       PROGRAM-ID. SNTEST.\n"
        "       ENVIRONMENT DIVISION.\n"
        "       CONFIGURATION SECTION.\n"
        f"{config_body}"
        "       DATA DIVISION.\n"
        "       WORKING-STORAGE SECTION.\n"
        "       01 WS-X PIC X.\n"
        "       PROCEDURE DIVISION.\n"
        "           STOP RUN.\n"
    )


def _special_names(source: str) -> dict:
    result = parse_cobol(source, error_recovery=ErrorRecoveryMode.FAIL_FAST)
    assert result.errors == []
    env = result.ast.get_division("ENVIRONMENT")
    return env.get_section_by_name("CONFIGURATION").get_metadata("special_names")


def test_single_sentence_special_names() -> None:
    special = _special_names(
        _program(
            "       SPECIAL-NAMES.\n"
            "           CLASS HEX-DIGIT IS '0' THRU '9' 'A' THRU 'F'\n"
            "           SYMBOLIC CHARACTERS NUL-CHAR BELL-CHAR ARE 1 8\n"
            "           ALPHABET MY-ALPHA IS EBCDIC\n"
            "           C01 IS TOP-OF-PAGE\n"
            "           SYSOUT IS PRINTER-OUT\n"
            "           UPSI-0 ON STATUS IS SW-ON OFF STATUS IS SW-OFF\n"
            "           CURRENCY SIGN IS 'EUR' WITH PICTURE SYMBOL '#'\n"
            "           CURRENCY SIGN IS '$'.\n"
        )
    )
    assert special["class_definitions"] == [
        {"name": "HEX-DIGIT", "ranges": ["0", "THRU", "9", "A", "THRU", "F"]}
    ]
    assert special["alphabet_definitions"] == [
        {"name": "MY-ALPHA", "values": ["EBCDIC"]}
    ]
    assert special["symbolic_characters"] == [
        {"name": "NUL-CHAR", "ordinal": 1, "alphabet": None},
        {"name": "BELL-CHAR", "ordinal": 8, "alphabet": None},
    ]
    assert special["mnemonic_definitions"] == [
        {"environment_name": "C01", "mnemonic_name": "TOP-OF-PAGE"},
        {"environment_name": "SYSOUT", "mnemonic_name": "PRINTER-OUT"},
        {"environment_name": "UPSI-0", "on_status": "SW-ON", "off_status": "SW-OFF"},
    ]
    assert special["currency_signs"] == [
        {"sign": "EUR", "picture_symbol": "#"},
        {"sign": "$", "picture_symbol": None},
    ]
    assert special["currency_sign"] == "$"


def test_symbolic_characters_is_form_followed_by_mnemonic() -> None:
    special = _special_names(
        _program(
            "       SPECIAL-NAMES.\n"
            "           SYMBOLIC CHARACTERS NUL IS 1 TAB IS 6 IN STD-ALPHA\n"
            "           C01 IS TOP-OF-PAGE\n"
            "           ALPHABET STD-ALPHA IS STANDARD-1.\n"
        )
    )
    assert special["symbolic_characters"] == [
        {"name": "NUL", "ordinal": 1, "alphabet": "STD-ALPHA"},
        {"name": "TAB", "ordinal": 6, "alphabet": "STD-ALPHA"},
    ]
    assert special["mnemonic_definitions"] == [
        {"environment_name": "C01", "mnemonic_name": "TOP-OF-PAGE"}
    ]
    assert special["alphabet_definitions"] == [
        {"name": "STD-ALPHA", "values": ["STANDARD-1"]}
    ]


def test_repository_paragraph_is_not_special_names() -> None:
    special = _special_names(
        _program(
            "       SPECIAL-NAMES.\n"
            "           C01 IS TOP-OF-PAGE.\n"
            "       REPOSITORY.\n"
            "           CLASS ACCOUNT IS 'com.acme.Account'\n"
            "           FUNCTION ALL INTRINSIC.\n"
        )
    )
    assert "class_definitions" not in special
    assert special["mnemonic_definitions"] == [
        {"environment_name": "C01", "mnemonic_name": "TOP-OF-PAGE"}
    ]
