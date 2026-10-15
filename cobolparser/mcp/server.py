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

from collections.abc import Callable
from typing import Annotated, Any

import anyio.to_thread
from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import Field

from .tools import CobolTools
from .workspace import Workspace

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


def build_server(workspace: Workspace) -> FastMCP:
    """An MCP server answering about *workspace*, not yet running."""
    tools = CobolTools(workspace)
    server = FastMCP("cobol-parser", instructions=INSTRUCTIONS, log_level="WARNING")

    async def off_loop(call: Callable[[], dict[str, Any]]) -> dict[str, Any]:
        def locked() -> dict[str, Any]:
            # The parse cache and the stdout redirect are process-wide.
            with workspace.lock:
                return call()

        # A cancelled request answers at once; its thread finishes on its
        # own and only then releases the lock to the next call.
        return await anyio.to_thread.run_sync(locked, abandon_on_cancel=True)

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
        file: File,
        name: Annotated[
            str,
            Field(
                description="Paragraph or section ('PARA OF SECTION' when the "
                "name repeats), or a program this file CALLs"
            ),
        ],
        program: Program = None,
        limit: Limit = None,
    ) -> dict[str, Any]:
        """Who transfers control to a paragraph or section: every PERFORM,
        PERFORM THRU range, GO TO, SORT/MERGE procedure, CICS HANDLE, SQL
        WHENEVER and fall-through, with its location, plus whether the
        paragraph is reachable at all. For a program name, the CALL sites in
        this file."""
        return await off_loop(lambda: tools.callers_of(file, name, program, limit))

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

    for tool in (
        program_brief,
        explain_symbol,
        callers_of,
        record_layout,
        lint,
        read_source,
    ):
        server.add_tool(tool, annotations=_READ_ONLY, structured_output=True)
    return server


def run_stdio(workspace: Workspace) -> None:
    """Serve *workspace* over stdio until the client disconnects."""
    build_server(workspace).run("stdio")
