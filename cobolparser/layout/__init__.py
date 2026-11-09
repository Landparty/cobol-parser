"""Record layout: what a COBOL record looks like in bytes.

Turns DATA DIVISION items (from a copybook or a whole program) into flat
field specs with byte offsets, lengths, categories, OCCURS/REDEFINES
expansion and level-88 values.  Analyzers and generators both read these
facts, so the package sits below :mod:`cobolparser.analysis` and
:mod:`cobolparser.generators` and imports neither.

Modules:

* :mod:`.fields` -- ``FieldSpec``, ``FieldCategory``, ``flatten_record``
* :mod:`.offsets` -- ``compute_record_layout``, ``compute_program_data_items``
* :mod:`.program` -- ``ProgramLayoutIndex`` (a whole program's records)
* :mod:`.copybook` -- copybook parsing and record selection
* :mod:`.values` -- ``ValueFactory`` (values assignable to a field)
* :mod:`.options` -- ``DataGeneratorOptions``
* :mod:`.errors` -- ``CopybookLayoutError``, ``ProgramLayoutError``

Byte widths per USAGE live in :mod:`cobolparser._storage`.
"""

from __future__ import annotations

from .copybook import parse_copybook_records, select_record, wrap_copybook_fragment
from .errors import CopybookLayoutError, ProgramLayoutError
from .fields import FieldCategory, FieldSpec, flatten_record
from .offsets import compute_program_data_items, compute_record_layout
from .options import DataGeneratorOptions
from .program import FileFacts, ProgramLayoutIndex, ResolvedField
from .values import ValueFactory

__all__ = [
    "CopybookLayoutError",
    "DataGeneratorOptions",
    "FieldCategory",
    "FieldSpec",
    "FileFacts",
    "ProgramLayoutError",
    "ProgramLayoutIndex",
    "ResolvedField",
    "ValueFactory",
    "compute_program_data_items",
    "compute_record_layout",
    "flatten_record",
    "parse_copybook_records",
    "select_record",
    "wrap_copybook_fragment",
]
