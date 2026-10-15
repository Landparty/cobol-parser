"""The MCP server: the only module that imports the MCP SDK.

Each tool here is a typed wrapper over :class:`~.tools.CobolTools` -- the
argument annotations and docstrings become the tool schemas a client sees --
and nothing else. Keeping the SDK in this one module means a change of SDK
(its v2 renames ``FastMCP``) touches one file.

A parse can take seconds, so each call runs on a worker thread, one at a
time (:attr:`Workspace.lock`), and the event loop stays free for pings,
cancellation and other requests.

Needs the ``[mcp]`` extra: ``pip install 'cobol-parser[mcp]'``.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Annotated, Any

import anyio.from_thread
import anyio.to_thread
from mcp.server.fastmcp import Context, FastMCP
from mcp.types import ToolAnnotations
from pydantic import Field

from .tools import CobolTools
from .workspace import Workspace

#: FastMCP finds the parameter to inject the request context into by a bare
#: ``Context`` annotation; ``Context[...]`` would be taken for an argument.
MCPContext = Context

INSTRUCTIONS = """\
Tools for answering questions about COBOL source with an exact parser,
instead of reading a program by eye. COBOL programs are long, their meaning
is spread across copybooks, and byte layouts are easy to get wrong, so prefer
these tools and cite what they return.

Every result has the same envelope:
- answer: the tool's own result. Every location is {file, line[, column]}
  in the file on disk (a copybook is named as itself), relative to the
  workspace root. Cite these as file:line.
- caveats: what could NOT be checked (an unresolved COPY, a partial parse,
  an analyzer that failed, ...). A caveat changes what the answer proves:
  say so rather than presenting an incomplete answer as complete.
- truncated: lists that were cut to the limit, with their true totals.
  Narrow the question or raise limit instead of assuming completeness.

Start with program_brief to learn what a program is and touches; then
explain_symbol for a data name, callers_of for a paragraph, record_layout for
a record's bytes, lint for what is wrong, and read_source to show the code at
a cited line.

