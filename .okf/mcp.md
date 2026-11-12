---
type: Module
title: MCP Server
description: cobolparser/mcp/ and `cobol-parser mcp` -- an MCP server (stdio) that lets AI agents question COBOL source; tools as plain functions (the tools/ package, one CobolTools mixin per area, plus the JCL tools), the task prompts (prompts.py), the response envelope and caveat kinds (envelope.py), the workspace guard, cobol.yml and parse cache (workspace.py), the root-wide cross-program indexes (codebase_index.py), and the one SDK-importing module (server.py).
tags: [mcp, ai, agents, tools, stdio, caveats, source-map]
timestamp: 2026-10-28T00:00:00Z
---

# MCP Server

<!-- okf:external add_tool FastMCP Prompt from_function -->

`cobol-parser mcp --root DIR` serves COBOL analysis tools to AI agents over
the Model Context Protocol, on stdin/stdout. Design and later phases:
`docs/plans/2026-10-15-mcp-server-design.md`; user guide:
`docs/mcp-server.md`. Start with `CobolTools` in `cobolparser/mcp/tools/__init__.py`.

| Module | Holds | Imports the SDK |
|---|---|---|
| `cobolparser/mcp/envelope.py` | `Response` (caveats + truncation), `Caveat`, `CAVEAT_KINDS`, `ToolError`, `MCP_SURFACE_VERSION`, limits | no |
| `cobolparser/mcp/workspace.py` | `Workspace` (path guard, `cobol.yml`, LRU parse cache), `ParsedProgram` (unit selection, `locate()`), `stdout_to_stderr()` | no |
| `cobolparser/mcp/tools/__init__.py` | `CobolTools`: one mixin per area below (each extends `BaseTools`), plus `read_procedure` / `find_statements` / `slice` / `check_claims` and `jcl_job` / `jobs_running` / `dataset_users` delegating to their modules | no |
| `cobolparser/mcp/tools/common.py` | `BaseTools` (`workspace`, `_relative()`, `_other_language_path()`) and the helpers several tools share: `_attempt()`, `_notes()`, `_listed()`, `_carry_parse_caveats()`, `_carry_index_caveats()`, `_coverage()`, `_declared_elsewhere()`, `_reachability()`, `_flow()`, `_file_facts()`, `_worth_showing()` (a unit's own statements: `cobolparser.models.walk.own_statements`) | no |
| `cobolparser/mcp/tools/structure.py` | `StructureTools`: `read_source` (`MAX_SOURCE_LINES`, `_source_lines()`), `explain_symbol`, `record_layout`; the data-item walk (`_walk_data_items()`) and layout helpers (`_layout_index()`, `_layout_for()`, `_renames_records()`) | no |
| `cobolparser/mcp/tools/brief.py` | `BriefTools`: `program_brief` (`BRIEF_*` caps, `_calls()`, `compare_sources()`, `_unreachable_reasons()`) | no |
| `cobolparser/mcp/tools/callers.py` | `CallersTools`: `callers_of`, program-level `_program_callers()` | no |
| `cobolparser/mcp/tools/impact.py` | `ImpactTools`: `impact_of_change` (member mode `_copybook_impact()`), `where_from` (`_lineage()`, `_hit()`, `_trail_ends()`) | no |
| `cobolparser/mcp/tools/overview.py` | `OverviewTools`: `codebase_overview` (`OVERVIEW_TOP`, `OVERVIEW_CLONE_MEMBERS`) | no |
| `cobolparser/mcp/tools/analysis.py` | `AnalysisTools`: `lint` (`_run_lint()`, also `program_brief`'s), `business_rules`, `diff_programs` | no |
| `cobolparser/mcp/tools/data.py` | `DataTools`: `decode_record` (`DEFAULT_DECODE_RECORDS`, `MAX_DECODE_BYTES`), `gen_fixtures` (`DEFAULT_FIXTURE_ROWS`, `MAX_FIXTURE_ROWS`) | no |
| `cobolparser/mcp/tools/jcl_index.py` | the `jcl` index (`jcl_index`, `JclIndex`, `JclFile`, `Libraries`), `jcl_available()` / `require_jcl()`, `INSTALL_HINT`, `_Locator` (job file vs procedure member), and which steps run a program (`run_by()`, `programs_run_by_jcl()`, `step_dds()`, `program_dds()`); reads JCL through `cobolparser.jcl`, so the `[jcl]` extra | no |
| `cobolparser/mcp/tools/jcl_common.py` | what the JCL tools share: `_dd_row()`, `_step_row()`, `explain_condition()`, `run_order()`, the index caveats (`_carry_index()`), control members, utility dataset uses (`_utility_uses()`, `_idcams_named()`), `_ProgramUses` | no |
| `cobolparser/mcp/tools/jcl_job.py` | `jcl_job`; SORT control cards over record layouts (`_Layouts`, `_sort_layout()`) | no |
| `cobolparser/mcp/tools/jcl_programs.py` | `jobs_running` (`_job_flow()`, `_follow_calls()`) | no |
| `cobolparser/mcp/tools/jcl_datasets.py` | `dataset_users` (DB2 utility SQL, `_sql_programs()`, `_jobs_by_effect()`) | no |
| `cobolparser/mcp/languages.py` | PL/I and assembler sources read through the sibling parsers (`[pl1]` / `[hlasm]` extras): `LANGUAGE_SUFFIXES`, `SourceFacts`, `read_facts()`, the `languages` index (`languages_index`, `LanguagesIndex`, `source_files`), `facts_for()`, `parser_available()`, `install_hint()`, `LIMITS` | no |
| `cobolparser/mcp/claims.py` | `check_claims()`, `CLAIM_KINDS`, `MAX_CLAIMS` (25), one checker per kind (`_CHECKERS`) | no |
| `cobolparser/mcp/sort_layout.py` | DFSORT control statements over a byte map: `parse_sort_control()` (`SortControl`: SORT / MERGE keys incl. `FORMAT=`, INCLUDE / OMIT tests, INREC / OUTREC `FIELDS=` / `BUILD=` as `Segment`s; an edit mask, a `p` with no length, OVERLAY / IFTHEN -> `not_mapped`; INCLUDE / OMIT tests are read quote-aware (`_tests()`), a field-to-field comparison (`p1,m1,f1,EQ,p2,m2,f2`) kept as a `(p2, m2)` value, an unreadable condition -> `not_mapped`; OUTFIL parameters (`_outfil()`) -> `not_mapped` and `outfil_reformat`, so `read_back()` gives `not mapped` rows for a reformatted output, #795), `map_sort()` (`sort_keys`, `record_tests`, `inrec_layout` / `outrec_layout` with lengths, `input_not_copied`; keys read through INREC, tests not: INCLUDE runs first), `read_back()`, `fields_at()` | no |
| `cobolparser/mcp/slicing.py` | `slice_field()` (the `slice` tool), `MAX_SLICE_STATEMENTS` | no |
| `cobolparser/mcp/navigation.py` | `read_procedure()`, `find_statements()`, `statement_rows()` / `StatementRow`, the `statements` index (`statements_index()`), `statement_verb()` | no |
| `cobolparser/mcp/hints.py` | `add_hints()`: the `next` calls per tool, `MAX_HINTS` | no |
| `cobolparser/mcp/prompts.py` | `PROMPTS` (`PromptSpec`): `explain_program`, `review_program`, `plan_change`, `document_business_rules`, `onboard_codebase`, each a plain function returning the request text | no |
| `cobolparser/mcp/codebase_index.py` | `programs_index` / `lineage_index` / `health_index`: assembled from per-file facts, cached by `Workspace.index()` | no |
| `cobolparser/mcp/facts.py` | `FileFacts` (one parse's facts for every index), `compute_facts()`, `FactsStore` (current facts kept, stale ones recomputed in a spawn pool, pickled to `cache_dir` with `HEAVY_FIELDS` in per-file shards, `warm()`, `load_extra()` / `save_extra()`), `store_for()`, `surveyed()`, `default_cache_dir()` | no |
| `cobolparser/mcp/tool_groups.py` | `TOOL_GROUPS`, `ALL_TOOLS`: kept apart from `server.py` so `mcp --help` can list the tools without the `[mcp]` extra | no |
| `cobolparser/mcp/server.py` | `build_server()`, `run_stdio()`: typed wrappers registered on `FastMCP` (each wrapped by `_on_the_wire()`, see the envelope), `PROMPTS` through `Prompt.from_function`; `serverInfo.version` is the package's `__version__` (FastMCP takes none and the low-level server would report the SDK's) | **yes** (`[mcp]` extra) |

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
| `program_brief(file, program, limit)` | `size` (own statements only: `get_all_statements()` walks into contained units), `entry_points`, `interface` (entry points, parameters, `call_example`) and `interface_notes`, `files` (C/R/U/D string, open modes, organization, records, key, status field; EXEC CICS file-control files included, a data-item `FILE(...)` reported as `incomplete-analysis`, #538), `sql_tables`, `calls` (one row per target; dynamic `candidates` from `DynamicCallAnalyzer`, trailing blanks stripped by `_call_targets()` so a padded `MOVE 'ACCTVAL ' TO WS-PGM` matches `ACCTVAL` (#754); CICS LINK/XCTL `PROGRAM`; `via: "FUNCTION"` for each user-defined function the REPOSITORY declares and a `FUNCTION name(...)` invokes, so program-level `callers_of` of a FUNCTION-ID lists its invokers; `FACTS_VERSION` 5, 7 since the lineage reports gained `picture` / `usage` / `redefines` and `overlays`, 8 since candidates are stripped), `cics_commands` / `exec_dli_commands` counts, `unreachable_procedures` (`DeadCodeAnalyzer`'s, via `_reachability()`; the flow graph's only if it raises), `unreachable_reasons` (`_unreachable_reasons()`, one `{procedure, reason, location}` row each: what names it (nothing, or only unreachable code, with the `GOTO from X at file:line`; FALL_THROUGH and `*_THRU` edges do not count) and why control does not fall in from the procedure before it (unreachable too, reached only as a PERFORM ... THRU end, ends with its exit statement at file:line, only PERFORMed)), `perform_cycles`, `health`, `lint` (whole file: summary + `BRIEF_LINT` worst), `call_tree` with `follow_calls` (`_brief_call_tree()`: `codebase_index.call_chain()` rows, at most `BRIEF_CALL_TREE` (25), each COBOL one with its own `files` / `sql_tables` (C/R/U/D, `_program_uses()`) and `cics_commands`; a callee with several COBOL sources (`also_in`) gets `implementations` (`_implementations()`, at most `BRIEF_IMPLEMENTATIONS` (4): each source's files, `sql_tables`, `dds` (`jcl_tools.program_dds()`: SELECT DDs not OPTIONAL, not SD, not ASSIGN USING) and `dds_coded_by` (`jcl_tools.step_dds()`: the steps running the brief's program whose DDs include every one, with `datasets`)) and an `implementation_note` naming the version those steps are set up to run, or saying none is; also for a PL/I or assembler brief), `runs_as` (`_brief_runs_as()`: `{runs_as, because}` from `RunsAs`, absent when nothing says), `control_flow_notes` (`_control_flow_notes()`: no node with `has_stop_run` / `has_goback` / `has_exit_program` / `has_cics_exit` / `has_abend_call` -> falls off the end of the last procedure; more than one paragraph, no PERFORM or GO TO anywhere and nothing ends before the last -> the fall-through chain; `_file_open_close_notes()`: FD files (`FileFacts.record_type == "FD"`, not a SORT/MERGE USING or GIVING file) never OPENed, or OPENed with no CLOSE naming them), `also_declared_in` (`_brief_also_declared()`: other `programs` index nodes with the same PROGRAM-ID, at most `BRIEF_ALSO_DECLARED` (5), each `compare_sources()`: difflib over `split_source_lines`, `identical` / `comments_only` (column 7 `*` or `/`) / `differing_lines` (first `_DIFF_LINES_SHOWN`) / `differing_line_count` / `comparison`), `link_edit` / `link_edited_into` (`link_decks.own_decks()` / `bound_into()`: `.lnk` / `.lked` / `.lkd` / `.lkedit` / `.link` / `.bind` files under the root, `parse_decks()` splits a deck at each NAME into one `LinkDeck` per load module (a deck with none takes the file stem; continuation cards joined, #794), `parse_deck()` (the first) reads INCLUDE `DD(MEMBER,...)` or bare members, NAME (else the file stem) and ENTRY; a `link-decks` workspace index), `run_by` (outermost unit only: the JCL steps that run the PROGRAM-ID or the file stem, `{job, step, file, location}`, at most `BRIEF_RUN_BY` (10); `jcl_tools.run_by()`, left out without the `[jcl]` extra or JCL; an other-language brief carries it too, and its "no callers" note only when neither is found) | `ProgramFlowAnalyzer`, `DeadCodeAnalyzer`, `ProgramSignatureExtractor`, `CRUDMatrixGenerator`, `ProgramLayoutIndex.file_facts`, `TechnicalDebtAnalyzer`, `LintAnalyzer`; each section through `_attempt()`, so one analyzer raising costs only its section (`analyzer-failed`) |
| `callers_of(file, name, program, limit)` | per matching paragraph/section: `callers` (`from`, `type`, location, `thru`, `via_range`, `perform_type`, `condition`, `loop`; a `FALL_THROUGH` out of a THRU range end also gets `note` and `entered_by_goto`, the GO TO edges onto that end, `_note_range_end_run_on()`), `callers_by_type`, `reachable`, `is_entry_point`. `file=None`, or a name that is no procedure of `file`: `_program_callers()` (`kind: program`, `scope: workspace`): `callers` (`program`, `via`, location, `copied_at` (`_copied_at()`: for a site in a copybook, the program's COPY line from `index.copy_sites`), `from` (the paragraph), `dynamic`/`target_from`), `call_type` per caller row (`_call_type()`: a COBOL CALL literal is static unless compiled with DYNAM, a CALL identifier dynamic, EXEC CICS LINK / XCTL dynamic, a PL/I CALL to an ENTRY declared `OPTIONS(FETCHABLE)` (`languages._fetchable_entries()`, a text scan of `DCL name ... ENTRY ... FETCHABLE`; a parenthesized name list is not read) dynamic, other PL/I EXTERNAL ENTRY static; none for assembler), `runs_as` per caller row and `runs_as_because` per program (`_label_runs_as()` over `codebase_index.RunsAs`: `online (CICS)` when the unit issues EXEC CICS (copybooks included) or its LINKAGE SECTION declares DFHCOMMAREA, `batch` when a JCL step runs it (`jcl_tools.programs_run_by_jcl()`), `IMS` for DL/I calls, else what its callers are one hop up (`a subroutine; its callers run ...`), else absent; `UnitFacts.services` / `commarea` from `unit_services()` / `unit_commarea()`, a PL/I or assembler source's `services` kinds), `calling_programs`, `declared_in`, `coverage` (`_coverage()`: `files_read` by language, `files_not_analyzed`, `files_failed`), `sources_not_analyzed` (also when the name is declared), `unresolved_dynamic_calls` scoped by `_unresolved_near()` to sites in the top folder of a declaration or caller or in a file whose text names the program (the rest counted in `unresolved_dynamic_calls_elsewhere` `{count, folders}`), `link_edited_into` (`link_decks.bound_into()`: decks of another load module that INCLUDE it; the "called by nobody" `note` then says it is bound into those instead), a `note` when it is external or called by nobody. `units_named()` skips FACTORY / OBJECT / METHOD units, which no CALL can reach (#500). Nested programs are scoped (#532): a `_calls` row carries `nested` (a static CALL COBOL scope sends to a program nested in the caller's compilation unit) or `nested_candidates`; a caller reaching one is marked `nested`; when every declaration is nested, the other CALLs go to `out_of_scope_callers`; `contained` / `depth` are the source nesting (a stacked unit is outermost), and `duplicate-declaration` counts outermost declarations only. ENTRY names count (#521): `UnitFacts.entries`; a CALL to one of the program's ENTRY names is a caller (with `entry`), and `units_named()` falls back to the units declaring an ENTRY of that name (`declared_in` then names the `program`) | flow edges in `_CONTROL_EDGES`; a THRU is two edges (opener + `*_THRU` closer), so only openers count and `range_members` gives `via_range`. `reachable` is `DeadCodeAnalyzer`'s (memoized `_reachability()`), not `flow.unreachable_nodes`, which misses the paragraph after a PERFORMed one; a `FALL_THROUGH` edge is a caller only when it is in `DeadCodeReport.fall_through_edges` or leaves the first entry point (#486). Program level: the `programs` index's per-unit `_calls` rows: a static target, or a dynamic one whose traced `candidates` include the name; an incomplete dynamic row is listed, not counted |
| `impact_of_change(name, file, program, depth, limit)` | member mode (a member suffix, or `file=None` and a name in `graph.members`): `copied_by` (program, file, `copy_sites`, each with `statement`: `COPY`, `EXEC SQL INCLUDE` (`_include_statement()`: the site line and the two after it, SQL before INCLUDE), `++INCLUDE` or `-INC`), `commented_out` + `commented_out_note` (`_commented_out()`: programs in the copying programs' folders whose only COPY / INCLUDE of the member is on a comment line, column-7 `*` / `/` or after `*>`, `{file, line, text}`), `not_affected` (`_unaffected_neighbours()`: `count`, `programs` (at most `_NEIGHBOURS_SHOWN` (25) PROGRAM-IDs), `folders`, `note`: programs in the folders of the copying files that copy it neither directly nor through another member; absent when there are none), `brought_in_by` (`_statement_counts()`: programs per statement kind, only when there are two kinds), `copied_through_other_members` (chains), `fields`, `resolved_to`, `coverage`; `member_files_to_change` (`_other_language_members()`: `resolved_to` plus the other languages' `member_files`, with a `note`; only when COBOL copies the member and another language includes its own file); `included_by_other_languages` rows carry `member_files` (`languages.member_files()`: the PL/I / assembler include files of that member name, by `MEMBER_SUFFIXES`). Otherwise field mode, as `where_from` but forward | `CopybookImpactAnalyzer` over the `programs` index's `CodebaseGraph`, COPY lines from `graph.copy_sites`; field mode `LineageGraph.impact` |
| `where_from(field, file, program, depth, limit, full_paths)` | `programs`, `tables`, `datasets`, `by_confidence`, `trail_ends` (`_trail_ends()`: hits no other path passes through), `may_be_overwritten` (count), `hits` sorted exact first, then those without `may_be_overwritten` (`ImpactHit.overwritten` rendered `FIELD by STATEMENT at file:line`), then by path length, each path shortened by `_share_paths()` to what it adds to the earlier hit it continues (`from_hit`, `after_step`) unless `full_paths`; impact_of_change field mode the same (each: `program`, `field`, `node_kind`, `derived`, `confidence`, `file`, `location` of the statement that reaches it, `path` as one string per step `NODE (STATEMENT at file:line)`) | `LineageGraph.impact(..., "backward")` over the `lineage` index; `file` limits the start to that file's units (`program` to one). A declared field with no value flow is `found: true` with no hits and the graph's `notes`; `found: false` only for a name matching no item, and its `suggestions` never hold the name asked for (#546). A bare name matching several fields of one program gets an `ambiguous-name` caveat (from `ImpactResult.ambiguous`, #540) and every match is traced |
| `codebase_overview(limit, language, path)` | `index`, `programs` (a filter scopes every section, `scope` says so: call-graph lists, edge count and cycles over the matched programs, copybook use counted among them, health and index caveats over their files, clone groups with a member among them and only those members; clone `members` at most `OVERVIEW_CLONE_MEMBERS` (3) with one `duplicated_code.groups[].members` truncation entry; filtered by `language` (`_language_named()`: COBOL / PL/I / assembler and aliases such as `asm`, `pli`; another name is a `ToolError`) and `path` (`_path_matches()`: a folder prefix or an `fnmatch` glob), with `programs_filter` and `programs_matched`; grade, score, `calls`, `called_by` -- both 0 on a FACTORY / OBJECT / METHOD row, whose CALLs count on its class, and such a name never hides an external callee from `not_in_workspace`, #500 -- `contained`, `unit_kind`), `call_graph` (`entry_programs`, `most_called`, `not_in_workspace`, `in_workspace_not_analyzed` (a callee whose name `Workspace.other_sources()` finds: a non-COBOL source by stem, or an assembler `CSECT` / `START` label / `ENTRY` name; suffixes in `OTHER_SOURCE_LANGUAGES`), `cycles`, `unresolved_dynamic_calls`); `index.other_sources_not_analyzed` counts them by language; program-level `callers_of` of such a name gives `sources_not_analyzed` and a note instead of "external", `copybooks` (`most_used`, `not_found`), `health` (`grades`, `worst`), `duplicated_code` (groups, members capped) | `programs` + `health` indexes; top lists are `OVERVIEW_TOP` (10) long, `limit` only lowers them |
| `record_layout(file, record, program, limit)` | `records[]`: `qualified_name` (`X OF Y`), `section`, `declared_at`, offset/length, `redefines`, `fields` in source order each with `declared_at`; an FD name gives every record of the file (`file`); a level-66 RENAMES name gives its range (`level` 66, `renames`: the record, the record's `fields` inside the range; `_renames_records`, #563; one it cannot place is `found: false` with an `incomplete-analysis` caveat) | `compute_record_layout` per 01 plus `flag_record_layout` (SYNC slack -> `offset_ambiguous` + an `incomplete-analysis` caveat, #488; a partial level-88 line gets a caveat whose effect leaves offsets exact; `explain_symbol` carries the same caveat for its item's record); `_declarations()` matches the n-th layout entry of a qualified name to its n-th declaration (FILLER repeats) and re-sorts, since the layout emits a group after its members |
| `explain_symbol(file, name, program, limit)` | each declaration matching `name` (or `X OF Y` / `X IN Y`, partial chains allowed, resolved by `XrefReport.entries_named`, #541): `declared_at`, `layout` (PICTURE, USAGE, `byte_offset`, `byte_length`, REDEFINES, level-88 values; a level-66 RENAMES item gets the byte range `data-items` places it at, or an `incomplete-analysis` caveat when it cannot be placed, #485, #563; a SPECIAL-NAMES name is found with its xref kind, `mnemonic-name` / `class-name` / ..., declared at the CONFIGURATION SECTION, #519), `references` with role/statement/paragraph, `references_by_role`; `suggestions` when not found | `XrefAnalyzer`, `compute_program_data_items`; not found: `special_register` from xref's `is_special_register()` (no suggestions then) |

| `business_rules(file, program, kind, procedure, include_technical, limit)` | `summary` (whole program: per-kind counts, `technical_rules_excluded`, `rules_in_dead_code`), `rule_count` (after the filters), `rules` (`_rule()`: `rule_id`, kind, statement, procedure/section, `location`, `condition` or `formula` -- a calculation's condition is its formula and is dropped --, `branches` with `actions` (`text`, `location`, nested `rule_id`), `guards`, `reached_via`, `inputs`, `outputs`, `classification`; empty fields left out), `condition_names` (only those the shown rules test), a `note` when technical rules were left out, `suggestions` for a `procedure` matching nothing | `BusinessRuleExtractor`, memoized as `rules` / `rules+technical`; its heuristics caveat passed on as `incomplete-analysis` |
| `diff_programs(old_file, new_file, old_program, new_program, category, rename_threshold, limit)` | `old` / `new` (`program_info`), `summary` (whole diff: `by_category`, `by_kind`), `changes` (`_change()`: kind, category, symbol, detail, `old` / `new` values, `old_location` cited through the old parse, `new_location` through the new one; `None` keys dropped), a `note` when nothing changed | `ProgramDiffer` on the two selected units; its caveats as `incomplete-analysis` |
| `decode_record(copybook, data_file, record, view, skip, max_records, fields, charset, endian, record_format, record_separator, record_length, limit)` | `record_name`, `record_length`, `framing_length` (the stride the file is cut at: a whole program's FD LRECL when longer than the record), `view`, `views` (name, redefines, offset, length), `fields` (name, offset, length, picture, usage: once, not per record); with a data file `records` (`index`, `file_offset`, `length`, `values` name -> value, `absent`, `errors`), `record_count`, `more_records`, `error_count`, `next` (the `skip` of the next page) | `RecordDecoder.from_copybook_source` (the copybook read with `Workspace.read_text`, COPYs expanded from the config's copybook dirs; each unexpanded member an `unresolved-copybook` caveat), `decode_bytes` on at most `MAX_DECODE_BYTES` (16 MiB) of the file -- a cut file reports no trailing bytes. Fixed format with no separator: the read starts at `skip * (record_length or framing_length)` (indexes and offsets shifted back); any other framing reads from byte 0, and a page the window cut short (`window_spent`) gets a caveat and no `next`, so following `next` cannot loop. Encoding: argument, else `config.data`, else built-in (`_encoding_options`). Default page `DEFAULT_DECODE_RECORDS` (10) |
| `gen_fixtures(file, program, mode, seed, rows, scenario, limit)` | `program_id`, `mode`, `seed`, `bundle_version`, `rows_per_sequence`, `coverage`, `scenario_count`, `scenarios` (`_scenario()`: name, intent, entry, `fixtures` (`boundary` `CATEGORY:KEY`, paragraph, `location`, direction, provenance, `columns`, `rows` as lists aligned to `columns`, terminal, status, unresolved), `expectations`, `unconstrained`, `verification` (`status` + `reasons`, as the CLI prints them)), `arm_coverage` for branches/all (counts + `missed_arms` with reason and `location` from the arm key's `@line`), `replay` | the workspace parse, not `analyze_from_file` (which re-parses with strict copybooks): `ProgramLayoutIndex.build(unit)`, `ProgramFixtureGenerator._resolve_callees` over `Workspace.callee_directories()` (`callee_path` under the root only; the rest a caveat), each file found vetted by `accept=` -> `Workspace.under_root()` (a link out of the root is not read; a caveat names it), `BoundaryInventoryAnalyzer`, `generate_with_scenarios`. Seed: argument, else `config.seed`, else 0 (idempotent; the CLI's default is random). `rows` default `DEFAULT_FIXTURE_ROWS` (3), max 100. `bundle.unresolved` folded into one caveat |
| `jcl_job(file, job, step, limit)` | `file`, `jobs` (name, `location`, `parameters`, job-level `dds`, `step_count`, `steps`: `_step_row()` -- name, `location`, `program`, `runs` (a launcher's `effective_programs()`), `from_procedure` / `invokes_procedure`, `parm`, `condition`, `dds`: `_dd_row()` -- `ddname`, `kind` (dataset/temporary/sysout/dummy/instream/unnamed), `dataset`, `disposition`, `access` (`_access()`: SHR read, OLD exclusive, NEW or omitted create, MOD extend; a utility's own DD role first, `access_from: utility`, via `_utility_uses()`, which also reads IEFBR14: a normal disposition of DELETE is `delete`), `sysout_class`, RECFM/LRECL, `unapplied_override`, `instream_line_count` + first `MAX_INSTREAM_LINES` (20) `instream_lines`, `concatenated`), `run_order` (`run_order()`: `STEP (PROGRAM, when it runs)` joined by `->`, the `explain_condition()` words after "so it"), and for a SORT step `sort_layout` (`_sort_layout()`: the SYSIN cards (`_sysin_lines()`, in-stream or member), the SORTIN dataset's layout from `_Layouts` (every DD naming its base name in a non-utility step, the step's programs and their COBOL callees two levels deep (`call_chain`), the SELECT for that DD, candidate records = the FD records, `READ ... INTO` targets, `WRITE` / `REWRITE ... FROM` sources, the one with most elementary items through `record_layout`, at most `SORT_LAYOUT_PROGRAMS` (6) program DDs), `map_sort()`, then `output_read_as` (`_sort_output_layout()`: the SORTOUT dataset, or what a later IDCAMS REPRO of the same job writes from it, read back through its layout, at most `SORT_READ_BACK_FIELDS` (40)); with no reader, `input` + a `note`), `program_sources` (PGM -> COBOL file by stem: a load module is named after its source member), `procedures` (`in-stream`, a member path, `jcl-parser template` (an IBM-supplied procedure found nowhere under the root, #744), or `expanded: false`), `symbols`, `errors` (cited) | `JclParser(library=members)`, *members* from `Libraries.for_text()`, a PROCLIB concatenation (first member of a name wins): the file's `JCLLIB ORDER=` libraries (`_jcllib_names()`, a parenthesized list may run over several cards; a `//*` comment card and in-stream data (`_job_cards()`: after `DD *` up to `/*` or the next `//` card, after `DD DATA` or a `DLM=` up to its delimiter, e.g. a job submitted through INTRDR; a `//*` card is never the DD that starts it) are not read, #749; a directory under the root named exactly so, `by_name`; one with none -> `JclFile.missing_libraries` -> `incomplete-analysis`), then `configured` (`Workspace.proc_directories()` + any directory whose name contains `PROCLIB`; members with `LIBRARY_SUFFIXES`: none, `.prc`, `.proc`, `.jcl`, `.cntl`; a `.jcl` file there is not a job), then `discovered` (directories holding `.prc` / `.proc`; only those suffixes, so a same-named `.cbl` never shadows one); answer `procedure_libraries` = `JclFile.libraries`, the directories searched; skipped proc_path entries -> caveat (`_carry_libraries`); `errors` -> `partial-parse`, `unresolved` -> `incomplete-analysis`. A file in the `jcl` index is reused; another suffix is parsed on the spot. `_Locator`: a step expanded from a cataloged member is cited in the member; its DD in the job file only when that line really is `//PROCSTEP.DD ` (the two share line numbers); an unnamed concatenation member after such an override in the job file only when that line is an unnamed `// DD` card and the dataset name does not settle it for the member (`flattened()`); lines read with `split_source_lines` |
| `jobs_running(program, limit, follow_calls)` | `program`, `jcl_files`, `step_count`, `steps` (`file`, `job` + `_step_row()`; with the source: DD rows carry `cobol_files`, and `dds_not_coded` lists non-OPTIONAL, non-SD SELECTs whose DD the step lacks), `source` (`program_info`), `files` (`_selects()`: `file_name`, `ddname` via `normalize_ddname`, `optional`, `assign_using` (DD unknown), `sort_work_file`, `declared_at`), `sources` + a `duplicate-declaration` caveat when several sources (any language) declare the name (`_also_named()`), `jobs` (`_job_flow()`, the first `JOB_FLOWS_SHOWN` (5) jobs, each with `step_count` and `run_order()`, `JOB_FLOW_STEPS` (40) steps each: `step`, `program` / `runs`, `from_procedure` / `invokes_procedure`, `condition`, `condition_means` (`explain_condition()`: COND=(code,op[,step]) and EVEN / ONLY in words, also on `_step_row()`), `runs_the_program`, `reads` / `writes` as `DD=DATASET` by `_step_access()` (and IDCAMS SYSIN commands as `DELETE DSN (delete)`) (STEPLIB-like DDs, SYSOUT, DUMMY and NULLFILE left out), `fed_by` (dataset -> the earlier step that wrote its base name), `control` (in-stream lines, at most `FLOW_CONTROL_LINES` (12), or a SYSIN / SYMNAMES member `LIB(MEMBER)` found under the root by `_ControlMembers` (stem, `CONTROL_SUFFIXES`, nearest folder first) with `_control_lines()`); for a utility, `_NoProgramUses`, so no program is parsed), with `follow_calls` `calls` (`codebase_index.call_chain()`: breadth first to `CALL_CHAIN_DEPTH` (6) over static targets and dynamic candidates, each program once with `also_called_by`; rows `program`, `called_by`, `via`, `depth`, `at` (first call site), `dynamic`, `language`, `file`, `also_in`, `analyzed: false` / `in_workspace: false`; notes for untraced dynamic calls and the depth limit) and `languages_run`, a `note` when no step runs it. JCL gap caveats (`_carry_index()`) are spelled out only for files in the answer or whose text (or a procedure it names) mentions the program (`_mentions()`); the rest are one counting caveat; `dataset_users` scopes them the same way by the dataset's base name | steps matched by `PGM=` or `effective_programs()` across the `jcl` index; source by file stem, else `_declaring_file()` (a `PROGRAM-ID.` text scan, never a parse: a utility such as SORT costs no parse of the root); a source that does not parse is an `analyzer-failed` caveat, the steps still answered; matched with `JclParseResult.steps_running()`; SELECTs of the unit only (`_contained_node_ids`), SD from `_file_facts` |
| `dataset_users(dataset, limit)` | `dataset`, `use_count`, `by_access` (access -> programs, `JOB.STEP` for a DD with no program), `jobs`, `jobs_by_effect` (`_jobs_by_effect()`: `change_it` {count, jobs: job -> every use in card order, `STEP: access` or the IDCAMS command, `by` its programs, `from` / `to` a utility's other datasets}, any access but read; `only_read_it` {count, jobs}), `uses` (dataset as coded, file, job, step, `programs`, ddname, disposition, `access` (`_step_access()`: a COBOL program's OPEN mode for the DD through `_ProgramUses` (SELECT -> DD, `CRUDMatrixGenerator` open modes; INPUT read, OUTPUT write, I-O update, EXTEND extend, `_combine()` with DISP: create when NEW, extend when MOD), else a utility's DD roles (`_utility_uses()`: SORT SORTIN/SORTOUT/OUTFIL FNAMES, IEBGENER SYSUT1/SYSUT2, ICETOOL FROM/TO, IDCAMS REPRO INFILE/OUTFILE or INDATASET/OUTDATASET), else DISP), plus one row per IDCAMS command in an in-stream SYSIN that names the dataset itself (`_idcams_named()`: DELETE, DEFINE ... NAME, RELATE, REPRO/BLDINDEX/PRINT INDATASET, OUTDATASET; `ddname: null`, `command`, `access` delete / define / read / write), `access_from` (program / utility / idcams command / disp), `disposition_access` when not disp, `copied_from` / `copied_to` on a utility's write / read (`_utility_datasets()`: the DDs and REPRO INDATASET / OUTDATASET it reads or writes), `access_because` when from the program (`_ProgramUses.because()`: each program's OPEN of the file behind the DD, mode and on-disk line via `_open_lines()` and `ParsedProgram.locate()`, plus, for DISP=SHR / OLD, that DISP says nothing about reading or writing), `location`, `temporary`), plus one row per DB2 table a DSNTEP2 / DSNTEP4 / DSNTIAD / DSNTIAUL step's SQL names (`_db2_utility_uses()`: the program direct or as TSO `RUN PROGRAM(...)` in SYSTSIN, `_control_dd()` in-stream or the member under the root, `_sql_statements()` split on `;` with literals blanked and `--` comments cut, `_sql_tables()` the changed table (`_SQL_CHANGES`) and FROM / JOIN reads; DSNTIAUL without `PARMS('SQL')` unloads each SYSIN table whole, an unload's SYSRECnn dataset in `copied_to`; `access_from: db2 sql`, `command`, `runs_as`, `sql`, `sql_from`, `sql_location`; matched qualified or by the last qualifier), `sql_programs` (`_sql_programs()`: `statements` index EXEC SQL rows naming the table, `change_it` / `only_read_it` {count, programs: program -> `VERB [cursor C] in PARA at file:line`}), `temporary_note`, a `note` when none | `_cards()`: `all_dd_statements()`'s order (job-level DDs included, step `None`) with each concatenation member placed by `_Locator.flattened()`; `_matcher()`: base name (member / GDG generation stripped) unless the pattern has `(`; `_filter_regex()`: z/OS filter wildcards, `%` one character, `*` within a qualifier, `**` any number of qualifiers |

| `read_procedure(file, name, program)` | `name`, `kind`, `line_count`, `segments` (`file`, `start_line`, `lines`: consecutive lines of one file, a COPY member's its own), `section` / `paragraphs` | `ProcedureIndex` over the unit's PROCEDURE DIVISION; the range ends before the next header at its level (`_procedure_end()`); the last procedure runs from its last statement to the next Area A line or `END PROGRAM` (at most `_TAIL_LINES`); each expanded line through `locate()`, text from the file on disk; `MAX_PROCEDURE_LINES` (300) |
| `find_statements(verb, operand, role, literal, paragraph, file, program, limit)` | `scope` (file / workspace), `filters`, `match_count`, `by_verb`, `file_count`, `by_file` (top `BY_FILE_SHOWN`), `statements` (`location`, `program`, `verb`, `paragraph`, `section`, `text` (the on-disk line, fixed-format areas cut, `MAX_TEXT`), `operand_roles`), `other_forms` (`_other_forms()`: for verb `EXEC DLI`, the CALL rows naming a `_DLI_MODULES` literal, and the reverse for a CALL search that matched one: `form`, `statement_count`, `programs`, `note`), `also_check` when an operand search matched EXEC SQL (DB2 utility steps: `dataset_users`), with `operand` `programs_by_role` (`_programs_by_role()`: `changed_by` {count, programs: program -> `VERB at file:line`} for any role but read / condition, `only_read_by` {count, programs}, from every match before the `limit` cut), `suggestions` when nothing matched | `statement_rows()`: `own_statements()` of every unit, `statement_verb()` (`EXEC CICS X` / `EXEC DLI X` / `EXEC SQL X` / `statement_type`), operands from `XrefAnalyzer` references keyed by (line, statement class), plus an EXEC SQL statement's tables (`_sql_table_roles()`: qualified and bare, role `insert` / `update` / `delete` / `merge` for a data change's target, `read` otherwise, an OPEN / FETCH reading its cursor's tables via `_cursor_tables()`; a row whose line is only `EXEC SQL` shows the SQL text; `FACTS_VERSION` 9); without `file` the `statements` index (`Workspace.index`, rebuilt like the others); a verb matches by word prefix; `literal` only on the first line (a caveat says so) |
| `slice(file, field, direction, program, limit, aliases)` | `matched`, `statement_count`, `by_role`, `fields` (other fields of the slice), `ports`, `paragraphs` (`paragraph`, `statements`: `location`, `verb`, `role` data / control / decision / controlled, `text`, `flows` `SRC -> DST` or `tests F`), `aliases_not_followed`; `found: false` + `suggestions` | the unit's memoized `lineage` report in a one-report `LineageGraph`: starts from `_start_groups()`, a BFS over `_in` / `_out` with the alias-class rule, stopping at ports; an inexact alias edge (`overlay_class` and not exact) is skipped unless `aliases`. Rows keyed by parsed line (`_EdgeInfo.seq_line`), located with `ParsedProgram.locate()`; `control` rows are the `CobolStatement` ancestors of each data row's innermost statement (`_statements_by_line`, `_enclosing`); forward, `decision` rows are xref `condition` references to a slice field (qualified from `XrefEntry.ancestors`, a level-88 counting for its item) and `controlled` their `_statements_under()`; capped at `MAX_SLICE_STATEMENTS` (200) or `limit`. #796: the traversal is a pending-names loop (`follow_graph`) over an `_XrefIndex` (xref writes / tests keyed by qualified name, `written_on` / `tested_on` by line): a field with no lineage edge is still `found` when it is a lineage item (`matched`); backward, a literal / figurative / `SET` write of a slice field is a `data` row (`sets X`) and every field a `control` row tests joins the slice; forward, the writes of `controlled` statements are followed; a field with no flows gets a `note` |
| `check_claims(claims)` | `summary` (verdict -> count), `results` (`claim` echoed, `verdict` confirmed / contradicted / not_checkable, `why`, `evidence` up to 10 locations), `legend` naming every kind | each kind answered from what the other tools use: `calls` the `programs` index's `UnitFacts.calls` (a dynamic row without `candidates_complete` makes a miss `not_checkable`); `copies` its `copy_sites`; `performs` / `reachable` / `unreachable` `callers_of(file, name)`'s procedure (FALL_THROUGH is no transfer); `writes_field` / `sets_only_in` `find_statements(operand, role="write", file)` for O and for every item sharing its bytes (`_storage_aliases`, from the `data-items` layout: an ancestor group, a REDEFINES / RENAMES item or another 01 record of the same FD / SD covering O is a sure write, cited `through` it; `_record_io_writes` adds a `READ` / `RETURN` of the file whose record area holds O as a possible write and `WRITE` / `REWRITE` / `RELEASE` record `FROM` x as a write of that record, #788; a partial overlap, a table element, a duplicated name or `INITIALIZE ... REPLACING` makes the claim not_checkable; when O cannot be placed a `sets_only_in` that would be confirmed is not_checkable, #778); `flows_to` `impact_of_change` field mode (a hit, dataset or table whose whole name is O -- a field's own or qualified name or a path step's, a dataset equal to O or its GDG base, a table or its unqualified name; never a substring, #776; a `may_be_overwritten` hit is contradicted when every overwrite is a MOVE, else not_checkable; an inexact one not_checkable); `reads_dataset` / `writes_dataset` `dataset_users` rows of steps running S (`access` in write/create/extend/update or read/update; only `access_from: disp` -> not_checkable). A `ToolError` (missing field, unknown program or procedure) is `not_checkable` with its text; claims past `MAX_CLAIMS` are cut with `truncated` |

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

Tool selection (`server.py`, groups in `tool_groups.py`): `TOOL_GROUPS` (`core`, `data`, `jcl`) and
`select_tools(spec, workspace)`; `--tools auto` (the CLI default) is `core`
plus `jcl` when `Workspace.has_jcl()`; `build_server(workspace)` defaults to
`all`. `instructions_for(enabled)` sends `INSTRUCTIONS` (incl. the
"search so that nothing is missed" checklist: start with a tool, trace every
branch, every form of a service, repeat what the tools flag, JOB card and
file, counts that match) plus one guide paragraph per offered group and
names the tools left out. `compact_schema()` strips pydantic's
`title`s and the `anyOf [T, null]` / `default: null` of optional arguments
from each advertised input schema (arguments are still validated against
the signature), and the docstrings and `Field` descriptions are one line:
together about 43% fewer schema characters for `all` than before.

### PL/I and assembler

`languages.py` reads every `.pli` / `.pl1` (through `pl1_parser`, the
`[pl1]` extra) and `.asm` / `.s` / `.hlasm` / `.alc` / `.mlc` / `.assemble` / `.asmpgm` (through `hlasmparser`,
the `[hlasm]` extra; `.mac` stays a source not analyzed) file under the root
that `cobol.yml` does not count as COBOL, into a `SourceFacts`: `program_id`
(PL/I `program_name` / the first CSECT, else the stem), `entries` (stem,
PL/I `ENTRY` and the main procedure's `entry_names`, assembler CSECTs and
`_assembler_names()`), `sections`, `calls` in the `_calls` row shape
(PL/I: one row per `(target, CALL|FETCH)`, an aliased call's
`external_name` half skipped so the row is the real program with
`local_name`; an entry variable or dynamic call is `dynamic` with no
candidates; assembler: `subprogram_call` deps by `command`, an `EPLOC=`
one `dynamic` with the `DC` value as complete `candidates`, `EXEC CICS
LINK` / `XCTL` from `PROGRAM(...)` in `raw_operands`), `includes`,
`services` (assembler CICS / SQL / MQ / IMS). The `languages` index
(`Workspace.index`, tree stamps plus each file's) re-reads only files whose
stamp changed; a language whose parser does not import is listed in
`not_installed`, never read. It is not part of `FactsStore`: the parses are
cheap, but the index itself is saved with `FactsStore.save_extra("languages")`
and reloaded on a restart, so only changed files are re-read.
`MEMBER_SUFFIXES` name a language's include files (PL/I `.inc` / `.incl` /
`.plinc` / `.pli` / `.pl1`, assembler `.mac` / `.maclib` / `.asm` /
`.asmcopy`; never `.cpy`, a COBOL copybook); `member_files()` finds them.

`_absorb_other_languages()` (end of `_build_programs`) adds each analyzed
source as a `UnitFacts` (`language`), its includes to `copy_sites` (with
`language`), and rewrites the graph's `call_edges`: an edge to a foreign
unit's entry name goes to the unit (`entry` set, like #521), and each
foreign row becomes edges (`cics-link` / `cics-xctl` by `via`, else
`call`). So `codebase_overview` (`language`, `program_units_by_language`,
`_other_language_caveats()`: one caveat per missing parser with its install
command, one per read language with `LIMITS`), program-level `callers_of`,
`check_claims` `calls` (the callee's entry names count) / `copies`, and the
JCL tools (`_other_language_source()`: `jobs_running`'s `source`,
`jcl_job`'s `program_sources`, looked up once per program name per call) all see them. `program_brief` and
`callers_of` on such a file dispatch through `_other_language_path()`
(`_other_language_brief()`); every other file tool hits
`Workspace._refuse_other_language()`, a `ToolError` naming the tools that
read it. `Workspace.other_sources()` leaves out suffixes whose parser
imports. `impact_of_change` treats a name in `copy_sites` as a member and
lists `included_by_other_languages`.

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
`DEFAULT_ANSWER_BYTES` 24000) halves the answer's
largest list from the end until it fits, each cut a `truncated` entry with
`reason: "answer budget"` (an earlier `limit` cut keeps its `total`); once
every list is down to one item, the answer's longest strings (over 200
characters) are halved, each cut with `shown_chars` / `total_chars`. The
size is `envelope.wire_size()`: the `structuredContent` plus the text copy
sent beside it, JSON-escaped. `_on_the_wire()` makes each tool return a
`CallToolResult` whose text copy is `wire_text()` (compact JSON): left to
FastMCP it was pretty-printed, and an answer cut to 24000 compact bytes
went out at about three times that. Still over once every list is at one
item and every long string halved, `_trim_envelope` cuts the envelope (sweep
O5: `codebase_overview` asked for 2 KB answered 4.4 KB, most of it caveats
and the cut records): `next` goes, `caveats` are halved (never below one; a
`caveats` entry in `truncated`), the `answer budget` entries fold into one
(`field` the comma-joined cut fields, `fields` their count), and, only when
emptying them all would fit (`_fits_without_lists`), the answer's one-item
lists are emptied largest first. Scalars and short strings are never cut, so
a budget below them still cannot be met. A location anywhere in `answer` is
`{"file", "line", "column"?}` in the file on disk, root-relative when it can
be; `null` with an `unmapped-location` caveat when the source map has no
entry. `caveats[].kind` is closed: <!-- okf:gen mcp-caveat-kinds -->`unresolved-copybook`, `partial-parse`, `analyzer-failed`, `incomplete-analysis`, `ambiguous-name`, `duplicate-declaration`, `unmapped-location`, `program-unit-selected`<!-- /okf:gen -->.
A new kind or a changed shape bumps `MCP_SURFACE_VERSION`. A request that
cannot be answered at all (path outside the workspace, unknown program unit,
bad severity) raises `ToolError`, which the SDK returns as an error result.

## Workspace

- **Shared analysis facts.** `ParsedProgram.context(unit)` keeps one
  [`ProgramContext`](analysis.md#calling-conventions) per unit per parse;
  `.xref(unit)` / `.flow(unit)` read it under `stdout_to_stderr()`. Tools use
  these instead of constructing `XrefAnalyzer` / `ProgramFlowAnalyzer`
  (`common._flow`, `navigation.statement_rows`, `explain_symbol`, the slice's
  `_XrefIndex`, `program_brief`'s debt and the codebase index's health).
  `ParsedProgram.report(name, unit, build)` still memoizes the other reports.
- **Guard.** `Workspace.resolve()` resolves symlinks, then `_within()`
  accepts anything under the root and, under a kept copybook directory
  outside the root (`_outside`), only a *member* (`_member_of`): suffix in
  `COPYBOOK_MEMBER_SUFFIXES` (lower-cased `CopybookSearchPath().extensions`:
  `.cpy`, `.cbl`, `.cob`, `.copy`, `.dcl`, `""`) and no dot-named component below the
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
  (`cobolparser.layout.copybook.wrap_copybook_fragment`, the gen-data skeleton) so `record_layout` on a
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
  `project.abend_programs` too: `Workspace.site_settings()` wraps
  `using_site_abend_programs()` (thread-local, so the warm-up thread and a
  tool call cannot cut each other's list) around every public tool method
  (`BaseTools.__init_subclass__` wraps them), every `compute_facts()` and
  each warm-up index build; the facts key includes the list (#900).
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
  through `anyio.from_thread.run(ctx.report_progress, ..., token=...)` at
  most once a `PROGRESS_INTERVAL`. The token is taken on the event loop in
  `off_loop`: a call waiting on the warm-up thread's pooled build is
  reported from that thread, which anyio did not start; the warm-up build
  reports too (it used to compute with reporting off, so no progress was
  ever sent while the first call waited on it). A listener that raises is dropped, never fails the
  build.
- **Members read badly.** `_parse()` maps every lexer / parser problem's
  line (`_member_diagnostics()`: `ParseError.line_number`, or "line N" in a
  warning) through the source map; each COPY member one lands in gets an
  `incomplete-analysis` caveat ("copybook X was read with N lexer or parser
  problem(s)", most often a member read in the wrong source format), and
  `ParsedProgram.degraded_names` holds the data names its text declares
  (`names_declared_in()`, read in both formats). `lint` withholds the
  undefined-name findings about those names (`_without_degraded_undefined()`,
  with a caveat); `record_layout` (not found) and `explain_symbol`
  (undeclared) add `declared_in_degraded_copybook` and a `hint`
  (`_degraded_declaration()`). `decode_record` compares the decoded
  record's fields with the PICTURE entries of that record in the member's
  text (`_missing_fields_caveat()`). The `partial-parse` caveat and the
  "not expanded" warnings cite each line as `file:line` on disk
  (`_describe_error()`, `_cite_expanded_lines()`), not as a line of the
  expanded text past the end of the program.
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
`StatementRow`s. `FileFacts.stamps` are the parse's stamps (the file, every
copybook the expander opened -- the source map's files plus
`ParseResult.expansion_copybooks`, so a member that only COPYs another is
stamped too, #763 -- and the copybook directories), so after an edit only the
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
another key starts afresh, an unreadable file is no cache. `HEAVY_FIELDS`
(`lineage`, `lineage_problems`, `statements`, ~90% of the bytes) are kept
out of that core pickle (`FileFacts.heavy` false there) in one shard per
file under `facts-<sha>.pickle.d/` (`_shard_file()`, written for
`_heavy_dirty` paths), loaded only by `facts(heavy=True)` /
`surveyed(heavy=True)` -- the `lineage` and `statements` builds; a shard
that is missing or stale recomputes that file (`FACTS_VERSION` 8). So a
restart loads the core in about a second and pays for lineage only on the
first `where_from`. `load_extra(name)` / `save_extra(name, value)` keep
other pickles under the same key (the `languages` index uses it).
`server.warm_indexes()` (from `run_stdio`) runs `warm()`, then builds
the `programs` index and, with the `[jcl]` extra, the `jcl` index, each
under `Workspace.lock`, in a background thread, so the first
cross-program call does not pay for them. The CLI default
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
- `[pl1]` (`landparty-pl1-parser>=2.0.0`) and `[hlasm]` (`hlasm-parser>=0.2.2`)
  are read only by `languages.py`, imported per language on first use; not
  in `[dev]` until they are on PyPI, so CI skips
  `test_mcp_languages.py` (`importorskip`). mypy ignores their imports.
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
