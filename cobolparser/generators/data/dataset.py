"""Generated dataset: CSV-serializable record layout plus synthetic rows."""

from __future__ import annotations

import csv
import io
import os
from dataclasses import dataclass
from typing import Any

from .encoding import EncodingOptions, encode_record, hex_dump
from .encoding import record_length as _record_length
from .layout import FieldSpec

# Line terminator shared by every CSV output path. Deliberately "\n" rather
# than the csv module's RFC 4180 "\r\n": both GeneratedDataset.to_csv and
# .write_csv must agree, or the same seed writes different bytes to stdout
# than to --output.
_DEFAULT_LINE_TERMINATOR = "\n"


@dataclass
class GeneratedDataset:
    """The generated rows plus the layout they were generated from.

    Attributes:
        record_name: Name of the level-01 record the columns came from.
        fields: Column specifications, in record order.
        rows: Generated rows, each a list of cells aligned to ``fields``.
        seed: The seed actually used -- pass it back to reproduce this run.
    """

    record_name: str
    fields: list[FieldSpec]
    rows: list[list[str]]
    seed: int

    @property
    def header(self) -> list[str]:
        """CSV header: one column name per field."""
        return [f.column for f in self.fields]

    def to_csv(self, *, line_terminator: str = _DEFAULT_LINE_TERMINATOR) -> str:
        """Render the dataset as CSV text, header row first."""
        buffer = io.StringIO()
        writer = csv.writer(buffer, lineterminator=line_terminator)
        writer.writerow(self.header)
        writer.writerows(self.rows)
        return buffer.getvalue()

    def write_csv(
        self,
        path: str | os.PathLike[str],
        *,
        line_terminator: str = _DEFAULT_LINE_TERMINATOR,
    ) -> None:
        """Write the dataset to *path* as CSV.

        Uses ``newline=""`` per the :mod:`csv` module's contract, so quoted
        cells containing newlines round-trip correctly on every platform.

        The line terminator defaults to the same ``"\\n"`` :meth:`to_csv`
        uses, *not* the :mod:`csv` module's ``"\\r\\n"``.  Sharing the default
        is what makes the byte-identical guarantee hold across output paths:
        otherwise ``gen-data -o out.csv`` and ``gen-data > out.csv`` would
        write different bytes for the same seed.  Pass ``"\\r\\n"`` explicitly
        for strict RFC 4180 output.
        """
        with open(path, "w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle, lineterminator=line_terminator)
            writer.writerow(self.header)
            writer.writerows(self.rows)

    def record_length(self) -> int:
        """Byte length of one record image of this layout.

        Only meaningful when the dataset was generated with
        :meth:`~.options.DataGeneratorOptions.for_record_image` options --
        otherwise FILLER and capped OCCURS leave holes, and this reports the
        length of a record that no program would recognise.
        """
        return _record_length(self.fields)

    def to_records(self, opts: EncodingOptions | None = None) -> bytes:
        """Render every row as its real COBOL record image.

        This is the one output path where ``USAGE`` decides the bytes rather
        than just annotating them: a ``COMP-3`` field contributes packed
        nibbles, a ``COMP`` field a big-endian integer, a signed DISPLAY
        field an overpunched sign.  See :mod:`.encoding` for the conventions
        and their documented limits.
        """
        options = opts or EncodingOptions()
        return b"".join(
            encode_record(self.fields, row, options) + options.record_separator
            for row in self.rows
        )

    def write_records(
        self,
        path: str | os.PathLike[str],
        opts: EncodingOptions | None = None,
    ) -> None:
        """Write :meth:`to_records` to *path*, in binary mode.

        Binary mode is not incidental: a COMP field's bytes routinely include
        0x0A and 0x0D, and a text-mode write would corrupt them on Windows.
        """
        with open(path, "wb") as handle:
            handle.write(self.to_records(opts))

    def to_hex_dump(self, opts: EncodingOptions | None = None) -> str:
        """Render the record images as an annotated hex dump.

        The readable form of :meth:`to_records` -- same bytes, plus the
        offset, length, and field each one belongs to.  Use this when a human
        is looking at the output; use :meth:`to_records` when a program is.
        """
        return hex_dump(
            self.fields,
            self.rows,
            opts or EncodingOptions(),
            record_name=self.record_name,
        )

    def to_dicts(self) -> list[dict[str, str]]:
        """Return the rows as column-name-keyed dicts."""
        header = self.header
        return [dict(zip(header, row, strict=True)) for row in self.rows]

    def to_dict(self) -> dict[str, Any]:
        """Serialise the dataset (layout plus rows) for JSON output."""
        return {
            "record_name": self.record_name,
            "seed": self.seed,
            "row_count": len(self.rows),
            "fields": [f.to_dict() for f in self.fields],
            "rows": self.to_dicts(),
        }
