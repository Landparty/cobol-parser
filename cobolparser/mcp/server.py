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

import threading
import time
from collections.abc import Callable
from typing import Annotated, Any

import anyio.from_thread
import anyio.to_thread
from mcp.server.fastmcp import Context, FastMCP
from mcp.server.fastmcp.prompts import Prompt
from mcp.types import ToolAnnotations
from pydantic import Field

from .envelope import DEFAULT_ANSWER_BYTES, fit_budget
from .hints import add_hints
from .prompts import PROMPTS
from .tools import CobolTools
from .workspace import Workspace

#: FastMCP finds the parameter to inject the request context into by a bare
#: ``Context`` annotation; ``Context[...]`` would be taken for an argument.
MCPContext = Context

INSTRUCTIONS = """\
Tools for answering questions about a mainframe codebase (COBOL, with the
PL/I, assembler and JCL around it) with exact parsers, instead of reading
programs by eye. COBOL programs are long, their meaning is spread across
copybooks, and byte layouts are easy to get wrong, so prefer these tools and
cite what they return. Root-wide answers carry coverage (the files read, by
language, and those no parser here reads): when it covers the question, a
short or empty list is the whole answer, with no text search needed.

Every result has the same envelope:
- answer: the tool's own result. Every location is {file, line[, column]}
  in the file on disk (a copybook is named as itself), relative to the
  workspace root. Cite these as file:line.
- caveats: what could NOT be checked (an unresolved COPY, a partial parse,
  an analyzer that failed, ...). A caveat changes what the answer proves:
  say so rather than presenting an incomplete answer as complete.
- truncated: lists that were cut to the limit, with their true totals.
  Narrow the question or raise limit instead of assuming completeness.
  An answer is also kept under a size budget: a list cut to fit it says
  reason "answer budget".
- next (when present): ready-made calls that usually answer the follow-up
  question. Suggestions, not facts.
"""

#: One paragraph of guidance per tool group, sent only when a tool of the
#: group is offered (the instructions are tokens too).
_GROUP_GUIDE: dict[str, str] = {
    "core": """\
Start with program_brief to learn what a program is and touches; then
explain_symbol for a data name, callers_of for a paragraph, record_layout for
a record's bytes, lint for what is wrong, business_rules for the decisions
and calculations it implements, read_procedure for a whole paragraph, and
read_source to show the code at a cited line. slice gives only the
statements that compute a field (or that it feeds), under their paragraphs:
read it before reading a whole program to explain one value. Before you
answer, pass the checkable statements of your answer to check_claims.
find_statements searches
parsed statements (by verb, operand, literal or paragraph) in one file or
the whole root: prefer it to a text search, which matches comments and
misses copybook code.

Across programs: codebase_overview for the whole workspace, callers_of with a
program name for every CALL/LINK/XCTL to it, impact_of_change for what a
change to a copybook or a field reaches, and where_from for where a field's
value comes from. codebase_overview takes language and path to look at only
the PL/I, assembler or COBOL programs, or one application's folder: pass
path when the question names an application, since the whole root is large.
program_brief with follow_calls gives every program a transaction runs,
each with the files and SQL tables it reads and writes; a callee with
several sources (a VSAM and a DB2 version) lists each under
implementations, with the JCL steps whose DDs say which one they run. The root is
indexed in the background at start; later calls reuse the index until a file
changes. PL/I and assembler programs (with the [pl1] / [hlasm] extras) are in
the call graph, callers_of and program_brief too; the other tools read COBOL
only.
""",
    "data": """\
Data and versions: diff_programs says what changed between two versions of a
program (behaviour, not lines); decode_record reads a data file through a
copybook's byte layout; gen_fixtures generates test data for every file,
CALL, SQL and CICS boundary a program touches, scenario by scenario.
""",
    "jcl": """\
How programs are run (needs the [jcl] extra; without it these tools answer
with the install command): jobs_running for every JCL step that runs a
program, with each of its SELECT files bound to a DD and a dataset (with
follow_calls, also every program it CALLs in turn and its language) and
each of those jobs step by step: the datasets every step reads and writes,
its SORT / IDCAMS control cards, and which earlier step fed what it reads;
dataset_users for every job, step and program that reads or writes a
dataset; jcl_job to read one JCL file's jobs, steps and DD statements,
with each job's run_order (when every step runs) and, for a SORT step, its
keys and OUTREC output already mapped onto the record's fields.
program_brief names the steps that run a program under run_by.
""",
}


