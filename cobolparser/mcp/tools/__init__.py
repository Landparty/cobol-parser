"""The MCP tools, as plain functions over a :class:`Workspace`.

Nothing here imports the MCP SDK: every tool takes plain arguments and
returns a plain dict (the :mod:`..envelope` shape), so it is unit-testable
without the ``[mcp]`` extra and callable from any other front end -- the
backend, the VS Code extension -- exactly as the server calls it.

Each tool answers one question a person asks about COBOL, joining analyzers
server-side, rather than mirroring a CLI subcommand: a whole ``xref`` report
of a large program would spend a model's context on the first call.

:class:`CobolTools` gathers one mixin per area; each module holds its
tools and the helpers only they use, :mod:`.common` what several share:

* :mod:`.structure` -- ``read_source``, ``explain_symbol``, ``record_layout``
* :mod:`.brief` -- ``program_brief``
* :mod:`.callers` -- ``callers_of``
* :mod:`.impact` -- ``impact_of_change``, ``where_from``
* :mod:`.overview` -- ``codebase_overview``
* :mod:`.analysis` -- ``lint``, ``business_rules``, ``diff_programs``
* :mod:`.data` -- ``decode_record``, ``gen_fixtures``
* the JCL tools (the ``[jcl]`` extra): :mod:`.jcl_index` (the ``jcl`` index,
  locations, which steps run a program), :mod:`.jcl_common`,
  :mod:`.jcl_job`, :mod:`.jcl_programs` (``jobs_running``),
  :mod:`.jcl_datasets` (``dataset_users``)
* ``read_procedure`` / ``find_statements`` (:mod:`..navigation`), ``slice``
  (:mod:`..slicing`) and ``check_claims`` (:mod:`..claims`) delegate.
"""

from __future__ import annotations

from typing import Any

from .analysis import AnalysisTools
from .brief import BriefTools
from .callers import CallersTools
from .data import DataTools
from .impact import ImpactTools
from .overview import OverviewTools
from .structure import StructureTools


class CobolTools(
    StructureTools,
    BriefTools,
    CallersTools,
    ImpactTools,
    OverviewTools,
    AnalysisTools,
    DataTools,
):
    """Every tool the MCP server exposes, bound to one workspace."""

    # -- delegated: navigation, slicing, claims, JCL (the [jcl] extra) -------

    def read_procedure(
        self, file: str, name: str, program: str | None = None
    ) -> dict[str, Any]:
        """One paragraph or section of *file*, whole (:mod:`.navigation`)."""
        from ..navigation import read_procedure

        return read_procedure(self.workspace, file, name, program)

    def slice(
        self,
        file: str,
        field: str,
        direction: str = "backward",
        program: str | None = None,
        limit: int | None = None,
        aliases: bool = False,
    ) -> dict[str, Any]:
        """The statements that can affect *field*, or that it affects, in
        one program (:mod:`.slicing`)."""
        from ..slicing import slice_field

        return slice_field(
            self.workspace, file, field, direction, program, limit, aliases
        )

    def check_claims(self, claims: list[dict[str, Any]]) -> dict[str, Any]:
        """Each claim confirmed, contradicted or not checkable
        (:mod:`.claims`)."""
        from ..claims import check_claims

        return check_claims(self, claims)

    def find_statements(
        self,
        verb: str | None = None,
        operand: str | None = None,
        role: str | None = None,
        literal: str | None = None,
        paragraph: str | None = None,
        file: str | None = None,
        program: str | None = None,
        limit: int | None = None,
    ) -> dict[str, Any]:
        """Statements by verb / operand / literal / paragraph
        (:mod:`.navigation`)."""
        from ..navigation import find_statements

        return find_statements(
            self.workspace,
            verb,
            operand,
            role,
            literal,
            paragraph,
            file,
            program,
            limit,
        )

    def jcl_job(
        self,
        file: str,
        job: str | None = None,
        step: str | None = None,
        limit: int | None = None,
    ) -> dict[str, Any]:
        """One JCL file's jobs, steps and DD statements, cited on disk."""
        from .jcl_job import jcl_job

        return jcl_job(self.workspace, file, job, step, limit)

    def jobs_running(
        self, program: str, limit: int | None = None, follow_calls: bool = False
    ) -> dict[str, Any]:
        """Every JCL step under the root that runs *program*, each of its
        ``SELECT`` files bound to a DD and a dataset; with *follow_calls*,
        the programs it CALLs in turn, in any language."""
        from .jcl_programs import jobs_running

        return jobs_running(self.workspace, program, limit, follow_calls)

    def dataset_users(self, dataset: str, limit: int | None = None) -> dict[str, Any]:
        """Every job, step and program under the root that uses *dataset*."""
        from .jcl_datasets import dataset_users

        return dataset_users(self.workspace, dataset, limit)
