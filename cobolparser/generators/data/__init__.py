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
  ``OCCURS ... DEPENDING ON`` uses the maximum bound.
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

:mod:`.storage` owns the byte widths this depends on and :mod:`.encoding`
the byte values, including a documented list of what is *not* modelled
(:func:`.encoding.encoding_caveats`).
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
from .copybook import CopybookDataGenerator, parse_copybook_records
from .dataset import GeneratedDataset
from .encoding import (
    Charset,
    EncodingOptions,
    Endian,
    RecordEncodingError,
    encode_field,
    encode_record,
    encoding_caveats,
    hex_dump,
    record_length,
)
from .errors import CopybookLayoutError, ProgramLayoutError
from .layout import FieldCategory, FieldSpec, flatten_record
from .options import DataGeneratorOptions
from .program_layout import FileFacts, ProgramLayoutIndex, ResolvedField
from .storage import binary_byte_length, packed_byte_length, storage_size
from .values import ValueFactory

__all__ = [
    "BUNDLE_VERSION",
    "BoundaryFixture",
    "Charset",
    "CopybookDataGenerator",
    "CopybookLayoutError",
    "CoverageSummary",
    "DataGeneratorOptions",
    "EncodingOptions",
    "Endian",
    "Expectation",
    "FieldCategory",
    "FieldSpec",
    "FileFacts",
    "FixtureBundle",
    "GeneratedDataset",
    "ProgramLayoutError",
    "ProgramLayoutIndex",
    "RecordEncodingError",
    "ResolvedField",
    "Scenario",
    "ValueFactory",
    "binary_byte_length",
    "encode_field",
    "encode_record",
    "encoding_caveats",
    "flatten_record",
    "hex_dump",
    "packed_byte_length",
    "parse_copybook_records",
    "record_length",
    "storage_size",
]