def instructions_for(enabled: set[str]) -> str:
    """The server instructions for the tools in *enabled*."""
    parts = [INSTRUCTIONS]
    for group, names in TOOL_GROUPS.items():
        if enabled & set(names):
            parts.append(_GROUP_GUIDE[group])
    hidden = [t for t in ALL_TOOLS if t not in enabled]
    if hidden:
        parts.append(
            "Not offered by this server (start it with --tools all for "
            f"them): {', '.join(hidden)}.\n"
        )
    return "\n".join(parts)


_READ_ONLY = ToolAnnotations(readOnlyHint=True, idempotentHint=True)

File = Annotated[
    str,
    Field(description="Source file, relative to the root"),
]
Program = Annotated[
    str | None,
    Field(description="PROGRAM-ID of a unit (default: the outermost)"),
]
Limit = Annotated[
    int | None,
    Field(description="Max list length (default 50)"),
]
OptionalFile = Annotated[
    str | None,
    Field(description="File declaring the field (default: every program)"),
]
FullPaths = Annotated[
    bool,
    Field(description="Every hit's whole path, not shared with earlier hits"),
]
Depth = Annotated[
    int | None,
    Field(description="Max program boundaries to cross (0: stay in the program)"),
]


#: The tools by group. ``--tools`` takes a profile, group or tool names.
TOOL_GROUPS: dict[str, tuple[str, ...]] = {
    "core": (
        "codebase_overview",
        "program_brief",
        "explain_symbol",
        "callers_of",
        "impact_of_change",
        "where_from",
        "record_layout",
        "lint",
        "business_rules",
        "read_source",
        "read_procedure",
        "find_statements",
        "slice",
        "check_claims",
    ),
    "data": ("decode_record", "gen_fixtures", "diff_programs"),
    "jcl": ("jcl_job", "jobs_running", "dataset_users"),
}

ALL_TOOLS: tuple[str, ...] = tuple(t for g in TOOL_GROUPS.values() for t in g)


def select_tools(spec: str | None, workspace: Workspace) -> set[str]:
    """The tool names *spec* enables over *workspace*.

    *spec* is ``all``, ``auto`` (the default: ``core``, plus ``jcl`` when
    the root holds JCL), or a comma-separated list of group and tool names.
    Every tool definition is sent to the model on every turn, so a tool the
    workspace cannot use is tokens spent for nothing.
    """
    spec = (spec or "auto").strip().lower()
    if spec == "all":
        return set(ALL_TOOLS)
    if spec == "auto":
        enabled = set(TOOL_GROUPS["core"])
        if workspace.has_jcl():
            enabled |= set(TOOL_GROUPS["jcl"])
        return enabled
    enabled = set()
    for part in (p.strip() for p in spec.split(",")):
        if not part:
            continue
        if part in TOOL_GROUPS:
            enabled |= set(TOOL_GROUPS[part])
        elif part in ALL_TOOLS:
            enabled.add(part)
        else:
            choices = ", ".join(("all", "auto", *TOOL_GROUPS, *ALL_TOOLS))
            raise ValueError(f"unknown tool or group {part!r} (choose from {choices})")
    if not enabled:
        raise ValueError("--tools selects no tool")
    return enabled


def compact_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """*schema* without what costs tokens and tells a model nothing: the
    ``title`` pydantic derives from each name, and the ``anyOf [T, null]``
    plus ``default: null`` of an optional argument (not being ``required``
    already says it may be left out). Arguments are still validated against
    the full signature; only the advertised schema shrinks."""

    def walk(node: Any) -> Any:
        if isinstance(node, list):
            return [walk(n) for n in node]
        if not isinstance(node, dict):
            return node
        out = {k: walk(v) for k, v in node.items() if k != "title"}
        variants = out.get("anyOf")
        if isinstance(variants, list) and {"type": "null"} in variants:
            rest = [v for v in variants if v != {"type": "null"}]
            if len(rest) == 1 and isinstance(rest[0], dict):
                del out["anyOf"]
                out = {**rest[0], **out}
        if "default" in out and out["default"] is None:
            del out["default"]
        return out

    result: dict[str, Any] = walk(schema)
    if isinstance(schema.get("properties"), dict):
        # A property *named* title is an argument, not a schema keyword.
        result["properties"] = {
            name: walk(prop) for name, prop in schema["properties"].items()
        }
    return result


