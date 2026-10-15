"""Generated dataset: CSV-serializable record layout plus synthetic rows."""

from __future__ import annotations

import csv
import io
import os
from dataclasses import dataclass, field, replace
from typing import Any

from .encoding import EncodingOptions, encode_record, hex_dump
from .encoding import minimum_record_length as _minimum_record_length
from .encoding import record_length as _record_length
from .encoding import row_record_length as _row_record_length
from .layout import FieldSpec, VaryingLength

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
        varying: The FD's ``RECORD VARYING FROM min TO max`` range, when the
            record declares one (or when the caller supplied one via
            ``DataGeneratorOptions.record_varying``).  ``None`` means the
            record's length is decided by the layout alone.
        declared_lengths: One record length per row, drawn from
            :attr:`varying` at generation time, or ``None`` when there is no
            range.  Applied only by the variable-length record formats;
            ``RecordFormat.FIXED`` writes full-length records whatever this
            says, because that is what asking for RECFM=F means.
        caveats: Ways this dataset is not what was asked for -- e.g. a
            ``RECORD VARYING`` range clamped to the bytes the layout
            describes, or ignored because nothing of it fit.  Printed in
            :meth:`to_hex_dump`'s header and on stderr by ``gen-data``.
    """

    record_name: str
    fields: list[FieldSpec]
    rows: list[list[str]]
    seed: int
    varying: VaryingLength | None = None
    declared_lengths: list[int] | None = None
    caveats: list[str] = field(default_factory=list)

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

        Every ``OCCURS`` occurrence present: the fixed-length record length,
        and the maximum (the ``LRECL``) for a variable-length file.

        Only meaningful when the dataset was generated with
        :meth:`~.options.DataGeneratorOptions.for_record_image` options --
        otherwise FILLER and capped OCCURS leave holes, and this reports the
        length of a record that no program would recognise.
        """
        return _record_length(self.fields)

    def minimum_record_length(self) -> int:
        """Byte length of the shortest record this dataset can produce.

        Every ``OCCURS ... DEPENDING ON`` table at its declared minimum, or
        the FD's own ``RECORD VARYING`` floor when that is what decides the
        length.  Equal to :meth:`record_length` when neither applies -- which
        is the machine-readable way of saying the record is fixed-length.

        The FD floor is used only when :attr:`declared_lengths` was actually
        drawn, i.e. when no table decides instead.  Reporting it for a record
        whose table decides would contradict :meth:`record_lengths` and
        :meth:`to_records`, which correctly ignore the FD range there.
        """
        if self.varying is not None and self.declared_lengths is not None:
            return self.varying.minimum
        return _minimum_record_length(self.fields)

    @property
    def is_variable_length(self) -> bool:
        """Whether this record's length can differ from row to row at all.

        True when some field sits inside an ``OCCURS ... DEPENDING ON``
        table, and true when the FD declares a ``RECORD VARYING`` range --
        the two independent ways a COBOL record varies.  A dataset for which
        this is False encodes identically under every
        :class:`~.encoding.RecordFormat` bar the RDW.
        """
        return self.varying is not None or any(
            spec.odo_controls for spec in self.fields
        )

    def _length_for(self, index: int) -> int | None:
        """The declared byte length of row *index*, if it has one."""
        if self.declared_lengths is None:
            return None
        return self.declared_lengths[index]

    def _resolved_options(self, opts: EncodingOptions | None) -> EncodingOptions:
        """*opts* with ``AUTO`` decided against this dataset, once.

        The encoder can only see a record-length range through a drawn
        ``data_length``; an FD range without ``DEPENDING ON`` draws none but
        still makes the file variable, so ``AUTO`` is settled here, where the
        :attr:`varying` range is known.
        """
        options = opts or EncodingOptions()
        fmt = options.resolved_format(self.fields, varying=self.varying is not None)
        return (
            options
            if fmt is options.record_format
            else replace(options, record_format=fmt)
        )

    def record_lengths(self, opts: EncodingOptions | None = None) -> list[int]:
        """Byte length of each row's record image, in row order.

        Computed from the layout rather than by encoding, so asking what a
        large dataset's records weigh does not cost building all of them.
        """
        options = self._resolved_options(opts)
        return [
            _row_record_length(
                self.fields, row, options, data_length=self._length_for(index)
            )
            for index, row in enumerate(self.rows)
        ]

    def to_records(self, opts: EncodingOptions | None = None) -> bytes:
        """Render every row as its real COBOL record image.

        This is the one output path where ``USAGE`` decides the bytes rather
        than just annotating them: a ``COMP-3`` field contributes packed
        nibbles, a ``COMP`` field a big-endian integer, a signed DISPLAY
        field an overpunched sign.  See :mod:`.encoding` for the conventions
        and their documented limits.
        """
        options = self._resolved_options(opts)
        return b"".join(
            encode_record(
                self.fields, row, options, data_length=self._length_for(index)
            )
            + options.record_separator
            for index, row in enumerate(self.rows)
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
            self._resolved_options(opts),
            record_name=self.record_name,
            data_lengths=self.declared_lengths,
            varying=self.varying,
            extra_caveats=self.caveats,
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
