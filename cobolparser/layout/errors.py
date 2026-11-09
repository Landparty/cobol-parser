"""Errors raised during copybook and program data generation."""

from __future__ import annotations


class CopybookLayoutError(ValueError):
    """Raised when a copybook cannot be turned into a usable record layout."""


class ProgramLayoutError(ValueError):
    """Raised when a program's layout cannot be indexed.

    Covers both a program that does not parse to an AST at all and a
    strict-mode copybook resolution failure -- a record layout with a hole
    in it is wrong, not merely incomplete, so this is a hard failure rather
    than a partial :class:`~.program_layout.ProgramLayoutIndex`.
    """