def build_server(
    workspace: Workspace,
    tools_spec: str | None = "all",
    max_answer_bytes: int | None = DEFAULT_ANSWER_BYTES,
) -> FastMCP:
    """An MCP server answering about *workspace*, not yet running, offering
    the tools *tools_spec* selects (:func:`select_tools`), each result cut
    to *max_answer_bytes* (:func:`~.envelope.fit_budget`; None or 0: no
    budget) and given next-step hints (:mod:`.hints`)."""
    enabled = select_tools(tools_spec, workspace)
    tools = CobolTools(workspace)
    server = FastMCP(
        "cobol-parser", instructions=instructions_for(enabled), log_level="WARNING"
    )

    async def off_loop(
        name: str,
        call: Callable[[], dict[str, Any]],
        ctx: MCPContext | None = None,
    ) -> dict[str, Any]:
        def locked() -> dict[str, Any]:
            # The parse cache and the stdout redirect are process-wide.
            with workspace.lock:
                workspace.progress = _progress_reporter(ctx) if ctx else None
                try:
                    result = call()
                finally:
                    workspace.progress = None
            # Hints first: they are a few dozen bytes the budget leaves be.
            add_hints(name, result, enabled)
            return fit_budget(result, max_answer_bytes)

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
        """Numbered source lines around file:line (at most 200)."""
        return await off_loop(
            "read_source", lambda: tools.read_source(file, line, before, after)
        )

    async def read_procedure(
        file: File,
        name: Annotated[str, Field(description="Paragraph or section")],
        program: Program = None,
    ) -> dict[str, Any]:
        """One whole paragraph or section, numbered, COPY lines cited in
        their copybook."""
        return await off_loop(
            "read_procedure", lambda: tools.read_procedure(file, name, program)
        )

    async def find_statements(
        verb: Annotated[
            str | None,
            Field(description="Verb or its start: WRITE, EXEC CICS, EXEC SQL SELECT"),
        ] = None,
        operand: Annotated[
            str | None, Field(description="Data or file name used by the statement")
        ] = None,
        role: Annotated[
            str | None, Field(description="Operand role: read, write, condition, ...")
        ] = None,
        literal: Annotated[
            str | None, Field(description="Text on the statement's line")
        ] = None,
        paragraph: Annotated[
            str | None, Field(description="Only statements in this paragraph")
        ] = None,
        file: Annotated[
            str | None, Field(description="Only this file (default: the whole root)")
        ] = None,
        program: Program = None,
        limit: Limit = None,
        ctx: MCPContext | None = None,
    ) -> dict[str, Any]:
        """Parsed statements matching every filter given (copybook code
        included, comments not), in one file or under the root."""
        return await off_loop(
            "find_statements",
            lambda: tools.find_statements(
                verb, operand, role, literal, paragraph, file, program, limit
            ),
            ctx,
        )

    async def slice(  # the tool's name; shadows the builtin only here
        file: File,
        field: Annotated[
            str, Field(description="Data item ('X OF Y' when it repeats)")
        ],
        direction: Annotated[
            str,
            Field(description="backward: what feeds it; forward: what it feeds"),
        ] = "backward",
        program: Program = None,
        limit: Limit = None,
        aliases: Annotated[
            bool, Field(description="Also follow inexact REDEFINES aliases")
        ] = False,
    ) -> dict[str, Any]:
        """Only the statements of one program that can affect a field (or
        that it affects), with the IFs they run under, each cited."""
        return await off_loop(
            "slice",
            lambda: tools.slice(file, field, direction, program, limit, aliases),
        )

    async def check_claims(
        claims: Annotated[
            list[dict[str, Any]],
            Field(
                description="Each {kind, subject, object, file?, program?}; kind: "
                "calls, copies, performs, unreachable, reachable, writes_field, "
                "sets_only_in, reads_dataset, writes_dataset, flows_to"
            ),
        ],
        ctx: MCPContext | None = None,
    ) -> dict[str, Any]:
        """Check statements of a draft answer: each confirmed, contradicted
        (with evidence) or not checkable (with why)."""
        return await off_loop("check_claims", lambda: tools.check_claims(claims), ctx)

    async def lint(
        file: File,
        rules: Annotated[
            list[str] | None,
            Field(description="Rule ids to run (default: all)"),
        ] = None,
        min_severity: Annotated[
            str | None,
            Field(description="Lowest severity to report: error, warning or info"),
        ] = None,
        limit: Limit = None,
    ) -> dict[str, Any]:
        """Every lint rule over a program in one pass; findings worst first,
        each with its location."""
        return await off_loop(
            "lint", lambda: tools.lint(file, rules, min_severity, limit)
        )

    async def explain_symbol(
        file: File,
        name: Annotated[
            str,
            Field(
                description="Data, condition, paragraph or file name ('X OF Y' to qualify)"
            ),
        ],
        program: Program = None,
        limit: Limit = None,
    ) -> dict[str, Any]:
        """A name's declaration (PICTURE, USAGE, offset, length, REDEFINES,
        level-88 values) and every reference with its role and paragraph."""
        return await off_loop(
            "explain_symbol", lambda: tools.explain_symbol(file, name, program, limit)
        )

    async def program_brief(
        file: File,
        program: Program = None,
        limit: Limit = None,
        follow_calls: Annotated[
            bool,
            Field(
                description="Also every program it runs through CALL / LINK / "
                "XCTL, each with the files and SQL tables it uses"
            ),
        ] = False,
    ) -> dict[str, Any]:
        """A program on one page: interface, files and their C/R/U/D use,
        SQL tables, calls, CICS/DL/I, unreachable paragraphs, health, worst
        lint findings, the JCL steps that run it; a PL/I or assembler file:
        its calls and includes. Start here; follow_calls for what a whole
        transaction or job step touches (a callee with several sources
        compares them under implementations: which one the jobs that run
        this program are set up for, by the DDs they code)."""
        return await off_loop(
            "program_brief",
            lambda: tools.program_brief(file, program, limit, follow_calls),
        )

    async def callers_of(
        name: Annotated[
            str,
            Field(description="Paragraph, section or PROGRAM-ID"),
        ],
        file: Annotated[
            str | None,
            Field(description="File holding the paragraph; omit for a PROGRAM-ID"),
        ] = None,
        program: Program = None,
        limit: Limit = None,
        ctx: MCPContext | None = None,
    ) -> dict[str, Any]:
        """Every PERFORM / GO TO / fall-through into a paragraph, and whether
        it is reachable; for a PROGRAM-ID, every CALL / LINK / XCTL to it
        under the root, each caller with how the call links (call_type:
        static, dynamic, PL/I FETCHABLE) and whether it runs online, in
        batch or under IMS (runs_as, evidence in runs_as_because): quote
        those rather than infer them from program names."""
        return await off_loop(
            "callers_of", lambda: tools.callers_of(file, name, program, limit), ctx
        )

    async def record_layout(
        file: File,
        record: Annotated[
            str,
            Field(description="Record, group or FD name"),
        ],
        program: Program = None,
        limit: Limit = None,
    ) -> dict[str, Any]:
        """A record's byte map: every field with PICTURE, USAGE, offset,
        length, OCCURS, REDEFINES and level-88 values."""
        return await off_loop(
            "record_layout", lambda: tools.record_layout(file, record, program, limit)
        )

    async def impact_of_change(
        name: Annotated[
            str,
            Field(description="Copybook member or data item"),
        ],
        file: OptionalFile = None,
        program: Program = None,
        depth: Depth = None,
        limit: Limit = None,
        full_paths: FullPaths = False,
        ctx: MCPContext | None = None,
    ) -> dict[str, Any]:
        """What a change reaches: for a copybook, every program COPYing it
        (each site says COPY or EXEC SQL INCLUDE: only the INCLUDEs go
        through the DB2 precompiler; commented_out lists programs whose only
        COPY of it is on a comment line, so they are not affected, and
        not_affected the programs beside them that do not copy it); for a
        field, everything its value
        flows into across programs, files, CALLs and DB2 columns."""
        return await off_loop(
            "impact_of_change",
            lambda: tools.impact_of_change(
                name, file, program, depth, limit, full_paths
            ),
            ctx,
        )

    async def where_from(
        field: Annotated[
            str, Field(description="Data item ('X OF Y' when it repeats)")
        ],
        file: OptionalFile = None,
        program: Program = None,
        depth: Depth = None,
        limit: Limit = None,
        full_paths: FullPaths = False,
        ctx: MCPContext | None = None,
    ) -> dict[str, Any]:
        """Where a field's value comes from across programs: the fields,
        datasets, DB2 columns and CALL arguments that flow into it."""
        return await off_loop(
            "where_from",
            lambda: tools.where_from(field, file, program, depth, limit, full_paths),
            ctx,
        )

    async def codebase_overview(
        limit: Limit = None,
        language: Annotated[
            str | None,
            Field(description="Only programs in COBOL, PL/I or assembler"),
        ] = None,
        path: Annotated[
            str | None,
            Field(description="Only programs under this folder (or glob)"),
        ] = None,
        ctx: MCPContext | None = None,
    ) -> dict[str, Any]:
        """The whole workspace on one page: programs (COBOL, PL/I, assembler)
        and health grades, call graph, missing programs and copybooks,
        duplicated code. language / path narrow every section to those
        programs (path: an application's folder, or a glob)."""
        return await off_loop(
            "codebase_overview",
            lambda: tools.codebase_overview(limit, language, path),
            ctx,
        )

    async def business_rules(
        file: File,
        program: Program = None,
        kind: Annotated[
            str | None,
            Field(description="decision, validation or calculation"),
        ] = None,
        procedure: Annotated[
            str | None,
            Field(description="Only rules in this paragraph or section"),
        ] = None,
        include_technical: Annotated[
            bool,
            Field(description="Include FILE STATUS / EOF / SQLCODE rules"),
        ] = False,
        limit: Limit = None,
    ) -> dict[str, Any]:
        """A program's decisions, validations and calculations as decision
        tables, with inputs, outputs, guards and locations."""
        return await off_loop(
            "business_rules",
            lambda: tools.business_rules(
                file, program, kind, procedure, include_technical, limit
            ),
        )

    async def diff_programs(
        old_file: Annotated[
            str, Field(description="The earlier version, relative to the root")
        ],
        new_file: Annotated[
            str, Field(description="The later version, relative to the root")
        ],
        old_program: Program = None,
        new_program: Program = None,
        category: Annotated[
            str | None,
            Field(description="program, file, data or procedure"),
        ] = None,
        rename_threshold: Annotated[
            float | None,
            Field(description="Similarity counted as a rename (default 0.8)"),
        ] = None,
        limit: Limit = None,
    ) -> dict[str, Any]:
        """What changed in behaviour between two versions of a program:
        interface, files, data items, paragraphs and statements."""
        return await off_loop(
            "diff_programs",
            lambda: tools.diff_programs(
                old_file,
                new_file,
                old_program,
                new_program,
                category,
                rename_threshold,
                limit,
            ),
        )

    async def decode_record(
        copybook: Annotated[
            str,
            Field(description="Copybook or program with the layout"),
        ],
        data_file: Annotated[
            str | None,
            Field(description="Data file (omit for the layout only)"),
        ] = None,
        record: Annotated[
            str | None,
            Field(description="01 record to use when the copybook has several"),
        ] = None,
        view: Annotated[
            str | None,
            Field(description="REDEFINES view to read through"),
        ] = None,
        skip: Annotated[int, Field(description="Records to skip first")] = 0,
        max_records: Annotated[
            int | None, Field(description="Records to decode (default 10)")
        ] = None,
        fields: Annotated[
            list[str] | None,
            Field(description="Only these fields"),
        ] = None,
        charset: Annotated[
            str | None,
            Field(description="ascii or ebcdic"),
        ] = None,
        endian: Annotated[
            str | None,
            Field(description="auto, big, little or native"),
        ] = None,
        record_format: Annotated[
            str | None,
            Field(description="fixed, variable, variable-bare or auto"),
        ] = None,
        record_separator: Annotated[
            str | None,
            Field(description="none, or newline between records"),
        ] = None,
        record_length: Annotated[
            int | None,
            Field(description="LRECL when not the layout's length"),
        ] = None,
        limit: Limit = None,
    ) -> dict[str, Any]:
        """Decode a data file's records through a copybook layout (COMP-3,
        binary, zoned, EBCDIC); without a data file, the layout and views."""
        return await off_loop(
            "decode_record",
            lambda: tools.decode_record(
                copybook,
                data_file,
                record,
                view,
                skip,
                max_records,
                fields,
                charset,
                endian,
                record_format,
                record_separator,
                record_length,
                limit,
            ),
        )

    async def gen_fixtures(
        file: File,
        program: Program = None,
        mode: Annotated[
            str,
            Field(description="happy, branches or all"),
        ] = "happy",
        seed: Annotated[
            int | None,
            Field(description="Random seed (default: cobol.yml, else 0)"),
        ] = None,
        rows: Annotated[
            int | None,
            Field(description="Rows per READ / FETCH sequence (default 3)"),
        ] = None,
        scenario: Annotated[
            str | None,
            Field(description="Only scenarios whose name contains this"),
        ] = None,
        limit: Limit = None,
    ) -> dict[str, Any]:
        """Test-data scenarios for a program: values for every mocked file,
        CALL, SQL and CICS boundary, and what to assert afterwards."""
        return await off_loop(
            "gen_fixtures",
            lambda: tools.gen_fixtures(
                file, program, mode, seed, rows, scenario, limit
            ),
        )

    async def jcl_job(
        file: Annotated[
            str,
            Field(description="JCL file, relative to the workspace root"),
        ],
        job: Annotated[
            str | None,
            Field(description="Only the job of this name (default: every job)"),
        ] = None,
        step: Annotated[
            str | None,
            Field(description="Only this step (STEP or INVOKE.STEP)"),
        ] = None,
        limit: Limit = None,
    ) -> dict[str, Any]:
        """One JCL file's jobs, steps and DD statements, procedures
        expanded, with the COBOL source of each program run. Each job has
        ``run_order``: the steps in order with when each runs (its COND in
        words), worth stating in any description of the job. A SORT step
        whose input a COBOL program reads has ``sort_layout``: the sort
        keys, INCLUDE tests and OUTREC output in field names, the input
        bytes not copied, and the layout the output is read through."""
        return await off_loop("jcl_job", lambda: tools.jcl_job(file, job, step, limit))

    async def jobs_running(
        program: Annotated[
            str,
            Field(description="Program name, as PGM= names it"),
        ],
        limit: Limit = None,
        follow_calls: Annotated[
            bool,
            Field(
                description="Also list every program it CALLs / LINKs / XCTLs "
                "in turn, with its language"
            ),
        ] = False,
    ) -> dict[str, Any]:
        """Every JCL step that runs a program, each SELECT file bound to its
        DD and dataset, DDs the step does not code, and each job step by
        step (datasets read and written, SORT / IDCAMS control cards, which
        step feeds which); with follow_calls,
        the COBOL, PL/I and assembler code the step runs through CALLs."""
        return await off_loop(
            "jobs_running",
            lambda: tools.jobs_running(program, limit, follow_calls),
        )

    async def dataset_users(
        dataset: Annotated[
            str,
            Field(description="Dataset name; z/OS wildcards %, *, ** allowed"),
        ],
        limit: Limit = None,
    ) -> dict[str, Any]:
        """Every job, step and program that uses a dataset, and whether it
        reads, creates, extends or writes it."""
        return await off_loop(
            "dataset_users", lambda: tools.dataset_users(dataset, limit)
        )

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
        read_procedure,
        find_statements,
        slice,
        check_claims,
        business_rules,
        diff_programs,
        decode_record,
        gen_fixtures,
        jobs_running,
        dataset_users,
        jcl_job,
    ):
        if tool.__name__ not in enabled:
            continue
        server.add_tool(tool, annotations=_READ_ONLY, structured_output=True)
        registered = server._tool_manager.get_tool(tool.__name__)
        if registered is not None:
            registered.parameters = compact_schema(registered.parameters)
    for spec in PROMPTS:
        server.add_prompt(
            Prompt.from_function(
                spec.function, name=spec.name, description=spec.description
            )
        )
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


