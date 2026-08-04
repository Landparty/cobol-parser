"""Confirms the copybook_data.py shim re-exports, rather than redefines.

Two independently-defined classes that compare equal but fail `is` would
break every downstream isinstance check -- exactly the failure a shim
introduces if someone later "fixes" it by re-defining a name instead of
re-exporting it.
"""

from __future__ import annotations

import pytest

_NAMES = [
    "CopybookDataGenerator",
    "CopybookLayoutError",
    "DataGeneratorOptions",
    "FieldCategory",
    "FieldSpec",
    "GeneratedDataset",
    "flatten_record",
    "parse_copybook_records",
]


@pytest.mark.parametrize("name", _NAMES)
def test_shim_and_canonical_are_the_same_object(name):
    from cobolparser.generators import copybook_data, data

    assert getattr(copybook_data, name) is getattr(data, name)
