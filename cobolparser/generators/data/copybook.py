"""The CopybookDataGenerator entry point and FD record framing.

Copybook parsing itself (:func:`parse_copybook_records`, :func:`select_record`,
:func:`wrap_copybook_fragment`) lives in :mod:`cobolparser.layout.copybook`
and is re-exported here.
"""

from __future__ import annotations

import os
import random

from ...layout.copybook import (
    parse_copybook_records,
    select_record,
    wrap_copybook_fragment,
)
from ...layout.errors import CopybookLayoutError
from ...layout.fields import (
    FieldSpec,
    VaryingLength,
    flatten_record,
    occurs_expansion_caveats,
)
from ...layout.options import DataGeneratorOptions
from ...layout.values import ValueFactory
from ...models.data_items import CobolDataItem
from .dataset import GeneratedDataset
from .encoding import record_length
from .views import build_record_views

__all__ = [
    "CopybookDataGenerator",
    "fd_record_length",
    "parse_copybook_records",
    "select_record",
    "wrap_copybook_fragment",
]


def fd_record_length(
    records: list[CobolDataItem],
    chosen: CobolDataItem,
    options: DataGeneratorOptions | None = None,
) -> int | None:
    """The fixed-length ``LRECL`` of *chosen*'s file, when it is longer than
    *chosen* itself.

    Every 01 under one FD describes the same record area, so in a RECFM=F
    file each record is the file's length, whichever 01 it happens to be --
    not the length of the 01 somebody picked with ``--record``.  That length
    is the largest 01 under the FD (what the compiler sizes the area to), or
    the FD's own fixed ``RECORD CONTAINS n`` when that is larger still.  A
    ``RECORD CONTAINS`` smaller than the largest 01 does not shrink the area,
    so every 01 of one FD gets the same answer.

    ``None`` when the layout's own length already is the answer: *chosen*
    belongs to no FD/SD (a bare copybook, a WORKING-STORAGE record), or it
    is the longest record of its file.  Module-level, like
    :func:`select_record`, because ``gen-data`` and ``decode`` must frame
    the same source the same way.
    """
    fd_name = chosen.get_metadata("fd_file_name")
    if not fd_name:
        return None
    own = build_record_views(chosen, options).framing_length
    lrecl = max(
        [
            own,
            *(
                build_record_views(item, options).framing_length
                for item in records
                if item is not chosen and item.get_metadata("fd_file_name") == fd_name
            ),
        ]
    )
    block = (chosen.get_metadata("fd_clauses") or {}).get("record") or {}
    declared = block.get("max")
    if declared is not None and block.get("min") is None and not block.get("varying"):
        lrecl = max(lrecl, int(declared))
    return lrecl if lrecl > own else None


