---
type: Module
title: MCP Server
description: cobolparser/mcp/ and `cobol-parser mcp` -- an MCP server (stdio) that lets AI agents question COBOL source; tools as plain functions (tools.py), the task prompts (prompts.py), the response envelope and caveat kinds (envelope.py), the workspace guard, cobol.yml and parse cache (workspace.py), the root-wide cross-program indexes (codebase_index.py), and the one SDK-importing module (server.py).
tags: [mcp, ai, agents, tools, stdio, caveats, source-map]
timestamp: 2026-10-28T00:00:00Z
---

# MCP Server

<!-- okf:external add_tool FastMCP Prompt from_function -->

`cobol-parser mcp --root DIR` serves COBOL analysis tools to AI agents over
the Model Context Protocol, on stdin/stdout. Design and later phases:
`docs/plans/2026-10-15-mcp-server-design.md`; user guide:
`docs/mcp-server.md`. Start with `CobolTools` in `cobolparser/mcp/tools.py`.

| Module | Holds | Imports the SDK |
|---|---|---|
| `cobolparser/mcp/envelope.py` | `Response` (caveats + truncation), `Caveat`, `CAVEAT_KINDS`, `ToolError`, `MCP_SURFACE_VERSION`, limits | no |
| `cobolparser/mcp/workspace.py` | `Workspace` (path guard, `cobol.yml`, LRU parse cache), `ParsedProgram` (unit selection, `locate()`), `stdout_to_stderr()` | no |
| `cobolparser/mcp/tools.py` | `CobolTools`: `codebase_overview`, `program_brief`, `explain_symbol`, `callers_of`, `impact_of_change`, `where_from`, `record_layout`, `lint`, `read_source`, `business_rules`, `diff_programs`, `decode_record`, `gen_fixtures`, and `jcl_job` / `jobs_running` / `dataset_users` delegating to `jcl_tools.py` | no |
| `cobolparser/mcp/jcl_tools.py` | the JCL tools (`jcl_job`, `jobs_running`, `dataset_users`), the `jcl` index (`jcl_index`, `JclIndex`, `JclFile`), `_Locator` (job file vs procedure member), `INSTALL_HINT`; reads JCL through `cobolparser.jcl`, so the `[jcl]` extra | no |
| `cobolparser/mcp/claims.py` | `check_claims()`, `CLAIM_KINDS`, `MAX_CLAIMS` (25), one checker per kind (`_CHECKERS`) | no |
| `cobolparser/mcp/slicing.py` | `slice_field()` (the `slice` tool), `MAX_SLICE_STATEMENTS` | no |
| `cobolparser/mcp/navigation.py` | `read_procedure()`, `find_statements()`, `statement_rows()` / `StatementRow`, the `statements` index (`statements_index()`), `statement_verb()` | no |
| `cobolparser/mcp/hints.py` | `add_hints()`: the `next` calls per tool, `MAX_HINTS` | no |
| `cobolparser/mcp/prompts.py` | `PROMPTS` (`PromptSpec`): `explain_program`, `review_program`, `plan_change`, `document_business_rules`, `onboard_codebase`, each a plain function returning the request text | no |
| `cobolparser/mcp/codebase_index.py` | `programs_index` / `lineage_index` / `health_index`: assembled from per-file facts, cached by `Workspace.index()` | no |
| `cobolparser/mcp/facts.py` | `FileFacts` (one parse's facts for every index), `compute_facts()`, `FactsStore` (current facts kept, stale ones recomputed in a spawn pool, pickled to `cache_dir`, `warm()`), `store_for()`, `surveyed()`, `default_cache_dir()` | no |
| `cobolparser/mcp/server.py` | `build_server()`, `run_stdio()`: typed wrappers registered on `FastMCP`, and `PROMPTS` through `Prompt.from_function` | **yes** (`[mcp]` extra) |

## Contents

- [Tools](#tools)
- [Prompts](#prompts)
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
| `read_source(file, line, before, after)` | numbered lines around a citation, at most `MAX_SOURCE_LINES` (200); the cut trims context, never `line`: `line` and its `after` lines first, the rest of the budget from `before` (#537), with a `truncated` entry | the file, streamed through the guard (`newline=""`: splits as `split_source_lines` does) in the encoding the parse detected (`_source_lines`, #522; EBCDIC / UTF-16 converted whole); only up to `MAX_SOURCE_LINES - 1` lines either side of `line` are kept |
| `lint(file, rules, min_severity, limit)` | findings worst first, `summary` counts, `rules_run` | `LintAnalyzer` over **every** unit, `add_parse_errors`; defaults from `cobol.yml`'s `lint:` |
| `program_brief(file, program, limit)` | `size` (own statements only: `get_all_statements()` walks into contained units), `entry_points`, `interface` (entry points, parameters, `call_example`) and `interface_notes`, `files` (C/R/U/D string, open modes, organization, records, key, status field; EXEC CICS file-control files included, a data-item `FILE(...)` reported as `incomplete-analysis`, #538), `sql_tables`, `calls` (one row per target; dynamic `candidates` from `DynamicCallAnalyzer`; CICS LINK/XCTL `PROGRAM`), `cics_commands` / `exec_dli_commands` counts, `unreachable_procedures` (`DeadCodeAnalyzer`'s, via `_reachability()`; the flow graph's only if it raises), `perform_cycles`, `health`, `lint` (whole file: summary + `BRIEF_LINT` worst) | `ProgramFlowAnalyzer`, `DeadCodeAnalyzer`, `ProgramSignatureExtractor`, `CRUDMatrixGenerator`, `ProgramLayoutIndex.file_facts`, `TechnicalDebtAnalyzer`, `LintAnalyzer`; each section through `_attempt()`, so one analyzer raising costs only its section (`analyzer-failed`) |
| `callers_of(file, name, program, limit)` | per matching paragraph/section: `callers` (`from`, `type`, location, `thru`, `via_range`, `perform_type`, `condition`, `loop`), `callers_by_type`, `reachable`, `is_entry_point`. `file=None`, or a name that is no procedure of `file`: `_program_callers()` (`kind: program`, `scope: workspace`): `callers` (`program`, `via`, location, `from` (the paragraph), `dynamic`/`target_from`), `calling_programs`, `declared_in`, `unresolved_dynamic_calls`, a `note` when it is external or called by nobody. `units_named()` skips FACTORY / OBJECT / METHOD units, which no CALL can reach (#500). Nested programs are scoped (#532): a `_calls` row carries `nested` (a static CALL COBOL scope sends to a program nested in the caller's compilation unit) or `nested_candidates`; a caller reaching one is marked `nested`; when every declaration is nested, the other CALLs go to `out_of_scope_callers`; `contained` / `depth` are the source nesting (a stacked unit is outermost), and `duplicate-declaration` counts outermost declarations only. ENTRY names count (#521): `UnitFacts.entries`; a CALL to one of the program's ENTRY names is a caller (with `entry`), and `units_named()` falls back to the units declaring an ENTRY of that name (`declared_in` then names the `program`) | flow edges in `_CONTROL_EDGES`; a THRU is two edges (opener + `*_THRU` closer), so only openers count and `range_members` gives `via_range`. `reachable` is `DeadCodeAnalyzer`'s (memoized `_reachability()`), not `flow.unreachable_nodes`, which misses the paragraph after a PERFORMed one; a `FALL_THROUGH` edge is a caller only when it is in `DeadCodeReport.fall_through_edges` or leaves the first entry point (#486). Program level: the `programs` index's per-unit `_calls` rows: a static target, or a dynamic one whose traced `candidates` include the name; an incomplete dynamic row is listed, not counted |
| `impact_of_change(name, file, program, depth, limit)` | member mode (a member suffix, or `file=None` and a name in `graph.members`): `copied_by` (program, file, `copy_sites`), `copied_through_other_members` (chains), `fields`, `resolved_to`. Otherwise field mode, as `where_from` but forward | `CopybookImpactAnalyzer` over the `programs` index's `CodebaseGraph`, COPY lines from `graph.copy_sites`; field mode `LineageGraph.impact` |
| `where_from(field, file, program, depth, limit, full_paths)` | `programs`, `tables`, `datasets`, `by_confidence`, `trail_ends` (`_trail_ends()`: hits no other path passes through), `may_be_overwritten` (count), `hits` sorted exact first, then those without `may_be_overwritten` (`ImpactHit.overwritten` rendered `FIELD by STATEMENT at file:line`), then by path length, each path shortened by `_share_paths()` to what it adds to the earlier hit it continues (`from_hit`, `after_step`) unless `full_paths`; impact_of_change field mode the same (each: `program`, `field`, `node_kind`, `derived`, `confidence`, `file`, `location` of the statement that reaches it, `path` as one string per step `NODE (STATEMENT at file:line)`) | `LineageGraph.impact(..., "backward")` over the `lineage` index; `file` limits the start to that file's units (`program` to one). A declared field with no value flow is `found: true` with no hits and the graph's `notes`; `found: false` only for a name matching no item, and its `suggestions` never hold the name asked for (#546). A bare name matching several fields of one program gets an `ambiguous-name` caveat (from `ImpactResult.ambiguous`, #540) and every match is traced |
| `codebase_overview(limit)` | `index`, `programs` (grade, score, `calls`, `called_by` -- both 0 on a FACTORY / OBJECT / METHOD row, whose CALLs count on its class, and such a name never hides an external callee from `not_in_workspace`, #500 -- `contained`, `unit_kind`), `call_graph` (`entry_programs`, `most_called`, `not_in_workspace`, `in_workspace_not_analyzed` (a callee whose name `Workspace.other_sources()` finds: a non-COBOL source by stem, or an assembler `CSECT` / `START` label / `ENTRY` name; suffixes in `OTHER_SOURCE_LANGUAGES`), `cycles`, `unresolved_dynamic_calls`); `index.other_sources_not_analyzed` counts them by language; program-level `callers_of` of such a name gives `sources_not_analyzed` and a note instead of "external", `copybooks` (`most_used`, `not_found`), `health` (`grades`, `worst`), `duplicated_code` (groups, members capped) | `programs` + `health` indexes; top lists are `OVERVIEW_TOP` (10) long, `limit` only lowers them |
| `record_layout(file, record, program, limit)` | `records[]`: `qualified_name` (`X OF Y`), `section`, `declared_at`, offset/length, `redefines`, `fields` in source order each with `declared_at`; an FD name gives every record of the file (`file`); a level-66 RENAMES name gives its range (`level` 66, `renames`: the record, the record's `fields` inside the range; `_renames_records`, #563; one it cannot place is `found: false` with an `incomplete-analysis` caveat) | `compute_record_layout` per 01 plus `flag_record_layout` (SYNC slack -> `offset_ambiguous` + an `incomplete-analysis` caveat, #488; a partial level-88 line gets a caveat whose effect leaves offsets exact; `explain_symbol` carries the same caveat for its item's record); `_declarations()` matches the n-th layout entry of a qualified name to its n-th declaration (FILLER repeats) and re-sorts, since the layout emits a group after its members |
| `explain_symbol(file, name, program, limit)` | each declaration matching `name` (or `X OF Y` / `X IN Y`, partial chains allowed, resolved by `XrefReport.entries_named`, #541): `declared_at`, `layout` (PICTURE, USAGE, `byte_offset`, `byte_length`, REDEFINES, level-88 values; a level-66 RENAMES item gets the byte range `data-items` places it at, or an `incomplete-analysis` caveat when it cannot be placed, #485, #563; a SPECIAL-NAMES name is found with its xref kind, `mnemonic-name` / `class-name` / ..., declared at the CONFIGURATION SECTION, #519), `references` with role/statement/paragraph, `references_by_role`; `suggestions` when not found | `XrefAnalyzer`, `compute_program_data_items`; not found: `special_register` from xref's `is_special_register()` (no suggestions then) |

| `business_rules(file, program, kind, procedure, include_technical, limit)` | `summary` (whole program: per-kind counts, `technical_rules_excluded`, `rules_in_dead_code`), `rule_count` (after the filters), `rules` (`_rule()`: `rule_id`, kind, statement, procedure/section, `location`, `condition` or `formula` -- a calculation's condition is its formula and is dropped --, `branches` with `actions` (`text`, `location`, nested `rule_id`), `guards`, `reached_via`, `inputs`, `outputs`, `classification`; empty fields left out), `condition_names` (only those the shown rules test), a `note` when technical rules were left out, `suggestions` for a `procedure` matching nothing | `BusinessRuleExtractor`, memoized as `rules` / `rules+technical`; its heuristics caveat passed on as `incomplete-analysis` |
| `diff_programs(old_file, new_file, old_program, new_program, category, rename_threshold, limit)` | `old` / `new` (`program_info`), `summary` (whole diff: `by_category`, `by_kind`), `changes` (`_change()`: kind, category, symbol, detail, `old` / `new` values, `old_location` cited through the old parse, `new_location` through the new one; `None` keys dropped), a `note` when nothing changed | `ProgramDiffer` on the two selected units; its caveats as `incomplete-analysis` |
| `decode_record(copybook, data_file, record, view, skip, max_records, fields, charset, endian, record_format, record_separator, record_length, limit)` | `record_name`, `record_length`, `framing_length`, `view`, `views` (name, redefines, offset, length), `fields` (name, offset, length, picture, usage: once, not per record); with a data file `records` (`index`, `file_offset`, `length`, `values` name -> value, `absent`, `errors`), `record_count`, `more_records`, `error_count`, `next` (the `skip` of the next page) | `RecordDecoder.from_copybook_source` (the copybook read with `Workspace.read_text`, COPYs expanded from the config's copybook dirs; each unexpanded member an `unresolved-copybook` caveat), `decode_bytes` on at most `MAX_DECODE_BYTES` (16 MiB) of the file -- a cut file reports no trailing bytes. Encoding: argument, else `config.data`, else built-in (`_encoding_options`). Default page `DEFAULT_DECODE_RECORDS` (10) |
| `gen_fixtures(file, program, mode, seed, rows, scenario, limit)` | `program_id`, `mode`, `seed`, `bundle_version`, `rows_per_sequence`, `coverage`, `scenario_count`, `scenarios` (`_scenario()`: name, intent, entry, `fixtures` (`boundary` `CATEGORY:KEY`, paragraph, `location`, direction, provenance, `columns`, `rows` as lists aligned to `columns`, terminal, status, unresolved), `expectations`, `unconstrained`, `verification` (`status` + `reasons`, as the CLI prints them)), `arm_coverage` for branches/all (counts + `missed_arms` with reason and `location` from the arm key's `@line`), `replay` | the workspace parse, not `analyze_from_file` (which re-parses with strict copybooks): `ProgramLayoutIndex.build(unit)`, `ProgramFixtureGenerator._resolve_callees` over `Workspace.callee_directories()` (`callee_path` under the root only; the rest a caveat), `BoundaryInventoryAnalyzer`, `generate_with_scenarios`. Seed: argument, else `config.seed`, else 0 (idempotent; the CLI's default is random). `rows` default `DEFAULT_FIXTURE_ROWS` (3), max 100. `bundle.unresolved` folded into one caveat |
| `jcl_job(file, job, step, limit)` | `file`, `jobs` (name, `location`, `parameters`, job-level `dds`, `step_count`, `steps`: `_step_row()` -- name, `location`, `program`, `runs` (a launcher's `effective_programs()`), `from_procedure` / `invokes_procedure`, `parm`, `condition`, `dds`: `_dd_row()` -- `ddname`, `kind` (dataset/temporary/sysout/dummy/instream/unnamed), `dataset`, `disposition`, `access` (`_access()`: SHR read, OLD exclusive, NEW or omitted create, MOD extend), `sysout_class`, RECFM/LRECL, `unapplied_override`, `instream_line_count` + first `MAX_INSTREAM_LINES` (20) `instream_lines`, `concatenated`), `program_sources` (PGM -> COBOL file by stem: a load module is named after its source member), `procedures` (`in-stream`, a member path, `jcl-parser template` (an IBM-supplied procedure found nowhere under the root, #744), or `expanded: false`), `symbols`, `errors` (cited) | `JclParser(library=members)`, *members* from `Libraries.for_text()`, a PROCLIB concatenation (first member of a name wins): the file's `JCLLIB ORDER=` libraries (`_jcllib_names()`, a parenthesized list may run over several cards; a directory under the root named exactly so, `by_name`; one with none -> `JclFile.missing_libraries` -> `incomplete-analysis`), then `configured` (`Workspace.proc_directories()` + any directory whose name contains `PROCLIB`; members with `LIBRARY_SUFFIXES`: none, `.prc`, `.proc`, `.jcl`, `.cntl`; a `.jcl` file there is not a job), then `discovered` (directories holding `.prc` / `.proc`; only those suffixes, so a same-named `.cbl` never shadows one); answer `procedure_libraries` = `JclFile.libraries`, the directories searched; skipped proc_path entries -> caveat (`_carry_libraries`); `errors` -> `partial-parse`, `unresolved` -> `incomplete-analysis`. A file in the `jcl` index is reused; another suffix is parsed on the spot. `_Locator`: a step expanded from a cataloged member is cited in the member; its DD in the job file only when that line really is `//PROCSTEP.DD ` (the two share line numbers); an unnamed concatenation member after such an override in the job file only when that line is an unnamed `// DD` card and the dataset name does not settle it for the member (`flattened()`); lines read with `split_source_lines` |
| `jobs_running(program, limit)` | `program`, `jcl_files`, `step_count`, `steps` (`file`, `job` + `_step_row()`; with the source: DD rows carry `cobol_files`, and `dds_not_coded` lists non-OPTIONAL, non-SD SELECTs whose DD the step lacks), `source` (`program_info`), `files` (`_selects()`: `file_name`, `ddname` via `normalize_ddname`, `optional`, `assign_using` (DD unknown), `sort_work_file`, `declared_at`), a `note` when no step runs it | steps matched by `PGM=` or `effective_programs()` across the `jcl` index; source by file stem, else `_declaring_file()` (a `PROGRAM-ID.` text scan, never a parse: a utility such as SORT costs no parse of the root); a source that does not parse is an `analyzer-failed` caveat, the steps still answered; matched with `JclParseResult.steps_running()`; SELECTs of the unit only (`_contained_node_ids`), SD from `_file_facts` |
| `dataset_users(dataset, limit)` | `dataset`, `use_count`, `by_access` (access -> programs, `JOB.STEP` for a DD with no program), `jobs`, `uses` (dataset as coded, file, job, step, `programs`, ddname, disposition, `access` (`_step_access()`: a COBOL program's OPEN mode for the DD through `_ProgramUses` (SELECT -> DD, `CRUDMatrixGenerator` open modes; INPUT read, OUTPUT write, I-O update, EXTEND extend, `_combine()` with DISP: create when NEW, extend when MOD), else a utility's DD roles (`_utility_uses()`: SORT SORTIN/SORTOUT/OUTFIL FNAMES, IEBGENER SYSUT1/SYSUT2, ICETOOL FROM/TO, IDCAMS REPRO INFILE/OUTFILE or INDATASET/OUTDATASET), else DISP), `access_from` (program / utility / disp), `disposition_access` when not disp, `location`, `temporary`), `temporary_note`, a `note` when none | `_cards()`: `all_dd_statements()`'s order (job-level DDs included, step `None`) with each concatenation member placed by `_Locator.flattened()`; `_matcher()`: base name (member / GDG generation stripped) unless the pattern has `(`; `_filter_regex()`: z/OS filter wildcards, `%` one character, `*` within a qualifier, `**` any number of qualifiers |

| `read_procedure(file, name, program)` | `name`, `kind`, `line_count`, `segments` (`file`, `start_line`, `lines`: consecutive lines of one file, a COPY member's its own), `section` / `paragraphs` | `ProcedureIndex` over the unit's PROCEDURE DIVISION; the range ends before the next header at its level (`_procedure_end()`); the last procedure runs from its last statement to the next Area A line or `END PROGRAM` (at most `_TAIL_LINES`); each expanded line through `locate()`, text from the file on disk; `MAX_PROCEDURE_LINES` (300) |
| `find_statements(verb, operand, role, literal, paragraph, file, program, limit)` | `scope` (file / workspace), `filters`, `match_count`, `by_verb`, `file_count`, `by_file` (top `BY_FILE_SHOWN`), `statements` (`location`, `program`, `verb`, `paragraph`, `section`, `text` (the on-disk line, fixed-format areas cut, `MAX_TEXT`), `operand_roles`), `suggestions` when nothing matched | `statement_rows()`: `_own_statements()` of every unit, `statement_verb()` (`EXEC CICS X` / `EXEC DLI X` / `EXEC SQL X` / `statement_type`), operands from `XrefAnalyzer` references keyed by (line, statement class); without `file` the `statements` index (`Workspace.index`, rebuilt like the others); a verb matches by word prefix; `literal` only on the first line (a caveat says so) |
| `slice(file, field, direction, program, limit, aliases)` | `matched`, `statement_count`, `by_role`, `fields` (other fields of the slice), `ports`, `paragraphs` (`paragraph`, `statements`: `location`, `verb`, `role` data / control / decision / controlled, `text`, `flows` `SRC -> DST` or `tests F`), `aliases_not_followed`; `found: false` + `suggestions` | the unit's memoized `lineage` report in a one-report `LineageGraph`: starts from `_start_groups()`, a BFS over `_in` / `_out` with the alias-class rule, stopping at ports; an inexact alias edge (`overlay_class` and not exact) is skipped unless `aliases`. Rows keyed by parsed line (`_EdgeInfo.seq_line`), located with `ParsedProgram.locate()`; `control` rows are the `CobolStatement` ancestors of each data row's innermost statement (`_statements_by_line`, `_enclosing`); forward, `decision` rows are xref `condition` references to a slice field (qualified from `XrefEntry.ancestors`, a level-88 counting for its item) and `controlled` their `_statements_under()`; capped at `MAX_SLICE_STATEMENTS` (200) or `limit` |
| `check_claims(claims)` | `summary` (verdict -> count), `results` (`claim` echoed, `verdict` confirmed / contradicted / not_checkable, `why`, `evidence` up to 10 locations), `legend` naming every kind | each kind answered from what the other tools use: `calls` the `programs` index's `UnitFacts.calls` (a dynamic row without `candidates_complete` makes a miss `not_checkable`); `copies` its `copy_sites`; `performs` / `reachable` / `unreachable` `callers_of(file, name)`'s procedure (FALL_THROUGH is no transfer); `writes_field` / `sets_only_in` `find_statements(operand, role="write", file)`; `flows_to` `impact_of_change` field mode (a hit, dataset or table matching O; a `may_be_overwritten` hit is contradicted when every overwrite is a MOVE, else not_checkable; an inexact one not_checkable); `reads_dataset` / `writes_dataset` `dataset_users` rows of steps running S (`access` in write/create/extend/update or read/update; only `access_from: disp` -> not_checkable). A `ToolError` (missing field, unknown program or procedure) is `not_checkable` with its text; claims past `MAX_CLAIMS` are cut with `truncated` |

Invariants:

- A reference location carries **no column**: xref's column is the
  statement's, not the operand's, and would mislead.
- `byte_offset` 0 is reported (`_worth_showing`): `0 in (None, [], False)` is
  True in Python.
- xref's notes about undeclared names are passed on only when the answer is
  about an undeclared or unknown name (`_UNDECLARED_CAVEATS`); elsewhere they
  are tokens a model pays for and cannot use.
- Lint keeps errors when the list is cut: ordering is severity, then source.
- Enumerated arguments are case-insensitive: `lint`'s `rules` and
  `min_severity` like `business_rules`' `kind`, `diff_programs`' `category`
  and `gen_fixtures`' `mode`.
- `where_from` / `impact_of_change` with `program` and no `file` limit the
  start to that PROGRAM-ID wherever it is declared (an unknown one is a
  `ToolError` with close names); before, `program` was dropped and every
  program answered.
- A name `explain_symbol`, `record_layout` or `callers_of` cannot find in the
  selected unit, but another unit of the same file declares, gets
  `declared_in_program_units` and a `hint` to pass `program=`
  (`_declared_elsewhere`): the default unit is the outermost, so a name only
  a nested program declares otherwise reads as missing.

Tool selection (`server.py`): `TOOL_GROUPS` (`core`, `data`, `jcl`) and
`select_tools(spec, workspace)`; `--tools auto` (the CLI default) is `core`
plus `jcl` when `Workspace.has_jcl()`; `build_server(workspace)` defaults to
`all`. `instructions_for(enabled)` sends one guide paragraph per offered
group and names the tools left out. `compact_schema()` strips pydantic's
`title`s and the `anyOf [T, null]` / `default: null` of optional arguments
from each advertised input schema (arguments are still validated against
the signature), and the docstrings and `Field` descriptions are one line:
together about 43% fewer schema characters for `all` than before.

## Prompts

`prompts.py`: one function per prompt, returning the request text (a
user message); `PromptSpec.description` is the function's docstring. Each
names the tools to call in order and ends with the shared `_METHOD`
paragraph (cite `file:line`, read the caveats, narrow a truncated list).
The prompt *names and arguments* are surface (interface-contract.md); the
text is not. A test checks every prompt names real `CobolTools` methods.

## Envelope

`Workspace.read_text` decodes a program as the CLI does
(`read_program_source`, #522): a cp1252 / Latin-1 program is parsed, not
refused, and a lossy decode is an `incomplete-analysis` caveat on every
answer about it.

Every tool returns `{"surface_version", "answer", "caveats", "truncated",
"program"?, "next"?}` (`Response.build`). Two passes in `server.py`'s
`off_loop`, not in `CobolTools` (a Python caller gets neither): `hints.add_hints()`
adds `next`, at most `MAX_HINTS` (2) `tool(arg="v")` strings derived from the
answer alone, naming only offered tools, and never failing the call; then
`envelope.fit_budget(result, max_answer_bytes)` (`--max-answer-bytes`,
`DEFAULT_ANSWER_BYTES` 24000, compact-JSON bytes) halves the answer's
largest list from the end until it fits, each cut a `truncated` entry with
`reason: "answer budget"` (an earlier `limit` cut keeps its `total`). A location anywhere in `answer` is
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
- **Bare copybooks.** `_parse()` wraps a source with no division header
  (`wrap_copybook_fragment`, the gen-data skeleton) so `record_layout` on a
  `.cpy` finds its records, and `_unwrap_source_map()` maps the wrapped lines
  back to the file's own (skeleton lines map to nothing) -- through the
  expansion source map when copybook dirs are set (#536). Only a file that is
  not a program file by suffix is wrapped (a `.cbl` with no division header
  stays a failed program, not a `COPYBOOK-LAYOUT` one in the codebase
  indexes), and every answer on a wrapped file carries an
  `incomplete-analysis` caveat: the skeleton's PROGRAM-ID, procedures and
  "every field unused" are not facts about a program.
- **Config.** `_root_config_file(root)`: `cobol.yml`/`cobol.yaml` in the
  root itself, never the CLI's walk-up (`find_config_file`) -- a parent's
  file does not count. Unless the CLI was given
  `--config`/`--no-config` (`args._config_explicit`), which passes the
  config in and fixes it. Otherwise `refresh_config()` (run by `config` and
  `resolve()`) re-checks the root's `cobol.yml` and compares its `(mtime_ns, size)`; a
  change reloads it, recomputes the guard's directories and clears the
  cache. A `ConfigError` becomes a `ToolError` and is retried next call.
  Copybook paths, source format, `debug_lines` and `define` come from it (`define: [X=]` is
  the empty value, as the CLI reads `--define X=`); no
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
  `off_loop` sets `Workspace.progress` for that one call; `FactsStore._compute()`
  in `facts.py` reports `(done, total, "reading FILE")` per file, sent
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

`codebase_index.py`, over `facts.py`. Every index is assembled from the
per-file `FileFacts` of `Workspace.program_files()` (`cobol.yml`
`extensions`, default `.cbl`/`.cob`/`.cobol`; hidden directories and
copybook directories inside the root skipped), given by
`facts.surveyed()` -> `store_for(workspace).facts()`. `compute_facts()`
parses a file once with `cached_or_parse()` (a current cached parse is
reused, a fresh one never enters the LRU) and takes from that parse what
every index needs: `UnitFacts` (`_unit_facts`), its `GraphPart`
(`CodebaseGraphBuilder.absorb()`; the index joins them with `assemble()`),
`LineageFacts` per unit, health rows and redundancy fingerprints, and
`StatementRow`s. `FileFacts.stamps` are the parse's stamps (the file, its
expanded copybooks, the copybook directories), so after an edit only the
stale files are recomputed; the index's own `tree_stamps()` still notice an
added or removed program.

`FactsStore` (`Workspace.facts_store`; `store_for` makes an in-process,
memory-only one when the CLI set none): with `workers > 1` and at least
`PARALLEL_THRESHOLD` (12) stale files, a `spawn` `ProcessPoolExecutor`
whose initializer (`_init_worker`) dup2s stderr over stdout and builds its
own `Workspace` from the vetted config; a worker that dies costs its file
(`failed`), not the index. With `cache_dir` the facts are pickled to
`facts-<sha of root>.pickle` (atomic replace) under a key of
`FACTS_VERSION`, the package version, the Python version and the config;
another key starts afresh, an unreadable file is no cache. The CLI default
is `default_cache_dir()`, never under the root, so a checkout cannot plant
a pickle. `warm()` (started by `run_stdio` unless `--no-warm-up`) computes
every stale file in a thread: pooled, outside `Workspace.lock`, with
`_busy` cleared so `facts()` waits rather than recomputing; in-process, one
file at a time under `Workspace.lock` then `FactsStore.lock` (the order a
tool call takes them), so calls interleave. Measured on an 80-program root
(4 CPUs): every index from cold 9.5 s in one process, 2.8 s with 4
workers, 0.1 s after a restart from disk; before, each index parsed the
root itself (4-5 s each). Every index records
`failed` (file -> reason) and `file_caveats`; tools fold them into a few
aggregated caveats (`_carry_index_caveats`, `_notes`: `NOTES_SHOWN` named,
then a count), with the root cut from library notes (`_relative`).

| Index | Built on first | Keeps |
|---|---|---|
| `programs` | program-level `callers_of`, `impact_of_change`, `codebase_overview` | `UnitFacts` per unit (id, file, depth, `unit_kind`, `graph_id` (the graph's id, `OUTER/INNER` for a nested unit), `entries`, `_calls` rows with on-disk sites); the `CodebaseGraph` from `CodebaseGraphBuilder.assemble()` over the files' `GraphPart`s (no second parse); `copy_sites` |
| `lineage` | field-mode `impact_of_change`, `where_from` | every unit's `FieldFlowAnalyzer` report (after `apply_source_map`) in one `LineageGraph`; JCL under the root (`.jcl`/`.job`, less the members of `configured` procedure libraries) through `load_jobs(jcl, proc_path=...)` when jcl-parser imports (PROCs from `Workspace.proc_directories()`, then `jcl_tools.procedure_libraries()`'s `configured`, the JCLLIB-named directories (`jcllib_directories`) and `discovered`: the libraries the JCL tools read, every file in them stamped; proc_path folders outside are skipped with a problem; with none at all, an unexpanded PROC adds a hint naming `.prc` / PROCLIB / `project.proc_path`; the steps `bindings_from_jobs` could not read become the graph's `join_caveats`), else `jcl_note`; `edge_files` |
| `health` | `codebase_overview` | grade/score per unit (`TechnicalDebtAnalyzer` sharing the memoized flow and redundancy reports); `cross_file_clone_groups` over a hand-built `ScanReport` (fingerprints stamped with `origin` and, as `scan` does, `body_origin`, #470), members placed on disk |

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
- The JCL tools need the `[jcl]` extra (`jcl-parser`, also in `[dev]`) at
  call time, not at import: the server always lists them, and without
  `jclparser` each raises `ToolError(INSTALL_HINT)` (`require_jcl()`), so a
  client learns the install command instead of reading "no JCL".
- Tests: `tests/unit/mcp_server/` (`test_mcp_tools.py`,
  `test_mcp_v3_tools.py` (business rules, diff, decode, fixtures, prompts),
  `test_mcp_jcl_tools.py` (the JCL tools over `tests/samples/lineage/` +
  `tests/samples/jcl/` and a cataloged procedure member; skipped without
  `jclparser`)
  and `test_mcp_codebase.py`, the cross-program tools over copies of
  `tests/samples/enterprise/` and `tests/samples/lineage/`, need no SDK;
  `test_mcp_server.py` drives an in-memory client session and the CLI). The
  directory is not named `mcp`: a test package of that name shadows the SDK.

## See also

- [cli.md](cli.md) -- the `mcp` subcommand row, `cobol.yml`
- [analysis/lint.md](analysis/lint.md) -- `LintAnalyzer`, source-map origins
- [analysis/data-use.md](analysis/data-use.md) -- `XrefAnalyzer`
- [integration.md](integration.md) -- the other external surfaces
