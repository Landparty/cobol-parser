"""Backwards-compatible re-exports.

The canonical home is :mod:`cobolparser.generators.data`.  This module is
kept because `tests/unit/test_copybook_data_generator.py` and the CLI's
lazy import in `cli/commands/data.py` both import from this path.
"""

from __future__ import annotations

from .data.copybook import CopybookDataGenerator, parse_copybook_records
from .data.dataset import GeneratedDataset
from .data.errors import CopybookLayoutError
from .data.layout import FieldCategory, FieldSpec, flatten_record
from .data.options import DataGeneratorOptions

__all__ = [
    "CopybookDataGenerator",
    "CopybookLayoutError",
    "DataGeneratorOptions",
    "FieldCategory",
    "FieldSpec",
    "GeneratedDataset",
    "flatten_record",
    "parse_copybook_records",
]
