"""Parser-level integration tests for IBM-specific USAGE clause recognition.

Verifies that the data division parser correctly captures IBM USAGE types —
PACKED-DECIMAL, COMPUTATIONAL-4/5, POINTER, PROCEDURE-POINTER, FUNCTION-POINTER —
both when written with an explicit USAGE keyword and when written bare (without it).

Prior to the fix these values silently fell through to `else: consume()` and the
resulting data item had usage="DISPLAY", causing wrong size calculations downstream.
"""

import textwrap
from pathlib import Path

from cobolparser import parse_cobol


def _parse_working_storage(items_cobol: str):
    """Wrap bare data items in a minimal valid COBOL program and parse it."""
    source = textwrap.dedent(
        f"""\
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TESTPROG.
        DATA DIVISION.
        WORKING-STORAGE SECTION.
        01  WS-ROOT.
        {items_cobol}
        PROCEDURE DIVISION.
        STOP RUN.
        """
    )
    return parse_cobol(source, filename="test.cbl")


def _find_item(result, name: str):
    """Find the first data item with the given name in the parsed AST."""
    items = result.ast.find_all_by_type("DataItem")
    for item in items:
        if hasattr(item, "name") and item.name.upper() == name.upper():
            return item
    return None


# ---------------------------------------------------------------------------
# PACKED-DECIMAL
# ---------------------------------------------------------------------------


def test_packed_decimal_without_usage_keyword():
    result = _parse_working_storage(
        "    05  WS-AMT  PIC 9(7)V99 PACKED-DECIMAL."
    )
    assert result.success
    item = _find_item(result, "WS-AMT")
    assert item is not None
    assert item.usage == "PACKED-DECIMAL"


def test_packed_decimal_with_usage_keyword():
    result = _parse_working_storage(
        "    05  WS-AMT  PIC 9(7)V99 USAGE PACKED-DECIMAL."
    )
    assert result.success
    item = _find_item(result, "WS-AMT")
    assert item is not None
    assert item.usage == "PACKED-DECIMAL"


# ---------------------------------------------------------------------------
# COMPUTATIONAL-4 / COMPUTATIONAL-5
# ---------------------------------------------------------------------------


def test_computational_4_without_usage_keyword():
    result = _parse_working_storage("    05  WS-C4  PIC 9(9) COMPUTATIONAL-4.")
    assert result.success
    item = _find_item(result, "WS-C4")
    assert item is not None
    assert item.usage == "COMPUTATIONAL-4"


def test_computational_5_without_usage_keyword():
    result = _parse_working_storage("    05  WS-C5  PIC 9(9) COMPUTATIONAL-5.")
    assert result.success
    item = _find_item(result, "WS-C5")
    assert item is not None
    assert item.usage == "COMPUTATIONAL-5"


def test_computational_4_with_usage_keyword():
    result = _parse_working_storage(
        "    05  WS-C4  PIC 9(9) USAGE COMPUTATIONAL-4."
    )
    assert result.success
    item = _find_item(result, "WS-C4")
    assert item is not None
    assert item.usage == "COMPUTATIONAL-4"


# ---------------------------------------------------------------------------
# POINTER / PROCEDURE-POINTER / FUNCTION-POINTER
# ---------------------------------------------------------------------------


def test_pointer_without_usage_keyword():
    result = _parse_working_storage("    05  WS-PTR  POINTER.")
    assert result.success
    item = _find_item(result, "WS-PTR")
    assert item is not None
    assert item.usage == "POINTER"


def test_pointer_with_usage_keyword():
    result = _parse_working_storage("    05  WS-PTR  USAGE POINTER.")
    assert result.success
    item = _find_item(result, "WS-PTR")
    assert item is not None
    assert item.usage == "POINTER"


def test_procedure_pointer_without_usage_keyword():
    result = _parse_working_storage("    05  WS-PPTR  PROCEDURE-POINTER.")
    assert result.success
    item = _find_item(result, "WS-PPTR")
    assert item is not None
    assert item.usage == "PROCEDURE-POINTER"