def run_stdio(
    workspace: Workspace,
    tools_spec: str | None = "auto",
    max_answer_bytes: int | None = DEFAULT_ANSWER_BYTES,
    *,
    warm_up: bool = True,
) -> None:
    """Serve *workspace* over stdio until the client disconnects; with
    *warm_up*, every program's facts are computed in the background meanwhile,
    so the first cross-program question finds them ready."""
    server = build_server(workspace, tools_spec, max_answer_bytes)
    if warm_up:
        warm_indexes(workspace)
    server.run("stdio")


def warm_indexes(workspace: Workspace) -> threading.Thread:
    """Compute every program's facts in the background, then build the
    call/COPY graph and the JCL index from them, so the first cross-program
    question (``callers_of``, ``jobs_running``, ...) finds them built. Each
    index is built under :attr:`Workspace.lock`, so a tool call meanwhile
    waits for at most one of them, and a failure only means it is built on
    first use instead."""
    from .codebase_index import programs_index
    from .facts import store_for

    def run() -> None:
        facts_thread = store_for(workspace).warm()
        if facts_thread is not None:
            facts_thread.join()
        builders: list[Callable[[Workspace], Any]] = [programs_index]
        from .jcl_tools import jcl_available, jcl_index

        if jcl_available():
            builders.append(jcl_index)
        for build in builders:
            try:
                with workspace.lock:
                    build(workspace)
            except Exception:  # noqa: BLE001 -- warm-up is best-effort
                continue

    thread = threading.Thread(target=run, name="cobol-index-warmup", daemon=True)
    thread.start()
    return thread
