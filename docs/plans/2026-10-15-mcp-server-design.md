# An MCP server for AI-assisted COBOL analysis

**Status:** All four phases built, `slice` included; the user guide is
`docs/mcp-server.md`. The "as built" sections record where each phase
differed from this plan. Read against
`cobol-parser` main @ `af1690d` on 2026-10-15. Implements
`docs/feature-ideas.md` #30.

**Decided 2026-10-15 (Samuel):** the official `mcp` SDK, and stdio only.

## The question

How should an AI agent use `cobolparser`'s analyzers on someone's COBOL code,
from any MCP client (Claude desktop, claude.ai, Cursor, an Agent SDK app), not
only from a shell?

## What already exists, and what it does not cover

| Piece | What it gives an agent | Gap |
|---|---|---|
| `.okf/` bundle | Static knowledge about the parser's *own* code | Nothing about the user's COBOL; no live analysis |
| `.claude/skills/cobol-analysis/` | Teaches an agent to run the CLI and cite its output | Needs a shell; lives in this repo only, not in the wheel; every call re-parses; CLI reports are sized for humans and tools, not context windows |
| CLI (`cobolparser/cli/parse.py`) | Every analyzer, JSON out | Flag surface an agent has to guess at; whole reports (an `xref` of a 20k-line program is megabytes) |

The analyzers already separate "this is false" from "I could not check this"
(`caveats`, `unresolved`, `failed_rules`, `undefined`). The server's job is
to carry that distinction to the model intact, in small payloads, with a
citation on every fact.

## Non-goals

- **No model calls inside `cobolparser`** (the rule stated in
  `docs/feature-ideas.md`). The server only answers questions; the client
  owns the model.
- **Not a subcommand mirror.** One tool per CLI subcommand spends the context
  window on the first call and leaves the model to do the joins itself.
- **No writes in v1.** No tool edits source or writes files outside the
  response. `gen-fixtures` / `gen-data` output is v3, returned inline.
- **No change to the core's zero-dependency rule.** Everything MCP-specific
  sits behind an optional extra.

## Design principles