Across programs: codebase_overview for the whole workspace, callers_of with a
program name for every CALL/LINK/XCTL to it, impact_of_change for what a
change to a copybook or a field reaches, and where_from for where a field's
value comes from. The first such call indexes every program under the root,
which takes a while on a large one; later calls reuse the index until a file
changes.
"""

_READ_ONLY = ToolAnnotations(readOnlyHint=True, idempotentHint=True)

File = Annotated[
    str,
    Field(description="COBOL source file, relative to the workspace root"),
]
Program = Annotated[
    str | None,
    Field(
        description="PROGRAM-ID of one program unit, when the file holds "
        "several (default: the outermost)"
    ),
]
Limit = Annotated[
    int | None,
    Field(description="Most items to return in a list (default 50, max 500)"),
]
OptionalFile = Annotated[
    str | None,
    Field(
        description="COBOL source file the field is declared in, relative to "
        "the workspace root (omit it: every program declaring the name)"
    ),
]
Depth = Annotated[
    int | None,
    Field(
        description="Most program boundaries (dataset, CALL, DB2 table) a "
        "path may cross (default: no limit; 0 stays in the program)"
    ),
]


def build_server(workspace: Workspace) -> FastMCP:
    """An MCP server answering about *workspace*, not yet running."""
    tools = CobolTools(workspace)
    server = FastMCP("cobol-parser", instructions=INSTRUCTIONS, log_level="WARNING")

    async def off_loop(
        call: Callable[[], dict[str, Any]], ctx: MCPContext | None = None
    ) -> dict[str, Any]:
        def locked() -> dict[str, Any]:
            # The parse cache and the stdout redirect are process-wide.
            with workspace.lock:
                workspace.progress = _progress_reporter(ctx) if ctx else None
                try:
                    return call()
                finally:
                    workspace.progress = None

        # A cancelled request answers at once; its thread finishes on its
        # own and only then releases the lock to the next call.
        result: dict[str, Any] = await anyio.to_thread.run_sync(
            locked, abandon_on_cancel=True
        )
        return result

    async def read_source(
        file: Annotated[
            str, Field(description="File to read, relative to the workspace root")
        ],
        line: Annotated[int, Field(description="1-based line to centre on")] = 1,
        before: Annotated[int, Field(description="Lines to show before")] = 10,
        after: Annotated[int, Field(description="Lines to show after")] = 10,
    ) -> dict[str, Any]:
        """The source lines around file:line (at most 200), numbered as an
        editor numbers them. Use it to show the code behind a citation."""
        return await off_loop(lambda: tools.read_source(file, line, before, after))

    async def lint(
        file: File,
        rules: Annotated[
            list[str] | None,
            Field(
                description="Rules to run (default: all, or cobol.yml's lint "
                "rules): dead-code, unused-variables, move-type-check, "
                "io-sequence, linkage-check, recursion-check, complexity, "
                "dclgen-check, sql-cics-check"
            ),
        ] = None,
        min_severity: Annotated[
            str | None,
            Field(description="Lowest severity to report: error, warning or info"),
        ] = None,
        limit: Limit = None,
    ) -> dict[str, Any]:
        """Everything wrong with a program in one pass: dead code, unused
        data items, MOVE type mismatches, I/O sequencing, LINKAGE problems,
        recursion risks, complexity, DCLGEN and SQL/CICS checks. Findings are
        worst first, each with its location on disk."""
        return await off_loop(lambda: tools.lint(file, rules, min_severity, limit))

    async def explain_symbol(
        file: File,
        name: Annotated[
            str,
            Field(
                description="Data item, condition name (level 88), paragraph, "
                "section or file name; qualify as 'X OF Y' when it is ambiguous"
            ),
        ],
        program: Program = None,
        limit: Limit = None,
    ) -> dict[str, Any]:
        """What a name is and where it is used: its declaration (with
        PICTURE, USAGE, byte offset and length, REDEFINES, level-88 values),
        then every reference with its role (read, write, condition, ...),
        statement and paragraph. Suggests close names when it is not found."""
        return await off_loop(lambda: tools.explain_symbol(file, name, program, limit))

    async def program_brief(
        file: File, program: Program = None, limit: Limit = None
    ) -> dict[str, Any]:
        """What a program is, on one page: size, entry points, calling
        interface (USING parameters and a CALL example), files with their
        organization and C/R/U/D use, SQL tables, called programs (dynamic
        CALL candidates included), CICS and DL/I commands, unreachable
        paragraphs, health grade and the worst lint findings. Start here."""
        return await off_loop(lambda: tools.program_brief(file, program, limit))

    async def callers_of(
        name: Annotated[
            str,
            Field(
                description="Paragraph or section ('PARA OF SECTION' when the "
                "name repeats), or a PROGRAM-ID"
            ),
        ],
        file: Annotated[
            str | None,
            Field(
                description="COBOL source file the paragraph is in, relative "
                "to the workspace root; omit it to ask about a program"
            ),
        ] = None,
        program: Program = None,
        limit: Limit = None,
        ctx: MCPContext | None = None,
    ) -> dict[str, Any]:
        """Who transfers control to a paragraph or section: every PERFORM,
        PERFORM THRU range, GO TO, SORT/MERGE procedure, CICS HANDLE, SQL
        WHENEVER and fall-through, with its location, plus whether the
        paragraph is reachable at all. For a program, every CALL, EXEC CICS
        LINK and XCTL to it from any program under the root (dynamic CALLs
        included where their target can be traced)."""
        return await off_loop(lambda: tools.callers_of(file, name, program, limit), ctx)

    async def record_layout(
        file: File,
        record: Annotated[
            str,
            Field(
                description="Record or group name ('X OF Y' when it repeats), "
                "or a file (FD) name for all of its records"
            ),
        ],
        program: Program = None,
        limit: Limit = None,
    ) -> dict[str, Any]:
        """The byte map of a record: every field in source order with level,
        PICTURE, USAGE, byte offset and length from the start of the 01
        record, OCCURS, REDEFINES, level-88 values and where it is declared.
        Use it to read or build a record image or to check a field's
        position."""
        return await off_loop(lambda: tools.record_layout(file, record, program, limit))

    async def impact_of_change(
        name: Annotated[
            str,
            Field(
                description="Copybook member (name or file name) or data "
                "item ('X OF Y' when it repeats)"
            ),
        ],
        file: OptionalFile = None,
        program: Program = None,
        depth: Depth = None,
        limit: Limit = None,
        ctx: MCPContext | None = None,
    ) -> dict[str, Any]:
        """What a change reaches. For a copybook member: every program that
        COPYs it, directly or through another member, with the COPY lines,
        and the fields it declares. For a field: everything its value flows
        into, across programs, through MOVEs, arithmetic, files (joined by the
        JCL under the root), CALL arguments and DB2 columns, each with the
        path of statements that carries it."""
        return await off_loop(
            lambda: tools.impact_of_change(name, file, program, depth, limit), ctx
        )

    async def where_from(
        field: Annotated[
            str, Field(description="Data item ('X OF Y' when it repeats)")
        ],
        file: OptionalFile = None,
        program: Program = None,
        depth: Depth = None,
        limit: Limit = None,
        ctx: MCPContext | None = None,
    ) -> dict[str, Any]:
        """Where a field's value comes from, across programs: every field,
        file, dataset, DB2 column or CALL argument that flows into it, each
        with the path of statements that carries it."""
        return await off_loop(
            lambda: tools.where_from(field, file, program, depth, limit), ctx
        )

    async def codebase_overview(
        limit: Limit = None, ctx: MCPContext | None = None
    ) -> dict[str, Any]:
        """The whole workspace on one page: every program with its health
        grade and how many programs it calls and is called by; the call
        graph's entry programs, most-called programs, programs called but
        not present, and call cycles; the most-used and missing copybooks;
        the worst health scores; and paragraphs duplicated between programs.
        Start here for a codebase you do not know."""
        return await off_loop(lambda: tools.codebase_overview(limit), ctx)

    for tool in (
        codebase_overview,
        program_brief,
        explain_symbol,
        callers_of,
        impact_of_change,
        where_from,
        record_layout,
        lint,
        read_source,
    ):
        server.add_tool(tool, annotations=_READ_ONLY, structured_output=True)
    return server


#: Seconds between two progress notifications while an index is built.
PROGRESS_INTERVAL = 1.0


def _progress_reporter(
    ctx: MCPContext,
) -> Callable[[float, float | None, str], None]:
    """A reporter the worker thread calls, forwarding to *ctx* on the event
    loop at most once a :data:`PROGRESS_INTERVAL`. Without a progress token
    from the client, ``report_progress`` sends nothing."""
    last = [0.0]

    def report(done: float, total: float | None, message: str) -> None:
        now = time.monotonic()
        if now - last[0] < PROGRESS_INTERVAL:
            return
        last[0] = now
        anyio.from_thread.run(ctx.report_progress, done, total, message)

    return report


def run_stdio(workspace: Workspace) -> None:
    """Serve *workspace* over stdio until the client disconnects."""
    build_server(workspace).run("stdio")
