---
type: Module
title: MCP Server
description: cobolparser/mcp/ and `cobol-parser mcp` -- an MCP server (stdio) that lets AI agents question COBOL source; tools as plain functions (tools.py), the response envelope and caveat kinds (envelope.py), the workspace guard, cobol.yml and parse cache (workspace.py), the root-wide cross-program indexes (codebase_index.py), and the one SDK-importing module (server.py).
tags: [mcp, ai, agents, tools, stdio, caveats, source-map]
timestamp: 2026-10-16T00:00:00Z
---

# MCP Server

<!-- okf:external add_tool FastMCP -->

`cobol-parser mcp --root DIR` serves COBOL analysis tools to AI agents over
the Model Context Protocol, on stdin/stdout. Design and later phases:
`docs/plans/2026-10-15-mcp-server-design.md`; user guide:
`docs/mcp-server.md`. Start with `CobolTools` in `cobolparser/mcp/tools.py`.

| Module | Holds | Imports the SDK |
|---|---|---|
| `cobolparser/mcp/envelope.py` | `Response` (caveats + truncation), `Caveat`, `CAVEAT_KINDS`, `ToolError`, `MCP_SURFACE_VERSION`, limits | no |
| `cobolparser/mcp/workspace.py` | `Workspace` (path guard, `cobol.yml`, LRU parse cache), `ParsedProgram` (unit selection, `locate()`), `stdout_to_stderr()` | no |
| `cobolparser/mcp/tools.py` | `CobolTools`: `codebase_overview`, `program_brief`, `explain_symbol`, `callers_of`, `impact_of_change`, `where_from`, `record_layout`, `lint`, `read_source` | no |
| `cobolparser/mcp/codebase_index.py` | `programs_index` / `lineage_index` / `health_index`: facts about every program under the root, cached by `Workspace.index()` | no |
| `cobolparser/mcp/server.py` | `build_server()`, `run_stdio()`: typed wrappers registered on `FastMCP` | **yes** (`[mcp]` extra) |

## Contents