1. **Tools are questions.** Each tool answers one thing a person asks about
   COBOL ("what is this program", "where is this field used", "what breaks if
   I change it"), joining analyzers server-side.
2. **Every fact carries `file:line`** in the file *on disk*, not the line in
   the copybook-expanded text. A fact inside an inlined copybook names the
   copybook. A fact the source map cannot place says so (`origin: null`)
   rather than guessing.
3. **Every response carries a caveats envelope.** An unresolved `COPY`,
   a parse error, an analyzer that raised, a truncated list: each is named.
4. **Payloads have a budget.** Lists are capped (default 50 items, `limit`
   argument up to 500), always with the true total and a `truncated` flag so
   the model knows to narrow the question rather than assume completeness.
5. **Parse once.** The server keeps parsed programs in memory across calls.

## Response envelope

Every tool returns the same outer shape, as MCP structured content (and the
same JSON as text content for clients that ignore structured output):

```json
{
  "answer": { "...": "tool-specific" },
  "citations_resolved": true,
  "caveats": [
    {"kind": "unresolved-copybook", "detail": "COPY CUSTREC not found on the copybook path",
     "effect": "fields from CUSTREC are missing; unused-variable results are incomplete"}
  ],
  "truncated": [{"field": "references", "shown": 50, "total": 412}],
  "program": {"file": "src/ACCTUPD.cbl", "program_id": "ACCTUPD", "parsed_at": "..."}
}
```

A location anywhere inside `answer` is always:

```json
{"file": "copy/CUSTREC.cpy", "line": 14, "column": 12}
```

`caveats[].kind` is a closed enum, documented with the tools, so a client can
branch on it: `unresolved-copybook`, `parse-error`, `partial-parse`,
`analyzer-failed`, `ambiguous-name`, `dynamic-call`, `unmapped-location`,
`duplicate-declaration`, `outside-workspace`.

## Tool set

### v1: one program

| Tool | Answers | Built on |
|---|---|---|
| `program_brief(file, program?)` | Program id, divisions, paragraph count, files (FD + organization), CALL targets (static and dynamic candidates), EXEC SQL tables / CICS commands, LINKAGE signature, health grade, top 5 lint findings | `ProgramSignatureExtractor`, `ProgramFlowAnalyzer`, `DynamicCallAnalyzer`, `TechnicalDebtAnalyzer`, `LintAnalyzer`, `ProgramLayoutIndex.file_facts` |
| `explain_symbol(file, name, program?)` | What a data item, condition name, paragraph or section is: declaration, PICTURE/USAGE, byte offset/length, REDEFINES chain, level-88 values, then every reference with its role (`write`/`read`/`condition`/...) and the statement text | `XrefAnalyzer`, `compute_program_data_items` |
| `callers_of(file, name, program?)` | Paragraph/section: who PERFORMs / GO TOs / falls into it, and whether it is reachable. Program id: which programs CALL it (needs `root`) | `ProgramFlowAnalyzer` edges, `DeadCodeAnalyzer`; `CodebaseGraph.callers_of` |
| `lint(file, rules?, min_severity?)` | Severity-graded findings, already source-mapped | `LintAnalyzer` + `lint.apply_source_map` |
| `record_layout(file, record, program?)` | The flattened byte map of one record: field, offset, length, PICTURE, USAGE, REDEFINES | `compute_program_data_items` |
| `read_source(file, line, before?, after?)` | The lines around a citation, so a client with no file access can follow one. Capped at 200 lines per call | the file on disk, through the workspace guard |

### v2: across programs (needs a workspace root)

| Tool | Answers | Built on |
|---|---|---|
| `impact_of_change(name, file?)` | Copybook member: every program that COPYs it, transitively. Field: the field-level forward lineage, across programs, joined through datasets / CALL arguments / DB2 columns | `CopybookImpactAnalyzer`, `LineageGraph.impact` |
| `where_from(field, file)` | Backward lineage: where this field's value comes from | `LineageGraph` (backward) |
| `codebase_overview(root?)` | Programs, call graph summary, copybook fan-out, worst health grades, cross-program clone groups | `CodebaseGraphBuilder`, `scan_files`, `cross_file_clone_groups` |

### v3: later

`business_rules`, `decode_record`, `gen_fixtures` (inline), `diff_programs`,
and `slice` once `docs/feature-ideas.md` #31 exists. `slice` is the single
most useful tool for a model reading a 20,000-line program, so it is the
first library feature this server would pull forward.

## Workspace, config and safety

- The server is started with a **root** (`cobol-parser mcp --root DIR`,
  default the cwd). Every `file` argument is resolved under it and refused
  outside it, through `preprocess/path_resolver.validate_path_within_directory`.
  Symlinks that leave the root are refused the same way.
- `cobol.yml` is discovered from the root with the existing
  `config/project.py` (`find_config_file` / `load_project_config`), so
  copybook paths, source format, dialect and defines are the ones the CLI and
  the VS Code extension already use. A tool never takes a copybook path
  argument: one config, one answer.
- The server is read-only and never executes anything from the workspace.

## Session cache

- Key: `(resolved path, mtime_ns, size, config fingerprint, program unit)`.
  A file edited between calls is re-parsed on the next call; nothing else is.
- Value: the `ParseResult` (with `expansion_source_map`) plus analyzer
  reports computed lazily on first use and kept beside it.
- Bound: LRU by entry count (default 32 programs), configurable. A
  `CodebaseGraph` / `LineageGraph` for the root is built once, on the first
  v2 call, and invalidated when any file under the root it read changes.
- Parsing uses `ErrorRecoveryMode.COLLECT_ALL`, as the CLI does, so a program
  with one bad statement still answers, with a `partial-parse` caveat.

## Phase 1 as built: what differed from this plan

- The shared location helper mostly existed already: `lint.stamp_report_origins`
  maps lines in any serialized report. What lived only in the CLI was the
  *column* offset, so Phase 1 moved `_lint_column_offset` into
  `analysis/lint.py` as `source_column_offsets()`; the CLI and the server both
  call it. The server maps each location itself (`ParsedProgram.locate`).
- xref reference columns are the statement's, not the operand's, so
  `explain_symbol` cites references by line only.
- A missing copybook made the expander raise, costing every other member its
  expansion. The review follow-up added `skip_missing_copybooks=True` to
  `expand_copybooks` / `parse_cobol_with_expansion`: the member is left
  unexpanded and named in a caveat, the rest expand. Other expansion
  failures (a circular COPY) still fall back to a plain parse with a caveat.
- Also from the review: tools run on a worker thread one at a time
  (`Workspace.lock`), `cobol.yml` is re-read when it changes, `read_source`
  streams the file, and `explain_symbol` flags special registers
  (`special_register`, through xref's new `is_special_register()`).
- `cobol-parser mcp` without the extra exits 1 (the CLI's `_fail()`), not 2.
- `[mcp]` is also in `[dev]`, so CI's coverage job tests the server too; the
  tests live in `tests/unit/mcp_server/` because a test package named `mcp`
  shadows the SDK.
- Two caveat kinds were not needed (`dynamic-call`, `outside-workspace`: a
  path outside the workspace is an error result) and one was added
  (`incomplete-analysis`, an analyzer's own note that it could not examine
  everything).

## Phase 2 as built

- `program_brief` lints the whole file (`lint.scope: "file"`): lint findings
  carry no program unit. Everything else in it is about the selected unit,
  and its statement counts leave out contained programs.
- Instead of `DeadCodeAnalyzer`, `callers_of` reports `reachable` from the
  flow graph's `unreachable_nodes`. A `PERFORM A THRU C` is one caller of A,
  B and C (`via_range`), not the two edges the graph stores.
- `callers_of` on a program name answers with the CALL sites in this file;
  which *other* programs call it waits for the Phase 3 cross-program index.
- `record_layout` cites every field's declaration. The layout emits a group
  after its members, so fields are re-sorted into source order.
- Analyzer reports are memoized on the cached parse
  (`ParsedProgram.report`), as "Session cache" planned.
- No library change was needed.

## Phase 3 as built

- **Three indexes, not one.** The root-wide cache is three separate builds
  (`cobolparser/mcp/codebase_index.py`): who calls what and the COPY graph,
  field lineage, and health with cross-program clones. Each is built on the
  first call that needs it, so a session that only asks who calls a
  program never pays for lineage. Each is kept until any file it read, or
  any directory under the root, changes.
- **One parse per file per index,** through the workspace's own settings
  (`>>DEFINE` symbols, skip-missing copybooks), reusing a current cached
  parse and never filling the LRU. Not `scan_files`: its parse has no
  `define` symbols and fails a whole expansion on one missing member, and
  its worker processes would parse with different settings than every
  other tool. The index is sequential; on 459 NIST programs with copybooks
  the call graph takes about a minute, most of it in the COPY lexer. The
  build sends MCP progress notifications per file read, so a client that
  resets its timeout on progress keeps waiting; other calls still queue
  behind the workspace lock until it finishes.
- **`CodebaseGraphBuilder.build_from_results()`** (library change) lets the
  index hand the builder its own parses instead of the builder parsing every
  file again, and `CodebaseGraph.copy_sites` keeps the line of every COPY the
  builder already scanned.
- **`callers_of` keeps one name.** `file` became optional: a name that is
  no paragraph of `file` (or any name, with no `file`) is answered at
  program level over the whole root, `scope: "workspace"`. The Phase 2
  "this file only" answer is widened to the root; its rows gained
  `program` and keep `from` (the paragraph holding the CALL).
- **`impact_of_change` picks its mode from the name.** A member suffix, or a
  name a COPY statement names when no `file` is given, is a copybook;
  anything else is a field. `where_from` is the same field query backward.
  Both take `depth`, the number of program boundaries a path may cross.
- **Datasets join through JCL under the root** (`.jcl`, `.job`) when
  jcl-parser is installed; a flow that stops at an unbound file says so.
- **Lineage paths are one string per step** (`NODE (STATEMENT at
  file:line)`), not nested objects: a path runs to a dozen steps and fifty
  hits of nested dicts cost a model more than the facts.
- A linkage step used to cite the program's first line; it now cites the
  `PROCEDURE DIVISION USING` line (library fix in `field_lineage.py`).
- No new caveat kind; `MCP_SURFACE_VERSION` stays "1".

## Phase 4 as built (2026-10-27)

- **Four tools, `slice` not yet.** `business_rules`, `diff_programs`,
  `decode_record` and `gen_fixtures` wrap analyzers that already existed;
  `slice` still waits for the library feature (`docs/feature-ideas.md`
  #31). No library change.
- **`business_rules`** memoizes the report beside the parse like the other
  per-program reports. `kind` and `procedure` filter; `summary` counts the
  whole program, so a filtered answer never reads as the whole catalogue. A
  calculation's `condition` (a copy of its formula) is dropped, and empty
  fields are left out.
- **`diff_programs`** parses both sides through the workspace (one config,
  so the diff means something) and cites each side in its own file.
- **`decode_record`** reads at most the first 16 MiB of a data file
  (`MAX_DECODE_BYTES`) and pages 10 records at a time with `skip`; the
  field list is given once and each record is a name -> value map, with
  per-record `errors`. Encoding arguments default to `cobol.yml`'s `data:`.
  The data file goes through the same workspace guard as any other read.
- **`gen_fixtures`** runs on the workspace's parse (so `>>DEFINE`, source
  format and skip-missing copybooks apply) rather than
  `analyze_from_file`, which re-parses with strict copybooks. Rows are a
  list per row aligned to `columns`, 3 per sequence by default; the seed
  defaults to `cobol.yml`'s `seed`, else 0, so the tool stays idempotent
  (the CLI's default seed is random). `callee_path` directories outside the
  root are skipped with a caveat: a callee is a whole program, which the
  guard would refuse to read there.
- **Prompts** (open question 3): `explain_program`, `review_program`,
  `plan_change`, `document_business_rules` and `onboard_codebase`, in
  `cobolparser/mcp/prompts.py` (no SDK import), registered by `server.py`.
- Adding tools and prompts is additive: `MCP_SURFACE_VERSION` stays "1".

## The one library change v1 needs: source-mapped locations everywhere

Today only `LintAnalyzer` (`lint.apply_source_map`) and `FieldFlowAnalyzer`
(`field_lineage.apply_source_map`) translate locations in expanded text back
to `(file, line)` on disk. `XrefAnalyzer`, `ProgramFlowAnalyzer`,
`DeadCodeAnalyzer` and the rest report lines in the expanded text, which is
wrong by the length of every `COPY` above them.

Rather than a third copy of the mapping, v1 adds one shared helper (say
`cobolparser/_origin.py`: `origin_of(location, source_map, column_offset)`),
used by the server for every location it emits, and moves the two existing
`apply_source_map` functions onto it. Analyzer report shapes do not change,
so `interface-contract.md` is untouched.

## Packaging

- New package `cobolparser/mcp/`:
  - `tools.py`: the tool functions. Plain Python taking and returning plain
    dicts, **no MCP import**, so they are unit-testable and reusable by any
    other front end (the VS Code extension, the backend).
  - `workspace.py`: root guard, config load, session cache.
  - `envelope.py`: the envelope, caveat kinds, truncation.
  - `server.py`: the only module that imports the MCP SDK; registers each
    tool with its schema and `readOnlyHint` / `idempotentHint` annotations.
- New optional extra `[mcp]` in `pyproject.toml`, the same pattern as `[jcl]`.
  `cobol-parser mcp` without it exits 2 with "install cobol-parser[mcp]".
- Transport: stdio only in v1 (what desktop clients launch). Streamable HTTP
  is a flag later if the backend wants to host it.
- Pure Python. Nothing here touches the Cython accelerators; it runs on
  whichever backend `COBOLPARSER_ACCEL` selects.
- Client setup is one line, documented in `docs/mcp-server.md`, e.g.
  `claude mcp add cobol -- cobol-parser mcp --root /path/to/checkout`.

### SDK choice

**Decided 2026-10-15 (Samuel): the official `mcp` SDK**, in the `[mcp]` extra,
pinned `<2`.

| Option | For | Against |
|---|---|---|
| Official `mcp` SDK in the extra (recommended) | Tracks protocol revisions for us; schemas from type hints | Pulls in pydantic and anyio (only for `[mcp]` users); the SDK's main branch renames `FastMCP` to `MCPServer` for v2, so pin `<2` and keep it inside `server.py` |
| Hand-rolled stdlib JSON-RPC over stdio | Zero dependencies, like `config/_yaml.py` | We own every protocol revision (initialize, capabilities, structured content, cancellation) forever |

Because `tools.py` never imports the SDK, switching later costs one module.

## Testing

- `tests/unit/mcp/test_tools.py`: every tool against `tests/samples/enterprise/`
  and `tests/samples/copybook_programs/`, asserting answers, that every
  location resolves to a real line in a real file, and the caveat for a
  missing copybook. Runs without the extra, so it counts toward the 90% floor.
- Payload budget tests: every tool on the largest sample stays under a fixed
  size (say 16 KB) at default limits.
- `tests/integration/test_mcp_server.py`: starts the server in-memory with the
  SDK client, lists tools, calls each once. Skipped when `[mcp]` is not
  installed; the `coverage` job omits `server.py` (a thin registration layer)
  rather than installing the extra.

## Docs and OKF

- `.okf/mcp.md` plus a row in `.okf/index.md` and the CLAUDE.md task table;
  `scripts/okf_check.py` already checks those claims.
- `docs/mcp-server.md`: client setup, tool reference, caveat kinds.
- `cobol-analysis` skill: one line saying to prefer the MCP tools when they
  are connected.
- `interface-contract.md`: the tool names and envelope become a third
  external surface, with an `MCP_SURFACE_VERSION` in the envelope.

## Phases

1. **Foundation.** `_origin.py` helper (and move both `apply_source_map` onto
   it), `workspace.py`, `envelope.py`, cache, `cobol-parser mcp`, and
   `read_source`, `lint`, `explain_symbol`. Small, and useful on its own.
2. **Rest of v1.** `program_brief`, `callers_of` (paragraph level),
   `record_layout`; docs and OKF.
3. **v2 cross-program.** Root-wide graph cache, `callers_of` at program level,
   `impact_of_change`, `where_from`, `codebase_overview`. Built (see "Phase 3
   as built").
4. **v3** as listed above. Built except `slice` (see "Phase 4 as built"),
   which comes once the library has it.

## Open questions

1. ~~SDK in an extra or a zero-dependency hand-rolled server?~~ Decided:
   the official SDK (see "SDK choice").
2. ~~stdio only for now, or HTTP too?~~ Decided: stdio only. The backend
   can call `CobolTools` directly.
3. ~~Should the server ship the `cobol-analysis` skill's guidance as MCP
   *prompts*?~~ Done in Phase 4: five task prompts that each carry the
   "run the tool, cite it, read the caveats" method.