def test_function_pointer_without_usage_keyword():
    result = _parse_working_storage("    05  WS-FPTR  FUNCTION-POINTER.")
    assert result.success
    item = _find_item(result, "WS-FPTR")
    assert item is not None
    assert item.usage == "FUNCTION-POINTER"


# ---------------------------------------------------------------------------
# End-to-end: existing ibm_extensions.cbl sample
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Data clauses: SIGN, SYNCHRONIZED, JUSTIFIED, BLANK WHEN ZERO
# ---------------------------------------------------------------------------


def test_sign_is_leading():
    result = _parse_working_storage(
        "    05  WS-AMT  PIC S9(9) COMP SIGN IS LEADING."
    )
    assert result.success
    item = _find_item(result, "WS-AMT")
    assert item is not None
    assert item.sign_clause == "LEADING"


def test_sign_is_trailing_separate():
    result = _parse_working_storage(
        "    05  WS-AMT  PIC S9(9) SIGN IS TRAILING SEPARATE."
    )
    assert result.success
    item = _find_item(result, "WS-AMT")
    assert item is not None
    assert item.sign_clause == "TRAILING SEPARATE"


def test_sign_leading_no_is():
    result = _parse_working_storage(
        "    05  WS-AMT  PIC S9(5) SIGN LEADING SEPARATE CHARACTER."
    )
    assert result.success
    item = _find_item(result, "WS-AMT")
    assert item is not None
    assert item.sign_clause == "LEADING SEPARATE"


def test_synchronized():
    result = _parse_working_storage(
        "    05  WS-BIN  PIC 9(4) COMP SYNCHRONIZED."
    )
    assert result.success
    item = _find_item(result, "WS-BIN")
    assert item is not None
    assert item.synchronized is True


def test_sync_left():
    result = _parse_working_storage(
        "    05  WS-BIN  PIC 9(4) COMP SYNC LEFT."
    )
    assert result.success
    item = _find_item(result, "WS-BIN")
    assert item is not None
    assert item.synchronized is True


def test_justified_right():
    result = _parse_working_storage(
        "    05  WS-NAME  PIC X(20) JUSTIFIED RIGHT."
    )
    assert result.success
    item = _find_item(result, "WS-NAME")
    assert item is not None
    assert item.justified is True


def test_just_bare():
    result = _parse_working_storage(
        "    05  WS-NAME  PIC X(20) JUST."
    )
    assert result.success
    item = _find_item(result, "WS-NAME")
    assert item is not None
    assert item.justified is True


def test_blank_when_zero():
    result = _parse_working_storage(
        "    05  WS-AMT  PIC 9(7)V99 BLANK WHEN ZERO."
    )
    assert result.success
    item = _find_item(result, "WS-AMT")
    assert item is not None
    assert item.blank_when_zero is True


def test_blank_when_zeros():
    result = _parse_working_storage(
        "    05  WS-AMT  PIC 9(7) BLANK WHEN ZEROS."
    )
    assert result.success
    item = _find_item(result, "WS-AMT")
    assert item is not None
    assert item.blank_when_zero is True


def test_ibm_extensions_sample_usage_fields():
    """The ibm_extensions.cbl sample already contains PACKED-DECIMAL and POINTER;
    verify the parser captures them correctly after the fix."""
    sample = (
        Path(__file__).parent.parent / "samples" / "ibm_extensions.cbl"
    )
    source = sample.read_text(encoding="utf-8")
    result = parse_cobol(source, filename="ibm_extensions.cbl")

    assert result.success

    packed = _find_item(result, "WS-PACKED-DECIMAL")
    assert packed is not None, "WS-PACKED-DECIMAL not found in AST"
    assert packed.usage == "PACKED-DECIMAL"

    pointer = _find_item(result, "WS-PCB-POINTER")
    assert pointer is not None, "WS-PCB-POINTER not found in AST"
    assert pointer.usage == "POINTER"
