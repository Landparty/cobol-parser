"""Re-export shim for the package's byte-size authority.

The implementation lives in :mod:`cobolparser._storage`, which -- like
:mod:`cobolparser._errors` -- has zero internal dependencies so it can be
imported from *both* sides of a would-be import cycle.  It moved there when
:meth:`cobolparser.models.data_items.CobolDataItem.calculate_size` started
deferring to it: ``cobolparser.generators.data`` eagerly imports
``program_layout``, which imports ``cobolparser.models``, so a model
importing ``generators.data.storage`` directly would close that loop.

Every existing importer of this module keeps working unchanged.
"""

from __future__ import annotations

from ..._storage import (
    BINARY_FIXED_USAGES,
    BINARY_NATIVE_USAGES,
    BINARY_USAGES,
    DOUBLE_FLOAT_USAGES,
    FLOAT_USAGES,
    INDEX_BYTES,
    PACKED_USAGES,
    POINTER_64_BYTES,
    POINTER_BYTES,
    POINTER_USAGES,
    PROCEDURE_POINTER_BYTES,
    SINGLE_FLOAT_USAGES,
    binary_byte_length,
    packed_byte_length,
    storage_size,
)

__all__ = [
    "BINARY_FIXED_USAGES",
    "BINARY_NATIVE_USAGES",
    "BINARY_USAGES",
    "DOUBLE_FLOAT_USAGES",
    "FLOAT_USAGES",
    "INDEX_BYTES",
    "PACKED_USAGES",
    "POINTER_64_BYTES",
    "POINTER_BYTES",
    "PROCEDURE_POINTER_BYTES",
    "POINTER_USAGES",
    "SINGLE_FLOAT_USAGES",
    "binary_byte_length",
    "packed_byte_length",
    "storage_size",
]
