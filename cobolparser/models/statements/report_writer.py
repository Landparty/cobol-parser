"""Report Writer control statement AST nodes: INITIATE, TERMINATE, SUPPRESS.

``GENERATE`` (the third Report Writer verb) lives in :mod:`.misc` as
:class:`~.misc.GenerateStatement`; these three complete the set so a Report
Writer program no longer loses its report start/stop statements to the
"unsupported statement" warning path.
"""

from typing import Any

from ..ast_base import SourceLocation
from .base import CobolStatement


class _ReportNameListStatement(CobolStatement):
    """Shared shape for the verbs that take one or more report names."""

    def __init__(self, statement_type: str, location: SourceLocation):
        super().__init__(statement_type, location)
        self.report_names: list[str] = []

    def add_report_name(self, name: str) -> None:
        """Record one report-name operand."""
        self.report_names.append(name)
        self._add_unique_operand(name)

    def to_dict(self) -> dict[str, Any]:
        result = super().to_dict()
        result["report_names"] = list(self.report_names)
        return result


class InitiateStatement(_ReportNameListStatement):
    """AST node for ``INITIATE report-name-1 [report-name-2 ...]``."""

    def __init__(self, location: SourceLocation):
        super().__init__("INITIATE", location)


class TerminateStatement(_ReportNameListStatement):
    """AST node for ``TERMINATE report-name-1 [report-name-2 ...]``."""

    def __init__(self, location: SourceLocation):
        super().__init__("TERMINATE", location)


class SuppressStatement(CobolStatement):
    """AST node for ``SUPPRESS [PRINTING]`` (inside a USE BEFORE REPORTING
    declarative)."""

    def __init__(self, location: SourceLocation):
        super().__init__("SUPPRESS", location)
        self.printing: bool = False  # explicit PRINTING keyword present

    def to_dict(self) -> dict[str, Any]:
        result = super().to_dict()
        result["printing"] = self.printing
        return result


__all__ = ["InitiateStatement", "TerminateStatement", "SuppressStatement"]
