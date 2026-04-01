"""Division parser module for COBOL parser refactoring.

This package provides the foundation for extracting division-specific parsing
logic from the monolithic parser into focused, testable components.

Structure:
- base.py: BaseDivisionParser abstract class
- factory.py: DivisionParserFactory for managing parsers
- identification.py: IdentificationDivisionParser (Phase 2.2)
- environment.py: EnvironmentDivisionParser (Phase 2.5)
- data.py: DataDivisionParser (Phase 2.8)
- procedure.py: ProcedureDivisionParser (Phase 2.11)
"""

from .base import BaseDivisionParser
from .factory import (
    DivisionParserFactory,
    DivisionType,
    get_default_factory,
    reset_default_factory,
)

__all__ = [
    "BaseDivisionParser",
    "DivisionParserFactory",
    "DivisionType",
    "get_default_factory",
    "reset_default_factory",
]