- [Tools](#tools)
- [Envelope](#envelope)
- [Workspace](#workspace)
- [Cross-program indexes](#cross-program-indexes)
- [Packaging and tests](#packaging-and-tests)
- [See also](#see-also)

## Tools

Tools answer questions, not subcommands: one call joins analyzers and
returns a small payload. Every list is capped (`limit`, default 50, max 500).

| Tool | Answers | Built on |
|---|---|---|
| `read_source(file, line, before, after)` | numbered lines around a citation, at most `MAX_SOURCE_LINES` (200) | the file, streamed through the guard (`newline=""`: splits as `split_source_lines` does); only the window is kept |
| `lint(file, rules, min_severity, limit)` | findings worst first, `summary` counts, `rules_run` | `LintAnalyzer` over **every** unit, `add_parse_errors`; defaults from `cobol.yml`'s `lint:` |
| `program_brief(file, program, limit)` | `size` (own statements only: `get_all_statements()` walks into contained units), `entry_points`, `interface` (entry points, parameters, `call_example`) and `interface_notes`, `files` (C/R/U/D string, open modes, organization, records, key, status field), `sql_tables`, `calls` (one row per target; dynamic `candidates` from `DynamicCallAnalyzer`; CICS LINK/XCTL `PROGRAM`), `cics_commands` / `exec_dli_commands` counts, `unreachable_procedures` (`DeadCodeAnalyzer`'s, via `_reachability()`; the flow graph's only if it raises), `perform_cycles`, `health`, `lint` (whole file: summary + `BRIEF_LINT` worst) | `ProgramFlowAnalyzer`, `DeadCodeAnalyzer`, `ProgramSignatureExtractor`, `CRUDMatrixGenerator`, `ProgramLayoutIndex.file_facts`, `TechnicalDebtAnalyzer`, `LintAnalyzer`; each section through `_attempt()`, so one analyzer raising costs only its section (`analyzer-failed`) |
| `callers_of(file, name, program, limit)` | per matching paragraph/section: `callers` (`from`, `type`, location, `thru`, `via_range`, `perform_type`, `condition`, `loop`), `callers_by_type`, `reachable`, `is_entry_point`. `file=None`, or a name that is no procedure of `file`: `_program_callers()` (`kind: program`, `scope: workspace`): `callers` (`program`, `via`, location, `from` (the paragraph), `dynamic`/`target_from`), `calling_programs`, `declared_in`, `unresolved_dynamic_calls`, a `note` when it is external or called by nobody | flow edges in `_CONTROL_EDGES`; a THRU is two edges (opener + `*_THRU` closer), so only openers count and `range_members` gives `via_range`. `reachable` is `DeadCodeAnalyzer`'s (memoized `_reachability()`), not `flow.unreachable_nodes`, which misses the paragraph after a PERFORMed one; a `FALL_THROUGH` edge is a caller only when it is in `DeadCodeReport.fall_through_edges` or leaves the first entry point (#486). Program level: the `programs` index's per-unit `_calls` rows: a static target, or a dynamic one whose traced `candidates` include the name; an incomplete dynamic row is listed, not counted |
| `impact_of_change(name, file, program, depth, limit)` | member mode (a member suffix, or `file=None` and a name in `graph.members`): `copied_by` (program, file, `copy_sites`), `copied_through_other_members` (chains), `fields`, `resolved_to`. Otherwise field mode, as `where_from` but forward | `CopybookImpactAnalyzer` over the `programs` index's `CodebaseGraph`, COPY lines from `graph.copy_sites`; field mode `LineageGraph.impact` |
| `where_from(field, file, program, depth, limit)` | `programs`, `tables`, `datasets`, `hits` (each: `program`, `field`, `node_kind`, `derived`, `confidence`, `file`, `location` of the statement that reaches it, `path` as one string per step `NODE (STATEMENT at file:line)`) | `LineageGraph.impact(..., "backward")` over the `lineage` index; `file` limits the start to that file's units (`program` to one). A declared field with no value flow is `found: true` with no hits and the graph's `notes`; `found: false` only for a name matching no item, and its `suggestions` never hold the name asked for (#546). A bare name matching several fields of one program gets an `ambiguous-name` caveat (from `ImpactResult.ambiguous`, #540) and every match is traced |
| `codebase_overview(limit)` | `index`, `programs` (grade, score, `calls`, `called_by`, `contained`, `unit_kind`), `call_graph` (`entry_programs`, `most_called`, `not_in_workspace`, `cycles`, `unresolved_dynamic_calls`), `copybooks` (`most_used`, `not_found`), `health` (`grades`, `worst`), `duplicated_code` (groups, members capped) | `programs` + `health` indexes; top lists are `OVERVIEW_TOP` (10) long, `limit` only lowers them |
| `record_layout(file, record, program, limit)` | `records[]`: `qualified_name` (`X OF Y`), `section`, `declared_at`, offset/length, `redefines`, `fields` in source order each with `declared_at`; an FD name gives every record of the file (`file`) | `compute_record_layout` per 01; `_declarations()` matches the n-th layout entry of a qualified name to its n-th declaration (FILLER repeats) and re-sorts, since the layout emits a group after its members |
| `explain_symbol(file, name, program, limit)` | each declaration matching `name` (or `X OF Y`): `declared_at`, `layout` (PICTURE, USAGE, `byte_offset`, `byte_length`, REDEFINES, level-88 values; a level-66 RENAMES item gets its THRU byte range, or an `incomplete-analysis` caveat when it cannot be placed, #485), `references` with role/statement/paragraph, `references_by_role`; `suggestions` when not found | `XrefAnalyzer`, `compute_program_data_items`; not found: `special_register` from xref's `is_special_register()` (no suggestions then) |

Invariants:

- A reference location carries **no column**: xref's column is the
  statement's, not the operand's, and would mislead.
- `byte_offset` 0 is reported (`_worth_showing`): `0 in (None, [], False)` is
  True in Python.
- xref's notes about undeclared names are passed on only when the answer is
  about an undeclared or unknown name (`_UNDECLARED_CAVEATS`); elsewhere they
  are tokens a model pays for and cannot use.
- Lint keeps errors when the list is cut: ordering is severity, then source.

## Envelope

Every tool returns `{"surface_version", "answer", "caveats", "truncated",
"program"?}` (`Response.build`). A location anywhere in `answer` is
`{"file", "line", "column"?}` in the file on disk, root-relative when it can
be; `null` with an `unmapped-location` caveat when the source map has no
entry. `caveats[].kind` is closed: <!-- okf:gen mcp-caveat-kinds -->`unresolved-copybook`, `partial-parse`, `analyzer-failed`, `incomplete-analysis`, `ambiguous-name`, `duplicate-declaration`, `unmapped-location`, `program-unit-selected`<!-- /okf:gen -->.
A new kind or a changed shape bumps `MCP_SURFACE_VERSION`. A request that
cannot be answered at all (path outside the workspace, unknown program unit,
bad severity) raises `ToolError`, which the SDK returns as an error result.

## Workspace

- **Guard.** `Workspace.resolve()` resolves symlinks, then `_within()`
  accepts anything under the root and, under a kept copybook directory
  outside the root (`_outside`), only a *member* (`_member_of`): suffix in
  `COPYBOOK_MEMBER_SUFFIXES` (lower-cased `CopybookSearchPath().extensions`:
  `.cpy`, `.cbl`, `.cob`, `""`) and no dot-named component below the
  directory. A non-member there gets "not a copybook member"; anything else
  "outside the workspace". The index walk (`program_files()`,
  `files_named()`) applies the same `_within()`, so a symlink out of the
  root is never indexed (#544).
- **Refused copybook directories (#544).** `_use_config()` asks
  `_refusal(dir)` of each resolved `copybook_path` entry: under the root is
  always fine; refused are the filesystem root, an ancestor of the root, the
  home directory or an ancestor of it (`Path.home()`), anything under
  `REFUSED_SYSTEM_DIRS` (`/etc`, `/proc`, `/sys`, `/dev`, `/boot`, `/run`,
  `/var/run`), and a path with a dot-named component. Refused entries are
  removed from the config itself (`dataclasses.replace`), so the parse and
  `CodebaseGraphBuilder` never search them, and listed as `(entry, reason)`
  in `refused_copybook_dirs`. `_parse()` adds an `unresolved-copybook`
  caveat naming them only when the parse has an unexpanded COPY (no new
  caveat kind); `_cmd_mcp` prints one stderr warning per refused directory.
  The same rules apply to every config source (found, `--config`, built in
  code).
- **Config.** `_root_config_file(root)`: `cobol.yml`/`cobol.yaml` in the
  root itself, never the CLI's walk-up (`find_config_file`) -- a parent's
  file does not count. Unless the CLI was given
  `--config`/`--no-config` (`args._config_explicit`), which passes the
  config in and fixes it. Otherwise `refresh_config()` (run by `config` and
  `resolve()`) re-checks the root's `cobol.yml` and compares its `(mtime_ns, size)`; a
  change reloads it, recomputes the guard's directories and clears the
  cache. A `ConfigError` becomes a `ToolError` and is retried next call.
  Copybook paths, source format, `debug_lines` and `define` come from it; no
  tool takes them.
- **Parse.** Always `COLLECT_ALL`. With copybook paths it expands with
  `skip_missing_copybooks=True`, so a missing member is left as written and
  the rest still expand. Any other `PreprocessingError` (circular COPY, a
  size or nesting limit) falls back to a plain parse with an
  `unresolved-copybook` caveat rather than failing. Each "COPY X was not
  expanded" parse warning becomes its own caveat; parse errors become
  `partial-parse`. `>>DEFINE` symbols are applied before a plain parse, as
  the CLI does.
- **Locations.** `ParsedProgram.locate()` maps an expanded-text line through
  `expansion_source_map` (identity when nothing expanded) and adds
  `source_column_offsets()` ([analysis/lint.md](analysis/lint.md)) to a
  known column.
- **Cache.** LRU keyed by resolved path (`--cache-size`, default 32). An
  entry is reused only while the `(mtime_ns, size)` of the program, of
  every copybook its source map names, **and of every copybook directory
  and its immediate subdirectories** is unchanged. The directories are what
  catch a member that was missing and has since been added: the parse read
  no file of it.
- **Threads.** `Workspace` is not thread-safe (cache, `redirect_stdout`).
  `server.py` runs each tool through `anyio.to_thread.run_sync(...,
  abandon_on_cancel=True)` holding `Workspace.lock`, so the event loop stays
  free and calls run one at a time.
- **Progress.** The cross-program tools take a FastMCP `Context` (annotated
  with the bare class, `MCPContext`: `Context[...]` is not detected).
  `off_loop` sets `Workspace.progress` for that one call; `_programs()` in
  `codebase_index.py` reports `(done, total, "reading FILE")` per file, sent
  through `anyio.from_thread.run(ctx.report_progress, ...)` at most once a
  `PROGRESS_INTERVAL`. A listener that raises is dropped, never fails the
  build.
- **Report memo.** `ParsedProgram.report(name, unit, build)` keeps each
  analyzer report beside the parse, so `program_brief` and `callers_of`
  share one flow graph and the cache drops both together.
- **Lint grading.** `_copybook_item_names()` takes from the source map the
  data items declared only inside a COPY member, so `lint` grades an unused
  copybook field as info, as the CLI does (the CLI finds the same set by
  diffing an unexpanded parse).
- **Indexes.** `Workspace.index(name, build)` keeps one value per name with
  the stamps its build returned, and rebuilds when any changed; `_use_config`
  drops them all. `tree_stamps()` stamps every directory under the root, so
  an added or removed program is noticed without re-reading every file.
- **stdout.** Over stdio stdout is the protocol; tools run library code
  under `stdout_to_stderr()`, and the server logs at WARNING.

## Cross-program indexes

`codebase_index.py`. Each index is one walk of `Workspace.program_files()`
(`cobol.yml` `extensions`, default `.cbl`/`.cob`/`.cobol`; hidden
directories and copybook directories inside the root skipped), parsing each
file with `cached_or_parse()`: a current cached parse is reused, a fresh one
never enters the LRU (a walk must not evict what the client asked about).
Only facts are kept, so one AST is live at a time. Every index records
`failed` (file -> reason) and `file_caveats`; tools fold them into a few
aggregated caveats (`_carry_index_caveats`, `_notes`: `NOTES_SHOWN` named,
then a count), with the root cut from library notes (`_relative`).

| Index | Built on first | Keeps |
|---|---|---|
| `programs` | program-level `callers_of`, `impact_of_change`, `codebase_overview` | `UnitFacts` per unit (id, file, depth, `unit_kind`, `_calls` rows with on-disk sites); the `CodebaseGraph` from `CodebaseGraphBuilder.build_from_results()` fed the same parses (no second parse); `copy_sites` |
| `lineage` | field-mode `impact_of_change`, `where_from` | every unit's `FieldFlowAnalyzer` report (after `apply_source_map`) in one `LineageGraph`; JCL under the root (`.jcl`/`.job`) through `load_jobs` when jcl-parser imports, else `jcl_note`; `edge_files` |
| `health` | `codebase_overview` | grade/score per unit (`TechnicalDebtAnalyzer` sharing the memoized flow and redundancy reports); `cross_file_clone_groups` over a hand-built `ScanReport`, members placed on disk |

Lineage locations: a `LineageGraph` hop carries its edge's origin line and,
when the report was source-mapped, its origin file (`Hop.origin_file`, from
the edge's `origin.file`), which `_hop_location` cites directly (#489: a
program line and a PROCEDURE DIVISION copybook line of one number used to
share a key, and the last written won). Without it, `edge_files` maps
`(PROGRAM, line, kind, statement)` to the file from the report's own edges
(`None` when two files claim one key -- never guessed); a program parsed
without expansion uses its own file; anything else is `null` with
`unmapped-location`. Join hops (dataset,
table, CALL) have no line and no `location`.

Cost: on 459 NIST programs with copybooks, the `programs` index takes about
a minute (56 s measured); `extract_copy_statements` (the COPY lexer) is the largest single cost,
which is why the index reuses the builder's COPY scan for its COPY lines
rather than running its own.

## Packaging and tests

- `[mcp]` extra (`mcp>=1.10,<2`, also in `[dev]`). mypy ignores missing
  `mcp`/`pydantic` imports, so the typecheck job needs no extra. Tools are
  registered with `add_tool()` rather than decorators, which
  `disallow_untyped_decorators` would reject when the SDK is untyped.
- `cobol-parser mcp` without the extra exits 1 naming the install command.
- Tests: `tests/unit/mcp_server/` (`test_mcp_tools.py` and
  `test_mcp_codebase.py`, the cross-program tools over copies of
  `tests/samples/enterprise/` and `tests/samples/lineage/`, need no SDK;
  `test_mcp_server.py` drives an in-memory client session and the CLI). The
  directory is not named `mcp`: a test package of that name shadows the SDK.

## See also

- [cli.md](cli.md) -- the `mcp` subcommand row, `cobol.yml`
- [analysis/lint.md](analysis/lint.md) -- `LintAnalyzer`, source-map origins
- [analysis/data-use.md](analysis/data-use.md) -- `XrefAnalyzer`
- [integration.md](integration.md) -- the other external surfaces
