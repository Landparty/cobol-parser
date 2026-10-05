"""Copybook parsing and the CopybookDataGenerator entry point."""

from __future__ import annotations

import os
import random
import re

from ..._lines import split_source_lines
from ...models.data_items import CobolDataItem
from ...models.program import CobolProgram
from ...parser import parse_cobol
from ...plugins.core import ErrorRecoveryMode
from .dataset import GeneratedDataset
from .encoding import record_length
from .errors import CopybookLayoutError
from .layout import FieldSpec, VaryingLength, flatten_record
from .options import DataGeneratorOptions
from .values import ValueFactory

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
    for raw in split_source_lines(source):
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
            "       " + line if line.strip() else ""
            for line in split_source_lines(source)
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


def select_record(
    records: list[CobolDataItem],
    record: str | None,
    filename: str = "<copybook>",
) -> CobolDataItem:
    """Pick the record called *record*, or the first one when it is ``None``.

    Module-level because both halves of the package need it and they need it
    to agree: generating data from ``--record CUST-REC`` and *decoding* a
    file through ``--record CUST-REC`` must land on the same 01, or a
    round-trip through the record image silently changes layout.

    Raises:
        CopybookLayoutError: if the named record is not one of *records*,
            listing the ones that are.
    """
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
        # After the rows, deliberately: a copybook that declares no varying
        # range draws nothing here, and so generates byte-identical output to
        # a version of this package that had never heard of one.
        caveats: list[str] = []
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
        )

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
        """
        if varying is None or any(spec.odo_controls for spec in fields):
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
