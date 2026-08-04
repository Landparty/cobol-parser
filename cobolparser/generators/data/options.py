"""Options controlling test-data generation."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class DataGeneratorOptions:
    """Knobs controlling which fields become columns and how values are made.

    Attributes:
        rows: Number of records to generate.
        seed: RNG seed; ``None`` draws one at random and records it on the
            resulting dataset.
        include_filler: Emit FILLER items as columns.
        include_redefines: Emit fields belonging to a REDEFINES group.  Off by
            default because a redefinition aliases bytes already covered by
            another column.
        expand_occurs: Emit one column per OCCURS occurrence.  When off, only
            the first occurrence is emitted.
        max_occurs: Cap on occurrences expanded per table, or ``None`` for the
            table's own maximum.
        respect_values: Treat a VALUE clause as a fixed value for that column.
        use_condition_values: Draw from level-88 VALUEs when the field has any.
        semantic_hints: Use field-name heuristics (NAME, CITY, ZIP, DATE, ...)
            to make values readable.  Constraints from the PICTURE always win.
        header_style: ``"short"`` for the field's own name, ``"path"`` for the
            dotted path from the record root.
        unique_fields: Field names whose column must hold distinct values.
        blank_rate: Fraction of cells (0.0-1.0) left blank, for exercising
            missing-data paths.
    """

    rows: int = 10
    seed: int | None = None
    include_filler: bool = False
    include_redefines: bool = False
    expand_occurs: bool = True
    max_occurs: int | None = None
    respect_values: bool = True
    use_condition_values: bool = True
    semantic_hints: bool = True
    header_style: str = "short"
    unique_fields: tuple[str, ...] = ()
    blank_rate: float = 0.0

    def __post_init__(self) -> None:
        if self.rows < 0:
            raise ValueError("rows must be non-negative")
        if self.header_style not in ("short", "path"):
            raise ValueError("header_style must be 'short' or 'path'")
        if not 0.0 <= self.blank_rate <= 1.0:
            raise ValueError("blank_rate must be between 0.0 and 1.0")
        if self.max_occurs is not None and self.max_occurs < 1:
            raise ValueError("max_occurs must be at least 1")
