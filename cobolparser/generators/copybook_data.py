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
"""

from __future__ import annotations

import csv
import io
import os
import random
import re
from dataclasses import dataclass
from typing import Any

from ..models.data_items import (
    CobolDataItem,
)
from ..models.program import CobolProgram
from ..parser import parse_cobol
from ..plugins.core import ErrorRecoveryMode
from .data.errors import CopybookLayoutError
from .data.layout import (
    FieldCategory,
    FieldSpec,
    flatten_record,
)
from .data.options import DataGeneratorOptions
from .data.values import ValueFactory

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

# ---------------------------------------------------------------------------
# Copybook parsing
# ---------------------------------------------------------------------------

# A copybook is a DATA DIVISION fragment, not a compilable program, so it is
# wrapped in a minimal program skeleton before being handed to the parser.
_WRAPPER_HEAD = (
    "       IDENTIFICATION DIVISION.\n"
    "       PROGRAM-ID. COPYBOOK-LAYOUT.\n"
    "       DATA DIVISION.\n"
    "       WORKING-STORAGE SECTION.\n"
)
_WRAPPER_TAIL = "       PROCEDURE DIVISION.\n           CONTINUE.\n"

_PROGRAM_RE = re.compile(r"^\s*IDENTIFICATION\s+DIVISION\s*\.", re.IGNORECASE | re.M)
_PROGRAM_ID_RE = re.compile(r"^\s*PROGRAM-ID\s*\.", re.IGNORECASE | re.M)
# A one- or two-digit level number inside the sequence area (columns 1-6),
# followed by a separator -- the decisive free-form signal. Six-digit sequence
# numbers cannot match, and fixed-format code cannot start before column 8.
_FREE_FORM_LEVEL_RE = re.compile(r"^ {0,5}\d{1,2}[ .]")


def _looks_like_program(source: str) -> bool:
    """True when *source* is a whole program rather than a bare fragment."""
    return bool(_PROGRAM_RE.search(source) or _PROGRAM_ID_RE.search(source))


def _looks_fixed_format(source: str) -> bool:
    """Heuristically detect fixed-format column layout in a copybook fragment.

    A fixed-format line keeps columns 1-6 for the sequence number and column 7
    for the indicator, so real code never starts before column 8.  A free-form
    copybook, by contrast, starts its level numbers in column 1.

    A **short level number in the sequence area** (``01 REC.``, ``05 FLD``) is
    decisive: one or two digits followed by a space or period cannot be a
    six-digit sequence number, and cannot be fixed-format code, which starts
    at column 8.  Only one such line is needed -- a copybook that puts its 01
    in column 1 but indents subordinate items past column 8 is common, and
    majority-scoring it as fixed would slice the ``01`` line away entirely.

    Absent that signal, lines are scored on their sequence area: a blank one
    (indented code) or an all-digit one (a real sequence number, as in the
    NIST corpus) is fixed-shaped; anything else is code starting too early to
    be fixed format.  Scoring rather than requiring agreement keeps real
    copybooks -- which mix blank lines, comments, and continuations -- from
    being decided by a single odd line.

    When the two are tied the verdict is *fixed*: mis-indenting a fixed-format
    copybook pushes real code past column 72 and truncates it, which is worse
    than leaving an already-indented free-form copybook alone.
    """
    fixed = 0
    free = 0
    for raw in source.splitlines():
        line = raw.expandtabs(8)
        if not line.strip():
            continue
        if _FREE_FORM_LEVEL_RE.match(line):
            return False
        sequence_area = line[:6].strip()
        if not sequence_area or sequence_area.isdigit():
            fixed += 1
        else:
            free += 1
    return fixed >= free


def _wrap_fragment(source: str) -> str:
    """Embed a copybook fragment in a minimal, parseable program skeleton."""
    if _looks_fixed_format(source):
        body = source
    else:
        # Free-form fragment: shift into Area B so the fixed-format wrapper and
        # the fragment agree on a single column convention.
        body = "\n".join(
            "       " + line if line.strip() else "" for line in source.splitlines()
        )
    if not body.endswith("\n"):
        body += "\n"
    return _WRAPPER_HEAD + body + _WRAPPER_TAIL


def parse_copybook_records(
    source: str,
    *,
    filename: str = "<copybook>",
) -> list[CobolDataItem]:
    """Parse *source* and return its record roots (the level-01/77 items).

    Accepts either a bare copybook fragment or a complete COBOL program; a
    fragment is wrapped in a program skeleton first.  Parsing runs in
    ``COLLECT_ALL`` recovery so an unrelated defect elsewhere in a program
    still yields the data items that did parse.

    Raises:
        CopybookLayoutError: if the source yields no usable record layout.
    """
    if not source.strip():
        raise CopybookLayoutError(f"{filename}: copybook is empty")

    text = source if _looks_like_program(source) else _wrap_fragment(source)
    result = parse_cobol(
        text,
        filename=filename,
        error_recovery=ErrorRecoveryMode.COLLECT_ALL,
    )
    ast = result.ast
    if ast is None:
        detail = result.errors[0] if result.errors else "no AST produced"
        raise CopybookLayoutError(f"{filename}: could not parse copybook ({detail})")

    roots = _top_level_items(ast)
    records = [item for item in roots if item.level in (1, 77) and not item.is_filler]
    if records:
        return records

    # A copybook holding only subordinate items (level 02-49, no 01) is a
    # legitimate idiom: it is meant to be COPY'd *inside* an existing record.
    # Synthesise the record root its author assumed, so such a fragment is
    # still generatable rather than rejected.
    subordinate = [item for item in roots if 2 <= item.level <= 49]
    if subordinate:
        return [_synthesise_record(subordinate, filename)]

    raise CopybookLayoutError(
        f"{filename}: no level-01 record layout found in copybook"
    )


def _all_data_items(ast: CobolProgram) -> list[CobolDataItem]:
    """Return every data item in *ast*, outermost first, in source order."""
    items = ast.find_all_by_type("DataItem")
    return [item for item in items if isinstance(item, CobolDataItem)]


def _top_level_items(ast: CobolProgram) -> list[CobolDataItem]:
    """Return the data items that are not nested inside another data item."""
    items = _all_data_items(ast)
    nested = {id(child) for item in items for child in item.get_all_children()}
    return [item for item in items if id(item) not in nested]


def _synthesise_record(items: list[CobolDataItem], filename: str) -> CobolDataItem:
    """Wrap orphan subordinate items in a virtual level-01 record."""
    stem = os.path.splitext(os.path.basename(filename))[0].upper()
    # Reduce the stem to a legal COBOL data name: illegal characters become
    # hyphens, runs collapse, and leading/trailing hyphens are dropped, so the
    # placeholder filename "<copybook>" yields COPYBOOK-RECORD rather than
    # the malformed "-COPYBOOK--RECORD".
    name = re.sub(r"-+", "-", re.sub(r"[^A-Z0-9]", "-", stem)).strip("-")
    root = CobolDataItem(f"{name or 'COPYBOOK'}-RECORD", 1, items[0].location)
    for item in items:
        root.add_child(item)
    return root


# Line terminator shared by every CSV output path. Deliberately "\n" rather
# than the csv module's RFC 4180 "\r\n": both GeneratedDataset.to_csv and
# .write_csv must agree, or the same seed writes different bytes to stdout
# than to --output.
_DEFAULT_LINE_TERMINATOR = "\n"


# ---------------------------------------------------------------------------
# Dataset
# ---------------------------------------------------------------------------


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
    ) -> GeneratedDataset:
        """Read a copybook from *path* and generate a dataset from it."""
        with open(path, encoding="utf-8") as handle:
            source = handle.read()
        return self.generate_from_source(source, filename=str(path), record=record)

    def generate_from_source(
        self,
        source: str,
        *,
        filename: str = "<copybook>",
        record: str | None = None,
    ) -> GeneratedDataset:
        """Parse *source* and generate a dataset from one of its records.

        Args:
            source: Copybook text, or a full COBOL program.
            filename: Name used in error messages.
            record: Which level-01 record to use.  Defaults to the first.

        Raises:
            CopybookLayoutError: if the copybook has no usable layout, or the
                requested *record* is not present.
        """
        records = parse_copybook_records(source, filename=filename)
        chosen = self._select_record(records, record, filename)
        return self.generate_from_record(chosen)

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
        return GeneratedDataset(
            record_name=record.name,
            fields=fields,
            rows=rows,
            seed=seed,
        )

    # -- helpers ------------------------------------------------------------

    @staticmethod
    def _select_record(
        records: list[CobolDataItem],
        record: str | None,
        filename: str,
    ) -> CobolDataItem:
        if record is None:
            return records[0]
        wanted = record.upper()
        for item in records:
            if item.name.upper() == wanted:
                return item
        available = ", ".join(item.name for item in records)
        raise CopybookLayoutError(
            f"{filename}: record '{record}' not found (available: {available})"
        )
