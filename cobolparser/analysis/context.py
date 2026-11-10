"""One program unit's derived facts, each built at most once.

Several analyzers need the same expensive facts about a program: the
cross-reference (:class:`~.xref.XrefReport`), the control flow graph
(:class:`~.program_flow.ProgramFlowReport`) and the procedure index
(:class:`~._procedures.ProcedureIndex`). Before :class:`ProgramContext`, each
one rebuilt them, so ``lint`` alone ran the flow analyzer several times and
``gen-fixtures`` built the cross-reference in three places.

A context wraps one :class:`~cobolparser.models.program.CobolProgram` and
builds each fact lazily, on first use, then hands the same object to every
later reader. Every analyzer that reads one of these facts accepts either a
bare AST or a context in its ``analyze()``; a bare AST gets a context of its
own for the length of that one call, so existing callers keep working and
nothing is shared across calls unless the caller asks for it by passing the
same context::

    from cobolparser import parse_cobol
    from cobolparser.analysis import LintAnalyzer, ProgramContext

    ctx = ProgramContext(parse_cobol(source).ast)
    flow = ctx.flow                       # built here, once
    lint = LintAnalyzer().analyze(ctx)    # reuses ctx.flow and ctx.xref

The facts are shared, so a reader must not mutate them. A context also
assumes its AST does not change after the first fact is read: build a new
context after editing the tree.

Contained (nested) programs are separate units: each gets its own context,
which :meth:`ProgramContext.unit` builds once and keeps.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..models.program import CobolProgram

if TYPE_CHECKING:
    from ._procedures import ProcedureIndex
    from .program_flow import ProgramFlowReport
    from .xref import XrefReport


class ProgramContext:
    """Lazily built, memoized facts about one program unit.

    Args:
        ast: The program unit.
        flow: An already built control flow graph of *ast*, used instead of
            building one (for callers that kept one from an earlier step).
        xref: An already built cross-reference of *ast*, likewise.
    """

    def __init__(
        self,
        ast: CobolProgram,
        *,
        flow: ProgramFlowReport | None = None,
        xref: XrefReport | None = None,
    ) -> None:
        self.ast = ast
        self._flow = flow
        self._xref = xref
        self._procedures: ProcedureIndex | None = None
        self._procedures_built = False
        self._units: dict[int, ProgramContext] = {}

    @classmethod
    def of(
        cls,
        target: CobolProgram | ProgramContext,
        *,
        flow: ProgramFlowReport | None = None,
    ) -> ProgramContext:
        """*target* itself when it is a context, else a new context over it.

        *flow* is the ``flow_report=`` an analyzer was handed for backward
        compatibility: it seeds the context's flow graph unless the context
        already built one.
        """
        if isinstance(target, ProgramContext):
            if flow is not None and target._flow is None:
                target._flow = flow
            return target
        return cls(target, flow=flow)

    @property
    def xref(self) -> XrefReport:
        """The cross-reference of the unit (:class:`~.xref.XrefAnalyzer`)."""
        if self._xref is None:
            from .xref import XrefAnalyzer

            self._xref = XrefAnalyzer().analyze(self.ast)
        return self._xref

    @property
    def flow(self) -> ProgramFlowReport:
        """The control flow graph of the unit
        (:class:`~.program_flow.ProgramFlowAnalyzer`)."""
        if self._flow is None:
            from .program_flow import ProgramFlowAnalyzer

            self._flow = ProgramFlowAnalyzer().analyze(self.ast)
        return self._flow

    @property
    def procedures(self) -> ProcedureIndex | None:
        """Every named procedure of the PROCEDURE DIVISION, or ``None`` when
        the unit has none."""
        if not self._procedures_built:
            from ._procedures import ProcedureIndex

            division = self.ast.procedure_division
            self._procedures = (
                ProcedureIndex.build(division) if division is not None else None
            )
            self._procedures_built = True
        return self._procedures

    def unit(self, program: CobolProgram) -> ProgramContext:
        """The context of *program*: this one when it is this context's own
        AST, else a context built once per contained program and kept."""
        if program is self.ast:
            return self
        found = self._units.get(id(program))
        if found is None or found.ast is not program:
            found = ProgramContext(program)
            self._units[id(program)] = found
        return found


__all__ = ["ProgramContext"]