class CopybookDataGenerator:
    """Generates synthetic CSV test data from a COBOL copybook layout.

    Example::

        generator = CopybookDataGenerator(DataGeneratorOptions(rows=50, seed=1))
        dataset = generator.generate_from_source(copybook_text)
        dataset.write_csv("customers.csv")
    """

    def __init__(self, options: DataGeneratorOptions | None = None) -> None:
        self.options = options or DataGeneratorOptions()

    # -- entry points -------------------------------------------------------

    def generate_from_file(
        self,
        path: str | os.PathLike[str],
        *,
        record: str | None = None,
        copybook_paths: list[str] | None = None,
    ) -> GeneratedDataset:
        """Read a copybook from *path* and generate a dataset from it."""
        with open(path, encoding="utf-8") as handle:
            source = handle.read()
        return self.generate_from_source(
            source, filename=str(path), record=record, copybook_paths=copybook_paths
        )

    def generate_from_source(
        self,
        source: str,
        *,
        filename: str = "<copybook>",
        record: str | None = None,
        copybook_paths: list[str] | None = None,
    ) -> GeneratedDataset:
        """Parse *source* and generate a dataset from one of its records.

        Args:
            source: Copybook text, or a full COBOL program.
            filename: Name used in error messages.
            record: Which level-01 record to use.  Defaults to the first.
            copybook_paths: Directories to expand ``COPY`` statements from
                (see :func:`parse_copybook_records`).  A ``COPY`` left
                unexpanded is named in the dataset's ``caveats``.

        Raises:
            CopybookLayoutError: if the copybook has no usable layout, or the
                requested *record* is not present.
        """
        warnings: list[str] = []
        records = parse_copybook_records(
            source, filename=filename, copybook_paths=copybook_paths, warnings=warnings
        )
        chosen = self._select_record(records, record, filename)
        dataset = self.generate_from_record(chosen)
        dataset.lrecl = fd_record_length(records, chosen, self.options)
        dataset.caveats[:0] = warnings
        return dataset

    def generate_from_record(self, record: CobolDataItem) -> GeneratedDataset:
        """Generate a dataset from an already-parsed record item."""
        fields = flatten_record(record, self.options)
        if not fields:
            raise CopybookLayoutError(
                f"{record.name}: record has no generatable fields "
                "(all FILLER, REDEFINES, or empty)"
            )

        seed = self.options.seed
        if seed is None:
            seed = random.randrange(2**31)
        rng = random.Random(seed)
        factory = ValueFactory(rng, self.options)

        rows = [
            [factory.value_for(spec, row) for spec in fields]
            for row in range(self.options.rows)
        ]
        # After the rows, deliberately: a copybook that declares no varying
        # range draws nothing here, and so generates byte-identical output to
        # a version of this package that had never heard of one.
        caveats = occurs_expansion_caveats(record, self.options) + self._unique_caveats(
            record, fields, factory
        )
        varying = self._varying_for(record, fields, caveats)
        lengths = self._draw_lengths(varying, fields, rng)
        if lengths is not None:
            self._write_length_field(fields, rows, lengths, varying, factory)
        return GeneratedDataset(
            record_name=record.name,
            fields=fields,
            rows=rows,
            seed=seed,
            varying=varying,
            declared_lengths=lengths,
            caveats=caveats,
            record_image_gap=self._record_image_gap(record, fields),
        )

    def _record_image_gap(
        self, record: CobolDataItem, fields: list[FieldSpec]
    ) -> tuple[int, int] | None:
        """``(covered, full)`` byte lengths when these options' layout is
        shorter than the record-image one; ``None`` when it is not."""
        full_options = self.options.for_record_image()
        if full_options == self.options:
            return None
        try:
            full = record_length(flatten_record(record, full_options))
            have = record_length(fields)
        except Exception:  # noqa: BLE001 -- a diagnostic, never a failure
            return None
        return (have, full) if have < full else None

    def _unique_caveats(
        self, record: CobolDataItem, fields: list[FieldSpec], factory: ValueFactory
    ) -> list[str]:
        """What ``unique_fields`` could not deliver (#526): a name that
        matches no generated column, and a column that repeats because its
        PICTURE ran out of distinct values."""
        caveats: list[str] = []
        known = {spec.name.upper() for spec in fields} | {
            spec.column.upper() for spec in fields
        }
        for name in self.options.unique_fields:
            if name.upper() not in known:
                caveats.append(
                    f"unique field {name} matches no generated field of record "
                    f"{record.name}; ignored"
                )
        for column in factory.duplicate_columns:
            caveats.append(
                f"unique field {column} repeats a value: its PICTURE cannot "
                f"hold {self.options.rows} distinct values"
            )
        return caveats

    # -- variable record length ---------------------------------------------

    def _varying_for(
        self,
        record: CobolDataItem,
        fields: list[FieldSpec],
        caveats: list[str] | None = None,
    ) -> VaryingLength | None:
        """The record-length range in force, or ``None`` for a fixed record.

        An explicit :attr:`DataGeneratorOptions.record_varying` wins -- it is
        the only way to say so for a bare copybook, which has no FD to read.
        Otherwise the record's own ``FD ... RECORD VARYING FROM min TO max``
        clause is used, which is present whenever the source parsed was a
        whole program rather than a copybook fragment.

        A range clamped or ignored to fit the layout appends a sentence
        saying so to *caveats* (see :meth:`VaryingLength.build`).
        """
        size = record_length(fields)
        declared = self.options.record_varying
        if declared is not None:
            return VaryingLength.build(
                declared[0],
                declared[1],
                None,
                size,
                caveats=caveats,
                source="requested RECORD VARYING",
            )
        return VaryingLength.from_fd_clauses(
            record.get_metadata("fd_clauses"), record_size=size, caveats=caveats
        )

    def _draw_lengths(
        self,
        varying: VaryingLength | None,
        fields: list[FieldSpec],
        rng: random.Random,
    ) -> list[int] | None:
        """One record length per row, drawn uniformly across the range.

        Uniform rather than weighted: the FD states the range and nothing
        else, so every length in it is equally a real record.  Drawn here,
        from the same seeded RNG the values came from, so a seed reproduces
        the record *lengths* as exactly as it reproduces their contents --
        which it could not if the encoder drew them at write time.

        Nothing is drawn when the record also has an ``OCCURS ... DEPENDING
        ON`` table.  Both mechanisms can be declared at once, but only one
        can decide, and the table does: its count is real data saying how
        many occurrences this record holds, while the FD range only bounds
        the length.  A drawn length would cut the table-trimmed body at an
        unrelated offset, and ``declared_lengths`` would report a number
        nothing honoured.

        Nothing is drawn either for an FD range without ``DEPENDING ON``
        (:attr:`VaryingLength.per_record` false): there each record is as
        long as its own 01, and a drawn length would cut it mid-field.
        """
        if (
            varying is None
            or not varying.per_record
            or any(spec.odo_controls for spec in fields)
        ):
            return None
        return [
            rng.randint(varying.minimum, varying.maximum)
            for _ in range(self.options.rows)
        ]

    @staticmethod
    def _write_length_field(
        fields: list[FieldSpec],
        rows: list[list[str]],
        lengths: list[int],
        varying: VaryingLength | None,
        factory: ValueFactory,
    ) -> None:
        """Put each row's own length in the ``DEPENDING ON`` field, if it has one.

        Usually it has none: the length item of a ``RECORD VARYING`` clause is
        normally a WORKING-STORAGE counter the program sets before a WRITE and
        the runtime fills in after a READ -- it travels in the RDW, not in the
        record.  When a copybook *does* put it in the record, leaving the
        generated value there would contradict the record's own length.
        """
        if varying is None or not varying.depending_on:
            return
        wanted = varying.depending_on.upper()
        for index, spec in enumerate(fields):
            if spec.name.upper() != wanted:
                continue
            for row, length in zip(rows, lengths, strict=True):
                row[index] = factory.render(spec, str(length))

    # -- helpers ------------------------------------------------------------

    @staticmethod
    def _select_record(
        records: list[CobolDataItem],
        record: str | None,
        filename: str,
    ) -> CobolDataItem:
        """Kept as a method for callers that already had it; see
        :func:`select_record`, which is the implementation."""
        return select_record(records, record, filename)
