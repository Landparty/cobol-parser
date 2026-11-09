"""Synthetic test-data generation from a COBOL copybook layout.

Turns a copybook (or the record layouts of a full program) into a CSV of
generated rows: one column per elementary field, one row per generated
record.  Values honour each field's PICTURE category, size, digit counts,
sign, ``USAGE``, ``VALUE`` clause, and any level-88 condition values, so a
generated row is always assignable to the record it was generated from.

Typical use::

    from cobolparser.generators import (
        CopybookDataGenerator,
        DataGeneratorOptions,
    )

    generator = CopybookDataGenerator(DataGeneratorOptions(rows=100, seed=7))
    dataset = generator.generate_from_file("CUSTOMER.cpy")
    print(dataset.to_csv())

Generation is deterministic for a given ``seed``: the same seed and the same
copybook always produce byte-identical CSV.  When no seed is supplied one is
drawn at random and recorded on :attr:`GeneratedDataset.seed`, so an
interesting run can always be reproduced after the fact.

Design notes
------------

* **REDEFINES are excluded by default.**  A redefining item aliases the same
  bytes as the item it redefines, so emitting both would put two
  contradictory values in one row.  ``include_redefines`` opts in anyway
  (useful when the redefinition is the layout you actually care about).
* **OCCURS are expanded** into one column per occurrence, named with the
  COBOL subscript convention (``ITEM-CODE(1)``, ``ITEM-CODE(2)``, ...).
  ``OCCURS ... DEPENDING ON`` is *flattened* at the maximum bound -- a CSV
  column list has to cover every occurrence a record could hold -- with the
  generated counter kept inside the table's own bounds, so it always names a
  real occurrence.  Which occurrences a *record image* actually contains is
  a per-row question; see "Fixed and variable length" below.
* **Edited pictures** (``-ZZ,ZZ9.99``) contribute their *logical* numeric
  value, not the edited display form.  A CSV is consumed by tooling that
  wants the value; the edit mask is a presentation concern of the COBOL
  program.
* **FILLER is skipped** by default -- it names no field a consumer can use.

Record images
-------------

Everything above describes the CSV-shaped output, where a value is *display*
text regardless of the field's ``USAGE``.  For the bytes a COBOL program
would actually read -- ``COMP-3`` packed nibbles, ``COMP`` big-endian
binary, signed DISPLAY overpunches -- generate with
:meth:`DataGeneratorOptions.for_record_image` options and use
:meth:`GeneratedDataset.to_records` (or :meth:`~GeneratedDataset.to_hex_dump`
for the annotated, editor-readable form)::

    options = DataGeneratorOptions(rows=100, seed=7).for_record_image()
    dataset = CopybookDataGenerator(options).generate_from_file("CUSTOMER.cpy")
    dataset.write_records("CUSTOMER.BIN", EncodingOptions(charset=Charset.EBCDIC))

A dataset generated with the CSV-shaped defaults (FILLER skipped, OCCURS
capped) still renders records, but they are short: its record-image methods
then emit an :class:`IncompleteRecordImageWarning` naming the bytes covered
against the record's length.

:mod:`.storage` owns the byte widths this depends on and :mod:`.encoding`
the byte values, including a documented list of what is *not* modelled
(:func:`.encoding.encoding_caveats`).

Fixed and variable length
-------------------------

A copybook says how long a record *can* be, not whether the file holding it
is RECFM=F/FB (every record the layout's full length) or RECFM=V/VB (each
record only as long as its own ``OCCURS ... DEPENDING ON`` counter makes
it).  :class:`~.encoding.RecordFormat` on
:class:`~.encoding.EncodingOptions` says which to write::

    from cobolparser.generators.data import EncodingOptions, RecordFormat

    dataset.write_records(
        "ORDER.VB", EncodingOptions(record_format=RecordFormat.VARIABLE)
    )

``FIXED`` is the default, so a copybook without such a table -- which is
every copybook whose length cannot vary -- writes exactly the bytes it always
did.  ``VARIABLE`` drops the occurrences past each row's counter and frames
every record with the 4-byte RDW that lets a reader find the next one;
``VARIABLE_BARE`` drops the framing; ``AUTO`` picks from the layout.
:meth:`GeneratedDataset.record_lengths` reports what each row weighs and
:meth:`~GeneratedDataset.minimum_record_length` the floor.
"""

from __future__ import annotations

from .bundle import (
    BUNDLE_VERSION,
    BoundaryFixture,
    CoverageSummary,
    Expectation,
    FixtureBundle,
    Scenario,
)
from .compare import (
    CompareError,
    CompareResult,
    FieldDifference,
    RecordDifference,
    compare_files,
    compare_records,
)
from .copybook import CopybookDataGenerator, parse_copybook_records, select_record
from .dataset import GeneratedDataset, IncompleteRecordImageWarning
from .decoding import (
    DecodedField,
    DecodedRecord,
    DecodeResult,
    RecordDecoder,
    RecordDecodingError,
    decode_field,
    decode_record,
    decoded_hex_dump,
)
from .encoding import (
    MAX_VARIABLE_RECORD,
    RDW_SIZE,
    Charset,
    EncodingOptions,
    Endian,
    RecordEncodingError,
    RecordFormat,
    encode_field,
    encode_rdw,
    encode_record,
    encoding_caveats,
    hex_dump,
    minimum_record_length,
    record_length,
    row_record_length,
)
from ...layout.errors import CopybookLayoutError, ProgramLayoutError
from ...layout.fields import (
    FieldCategory,
    FieldSpec,
    OdoControl,
    VaryingLength,
    flatten_record,
    occurrence_count,
    present_indexes,
    unresolved_odo_counters,
)
from ...layout.options import DataGeneratorOptions
from ...layout.program import FileFacts, ProgramLayoutIndex, ResolvedField
from ..._storage import binary_byte_length, packed_byte_length, storage_size
from ...layout.values import ValueFactory
from .views import PlacedField, RecordView, RecordViews, build_record_views

__all__ = [
    "BUNDLE_VERSION",
    "BoundaryFixture",
    "Charset",
    "CompareError",
    "CompareResult",
    "CopybookDataGenerator",
    "CopybookLayoutError",
    "CoverageSummary",
    "DataGeneratorOptions",
    "DecodeResult",
    "DecodedField",
    "DecodedRecord",
    "EncodingOptions",
    "Endian",
    "Expectation",
    "FieldCategory",
    "FieldDifference",
    "FieldSpec",
    "FileFacts",
    "FixtureBundle",
    "GeneratedDataset",
    "IncompleteRecordImageWarning",
    "MAX_VARIABLE_RECORD",
    "OdoControl",
    "PlacedField",
    "ProgramLayoutError",
    "ProgramLayoutIndex",
    "RDW_SIZE",
    "RecordDecoder",
    "RecordDecodingError",
    "RecordDifference",
    "RecordEncodingError",
    "RecordFormat",
    "RecordView",
    "RecordViews",
    "ResolvedField",
    "Scenario",
    "ValueFactory",
    "VaryingLength",
    "binary_byte_length",
    "build_record_views",
    "compare_files",
    "compare_records",
    "decode_field",
    "decode_record",
    "decoded_hex_dump",
    "encode_field",
    "encode_rdw",
    "encode_record",
    "encoding_caveats",
    "flatten_record",
    "hex_dump",
    "minimum_record_length",
    "occurrence_count",
    "packed_byte_length",
    "parse_copybook_records",
    "present_indexes",
    "record_length",
    "row_record_length",
    "select_record",
    "storage_size",
    "unresolved_odo_counters",
]
