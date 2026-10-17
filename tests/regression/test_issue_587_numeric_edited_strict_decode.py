"""Issue #587: ``deedit_numeric`` checked only that each digit position held
a digit (or a suppression character), so bytes in an insertion, fixed sign,
``CR``/``DB`` or currency position -- and a space in a ``9`` position -- were
read past.  ``'9999999'`` in ``PIC ZZ9.99-`` decoded cleanly as 999.99,
``decode --strict`` exited 0, and ``compare`` called two different byte
strings equal.  The text must now be exactly what editing its value writes.
"""

from __future__ import annotations

import pytest

from cobolparser.generators.data import compare_records
from cobolparser.generators.data.decoding import RecordDecoder
from cobolparser.generators.data.editing import deedit_numeric, edit_numeric
from cobolparser.generators.data.encoding import EncodingOptions

COPYBOOK = (
    "       01 R.\n" "          05 ID   PIC 9(4).\n" "          05 ED   PIC ZZ9.99-.\n"
)


@pytest.mark.parametrize(
    ("picture", "text"),
    [
        ("ZZ9.99-", "9999999"),  # '.' and sign positions hold '9'
        ("ZZ9.99-", " 12.345"),  # sign position holds '5'
        ("ZZ9.99-", "  1.00+"),  # a '-' sign never shows '+'
        ("ZZ9.99-", "       "),  # zero edits as '  0.00 '
        ("ZZ9.99CR", " 12.34XX"),
        ("99B99", "12X34"),
        ("99/99/99", "12-31-99"),
        ("$ZZ9.99", "X 12.34"),
        ("ZZ9.99", " 12,34"),
        ("999.99", "1 3.4 "),
    ],
)
def test_text_no_edit_produces_is_rejected(picture: str, text: str) -> None:
    assert deedit_numeric(picture, text) is None


@pytest.mark.parametrize(
    ("picture", "value"),
    [
        ("ZZ9.99-", "-12.34"),
        ("ZZ9.99-", "12.34"),
        ("ZZ9.99CR", "-12.34"),
        ("ZZ9.99DB", "0"),
        ("99B99", "1234"),
        ("99/99/99", "123199"),
        ("$ZZ9.99", "1.5"),
        ("$$,$$9.99", "1234.56"),
        ("**,**9.99", "0"),
        ("+++,+++", "-514"),
        ("ZZ,ZZZ", "0"),
        ("ZZPPP", "57000"),
    ],
)
def test_every_edited_form_still_reads_back(picture: str, value: str) -> None:
    edited = edit_numeric(picture, value)
    assert edited is not None
    assert deedit_numeric(picture, edited) is not None


def _decode(ed_bytes: bytes):
    decoder = RecordDecoder.from_copybook_source(COPYBOOK, opts=EncodingOptions())
    return decoder, decoder.decode_bytes(b"0001" + ed_bytes)


def test_decode_reports_the_bad_bytes_as_a_field_error() -> None:
    _, result = _decode(b"9999999")
    assert result.error_count == 1
    assert "is not a value PIC ZZ9.99- can display" in result.records[0].errors[0]


def test_compare_no_longer_calls_different_bytes_equal() -> None:
    decoder, good = _decode(b" 12.34 ")
    _, bad = _decode(b" 12.345")
    diff = compare_records(good, bad, view=decoder.views.base)
    assert not diff.equal
