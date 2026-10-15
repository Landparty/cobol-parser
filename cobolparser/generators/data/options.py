"""Options controlling test-data generation."""

from __future__ import annotations

from dataclasses import dataclass, replace


@dataclass
class DataGeneratorOptions:
    """Knobs controlling which fields become columns and how values are made.

    Attributes:
        rows: Number of records to generate.
        seed: RNG seed; ``None`` draws one at random and records it on the
            resulting dataset.
        include_filler: Emit FILLER items as columns.
        include_condition_filler: Emit a FILLER that owns a level-88
            condition name even when ``include_filler`` is off. A program
            tests such a FILLER through its 88 (``05 PIC X. 88 FLAG-ON``), so
            program-scoped generation (gen-fixtures) needs its column to pin
            the branch's value on; a plain copybook CSV does not.
        include_redefines: Emit fields belonging to a REDEFINES group.  Off by
            default because a redefinition aliases bytes already covered by
            another column.
        expand_occurs: Emit one column per OCCURS occurrence.  When off, only
            the first occurrence is emitted.
        max_occurs: Cap on occurrences expanded per table, or ``None`` for the
            table's own maximum. Always subject to an internal hard ceiling
            (``layout._MAX_OCCURS_HARD_CAP``) regardless of this value, so a
            pathological ``OCCURS`` count in the source cannot exhaust memory.
        respect_values: Treat a VALUE clause as a fixed value for that column.
        use_condition_values: Draw from level-88 VALUEs when the field has any.
        semantic_hints: Use field-name heuristics (NAME, CITY, ZIP, DATE, ...)
            to make values readable.  Constraints from the PICTURE always win.
        header_style: ``"short"`` for the field's own name, ``"path"`` for the
            dotted path from the record root.
        unique_fields: Field names whose column must hold distinct values.
        blank_rate: Fraction of cells (0.0-1.0) left blank, for exercising
            missing-data paths.
        record_varying: ``(min, max)`` byte length range for the generated
            records, as an FD's ``RECORD VARYING FROM min TO max`` would
            declare.  Only needed for a bare copybook, which carries no FD:
            when the source is a whole program the clause is read off the
            record itself.  ``None`` (the default) means "take whatever the
            source says", which for a copybook is a fixed-length record.
    """

    rows: int = 10
    seed: int | None = None
    include_filler: bool = False
    include_condition_filler: bool = False
    include_redefines: bool = False
    expand_occurs: bool = True
    max_occurs: int | None = None
    respect_values: bool = True
    use_condition_values: bool = True
    semantic_hints: bool = True
    header_style: str = "short"
    unique_fields: tuple[str, ...] = ()
    blank_rate: float = 0.0
    record_varying: tuple[int, int] | None = None

    def for_record_image(self) -> DataGeneratorOptions:
        """A copy of these options that describes every byte of the record.

        The CSV-shaped defaults are deliberately lossy -- FILLER skipped
        because it names nothing a consumer can use, OCCURS capped so a big
        table does not swamp the columns.  A *record image* cannot afford
        either: a skipped FILLER is a hole in the record and a capped table
        truncates it, and both would go unnoticed because the bytes that
        remain still look plausible.  So: FILLER in, REDEFINES out (a
        redefinition aliases bytes the original already covers, and writing
        both would put two values in one place), every occurrence expanded.
        """
        return replace(
            self,
            include_filler=True,
            include_redefines=False,
            expand_occurs=True,
            max_occurs=None,
        )

    def __post_init__(self) -> None:
        if self.rows < 0:
            raise ValueError("rows must be non-negative")
        if self.header_style not in ("short", "path"):
            raise ValueError("header_style must be 'short' or 'path'")
        if not 0.0 <= self.blank_rate <= 1.0:
            raise ValueError("blank_rate must be between 0.0 and 1.0")
        if self.max_occurs is not None and self.max_occurs < 1:
            raise ValueError("max_occurs must be at least 1")
        if self.record_varying is not None:
            low, high = self.record_varying
            if low < 0 or high < 0:
                raise ValueError("record_varying lengths must be non-negative")
            if low > high:
                raise ValueError("record_varying min must not exceed max")
