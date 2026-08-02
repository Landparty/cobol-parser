"""Copybook parsing and the CopybookDataGenerator entry point."""

from __future__ import annotations

import os
import random
import re

from ...models.data_items import CobolDataItem
from ...models.program import CobolProgram
from ...parser import parse_cobol
from ...plugins.core import ErrorRecoveryMode
from .dataset import GeneratedDataset
from .errors import CopybookLayoutError
from .layout import flatten_record
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
