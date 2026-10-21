"""Issue #558: gen-data applied JUSTIFIED RIGHT and BLANK WHEN ZERO to a
VALUE-clause initial value. Initialisation by VALUE is not affected by either
clause (IBM LRM, VALUE clause), so ``PIC X(5) JUST VALUE 'AB'`` holds
``AB   `` and ``PIC 9(3) BLANK WHEN ZERO VALUE 0`` holds ``000``. Both
clauses still apply to generated values, which stand for MOVE results.
"""

from __future__ import annotations

from cobolparser.generators import (
    Charset,
    CopybookDataGenerator,
    DataGeneratorOptions,
    EncodingOptions,
    RecordDecoder,
)

COPYBOOK = """\
       01  R.
           05  A  PIC X(5) JUSTIFIED RIGHT VALUE 'AB'.
           05  E  PIC 9(3) BLANK WHEN ZERO VALUE 0.
           05  H  PIC X(4) JUSTIFIED RIGHT VALUE X'C1C2'.
           05  F  PIC X(5) JUSTIFIED RIGHT.
               88  F-AB VALUE 'AB'.
           05  G  PIC 9(3) BLANK WHEN ZERO.
               88  G-ZERO VALUE 0.
"""


def _image(tmp_path, charset: Charset = Charset.ASCII):
    path = tmp_path / "jr.cpy"
    path.write_text(COPYBOOK)
    opts = DataGeneratorOptions(rows=1, seed=1).for_record_image()
    dataset = CopybookDataGenerator(opts).generate_from_file(str(path))
    enc = EncodingOptions(charset=charset)
    return path, dataset, enc, dataset.to_records(enc)


def test_value_clause_ignores_justified_and_bwz(tmp_path) -> None:
    _path, _dataset, _enc, image = _image(tmp_path)
    assert image[0:5] == b"AB   "
    assert image[5:8] == b"000"
    assert image[8:12] == b"\xc1\xc2  "


def test_moved_values_still_justified_and_blanked(tmp_path) -> None:
    # The level-88 values stand for SET / MOVE results: both clauses apply.
    _path, _dataset, _enc, image = _image(tmp_path)
    assert image[12:17] == b"   AB"
    assert image[17:20] == b"   "


def test_decode_of_encode_is_the_row(tmp_path) -> None:
    path, dataset, enc, image = _image(tmp_path, Charset.EBCDIC)
    result = RecordDecoder.from_copybook_file(str(path)).decode_bytes(image, opts=enc)
    assert result.error_count == 0
    assert [list(r.values().values()) for r in result.records] == dataset.rows
