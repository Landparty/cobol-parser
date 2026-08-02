"""Errors raised during copybook data generation."""

from __future__ import annotations


class CopybookLayoutError(ValueError):
    """Raised when a copybook cannot be turned into a usable record layout."""
