"""The interface every single-program analyzer shares.

A program analyzer is constructed with its options, then run on one
program unit::

    report = SomeAnalyzer(options...).analyze(ast)
    report.to_dict()

:class:`ProgramAnalyzer` states that shape so code that runs analyzers
generically (``scan``, the CLI, the MCP server, a user's own pipeline) can be
typed against it instead of against each class. It is a
:class:`typing.Protocol`: an analyzer conforms by having the method, without
inheriting anything. The analyzers that read the shared facts also accept a
:class:`~.context.ProgramContext` in place of the AST.

Which analyzers conform, and which deliberately do not (they need more than
one program, a layout index, or annotate the AST instead of reporting), is
pinned by ``tests/contracts/test_analyzer_protocol.py``.
"""

from __future__ import annotations

from typing import Any, Protocol, TypeVar, runtime_checkable

from ..models.program import CobolProgram

R_co = TypeVar("R_co", covariant=True)


@runtime_checkable
class Report(Protocol):
    """An analyzer's result: a dataclass-like object with a JSON-ready
    ``to_dict()``."""

    def to_dict(self) -> dict[str, Any]: ...


@runtime_checkable
class ProgramAnalyzer(Protocol[R_co]):
    """Anything with ``analyze(ast) -> report`` over one program unit."""

    def analyze(self, ast: CobolProgram, /) -> R_co: ...


__all__ = ["ProgramAnalyzer", "Report"]
