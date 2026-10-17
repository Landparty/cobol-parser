---
type: Log
title: OKF Update Log
description: Dated log of OKF bundle updates, newest first.
tags: [log, changelog, history]
timestamp: 2026-10-16T00:00:00Z
---

# OKF Update Log

Newest first. A follow-up entry may sit directly under the entry it
follows up on even when a day or two out of order -- that adjacency is
deliberate. Anything else appended to the bottom is a mistake: five
entries, including both 2026-09-15 sections, were found there on
2026-09-15 and moved back up.

## 2026-10-17 -- Lineage: receivers of one statement are not linked (#535)

[analysis/lineage.md](analysis/lineage.md): `_reads_to_writes` no longer
draws edges between the self-accumulating receivers of one statement
(ADD/SUBTRACT/MULTIPLY/DIVIDE without GIVING, INSPECT counters, STRING /
UNSTRING POINTER and TALLYING IN).

## 2026-10-16 -- Dynamic CALL: SET cond TO TRUE and MOVE sources (#511)

[analysis/data-use.md](analysis/data-use.md): `DynamicCallAnalyzer` treats
`SET cond TO TRUE | FALSE` as a write to the condition's parent, checks for
untracked writes on every MOVE source feeding a CALL variable (and carries
the incompleteness along the MOVEs), and gives a literal MOVE to a source's
group the slice that lands in the source.
## 2026-10-16 -- MCP reachability from dead-code (#486)

[mcp.md](mcp.md), [analysis/flow.md](analysis/flow.md): `callers_of`'s
`reachable` and `program_brief`'s `unreachable_procedures` come from
`DeadCodeAnalyzer`; new `DeadCodeReport.fall_through_edges` filters the
flow graph's phantom `FALL_THROUGH` callers.
## 2026-10-16 -- xref declares FILLER level-88s and level-66 RENAMES (#485)

[analysis/data-use.md](analysis/data-use.md): `XrefAnalyzer` now declares
the level-88s under a FILLER and every level-66 `RENAMES` item, so they no
longer read as undefined in `xref`, `explain_symbol` and `lineage`.
[analysis/lineage.md](analysis/lineage.md): lineage maps a RENAMES item onto
the fields of its THRU range (else a caveat); [mcp.md](mcp.md):
`explain_symbol` gives it a byte range (else a caveat).

## 2026-10-15 -- MCP server, Phase 3 review fixes

[mcp.md](mcp.md): the index walk keeps symlinks out of the root out; a
dynamic `EXEC CICS LINK/XCTL PROGRAM(var)` gets candidates like a dynamic
CALL; `codebase_overview`'s `calls` counts graph targets; copybook impact
keeps every file of a duplicated PROGRAM-ID; a member asked about as a field
gets a `hint`; index builds send MCP progress. [analysis/lineage.md](analysis/lineage.md):
the duplicate PROGRAM-ID caveat is only returned to queries that reach it.

## 2026-10-15 -- MCP server, Phase 3

[mcp.md](mcp.md) gains the cross-program tools (`codebase_overview`,
`impact_of_change`, `where_from`, `callers_of` at program level) and
`codebase_index.py`'s three root-wide indexes. [analysis/codebase.md](analysis/codebase.md)
documents `CodebaseGraphBuilder.build_from_results()` and
`CodebaseGraph.copy_sites`. [analysis/lineage.md](analysis/lineage.md): a
linkage edge now cites the `PROCEDURE DIVISION USING` line rather than the
program's first line.

## 2026-10-15 -- MCP server, Phase 2

[mcp.md](mcp.md) gains `program_brief`, `callers_of` (paragraph level, plus
CALL sites of a program the file calls) and `record_layout`, and
`ParsedProgram.report()`, which keeps analyzer reports beside the cached
parse.

## 2026-10-15 -- MCP server, Phase 1

New [mcp.md](mcp.md) for `cobolparser/mcp/` and `cobol-parser mcp`
(`read_source`, `lint`, `explain_symbol`). [cli.md](cli.md) gains the `mcp`
row; [analysis/lint.md](analysis/lint.md) documents
`source_column_offsets()`, moved out of the CLI so the server shares it.
Review fixes: the parse cache also stamps copybook directories, and `lint`
grades unused copybook fields as info, matching the CLI.
Minor follow-ups: `expand_copybooks(skip_missing_copybooks=True)`
([preprocessing.md](preprocessing.md)) so one missing member no longer drops
every expansion; xref's `is_special_register()` behind `explain_symbol`'s
`special_register`; tools run on a worker thread under `Workspace.lock`;
`cobol.yml` is re-read when it changes; `read_source` streams.

## 2026-10-15 -- bundle restructure: history archived, big files split, content guard

Topic files now describe current behaviour only. Dated write-ups, audits and
before/after tables moved verbatim to per-topic archives in
[history/](history/); what they established that is still true stays in the
topic files as present-tense invariants. [analysis.md](analysis.md),
[parser.md](parser.md) and [generators.md](generators.md) are now short
routing pages in front of `analysis/` (8 files), `parser/` (6) and
`generators/` (4); no topic file is over ~55 KB. Every topic file has the
same shape (title, summary, Contents, topic-named `##` sections, See also).
`OKF_MAP` maps each module to the one file a reader would load.
New `scripts/okf_check.py` (run by the pre-commit hook and by
`tests/test_okf_claims.py`) checks the bundle's claims against the code:
imports, `cobolparser.*` names, class/function names, repo paths, links and
anchors, the `cli.md` subcommand table against argparse, and
`<!-- okf:gen NAME -->` spans for counts and lists the code can answer.
[index.md](index.md) routes to the new files and documents both guards.

## 2026-10-15 -- whole-bundle audit: every file checked against source

Every topic file was re-verified against the current source (imports,
signatures, dataclass fields, enum members, `--help` output, test
collection) and restructured for reading: each now opens with an Overview
and a Contents list, reference sections lead, dated notes read as rationale.
Notable corrections: [lexer.md](lexer.md) / [preprocessing.md](preprocessing.md)
/ [ast-models.md](ast-models.md) still described the Cython fast paths as
used whenever compiled (now `COBOLPARSER_ACCEL=1` only);
[analysis.md](analysis.md) counted 29 modules (33 + six private helpers) and
listed edge/violation kinds that do not exist (`GO_TO`,
`NUMERIC_TO_ALPHANUMERIC`, `MISSING_USING_CLAUSE`); [tests.md](tests.md)
described CI as running (`ci.yml` is fully commented out) and had 13,000 /
464 for 13,689 tests / 483 files; [dialects.md](dialects.md) said EXEC nodes
build on the dialect's own classes (the parser uses `models/sql_statements`
and `ibm_exec_statements`); [preprocessing.md](preprocessing.md) had
`PreprocessingError` extending `ParseError` (it is a plain `Exception`) and
a wrong pipeline order; [parser.md](parser.md) passed a dialect instance
where `DialectType` is taken; [cli.md](cli.md) gained a 38-row subcommand
reference table; [batch.md](batch.md) (last touched 2026-07-08) now covers
`scan.py`; [integration.md](integration.md) now summarises the whole
`interface-contract.md`, mocky-mock surface included. `index.md` gained a
"How each file reads" note; CLAUDE.md's routing table, counts, usage lines
and module lists were brought in line.

## 2026-10-15 -- bug hunt: gen-data `VALUE ALL X'..'` bytes

[generators.md](generators.md) (DISPLAY alphanumeric row): `VALUE ALL
X'FF'` was filled as Latin-1 text and re-encoded in the record charset
(`3f 3f` ASCII, `df df` EBCDIC); it is now a `LiteralCell` of the literal's
bytes repeated across the field, and decodes back to that cell.
[tests.md](tests.md): four `TestHexLiteralBytes` cases.

## 2026-10-15 -- issue #354: reached_via covers THRU ranges and GO TO DEPENDING

[analysis.md](analysis.md) (business rules, "Context on every rule"):
`BusinessRuleExtractor`'s `reached_via` now links every procedure of a
`PERFORM ... THRU` range and every `GO TO ... DEPENDING ON` target, not just
the first; the matching "Known limits" entry is gone.
[tests.md](tests.md): three regressions in `TestNestingAndReachability`.

## 2026-10-15 -- issue #340: TABLE-prefixed table names are tables

[analysis.md](analysis.md) (field lineage `sql` port row): `_sql_flow`'s
`_from_tables` treats a FROM piece as a table function only when it reads
`TABLE` followed by `(`, so `TABLE_CUST` / `TABLES_CFG` / `TABLEX` are
traced like any other table instead of skipped with the table-function
caveat.

## 2026-10-14 -- issue #395: dynamic-SQL trace respects statement order

[analysis.md](analysis.md) (`SQL_DYNAMIC_CONCATENATION` row):
`SqlCicsAnalyzer` no longer blames a PREPARE on a STRING the buffer was
overwritten after. A whole-item `MOVE` written directly earlier in the
PREPARE's paragraph cuts off every writer before it and elsewhere;
`_WriterFlow` in `sql_cics_lint.py` owns the rule. Without such a MOVE the
trace stays program-wide, so a statement built in a PERFORMed paragraph is
still found.

## 2026-10-14 -- issue #402: optional-keyword forms

[parser.md](parser.md): `OCCURS n TO UNBOUNDED` is an unbounded ODO table
(Python walker and the `_data_fast.pyx` bail-out); `INITIALIZE ... FILLER`
without WITH sets `with_filler`; FD `RECORD VARYING [IN SIZE] n TO m`
without FROM takes n as the minimum, and a lone `VARYING n` leaves the maximum None. `ENTRY ... USING [BY] VALUE/REFERENCE`
keeps every operand and records `EntryStatement.parameter_modes`, which
[analysis.md](analysis.md)'s `ProgramSignatureExtractor` now carries as each
ENTRY operand's `by_clause`.

## 2026-10-14 -- issue #403: leading IS in an abbreviated leg

[parser.md](parser.md): `_expand_abbreviated_condition` drops the optional
`IS` that opens an abbreviated leg (`IF A > 1 AND IS < 5`), so the leg
expands to `A < 5` instead of an operand-less COMPARISON.

## 2026-10-14 -- issue #390: special registers are not paragraph headers

[parser.md](parser.md) (the `looks_like_paragraph_boundary()` entry):
special registers (`RETURN-CODE`, `TALLY`, ...), reserved words that lex as
identifiers (`RUN`, `TRUE`, ...) and, in fixed-format source, any token in
Area B are never read as a paragraph header swallowed by a missing period.

## 2026-10-14 -- issue #394: XML PARSE THRU on the next line

[ast-models.md](ast-models.md), [analysis.md](analysis.md): the
`PROCESSING PROCEDURE [IS] p [THRU|THROUGH q]` consumer in
`xml_json_parser.py` looks past line breaks for `IS` and `THRU`/`THROUGH`
(`peek_past_noise`). A THRU on its own line used to fall into
`operands`/`clause_items`, leaving `processing_procedure_thru` None, so
dead-code, program-flow and lint reported the handler range dead. An `IS`
on its own line was read as the procedure name the same way.

## 2026-10-15 -- gen-fixtures follow-ups to #364 and #404

[generators.md](generators.md): the scenario planner no longer merges arms
on two 01 records of one FD (only one view is generated per scenario, so the
second record's arm was lost while coverage counted it merged); an arm whose
own path pins both is missed, and a scenario that still drops pins has its
arms demoted. The "alternate view(s) not generated" note names only records
no scenario used. A FILLER that owns a level-88 keeps its gen-fixtures column
under the path segment `FILLER#<n>`, so its branch witness is generated.

## 2026-10-14 -- issue #404: an unnamed data entry is FILLER

[ast-models.md](ast-models.md): `05 PIC X(3).` (FILLER omitted) now has
`is_filler=True` outside report groups, and the new
`CobolDataItem.layout_name` names it `FILLER` in record layouts, so gen-data
no longer writes an `ANONYMOUS-<level>-<line>` column and data-items,
lineage and host-variable resolution treat it like `05 FILLER`. The NIST
copybook-corpus floor in `test_copybook_csv_generation.py` drops from 20 to
10: the twelve layouts lost were all bogus ANONYMOUS columns from
PROCEDURE DIVISION fragments.

## 2026-10-14 -- issue #330: literal operands keep their quotes

[parser.md](parser.md) ("Literal Re-Quoting"), [analysis.md](analysis.md):
STRING, UNSTRING, INSPECT, CALL USING, SET and INITIALIZE REPLACING now
re-quote a string-literal operand the way MOVE and DISPLAY do, through
`_utils.literal_operand_text()`. business-rules' STRING re-quoting
heuristic is gone; unused-variables, lineage and xref no longer read
`'WS-CODE'` as the item `WS-CODE`.
Follow-up from review: `_literals.QUOTED_LITERAL_RE` / `is_quoted_literal()`
take the typed-literal prefix with the quotes, so the `X` of `X'00'` is no
longer read as the item `X` (unused-variables, xref, lineage, redundancy),
and gen-fixtures no longer reports a literal CALL argument unresolved.

## 2026-10-14 -- issue #363: gen-fixtures call_count follows control flow

[generators.md](generators.md), [analysis.md](analysis.md): `call_count`
was `len(sequence)` (+1 for AT END), or 1 for CALL/STATUS_ONLY, one per
statement, whatever branches and loops surrounded it. New
`analysis/invocation_counts.py` counts each statement on the certain path;
counts are merged per boundary key and omitted where they are not exact.

## 2026-10-14 -- bug hunt: `diff` PICTURE / USAGE spellings

[analysis.md](analysis.md): `diff` reported `PIC X(2)` -> `PIC XX` as
picture-changed and `COMP-3` -> `PACKED-DECIMAL` (or `COMP` -> `BINARY`) as
usage-changed. Both now compare by meaning; the strings are still shown as
coded.

## 2026-10-13 -- issue #291: MOVE FUNCTION sources are checked

[analysis.md](analysis.md): move-type-check counted every `MOVE FUNCTION
x(...)` as unresolved and lint blamed a missing COPY. Intrinsic results now
take their category from the intrinsic catalog (or their first argument);
the rest is counted in `unresolved_function_count` with its own caveat.

## 2026-10-13 -- compare: LOW-VALUES padding is a difference (#287)

[generators.md](generators.md), [cli.md](cli.md): a values compare treated
trailing (or all) LOW-VALUES and spaces in a text field as equal, because
the decoder strips both. Text fields now also compare their NUL positions,
and the text report shows hex when two differing values print the same.

## 2026-10-13 -- bug hunt: a CALL may write GLOBAL / EXTERNAL storage

[analysis.md](analysis.md): ConstantFolder kept a GLOBAL or EXTERNAL
field's value across a CALL that never named it; a contained program (or
any program sharing the EXTERNAL item) can write it. Every CALL / INVOKE
now forgets those leaves.

## 2026-10-13 -- bug hunt: ConstantFolder and control flow it did not follow

[analysis.md](analysis.md): `field_equals` values contradicted GnuCOBOL
output for `PERFORM` of a SECTION (walked nothing), `IF ... GO TO X-EXIT` /
`EXIT PARAGRAPH` (the skipped MOVE was folded), and DISPLAYs inside IF arms,
loops or past a GO TO (never treated as sites). All three now veto or
poison; see "Every site, and only control flow the walk really follows".

## 2026-10-11 -- bug hunt: ACCEPT FROM DATE YYYYMMDD is not a boundary

[analysis.md](analysis.md): `BoundaryInventoryAnalyzer._classify_accept`
compared the whole `from_source` against the non-interactive sources, but
cobolparser keeps the format qualifier there (`DATE YYYYMMDD`, `DAY
YYYYDDD`), so the commonest date idiom became a console `ACCEPT` boundary:
`gen-fixtures` generated stdin data for it and mockymock's `generate
--with-data` warned of a boundary key mismatch. It now compares the first
word, as mockymock's `mock_surface` does.

## 2026-10-12 -- FILLER VALUE SPACES in record images

[generators.md](generators.md): a FILLER whose `VALUE` is `SPACES`,
`LOW-VALUES`, `HIGH-VALUES` or `NULL` is encoded as that byte throughout
(`encoding._filler_fill()`); it used to carry the random text the value
generator draws for those figuratives. Checked byte-for-byte against
GnuCOBOL 3.2.

## 2026-10-12 -- lineage: ACCEPT FROM DATE is not a console port

[analysis.md](analysis.md): `FieldFlowAnalyzer` made every ACCEPT a
`console` port keyed on its whole `from_source`, so `ACCEPT X FROM DATE
YYYYMMDD` became a port `console:DATE YYYYMMDD` and a summary row from it
to every output the date reached. DATE / DAY / DAY-OF-WEEK / TIME
(matched on the first word, as PR #290 makes `BoundaryInventoryAnalyzer`
do) now make no port.

## 2026-10-12 -- multi-line EXEC boundary keys

[analysis.md](analysis.md): `BoundaryInventoryAnalyzer._unique_prefix`
collapses the other sites' whitespace before comparing, so two multi-line
EXEC SQL/CICS/DLI sites that differ only after a line break get distinct
keys (they used to share one, and mockymock `generate --with-data` warned of
a key mismatch and left both sites with placeholder bodies).

## 2026-10-08 -- JCL is read by jcl-parser

[jcl.md](jcl.md) rewritten: `cobolparser/jcl/` no longer parses JCL. Its card
scanner (`lexer.py`) and statement parser were deleted; `jcl/parser.py` is now
an adapter over the sibling `jcl-parser` package (optional extra
`cobol-parser[jcl]`, `>=2.0.0`), adding several jobs per deck, card-level
recovery, `proc_paths` procedure libraries (`jcl --proc-path`) and the
`unresolved` notes. The diagnostics jcl-parser does not raise are listed
under "Known gaps". [cli.md](cli.md), [index.md](index.md),
[analysis.md](analysis.md) follow.

## 2026-10-08 -- bug hunt: parser, analyzers, preprocessing, storage, JCL, CLI

[parser.md](parser.md): `_conditions.py` threads the abbreviated subject
through the recursion, so `A = 1 OR 2 AND NOT 3` and `A = 1 OR (2 AND 3)`
build full relations instead of operand-less COMPARISON nodes;
`data_clauses.py` stops the picture scan at a same-line word after a gap
(`PIC X(3) VALUES ...` no longer reads `X(3)VALUES`), and knows `BASED`.
[analysis.md](analysis.md): recursion-risk escapes ignore IF/EVALUATE
branch edges; unused-variables sees PERFORM TIMES counts, WRITE ADVANCING
counts, INITIALIZE BY values, CORRESPONDING pairs and XML/JSON group
operands; xref reads WRITE ADVANCING; `_names.py` accepts digit-led words.
[preprocessing.md](preprocessing.md): the expander splits on every record
boundary (bare-CR files expand) and `>>` lines never join a data entry.
[ast-models.md](ast-models.md): signed NATIONAL charges the implicit
separate sign. [jcl.md](jcl.md) / [cli.md](cli.md): omitted positional
sub-parameters keep their slot; `jcl --dd-map --program` filters;
`python -m cobolparser.cli.parse` runs.

## 2026-10-08 -- `parser.py` refactor (no behavior change)

[parser.md](parser.md): `_parse_core` split into `_preprocess_source` /
`_normalize_fixed_source` / `_tokenize`; `parse_program`'s loop body into
`_handle_unmatched_token` / `_parse_division`; `_handle_oo_unit_marker`
into `_open_id_clause_unit` / `_open_factory_or_object_unit` /
`_close_oo_unit`. `parse_cobol()` no longer detects/normalizes itself --
it delegates to `CobolParser`, so there is one fixed-format path.
[preprocessing.md](preprocessing.md): format detection moved to
`preprocess/source_format.py` (`detect_fixed_format`), with the shared
`normalize_with_recovery` used by the parser and the lexer.

## 2026-10-05 -- happy path kept in `branches`/`all` scenario modes

`generators.md`: `generate_with_scenarios` now prepends the happy-path
scenario in `branches`/`all`, so no bundle comes back with zero scenarios.

## 2026-10-05 -- from_json restores structure, equals compares content (#273)

[ast-models.md](ast-models.md): `CobolProgram.from_json` rebuilds sections,
paragraphs (no statements) and data items with their clauses, and warns
(`LossyDeserializationWarning`) with counts when statements are dropped.
`ASTNode.equals` compares location-stripped `to_dict()` plus the child
node-type tree instead of node types and child counts only.

## 2026-10-04 -- compare: differing trailing partial records are a difference (#250)

[generators.md](generators.md) / [cli.md](cli.md): `CompareResult.trailing_differs`
makes `equal` False when both files' tails differ, or under `compare_bytes`
when only one file has a tail (option (b)); `compare` then exits 1.

## 2026-10-04 -- lint: parse errors become `parse` findings (#249)

[cli.md](cli.md) / [analysis.md](analysis.md): `lint` turns each
`ParseResult.errors` entry into an error-severity `rule: "parse"` finding
(`add_parse_errors`), so `--fail-on` trips on a file that did not parse
(option (b): findings, not a hard exit 1). The sql-cics-check caveat for a unit
with no PROCEDURE DIVISION no longer claims an unchecked EXEC block.

## 2026-10-04 -- `parse_files_with_copybooks` source map, warnings, expansion failure reason (#255)

[batch.md](batch.md): the copybook-aware batch path now attaches
`expansion_source_map` and the expansion's warnings, as
`parse_cobol_with_expansion` does; when expansion raises, the
whole-file unexpanded fallback is kept (codebase-graph depends on it) but the
reason reaches `BatchResult.copybook_error` and `result.warnings`.

## 2026-10-04 -- audit: bundle checked against the current code, CI and release

Every `.okf/*.md` checked against the tree (backticked paths and class
names resolved in bulk, counts re-measured, CLI flags diffed against
`cli/parse.py`'s argparse). Counts that held: 244 `TokenType` members, 72
registered statement parsers, 29 analysis modules; no file still claims a
non-AGPL licence. Fixed:
[tests.md](tests.md): the CI section described the pre-2026-10-03 shape
(`build` PR/dispatch-only) -- now nightly `schedule`, `paths-ignore` for
docs-only changes, `build` on every trigger with a 3.11/3.12 smoke subset
on PRs, `coverage` on everything but push; release-please + cibuildwheel +
sdist summarized, closed-source mode noted as removed; the nonexistent
`baselines/` directory dropped; suite size updated (~12,340 tests, 439
files). [cli.md](cli.md): `--error-recovery` (and which subcommands take
it), `preprocess --strip-directives`, `expand --max-depth` were
undocumented. [jcl.md](jcl.md): round-11 behaviour (per-job PROC/SET scope,
JOB card closing an open PROC, `/* comment` as delimiter, `DD *` to EOF,
`--program` per job) existed only in this log; `jcl/bindings.py` section;
a Known-gaps bullet that had drifted under "DUMMY and overrides" moved back.
[ast-models.md](ast-models.md): `CobolProgram.program_name` (not
`program_id`), `contained_programs` / `unit_kind`; `PictureClause` field
names (`pattern`, `size`, ... -- there is no `picture_string`/`category`);
`RenamesItem` and `CobolFileDescription` named. [parser.md](parser.md) and
`CLAUDE.md`: the removed `ParserHost` protocol; a report path
(`reports/audit-2026-07-09.md`) that never existed. [analysis.md](analysis.md):
`ExecSQLStatement` spelling. [preprocessing.md](preprocessing.md): the NIST
corpus lives in `examples/cobol/`, not `examples/nist-cobol85`. `CLAUDE.md`:
33 statement parser files (not 34), test counts, CI triggers, and the seven
subcommands missing from its command list.

## 2026-09-30 -- business rule extraction (`business_rules.py`, `business-rules` subcommand)

New analyzer [analysis.md](analysis.md) `BusinessRuleExtractor`: every IF /
EVALUATE / SEARCH as a decision table (one branch per arm, condition +
actions), promoted to `validation` on an error signal, and paragraph-level
arithmetic as `calculation` rules with normalized formulas. Technical rules
(file status, READ AT END flags, SQLCODE/EIB*) are found from the program
and excluded by default but counted. Rules carry `guards`, `reached_via`,
inputs/outputs (via xref's role mapping), level-88 names spelled out in a
report glossary, `in_dead_code`, and a `data_lineage` inversion. New
[cli.md](cli.md) `business-rules` subcommand (`--format json|text`,
`--include-technical`). Ships feature idea #21; deliberately not built on
`constraints.py` (boundary-fed fields only -- see analysis.md).

## 2026-09-30 -- bug hunt round 12: DB2 types and tables, leading-sentence flow node, cross-unit CALL values, corpus sweep

Each reproduced first and pinned by `tests/unit/**/test_bug_hunt_r12_*.py`.
[dialects.md](dialects.md): bare `FLOAT` / `FLOAT(22..53)` is COMP-2 (was
COMP-1; `FLOAT(n)` keeps `precision`), bare `DECIMAL` is (5,0),
`TIMESTAMP(p)` is `20+p` characters; `FROM FINAL|NEW|OLD TABLE (INSERT ...)`
records the nested target (`ExecSQLStatement.data_change_tables`) and
`DELETE T WHERE` records `T`; scrollable cursors keep their name; cursor CTE
names, `TABLE(...)` and `LATERAL` are not tables; `/* */` comments inside
EXEC SQL are dropped.
[analysis.md](analysis.md): program flow has a `PROCEDURE DIVISION` node for
sentences before the first paragraph (it becomes the entry point);
complexity counts a section's leading sentences; DynamicCallAnalyzer
analyses each program unit on its own data and resets stale values;
xref records an OF/IN qualifier of a receiver as a reference, not a write;
host-variable resolution honours `:S.X`; `EXEC SQL SET :X = ...` is OUTPUT;
the SELECT-without-INTO lint ignores literals; CRUD marks FINAL TABLE
targets; scenario reachability uses the flow graph's parent procedure.
[generators.md](generators.md): `ProgramLayoutIndex.resolve` records no
bogus ambiguity for table elements; figurative QUOTE/ZERO must fill the
field; N/G values are sized in character positions; a truncated last RECFM=V
record is `trailing`; DATE/TIME numeric cells are written without leading
zeros so `decode(encode(row)) == row`.
[parser.md](parser.md): DECIMAL-POINT IS COMMA pictures keep their comma
(`-9,9(5)E-99`, `9,99`); lower-case relational words (`greater than or
equal to`); `GO TO.` has no target; `EQUALS`; subscripted/qualified
condition-names; INSPECT REPLACING CHARACTERS has no `from_value`;
I-O-CONTROL / SOURCE-/OBJECT-COMPUTER entries are recorded as metadata;
`from_json` keeps `unit_kind` and contained programs.
[cli.md](cli.md): `expand` reports a missing/circular COPY cleanly; a closed
stdout pipe exits 141 quietly; `cobol.yml` flow collections may span lines.
`ProfilerContext` reports the call's own peak (`peak_memory_exact`).
A corpus sweep (19,213 analyzer/generator runs over 640 files; 10,062
parser mutants) found no remaining crashes.

## 2026-09-30 -- bug hunt round 11: operator currency signs, JCL job scoping, float/P-scaled pictures, leading-sentence dead code

Each reproduced first and pinned by `tests/unit/**/test_bug_hunt_r11_*.py`.
[lexer.md](lexer.md): a declared currency sign shaped like an operator
(`<`, `>`, `=`) lexes as CURRENCY inside a picture string (NC108M parses
clean). [parser.md](parser.md): `_detect_fixed_format` samples only
fixed-format regions around `>>SOURCE FORMAT IS FREE`; EVALUATE Condition
selector text keeps string-literal quotes (`NOT 'THRU'`); SORT/MERGE KEY,
CANCEL and WRITE ADVANCING keep OF/IN qualifiers; a repeated CALL
exception phrase is merged with a warning; SELECT FILE STATUS/RELATIVE KEY
qualifiers (`*_qualifiers` fields), RELATIVE without KEY, `;` separators;
STRING/UNSTRING stop at a handler's period; level-88 bare `FALSE lit` and
unparsed-tail warning; GO TO DEPENDING keeps repeated targets; COMPUTE
expression trees fold qualified operands; `S1 SECTION 50.` segment numbers;
SYMBOLIC CHARACTERS stops at CLASS.
[generators.md](generators.md): external floating-point pictures edit and
de-edit a normalized mantissa/exponent; P positions in edited pictures count
as value digits (`scaling_leading`); level-88 figurative values are never
written as words; alphanumeric-edited values keep their insertion
characters; a qualified ODO counter names only its own item; free-form
copybooks split lines with `split_source_lines`.
[jcl.md](jcl.md): a JOB card ends an unterminated PROC; in-stream PROCs and
SET symbols are local to their job; `/* comment` is a delimiter; `DD *` data
may end at end of input; `jcl --bindings --program` matches per job.
[preprocessing.md](preprocessing.md): a `..` in a configured copybook
directory is not a traversal; COPY OF/IN library directories match
case-insensitively when the search does. [batch.md](batch.md): scan
isolates a file that fails strict decoding.
[analysis.md](analysis.md): dead-code and program-flow account for
sentences before a section's (or the division's) first paragraph; dynamic
CALL value sets are marked incomplete after ACCEPT/STRING/INITIALIZE/group or
slice writes; move-type-check resolves qualified duplicate names; dclgen
treats usage synonyms as equal and finds NOT NULL anywhere in a column;
REWRITE is valid on record-sequential files; const-fold skips DECLARATIVES;
IMS tracks qualified MOVEs into SSA segment names.

## 2026-09-29 -- bug hunt round 10: SEARCH sentence end, nested NOT phrases, POINTER-64, UX literals, xref declarations

Each reproduced first and pinned by `tests/unit/**/test_bug_hunt_r10_*.py`.
[parser.md](parser.md): a SEARCH WHEN/AT END body ends at the sentence
period (it swallowed the rest of the paragraph); `STOP RUN RETURNING 8` /
`STOP 12` accept a LEVEL_NUMBER-lexed integer; `ROUNDED MODE IS x` consumed;
WRITE/REWRITE `FROM` a literal or figurative; a nested READ/WRITE/DELETE/
START/REWRITE/STRING/UNSTRING/INSPECT/SORT/MERGE/XML/JSON/RETURN and a
PERFORM UNTIL condition no longer eat the enclosing statement's `NOT ...`
phrase; `WHEN NOT 1 THRU 5` is a negated Condition, not a range; qualified
PERFORM TIMES counts, CALL RETURNING items and SEARCH tables/VARYING indexes.
DATA DIVISION: POINTER-32/POINTER-64 sizes (4/8), lower-case PICTURE `s`/`p`,
DBCS `GGBGG` (2 bytes/position), level-66 RENAMES across lines and qualified
(`renames_*_qualifiers`), level-88 THRU across lines, typed (hex) 88 values,
FD RECORD VARYING bounds read by keyword (an omitted bound is None).
[lexer.md](lexer.md): `UX"..."` is one literal; commented-out
DECIMAL-POINT IS COMMA / CURRENCY SIGN no longer take effect; `tokenize`
invents no column-7 COMMENT tokens in free-format regions.
[preprocessing.md](preprocessing.md): `>>EVALUATE FALSE` and `>>WHEN a THRU b`;
directive number comparison only for COBOL-shaped numerals (not `nan`/`inf`).
[cli.md](cli.md): `--define` keeps `>>SOURCE FORMAT` directives.
[analysis.md](analysis.md): xref no longer double-declares INDEXED BY names
and records SELECT (FILE STATUS, PASSWORD, ASSIGN USING) and DATA DIVISION
(FD DEPENDING ON, ODO counter) references; program signatures merge a
group's own and subordinate directions and see level-88 uses; unused-variables
ignores contained programs' references except to GLOBAL items; ProgramDiffer
sees SEARCH ALL and INSPECT CONVERTING BEFORE/AFTER; the SQLCODE-check search
scans every paragraph of a PERFORM THRU range; `extended_complexity` counts
AND/OR in EVALUATE/SEARCH WHEN text and not unary NOT.

## 2026-09-28 -- bug hunt round 9: JCL overrides, record images, COMPUTE, EVALUATE, config

[jcl.md](jcl.md): `PARM.ps=` / `COND.ps=` (and unqualified PARM/COND) on a
procedure EXEC are applied to the procedure steps; an in-stream DD override
replaces a procedure dataset (and vice versa); IF expressions continue to
THEN and text after THEN/ELSE/ENDIF is a comment; concatenated procedure DDs
are overridden by position; column 72 is never part of a field.
[generators.md](generators.md): JUSTIFIED RIGHT honoured in record images;
excess decimal places truncated (not rounded) on encode and edit; 31-digit
values keep every digit; a non-zero COMP-3 pad nibble is a decode error.
[parser.md](parser.md): unary sign binds tighter than `**` (IBM hierarchy);
string literals spelled like clause words (`"ELSE"`, `"ANY"`, `"THRU"`,
`"END-IF"`, `"WHEN"`, ...) stay literals in IF/EVALUATE/SEARCH/PERFORM
conditions; `COMPUTE X EQUAL expr`.
[analysis.md](analysis.md): ConstantFolder poisons COMPUTEs whose IBM
intermediate quotient truncation it cannot reproduce (`7 / 2 * 2` is 6, not
7); `domains.solve()` no longer witnesses LOW-/HIGH-VALUES as blanks; each
later EVALUATE WHEN arm carries the negation of the earlier ones
(first-match); xref reads BY CONTENT / BY VALUE CALL arguments as reads;
ProgramDiffer compares every statement field and matches unnamed data
entries as FILLER; the SQLCODE-check search stops at the next EXEC SQL.
[cli.md](cli.md): the `cobol.yml` reader rejects `- ` where a scalar
belongs, reads every YAML 1.2 double-quoted escape, and names a tab after
`-`; a list/mapping `project.define` value is a ConfigError.

## 2026-09-28 -- bug hunt round 8: parsers, preprocessing, generators, analysis, JCL/config

[parser.md](parser.md): SEARCH without END-SEARCH no longer eats an
enclosing ELSE and the rest of the sentence; INITIALIZE targets / REPLACING
BY values keep subscripts and OF/IN qualifiers; `NOT >=` / `NOT GREATER
THAN OR EQUAL TO` resolve to LESS (and the `<=` family to GREATER);
STRING/UNSTRING `DELIMITED` without `BY` keeps its delimiters; `DISPLAY
FUNCTION TRIM(A)` is one item; group USAGE / SIGN are inherited by
subordinate elementary items (`usage_explicit`).
[preprocessing.md](preprocessing.md): a long continued literal survives
copybook expansion (re-continued, not truncated); REPLACE LEADING/TRAILING;
a malformed REPLACE warns; `:TAG:` replaced every time in a word; COPY
REPLACING matches code+literal search text, compares literals
case-sensitively, and no longer splits `1.5` or `WS_A`.
[generators.md](generators.md): complex-ODO counter lookup falls back by
name in the decoder; variable-bare framing by layout before separator;
BLANK WHEN ZERO; national-content caveat.
[analysis.md](analysis.md): ConstantFolder forgets PERFORM VARYING/AFTER and
SEARCH VARYING variables and writes through level-66 RENAMES; program
signatures grade ENTRY parameters, carry BY VALUE, and count the RETURNING
item as named. [jcl.md](jcl.md): SET values are taken at the EXEC card;
DCB overrides merge; `DD *,DLM=` keeps `//` cards as data; continued
strings keep blanks through column 71; CR/LF-only line splitting.
[cli.md](cli.md): `cobol.yml` reader handles `''` / `\"` escapes, rejects
content after `...`, ignores a UTF-8 BOM.

## 2026-09-28 -- accelerator audit: OCCURS count overflow, short-record literals, `*>` in data entries

Differential run (Cython vs forced pure-Python) over tests/samples,
examples/cobol and ~35k generated fixed/free-form inputs: tokens, normalized
text and ASTs agreed everywhere except one. [lexer.md](lexer.md):
`_data_fast` OCCURS counts past INT_MAX raised `OverflowError` and cost the
whole DATA DIVISION (`cdef int` -> `cdef object`).
[preprocessing.md](preprocessing.md): a continued literal on a record whose
trailing blanks were stripped lost the blanks through column 72 (pure,
Cython and the expander). [parser.md](parser.md): `*>` floating comments
are dropped from the parser's `TokenStream`, so a comment between a data
clause keyword and its operand no longer drops the operand or fabricates a
level-number item.

## 2026-09-28 -- control-flow bug hunt: nested-unit references, PERFORM UNTIL scope terminators, DOT keyword ids, hidden unreachable nodes

[analysis.md](analysis.md): `DeadCodeAnalyzer` and the flow scanner's ENTRY
collection no longer credit a contained program's PERFORM/ENTRY to the
container's same-named paragraph. [parser.md](parser.md): an out-of-line
`PERFORM p UNTIL c` nested in IF/EVALUATE/inline PERFORM stops at the
enclosing `END-xxx` instead of swallowing it (which re-nested a top-level
`STOP RUN` into the IF arm). [generators.md](generators.md): DOT quotes
paragraph ids that are DOT keywords; `show_unreachable=False` also drops the
hidden paragraph's edges, branch boxes and CALL-only external nodes.

## 2026-09-28 -- bug hunt round 8: comment-entries, currency symbols, SPECIAL-NAMES, SELECT short forms

[lexer.md](lexer.md): IDENTIFICATION DIVISION comment-entries lex as
verbatim `COMMENT_ENTRY` tokens (244 TokenType values); declared
SPECIAL-NAMES currency symbols lex as `CURRENCY`. [parser.md](parser.md):
comment-entry text stored as written; SPECIAL-NAMES clauses end at the next
clause (`symbolic_characters`, `currency_signs` added); SELECT without
`ORGANIZATION IS`, `ASSIGN USING`, clause words split across lines.
[ast-models.md](ast-models.md): `PictureClause.currency_symbols`,
`SelectStatement.assign_using`.

## 2026-09-28 -- bug hunt round 7: batch .prof collisions, DOT escaping, >>DEFINE arithmetic, nested ALTER in health

[batch.md](batch.md): per-file `.prof` dumps of inputs sharing a stem no
longer overwrite each other (`<stem>-2.prof`, ...). [generators.md](generators.md):
DOT edge labels are escaped, node-label line break no longer double-escaped.
[preprocessing.md](preprocessing.md): `>>DEFINE V AS 2 + 1` evaluates the
arithmetic expression. [analysis.md](analysis.md): `TechnicalDebtAnalyzer`
counts only the unit's own ALTERs, not its contained programs'.

## 2026-09-28 -- bug hunt round 6: IMS parmcount, LE FUNCTION words, callee USING order, report origins

[analysis.md](analysis.md): IMSSegmentAnalyzer read CBLTDLI/AIBTDLI's
optional leading parmcount as the function code (every operand shifted);
LanguageEnvironmentAnalyzer reported intrinsics out of data names containing
FUNCTION and missed them in conditions / STRING; the boundary inventory's
callee-source rung bound arguments to LINKAGE declaration order instead of
`PROCEDURE DIVISION USING`. [cli.md](cli.md): every analyzer subcommand now
stamps `origin` under `--copybook-path` (was lint / unused-variables only).
[parser.md](parser.md): UNSTRING `DELIMITED BY ALL` recorded
(`delimiter_all`, emitted only when present).

## 2026-09-28 -- bug hunt round 5: STATUS without FILE, CALL USING literals, refmod MOVEs, SQL indicators

[parser.md](parser.md): `SELECT ... STATUS IS x` (IBM's optional FILE) was
swallowed into `assign_to`; CALL USING stopped at a figurative constant or a
signed literal, dropping it and every later argument.
[analysis.md](analysis.md): move-type-check never resolved a glued
subscripted / reference-modified source (`T-E(2)`, `WS-A(1:3)`) and treated
a ref-modified receiver as its base category; dclgen-check reported null
indicators as unchecked host variables. [dialects.md](dialects.md):
`ExecSQLStatement.null_indicators` missed the `INDICATOR :x` form as parsed
from source (the rebuilt text has no blank before the colon).

## 2026-09-28 -- bug hunt round 4: linkage arguments, CLOSE REEL, SQL tables, CRUD writes

[analysis.md](analysis.md): linkage-check matched CALL arguments verbatim, so
subscripted / ref-modified / qualified / `ADDRESS OF` LINKAGE items read as
unreferenced; io-sequence treated `CLOSE f REEL|UNIT` as closing the file;
the CRUD matrix marked a write statement's subquery tables with the write
flag and ignored MERGE. [dialects.md](dialects.md): `ExecSQLStatement.tables`
no longer lists the column after a function-argument FROM
(`EXTRACT(YEAR FROM HIRE_DATE)`), and INSERT/UPDATE now also list the tables
their subqueries read (target still first).

## 2026-09-27 -- bug hunt round 3: INSPECT delimiters, directive comments, section dead code

[parser.md](parser.md): INSPECT `BEFORE INITIAL SPACE` dropped every later
TALLYING clause; CONVERTING lost subscripted operands and its BEFORE/AFTER.
[preprocessing.md](preprocessing.md): `*>` comments on `>>` directive lines
became part of the directive. [analysis.md](analysis.md): dead-code no longer
treats every paragraph of a referenced section as live past a terminator.

## 2026-09-27 -- bug hunt round 2: expanded-line locations, VB short tail, YAML strictness

[batch.md](batch.md) / [cli.md](cli.md): `scan` and `unused-variables
--copybook-path` reported expanded-text line numbers; report locations now
carry an `"origin"` from the expander's source map, as lint findings did.
[generators.md](generators.md): `variable-bare` decoding reported a short
trailing partial record as one more (truncated) row instead of `trailing`.
[cli.md](cli.md): the config YAML reader took `1_000` as an int, `key: a: b`
as the string `a: b`, `- - x` as the string `- x`, and counted form feeds as
line breaks.

## 2026-09-27 -- bug hunt: compare-bytes ignore, YAML apostrophes, split PIC repeats

[generators.md](generators.md): `compare_bytes=True` no longer reports an
ignored field's bytes as `(unmapped bytes)`. [cli.md](cli.md): the config
YAML reader no longer treats a mid-word apostrophe as opening a quote (it
swallowed trailing comments); `decode`/`compare` reject negative paging
flags and a non-positive `--record-length`. [ast-models.md](ast-models.md):
`PictureClause` sizes unedited pictures with split repeat factors
(`X(2)X(3)`, `9(2)9(3)`, `NN`) correctly.

## 2026-09-27 -- audit patch batch: typed VALUE literals, linear COPY scan, REPLACING size

From `AUDIT.md` §8 step 1. `VALUE X"4142"` kept only its content, so
gen-data wrote `41` for the bytes `AB`: the VALUE clause now keeps a typed
literal's source text (`data_clauses.literal_source`) and generators decode
it (`_literals.typed_literal_content`). The COPY scanner re-skipped a whole
whitespace run at every character of it (quadratic: 4,000 blank lines took
~170 s); it now jumps whole runs. REPLACING growth now counts toward
`max_total_size`. `cobolparser/error_log.txt`, a stray debug file that
shipped as package data, is deleted. `lexer.md`, `parser.md`,
`generators.md`, `preprocessing.md`, `tests.md` updated. Regression tests:
`tests/regression/test_audit_2026_09_27.py`.

## 2026-09-27 -- EXEC SQL MERGE and WITH (CTE) statements get a type and tables

`ExecSQLStatement` classified only statements that start with their verb,
and table extraction is keyed on the type, so `MERGE INTO ... USING ...` and
`WITH cte AS (...) SELECT ...` were `"UNKNOWN"` with `tables == []`: a
program writing a table through MERGE, or reading through a CTE, showed no
DB2 table use (the backend's MERGE-as-WRITE handling never ran). New
`SQLStatementType.MERGE`; the target (`INTO`) and source (`USING`) are read
by the tokenized pass, a `USING (SELECT ...)` subquery's tables by the FROM
regex, and the target is kept first. `_split_common_table_expressions()`
peels the CTE list off a `WITH` statement: the type is the main verb's, the
SELECT list is the main SELECT's, and CTE names are dropped from `tables`.
`ast-models.md` updated. Regression tests:
`tests/unit/test_exec_sql_merge_cte.py`.

## 2026-09-21 (follow-up) -- the stamp shape admits blanks between digits

Re-running the reported program against the fix below took its 19 warnings
down to 3. The residue was a second stamp layout in the same file: the
identification field laid out in *sub-fields* -- `01636  0`, a 5-digit
change id, two blanks, a 1-digit level, filling columns 73-80 exactly.
Both gates tested the tail with a plain `str.isdigit()`, which an embedded
blank fails, so the shop's own stamp still read as split code there.

`_is_numeric_id_stamp_text(tail)` is now the one definition of the shape --
at least one digit, nothing but digits and blanks -- used by the full-width
gate, the short-tail gate and the evidence test alike. Blanks are part of
an identification field's layout, not noise around it. Nothing the shape
excluded before is admitted now: any letter or punctuation still fails it
(`IX2094.2`, `AYS`, `ON WS-COUNT.`), and a sub-fielded run past column 80
still warns. The three reported lines are full-80-width, so the full-width
gate settles them with no file evidence needed; the whole-file gate covers
the shorter sub-fielded case. Corpus sweep unchanged at 3 genuine hits.
Pinned by `TestSubfieldedNumericStamp` and
`TestSubfieldedChangeStampDeckParsesWarningFree`.

## 2026-09-21 -- a short columns-73+ change stamp is not truncated code

Reported from a mockymock session: a real mainframe program was rejected
outright because `normalize_fixed_format` emitted ~19 `content beyond
column 72 was dropped mid-token` warnings, and mockymock refuses a program
fail-closed on *any* `ParseResult.warnings` entry. Nothing had been
truncated. The file's change-control tool stamps a 5-digit code at column
73 (`00551`, `00257`, `01641` -- it stamps physical lines as they change,
so the numbers jump around) with columns 1-6 blank, and every line whose
statement happened to end exactly on column 72 hit the mid-token shape.

The existing numeric-stamp gate only excused a tail filling columns 73-80
*exactly*, because per line a shorter all-digit tail is indistinguishable
from a data name's own trailing digits getting cut. That ambiguity is real
per line and absent across the file: a stamped deck also carries lines
where the stamp is preceded by a blank at column 72, where nothing *could*
have been split. `_has_identification_stamp_convention()` counts those, and
`MIN_ID_STAMP_EVIDENCE_LINES` (3) of them let the ambiguous lines be read
the same way. Lazy -- only a line that would warn asks for the scan, and it
returns at the third evidence line. A non-numeric tail and a numeric run
past column 80 still warn, stamped file or not. Mirrored in
`_preprocess_fast.pyx` (and its checked-in `.c`), with fast/pure parity
pinned over *multi-line* inputs, since the older parity cases are single
lines that can never establish a convention. Details in
[preprocessing.md](preprocessing.md); pinned by
`TestShortIdentificationStampConvention` and
`TestShortChangeStampDeckParsesWarningFree`.

## 2026-09-17 -- audit: the text-manipulation stages, read against the IBM rules

A second repo-wide audit, this time of everything that runs before the
lexer: record splitting, fixed-format continuation, `COPY ... REPLACING`,
`REPLACE`, `>>IF`, and EBCDIC copybook decoding. A differential fuzz of
`parse_cobol` (27k mutated parses over every sample program) found no
crash; reading the code against the IBM Enterprise COBOL reference found
nine defects, every one confirmed by a repro, none reachable by a suite
whose inputs are well-formed ASCII with one statement per line. Full
write-up in [preprocessing.md](preprocessing.md) ("Audit 2026-09-17");
pinned by `tests/regression/test_audit_2026_09_17_preprocessing.py`.

* **`str.splitlines()` is not a record splitter.** Form feed, NEL and the
  other Unicode line boundaries inside a record made two lines of it and
  shifted every later `location.line`. New `cobolparser/_lines.py`
  (`split_source_lines`) is used by every stage; `OKF_MAP` maps it.
* **EBCDIC NL records were silently truncated to the first record** --
  `detect_encoding` knew 0x15 was a newline, the decoder did not.
* **`validate_copybook_content` looked for the indicator in column 7 of
  content the expander had already stripped**, so every continued literal
  in a copybook produced a false "unbalanced quotes" warning.
* **`COPY ... REPLACING` compared raw characters, and re-applied clauses
  over its own output** -- `PIC  X(10)` missed, `== A ==` never matched,
  and a swap turned everything into one side. Text words, one pass.
* **`REPLACE` did not see `(` `)` as separators**, so a subscripted
  reference was never replaced.
* **`>>IF DEBUG DEFINED` (no `IS`) evaluated FALSE with a warning** and
  dropped the block on every parse.
* **A word continued across a comment line was split in two**, with no
  diagnostic; the comment/blank branches only deferred for an open literal.
* **A quotation mark in column 72 followed by `''` on the continuation**
  closed the literal instead of continuing it.

The two continuation fixes are mirrored in `_preprocess_fast.pyx`
(`_next_code_line`, `closing_quote_at_72`) and its regenerated `.c`.

## 2026-09-16 -- audit: an exactness gate that was itself inexact

A repo-wide audit (lint/format/typecheck clean, 11,088 tests green, parser
and all 23 analyzers fuzzed to zero crashes over 95 programs x 5 mutants,
copybook path traversal and symlink escape both correctly refused,
encode/decode round-tripping exact across the PICTURE/USAGE cross product).
Three defects found, two of them the same one twice.

* **`const_fold.py` could record a value that is wrong.** The module's whole
  contract is "exact by construction, or absent", and both halves of the
  machinery enforcing it decided exactness *using inexact decimal
  arithmetic*. `_exact_divide` multiplied the quotient back inside the same
  `prec=80` block the division ran in -- where the rounding error is by
  construction too small to represent, so the product rounded straight back
  to the dividend and the check passed for every inexact quotient it existed
  to catch. `_fits_exactly`, the last gate before a value is stored, scaled
  with `Decimal` operators running in the ambient 28-digit context, so a
  value carrying more precision was silently rounded by the very `abs()` and
  `*` used to test it. Together:
  `COMPUTE WS-T = 3 / 0.3333333333333333333333333333334` into
  `PIC S9(9)V9(9)` folded to `9.000000000` where COBOL stores
  `8.999999999` -- a wrong integer digit, emitted as a `field_equals`
  expectation into a generated fixture bundle. Both now decide over
  `Fraction`. Separately, a `/` inside a COMPUTE tree never went through
  `_exact_divide` at all; it does now, so both spellings of a division hold
  the same contract.

  The general lesson, and the reason this sat behind a green suite: a check
  written in the same arithmetic as the thing it checks has no independent
  standing. The tests all used short literals, where the defect is
  unreachable -- it needs an operand carrying more than ~28 significant
  digits, which IBM Enterprise COBOL permits under `ARITH(EXTEND)`. A
  differential test against exact rationals found in one pass what the
  suite could not.

* **`config/_yaml.py` mis-tracked a backslash escape.** `_strip_comment`
  advanced one character past `\` instead of two, so the escaped quote was
  read on its own and closed the string it sat inside. An even number of
  escaped quotes re-opened it and hid the damage; an odd number left a
  later `#` looking unquoted, so `msg: "a \" # b"` lost its tail and then
  failed with "unterminated quoted string" -- a legal config file rejected.

* **`encoding.py` carried a `# pragma: no cover` that claimed a guard it
  did not have**, saying the binary encoder's overflow branch was
  "guarded by `_digits_string`" when that helper is never called there. The
  asymmetry is real and deliberate (zoned/packed truncate like a COBOL MOVE;
  binary refuses a value with no representation in its byte width) -- only
  the comment was wrong. Behavior unchanged; the comment now says what is
  actually true and `generators.md` records the asymmetry.

Also corrected: `CLAUDE.md` claimed 24 analysis modules (28) and ~9,400
tests across 356 files (~11,100 across 388).

## 2026-09-15 -- OKF bundle repair: ordering, routing, and the map that lets it rot

A review of the bundle against the source tree, and the four things it found
fixed.

* **`OKF_MAP` had 15 holes, which is the mechanism behind everything else.**
  `scripts/okf_staleness_check.py` maps source paths to OKF files, and the
  pre-commit hook only asks for an update when a *mapped* path changes.
  Unmapped: the whole `cobolparser/jcl/` package, `cobolparser/parser.py`,
  `scan.py`, `plugins/`, `profiling.py`, `_errors.py` and more. The
  `parser.py` miss is the instructive one -- the map's
  `cobolparser/parsers/` prefix ends in a slash, so it never matched the
  orchestrator module sitting beside that package. A directory prefix and a
  same-named module are two entries, never one.
  `tests/test_okf_staleness_map.py` now fails if any source file maps
  nowhere, if a mapped OKF file does not exist, or if a directory prefix
  loses its slash.
* **`log.md` was not in log order.** Five entries had been appended to the
  bottom of a newest-first file, after the oldest (2026-06-28) section --
  including *both* 2026-09-15 entries, so the two newest entries in the repo
  were the last thing in a 4,356-line file and a reader skimming the top for
  recent work saw 2026-09-12 and stopped. Moved back into place; content is
  unchanged line for line. A follow-up entry may still sit under the entry it
  follows up on when a day or two out of order -- that adjacency is
  deliberate and the header now says so.
* **PR #212 had appendix-level coverage.** 8,253 lines across six modules
  had ~50 lines of OKF, explicitly "what a reviewer needs to know, not the
  full design". `xref`, `program_signature`, `codebase`, `sql_cics_lint` and
  `ast_diff` now have real sections in [analysis.md](analysis.md) (API,
  report shapes, the grading rules, and the known gaps kept where they
  were), and the JCL front end -- a whole second language, previously six
  lines *inside analysis.md*, where nobody would look for it -- has its own
  [jcl.md](jcl.md).
* **`index.md` did not route to any of it.** It claimed 24 analysis modules
  (28), hand-mirrored the package version, and listed no JCL at all. It now
  leads with a task -> file table and drops the version mirror.

Same append-after-the-end mistake, twice more: `cli.md` and `tests.md` both
had a section sitting *after* their "See Also". Both moved, and `cli.md`'s
seven-subcommand stub was replaced with real flag tables under the
Subcommand Reference where the other subcommands live.

The general lesson: a docs-staleness check is only as good as its map, and
nothing was checking the map. A convention that lives only in people's heads
("newest first", "See Also goes last") drifts exactly as fast.


## 2026-09-15 -- Enterprise COBOL program-type coverage

One representative program per program type (`tests/samples/enterprise/`,
22 programs; `docs/enterprise-program-types.md`) run through the whole
stack, and the gaps it found closed: OO COBOL units (CLASS-ID / FACTORY /
OBJECT / METHOD-ID, OBJECT REFERENCE), PROGRAM-ID attributes (RECURSIVE,
the PROGRAM word, optional period), RETURNING, 6.x data clauses (PIC U,
BYTE-LENGTH, DYNAMIC LENGTH, VOLATILE, OCCURS UNBOUNDED), DECLARATIVES
modelled (and honoured by dead-code, program-flow, io-sequence), XML
PROCESSING PROCEDURE and CICS HANDLE targets as references, EXEC DLI in
the IMS analyzer, CICS translator items and SET ADDRESS OF in
linkage-check / unused-variables, IS RECURSIVE in recursion-check,
conditional compilation by default, REPLACE partial words, JSON
CONVERTING, qualified DECLARE TABLE names, EXEC SQL INCLUDE expansion.
See [parser.md](parser.md), [analysis.md](analysis.md),
[ast-models.md](ast-models.md), [preprocessing.md](preprocessing.md),
[tests.md](tests.md) (each has a 2026-09-15 section) and the CHANGELOG.


## 2026-09-15 -- Review follow-ups on PR #212 (xref, signatures, codebase, SQL/CICS lint, diff, JCL) and #219

PR #219's did-you-mean pool keeps extensionless copybooks (see
[preprocessing.md](preprocessing.md)). PR #212's six modules get their
first OKF sections ([analysis.md](analysis.md), [cli.md](cli.md)) and the
fixes the review found: digit-led paragraph names credited, contained
programs excluded from the outer unit's xref/signature, special registers
and STRING literals out of `undefined`, `duplicate_declarations` on the
xref report, `returning` and ambiguous-role / duplicated-field grading on
signatures, normalized path keys and dot-less extensions on the codebase
graph, unexpanded-COPY caveats on `xref`, the `sql-cics-check` rule id,
DECLARE GLOBAL TEMPORARY TABLE graded, explicit diff signatures for the
statement types whose semantics live off `operands`, and the cataloged
`// PROC` header in JCL. Gaps the review found but this pass did not
close are listed per module in analysis.md.

## 2026-09-12 — missing-period check judges the entry, not the line

Found by running the `legacy-application` corpus through the COBOL Analyzer
extension's own surfaces: every one of the 20 expansions carried 8 identical
"may be missing terminating period" warnings, all false, all from one
copybook's multi-line `PIC` / `VALUE` entries. `validate_copybook_content`
now examines a whole data-description entry rather than a physical line.
See `preprocessing.md` for the mechanism and why blank lines still do not
close an entry.

The general lesson is the one the 2026-07-27 fix to this same check already
half-learned: COBOL's unit of source is the *sentence*, and any check
written against a line will be wrong for every construct that legally spans
more than one.

Follow-up the same day: the first cut of that fix left its two patterns
disagreeing about what a level number is (`\d{1,2}` for finding where an
entry starts, the original `\d{2}` for deciding whether to report it), so a
single-digit-level entry closed its neighbour but was never checked itself —
a hole that reads exactly like a clean result. They now share one
`_ENTRY_HEAD` fragment. Two regexes that must describe the same construct
are a drift hazard whether or not they currently agree; deriving both from
one definition is cheaper than the test that catches the drift later.


## 2026-09-10 — code-review follow-up: 15 findings across analysis/generators/parsers

A code-review pass over the 2026-09-09 review-fix diff (`CHANGELOG.md` →
Unreleased), one finder per angle (correctness, reuse, simplification,
efficiency, altitude/CLAUDE.md conventions, removed-behavior), each finding
verified before being accepted. Regression tests are spread across the
existing suite (see `tests.md`'s "Cross-repo review follow-up fixes"
section) rather than one new file per finding this time.

Three worth keeping in mind beyond their own doc sections:

* **A `has_suffix` flag dropped in one of four call sites is a real
  correctness bug, not a style nit (`analysis.md`).** `const_fold.py`'s
  `_apply_move_target`/`_write_numeric` correctly poison a subscripted/
  reference-modified write target instead of asserting a value; a third
  function computing the same "base item, with suffix" split
  (`_target_paths`, used by READ INTO/ACCEPT) silently dropped the flag and
  fully restored the base item instead. Same input shape, three call sites
  agreeing and a fourth silently not — worth grepping for every caller of a
  shared helper when auditing one of its call sites, not just reading the
  one you started at.
* **"Remove the duplicate" is not always right (`generators.md`,
  `analysis.md`).** Two reuse findings from the same review batch
  (`const_fold._link_redefines` vs `layout_offsets._walk_redefines_chain`;
  `dead_code._collect_range_end` vs `program_flow.edges.range_members`)
  turned out, on inspection, to solve genuinely different problems from a
  shared input shape — forcing a merge would have added a real dependency
  (a full CFG build, in the second case) for no correctness gain. Both are
  documented in place instead, with the investigation's own reasoning kept
  in the code comment rather than assumed away.
* **A stale override can mask a since-corrected value (`analysis.md`,
  `dialects.md`).** `ibm_enterprise.py`'s `_LEGACY_INTRINSIC_SIGNATURES`
  table was assumed at review time to be merely redundant with
  `le_signatures`'s catalogue; checking found it was actively wrong for
  `LENGTH` (`return_type`/`parameters` reported `"numeric"`/`["string"]`
  after the catalogue had already been corrected to the more precise
  `"integer"`/`["any"]`, silently overridden by the older hand-written
  value every time). Removed down to the one fact the catalogue has no
  field for at all (`CURRENT-DATE`'s byte length).

## 2026-09-09 — cross-repo bug review: 46 fixes across the pipeline

A review pass over every layer (lexer/preprocess, parsers, analysis,
generators, CLI) with one reviewer per area, each finding reproduced by a
script before it was accepted. Regression tests live in
`tests/regression/test_review_2026_09_09_{preprocess,parser,analysis,generators}.py`
(one class per finding); the full list is in `CHANGELOG.md` → Unreleased →
Fixed. Three decisions worth keeping:

### Continuation records owe a placeholder (`preprocessing.md`)

The normalizer's claim that "output line count equals input line count" only
ever held for comment and blank lines. A continued literal *removed* lines,
so every location after it was wrong — and lint, the extension's
diagnostics, and the expander's source map all consume those locations. The
fix is a `deferred` counter: a continuation record owes one empty line,
emitted after its logical line flushes. The same counter is what lets a
comment line interrupt an open literal without severing it (the placeholder
is deferred, the next `-` record rejoins), which had been on the LOW list
since July. Both paths (pure and Cython) changed; the parity harness still
reports zero mismatches.

### A PERFORM range end never falls through (`analysis.md`)

Two HIGH analysis bugs shared one cause: the CFG's documented
over-approximation of a fall-through edge out of a performed range's end.
`recursion-check` closed a phantom cycle with it (the priming-read idiom,
graded as an unconditional infinite loop), and `DeadCodeAnalyzer` credited
everything after an `xxx-EXIT` paragraph as reached when that paragraph was
a `GO TO` target inside its own range. Both fixes are local — the recursion
analyzer discards a cycle whose closing hop is that edge; dead-code stops
treating a THRU end as a fall-through source — rather than removing the
edge from the graph, which other consumers rely on.

### "Unknown" must be unknown (`generators.md`, `analysis.md`)

`ConstantFolder`'s contract is "exact by construction, or absent". Three
findings were places it kept a value it could not know: a group-level write
(the layout index resolves only leaves, so the write was a no-op), a
statement that overwrites its target through a field the folder did not
scan (SQL host variables, UNSTRING targets, a reference-modified MOVE), and
a `REDEFINES` alias. The solver had the same shape: a signed literal it
could not parse was *ignored*, which turned "constraint unknown" into
"constraint satisfied". Every one of these is now a poison or an
`Unsatisfiable` with a reason.

The CLI pass (eight smaller items, `tests/regression/test_review_2026_09_09_cli.py`)
found the one cross-repo contract break: the extension sends `--program` to
every analyzer, but `unused-variables` and `program-flow` never accepted it,
and the extension's "CLI too old" fallback re-ran without it — a wrong unit's
report with no sign of it. Both take it now.

Also removed: `LinkageChecker`'s `VALUE_TO_LINKAGE` rule, which had no basis
in COBOL and fired exactly where it could see the callee wanted BY VALUE.
Still open, recorded in `reports/open-findings.md`: numeric-edited fields are
written to record images as plain numbers, not the edited image.

## 2026-09-07 — where a line came from, and which program it belongs to

Request (from the VS Code extension's own limitation list): make the four
things the extension had to document as "we cannot do this" actually work.
Two of them are here.

### The expander's source map (`.okf/preprocessing.md`)

`preserve_source_locations` had been a stub since it was written — the branch
that would have built the map was a literal `pass`. Everything downstream
guessed instead: the extension re-anchored each lint finding by searching the
file for the name it was about, which works only because most rules report
something *unreferenced*, and cannot work at all for a finding inside an
inlined member.

Building the map turned out to be entirely about the four steps that move a
line — comment blanking and the sequence strip (neither does), continuation
joining (merges), the COPY splice (inserts), the width wrap (splits) — and
tracking an origin through each. Two decisions worth keeping:

**The cache had to carry origins too.** `content_cache` serves a member COPYd
twice from the first expansion; without `content_origins` beside it, the
second copy would have had no map, so the cheap path and the slow path would
have produced different answers. They are evicted together.

**A drifted map must mis-attribute nothing.** `_fit_origins` clamps the list
to the line count at every boundary. Every producer keeps them in step, but
"the map is one short" must never become "this finding is on the wrong line",
which is precisely the failure mode the map exists to end.

### Comments in the listing (`--keep-comments`)

Expansion blanks comments because a `COPY` inside one must not be expanded.
That is right for the lexer and wrong for a listing. The map made the fix
trivial and safe: restore a line's text only when the line is blank in the
expansion AND its origin is a comment line in its origin file, so the pass
cannot touch code, cannot move a line, and cannot resurrect a commented-out
COPY.

### Program units (`.okf/ast-models.md`, `.okf/analysis.md`, `.okf/cli.md`)

`contained_programs` has existed for a long time; nothing used it. Every
analyzer is program-scoped, so a multi-program file was analyzed as its
outermost program with no way to reach the others and nothing saying so — a
contained program came back clean because it was never looked at.

`program_units()` / `find_program_unit()` are the list and the lookup;
`--program NAME` selects on the CLI; `program_units` appears in the
identification header only when there is more than one, so single-program
output is byte-for-byte unchanged. **`lint` is the deliberate exception**: it
lints every unit by default, because lint is the file's diagnostics and a
skipped program reads as a clean one. Its per-rule bookkeeping had to change
with it — one `rules_run` / `failed_rules` entry per rule however many units
it ran on, since the reader needs to know a concern went unexamined, not how
many times the same exception was raised.

Verified end to end against the VS Code extension's live CLI contract suite
(`src/integration/cliContract.test.ts`), which exercises `--keep-comments`,
`--source-map`, lint origins and `--program` through the extension's own
argument builders and output parsers.

## 2026-09-07 — repo audit: two fabricated-answer bugs, four lint false positives

Request: "audit the repo, identify potential bugs or gaps", then "fix all of
the issues". Method was empirical — differential harnesses over the sample and
NIST corpora, round-trip property checks against the encoder/decoder's own
stated invariants, and a standalone reproduction for every finding. Findings
that could not be reproduced from a self-contained program were dropped, and
one was **withdrawn after the fix pass** (see the last section). Full report:
`reports/audit-2026-09-07.md`; regressions in
`tests/regression/test_audit_2026_09_07.py`.

### The shape both HIGH bugs share

Neither was a crash or a wrong number. Both were a component answering a
question it could not answer, in the affirmative, silently — and the
downstream machinery built to catch exactly that being unable to, because it
was fed the same fabrication.

**H1, `analysis/constraints.py`.** `_build_relational_constraint` refuses
`IF WS-IN = WS-LIMIT` when both operands resolve through the layout index.
When the right operand is a *subscripted* reference the index cannot resolve
— `WS-E (IDX)` — it fell through to the "right side is a literal" branch and
used the operand's own source text as the value: `WS-IN eq 'WS-E ( IDX )'`.
The hole was immediately next to a door already closed.

What made it worth a HIGH rather than a note is what happened downstream.
Nothing landed in `unsupported`. `ScenarioCoverage` counted the arm
**targeted**. And the negated arm reduced to "any value != that text", which
every generated value satisfies — so `generators/verification.py`, the module
whose whole purpose is to make a scenario's name a verdict rather than a
label, returned **`verified`**. It re-checks the planned constraints against
the emitted data; when the constraint itself is the fabrication, it is
downstream of the defect, not independent of it. Worth remembering when
reading that module's promises: it catches solver and rendering bugs, not
extraction bugs.

Fix: operands are whitelisted (quoted or numeric) rather than accepted by
default. The `EVALUATE` selector path had the same hole by a different route
— the lexer unquotes a selector before the extractor sees it, so `WHEN "AB"`
and `WHEN WS-OTHER` arrive identical, and "does this value name a real data
item" is the only discriminator left. `SEARCH WHEN` / `EVALUATE TRUE`
selector *text* is likewise pre-unquoted, so it keeps a deliberately looser
test (a bare word may be a literal; something with parens or spaces may not).
That two-mode split is not fussiness: a single strict test rejected every
string literal in those constructs, which one existing test caught.

**H2, `analysis/domains.py`.** `_apply_text` ended in `return True` for every
op it did not model. `True` means "domain still satisfiable", so `solve()`
went on to `pick()` and returned a witness. `IF WS-TXT IS NUMERIC` over a
`PIC X(10)` field returned `'XXXXXXXX'` — for the `THEN` arm, which it fails,
and for the `ELSE` arm, which it passes. Two scenarios distinguished by
exactly that field got byte-identical data.

Fix splits by what is actually true. Class conditions **are** enforceable on
an alphanumeric field (it can hold digits), so `TextDomain` grew
`require_numeric` / `require_alphabetic` and picks accordingly. Ordering ops
genuinely are not expressible on an allow/deny set, so they now return
`Unsatisfiable` carrying a reason that reaches `ScenarioCoverage.details`.
`_apply` returns `str | None` instead of `bool` so that reason survives the
trip. Note the deliberate consequence: an arm that used to produce a scenario
now produces a coverage miss. That is the point — a named scenario is a
claim, and "I could not model this" has to be a miss, not a scenario with a
caveat. One existing test pinned the old behavior and was rewritten to pin
the new one, which is a real behavior change and is called out as such.

### `analysis/unused_variables.py` — four false positives

A lint rule's false positive costs more than a missed finding, and all four
were on ordinary code: `STRING`/`UNSTRING ... DELIMITED BY <identifier>`
(both keep the delimiter in a `delimiters` list that never reaches
`.operands`), a group passed whole to `CALL ... USING` (propagation ran child
-> parent only), and REPORT SECTION `SOURCE`/`SUM`/`CONTROL`.

The REPORT SECTION one is the instructive one: those clauses became parseable
in #196, and a Report Writer program names its fields *only* in report
groups, never in the PROCEDURE DIVISION — so the analyzer reported every
field of every such program dead. The module's own TODO said REPORT SECTION
content was discarded by the parser, which had stopped being true. A stale
"known limitation" comment is how a fixed upstream gap stays broken
downstream.

The CALL fix is deliberately narrow — CALL arguments only, not every group
reference. `MOVE SPACES TO WS-GRP` really does leave `WS-CHILD` never
individually referenced, and silencing that would have bought quiet rather
than accuracy. Pinned by a test that asserts the finding is *kept*.

### `generators/data/views.py` — two disagreements with `layout_offsets.py`

Both modules' docstrings claim they cannot drift. Two cases where they did:

A `REDEFINES` entry wider than what it redefines. `data-items` reserves the
widest slot member; the base view sums only non-redefining fields. COBOL
forbids this below level 01, but compilers accept it and real copybooks
contain it — and `RecordView.length` is what `RecordDecoder` cuts
fixed-length records at, so the file got framed at the wrong stride and every
record after the first was garbage. Added `RecordViews.framing_length`
(`max(base.length, widest overlay end)` — identical for every conforming
layout) and a caveat. Deliberately did *not* rework `_place` into full slot
semantics: that means a second walk duplicating `flatten_record`'s OCCURS
expansion, which is precisely the drift the module exists to prevent, for a
construct no conforming compiler accepts.

`offset_ambiguous` after an `OCCURS ... DEPENDING ON` table. The flag existed
and only overlays could ever carry it — the base view was constructed with it
defaulted — so `--list-views` presented a maximum-length guess as a fact for
exactly the fields `data-items` reports as `byte_offset: null`.

### CI ran no tests at all

The largest process gap, and the cheapest fix. `build` installed `.[dev,fast]`
— pytest included — and never invoked it. 9,396 tests and a
`--cov-fail-under=90` floor went unenforced on every push and PR. `.okf/tests.md`
described a `test` job gated on `workflow_dispatch`; no such job was ever in
`ci.yml`.

pytest now runs in `build`, **after** `build_ext`, so CI exercises the Cython
extensions rather than the pure-Python fallback it was building and never
running a line through — plus a separate `coverage` job on a pure-Python
install, which is where the 90% floor is enforced.

That split is not fussiness, and the reason cost an hour: coverage.py cannot
see into a compiled Cython extension, so once `build_ext` has run, the
pure-Python bodies those extensions shadow read as unexecuted. Same suite,
same commit: **54.32%** with extensions built, **91.76%** without. Putting
the gate in `build` would fail on the build step rather than on the code.

Worth recording how that nearly became a phantom finding. Comparing a
coverage number taken *without* extensions (a 1,096-test subset, 59.74%)
against one taken *with* them (the full suite, 54.33%) looks like a subset
out-covering its own superset — arithmetically impossible, and it reads as
data loss in the tooling. It was written up as an open finding, complete
with a ruled-out list, before the pure-Python full run came back at 91.76%
and showed the two numbers had never been comparable. The lesson is narrow
and worth keeping: check which build produced a coverage number before
reasoning from it. `reports/open-findings.md` carries this as an operational
note rather than a defect.

### One finding withdrawn

The audit's LOW list claimed `COMPUTE A = (1 + 2)` without a terminating
period reports "unbalanced parentheses". It does not. The reproduction
generated a 124-character source line, and `normalize_fixed_format` correctly
truncates fixed-format source at column 72 — cutting the closing parens off,
so the expression really was unbalanced and the diagnostic was right. The
defect was in the audit harness. Recorded rather than quietly deleted,
because an audit finding that turns out to be wrong is worth the same
scrutiny as one that turns out to be right.

## 2026-09-07 — the decoder direction, and DCLGEN cross-checking

Request: the "data and records" gap — this package could *encode* a record
image and could not read one back, which is backwards from what anyone
actually has. People have a file: a VSAM extract, an EBCDIC flat file, a tape
image someone FTP'd off z/OS. None of them self-describing; all of them keyed
only by the copybook compiled against them. Plus the DCLGEN check that was
sitting one function call away from already-parsed data on both sides.

### `generators/data/decoding.py` + `generators/data/views.py`

The inverse of `encoding.py`, backing `cobol-parser decode`. Four decisions
worth keeping:

**Offsets come from the encoder's own arithmetic, not a second model.** A
`RecordView`'s field offsets are a running sum of `FieldSpec.storage_size` —
exactly what `encode_record()` does implicitly when it concatenates. Any
other derivation could drift; this one cannot, and
`test_base_offsets_match_the_encoded_record` checks it against real encoded
bytes rather than a hand-written offset table.

**REDEFINES became a first-class *view* rather than a flag.** A generator can
duck the question (it picks one reading and writes it); a decoder cannot,
because only the program knows which meaning applies to the record in front
of you. So `build_record_views()` returns the base layout plus one
`RecordView` per redefinition, each rooted at the offset of the item it
redefines, and switching overlay is a re-read of the same bytes rather than a
re-parse of the copybook. `flatten_record(..., ignore_root_redefines=True)`
is what makes an overlay flattenable at all; only the *root's* own clause is
exempted, so a nested REDEFINES still excludes its fields and a view stays a
contiguous run of bytes.

**Framing is a property of the file; trimming is a property of the format.**
Two bugs found in development, both by the round-trip test rather than by
inspection:
* Framing off the *chosen* view walks the file at the wrong stride — a
  200-byte record read through a 20-byte redefinition is still 200 bytes.
  Framing now always uses the base view.
* Applying `OCCURS DEPENDING ON` trimming under `RecordFormat.FIXED`
  produces silent garbage from the table onward: RECFM=F reserves every
  occurrence whatever the counter says, so trimming skips bytes that *are*
  in the record. `decode_bytes` resolves the format once and passes
  `trim_tables=fmt.is_variable`.

**Read more conventions than you write; report what you cannot read.** The
encoder writes one sign convention per charset because there was one compiler
to verify against. The decoder accepts every EBCDIC sign nibble, GnuCOBOL's
ASCII zone, *and* the `{ABC`/`}JKL` overpunches a transcoded EBCDIC file
carries — a decoder that choked on those would be useless on half the files
in the wild. But a sign is only honoured in the position the encoder would
have put one: a `D` zone mid-field is a corrupt digit, not a negative number,
and calling it a sign would flip a value that is merely unreadable. Bytes
that are not what the PICTURE says get `DecodedField.error` and a best-effort
value, never a silent zero — a copybook applied to the wrong file then shows
up as a wall of errors, which is the single most useful thing the module can
tell you.

The round trip is the load-bearing test: `encoding.py`'s expected bytes are
ground truth from GnuCOBOL, so a decoder that reproduces the generated CSV
from those bytes is verified against a real compiler at one remove. Two
columns are exempt by construction and the docstring says why (a float comes
back in shortest form; `FILLER` comes back empty because the encoder
deliberately discards it).

### `analysis/dclgen_check.py`

`DclgenChecker` — every `:host-var` graded against the DCLGEN `DECLARE TABLE`
column of its name, backing `cobol-parser dclgen-check` and lint's
`dclgen-check` rule. It resolves nothing itself: `HostVariableResolver`
already pairs a host variable with its DATA DIVISION item, and
`DeclareTableStatement.columns` already carries the DB2 side with
`db2_type_to_cobol_pic()` applied, so the checker only says whether a pair
agrees — and a fix to the type mapping fixes the check too.

**The name normalization is the whole feature.** DB2 columns are underscored
(`CUST_ID`); the host variables DCLGEN generates are hyphenated (`CUST-ID`),
because `_` is not a COBOL data-name character. The first draft reused
`HostVariableResolver`'s own verbatim column index and reported that *no*
column matched *any* host variable — i.e. it checked nothing while looking
like it had, on a program with five real mismatches in it. Fixed with
`_normalize()` in the checker rather than by changing the resolver's
semantics under its other consumers, and pinned by
`test_an_underscored_column_is_matched_to_its_hyphenated_host_variable`.

Severity is graded by what the mismatch costs at runtime, not by how easy it
is to detect: a dropped decimal place (`DECIMAL(9,2)` into `PIC S9(7)V9`) is
an error because every row is silently rescaled with no status code; an
over-long host variable is *info* because it only wastes space. A `category`
finding stands alone — every later check would be comparing digits against
characters, so four confusing restatements are suppressed. What the checker
cannot compare it says so about per variable (`report.unchecked`: no
DECLARE TABLE, a VARCHAR group binding, an opaque type), so a quiet report is
never mistaken for a checked one.

## 2026-09-07 — `lint`: every analyzer in one pass, as one list

Request: "more features to help devs". The gap this closes is not a missing
analysis — it is that answering "what is wrong with this program" meant
running seven subcommands, each re-parsing the same file in its own CPython
process, then learning seven different JSON shapes to merge into one list.
Both consumers who want that list (a CI gate, an editor's diagnostics) were
paying for it.

`cobolparser/analysis/lint.py` — `LintAnalyzer` — runs the selected rules over
**one** already-parsed AST and flattens their reports into a single stream of
`LintFinding` (`rule`, `severity`, `message`, `location`, `symbol`, `kind`),
ordered by source position. No analysis is re-implemented: every rule is a
mapping from an existing analyzer's report, so a fix in one of them reaches
lint output with no change here. Rule ids are the analyzer *subcommand names*
rather than a second vocabulary.

Three decisions worth keeping:

- **Severity is per finding.** Analyzers that already grade themselves keep
  their grading (MOVE ERROR/WARNING, recursion HIGH/MEDIUM, complexity
  rating); the rest carry a fixed severity per rule. The `_SEVERITY_*` tables
  are the whole policy, so changing a judgement is a one-line edit rather than
  a hunt through mapping code.
- **A quiet report is not a clean program.** `caveats` carries what an
  analyzer could not check (MOVE operands whose category never resolved — the
  `unresolved_count` that already existed and had no aggregate home), and
  `failed_rules` records a rule that raised, costing only its own findings.
  Both are structural, not prose, so a consumer cannot render "no problems"
  for a file that was largely unexamined without ignoring a field.
- **Exit code 3 for findings, not 1.** `--fail-on error|warning|info` gates
  CI. `1` already means "the run failed" across this CLI (and `2` is taken
  twice over: "recovered-but-errored parse" for `parse`, and argparse's own
  usage error for a rejected flag on any subcommand); reusing `1` would make
  a gate unable to tell a program with problems from a lint that never ran.
  `--fail-on` defaults to `never`, so findings alone never change the exit
  code. All four codes verified by running them, not assumed: missing file
  `1`, unknown `--rule` `2`, `--fail-on` hit `3`, otherwise `0`.

Also: findings identical in every visible field collapse to one.
`IOSequenceAnalyzer` reports one READ-before-OPEN once per control flow path
that reaches it (verified on `tests/samples/employee_processing.cbl`: the same
line, twice) — two facts about the graph, one thing to fix, and two identical
squiggles in an editor. Collapsed here, in the aggregate view, rather than
pushed down into the analyzer, whose per-path report is correct for its own
consumers.

`--copybook-path` does double duty: it expands COPY members so MOVE operands
resolve, *and* it lets lint grade a copybook-sourced unused item as info
rather than warning, reusing the unexpanded-parse set difference
`unused-variables` already uses for the same question.

New: `cobol-parser lint` (`--rule`, `--min-severity`, `--fail-on`,
`--format json|text`), `LintAnalyzer` / `LintReport` / `LintFinding` exported
from the top-level package. See [analysis.md](analysis.md) and [cli.md](cli.md);
`tests/unit/analysis/test_lint.py`, `tests/unit/cli/test_lint_subcommand.py`.

## 2026-09-05 (variable-length files, part 2: FD RECORD VARYING)

Follow-up to the same request, after being pointed at
mainframestechhelp.com's "reading a VL PS file sequentially" example. Part 1
below handled `OCCURS ... DEPENDING ON`; that example uses the *other*
mechanism, and it is the more common one:

```cobol
FD  EMPFILE
    RECORD VARYING FROM 47 TO 80 CHARACTERS
           DEPENDING ON EMPREC-LEN
    RECORDING MODE IS V.
01  EMP-RECORD80.   *> a flat record. No table. Nothing to trim.
```

`EMPREC-LEN` is a WORKING-STORAGE item, so **nothing in the record says how
long the record is** -- the length travels in the RDW. An ODO walk sees a
fixed 80-byte record and cannot do better.

* **`layout.VaryingLength`** — the FD's declared range.
  `from_fd_clauses()` reads what `data_file_description.py` *already*
  parsed into `fd_clauses["record"]` (`{varying, min, max, depending_on}`)
  and attaches to the 01 as metadata. Nothing consumed it before this; the
  parsing side needed no change at all. `RECORD CONTAINS 47 TO 80` is the
  same declaration without the keyword and parses identically.
* **The length is drawn at *generation* time, not at encode time.** One per
  row, uniform across the range, from the same seeded RNG the values came
  from — so a seed reproduces record *lengths* as exactly as it reproduces
  their contents, and `encode_record` stays a pure function. The draws
  happen *after* the value rows, so a record with no range draws nothing and
  its bytes are unchanged.
* **`encode_record(..., data_length=N)`** cuts the body to N bytes, mid-field
  if that is where it falls — which is exactly what a program reading
  `EMP-RECORD80(1:EMPREC-LEN)` sees. `--format hex` marks the fields past the
  cut as `(past record length)` rather than dropping them.
* **A whole program needs no flag; a copybook needs one.** The FD only exists
  in a program, and `gen-data` accepts both. `--record-varying MIN:MAX`
  (`DataGeneratorOptions.record_varying`) covers the copybook case and
  overrides the FD when both are present.
* **`--record-format`'s argparse default became `None`**, resolved to `fixed`
  later. Without that, an explicit `--record-format fixed` was
  indistinguishable from the default, so `--record-varying` could not imply
  `auto` without trampling a caller who really did want fixed.
* **`maximum` is clamped to the record's own length.** An FD promising more
  than its 01 can hold cannot be honoured by padding — those bytes were never
  declared.
* **Both mechanisms at once**: the table decides, the FD range is not applied
  on top, and a caveat says so. A Copilot review on PR #204 caught that the
  code did *not* actually do this -- `encode_record` cut the ODO-trimmed body
  to the FD-drawn length anyway, `row_record_length` and `hex_dump` reported
  as if it had, and `minimum_record_length()` preferred the FD floor. Fixed at
  the source (the generator draws no length for a record a table already
  sizes, so `declared_lengths` is `None` and everything downstream agrees for
  free) *and* defensively in `_effective_data_length()`, for a direct caller
  who passes both. The same review found `_link_odo_counters` collapsing
  disjoint bounds to the larger *minimum* -- the over-counting direction its
  own docstring calls unsafe -- where the tightest maximum was meant.

See "FD `RECORD VARYING`" in [generators.md](generators.md);
`tests/unit/generators/data/test_variable_length.py::TestFdRecordVarying`
works the linked example end to end.

## 2026-09-05 (variable-length record files: OCCURS DEPENDING ON honoured, RDW written)

Asked to generate mock data for **both variable- and fixed-length files**.
Fixed-length was all that existed: a copybook with an `OCCURS ... DEPENDING
ON` table got its table written at the maximum and a caveat on stderr saying
a real record would be shorter. That caveat was the feature request.

* **`RecordFormat` (`generators/data/encoding.py`)** — `fixed` (RECFM=F/FB,
  the default and byte-identical to what the previous release wrote),
  `variable` (RECFM=V/VB: only the occurrences the row's own counter names,
  behind a 4-byte RDW), `variable-bare` (the same trimmed records with no
  RDW), `auto` (variable iff the layout has an ODO table). On
  `EncodingOptions.record_format`, resolved by `resolved_format(specs)` —
  the same shape `Endian.AUTO`/`resolved_endian` already had. CLI:
  `gen-data --record-format`.
* **The RDW is part of the format, not a separate switch.** `LL LL 00 00`,
  big-endian, length *including the four RDW bytes*, whatever `--endian` and
  `--charset` say — it is written by the access method, not by the program.
  Without it a stream of differently-sized records has no way to say where
  one ends, so offering trimming without framing as the default would
  produce an unreadable file. `> 0xFFFF` raises rather than truncating the
  length field: that record needs RECFM=VS, which is not generated.
* **Three pieces make trimming work, none of them a second flattening pass.**
  `FieldSpec.odo_controls` (a `layout.OdoControl` per ODO dimension: the
  counter, *which subscript position* it governs, and the bounds — so nested
  tables fall out for free); `FieldSpec.odo_counter_bounds` on the counter,
  stamped by a post-pass because a counter is declared *before* the table
  that depends on it; and `layout.present_indexes(specs, row)`, whose
  order-preserving filter is what makes a field declared *after* the table
  shift up into the space the absent occurrences would have taken.
* **A real bug found on the way in: the generated counter was never bounded
  by the table.** A `PIC 9(4)` counter for `OCCURS 1 TO 50` could generate
  8 731 — a record no program could read, in the fixed-length output that
  already shipped. `ValueFactory` now draws the counter from the table's own
  `OCCURS min TO max`. Drawing across that range rather than generating
  freely and clamping is also what makes a variable file *vary*: clamping
  would pin nearly every row to the maximum. A declared `VALUE`/level-88
  still wins when it names a count the table can hold.
* **`max_times` is what was flattened, not what was declared.** `max_occurs`
  and the hard occurrence cap can both stop the walk short, and a counter
  allowed to name occurrence 50 of a table flattened to 10 would describe
  bytes no `FieldSpec` covers.
* **Lengths are now stated, not left to be inferred.**
  `minimum_record_length()`, `row_record_length()`,
  `GeneratedDataset.record_lengths()` / `.is_variable_length`; `--format
  record` prints the range to stderr (raw bytes have no header to carry an
  LRECL) and `--format hex` puts the RDW on a row of its own so field
  offsets stay true.
* **Additive schema change**, no `bundle_version` bump: `FieldSpec.to_dict()`
  gained `odo_controls` and `odo_counter_bounds`. `examples/fixtures/
  FIXTUREDEMO.bundle.json` was regenerated for the two new keys (no
  generated value changed — FIXTUREDEMO has no ODO table); **the copy in the
  sibling mocky-mock repo needs the same refresh.**

See "Fixed- and variable-length records" in [generators.md](generators.md);
`tests/unit/generators/data/test_variable_length.py`,
`tests/unit/cli/test_gen_data_cli.py::TestRecordFormatFlag`.

## 2026-09-05 (repo audit: two silent wrong-answer bugs, one rotten corpus)

A deep audit of the repo, starting from a green suite (9,015 passing) and
looking for what the tests were not asking. Three findings, all fixed.

* **`CobolDataItem.calculate_size()` had drifted from `storage_size` in six
  ways** and now defers to it. `BINARY`/`COMPUTATIONAL` reported 9 bytes
  instead of 4, `COMPUTATIONAL-3` 9 instead of 5, `COMP-1`/`COMP-2`/`INDEX`
  **0** (their usage branches sat behind an `is_elementary_item()` guard that
  requires a PICTURE, which none of them has), a group added its REDEFINES
  children instead of sharing their storage, and a group's own OCCURS
  multiplier was never applied, and a DISPLAY `SIGN IS SEPARATE` item never
  got its extra byte. Published as `calculated_size` on every data item's
  `to_dict()` and as `gen-data --list-records`' record `size`. See
  [ast-models.md](ast-models.md).
* **`DeadCodeAnalyzer` reported no dead code at all for the most common COBOL
  program shape.** The 2026-08-11 fall-through fix gated on
  `_referenced_names`, which includes PERFORM targets -- but a PERFORM
  returns at the end of its range rather than running on, so every paragraph
  after a performed one got a fall-through edge that cannot happen. Split out
  `_fallthrough_sources` (entry point, GO TO/ALTER targets, ENTRY
  paragraphs, and whatever they fall into) from plain reference-marking. See
  [analysis.md](analysis.md).
* **The sample corpus itself was corrupt, and nothing was checking it.**
  `tests/test_all_samples.py` collected zero tests despite being documented
  as the sample smoke test; 32 lines across 13 samples ran past column 72 and
  were being silently truncated mid-identifier. Both fixed. See
  [tests.md](tests.md).

Deliberately *not* changed, and recorded as a known divergence:
`ProgramFlowAnalyzer.build_fall_through_edges` still emits a `FALL_THROUGH`
edge out of a PERFORM target, so its `unreachable_nodes` under-reports the
same way `DeadCodeAnalyzer` used to. Changing the CFG's shape would move
flowcharts, `ScenarioPlanner` arm reachability and `TechnicalDebtAnalyzer`
at once; out of scope for an audit fix.

## 2026-09-05 (record images: COMP-3/COMP-5/COMP-1/2 written as real bytes)

Asked whether the copybook mocking feature — `mockymock.generateData`
("Generate Data from Copybook") in the VS Code extension, which shells out
to `gen-data` — could support `COMP-3`/`COMP-5` and friends. It already
*generated values* for them; what it could not do was emit them as the bytes
a program actually reads, and its reported `size` was the PICTURE's
character count rather than the storage width.

* **`generators/data/storage.py` (new)** — the package's single authority on
  how many bytes a data item occupies. Extracted rather than added because
  the arithmetic already existed twice (in `layout_offsets` and implicitly in
  `CobolDataItem.calculate_size`) and both copies were wrong in the same two
  places. `layout.py`, `layout_offsets.py` and `encoding.py` all defer to it
  now, so a record image's field widths cannot drift from the offsets
  `data-items` reports.
* **Two real sizing bugs fixed for every caller at once.** `USAGE INDEX`
  carries no PICTURE and was therefore sized as **zero bytes**, silently
  collapsing the byte offset of every item after it in the record. A DISPLAY
  item with `SIGN IS SEPARATE` was under-reported by one byte.
* **`generators/data/encoding.py` (new)** — display value → storage bytes.
  `EncodingOptions`, `encode_field`/`encode_record`, `hex_dump`, and
  `encoding_caveats`. Reached via `GeneratedDataset.to_records()` /
  `.write_records()` / `.to_hex_dump()` and `gen-data --format record|hex`.
* **Every encoding is verified against a compiler, not against a manual.**
  GnuCOBOL was installed, a probe program declaring one item per storage
  class was compiled, and its raw WORKING-STORAGE bytes read back; the probe
  and its output are reproduced in
  `tests/unit/generators/data/test_encoding.py`'s module docstring. This is
  what caught the version of this work that shipped `COMP-5` and both float
  usages as big-endian: they are **host order** — "native binary" is the
  whole point of `COMP-5` — while `COMP`/`COMP-4` really are always
  big-endian. A full round trip (generate a record file → read it from a
  compiled COBOL program → DISPLAY every field) reproduces the CSV exactly,
  for both a COMP-heavy copybook and a realistic one with FILLER, OCCURS,
  a level-88, `SIGN IS SEPARATE`, and signed zoned decimal.
* **`DataGeneratorOptions.for_record_image()`** — the CSV-shaped defaults
  (FILLER skipped, OCCURS capped) would each put a *hole* in a record image
  that still looked plausible, so the record formats force the byte-complete
  layout and print a note to stderr rather than letting `--include-filler` /
  `--max-occurs` look silently ignored.
* **Deliberately not built.** `SYNCHRONIZED` alignment: modelling slack bytes
  would give the repo two contradictory offset models, since
  `layout_offsets` is unaligned throughout — reported as a caveat instead.
  z/OS hexadecimal floating point: `COMP-1`/`COMP-2` are IEEE 754, also
  reported. A third zoned-sign convention (EBCDIC signs transcoded to ASCII
  as `{ABC`/`}JKL`): no compiler here to verify it against, and both real
  destinations are already covered by the charset-derived pair. `COMP-5`
  values are still generated within their PICTURE's digit count rather than
  its full binary range — widening it would churn every existing seed's
  output and produce literals that `TRUNC(STD)` would truncate in
  mockymock's own `MOVE`-based splice.
* **`FieldSpec` gained `storage_size`, `sign_clause`, `synchronized`,
  `occurs_depending_on`** — additive keys, so `bundle_version` stays `1`.
  `examples/fixtures/FIXTUREDEMO.bundle.json` was regenerated (verified
  purely additive: identical once the four new keys are stripped) and
  re-copied to mocky-mock, whose golden `.cut` test reads it.

## 2026-09-05 — A stale `_data_fast` build no longer costs the DATA DIVISION

Reported on Python 3.14: a compiled `_data_fast` accepting 18 arguments where
`data_clauses.parse_data_item` passes 19, so every COBOL file with a DATA
DIVISION failed to parse, degrading to a near-empty AST.

Root cause is drift between two separately compiled halves, not a bad `.c`:
the checked-in `_data_fast.c` was verified in sync with `_data_fast.pyx`
(regenerated, argument tables compared — same for `_lexer_fast` and
`_preprocess_fast`), so the 18-parameter binary can only have come from a
stale *build* — an in-place `.so` older than the tree, a cached `build/`, or
an installed wheel shadowing the source.

What made a build problem into a parse problem: the fast-path call site was
unconditional and positional, guarded only by `try/except ImportError` at
import. A present-but-mismatched extension sails past that guard and raises
`TypeError` from the middle of every data-description entry; `parser.py`'s
broad `except Exception` recorded it as a generic error at line 1 column 1 and
recovered by abandoning the division — losing the DATA *and* PROCEDURE
divisions and reporting only an argument count.

Fix: `_data_fast_usable()` probes the compiled helper once at import with an
empty token list (the clause loop never runs, so it returns `pos` without
reading any other parameter). On mismatch the fast path is disabled and
`logger.warning` names the rebuild; a missing extension stays silent, since
that is a normal pure-Python install. Verified against a real compiled
extension, and fast-path vs fallback ASTs compared byte-for-byte across the
94-file sample + shamrice corpus (zero mismatches).

Two self-review findings, both fixed before merge:

- The report was first written with `warnings.warn`, which at import time
  turns a stale build into an `import cobolparser` failure under `-W error`
  (reproduced) — inverting the guard's purpose. Now `logger.warning`.
- `_DATA_FAST_ARG_COUNT` is a third copy of the arity, and nothing checked it
  against the *literal call site* — only against the compiled extension. Bump
  the constant and the `.pyx` while missing the call and the probe passes
  while the real call raises. A second test now counts the call's arguments
  from `data_clauses.py`'s AST.

Not changed: `parser.py`'s division-level recovery still turns an unexpected
exception into a generic line-1 error and drops the division. That is the
reason this bug read as "empty AST" rather than "stale extension", but
narrowing it touches `COLLECT_ALL` semantics for every division parser and is
its own change.

Also not changed: `_lexer_fast` and `_preprocess_fast` keep the bare
`try/except ImportError`. Same two-halves structure, materially different
blast radius — verified, not assumed. Drift there does *not* "fail loudly"
(an earlier draft of this entry said so, wrongly): the `TypeError` is caught
by `parser.py`'s top-level safety net at `_parse_core` and becomes
`ParseError("Parser error: ...")` with `ast=None`. The difference that
matters is that every parse then returns `ast is None` / `success False` —
a total, unmissable failure — where `_data_fast` returned a *partially
populated* AST (IDENTIFICATION present, program name set) that a caller
reading `result.ast` would consume as real. `normalize_fixed_format`'s
non-`lines` parameters are also keyword-only, so appending one is backward
compatible by construction. Probing the lexer subclass would mean
constructing a lexer and calling internals, which is not the cheap one-call
check `_data_fast` allows.

See "Signature-drift guard" in [lexer.md](lexer.md);
`tests/regression/test_data_fast_signature_drift.py`.


## 2026-09-04 (level-88 branch seeding fixed; per-row witness groundwork)

Reported from a real `mockymock generate --with-data` run: scenarios named
for a branch arm were seeded with data that could not reach it.

* **`analysis/constraints.py`** — a bare level-88 condition-name constraint
  read `FieldSpec.condition_values`, the *union* of every 88 under the parent
  field, so `WHEN TYPE-P-BAL-M` and `WHEN TYPE-P-BAL-F` produced identical
  `in_set ("05", "09")` constraints and the solver picked `"05"` for both.
  Now scoped through the new `ProgramLayoutIndex.condition_values()`, which
  keeps each 88's own VALUEs alongside the existing parent mapping. Both
  lookups stay — they answer different questions, and the value factory still
  wants the union.
* **`analysis/constraints.py`** — `WHEN OTHER` was hardcoded to `[]`
  ("unconstrained") by v1 design. Combined with the value factory drawing an
  unconstrained level-88 field from its own `condition_values`, the OTHER
  scenario was *deterministically* unable to reach its own arm. Now negated
  into one `not_in_set` for the single-shared-field shape, with a recorded
  reason when the shape needs a disjunction instead.
* **`analysis/domains.py`** — that negation immediately hit a second wall: a
  `not_in_set` over every declared 88 value emptied the `EnumDomain` and
  returned `Unsatisfiable`. The enum is now a preference with a
  `_picture_domain()` fallback, so `IF NOT TYPE-M` still yields the other
  declared value while `WHEN OTHER` yields a third value the PICTURE admits.
  `_apply_numeric` gained explicit `in_set`/`not_in_set` handling so the
  fallback path cannot produce a witness violating a set op.
* **`generators/scenarios.py` / `program_fixtures.py`** — added
  `PlannedScenario.row_witnesses` (per-row pinning). Nothing populates it;
  it removes the *expressibility* blocker for cross-record correlation, whose
  remaining analysis is designed in
  `docs/plans/2026-09-04-cross-record-correlation-design.md`. `FixtureBundle`
  untouched, `BUNDLE_VERSION` unchanged.


## 2026-09-04 — Scenarios verify themselves, and carry their path condition

A scenario's *name* was a claim nothing checked. Two changes, one root cause:

- **[analysis]** `BranchConstraints.enclosing` — every decision point now
  records the `(branch_id, arm_id)` chain whose arms must all be taken for it
  to be reached. `_walk_list` threads it down through
  `_nested_statement_lists`, which pairs each nested statement list with the
  arm id it sits under; the ids match the keys registered in `arms`, by
  construction, which is what lets `ScenarioPlanner` join on them. A
  non-branch nesting (`AT END`, `ON EXCEPTION`, an inline `PERFORM` body)
  contributes nothing — it is a path condition in the general sense but is
  not modeled as a branch arm here, and an invented id would join to nothing.
- **[generators]** `ScenarioPlanner._path_constraints` folds those enclosing
  conjuncts into a targeted arm's own before solving. This was the biggest
  single source of scenarios whose data never reached their own arm: on
  `IF INV-QTY > 500 / IF INV-TYPE = "AB"` the inner arm's scenario pinned
  `INV-TYPE` and left `INV-QTY` to chance. An arm that becomes unsatisfiable
  once its path is added is now `missed` with that reason; an enclosing arm
  that was never modeled becomes a `PlannedScenario.path_gaps` entry rather
  than silence.
- **[generators]** New `generators/verification.py` +
  `Scenario.verification`: after generating, re-read the scenario's OWN rows
  and re-check every planned conjunct against them. Deliberately independent
  of the solver — it evaluates against the concrete rendered strings a mock
  will move into the program, so a solver bug, a rendering bug, and a witness
  that never reached any fixture all surface as findings. `unknown` is a real
  answer: `IF WS-INPUT > 0` on a `PIC X(10)` field cannot be decided from a
  rendered string (IBM COBOL only allows that ordering comparison when the
  alphanumeric operand is integer-like), and stamping it "verified" would be
  the same silent optimism this whole change removes.

Measured on the repo's own corpus (shamrice + tests/samples): 115 verified,
16 unverified across two real finding classes — an ACCEPT-fed text field
compared to a numeric literal, and enclosing arms with no modeled condition.
Additive to the bundle (`bundle_version` stays 1); `gen-fixtures` reports on
stderr, and mockymock renders the reasons as a `*> UNVERIFIED:` comment.

## 2026-09-04 — Review fixes on the path-folding machinery (PR #198)

Three findings from Copilot's review, all verified against the code before
changing anything, plus one found while verifying them:

- **[generators]** An OR-split enclosing arm was never folded.
  `_register_variants` registers `THEN#1`/`THEN#2`/... and no bare `THEN`
  for a condition containing an OR, while `BranchConstraints.enclosing`
  names the base arm id -- so the join missed every such arm. Replaced
  `_path_constraints` with `_path_options` (alternatives per enclosing arm)
  + `_solve_with_path` (try combinations, keep the first that stays
  satisfiable). Trying rather than fixing on the first disjunct is
  load-bearing: for `IF A = 100 OR A = 200 / IF A = 200`, the first disjunct
  makes the set unsatisfiable and would report a reachable arm as missed.
- **[generators]** `_merge_candidates` dropped a merged-in candidate's
  `path_gaps` (found while building the repro for the above). That turned an
  unpinned enclosing arm into a silently `verified` scenario -- the exact
  false positive the gap list exists to prevent.
- **[analysis]** SEARCH's `AT END` is a modeled arm (`_extract_search`
  registers `arms["AT_END"]`) but reached the walk through
  `_NESTED_STATEMENT_ATTRS` untagged, so a branch nested under it lost its
  enclosing chain and could read `verified` without its data establishing
  that the search found nothing. New `_ARM_BEARING_ATTRS` tags it.
- A test-name typo (`branchs` -> `branches`).

All four pinned by tests in `test_scenario_verification.py`.

## 2026-09-02 (REPORT SECTION parsed; XML/JSON handler bodies and PROCESSING PROCEDURE structured)

Driven by the sibling mocky-mock repo's "every COBOL dependency mockable"
work: its fail-closed gate refuses any `ParseResult.warnings` entry, so the
REPORT SECTION "not supported" warning made every Report Writer program
unmockable, and XML PARSE's text-only handler/PROCESSING PROCEDURE clauses
hid statements and a flow edge from it.

* **Added:** REPORT SECTION parsing -- `RD` clause capture in new
  `parsers/divisions/data_report_description.py`, report-group clauses
  (TYPE/LINE/NEXT GROUP/COLUMN/SOURCE/SUM/GROUP INDICATE/PRESENT WHEN) in
  `DataItemClauseParser.parse_data_item(report_group=True)`, anonymous
  `01 TYPE IS ...` entries, `metadata["rd_report_name"]` /
  `["rd_clauses"]` / `["report_clauses"]`. REPORT left
  `_UNSUPPORTED_SECTION_HEADERS`; the skip warning is gone. See
  [parser.md](parser.md), [ast-models.md](ast-models.md).
* **Added:** `XmlJsonStatement.processing_procedure` /
  `.processing_procedure_thru`, `.on_exception` / `.not_on_exception`
  (real statement lists; `clause_text` no longer carries handler text);
  `END-XML`/`END-JSON` in `SCOPE_TERMINATORS`.
* **Tests:** `tests/unit/test_report_section.py` (+11),
  `tests/unit/test_xml_json_structured_clauses.py` (+5); two existing
  assertions on flattened handler text updated. See [tests.md](tests.md).


## 2026-09-02 (Statement-coverage audit: every COBOL verb parses; silent-drop fixes)

Asked: are there silent gaps or drops of statements, and is every COBOL
statement supported? Answered with a per-verb probe and a 540-file corpus
sweep (statement-drop warnings ~370 -> 30, the rest being malformed
samples / unexpanded COPY / screen extensions).

* **Fixed** (all detailed in [parser.md](parser.md)'s "Statement-coverage
  audit (2026-09-02)" section): `ExecCicsStatement`/`ExecImsStatement`
  invisible to `get_all_statements()` (now `CobolStatement`s); `GO TO`
  target on the next line silently lost; optional `ON`/`AT` in SIZE ERROR /
  EXCEPTION / OVERFLOW / AT END / END-OF-PAGE phrases leaking handler
  bodies; MOVE silently eating foreign tokens; literals spelled like verbs
  truncating conditions; CALL handlers swallowing the enclosing ELSE /
  END-IF / END-PERFORM; `,`/`;` separators; XML GENERATE `SUPPRESS`;
  `EQUAL TO` connective in condition operands; a dozen NIST clause forms.
* **Added:** 22 statement parsers (Report Writer INITIATE/TERMINATE/
  SUPPRESS; Communication Module SEND/RECEIVE/ENABLE/DISABLE/PURGE; OS/VS
  EXHIBIT/EXAMINE/TRANSFORM; ENTER, NOTE, CHAIN; READY/RESET TRACE, SERVICE
  LABEL/RELOAD, TITLE; COBOL 2002 RAISE/RESUME/VALIDATE) with AST nodes in
  new `models/statements/report_writer.py`, `communication.py`, `legacy.py`
  (+ `control.py` / `data.py`). `UNSUPPORTED_VERBS` is down to
  `EXECUTE`/`GOTO`/`RECOVER`. See [ast-models.md](ast-models.md).
* **Tests:** `tests/unit/test_extended_verb_parsers.py` (+58) and
  `tests/regression/test_statement_coverage_audit_2026_09_02.py` (+70,
  including a 20-program NIST no-drop-warning guard); `test_tier3`/`tier5`/
  `tier7` and `test_open_findings_high_regressions.py` now use `EXECUTE` as
  the remaining unsupported-verb example and assert nodes for the verbs
  that gained parsers; `test_procedure_registry_dispatch_order.py` and
  `test_swallow_sweep.py` extended for the 22 parsers.

## 2026-08-28 (Embedded double quotes in re-emitted literals)

User-reported from mockymock's real-world corpus: `mockymock run` on a
~31k-line CICS/IMS program failed to compile with a bogus
`invalid symbol '%'` error. Root cause was here, not there.

* **Fixed** (detailed in [parser.md](parser.md)'s "Literal Re-Quoting"
  section): every site that re-emits a decoded `STRING_LITERAL` as COBOL
  source wrapped it in `"..."` without doubling an embedded `"`. CICS's
  `DFHAID` copybook declares `DFHTRIG PIC X VALUE IS '"'` -- content: one
  quote character -- which round-tripped to three quote characters, an
  unterminated literal that desynchronizes `cobc`'s tokenizer for the rest
  of the program. New zero-dependency `cobolparser/_literals.py::
  quote_literal()` now backs `parse_value_clause` (plain and `VALUE ALL`
  branches), `environment_select.py`'s `ASSIGN TO`, and the MOVE/DISPLAY/
  WRITE literal operands. Level-88 values are untouched -- they are stored
  undelimited, a different convention.
* **Verified** against real GnuCOBOL 4.0: the emitted four-quote form
  compiles and prints the quote character; the old three-quote form does
  not compile. Pinned by
  `tests/regression/test_embedded_quote_literals.py` (5 cases, including a
  parse -> emit -> re-parse round-trip).

## 2026-08-24 (Residual corpus findings: NEXT SENTENCE, PERFORM WITH TEST newline tolerance, DISPLAY subscript fold, WRITE/READ/START qualifier fold, bare-terminal-period overflow gate)

A follow-up sweep against a 105-program real-world corpus (88 OK / 17
refused, all refusals `PARSE_WARNING`) found six causes, four of them
worth code fixes; the other two (an apostrophe inside a single-quoted
literal closing the string early, and the general lenient
"closed-at-end-of-line" behavior for a genuinely unterminated string) are
inherent context-free-lexer ambiguity already handled as leniently as
possible (warn, don't hard-fail) and were left alone.

* **Fixed** (all five detailed in [parser.md](parser.md)'s "Residual
  corpus findings" section and [preprocessing.md](preprocessing.md)'s
  "Bare terminal period does not warn" section):
  - `NEXT SENTENCE` had no statement parser at all -- new
    `NextSentenceStatementParser` (`simple_statement_parsers.py`) + AST
    node `NextSentenceStatement` (`models/statements/misc.py`), and
    `TokenType.NEXT`/`"NEXT"` added to `STATEMENT_TOKEN_TYPES`/
    `STATEMENT_KEYWORDS` so condition-collection loops stop there instead
    of swallowing the words into the condition text.
  - `PERFORM ... WITH TEST BEFORE/AFTER` newline-intolerant at all three
    call sites in `perform_parser.py` -- added `skip_whitespace` before
    every peek following WITH/TEST.
  - DISPLAY's `_consume_subscript` newline-intolerant -- switched to a
    non-destructive `peek_past_noise` lookahead before consuming.
  - `consume_optional_qualifiers` wired into `write_parser.py`,
    `read_parser.py`, `start_parser.py` (previously only MOVE/arithmetic/
    SET).
  - `_normalize.py` + `_preprocess_fast.pyx` (mirrored, `.c` regenerated
    via `cythonize(..., compiler_directives={"language_level": "3",
    "boundscheck": False, "wraparound": False, "cdivision": True})`
    matching `setup.py`'s accelerator build): the column-72 mid-token
    overflow warning's rule 1 gains a third false-positive gate for a
    dropped tail that is only the statement-terminating period.
* **Updated** [parser.md](parser.md), [ast-models.md](ast-models.md),
  [preprocessing.md](preprocessing.md), [tests.md](tests.md).
* **Added** `tests/regression/test_corpus_residual_findings.py` (10 tests)
  and `TestBareTerminalPeriodDoesNotWarn` (+2) in
  `tests/regression/test_normalize_column_overflow_warning.py`. The new
  `NextSentenceStatementParser` registration also required updates to the
  self-maintaining registry-completeness tests:
  `tests/regression/test_swallow_sweep.py` (new `FIXTURES` entry) and
  `tests/unit/test_procedure_registry_dispatch_order.py` (new
  `EXPECTED_ORDER` position + `DISPATCH_CASES` case). Full suite (8,618
  tests) re-run clean against both the pure-Python and freshly-rebuilt
  Cython-accelerated paths.

## 2026-08-22 (normalize_fixed_format: numeric identification-area stamps no longer trip the mid-token overflow warning)

A concrete real-corpus repro (not a vague report — see the 2026-08-20 entry's
"deliberately not fixed" note for why that distinction matters here) found a
false-positive gap in the 2026-08-14 column-72 overflow-warning gate: a
vendored program's `WS000-D0000022-X PIC X(008) VALUE 'D0000022'.` line has
its statement-terminating period land exactly on column 72, immediately
followed (no separating blank) by `03050009` — an 8-digit, purely numeric,
per-line change/sequence stamp filling columns 73-80. Neighboring lines carry
the same shape (`03040000`, `03060000`, `03070000`, ... incrementing), an IBM
Z Open Editor/ISPF-style auto-numbering convention. Columns 1-6 are blank, so
the existing columns-1-6 sequence-number gate never recognized this file's
real (but differently-located) sequence-number convention, and every such
line spuriously warned `content beyond column 72 was dropped mid-token:
'03050009'` even though nothing was actually split — the digits are
legitimate, always-ignored identification-area content.

* **Changed** `cobolparser/preprocess/_normalize.py` and
  `cobolparser/_preprocess_fast.pyx` (mirrored, rebuilt via `python setup.py
  build_ext --inplace`, regenerated `.c` committed): rule 1 (mid-token split)
  now also skips whenever the dropped tail is non-empty and entirely digits
  *and* the line's total width still fits the traditional 80-column
  identification-area boundary. Deliberately narrower than "any dropped
  tail" so it doesn't reopen the exact case
  `test_blank_sequence_area_with_same_shape_still_warns` locks in (NIST's
  `IX2094.2`-shaped mixed alnum tail, blank columns 1-6, still a likely
  authoring mistake and still flagged) -- `.isdigit()` rejects that shape.
* **Updated** [preprocessing.md](preprocessing.md): documented the new gate
  as a named subsection under the existing column-73+ overflow write-up.
  Frontmatter `timestamp` bumped.
* **Added** two tests to
  `tests/regression/test_normalize_column_overflow_warning.py`:
  `test_numeric_identification_stamp_does_not_warn_with_blank_seq_area`
  (the repro shape above, both fast and pure implementations, must not warn)
  and `test_numeric_identification_stamp_still_warns_past_traditional_width`
  (a 9-digit tail spilling one column past the traditional 80-column width
  must still warn, via the existing word-boundary/exceeds-traditional-width
  rule) -- plus both new line shapes added to `TestFastAndPureParity.CASES`.
  Full suite (8,520 tests) re-run clean after the change; ruff/black/mypy
  clean on the touched files.

## 2026-08-21 (Second controlled re-probe on 1.8.0: 4 more real-corpus fixes)

A follow-up re-probe of the same real-world corpus against 1.8.0 (after the
two 2026-08-21 follow-ups above) found four items still standing from the
2026-08-20 sweep's "reviewed and deliberately left alone" note. All four
confirmed, reproduced, and fixed.

* **Paragraph-boundary dedent disambiguation (H9) only applied to a
  statement's *first* operand (`_utils.py`, and every operand-collection
  loop that calls `looks_like_paragraph_boundary`):** the 2026-08-20 sweep's
  MOVE fix disambiguated a real paragraph header (Area A, dedented) from a
  wrapped continuation-line operand (Area B) via `_looks_dedented_relative_to`
  — but only gated the check on `target_count == 0`; a *second-or-later*
  operand on its own continuation line still always tripped the boundary
  check regardless of indentation, exactly the same silent-drop bug shape
  for every operand past the first. Confirmed repros: `MOVE SPACES TO
  LKTRT-IND-PREMIER-APPEL\n    LKTRT-INDIC-SUITE.` and `OPEN OUTPUT
  FD020-FDDATE-OUT\n    FD020-SI6658-OUT.`, both silently dropping the
  second name. Fixed by hoisting `_looks_dedented_relative_to` into a shared
  `looks_dedented_relative_to` in `_utils.py` and ANDing it into every
  multi-operand call site regardless of position: `move_parser.py` (targets),
  `open_parser.py`/`close_parser.py` (file-name lists), `set_parser.py`
  (targets), `display_parser.py` (item list), `simple_statement_parsers.py`
  (CANCEL program-name list), `sort_merge_parsers.py` (SORT/MERGE's own
  clause-dispatch loop plus the shared `_parse_keys`/`_parse_file_list`
  helpers, now both threading a `reference_column` parameter), `string_
  unstring_parsers.py` (STRING's operand list, UNSTRING's clause loop, and
  `_parse_into_targets`, likewise threaded), `initialize_inspect_parsers.py`
  (INSPECT's "consume to period" trailer and `_parse_tallying`, likewise
  threaded), and `arithmetic_parsers.py` (`_consume_additional_arithmetic_
  targets`/`_consume_additional_giving_targets`, likewise threaded, plus
  COMPUTE's expression-token collection loop). Each site's reference column
  is the statement's own verb token column, matching MOVE's existing
  convention. The single highest-impact fix in this pass (the corpus's own
  count: 654 files affected).
* **Digit-led-identifier lexer lookahead only peeked one hyphen segment
  ahead (`lexer.py`, `_lexer_fast.pyx`):** the digit-branch of
  `tokenize_program_text` decided identifier-vs-numeric-literal by checking
  only the single character immediately after the leading digit run.
  `43E00-PROD` and `4E000-X` — real paragraph/data names whose first
  segment merely *looks* like scientific notation — hit the existing E-
  exponent exclusion and were misread as a `NUMERIC_LITERAL` (`43E00`)
  followed by a stray `MINUS` and `IDENTIFIER` (`PROD`). `22310-01-TRAITE`
  failed the same way for a different reason: its second segment (`01`) is
  also all-digit, so the one-hop lookahead never reached the third
  segment's letters at all. (`150000-X` and `01-DEPOT` already worked —
  their second segment starts with a letter directly.) Fixed by extending
  the lookahead past a matched E-exponent shape and then walking any
  further hyphen-joined segments for a letter anywhere in the rest of the
  word, ORed with the original one-hop check (still needed for the
  no-hyphen `25COUNT`/`45A` shapes the new hyphen-walk doesn't cover).
  Verified unaffected: plain `5E10`, `5E+5`, `5E-3`, `1.5E10` (no trailing
  hyphen segment, so `has_alpha` stays `False` and the numeric-literal path
  is unchanged). Both the pure-Python and Cython-accelerated lexers carry
  the identical fix (`.pyx` recompiled, `.c` regenerated) since the
  compiled `_lexer_fast.CobolLexer` is what actually serves `tokenize()`
  whenever the extension is built. Corrupted data-flow/CRUD analysis for
  654 files in the source corpus (same count as the operand-list fix above
  — both bugs hit largely the same file set).
* **SET's subscript fix only covered the *target* side
  (`set_parser.py`):** the 2026-08-20 sweep fixed `SET target(subscript) TO
  ADDRESS OF ...` by folding the target's subscript via
  `consume_optional_subscript` — but every *value*-reading branch (`TO`
  plain value, `TO ADDRESS OF` value, `UP BY` value, `DOWN BY` value) still
  read only a single token, silently truncating `SET IDX TO TABLE-ITEM(5)`
  to a value of `TABLE-ITEM` (subscript tokens left unconsumed, then
  swallowed as generic trailing tokens). Fixed by applying the same
  `consume_optional_subscript` fold to all four value-reading branches.
  428 occurrences across 112 files in the source corpus.
* **Embedded SQL `¬=` crashed the entire parse (`lexer.py`,
  `parsers/statements/_utils.py`):** the 2026-08-20 sweep added `BANG`/
  `PIPE` tokens for `!=`/`||`, but `¬` (U+00AC NOT SIGN — how some
  EBCDIC-derived mainframe source spells logical NOT) had no token of its
  own and hit the same hard `LexerError` `!`/`|` used to. Fixed by adding a
  `NOT_SIGN` token (mirroring `BANG`) and a `(NOT_SIGN, ASSIGN)` entry in
  `_EXEC_SQL_SPLIT_RELOP_PAIRS` so `¬=` rejoins without a spurious space,
  exactly like `!=`.

**Deliberately not fixed (unchanged from 2026-08-20):** `COMPUTE ... EQUAL`
in place of `=` was flagged again by this pass and again left alone —
still unconfirmed against real IBM Enterprise COBOL compiler behavior, so
likely invalid COBOL rather than a parser gap, not a case of "no repro" this
time but "no compiler ground truth yet."

Regression coverage for all four fixes: `tests/regression/
test_real_corpus_parse_failures.py` (`TestSecondOperandOnContinuationLine`,
`TestDigitLedHyphenatedProcedureNames`, `TestSetSubscriptedValue`,
`TestEmbeddedSqlNotSignOperator`).

**Post-fix `/code-review` (8-angle pass, same day):** caught two small dead
code/duplication issues, both fixed:

* The lexer's new hyphen-segment walk (`lexer.py`, `_lexer_fast.pyx`) had a
  standalone `if text[scan_pos].isalpha(): has_alpha = True` check
  immediately before a `while` loop whose first iteration re-examines that
  exact same character — a pure duplicate. Removed; the `while` alone
  covers it. `.pyx` recompiled, `.c` regenerated.
* `set_parser.py`'s four value-reading branches (`TO`, `TO ADDRESS OF`,
  `UP BY`, `DOWN BY`) each hand-copied the same 4-line "build parts, consume,
  fold subscript, join+strip" sequence. Factored into one
  `_consume_subscripted_value` helper.
* `_utils.py`'s `looks_dedented_relative_to` collapsed its two separate
  `is None` guards into one, and dropped a pointless `bool(...)` wrap
  around an already-boolean comparison.
* `.okf/tests.md` mis-stated this commit's own test-count delta as "+23"
  (the file's post-commit *total*) instead of "+11" (what this commit
  actually added) — corrected.

Two review findings were investigated and found to be **pre-existing
trade-offs, not new regressions** (both now pinned as expected results
rather than left as future "surprises"):

* `COMPUTE X = 5E10-Y.` (space-free subtraction, left operand shaped like
  scientific notation) now lexes as one `IDENTIFIER("5E10-Y")` instead of
  `NUMERIC_LITERAL MINUS IDENTIFIER`. Verified genuinely new (checked
  against the pre-fix pure-Python lexer directly, bypassing the compiled
  extension) but an unavoidable trade-off, not an oversight: the character
  sequence is structurally identical to a real hyphenated name
  (`43E00-PROD`), and real COBOL arithmetic is written with spaces around
  operators. See lexer.md's "Accepted trade-off" note.
* A missing-period statement whose second-or-later operand and the
  following paragraph header sit at *exactly* the same column can still be
  silently absorbed as an extra operand instead of recognized as a
  boundary. Verified via a worktree checkout of the pre-fix code that this
  exact ambiguity already existed for a statement's *first* operand from
  the original 2026-08-20 MOVE fix onward — not introduced by this pass,
  which only extends the same trade-off uniformly to every operand
  position. See parser.md's "Known limitation, not new" note.

One architectural observation from the review, deliberately not acted on in
this pass: the dedent-disambiguation *predicate* is now centralized
(`looks_dedented_relative_to`), but the operand-collection *loop* that
calls it is still hand-copied into 9+ parser files, and this bug shape
(an operand-collection loop mishandling a trailing operand) has now
recurred across five separate dated entries in this log. A shared
higher-order collection helper in `_utils.py`, or threading
`reference_column` through `ParseContext` instead of by hand, would remove
the need to re-derive this fix a sixth time -- flagged for a future,
dedicated pass rather than folded into this bug-fix PR.

## 2026-08-20 (Real-corpus parse-failure sweep: 5 fixes from an external error-analysis pass)

An external analysis of a 559-file real-world COBOL corpus (mainframe
extracts, not NIST/shamrice) surfaced hard parse failures and silent
content-drops that the existing test suite's synthetic fixtures never
exercised. Five confirmed, reproduced, and fixed; two flagged items were
deliberately left alone (see below).

* **MOVE target on its own continuation line, dropped when the target isn't
  a known DATA DIVISION name (`move_parser.py`):** `looks_like_paragraph_boundary`
  (see the H9 entry above) fired on the *first* token after `TO` whenever
  that token wasn't in `known_data_names` — e.g. it's declared via an
  unexpanded `COPY` member — misreading a perfectly ordinary line-wrapped
  target (`MOVE A TO\n    B.`) as the start of the next paragraph. The MOVE
  ended up with zero targets and a spurious "requires at least one target
  after TO" error. Fixed by exempting the very first target
  (`target_count == 0`) from the paragraph-boundary check: COBOL's MOVE
  grammar guarantees an operand immediately follows `TO`, so that position
  can never legitimately be a paragraph header. The single highest-impact
  fix in the sweep (~468 errors / 180 files in the source corpus).
* **Embedded SQL `!=` and `||` crashed the entire parse
  (`lexer.py`, `parsers/statements/_utils.py`):** `!` and `|` had no
  `SINGLE_CHAR_TOKENS` entry, so hitting either inside an `EXEC SQL ...
  END-EXEC` block (SQL not-equal / string concatenation) recorded a hard
  `LexerError` — which fails the *whole* parse (`result.ast is None`), not
  just that statement, since EXEC SQL text is reconstructed from already-lexed
  tokens (`collect_exec_sql_text`) rather than scanned as raw opaque text at
  the lexer level. Fixed by adding dedicated `BANG`/`PIPE` single-char
  tokens (mirroring how `>=`/`<=`/`<>` already lex as two single-char
  tokens and get rejoined) and extending `_EXEC_SQL_SPLIT_RELOP_PAIRS` so
  `!=` and `||` rejoin without a spurious space in the reconstructed SQL
  text. `<=`/`>=`/`<>` inside EXEC SQL already worked (no lexer error) —
  only the two characters with no token at all were fatal.
* **`PROGRAM-ID name` with no trailing period
  (`parsers/divisions/identification.py`):** IBM Enterprise COBOL tolerates
  a missing period after the program name (verified against real compiler
  behavior); the parser raised a hard `ParseError` instead, which aborted
  IDENTIFICATION DIVISION parsing before `AUTHOR`/`DATE-WRITTEN`/etc. were
  ever reached — cascading into "No recognizable COBOL division found near
  'AUTHOR'". Now records a `ParseResult.warnings` entry via `self.host.add_warning`
  and continues (the *first* period, right after the `PROGRAM-ID` keyword
  itself, is unaffected — only the confirmed real-world shape was
  relaxed).
* **`SET target(subscript) TO ADDRESS OF ...` dropped the subscript and the
  entire value clause (`set_parser.py`):** the target-collection loop had
  no subscript handling at all — a trailing `(1)` fell to the loop's
  `else: break`, which stopped the loop *before* the `TO` keyword was ever
  reached, so the whole rest of the statement (`TO ADDRESS OF ...`) was left
  in the stream and reported as "Unparsed tokens". Fixed by folding a
  trailing `(subscript[, subscript]...)` into the target via the shared
  `consume_optional_subscript` helper (same pattern MOVE/ADD/SUBTRACT/
  COMPUTE targets already use).
* **`SKIP1`/`SKIP2`/`SKIP3` compiler-listing directives unrecognized
  (`lexer.py`, `models/statements/misc.py`, `parsers/statements/
  simple_statement_parsers.py`, `parsers/divisions/procedure_registry.py`):**
  unlike `EJECT` (dedicated token + `EjectStatementParser`), `SKIP1`/`SKIP2`/
  `SKIP3` lexed as plain `IDENTIFIER`s and fell through to the PROCEDURE
  DIVISION's unrecognized-statement recovery, dropping the directive and
  adjacent tokens from the AST (~7,100 occurrences in the source corpus —
  the highest-frequency silent-drop found). Added dedicated `SKIP1`/`SKIP2`/
  `SKIP3` tokens and a new `SkipStatement` AST node / `SkipStatementParser`,
  registered directly after `EjectStatementParser` (same class of
  compiler-directing no-op).

**Post-review corrections (`/code-review`, same day):** an 8-angle review of
the PR caught one real regression and two smaller correctness gaps in the
fixes above, all now corrected:

* The MOVE fix's `target_count == 0` exemption over-corrected: a MOVE with
  a *genuinely* missing target, immediately followed by a real next
  paragraph, now silently absorbed that paragraph's header as the MOVE's
  bogus target instead of erroring — the opposite failure mode from the one
  being fixed, and the more dangerous one (silent AST corruption vs. a
  reported error). Fixed by disambiguating on indentation instead of
  disabling the check outright: a genuine paragraph header is dedented back
  to Area A relative to the MOVE statement's own column, while a wrapped
  continuation-line operand stays at or deeper than it (Area B) —
  `_looks_dedented_relative_to` in `move_parser.py`.
* `token_stream.expect(".")` in `_parse_program_id` can raise
  `UnexpectedEndOfInput` (stream exhausted right after the program name),
  not just `TokenMismatch` — the exact shape of a truncated real-world
  file — and the original fix only caught the latter, so that case still
  hard-failed. Now catches both. Also switched the `self.host.add_warning`
  call to the `getattr(host, "add_warning", None)` + `callable(...)` guard
  every other division parser already uses, for consistency.
* `set_parser.py`'s new subscript-folding changed `stmt.add_target(...)`
  from an unconditional call to one gated on `if target_name:`, silently
  dropping an edge-case empty-string target that the prior code always
  recorded. Reverted to the unconditional call.

One existing test (`test_error_missing_period_after_program_name` in
`tests/unit/test_identification_division_parser.py`) was found to be
passing for the wrong reason after the PROGRAM-ID fix — a coincidental
exception from the token *after* the one field being tested, not the field
itself — and was rewritten into two tests that isolate the actual behavior,
plus a new test for the truncated-file/`UnexpectedEndOfInput` case.

Reviewed and deliberately left alone: SKIP1/SKIP2/SKIP3 as unconditional
lexer keywords does shadow those words if used as a paragraph/data name or
a PERFORM/MOVE/GO TO target — but they're genuine COBOL reserved words (no
compilable program can declare them as identifiers), matching the existing
precedent for EJECT/CONTINUE already being unconditional keywords in this
lexer; no occurrence in this repo's test/example corpus either. The
`SkipStatementParser`/`SkipStatement` direct instantiation (not via
`ASTNodeFactory`) matches every sibling parser in the same file
(`EjectStatementParser`, `ContinueStatementParser`, etc.), so it wasn't
changed to avoid diverging from local convention for no functional gain.
The same first-operand paragraph-boundary misdetection bug shape the MOVE
fix addresses also exists, unfixed, in SET/DISPLAY/STRING/UNSTRING/SORT/
MERGE's operand-collection loops — flagged as a follow-up, not fixed here,
since (like the two items below) it has no concrete corpus repro backing
it, unlike the five fixes above which were each reproduced directly.

**Deliberately not fixed:** (1) `COMPUTE ... EQUAL` in place of `=` — the
external analysis itself flagged this as needing confirmation against real
mainframe compiler behavior before changing anything (1 file in the source
corpus); left alone pending that verification. (2) A vaguer report of
"`PERFORM ... TIMES`/`UNTIL`, `OF` qualification, `TEST BEFORE`/`AFTER`
tails dropped in various statements" and "67 real mid-token truncations
past column 72" — neither came with a concrete reproducible example (unlike
the five fixes above, all of which were reproduced against a minimal
`.cbl` before and after the fix), so no speculative change was made.

## 2026-08-21 (Follow-up: two more statements missing all-digit procedure-name support)

Re-verifying the "digit/float paragraph names" item from the 2026-08-20
sweep against the current parser found the underlying all-digit-name gap
(fixed for `PERFORM`/paragraph headers back on 2026-07-20) was never
extended to two sibling statements that also target a paragraph by name:

* **`ALTER paragraph-1 TO [PROCEED TO] paragraph-2`
  (`simple_statement_parsers.py`):** the from-paragraph read required an
  `IDENTIFIER` token outright, so `ALTER 1000 TO PROCEED TO 2000` (an
  all-digit from-paragraph) fell through the `while` loop's first check and
  the entire `ALTER` statement was dropped as unrecognized. The
  to-paragraph read was already unrestricted (any non-`PERIOD` token), so
  only the from-paragraph needed the same `IDENTIFIER`-or-all-digit
  `NUMERIC_LITERAL`/`LEVEL_NUMBER` check `perform_parser.py`'s
  `_is_procedure_name_token` already uses.
* **Computed `GO TO target-1 target-2 ... DEPENDING ON var` with
  all-digit targets (`go_parser.py`):** the first target already accepted
  any token value, but the scan-ahead loop that collects *additional*
  targets (and looks for the `DEPENDING` keyword that confirms this is a
  computed GO TO, not a single target followed by the next sentence)
  required `TokenType.IDENTIFIER` specifically. Once the first target was
  numeric, `GO TO 1000 2000 3000 DEPENDING ON WS-N` stopped scanning at
  `2000`, never found `DEPENDING`, and left `2000 3000 DEPENDING ON WS-N`
  — including the `DEPENDING ON` variable — unconsumed in the stream.

Both fixed by inlining the same all-digit-token check
(`IDENTIFIER`, or `NUMERIC_LITERAL`/`LEVEL_NUMBER` with an all-digit
value) at the point each statement decides whether a token is a
paragraph-name candidate. Regression coverage:
`tests/regression/test_real_corpus_parse_failures.py`
(`TestAlterNumericProcedureNames`, `TestGoToDependingOnNumericTargets`).

## 2026-08-19 (Coverage audit: gap-closing tests + one correctness fix, floor raised 81% -> 90%)

A full-suite coverage run (8,411 tests, no regressions) measured 91.79%,
well above the enforced 81% floor. Closed the clearest gaps rather than
chasing every scattered line:

* **`program_fixtures.py`** (84.4% -> 92.6%): `_resolve_callees`/
  `_find_callee_file` (the `--callee-path` file lookup for a static CALL
  target not bundled in the same compilation unit) had no tests at all —
  the existing `callee_paths=[]` test returns before that code ever runs.
  9 new tests in `test_program_fixtures.py`'s `TestCalleeResolution`:
  exact/lowercase/extension-fallback file matching, not-found, a swallowed
  `ProgramLayoutError`, dynamic-CALL exclusion, contained-program precedence
  over a same-named callee_paths file, and an end-to-end check that a
  file-resolved callee's LINKAGE writes flip the caller argument's
  direction via `callee-source` provenance.
* **`invoke_parser.py`** (79.8% -> ~88%): new
  `tests/unit/test_invoke_parser_error_paths.py` covers both
  required-operand validations (missing object identifier, missing method
  name), the `END-INVOKE` terminator, `BY REFERENCE/CONTENT/VALUE` in the
  USING clause, comma-separated parameters, a `RETURNING` with no target,
  an unrecognized `BY` mode word, and a following statement keyword with no
  period correctly ending the USING clause instead of being swallowed.
* **`unused_variables.py`** (80.2% -> 86.5%) — a real correctness fix, not
  just coverage: `ExecCicsStatement`/`ExecImsStatement` extend `ASTNode`
  directly, not `CobolStatement` (unlike `ExecSQLStatement`), so they never
  appeared in `ast.get_all_statements()` at all — the per-statement
  `host_variables`/`null_indicators` duck-typed sweep that already existed
  for EXEC SQL was dead code for EXEC CICS/DLI regardless of what fields it
  read, because the loop never saw those nodes. Fixed with a separate
  `ast.find_all_by_type("ExecCicsStatement"/"ExecImsStatement")` sweep over
  `.options`/`.arguments` in `_collect_referenced_names`. A field referenced
  only inside `EXEC CICS`/`EXEC DLI` is no longer falsely reported unused.
  8 new tests pin the fix (`TestExecCicsAndImsArguments`); 5 more
  (`TestExpressionAndSelectorCoverage`) close LogicalExpression AND/OR,
  PERFORM VARYING...AFTER, RENAMES, and EVALUATE TRUE Condition/Range
  selector gaps in the same walk. See [analysis.md](analysis.md).
* **`generators/data/values.py`** (81.4% -> 89.7%): new
  `tests/unit/generators/data/test_values.py` (34 tests) drives
  `ValueFactory` directly rather than through a copybook round-trip —
  every `_semantic_text` branch (email, phone, state, zip, city, street,
  first/last/bare name, date, description, code, flag), the numeric
  semantic hints (ID/money/count/rate/date/time, including the
  too-narrow-falls-back-to-random paths for date/time digits), the
  COMP-1/2 float path, `_format_number`'s sign/ceiling/decimal-only/
  zero-width clamping, `blank_rate`, the unique-field retry-then-sequential
  fallback, and `render()`'s never-randomly-negates guarantee.
* **`constraints.py`**/**`const_fold.py`**: both already carry deep
  NIST/shamrice corpus sweeps, so remaining gaps are scattered single-line
  defensive branches with low marginal value. Added the one clear gap in
  each: `to_dict()` serialization was entirely untested in both
  (`ConstraintReport`/`BranchConstraints`/`FieldConstraint`/
  `SequenceConstraint`, and `ConstantFoldResult`, including the
  copy-not-alias property), plus a multi-subject `EVALUATE ... ALSO`
  unsupported-path test in constraints.py.

Post-fix full-suite re-run: 8,476 tests (65 more than baseline), 0
failures, 92.22% coverage. `--cov-fail-under` raised from 81 to 90 in
`pyproject.toml` to lock in the new baseline with headroom (CLAUDE.md,
`.okf/index.md`, `.okf/tests.md` updated to match). CI still does not run
the suite automatically on push/PR — only `workflow_dispatch` — which
remains the single largest gap in this area; out of scope for this pass
per the requester's instruction.

## 2026-08-18 (`--help` epilogs with usage examples on every subcommand)

`cobolparser/cli/parse.py` — every subcommand parser (both the hand-built
ones and the 13 routed through `_build_analyzer_parser()`, which grew a
required `examples` kwarg) now sets `formatter_class=RawDescriptionHelpFormatter`
and an `epilog` with one or two runnable examples. `--help` UX only — no
flag, default, or output-shape changes. See [cli.md](cli.md).

## 2026-08-16 (Analyzer-subcommand audit: 9 fixes + gap tests)

Full audit of the 13 analyzer CLI subcommands (smoke sweep over the whole
sample + shamrice corpora, coverage-driven gap analysis, per-module review
with executed repros). Fixes, each pinned in
`tests/regression/test_audit_2026_08_16_analyzers.py`:

* **io_sequence.py** — execution-order walk (entry chain + PERFORM
  inlining + GO TO following) replaces the raw declaration-order AST walk
  that false-positived on the canonical PERFORM-structured program. See
  [analysis.md](analysis.md).
* **models/statements/call.py** — `set_possible_values` sorts
  (deterministic `analyze` JSON under hash randomization).
* **language_env_analyzer.py** — quoted literals no longer scanned for
  `FUNCTION <name>`.
* **ims_segment_analyzer.py** — group-SSA segment names merge MOVE-tracked
  child-field values with the static VALUE clause.
* **move_type_checker.py** — multi-part alphabetic PICTUREs (`AA(3)`)
  classify ALPHABETIC; trailing `CR`/`DB` classifies NUMERIC_EDITED.
* **technical_debt.py** — score rounded to serialized precision before
  grading; no-procedures components carry a finding.
* **complexity.py** — same-named paragraphs in different sections
  aggregate instead of dropping the second body.
* **generators/data/layout_offsets.py** — PIC-less USAGE-only record roots
  (`77 X USAGE COMP-1.`) report their usage.
* **cli/parse.py** — `analyze` emits `possible_values_incomplete`;
  `program-flow` warns when `--profile` meets a text format (see
  [cli.md](cli.md)).

New tests for previously-uncovered paths:
`tests/unit/cli/test_analyzer_cli_gaps.py` (unused-variables copybook
provenance flow, partial-parse warnings) and
`tests/unit/analysis/test_analyzer_gap_coverage.py` (complexity exception
clauses + precomputed flow_report, recursion-risk escape routes + MIXED
cycles, EVALUATE/Type-2 clones, grade bands C-F, weight normalization,
LINKAGE data-items).

Known, deliberately unfixed: `data-items` emits duplicate
`qualified_name`s for multiple FILLERs in one record (disambiguating would
change the output contract); analyzer subcommands warn on parse *errors*
but stay silent on dropped-content parse *warnings* (21/48 sample programs
produce such warnings — the noise trade-off is intentional); analyzers
remain single-program scope (no `contained_programs` recursion).

## 2026-08-16 (New analyzers: ComplexityAnalyzer, RedundancyAnalyzer, TechnicalDebtAnalyzer)

Added three new static-analysis modules implementing the "cyclomatic
complexity & maintainability metrics" idea from `docs/feature-ideas.md`
(idea #2), extended to also cover redundancy (dead code/unused variables/
duplicate-paragraph clones) and a composite technical-debt score:

* **`cobolparser/analysis/complexity.py`** -- `ComplexityAnalyzer`:
  per-paragraph/section McCabe cyclomatic complexity from a dedicated
  statement-tree walk (not `ProgramFlowAnalyzer`'s inter-paragraph CFG, per
  the design note in `docs/feature-ideas.md` -- most COBOL complexity lives
  *inside* a paragraph). Also `extended_complexity` (AND/OR-aware),
  `max_nesting_depth`, `fan_in`/`fan_out` (from `ProgramFlowReport` edges),
  and LOW/MODERATE/HIGH ratings via overridable `ComplexityThresholds`.
* **`cobolparser/analysis/redundancy.py`** -- `RedundancyAnalyzer`: wraps
  `DeadCodeAnalyzer`/`UnusedVariableAnalyzer` for dead/unused ratios, and
  adds new whole-paragraph Type-1 (exact)/Type-2 (renamed-identifier)
  duplicate-code detection via a hashable nested-tuple statement
  fingerprint -- deliberately exact matching only (no sub-paragraph
  sliding-window or near-miss/type-3 similarity scoring), reusing
  `unused_variables.py`'s `_NON_IDENTIFIER_WORDS` reserved-word set rather
  than re-deriving a second one.
* **`cobolparser/analysis/technical_debt.py`** -- `TechnicalDebtAnalyzer`:
  composite 0-100 debt score (A-F grade) combining the above two plus
  control-flow smells (GO TO density, `ALTER` usage, no-escape recursion
  cycles from `RecursionRiskAnalyzer`, unreachable nodes) and a size
  component, as a `DebtWeights`-weighted rollup where every point traces to
  a named finding. Also produces a `top_offenders` list ranking the worst
  procedures with their specific reasons.

New CLI subcommands `complexity` and `health` (`_build_analyzer_parser`,
`profiling=True`), both added to `_SUBCOMMANDS`/`cli.md` -- **catches an
easy-to-repeat bug**: `main()`'s legacy-syntax backward-compatibility shim
checks the first positional argument against `_SUBCOMMANDS` (a *second*,
separately-maintained set from the argparse subparsers actually registered
in `_build_parser`) to decide whether to prepend `"parse"`; forgetting to
add a new subcommand there makes `cobol-parser health foo.cbl` silently
misparse as `cobol-parser parse health foo.cbl` -- caught by a CLI smoke
test in `tests/unit/cli/test_complexity_health_subcommands.py::
TestSubcommandsRegistered::test_subcommand_via_main` before it shipped, not
after. All three analyzers/CLI subcommands single-program scope only (no
cross-file/batch redundancy in this pass, matching every other analyzer).

## 2026-08-14 (Fixed-format column-72 overflow: word-boundary drops + wired into the real parse pipeline)

Flagged during final whole-branch review of the data-item-layout plan (as
out-of-scope, unrelated to that feature) and investigated separately: a
test author writing `OCCURS 1 TO 10 TIMES DEPENDING ON WS-COUNT.` on one
line hit a real, pre-existing lexer/preprocessor gap — the clause's
` ON WS-COUNT.` operand was silently dropped, no error, no warning, and
`compute_record_layout` happily produced a *fixed* `OCCURS 10 TIMES` with
no ODO clause instead. Root cause was two independent things, both fixed
in `cobolparser/preprocess/_normalize.py` (+ `_preprocess_fast.pyx`
mirror, `.c` regenerated):

1. **The existing mid-token overflow check (added 2026-08-03) missed
   word-boundary drops.** It only fires when columns 72 and 73 are *both*
   non-blank; the OCCURS/DEPENDING repro breaks on a space (column 72),
   which the check treats identically to the traditional
   sequence-number/identification-area case it's designed to stay silent
   on. New second rule: a non-comment line whose real content (after
   `rstrip()`) extends past column 80 — the traditional maximum width of
   an 80-column punch-card line — is flagged regardless of where exactly
   it broke, since content can never legitimately survive past column 80.
2. **The diagnostic was never wired into any real entry point.**
   `warnings=None` by default meant the check ran but collected nothing,
   and none of `CobolParser.parse()` (`_parse_core`'s fixed-format
   auto-detection), the module-level `parse_cobol()`, `lexer.py`'s
   `_tokenize_source`/`tokenize_cobol()`, or the CLI's `preprocess`
   subcommand passed `warnings=` — so the mechanism added on 2026-08-03
   was completely unreachable from a normal parse the whole time. All four
   now surface it (`ParseResult.warnings`, the `_tokenize_source` warnings
   tuple element, and stderr for the CLI). `CobolParser.__init__` gained
   an `initial_warnings` parameter so `parse_cobol()`'s pre-construction
   normalization warnings survive the `self.warnings.clear()` at the top
   of `parse()`.
3. **Wiring rule 1 up for the first time revealed it was already far
   noisier than its own tests suggested.** Measuring both rules against
   the vendored NIST CCVS85 corpus (`examples/cobol/*.CBL`,
   `examples/nist-cobol85/*.CBL`) before shipping — prompted by review —
   found 4438 raw mid-token "hits", 4434 of them lines like
   `examples/cobol/IX209A.CBL:292`:
   `029100          "...".IX2094.2`, where the statement's own closing
   period genuinely lands on column 72 and the file's own per-line
   identification code starts immediately at column 73 with zero authoring
   mistake — this specific shape (code ending exactly at column 72, no
   padding blank before the identification field) was never covered by the
   2026-08-03 fix's own tests, which only exercised a padded variant.
   Fixed by gating both rules on the line's own columns 1-6: a real numeric
   sequence number there (all digits, ignoring blanks) is independent,
   reliable evidence the line belongs to the traditional 80-column
   convention (hand-typed modern source never bothers with sequence
   numbers) — dropped the corpus hit count to 4, all genuine (harmless)
   truncation of `*>` free-form inline-comment text the preprocessor
   doesn't parse `*>` semantics for (lexer-level only; a separate, smaller,
   left-as-is gap).

Column-72/TEXT_END_COL math itself was verified correct (not an off-by-one
— column 72 is the last kept code column, matching IBM fixed-format
convention exactly) before touching anything; see
[preprocessing.md](preprocessing.md) for the full three-rule writeup.

Surfacing the (already-existing) mid-token rule for the first time found
one genuine dormant hit in the project's own test suite too:
`tests/unit/test_unstring_gaps.py::TestUnstringCombined::
test_full_combined_statement` had an INTO-clause continuation line at
73 columns (one over) with a blank sequence area, silently dropping its
trailing comma for as long as the test existed with no effect on the
assertions — fixed by trimming one space of indentation. No other fixture
in the full suite (8281 tests, 2 new in this change) tripped either rule
after the fix; full suite + 91%+ coverage (floor 81%) both green.

Tests: `tests/regression/test_normalize_column_overflow_warning.py`
(`TestWordBoundaryOverflowWarns`, extended fast/pure parity) and new
`tests/regression/test_fixed_format_word_boundary_overflow.py`
(end-to-end through both `parse_cobol()` and `CobolParser.parse()`,
confirming the warning surfaces without being promoted to a hard error
under `FAIL_FAST`).

## 2026-08-14 (preprocessing: implementation split out of `preprocess/__init__.py`)

The closed-source PyPI release build (`COBOLPARSER_CLOSED_SOURCE=1`) compiles
every module in the package to a `.so`/`.pyd` *except* `__init__.py` and
`__main__.py`, on the premise that those are thin shims with no business logic.
`cobolparser/preprocess/__init__.py` violated that premise outright: 1,446 lines
holding `normalize_fixed_format`, `strip_compiler_directives`, the whole
`>>IF`/`>>EVALUATE` constant-condition evaluator (`_ConditionParser`,
`_evaluate_condition`), `validate_copybook_content`, `validate_level_numbers`,
and the `PreprocessingError` hierarchy — all of which would have shipped as
readable source in a wheel whose entire purpose is not to.

Moved verbatim into a new `cobolparser/preprocess/_normalize.py`
(the unused `typing.Optional` import was dropped — it only survived because
ruff grants F401 to `__init__.py`). `preprocess/__init__.py` is now a re-export
stub: the same `__all__`, the same `copybook_expander` re-exports, and the same
`_preprocess_fast` Cython swap with `_normalize_fixed_format_pure` preserved.
No public or private import path changed — `copybook_expander.py` and
`path_resolver.py` keep working through `from . import ...` because the
`._normalize` import sits above the `.copybook_expander` import in the stub.

Verified with a real closed-source wheel: `preprocess/_normalize.pyd` is
compiled, `preprocess/__init__.py` ships as the stub, and the wheel contains
zero `.c`/`.pyx`/`.h` files (Cython embeds the original source verbatim in C
comments, so a shipped `.c` is a full source leak — `exclude-package-data` in
`pyproject.toml` now blocks them). See `.okf/preprocessing.md`.

## 2026-08-14 (Follow-up fix: misnested level-77 dropped as a group's only child)

The final-review fix wave below (Finding 2) stopped a misnested
level-77 from corrupting its accidental parent's `byte_length`, but left
a narrower gap deliberately parked: when the misnested 77 was its
parent's *only* AST child (`01 WS-REC. 77 WS-CTR PIC 9(4) COMP.`, no
intervening `05`), `_direct_data_children(WS-REC)` returns empty, so
`compute_record_layout()` treats `WS-REC` as a childless elementary item
(`is_group=False, byte_length=0`) and `WS-CTR` never appears anywhere in
`compute_program_data_items()`'s output — silently dropped, not merely
misclassified.

Fixed in `compute_program_data_items()`
(`cobolparser/generators/data/layout_offsets.py`), per the adjudicated
recommendation to handle this at the section-walk level rather than
further patching the shared `_direct_data_children()` guard: a new
`_find_misnested_level_77_items()` helper walks each top-level record's
*raw*, unfiltered AST subtree (bypassing the guard, not extending it) to
find every level-77 item hidden by it, and each one is re-rooted as its
own independent record via `compute_record_layout()` — same treatment as
a genuine section-level 77 — including resolving its `redefines_chain`
against the section's top-level siblings via the already-in-scope
`siblings_by_name`, mirroring the top-level-record path immediately
above it. This recovers the 77 in both shapes (only-child, from this
fix, and has-siblings, verified to also now work end-to-end even though
it was only the byte_length-corruption half of that case that the
original guard fixed) — no case is left where the 77 is silently
dropped from the output.

Tests: 1 new test in `TestComputeProgramDataItems` —
`test_a_77_level_item_that_is_a_records_only_child_is_recovered_as_its_own_record`
— see [tests.md](tests.md). Full `tests/` suite (8272 passed, 1 skipped,
1 xfailed) passes with the 81% coverage gate live; the two other callers
of `compute_program_data_items()` (`cli/parse.py`,
`test_data_item_layout_corpus.py`) were checked for exact-count/snapshot
assertions and have none.

## 2026-08-14 (Final whole-branch review fix wave for the data-item-layout plan)

Two findings from a final whole-branch code review of the 9-task
data-item-layout plan (each task's own per-task review had already
passed, but missed these) were fixed in
`cobolparser/generators/data/layout_offsets.py`:

**Finding 1 (Critical) — root-level level-88s silently dropped.**
`compute_record_layout()` builds the record's own root `LayoutItem` via
a separate inline `out.insert(0, LayoutItem(...))` path that bypasses
`_layout_item()`'s condition-children loop entirely. A level-88
declared directly under a 01/77 record root with no intervening group
level — COBOL's most common flag idiom (`01 WS-EOF-FLAG PIC X. 88
WS-EOF VALUE "Y". 88 WS-NOT-EOF VALUE "N".`) — never appeared in the
output; the same shape nested one level deeper (under a `05`) worked
fine since that path goes through `_layout_item()`. Fixed by emitting
the root's own direct condition children right after the root
`LayoutItem` is inserted, mirroring `_layout_item()`'s loop exactly
(same `LayoutItem` shape, reusing the root's own `byte_offset=0`,
`byte_length=record_length`, `offset_ambiguous=False`).

**Finding 2 (Important) — a misnested level-77 corrupted an unrelated
preceding record's byte_length.** This is a pre-existing *parser*
behavior, deliberately left unfixed at the parser level per the
review's scope: the hierarchy builder nests items purely by
level-number comparison, so `77  WS-CTR ...` declared immediately after
`01 WS-REC. 05 WS-A PIC X(3).` becomes `WS-A`'s AST *child* (77 > 05),
not a section-level sibling of `WS-REC`. Verified directly by parsing
that exact fixture and printing the AST (not guessed) — confirmed
`section.data_items` contains only `WS-REC`, and `WS-A.children`
contains a `CobolDataItem` for `WS-CTR`. Since `_direct_data_children()`
counted that misnested 77 as a real data child, `_layout_item()`'s `if
data_children:` branch misclassified `WS-A` as a GROUP item and
discarded its own elementary `PIC X(3)`/byte_length, corrupting both
`WS-A`'s and `WS-REC`'s reported `byte_length`. Fixed with a guard
directly in `_direct_data_children()` — excluding any `CobolDataItem`
child with `level == 77`, since a level-77 item is never legitimately
subordinate to anything under COBOL's own level-number rules — chosen
over an alternative fix inside `compute_program_data_items()` because it
requires no duplicate tree-walking logic and fixes the root cause at
its single call-site-independent source. `test_77_level_record_is_its_own_flat_item`
(a *legitimate* standalone 77-level record, no preceding-sibling
entanglement) was re-run and still passes unchanged. Residual, in-scope
limitation left as-is: a level-77 item misnested this way still doesn't
appear as its own record in `compute_program_data_items()`'s output —
it's excluded from its accidental parent's children, not promoted to a
section-level sibling, since `section.data_items` never contained it.

Tests: 2 new tests in `TestLevel88` (01-level and 77-level record roots
with directly-attached 88s) and 1 new test in
`TestComputeProgramDataItems` (the `WS-REC`/`WS-A`/`WS-CTR` corruption
repro) — see [tests.md](tests.md). Full designated selection
(`test_layout_offsets.py` + `test_data_item_layout_corpus.py` +
`test_new_subcommands.py` + `test_layout.py`) and the full `tests/unit`
suite both pass with no regressions (5329 passed, 1 skipped, 1 xfailed).

## 2026-08-14 (New `data-items` CLI subcommand — final task of the data-item-layout plan)

Task 9 (last of 9) of the data-item-layout plan wires Task 8's
`compute_program_data_items()` (`cobolparser/generators/data/layout_offsets.py`)
into cobol-parser's own CLI, following the exact `dead-code`/`io-sequence`
registration pattern (`_build_analyzer_parser(subparsers, "data-items", ...,
_cmd_data_items, profiling=True)`). `_cmd_data_items` is a three-liner —
`_parse_or_fail(args)` then `compute_program_data_items(ast)` then
`_emit_report(output, args, prof, ast)` — identical in shape to
`_cmd_dead_code`. `"data-items"` was also added to `_SUBCOMMANDS` so the
legacy no-subcommand-given syntax (`cobol-parser data-items file.cbl`
without an explicit `parse` prefix) doesn't get misrouted to `parse`.

Tests landed in the existing `tests/unit/cli/test_new_subcommands.py`
(new `TestCmdDataItems` class, plus `"data-items"` added to the two
existing parametrized registration/output-silent test classes) rather
than a new file — that file's own docstring already scoped it to "new
CLI subcommands added to cobolparser.cli.parse", and `data-items` is
exactly that. See [cli.md](cli.md)'s "Data-Items" entry and
[tests.md](tests.md) for details.

## 2026-08-13 (`UnusedVariableAnalyzer`: Copilot PR-review fix — qualified names/FUNCTION calls falsely reported unused)

Copilot review on PR #148 (the `UnusedVariableAnalyzer` PR) caught a real
bug: statement parsers routinely join a whole qualified reference,
subscript, special register, or intrinsic function call into a *single*
operand string (`MoveStatement.source` for `MOVE WS-A OF WS-GRP TO ...`
is literally `"WS-A OF WS-GRP"`) — the analyzer's first version added
such an operand verbatim as one name, so `WS-A`/`WS-GRP` never matched a
declared item's bare name and were falsely reported unused. Reproduced
empirically before fixing, and confirmed against the sample corpus sweep
(534 → 485 flagged unused across `tests/samples/*.cbl` +
`examples/cobol/shamrice/*.cbl`, same corpus as the analyzer's original
validation pass).

Fixed by replacing the old boolean `_is_identifier_operand` gate (add the
whole operand as one name) with `_extract_identifiers` (tokenize the
operand, strip quoted substrings, filter a merged
figurative-constant/qualification-keyword/condition-stopword list) at
every call site, not just MOVE. See [analysis.md](analysis.md)'s
`UnusedVariableAnalyzer` section for the full writeup, and
`TestQualifiedAndFunctionOperands` in
`tests/unit/analysis/test_unused_variables.py` (+5 tests).

## 2026-08-13 (New analyzer: `UnusedVariableAnalyzer` + `unused-variables` CLI)

New `cobolparser/analysis/unused_variables.py` (`UnusedVariableAnalyzer`),
following the existing `<Analyzer>().analyze(ast) -> <Report>` shape.
Detects DATA DIVISION items never referenced in the PROCEDURE DIVISION —
FILLER and synthetic `ANONYMOUS-<level>-<line>` names always excluded,
group items used-if-any-descendant-used, level-88 usage marks its parent
used, REDEFINES/OCCURS DEPENDING ON/RENAMES treated as real structural
dependencies. Backed by the new `unused-variables` CLI subcommand.

Two findings worth flagging for future sessions, both documented in the
new module's docstring rather than fixed here (out of scope for adding an
analyzer):

1. `expand_copybooks`'s `preserve_source_locations` parameter is threaded
   all the way to `_expand_source_recursive` but never actually populates
   `context.source_maps` — a no-op feature, not a working one. The new
   analyzer's `--exclude-copybook-variables` flag instead determines
   copybook provenance by diffing `collect_declared_items()` on an
   unexpanded parse against the expanded one (see
   `_parse_without_copybook_expansion` in `cli/parse.py`).
2. SCREEN SECTION / REPORT SECTION / COMMUNICATION SECTION are not
   modeled by the DATA DIVISION parser (only FILE/WORKING-STORAGE/
   LOCAL-STORAGE/LINKAGE are recognized section names) — their clauses
   get mis-parsed as nested WORKING-STORAGE data items (e.g. a SCREEN
   SECTION `COLUMN 5` clause becomes an item literally named `COLUMN`).
   Confirmed empirically against `tests/samples/screen_section_io.cbl`
   and `report_writer.cbl` while validating the new analyzer against the
   full sample corpus. Spawned as a separate follow-up task, not fixed
   here.

Updated [analysis.md](analysis.md) (new `UnusedVariableAnalyzer` section +
module map row), [cli.md](cli.md) (new `unused-variables` subcommand
section). Timestamps bumped to 2026-08-13T00:00Z.

## 2026-08-13 (SCREEN/REPORT/COMMUNICATION SECTION headers no longer corrupt WORKING-STORAGE)

`DataDivisionParser` (`data.py`) only recognized FILE, WORKING-STORAGE,
LOCAL-STORAGE, and LINKAGE as DATA DIVISION section headers. A SCREEN
SECTION, REPORT SECTION, or COMMUNICATION SECTION header was not a
recognized section boundary in either `parse_division`'s dispatch loop or
`_parse_section`'s break conditions, so whichever section scan was in
progress (almost always WORKING-STORAGE) silently absorbed the unrecognized
header token-by-token and kept going into the following section's own
level-numbered content. Two distinct corruption shapes resulted, both
confirmed empirically:
- SCREEN SECTION's clause keywords (`COLUMN`, `LINE`, `BLANK`, ...), which
  the data-item clause loop doesn't recognize either, produced spurious
  top-level `CobolDataItem`s literally named `COLUMN` etc. (real file:
  `screen_section_io.cbl` ballooned WORKING-STORAGE from 5 to 33 items).
- COMMUNICATION SECTION's own CD/record content was silently eaten with no
  trace, but any data item declared *after* it with no section header of
  its own (a loose but common real-world pattern) was wrongly merged back
  into WORKING-STORAGE (real file: `communication_module.cbl`, 5 → 12).

Fixed by adding `SCREEN`/`REPORT`/`COMMUNICATION` to the section-break-header
set (so any in-progress section scan stops there) and a new
`DataDivisionParser._skip_section()` that consumes the header and discards
the body up to the next section/division boundary, then registers an empty,
distinctly-named `CobolSection` (`SCREEN`/`REPORT`/`COMMUNICATION`) plus a
`has_screen`/`has_report`/`has_communication` division-metadata flag. These
three sections' own grammars (screen-field clauses, RD/report-group entries,
CD entries) are still not modeled -- their content, and any item declared
under them, is discarded rather than corrupting WORKING-STORAGE or another
section. Two refinements added on review:
1. The discard is no longer silent -- `_skip_section` records a
   `ParseResult.warnings` entry naming the section, matching this repo's
   established "recognized but degraded" convention (`errors=0, warnings=0`
   must not imply a complete AST).
2. `REPORT` (and, less commonly, `COMMUNICATION`/`SCREEN`) also appears as
   an ordinary clause word outside a section header -- an FD's `REPORT IS
   report-name.` clause (`examples/cobol/shamrice/report_test.cbl:32`) is
   exactly this. `parse_division`'s dispatch now only routes to
   `_skip_section` when the next token is literally `SECTION`
   (`_next_is_section_keyword`, mirroring `_parse_section`'s own lookahead
   for these headers), so a bare clause-word use falls through to the
   existing unknown-token skip instead of wrongly discarding whatever
   source follows it.
Pinned by `tests/regression/test_screen_report_communication_sections.py`
(23 cases), including end-to-end pins against the three real sample
fixtures above and the `report_test.cbl` FD-clause collision.

## 2026-08-13 (Unblock CI: mypy union-narrowing fix + black==26.3.0 drift on two unrelated files)

`main`'s CI (`typecheck` and `lint` jobs) had been red since 2026-08-12
(commits 94490a2a, 5600be5) — unrelated to this branch's dead-code fix, but
blocking its own PR checks regardless, so fixed here:

- **`statement_text.py`:** `hasattr(s, "to_dict")` doesn't narrow a
  `str | CobolExpression` union for mypy, so `render_condition_text(s)`
  (which only accepts `CobolExpression | None`) still saw the full union.
  Swapped for `isinstance(s, CobolExpression)` — mypy narrows that
  correctly, runtime behavior is identical. See [analysis.md](analysis.md).
- **`flowchart.py` / `test_statement_text.py`:** reformatted with the
  CI-pinned `black==26.3.0` (a newer local black had already reformatted
  them differently) — whitespace-only. See [generators.md](generators.md),
  [tests.md](tests.md).

Local `ruff`/`black`/`mypy` must be run at the exact `ruff==0.15.0
black==26.3.0 mypy==1.20.0` pinned in `.github/workflows/ci.yml` to match
CI — a newer local toolchain can pass locally and still fail CI.

## 2026-08-13 (DeadCodeAnalyzer: section-propagation sibling bug + 100% coverage)

Correctness review of `cobolparser/analysis/dead_code.py` requested by Sam.
One real logic bug found and fixed:

**`_propagate_section_references` resurrected unrelated dead siblings.**
Chaining upward (paragraph referenced -> section referenced) before downward
(section referenced -> all its paragraphs referenced) meant a paragraph
referenced only via a plain `PERFORM child-paragraph` bootstrapped its whole
section into "referenced," and the downward pass then broadcast that to
every sibling paragraph -- even ones nothing PERFORMs/GOes TO and that
fall-through never reaches. Fixed by reordering so downward only ever sees
sections that were *directly* referenced before the function ran. Pinned by
`TestSectionPropagationDoesNotResurrectSiblings`
(`tests/unit/analysis/test_dead_code.py`).

Also closed every remaining coverage gap in the module (was 95.77%, now
100% line + 100% branch): inline PERFORM with no target, MERGE without an
output procedure / without THRU, a THRU range with a falsy start, a blank
SECTION name, invalid (`"."`) paragraph names inside a section, a duplicate
top-level paragraph name, an ENTRY statement with no parent paragraph, and
an ALTER alteration with a blank target -- 12 new tests, all defensive
branches exercised directly rather than via `parse_cobol()` since the
parser itself never emits these malformed shapes.

Updated [analysis.md](analysis.md) (`## DeadCodeAnalyzer`). Timestamp
bumped to 2026-08-13T00:00Z.

## 2026-08-12 (Program-flow label fidelity: ASCII, `<`/`>` escaping, arm summaries)

Driven by VS Code Program Flow webview feedback (mocky-mock-vscode-extension,
same session). Three fixes in `generators/flowchart.py` +
`analysis/program_flow/`:

1. **ASCII-only emitted labels** — exit terminals now `"{kind} @ {line}"`
   (was `·`), `GOTO_DEPENDING` now `GO TO ... DEPENDING` (was `…`); cp1252
   CLI stdout vs UTF-8 consumers rendered them as `�`.
2. **`_escape_mermaid_label()`** — `<`/`>` → `#lt;`/`#gt;` and `"` → `'` in
   every Mermaid label; Mermaid v11 (htmlLabels:false) swallows a bare `>`,
   and `#quot;` (unlike `#lt;`/`#gt;`) renders as literal `&quot;`.
3. **`BranchArm.summary`** (new additive field) via new
   `analysis/program_flow/statement_text.py`
   (`summarize_statement`/`summarize_arm`); both generators render it in arm
   boxes with a `+N more` marker and drop empty IF arms.

Updated [generators.md](generators.md) ("Label fidelity" section),
[analysis.md](analysis.md) (statement_text + `@` separator),
[tests.md](tests.md) (+37 tests). Timestamps bumped to 2026-08-12T18:00Z.

## 2026-08-12 (Bug review: Decimal witness pipeline, DIVIDE mode + folding, `**` text, typed-literal/ref-mod fidelity)

Cross-repo bug review (cobol-parser + mocky-mock, same session). Five
fixes, all pinned by `tests/regression/test_bug_review_2026_08_12.py`:

1. **Decimal end-to-end in the gen-fixtures numeric pipeline** (HIGH).
   `domains.NumericDomain`'s bounds/exclusions, `_apply_numeric`'s literal
   parsing, `_rendered_numeric_ok`, `scenarios._picture_ceiling`, and
   `ValueFactory._format_number`/`_fit_domain_value` all used float64, so
   a literal past ~16 significant digits was silently rounded:
   `IF ACCT-ID = 123456789012345678` (PIC 9(18)) produced fixture rows of
   `...680` while `ScenarioCoverage` reported the arm as targeted -- and
   `_rendered_numeric_ok` re-checked in float, so the corruption passed
   its own backstop. All Decimal now, `localcontext(prec=80)` where the
   widest PICTUREs could outgrow the default 28-digit context.
   [analysis.md](analysis.md), [generators.md](generators.md).
2. **`DivideStatement.division_mode`** records BY vs INTO;
   `const_fold._fold_divide` folds the unambiguous DIVIDE forms (exactness
   verified by multiply-back at prec 80); REMAINDER targets now poisoned
   by the arm/handler write scan too. [ast-models.md](ast-models.md),
   [analysis.md](analysis.md).
3. **COMPUTE `**` text**: the serialized `expression` string re-merges the
   two lexed `*` tokens (the tree already did) -- was `2 * * 3`.
4. **Typed-literal prefixes survive** in MOVE source / DISPLAY item text
   via `Token.raw_value` (`X"41"` no longer collapses to `"41"`).
5. **Ref-mod joins tight**: `_join_source_parts` renders `WS-X(2:3)`, not
   `WS-X(2 : 3)`. [parser.md](parser.md).

Also refreshed `reports/open-findings.md` / the follow-up audit header:
every headline item of the 2026-08-12 follow-up audit was already fixed
at HEAD (`b495f26`, PR #139) but both files still claimed "not yet
fixed"; re-verified each by direct reproduction before rewording.

## 2026-08-11 (Mermaid flowchart edge labels broke on unquoted parens/brackets)

A user's Program Flow webview (mocky-mock-vscode-extension) hit a Mermaid
parse error rendering `legacy-application/cobol/DEPTBMP.cbl`:
`Parse error ... UNTIL NO-MORE-MSGS (loop)| N_2000_PROCE ... got 'PS'`.
Root cause: `MermaidFlowchartGenerator._edge_style`/`generate` in
`cobolparser/generators/flowchart.py` wrote edge labels unquoted inside
Mermaid's `-->|label|` syntax. Mermaid's flowchart lexer reads an unquoted
`(` or `[` inside such a label as the start of a node shape (`PS`/`SQS`
tokens), not literal text -- so any `PERFORM UNTIL ... (loop)` annotation,
`CALL_DYNAMIC`'s `"CALL (dynamic)"` label, or `[THRU n]` badge broke
parsing. Fixed by wrapping the joined label text in quotes, reusing the
`#quot;` entity escape branch/arm labels already used for embedded double
quotes. DOT output is unaffected (`_dot_str` already quotes every label).

Verified against a real Mermaid 11.16.1 parse (the version pinned in the
VS Code extension): the pre-fix `DEPTBMP.cbl` output fails to parse, the
post-fix output parses cleanly. Full writeup in
[generators.md](generators.md)'s "Flowcharts" section; new/updated tests
noted in [tests.md](tests.md).

## 2026-08-12 (Core audit fixes: EVALUATE selector contract restored, MOVE source join, expect()-at-EOF, statistics snapshot, sequence-numbered ID division, path-resolver precedence + honored parameter, ReDoS regex removed, compiled-lexer warnings reset, dead code)

All pinned by `tests/regression/test_audit_2026_08_12_core.py` (plus the
pre-existing `test_evaluate_space_literal_when.py` for T-H1).

1. **T-H1 — EVALUATE WHEN selector contract restored** (`evaluate_parser.py`):
   commit `17fa400` routed every selector token through
   `condition_token_text()`, quoting *all* string literals and breaking the
   pinned contract (non-blank literals unquoted, blank/whitespace-only
   literals quoted). Reverted the selector path to blank-only re-quoting;
   subjects keep `condition_token_text()`. See [parser.md](parser.md).
2. **P-B1 — MOVE multi-word source corruption** (`move_parser.py`):
   `"".join` → subscript/sign-aware `_join_source_parts`. See parser.md's
   new "Core audit fixes (2026-08-12)" section.
3. **P-B2 — `TokenStream.expect()` matched anything at EOF**
   (`core/token_stream.py`): empty-valued tokens now mismatch. See parser.md.
4. **P-B3 — `ParseResult.statistics` clobbered on parser reuse**
   (`parser.py`, `plugins/core.py`): results now get
   `ParseStatistics.copy()` snapshots. See parser.md.
5. **P-B4 — `_ID_DIV_RE` vs sequence-numbered fixed format** (`parser.py`):
   optional exactly-6-char `[0-9 ]{6}` prefix allowed. See parser.md.
6. **P-B6 — Tier-2 full-filename index key was last-directory-wins**
   (`preprocess/path_resolver.py`): now first-configured-directory-wins in
   every tier. See [preprocessing.md](preprocessing.md).
7. **S-1 — exported-but-unused `COPY_PATTERN` regex with exponential
   backtracking removed** (`preprocess/copy_statement_parser.py`). See
   preprocessing.md.
8. **P-B5 — compiled lexer duplicated warnings across `tokenize()` calls**
   (`_lexer_fast.pyx`, checked-in `_lexer_fast.c` regenerated with Cython
   3.2.9 — note: this environment's Cython lacks the zstd string-compression
   branch the previous `.c` carried). See [lexer.md](lexer.md).
9. **P-D1 — `expand_copybooks()` ignored a caller-supplied `path_resolver`**
   (`preprocess/copybook_expander.py`): honored now; this also makes
   `parse_files_with_copybooks`' shared-resolver reuse real. See
   preprocessing.md.
10. **Dead code removed:** four space-containing (unreachable)
    `CobolLexer.KEYWORDS` entries (`"KEY IS"`, `"WITH LOCK"`, `"NO REWIND"`,
    `"NO ADVANCING"` — see lexer.md); a discarded
    `context.get_cache_key(...)` call in
    `copybook_expander._expand_source_recursive`; the never-used
    `_file_content_cache` dict in `batch.parse_files_with_copybooks`
    (docstring corrected — the real sharing is the reused `PathResolver`
    plus the module-level LRU file cache).

## 2026-08-12 (Test-infrastructure audit fixes: structural marker enforcement, placeholder skips implemented, assert-free tests strengthened)

Three test-suite audit findings fixed; no `cobolparser/` source changes.

1. **Markers enforced per directory (T-M1).** `-m contract` selected only
   66 of the 386 tests in `tests/contracts/` (2 of 21 files carried the
   marker), `-m io` only 69 of the 183 in the four io/io_statements
   directories, and 3 of 29 `tests/integration/` files lacked
   `integration`. Added six per-directory `conftest.py` files
   (`tests/contracts/`, `tests/integration/`, `tests/unit/io_statements/`,
   `tests/integration/io_statements/`, `tests/integration/io/`,
   `tests/contracts/io_statements/`) whose
   `pytest_collection_modifyitems` hook adds the directory's marker to
   every collected item under it, so new files cannot drift out of `-m`
   selection. After: `-m contract` 386 (== directory total), `-m io` 183
   (== the four directories' total), `-m integration` 1686 (all 1647
   in-directory + 39 explicitly-marked tests elsewhere). Existing in-file
   `pytestmark` lines were kept as harmless duplicates. See
   [tests.md](tests.md)'s new "Per-directory marker enforcement" section.

2. **12 "Implementation pending - Phase 6/7" skips implemented (T-M2).**
   The phases shipped long ago. All 12 permanently-skipped placeholders in
   `tests/unit/test_copybook_expansion.py`,
   `tests/integration/test_copybook_expansion_integration.py`, and
   `tests/contracts/test_copybook_expansion_contracts.py` now carry real
   assertions against what the expander exposes today: COPY REPLACING
   (parse + whole-text-word substitution), `parse_cobol_with_expansion`
   signature/ParseResult/end-to-end AST content, error tracing
   (`CopybookNotFoundError` names the member and search paths), nested
   attribution via `included_copybooks` real paths in inclusion order,
   line-number placement of expanded content, `CopyStatement.
   source_location` accuracy, and the `source_location_map` contract
   (dict when `preserve_source_locations=True`, None otherwise, key
   omitted from `to_dict()` when disabled). Note: the expander's
   line-by-line `source_location_map` is exposed but never *populated*
   (the tracking branch in `copybook_expander.py` is a documented no-op
   `pass`), so the tests pin the exposed contract, not per-line accuracy.

3. **Assert-free/tautological tests strengthened (T-M3).** All print-only
   test bodies and all 16 tautological `assert isinstance(result.success,
   bool)` checks across `tests/unit/test_comprehensive_real_world.py`,
   `tests/unit/test_parser_capabilities.py`, and
   `tests/unit/test_basic_real_world_parsing.py` replaced with real
   assertions -- every sampled pattern parses cleanly today, so each test
   now asserts `result.success` (with errors in the failure message) plus
   `result.ast is not None`, and where cheap, AST content (program name,
   division presence, data-item names, CALL statement count). The pure
   print "status report" test became a real capability sweep asserting
   the five historically-doubtful categories all parse.

## 2026-08-12 (Analysis/generators audit: 12 verified findings across const_fold, boundary_inventory, domains, flowchart, crud_matrix, io_sequence, value_tracker, program_layout, scanner)

Twelve audit findings fixed in `cobolparser/analysis/` and
`cobolparser/generators/`; regression tests in
`tests/regression/test_audit_2026_08_12_analysis.py` (one class per finding)
plus `tests/unit/test_flowchart_generator.py::TestExternalCallEndToEnd`.

1. **A-A1 `const_fold.py`:** the fold walk never poisoned statements nested
   in conditional handler bodies (`AT END`/`INVALID KEY`/`ON SIZE ERROR`/
   `ON OVERFLOW`/`ON EXCEPTION`/`AT EOP` and NOT variants) -- `MOVE 'N' TO
   WS-EOF. READ F AT END MOVE 'Y' TO WS-EOF. DISPLAY WS-EOF.` emitted
   `field_equals WS-EOF="N"` even when AT END fires. `_walk_one` now poisons
   every field any handler body could write, AFTER the statement's own fold
   (so a handler writing the statement's own target wins), via the new
   `_HANDLER_BODY_ATTRS` tuple.
2. **A-A2 `generators/flowchart.py`:** external-call nodes read
   `ext.get("target")` but `EdgeCollector.process_call` emits `"program"`,
   so EXT_ nodes never rendered from real analyzer reports; also
   `edge.target` is uppercased while `call_info["program"]` keeps original
   case, so ids disagreed for lowercase CALL literals. New module-level
   `_external_call_target()` reads `"program"` (with `"target"` kept as a
   hand-built-dict fallback) and uppercases, used by both generators.
3. **A-A3 `crud_matrix.py`:** `_collect_open_modes` used `stmt.open_mode`
   (first mode group) for every file; now reads
   `IOOpenStatement.file_modes` per file, falling back to `open_mode`.
   `OPEN INPUT IN-FILE OUTPUT OUT-FILE` records INPUT/OUTPUT respectively.
4. **A-A4 `const_fold.py`:** `_ordered_paragraphs` appended section-owned
   paragraphs before top-level ones, inverting source order for mixed
   programs and emptying PERFORM THRU ranges spanning both. Now interleaves
   by `location.line`, mirroring `program_flow/scanner.py` /
   `dead_code.py`'s already-fixed collection. (The analysis.md claim that
   it "mirrors scanner.py (sections before top-level paragraphs)" was
   wrong on both counts and is corrected.)
5. **A-A5 `boundary_inventory.py` / `constraints.py`:** both
   `_NESTED_STATEMENT_ATTRS` tuples omitted `on_size_error`,
   `not_on_size_error`, `not_on_overflow`, `not_at_eop_clause` -- a
   `CALL 'ERRLOG'` inside `ON SIZE ERROR` produced no boundary. All four
   added to both.
6. **A-A6 `domains.py`:** `NumericDomain.pick()` used a raw float midpoint
   with float-equality exclusion checks; `PIC 9` with `ne "4"` picked 4.5,
   which RENDERED (rounded) back to the excluded "4". Candidates are now
   enumerated on the field's decimal grid (integer units of `10**-d`),
   exclusions quantized before comparison, and `solve()` re-verifies the
   RENDERED witness against the domain as a defensive backstop.
7. **A-A7 `boundary_inventory.py`:** `_classify_file_op` never set
   `status_field` for OPEN/CLOSE, so `scenarios.py`'s "OPEN -> FILE STATUS
   35" error family could never fire. Both now resolve it via
   `index.file_facts(...)`, same as READ/DELETE/START/UNLOCK.
8. **A-B1 `io_sequence.py`:** ANY `StopStatement` was treated as program
   termination (clearing open-file state); only `STOP RUN` is
   (`stop_type == "RUN"`), matching `dead_code.py`/`scanner.py`'s
   `_is_terminator`. `OPEN, STOP 'literal', READ, CLOSE` is now clean.
9. **A-B2 `boundary_inventory.py`:** SQL/CICS/DLI keys were computed
   against previously *assigned* (already-shortened) same-category keys --
   order-dependent, and the first site could keep a key that is a prefix
   of a sibling's text (`SELECT A FROM T` / `SELECT B FROM T` yielded
   `SELECT` + `SELECT B`). Now two-pass: `analyze()` pre-collects every
   site's FULL normalized text per category (`_collect_exec_texts`), and
   each site's `_unique_prefix` compares against all OTHER sites' full
   texts (`_other_texts`) -- order-independent, prefix-unique keys
   (`SELECT A` / `SELECT B`). Serialized bundle keys can change for
   affected programs; the per-(program, seed) byte-identity contract holds.
10. **A-B3 `value_tracker.py`:** `_extract_literal_value` echoed any
    identifier-shaped string, so `MOVE WS-INPUT-PROG TO WS-TARGET`
    (untracked source) recorded the NAME "WS-INPUT-PROG" as a possible
    CALL value. `_track_move_statements` now gates recording on the new
    `_is_definite_literal` (quoted / numeric / figurative only); an
    untracked identifier source instead marks the target's value set
    incomplete (`_incomplete_variables`, propagated through var-to-var
    MOVEs) and `_populate_dynamic_calls` stamps
    `possible_values_incomplete=True` metadata on the CALL node.
11. **A-B4 `generators/data/program_layout.py`:** duplicate level-88
    condition names overwrote last-one-wins with no `ambiguities` entry.
    `_condition_index` now keeps every parent; a lookup that maps to more
    than one distinct parent field returns `None` and records the
    ambiguity, matching `resolve()`/`record_named()` semantics.
12. **A-C1 `program_flow/scanner.py`:** `scan_statements`' empty-section
    branch set `self._current_procedure` and did nothing else --
    `CobolSection` cannot carry statements of its own, so the branch was
    an unreachable-effect no-op; deleted.

Also fixed two pre-existing analysis.md errors while updating it:
`LinkageChecker` uses `.check(ast)` (not `.analyze`), and `IOViolationKind`'s
real names are `READ_BEFORE_OPEN`/`WRITE_BEFORE_OPEN`/`CLOSE_NOT_OPEN`.

## 2026-08-11 (PR #135 Copilot review: fall-through termination checks were last-statement-only / has_stop_run-etc. were nesting-blind)

Copilot's automated review on PR #135 (the fall-through fix below) caught
two related precision bugs in the same area, both fixed in the same pass:

1. Both `DeadCodeAnalyzer._terminates` and `ProcedureScanner`'s new GO TO
   tracking checked only `para.statements[-1]` -- a hard terminator or
   unconditional GO TO earlier in a paragraph (not its last statement)
   still unconditionally fires when reached, so trailing statements after
   it are themselves unreachable and don't change whether the paragraph
   falls through. Fixed by extracting a static `_is_terminator(stmt)`
   helper in each module and checking `any(...)` over every top-level
   statement instead of indexing `[-1]`.

2. `ProgramFlowAnalyzer.build_fall_through_edges` suppressed fall-through
   via `node.has_stop_run`/`has_goback`/`has_exit_program`, but those flags
   are set by the recursive statement walk whenever it encounters the
   statement *anywhere*, including nested inside an IF/EVALUATE arm --
   exactly the same "conditional treated as unconditional" bug the GO TO
   half of this PR fixes, just for the other three terminator kinds.
   Replaced with the same unified `_is_terminator`-over-top-level-
   statements check (renamed the threaded set from
   `_unconditional_gotos`/`unconditional_gotos` to
   `_terminating_paragraphs`/`terminating_paragraphs` throughout
   `scanner.py`/`graph.py`/`analyzer.py` since it now covers all four
   terminator kinds, not just GO TO). The `has_stop_run`/`has_goback`/
   `has_exit_program` fields themselves are untouched -- other consumers
   (flowchart-generator terminal nodes, `is_exit_point`) intentionally
   want the broader "anywhere in the paragraph" semantics.

Full writeups (including the one known, deliberately-unaddressed boundary
case -- a terminator inside an unconditional bare `PERFORM ... END-PERFORM`
block) in [analysis.md](analysis.md)'s `DeadCodeAnalyzer` and
`ProgramFlowAnalyzer` sections. New tests:
`test_terminator_earlier_in_paragraph_still_cuts_off_fall_through`
(`test_dead_code.py`), and
`test_terminator_earlier_in_paragraph_still_suppresses_fall_through` +
`test_conditional_stop_run_inside_if_does_not_suppress_fall_through`
(`test_program_flow.py`). Full suite green (5211 unit tests; `ruff`,
`black --check`, `mypy` clean on touched files).

## 2026-08-11 (Dead Code & Program Flow audit: remaining 2 of 7 findings -- fall-through concept and conditional GO TO)

Closes out the "Dead Code & Program Flow" analyzer audit (the artifact this
session reviewed found 5 of its 7 findings already fixed and merged to
main under various branches/commits from earlier sessions, and 2 genuinely
unaddressed -- confirmed by reading the current code, not by trusting
commit messages). Two unrelated local branches
(`claude/dead-code-section-550f0e`, `claude/optimistic-lumiere-bb902f`)
already contained a correct, well-tested fix for the conditional-GO-TO
finding, but both branched off a point *before* the paragraph-ordering fix
landed on main via a different implementation (`b0b204d`), so neither
could be cleanly merged or cherry-picked -- the underlying logic was
ported by hand onto current main's `scanner.py` (which also already has
the unrelated explicit-work-stack rewrite, `4e53724`, that those stale
branches never saw).

**Finding #1 -- DeadCodeAnalyzer had no fall-through concept at all.**
Fixed in `cobolparser/analysis/dead_code.py`: new `_collect_fallthrough_refs`
+ `_terminates`, gated on the predecessor already being reachable (not just
non-terminating) to avoid falsely un-deadening a chain of paragraphs that
are themselves never reached. See [analysis.md](analysis.md)
(`DeadCodeAnalyzer` section) for the full writeup.

Fixing this correctly required updating 21 pre-existing tests in
`tests/unit/analysis/test_dead_code.py`: they used `CONTINUE` (or a bare
`DISPLAY`) as a paragraph-body placeholder with no terminator, relying on
the analyzer's total blindness to fall-through to keep an intentionally
"dead" paragraph dead. Under the fix, several of those paragraphs are
*genuinely* reachable per real COBOL semantics (the fixture author's intent
was "isolated dead stub", but the actual shape was "straight-line code"),
so this wasn't test-breakage to route around -- it was the fixtures being
wrong about what they were testing. Added `STOP RUN` to the paragraph
immediately before each fixture's intentionally-dead island. See
[tests.md](tests.md).

**Finding #5 -- conditional GO TO treated as unconditional fall-through
terminator.** Fixed in `cobolparser/analysis/program_flow/graph.py` +
`scanner.py` + `analyzer.py`: `build_fall_through_edges` now suppresses
only when a paragraph's own last top-level statement is a bare
(non-`DEPENDING`) `GO TO` (`ProcedureScanner`-populated
`unconditional_gotos` set), not merely "any GOTO edge exists" refined by a
now-redundant `perform_count == 0` guard (dropped in the same change --
see [analysis.md](analysis.md)'s `ProgramFlowAnalyzer` section for why it
had no remaining justification once last-statement tracking exists).
`DeadCodeAnalyzer._terminates` (above) applies the identical rule
independently, by design -- the two analyzers deliberately don't share
code, per this module's existing architecture.

Verification: full `tests/unit` (5206 passed), `tests/integration` +
`tests/regression` (2411 passed; the only 7 failures --
`test_evaluate_space_literal_when.py` and
`test_normalize_line_number_preservation.py` -- were confirmed pre-existing
on a clean `main` checkout via `git stash`, unrelated to this change, a
stale Cython-extension issue). `ruff check`, `black --check`, and `mypy`
clean on all touched files.

## 2026-08-11 (Whole-branch final review: 4 composition bugs across the 7-task Mermaid/DOT flowchart-fidelity plan)

A final review of the whole branch (the plan below, all 7 tasks individually
reviewed clean) caught four composition bugs no single task's reviewer could
see — each one only surfaces when two tasks' output combines in the same
report. Fixed all four, plus two should-fix test-coverage gaps, in one pass
per the review's own instruction (no second fix wave):

* **Critical: Mermaid `linkStyle` indices off by the terminal-node link
  count.** `flowchart.py`'s exit-statement terminal-node loop (Task 5) runs
  *before* the edges loop (Tasks 4/6), emitting one `{nid} --> {exit_id}`
  link per paragraph with a recorded exit statement — but the edges loop's
  own `link_index` counter still started at 0, as if it were the only
  link-emitting loop in the diagram. Since Mermaid's `linkStyle N`
  addresses links by definition order across the *whole* diagram, every
  terminal-node link shifted every subsequent `linkStyle` index, so
  recursion/GO TO coloring landed on the wrong arrow in any program with
  both a terminal node and a styled edge — i.e. almost every real program.
  Fixed by seeding `link_index` with `terminal_link_count` (a new counter,
  incremented only when the terminal-node loop actually appends a link)
  before the edges loop starts. Verified empirically with a hand-built
  report (paragraph `C` has `STOP RUN`; paragraphs `A`/`B` form a
  `PERFORM_RECURSION` cycle): before the fix, the recursion edge `B --> A`
  (arrow position 2 in definition order) got `linkStyle 1`, addressing
  `A --> B` instead; after the fix it correctly gets `linkStyle 2`. New
  regression test:
  `test_linkstyle_index_accounts_for_terminal_node_links` in
  `tests/unit/test_flowchart_generator.py`.
* **Important: SORT/MERGE `... THRU ...` ranges vanished from both
  diagrams.** Task 6 made both generators skip any edge whose type ends in
  `_THRU`, relying on the *base* edge already carrying `thru_target`/
  `range_members` for a `[THRU n]` badge — true for `process_perform`
  (`edges.py`), which has always set those fields on both the base PERFORM
  edge and its `PERFORM_THRU` sibling, but `process_sort`/`process_merge`
  in the same file only ever set them on the `*_THRU` edge. Once the
  generators started unconditionally skipping the `*_THRU` edge, the range
  was lost entirely: no second arrow (correctly suppressed) *and* no badge
  (nothing on the base edge to badge). This was a regression from
  pre-Task-6 behavior (the second arrow used to at least show the range),
  not just a missing feature. Fixed by restructuring `process_sort`'s
  input/output-procedure handling and `process_merge`'s output-procedure
  handling to compute the range once and pass `thru_target`/`range_members`
  to *both* edges, mirroring `process_perform`. New tests:
  `test_sort_input_procedure_base_edge_carries_thru_range`,
  `test_sort_output_procedure_base_edge_carries_thru_range`,
  `test_merge_output_procedure_base_edge_carries_thru_range` in
  `tests/unit/analysis/test_program_flow.py` (unit-level, asserting the
  edge fields directly); `TestSortThruEndToEnd` in
  `tests/unit/test_flowchart_generator.py` (real COBOL through
  `parse_cobol` → `ProgramFlowAnalyzer` → both generators — confirmed these
  two tests fail against the pre-fix `edges.py` via `git stash` and pass
  against the fix, so they pin the actual repair, not just the
  already-correct badge-rendering consumer).
* **Important: terminal node id collided with the `XXXX-EXIT` COBOL
  idiom.** Both generators built a terminal node's id as `f"{nid}_EXIT"`.
  `PERFORM X THRU X-EXIT` is common enough that a program can legitimately
  contain a *real* paragraph literally named e.g. `9000-TERM-EXIT` — its
  own sanitized id (`N_9000_TERM_EXIT`) collided with paragraph
  `9000-TERM`'s synthetic terminal-node id, silently merging two distinct
  nodes in both Mermaid and DOT output. Fixed with a new module-level
  `_unique_exit_id(nid, paragraph_ids)` (shared by both generator classes):
  builds the set of every real paragraph's sanitized id up front, falls
  back from `_EXIT` to `_FLOWEXIT`, then to an incrementing numeric suffix,
  on collision. New tests (one per generator, proving the two nodes now
  get distinct ids): `test_terminal_id_does_not_collide_with_real_exit_paragraph`
  in both `TestMermaidFlowchartGenerator` and `TestDotFlowchartParity`.
* **Important: RETURN incorrectly rendered as a program-terminal node.**
  `scanner.py`'s `ReturnStatement` handling called
  `_record_exit_statement(node, "RETURN", stmt.location)`, so Task 5's
  terminal-node rendering drew a red double-circle for RETURN — but RETURN
  reads the next record from a sort/merge file, it does not terminate
  anything, and `scanner.py` deliberately never adds RETURN's paragraph to
  `self._exit_points` (`node.is_exit_point` stayed correctly `False` for
  it) — the terminal-node rendering directly contradicted the analyzer's
  own exit-point classification. Fixed by removing that one call;
  `node.has_return` and the `AT END`/`NOT AT END` nested-statement scanning
  are unaffected. New regression test:
  `test_return_does_not_record_exit_statement_kind` in
  `tests/unit/analysis/test_program_flow.py` (real COBOL, a RETURN inside a
  SORT OUTPUT PROCEDURE — the common real-world shape).
* **Should-fix: `FlowNode` exit-statement field test-coverage gaps.** Added
  to `TestExitStatementLocation`
  (`tests/unit/analysis/test_program_flow.py`):
  `to_dict()` presence/absence of both `exit_statement_kind` and
  `exit_statement_location` (as a dict, via `SourceLocation.to_dict()`);
  `EXIT PROGRAM` sets `exit_statement_kind == "EXIT PROGRAM"`; the
  first-write-wins rule (`STOP RUN` in an IF's THEN arm, `GOBACK` in its
  ELSE arm — asserts `STOP RUN` wins, since it's scanned first).

Updated: [analysis.md](analysis.md) (exit-statement subsection — explicit
RETURN-exclusion note, first-write-wins note, `to_dict()` presence rule),
[generators.md](generators.md) (all three styling bullets gained a
"bug fixed 2026-08-11" note explaining what was wrong and why, plus the new
reference tests). Full requested regression scope (`tests/unit/analysis/
tests/unit/test_flowchart_generator.py tests/integration/`): 2530 passed, 4
skipped, 0 failures. `tests/contracts/`/`tests/regression/` also run per
review request: 1150 passed, 6 pre-existing failures in
`test_normalize_line_number_preservation.py` (unrelated to this pass —
confirmed present on the unmodified branch tip via `git stash`, same
Cython-vs-pure-Python normalize_fixed_format issue noted in the 2026-08-10
entry below). `ruff check .`, `black --check .` (2 files needed
reformatting, applied), `mypy cobolparser/` all clean on touched files.

## 2026-08-11 (Mermaid/DOT flowchart fidelity: real condition text, exit nodes, recursion/GOTO styling, THRU badges)

Seven-task plan (`docs/superpowers/plans/2026-08-11-mermaid-flow-fidelity.md`)
closing four fidelity gaps between `cobolparser/generators/flowchart.py`'s
diagrams and the actual control flow they're meant to represent, plus the
analysis-layer data those diagrams needed and didn't have:

* **Real condition text** (Tasks 1-3): `BranchNode.condition_text` and
  PERFORM UNTIL's loop-test label previously showed only the AST node's
  type TAG (`"COMPARISON"`), never the actual condition. New
  `cobolparser/analysis/program_flow/condition_text.py` ->
  `render_condition_text()` reconstructs real COBOL text from the
  `ConditionalExpression`/`LogicalExpression` tree, correctly parenthesizing
  nested AND/OR/NOT, with a graceful fallback chain (raw operand ->
  `raw_condition` metadata -> type tag) so no caller ever gets nothing.
  String-literal quotes are preserved through condition-token collection
  rather than re-guessed at render time (a separate fix landed mid-plan,
  caught before it could produce `WS-FLAG = Y` instead of `WS-FLAG = 'Y'`).
* **Exit-statement terminal nodes** (Tasks 4-5 for Mermaid, Task 7 for DOT):
  `FlowNode` gained `exit_statement_kind`/`exit_statement_location`
  (`STOP RUN`/`GOBACK`/EXIT-family verbs), tracked by `scanner.py`. Both
  generators now draw a distinct terminal node per exit statement
  (Mermaid: `(((...)))` + `terminal` classDef; DOT: `shape=doublecircle`),
  positioned after the main node loop and before external-call nodes,
  respecting `show_unreachable` the same way the main node loop does.
* **Recursion/GO TO edge color distinction** (Task 4 for Mermaid, Task 7
  for DOT): new module-level `_recursion_pairs()` /
  `_PERFORM_EDGE_TYPE_VALUES` / `_GOTO_EDGE_TYPE_VALUES` (shared by both
  generator classes, not duplicated) classify each edge; a PERFORM edge
  closing a `PERFORM_RECURSION` cycle gets gold-dashed styling, any GO
  TO-family edge gets magenta-dashed styling. Mermaid via `linkStyle N
  <css>` lines (index `N` counts only *emitted* edges — a hidden
  fall-through edge must not consume an index, pinned by
  `test_linkstyle_index_skips_hidden_edges_correctly`); DOT via
  `color`/`style` attributes directly on the edge statement.
* **`[THRU n]` edge-label badges instead of a duplicate arrow** (Task 6 for
  Mermaid, Task 7 for DOT): a `PERFORM A THRU C`-style edge previously drew
  *two* arrows (one to the range start, one spanning the whole range) — now
  collapses to one arrow (to the range's first member) badged `[THRU n]`.
  Both generators' edges loops skip any edge whose type ends in `"_THRU"`
  unconditionally. **Task 7 finding:** DOT's edges loop was missing this
  skip entirely before this task (Mermaid gained it in Task 6) — a real
  parity bug, not just a missing style: without it, DOT rendered a
  redundant full-span arrow alongside the badge on every THRU range.

Updated: [analysis.md](analysis.md) (`ProgramFlowAnalyzer` section — new
condition-text-rendering and exit-statement-tracking subsection),
[generators.md](generators.md) (`Flowcharts` section — new subsection
documenting all three edge/node styling features across both generators).
New/extended tests: `tests/unit/test_flowchart_generator.py` gained
`TestMermaidFlowchartGenerator`'s linkStyle/terminal-node/THRU-badge cases
(Tasks 4-6) and a new `TestDotFlowchartParity` class (Task 7, 4 tests).
Task 7 also corrected two pre-existing DOT tests
(`test_fall_through_hidden_by_default`/`_shown_when_enabled`) whose
`"dashed" not in out` assertion became a false proxy once GOTO edges
legitimately gained `style="dashed"` — reworded to assert on the
FALL_THROUGH edge's own text instead, preserving the tests' original
intent (verify fall-through-specific visibility, not overload an
increasingly-ambiguous substring). Full suite: 7944 passed / 13 skipped / 1
xfailed (6 pre-existing, unrelated failures in
`test_normalize_line_number_preservation.py`, confirmed present on the
unmodified branch tip via `git stash`), 91.44% coverage. `ruff check .`,
`black --check .`, `mypy cobolparser/` all clean. Task 7 commit `0db3a69`.

## 2026-08-10 (Copybook-triggered comment-line drift in normalize_fixed_format)

GitHub issue #123: `program-flow`'s `location.line` drifted backward from a
paragraph's real source line by one per full-line comment anywhere earlier
in the file, but only when a `COPY` statement preceded it — traced to
`normalize_fixed_format`'s `flush_parts()` silently dropping (no
placeholder at all) a full-width, blank-indicator physical line whose
program-text is itself entirely blank. That exact shape never arises in a
plain fixed-format parse, only after `copy_statement_parser.
remove_comment_lines` blanks a `*`-comment line ahead of a second
`normalize_fixed_format` pass over copybook-expanded source. Fixed in both
`cobolparser/preprocess/__init__.py` and `cobolparser/_preprocess_fast.pyx`
by tracking whether a logical line was actually started rather than
inferring it from whether its merged text is non-empty. Rebuilt the Cython
extension in-place to regenerate `_preprocess_fast.c`. Updated:
[preprocessing.md](preprocessing.md) (Line-Number Preservation section).

## 2026-08-06 (CI no longer runs the full pytest suite automatically)

Requested change: too many tests (~5,969) to run on every push/PR; run them
locally instead. In `.github/workflows/ci.yml`, replaced the `test` job's
automatic-on-push/PR pytest run with a new `build` job (matrix Python
3.11/3.12/3.13: `pip install -e ".[dev,fast]"` + `python setup.py build_ext
--inplace`, no tests) that runs on every push/PR as before. The original
`test` job (`pytest tests/ -v`) is kept in the file but gated with
`if: github.event_name == 'workflow_dispatch'`, so it's available as a
manual Actions-tab trigger when CI needs to confirm the full suite, without
slowing down normal push/PR runs. Updated: [tests.md](tests.md) (CI/CD
section), root `CLAUDE.md` (CI/CD section).

## 2026-08-06 (Unbounded OCCURS count in test-data generation)

Code-review finding: `generators/data/layout.py::_occurrence_indexes` read
the OCCURS numeral straight from the parser with no upper bound, then
materialized `list(range(1, times + 1))`. Confirmed live: `05 TBL OCCURS
5000000 TIMES PIC X.` made `flatten_record()` take ~47s and add ~2.6GB
resident memory. `DataGeneratorOptions.max_occurs` defaults to no cap for
both `gen-data` and `gen-fixtures`, and `gen-fixtures` didn't even expose
the `--max-occurs` flag that `gen-data` did.

Fixed with a hard ceiling, `_MAX_OCCURS_HARD_CAP = 10_000` in
`generators/data/layout.py`, applied inside `_occurrence_indexes`
regardless of caller config (i.e. it also clamps an explicit `max_occurs`
larger than the ceiling) — same pattern as the existing
`_MAX_RANGE_EXPANSION` cap on level-88 THRU ranges. Added the missing
`--max-occurs` flag to the `gen-fixtures` CLI, threaded into its
`DataGeneratorOptions`. Re-ran the 5,000,000-occurrence repro after the fix:
0.18s / ~5MB, 10,000 specs. New tests:
`test_pathological_occurs_count_is_hard_capped` and
`test_max_occurs_beyond_hard_cap_is_still_clamped` in
`tests/unit/test_copybook_data_generator.py`;
`test_max_occurs_flag_defaults_to_none`,
`test_max_occurs_flag_parses`, `test_max_occurs_flag_is_accepted_end_to_end`
in `tests/unit/cli/test_gen_fixtures_cli.py`. Updated:
[generators.md](generators.md) (flattening rules table note).

## 2026-08-06 (ConstantFolder RecursionError on long PERFORM chains)

Code-review finding: `const_fold.py`'s `_walk_perform` followed a chain of
out-of-line `PERFORM`s (`P1` performs `P2` performs `P3` ... `PN`) by
recursing through Python's own call stack, one frame per paragraph — a few
hundred chained paragraphs (well under `sys.getrecursionlimit()`'s default
of 1000) raised an uncaught `RecursionError`, and every `gen-fixtures` call
reaches this path unconditionally (both `generate()` and
`generate_with_scenarios()`). Reproduced: 300 chained paragraphs folded
fine, 500 crashed. `_poison_written_names` had the identical defect for a
`PERFORM`-to-paragraph chain reached from inside a poisoned loop/branch body
— reproduced separately at ~1500 chained paragraphs (a higher threshold
since it recurses through fewer stack frames per paragraph). Both converted
to an explicit frame stack, the same fix `program_flow/cycles.py` already
uses for its own paragraph-graph traversal; recursion is still used for
genuinely nested statement lists (bounded by real source nesting, not
paragraph-chain length), left alone deliberately. New regression tests:
`tests/unit/analysis/test_const_fold.py::TestPerformChaining` — 2000-chain
tests for both paths, plus a sequential-re-PERFORM-of-the-same-paragraph
test pinning that the `visiting` add/discard lifetime (now bracketing a
frame push/pop instead of a recursive call/return) is unchanged. Full
detail: [analysis.md](analysis.md) (`ConstantFolder` section). Also
updated: `CHANGELOG.md`.

## 2026-08-05 (EJECT compiler-directing statement unrecognized)

User report: "make sure the ejects in the program are ignored, and
copybooks [too]." Confirmed via direct `parse_cobol()` repro: `EJECT` (the
source-listing page-eject directive) had no `TokenType`, no keyword entry,
and no statement parser, so it lexed as a bare `IDENTIFIER`. Two concrete
failures: (1) `EJECT.` (trailing period, the common real-world style) was
indistinguishable from a paragraph name to `is_paragraph_or_section_start`
and silently split the enclosing paragraph in two around a bogus empty
`EJECT` paragraph; (2) `EJECT` with no period fell through to the
"unsupported statement" recovery path and emitted a spurious "Unparsed
tokens ... clause or statement not fully supported" warning. Both
reproduced identically through COPY-expanded copybook text (copybooks with
shared paragraphs or multiple record layouts commonly use EJECT between
sections), confirmed with a dedicated repro before concluding it needed no
copybook-specific fix.

Fixed the same way `CONTINUE` (a genuine no-op) is handled: `TokenType.EJECT`
+ `KEYWORDS` entry (`lexer.py`), added to `STATEMENT_TOKEN_TYPES`/
`STATEMENT_KEYWORDS` (`_utils.py`), a new `EjectStatementParser` ->
`EjectStatement` no-op node (`simple_statement_parsers.py` /
`models/statements/misc.py`), registered in `create_statement_registry()`
right after `ContinueStatementParser`. New test:
`tests/regression/test_eject_statement.py`. Updated:
`tests/unit/test_procedure_registry_dispatch_order.py` and
`tests/regression/test_swallow_sweep.py` (both have completeness guards
that fail on an unfixtured newly-registered parser). Full detail:
[parser.md](parser.md) ("EJECT compiler-directing statement was
unrecognized"). Also updated: `CLAUDE.md` (Statement Parsers / AST
Statement Models tables), `CHANGELOG.md`.

## 2026-08-04 (PR #108 Copilot review: dead --describe flag, MANIFEST.json type mismatch)

GitHub Copilot's automated review of PR #108 left two comments; verified
both against the actual code before acting (per this repo's own "check the
claim, don't just trust or dismiss the bot" discipline) — both were real.

* **`gen-fixtures --describe` was a silent no-op.** Registered on the
  argument parser (`cobolparser/cli/parse.py`) with help text "Emit the
  resolved bundle as JSON (implied by --format json)" but `args.describe`
  was never read anywhere in `_cmd_gen_fixtures` — confirmed by grepping
  the whole file for `.describe` and finding only `gen-data`'s own,
  unrelated, correctly-wired `--describe` handling. Not in `CLAUDE.md`'s
  own `gen-fixtures` command-line documentation, not exercised by any
  test. Removed the flag entirely (its own help text already admits
  `--format json`, the default, already does what it would do — nothing
  distinct was left to implement).
* **`write_csv_dir()`'s `MANIFEST.json` changed a field's type.** Every
  fixture's `"sequence"` (normally `list[dict[str, str]]`) was replaced
  with a hint string (`"see <scenario-slug>/"`). A consumer that ran
  `MANIFEST.json` through the same deserializer as a real bundle JSON —
  reasonable, since every other key matches — would silently iterate the
  string character-by-character in place of real rows, rather than hit a
  clean type error. Fixed: `sequence` now stays `[]`; a new `csv_path` key
  per fixture (the CSV's path relative to the output dir, or `null` for a
  fixture with no CSV) carries the same information the hint string did,
  without the type mismatch.

Both fixed in `cobolparser/cli/parse.py` / `cobolparser/generators/data/bundle.py`.
New test: `test_program_fixtures.py::TestWriteCsvDir::test_manifest_sequence_stays_a_list_not_a_hint_string`
(zips the real `Scenario`/`BoundaryFixture` objects against their `to_dict()`
counterparts in the manifest, positionally, to check `csv_path` against
each fixture's *actual* layout/sequence state, not just spot-check one
value). Updated: [cli.md](cli.md) (removed the `--describe` flag from
`gen-fixtures`'s command line and documented the manifest fix),
[generators.md](generators.md) (`write_csv_dir` section),
`docs/fixture-bundle-schema.md` (`write_csv_dir` section), `CHANGELOG.md`.

## 2026-08-04 (interface-contract.md: pin the mocky-mock generators surface)

`interface-contract.md` gained a new "Generators Surface (mocky-mock)"
section, documenting the second external consumer of this repo alongside
the LegacyLens backend adapter it already covered: mocky-mock's `mockymock
generate --with-data` / `mockymock fixtures` subcommands (Phase 8 of the
`gen-fixtures` program-scoped test-data initiative) call
`cobolparser.generators.ProgramFixtureGenerator`/`DataGeneratorOptions`/
`generate_with_scenarios_from_file` directly and consume
`FixtureBundle.to_dict()`/`.to_json()`, gated on `bundle_version`. This is a
documentation-only change (no `cobolparser/` source touched, so
`scripts/okf_staleness_check.py`'s `OKF_MAP` — which only tracks
`cobolparser/*`/`tests/` source prefixes, not root-level docs — has nothing
to flag for it); the entry exists per this repo's own convention of logging
every `.okf`-bundle-adjacent change, not because the staleness gate fired.
No detail is duplicated here that isn't already canonical in
[`docs/fixture-bundle-schema.md`](../docs/fixture-bundle-schema.md) — the
new section links to it rather than restating its key tables, so the two
documents can't drift apart from a future bundle-shape change landing in
only one of them.

## 2026-08-04 (READ terminal status: unsafe placeholder field name)

Found integrating mockymock's `gen-fixtures` Phase 8 (`generate
--with-data`): `ProgramFixtureGenerator`'s READ `terminal` dict fell back to
a literal placeholder field name, `"FILE-STATUS"`, whenever a READ boundary
had no resolvable `FILE STATUS` clause — confirmed live, not theoretical,
against `INVUPDT.cbl`'s `INV-FILE`, which declares no `FILE STATUS` clause
at all. A consumer that splices that placeholder into a real `MOVE`
target — exactly what mockymock's `.cut` scaffolder does — generates COBOL
that fails to compile, since `"FILE-STATUS"` is not a data-name that exists
in the target program.

* **Root cause**: the `terminal` computation had its own ad hoc fallback
  (`status_field or "FILE-STATUS"`) instead of reusing `_status_dict`'s
  already-correct two-step resolution (`boundary.status_field`, then
  `index.file_facts(key).file_status_field`, else give up).
* **Fixed** `cobolparser/generators/program_fixtures.py`: extracted the
  shared two-step lookup into `_resolve_status_field(boundary, index) ->
  str | None`, used by both `_status_dict` and the `terminal` computation.
  `terminal` is now `None` (never a placeholder string) when neither step
  resolves — "exact by construction, or absent," the same rule this
  initiative's `ConstantFolder` (Phase 7) already follows.
* **A second bug in the same code path**, found while fixing the first:
  the READ fixture's `call_count` expectation derived "did an AT-END
  invocation happen" from whether `terminal` was truthy — after the fix
  above, that conflates "the sequence exhausts" (a fact about the program's
  `AT END` handler, independent of whether a status field can be named)
  with "we know a field name to report it in." A program that reads to EOF
  with an unresolvable status field still genuinely invokes the boundary
  one more time; undercounting it would make `VERIFY ... WAS CALLED n
  TIMES` wrong. Fixed by checking `"AT_END" in boundary.handlers` directly
  or a `has_terminal_invocation` flag, independent of `terminal`'s
  resolution.
* **Updated** [generators.md](generators.md): the Tier 1 `call_count`
  formula and the READ per-category generation-rules row both still
  described the old, buggy behavior verbatim (`terminal` set to
  `{status_field or "FILE-STATUS": "10"}`, `times = len(sequence) + (1 if
  terminal else 0)`) — corrected to match the fix.
* **Tests**: `tests/unit/test_program_fixtures.py` gained
  `TestTerminalStatusFieldResolution` (both the safe-`None` and the
  real-field-resolves cases, using `tests/samples/file_operations.cbl`'s
  `SEQ-FILE`/`WS-SEQ-STATUS`) and a corrected assertion in the pre-existing
  `test_empty_input_scenario_call_count_is_one_not_zero` (previously
  asserted the placeholder dict; now asserts `terminal is None` with the
  count still `1`). Full suite: 7,795 passed / 13 skipped / 1 xfailed,
  91.44% coverage. Commit `b3e2b32`, `CHANGELOG.md` Bug Fixes.

## 2026-08-03 (normalize_fixed_format column-73+ overflow warning)

Fixed a silent-truncation bug found during a whole-branch review of
mocky-mock's not-yet-merged `export` command: `normalize_fixed_format`'s
`line[TEXT_START_COL - 1 : TEXT_END_COL]` slice never bounds-checked the
line length, so any non-comment line longer than 72 columns had its
columns-73+ tail silently dropped — no warning, no error, no signal to the
caller. Repro: a hand-written 77-column `DISPLAY "X" WS-FIELD.` line (56
columns of indentation) silently became `DISPLAY "X" WS-F` (no closing
quote, no period) with mocky-mock still writing it to its "durable
deliverable" output and exiting 0. Confirmed as a live, not just
theoretical, bug: `legacy-application/cobol/ACCTMNT.cbl:388` already splits
the identifier `WS-PARM-DORM-DAYS` into `WS-PARM-DORM-D` + dropped `AYS`
this same way.

* **Updated** [preprocessing.md](preprocessing.md): documented the new
  `warnings: list[str] | None = None` parameter and the mid-token detection
  rule (column 72 *and* column 73 both non-blank — content actually split a
  token, as opposed to a traditional 80-column identification field like
  NIST CCVS85's `IC1014.2`, which must **not** warn; empirically checked
  against both `legacy-application/cobol/*.cbl` and the vendored
  `examples/nist-cobol85` corpus before picking this rule over a naive "any
  non-blank content past column 72" check, which would have fired on nearly
  every line of the NIST corpus).
* **Changed** `cobolparser/preprocess/__init__.py` and
  `cobolparser/_preprocess_fast.pyx` (mirrored, rebuilt via `python setup.py
  build_ext --inplace`, regenerated `.c` committed) — both now track the
  1-based physical line number and append one `f"Line {n}: content beyond
  column 72 was dropped mid-token: {dropped!r}"` message per qualifying
  line when a `warnings` list is passed. Comment lines are never checked
  (their text is discarded whether truncated or not). Default `None`
  preserves the exact old (silently-truncating) behavior for every existing
  caller.
* **Added**
  `tests/regression/test_normalize_column_overflow_warning.py`: pins the
  mid-token-warns / traditional-field-does-not-warn / comment-line-does-not-
  warn / `debug_lines_as_comments=False` D-line flip / no-`warnings`-arg
  backward-compatibility cases, plus a pure-vs-Cython parity test over the
  `warnings` list itself (the existing parity tests only ever compared the
  returned string).
* **mocky-mock side** (separate repo): `mockymock/cli/checks.py` now
  threads a `warnings` list through its `normalize_fixed_format` calls and
  exposes it on `StaticCheckResult`; `mockymock export` (only — `run`/`lint`
  intentionally left unchanged, out of scope for this fix) refuses instead
  of silently writing a corrupted "durable deliverable" and exiting 0. See
  mocky-mock's own `.okf/log.md` for that side of the fix.

## 2026-08-02 (generators/data/ package split: final whole-branch-review fixes)

Seven-task, zero-behavior-change refactor split `cobolparser/generators/
copybook_data.py` into a modular package `cobolparser/generators/data/`
(`options.py`, `errors.py`, `layout.py`, `values.py`, `dataset.py`,
`copybook.py`, `__init__.py`), with `copybook_data.py` reduced to a
backwards-compatible re-export shim — see the entry below for the original
feature. Each of the 7 tasks passed its own task-level review; a final
whole-branch review then caught a handful of doc/cosmetic gaps no single
task's diff could see on its own. Fixed here in one pass, no source-logic
changes:

* **Updated** [generators.md](generators.md): corrected `FieldSpec`'s
  description from "namedtuple" to "dataclass" — `layout.py` defines it
  with `@dataclass`, and `_assign_columns()` relies on that mutability to
  assign `spec.column` in place after construction, which a namedtuple
  could not support. Frontmatter `timestamp` bumped.
* **Relocated** the subsystem's module docstring (overview, `Typical
  use::` example, determinism/seed-replay guarantee, and the four "Design
  notes" bullets on REDEFINES/OCCURS/edited-pictures/FILLER defaults) from
  `copybook_data.py` onto `cobolparser/generators/data/__init__.py` — the
  new canonical home for the subsystem. The refactor had deleted it from
  `copybook_data.py` (flagged during Task 6 as a possible gap for Task 7)
  with no relocation target; Task 7 did not carry it forward, so the final
  review caught it. Also added the package's missing `from __future__
  import annotations` for consistency with every other module in `data/`
  (flagged during Task 1, deferred to final review).
* Removed a vestigial `if TYPE_CHECKING: pass` block (and its now-unused
  `TYPE_CHECKING` import) left in `data/values.py` from the Task 3
  extraction (flagged during Task 3, deferred to final review) — guarded
  nothing, served no purpose.
* Softened `copybook_data.py`'s shim docstring: it claimed the vendored
  backend copy (`backend/_vendor/cobol-parser/`) imports from this path.
  Checked directly against the sibling repo — the vendored copy predates
  the `gen-data` feature entirely (no `copybook_data.py`, no `data/`
  package, no reference anywhere), so that claim was dropped. The other
  two reasons already in the docstring (the unit test, `cli/parse.py`'s
  lazy import) were independently re-verified correct and kept.
* **Updated** root `CLAUDE.md`: the `cobolparser/generators/` section had
  lost its behavioral summary (honors PICTURE/USAGE/OCCURS/REDEFINES/
  level-88/VALUE, deterministic per `seed`, backs `gen-data`) when Task 7
  rewrote the bullet to describe the new file layout. Restored the
  behavioral sentence alongside the file-structure description rather
  than reverting Task 7's structural update.
* **Moved** `CHANGELOG.md`'s Task-7 "internal restructure" bullet from
  `## Unreleased` → `### Added` to `## Unreleased` → `### Changed` (Keep a
  Changelog, which this file's header cites: a no-API-change internal
  restructure is a "Changed", not an "Added"). Placed at the top of that
  section, alongside this repo's other god-class/module-decomposition
  refactor entries, consistent with the section's newest-first ordering.

Full suite green after the fix wave: 7327 passed / 13 skipped / 1 xfailed
(unchanged), coverage 92.11% (up from the pre-fix-wave 92.10% — removing
`values.py`'s dead `if TYPE_CHECKING: pass` block also removes an
always-missed branch/statement, so the uptick is an expected side effect
of finding 3, not a regression). `ruff check .`, `black --check .`, and
`mypy cobolparser/` all clean.

## 2026-08-02 (copybook → CSV synthetic test-data generation)

New feature: `cobolparser/generators/copybook_data.py` plus a
`cobol-parser gen-data` CLI subcommand. Flattens a copybook record layout
into CSV columns and generates rows of values constrained by each field's
PICTURE, `USAGE`, level-88 domain, and `VALUE` clause.

* **Created** [generators.md](generators.md) — new concept file covering both
  generator modules. `flowchart.py` was previously undocumented in the OKF
  (only mentioned in passing from cli.md's `program-flow --format`); it now
  has a home alongside `copybook_data.py`. Documents the public API, the
  copybook-fragment parsing strategy (program-skeleton wrapper, free-form
  Area-B shift, synthesised record root for level-02-only copybooks), the
  flattening rules table, the four-level value-precedence chain, and the
  determinism/seed-replay guarantee.
* **Updated** [index.md](index.md): added a Generators entry under
  "Analysis & Generation".
* **Updated** [cli.md](cli.md): added the `## Gen-Data` subcommand section
  between Expand and Analyze — flags, the two JSON modes (`--list-records`,
  `--describe`), and the note that this subcommand emits **CSV** on stdout
  rather than the JSON every other subcommand emits, so it is deliberately
  outside the "Output Identification" convention documented at the top of
  that file.
* **Updated** [tests.md](tests.md): added the three new test files to the
  directory layout and a generators.md cross-reference.

Two parser behaviours were confirmed against source while writing this and
are worth recording, since both shaped the generator's design:

* `ConditionNameItem.values` records `VALUE 2 THRU 4` as
  `["2", "THROUGH:4"]` — the range end is *marked*, not expanded. Consumers
  wanting the domain must expand it themselves (`_condition_values` does,
  capped at 64 entries).
* `PictureClause.is_signed` reports only an explicit `S`. A numeric-edited
  picture carrying `+`/`-`/`CR`/`DB` (e.g. `PIC -ZZ,ZZ9.99`) holds a sign but
  reports `is_signed=False`; the generator compensates in `_is_signed()`.
  Noted in [ast-models.md](ast-models.md) under Data Items.

## 2026-07-27 (validate_copybook_content: multiline missing-period regex + comment-only misreport)

User-reported pair of bugs in `cobolparser/preprocess/__init__.py`'s
`validate_copybook_content`, both specific to copybooks that start with (or
contain) comment lines — confirmed by direct script reproduction before any
fix was written, per this repo's TDD convention.

* **Updated** [preprocessing.md](preprocessing.md): documented both fixes
  under "Copybook Expansion".
  1. `_DATA_DEF_RE` used bare `\s`, which matches newlines. Since
     `remove_comment_lines` blanks comment lines to whitespace *before*
     `validate_copybook_content` runs, `^\s*` could bridge across those
     blanked lines and `[^\s]+` (not excluding `.`) swallowed a trailing
     period — producing false "missing terminating period" warnings on
     correctly-terminated lines, misattributed to the wrong line (reproduced:
     a copybook with 2 leading comment lines + 2 correctly-terminated code
     lines got both flagged, warnings attached to line 1 and line 4 instead
     of neither). Fixed by switching internal `\s`/`\s+`/`\s*` to
     `[ \t]`/`[ \t]+`/`[ \t]*` (can't cross a line) and the value token to
     `[^\s]*[^\s.]` ("non-whitespace, not ending in a period" — excludes
     only a trailing period, not a PICTURE's own internal decimal point).
     An initial `[^\s.]+` draft excluded periods everywhere in the token,
     which silently broke detection for decimal-point PICs like
     `PIC 9(5).99` with a genuinely missing terminator — caught by the
     advisor review before landing, fixed, and pinned with two more tests.
  2. The "contains only comments" check was dead code in the real pipeline:
     `remove_comment_lines` already blanks every comment line before
     `validate_copybook_content` sees the content, so a genuinely
     comment-only copybook fell into the earlier "is empty" branch instead —
     misleading, since comment-only is a legitimate documentation-only
     pattern. Fixed by adding an optional `raw_content` parameter (the
     pre-strip source); `_expand_source_recursive` now captures and passes
     it so the correct message is reported.
* Added regression tests to
  `tests/unit/test_preprocess_init_coverage.py::TestValidateCopybookContent`
  (6 new cases, written and confirmed failing before each fix) and
  strengthened `tests/unit/test_copybook_expander_coverage.py::
  TestExpandCopybooks::test_content_validation` to assert the exact message
  instead of just "warnings is non-empty".
* Full suite green: 7102 passed / 13 skipped / 1 xfailed, 92.20% coverage
  (up from 7096, no regressions). `ruff check`, `black --check`, and
  `mypy cobolparser/` clean on touched files.

## 2026-07-24 (targeted follow-up round: CALL BY-mode persistence, COMPUTE comma targets; vendor sync)

User-scoped follow-up after reviewing the five-fix sweep below ("one more
targeted round: SEARCH WHEN conditions, CALL BY CONTENT/REFERENCE groups,
READ/WRITE INTO clauses"). Checked those plus COMPUTE (an obvious sibling
of the just-fixed ADD/SUBTRACT/MULTIPLY/DIVIDE target lists). Found and
fixed two more real bugs, confirmed two candidates needed no fix:

* **Updated** [parser.md](parser.md): CALL's `BY REFERENCE`/`CONTENT`/
  `VALUE` passing mode didn't persist across a comma-separated parameter
  list within one BY-phrase group (`passing_mode` was reset to the
  REFERENCE default every loop iteration instead of only when a fresh
  `BY` keyword appeared) — a silent semantic corruption (parameter names
  intact, mode wrong), not a data-drop. COMPUTE's multi-target comma list
  (`COMPUTE A, B = expr`) had zero comma handling and was a **hard parse
  failure** ("COMPUTE statement missing '=' operator", no AST node at
  all) — worse than every other fix in this bug class, which were all
  silent/warned drops rather than outright failures. SEARCH's
  WHEN-condition collector and READ/WRITE's INTO/FROM clauses were
  checked and confirmed (by direct repro, not grammar inspection alone)
  to need no fix — neither takes a list per the standard grammar.
* **Updated** [ast-models.md](ast-models.md): new note on
  `CallStatement.using_parameters`' mode-persistence fix.
* Extended `tests/unit/test_initialize_sort_arithmetic_comma_gaps.py` to
  29 tests (was 22): `TestCallByModePersistsAcrossCommaList` (3),
  `TestComputeCommaTargets` (4).
* Full suite green: 7096 passed / 13 skipped / 1 xfailed, 92.20% coverage
  (up from 7089, no regressions). `ruff check .`, `black --check .`, and
  `mypy cobolparser/` all clean on touched files.
* **Vendor sync**: `backend/_vendor/cobol-parser/cobolparser/` was stale
  (predated even PR #99-#101) — user approved syncing it. Copied via
  `cp -r cobolparser/. ../backend/_vendor/cobol-parser/cobolparser/`
  (note the trailing `/.`: a bare `cp -r src/ dst/` against an
  **already-existing** `dst/` nests `dst/src/` instead of overwriting —
  hit this on the first attempt, caught via `diff -rq`, corrected).
  Also found and removed one genuinely stale leftover file in the vendor
  copy predating this repo's own 2026-07-14 `program_flow.py` →
  `program_flow/` package refactor (the source repo has no flat
  `program_flow.py` anymore; the vendor copy still had both the stale
  file and the new package, an ambiguous same-name module+package
  situation `cp -r` alone doesn't clean up since it only adds/overwrites,
  never deletes). Verified post-sync via a standalone import + parse
  smoke test against the vendored copy directly (not the full backend
  service, whose own dependencies weren't verified in this pass).
  `diff -rq` confirms full parity with `cobol-parser/cobolparser/`
  (excluding `__pycache__`) after the fix. Re-synced a second time after
  the CALL/COMPUTE fixes above landed.
* `CHANGELOG.md` (Unreleased → Fixed) and `reports/open-findings.md`
  updated in the same pass.

## 2026-07-24 (follow-up comma-list sweep: INITIALIZE, SORT/MERGE KEY/USING/GIVING, arithmetic GIVING)

Continuing the gap audit (user request: "make sure there is no gaps in the
cobolparser") after reconciling the doc debt below, re-verified the
comma-truncation bug class the 2026-07-22/23 sweep fixed elsewhere against
parsers that sweep didn't touch. Found and fixed four more real instances,
via direct `parse_cobol()` repro (not spec-recitation) before writing any
fix, per this repo's established methodology. A subsequent advisor
second-opinion review of this same pass surfaced a fifth, adjacent
instance (MULTIPLY/DIVIDE format-1 multi-target, distinct from the GIVING
multi-target fix already made) that the repro sweep itself had not
covered — confirmed empirically the same way, then fixed and pinned
alongside the other four rather than left as a known gap.

* **Updated** [parser.md](parser.md): new "Follow-up comma-list sweep:
  INITIALIZE, SORT/MERGE KEY/USING/GIVING, arithmetic GIVING (2026-07-24)"
  section. `INITIALIZE id-1, id-2, ...` (warned drop, now fixed).
  `SORT`/`MERGE` `KEY field-1, field-2 ...` — **fully silent**
  (`errors=[], warnings=[]`), the worst instance of this bug class found
  to date. `SORT`/`MERGE` `USING`/`GIVING file-1, file-2 ...` — also fully
  silent, same shared `_parse_file_list` helper. `ADD`/`SUBTRACT`/
  `MULTIPLY`/`DIVIDE ... GIVING id-3, id-4 ...` (multi-target GIVING list,
  symmetric with the TO/FROM multi-target fix from 2026-07-22/23, which
  did not extend to GIVING).
* **Updated** [ast-models.md](ast-models.md): new field notes for
  `ArithmeticStatement.givings: list[str]` and `MultiplyStatement`/
  `DivideStatement` now populating `.target`/`.targets` for format 1.
* New test file `tests/unit/test_initialize_sort_arithmetic_comma_gaps.py`
  (22 tests) pins all five fixes plus back-compat coverage for the
  pre-existing single-target/space-separated forms, including an explicit
  guard that format-2 (GIVING) MULTIPLY/DIVIDE do NOT gain a spurious
  `.target`.
* **Methodology note kept in parser.md:** the SORT/MERGE test's first
  draft used a fixture line that itself exceeded fixed-format column 72,
  producing a `giving_files: ['WS']`-shaped truncation that initially
  looked like a fifth bug. Confirmed via direct lexer/column inspection
  that this was a test-fixture artifact (this repo's own documented
  column-72 truncation semantics, correctly applied) before concluding
  so — fixed by reformatting the fixture across two lines, not by
  changing parser code. Recorded as a reminder for future fixture
  authoring in this repo, not as a finding.
* Full suite green after all five fixes: 7089 passed / 13 skipped / 1
  xfailed, 92.20% coverage (up from the 7067/92.19% baseline — +22 new
  tests, no regressions). `ruff check .` and `mypy cobolparser/` clean
  (107 source files; the shared `_BinaryArithmeticNode` structural
  `Protocol` gained a `set_target` method to type-check the format-1 fix);
  `black --check .` clean on all touched files (one pre-existing,
  unrelated formatting drift in
  `tests/regression/test_tier2_silent_drop_regressions.py`, not touched by
  this pass, left alone as out of scope).
* `CHANGELOG.md` (Unreleased → Fixed) and `reports/open-findings.md`
  updated in the same pass.

## 2026-07-24 (OKF reconciliation for PR #99-#101: statement-support verification sweep + EOF sentinel fix)

Nine fixes landed on `main` 2026-07-22/23 (PR #99, #100, #101 — commits
`5492c40`, `824f654`, `64ff7b9`, `316f0ce`, `82a82ec`, `68f68c0`,
`ddbc688`, `50b6028`, `4a8daa3`) with no matching OKF/`CHANGELOG.md`/
`open-findings.md` update. Reconciled retroactively while auditing this
repo for outstanding gaps (user request: "make sure there is no gaps in
the cobolparser").

* **Updated** [parser.md](parser.md): new "Statement-Support Verification
  Sweep (2026-07-22/23)" section — comma-separated list truncation across
  seven parsers (CALL USING incl. OMITTED, SET, UNSTRING INTO, DISPLAY
  items, computed GO TO, CANCEL, ENTRY USING), UNSTRING `DELIMITED BY ...
  OR ...` + `TALLYING IN`, EXEC CICS command-verb-on-next-line loss + EXEC
  SQL/DLI operator-rejoin spacing, INSPECT BEFORE+AFTER (both qualifiers,
  either order), PIC N(n) sizing, USAGE IS optional-IS handling, START KEY
  OR EQUAL TO trailing TO, WRITE AT END-OF-PAGE/NOT AT END-OF-PAGE, OPEN
  per-file `file_modes`, ADD/SUBTRACT ROUNDED/multi-target/CORRESPONDING +
  DIVIDE REMAINDER, DISPLAY UPON clause-continuation + period handling,
  ENTRY comma, ACCEPT FROM ENVIRONMENT name, STOP period consumption, and
  the EOF-sentinel phantom trailing paragraph (three distinct root causes
  now on record for that one symptom: DISPLAY UPON, STOP, and this EOF fix).
* **Updated** [ast-models.md](ast-models.md): new field notes for
  `ArithmeticStatement.targets`/`.rounded`/`.is_corresponding`,
  `DivideStatement.remainder`, `UnstringStatement.tallying_variable` +
  multi-delimiter `.delimiters`, `IOOpenStatement.file_modes`,
  `IOWriteStatement.not_at_eop_clause`, `IOAcceptStatement.
  environment_name`, and `PIC N(n)` sizing.
* Full suite re-verified green before and independent of this doc pass:
  7067 passed / 13 skipped / 1 xfailed, 92.19% coverage (no source changes
  in this pass — documentation only).
* `reports/open-findings.md` and `CHANGELOG.md` (Unreleased) also updated
  in the same pass.

## 2026-07-21 (generic swallow-sweep regression test added)

* **Added** `tests/regression/test_swallow_sweep.py`: formalizes the manual
  "period-less verb + marker statement" probe used throughout the
  2026-07-05..09 Silent-Drop Audit sections into a permanent, generic sweep
  — one fixture per class in `create_statement_registry()` (46), cross-product
  with a `DISPLAY 'MARKER'.` sentinel, asserting the marker survives as its
  own top-level entry in `CobolParagraph.statements` (not merely somewhere in
  `get_all_statements()`'s tree-wide recursion, which would false-pass a
  marker absorbed into a clause body — see design rationale in the test
  module docstring). A completeness guard fails the suite if a future
  statement parser is registered with no matching fixture. Validated during
  development by disabling `MoveStatementParser`'s boundary check and
  confirming exactly one targeted failure (no collateral damage), then
  reverting. A second validation pass caught a real gap: the initial
  ADD/SUBTRACT/MULTIPLY/DIVIDE fixtures used a plain scalar target, which is
  safe-by-construction (consumed in one shot regardless of any boundary
  check) and stayed green even with `_consume_arithmetic_target` mutated —
  redesigned around a subscripted `GIVING` target so they route through the
  shared `consume_optional_subscript` paren-depth loop instead, confirmed by
  mutating that loop (all four failed together, then reverted).
* **Updated** [parser.md](parser.md): new "Generic swallow-sweep regression"
  section cross-referencing this test from the audit trail it formalizes.
* **Updated** [tests.md](tests.md): added the new file to the `regression/`
  directory-layout annotations.

## 2026-07-21 (procedure_registry.py dispatch-order invariant test)

* **Updated** [parser.md](parser.md): added
  `tests/unit/test_procedure_registry_dispatch_order.py`, closing a gap
  flagged in review — `create_statement_registry()`'s first-match dispatch
  order is order-sensitive by design ("more specific before general") but
  had no automated invariant test, so a misordered future registration
  would have failed silently at runtime instead of at test/review time.
  Investigated every `matches()` implementation in
  `cobolparser/parsers/statements/` to find genuine first-token overlaps;
  confirmed the only real overlap in the current registry is the IBM EXEC
  family (`EXEC SQL`/`EXEC CICS`/`EXEC IMS`/`EXEC DLI` all start with
  `EXEC`, disambiguated on the second token) — every other registered verb
  matches a distinct `TokenType`. The new test file: (1) pins
  `create_statement_registry()`'s exact parser order in `EXPECTED_ORDER` so
  any accidental reorder/insertion/removal in `procedure_registry.py` fails
  immediately; (2) parametrizes `DISPATCH_CASES` — one real
  `Token`/`TokenStream` case per registered parser (46 total) — asserting
  `find_parser()` returns the correct class against the actual production
  registry, so a future parser with an overly broad `matches()` inserted in
  the wrong slot is caught by a wrong-class assertion instead of a silent
  mis-parse; (3) a guard test asserting `DISPATCH_CASES` covers every class
  the registry actually registers, so the invariant test itself can't
  silently drift out of sync. Verified the order-pin test actually catches
  breakage by temporarily swapping two adjacent registrations in a scratch
  copy — the test failed with a clear index-level diff, then the swap was
  reverted. Updated the "Adding a New Statement Parser" checklist in
  parser.md with a step to update this test. Pinned by
  `tests/unit/test_procedure_registry_dispatch_order.py`.

## 2026-07-21 (copybook REPLACING/`>>IF` ran before sequence-area stripping)

* **Updated** [preprocessing.md](preprocessing.md): user asked to confirm
  that fixed-format sequence-number (columns 1-6) and identification
  (columns 73-80) columns are always ignored "even in the copybooks."
  Confirmed the *default* expansion path already strips them correctly, but
  found a real gap via direct reproduction (not merely theorized —
  `expand_copybooks` run against copybooks with real 6-digit sequence
  numbers and column-72-flush REPLACING targets): `_expand_source_recursive`
  ran `apply_replacing_clauses`, `preprocess_conditional_compilation`,
  `validate_copybook_content`, and `validate_level_numbers` on the raw
  80-column copybook line, stripping sequence/identification columns only
  *afterward*. A length-changing `REPLACING` therefore shifted the
  column-72 boundary relative to the original line: a shrinking replacement
  (`==LONGPLACEHOLDERTAG==` by `==X==`) pulled the identification-area text
  into the kept window and inserted it into the parsed program; a growing
  replacement (`==SHORTTAG==` by a longer value) truncated real code,
  dropping the replaced text's terminating period. Separately, `>>IF`/
  `>>END-IF` inside a copybook using real (non-blank) sequence numbers were
  never recognized as directives (the check saw the sequence-number digits
  before `>>`), so conditional blocks never evaluated.
  Fix: `_expand_source_recursive`'s copybook-content branch now strips
  sequence/identification columns and blanks comment lines immediately
  after reading the file — before REPLACING, conditional compilation, or
  either validator sees it. `apply_replacing_clauses` gained an
  `indicator_position: int = 6` parameter (mirroring
  `normalize_continuation_lines`) so it locates the indicator column
  correctly on both raw (index 6) and pre-stripped (index 0) content, and
  `_expand_source_recursive` gained `already_stripped: bool = False` so its
  own internal strip is skipped when the caller already normalized the
  content (skipping it unconditionally would double-strip and eat 6 more
  real characters off every line). One pre-existing unit test
  (`test_copybook_expander_coverage.py::test_content_validation`) used a
  synthetic single-line copybook (`"* Just a comment"`, comment marker at
  column 1, not column 7) that only worked by coincidence against the old
  naive `.strip().startswith("*")` check; corrected the fixture to use a
  real fixed-format comment line (6-space sequence area + column-7 `*`).
  Pinned by
  `tests/regression/test_copybook_sequence_area_before_replacing.py`. Full
  suite green (6818 passed / 13 skipped / 1 xfailed).

## 2026-07-21 (PICTURE clause with no terminating period drops the next data item)

* **Updated** [parser.md](parser.md): `parse_picture_clause`
  (`parsers/divisions/data_clauses.py`) unconditionally treated a NEWLINE as
  "more picture pattern may follow" (needed for legitimate multi-line
  PICTURE clauses). When a clause's terminating period was missing, the loop
  crossed the newline and picked up the *next* data item's own
  `level-number data-name` pair as more pattern content — the lexer types
  every 1-2 digit integer as `LEVEL_NUMBER` regardless of context, and
  `LEVEL_NUMBER` is one of the token types the picture-pattern loop collects.
  The next item (and all its children) vanished from the AST with
  `result.success == True` and `result.warnings == []`.
  Root cause confirmed via a minimal repro (`cobolparser.parse_cobol` on a
  `REDEFINES ... PIC 9(08)` entry whose terminating period lands at column
  73): `normalize_fixed_format` extracts only columns 8-72, silently
  truncating the period. Empirically verified against real GnuCOBOL 3.2 (via
  mockymock's `mockymock-cobc` Docker container, plain fixed-format `cobc`,
  no `-free`) that the same source **fails to compile** there too
  (`group item 'Variable-name' cannot have PICTURE clause` / `syntax error,
  unexpected Literal`) — GnuCOBOL applies the same column-72 truncation
  (cobolparser's semantics already match) but never silently accepts the
  result the way cobolparser did. The bug is not fixed-format-specific: a
  plain missing period in free-form source hits the identical defect.
  Fix: `parse_picture_clause`'s NEWLINE branch now looks ahead past the
  newline for a LEVEL_NUMBER that cannot legally be more PICTURE content —
  either its value contains a digit other than `0`/`9` (the only two
  digit-shaped PICTURE symbols), or it's immediately followed by an
  `IDENTIFIER` (never legal inside a PICTURE pattern — occurrence counts
  are always parenthesized, e.g. `9(05)`) — and stops the clause there
  instead of consuming the newline, recording a `ParseResult.warnings`
  entry — consistent with the "dropped-content signal" contract mockymock's
  `check_whole_program` PARSE_WARNING refusal gate already depends on
  (`mocky-mock/.okf/integration.md` Gotchas). The Cython `_data_fast` fast
  path delegates PICTURE parsing back to this same method, so both paths are
  fixed together with no `.pyx`/`.c` change needed. Pinned by five new
  tests written first and confirmed failing against the old behavior:
  `tests/regression/test_picture_clause_missing_terminator.py`
  (`TestFixedFormatColumnTruncation` — the literal repro — and
  `TestFreeFormMissingPeriod` — the same defect with no column truncation
  involved). Full suite green (6813 passed / 13 skipped / 1 xfailed).
  **Follow-up (same day, advisor review):** the initial fix keyed only on
  "LEVEL_NUMBER followed by IDENTIFIER", missing an *anonymous* next item
  with no data-name at all (`05  REDEFINES ...` — no IDENTIFIER token
  follows the level number), which still silently corrupted the previous
  item's pattern and misattached the anonymous item's children to it. Added
  the digit-content signal above (any digit other than `0`/`9` can never be
  legal PICTURE content, so the token is unconditionally a real level
  number) to close that gap without reintroducing a false positive on the
  legitimate `PIC 9\n99.`-style multi-line continuation (every character of
  an all-`0`/`9` LEVEL_NUMBER stays ambiguous, so the IDENTIFIER check still
  gates that case). Also strengthened the original tests to assert
  parent/child re-attachment explicitly (not just node presence — the
  original bug's defining symptom was children reattaching to the *wrong*
  parent) and added `TestAnonymousNextItem`. Full suite green (6815 passed
  / 13 skipped / 1 xfailed).

## 2026-07-21 (SUBTRACT ... FROM and GIVING subscripted targets dropped)

* **Updated** [parser.md](parser.md): two sibling gaps in the same bug class
  as the ADD ... TO fix above, both in
  `parsers/statements/arithmetic_parsers.py` /
  `parsers/statements/_utils.py`:
  1. `SubtractStatementParser`'s `FROM` branch consumed an identifier
     target with a bare `stmt.set_target(tok.value); token_stream.consume()`
     instead of `_consume_arithmetic_target`, so `SUBTRACT 1 FROM
     VARIABLE (H, I, 1)` captured only `VARIABLE` and left `( H , I , 1 )`
     unconsumed as an "Unparsed tokens" content-drop warning. Fixed by
     routing the `IDENTIFIER` case through `_consume_arithmetic_target`
     (numeric-literal/level-number/figurative-constant targets, which can
     never carry a subscript, keep the original bare-consume branch).
  2. `_utils.consume_keyword_and_operand` — shared by every arithmetic
     statement's `GIVING` clause (ADD, SUBTRACT, MULTIPLY, DIVIDE) — only
     accepted a single bare `IDENTIFIER` token, so `ADD 1 TO A GIVING
     RESULT (H, I, 1)` dropped `(H, I, 1)` from the `GIVING` target too.
     Fixed by extracting the paren-depth-tracking subscript loop
     `_consume_arithmetic_target` already had into a new shared
     `consume_optional_subscript` helper in `_utils.py`, used by both
     `consume_keyword_and_operand` and (now refactored to call it)
     `_consume_arithmetic_target` itself.
  Pinned by three new tests written first and confirmed failing (dropped
  subscript, non-empty `warnings`/wrong return value) against the old
  behavior: `tests/unit/test_arithmetic_migration.py::test_subtract_statement_with_subscripted_target`,
  `::test_add_statement_with_subscripted_giving_target`, and
  `tests/unit/test_utils_clause_collection.py::TestConsumeKeywordAndOperand::test_consumes_subscripted_target`.
  Full unit (4625 passed / 4 skipped / 1 xfailed) and regression+integration
  (1870 passed / 4 skipped) suites all still green; `ruff`/`black`/`mypy`
  clean on the touched files.

## 2026-07-21 (ADD ... TO subscripted target dropped)

* **Updated** [parser.md](parser.md): `AddStatementParser`'s `TO` branch
  (`parsers/statements/arithmetic_parsers.py`) consumed its target via a
  private `_consume_identifier` helper that accepted only a bare
  `IDENTIFIER` token — unlike `COMPUTE`'s `_consume_arithmetic_target`
  (already shared), which folds a trailing `(subscript[, subscript]...)`
  group into the target string. `ADD 1 TO TABLE-ITEM (I, J, K)` therefore
  captured only `TABLE-ITEM` as the target and left `( I , J , K )`
  unconsumed as an "Unparsed tokens" content-drop warning; in a
  two-statement paragraph the recovery was bad enough to drop a
  *following* subscripted `ADD` statement from the AST entirely. Fixed by
  switching `AddStatementParser` to call the same `_consume_arithmetic_target`
  helper COMPUTE uses instead of its own bare-identifier method (removed);
  `AddStatement.target` now produces the same `"NAME ( SUB1 , SUB2 )"`
  shape COMPUTE already does for subscripted targets. Pinned by two new
  tests in `tests/unit/test_arithmetic_migration.py`
  (`test_add_statement_with_subscripted_target`,
  `test_add_statement_with_subscripted_target_and_giving`), written first
  and confirmed failing (dropped/truncated statement, non-empty
  `warnings`) against the old behavior before the fix. Full unit
  (4620 passed / 4 skipped / 1 xfailed), regression, and integration
  suites (1870 passed) all still green; `ruff`/`mypy` clean on the
  touched files.

## 2026-07-20 (WRITE ADVANCING mnemonic-name / SPECIAL-NAMES mnemonic clauses)

* **WRITE `ADVANCING` now accepts a mnemonic-name or identifier target**
  (`parsers/statements/write_parser.py`): `BEFORE|AFTER [ADVANCING]
  {integer-1 | identifier-1 | mnemonic-name-1}` previously only handled
  `integer-1` — an `IDENTIFIER` token (a line-count data-name, or a
  SPECIAL-NAMES mnemonic-name like a printer channel) was left
  unconsumed, and the leftover token was then mis-parsed by the procedure
  division scanner as a bogus paragraph header (`WRITE rec AFTER
  ADVANCING TOP-OF-PAGE.` produced an empty `advancing_clause` plus a
  phantom `TOP-OF-PAGE` paragraph). A trailing `LINE`/`LINES` after the
  identifier distinguishes `identifier-1` (`unit="LINES"`) from
  `mnemonic-name-1` (`unit="MNEMONIC"`, no suffix). `PAGE` still hits the
  existing CHANNEL path.
* **SPECIAL-NAMES mnemonic-name clauses are now captured**
  (`parsers/divisions/environment_sections.py`): `implementor-name IS
  mnemonic-name [ON STATUS IS cond] [OFF STATUS IS cond]` (e.g. `C01 IS
  TOP-OF-PAGE`, `CONSOLE IS CRT`, UPSI switch forms) previously fell into
  the SPECIAL-NAMES paragraph's generic unknown-clause fallback and was
  discarded with no trace. Detected via one-token lookahead (`name IS
  ...`) and collected into `special_names["mnemonic_definitions"]`.
  Pinned by `tests/unit/test_special_names.py` and
  `tests/unit/test_write_advancing.py`. Updated `parser.md`,
  `ast-models.md`, and `CHANGELOG.md` (Unreleased).

## 2026-07-20 (PERFORM THRU gaps: numeric procedure names + range reachability)

* **All-digit procedure names** (`PERFORM 1000 THRU 1999` numbering):
  `procedure_boundaries.py` recognizes numeric paragraph headers
  (`_is_procedure_name_token`), and `perform_parser.py` no longer consumes
  a numeric token as a speculative TIMES count — TIMES is checked by
  lookahead first, and all-digit tokens are accepted as the PERFORM target
  and the THRU end. Updated `parser.md`.
* **THRU range members reachable**: `program_flow/graph.py`
  `find_unreachable_nodes` treats every `FlowEdge.range_members` entry as a
  neighbor of the edge source, ending false `unreachable_nodes` for range
  intermediates whose fall-through edge was suppressed. Updated
  `analysis.md`.
* Pinned by `tests/unit/test_perform_thru_numeric.py` and
  `tests/unit/analysis/test_program_flow_thru_reachability.py`.

## 2026-07-20 (multi-line REDEFINES clause fix)

A `REDEFINES` keyword separated from its target data-name by a line break
lost the target (NEWLINE token between keyword and identifier). Fixed in
both the pure-Python clause loop (`data_clauses.py`, via `_skip_newlines`)
and the Cython fast path (`_data_fast.pyx`, inline newline-skip loop;
`_data_fast.c` regenerated with Cython 3.2.4). New multi-line REDEFINES
cases in `tests/unit/test_data_division_branches.py::TestRedefinesClause`,
including a forced pure-Python-loop variant. Updated `parser.md`
(multi-line clause gotcha) and `CHANGELOG.md` (Unreleased → Bug Fixes).

## 2026-07-20 (WRITE BEFORE/AFTER without ADVANCING keyword)

* **`WRITE ... AFTER 1` (no `ADVANCING`) no longer drops the clause**
  (`parsers/statements/write_parser.py`): the `ADVANCING` keyword is
  optional in the standard `BEFORE|AFTER [ADVANCING] [n] [LINES|LINE|PAGE]`
  phrase, but the parser required it — `AFTER 1`, `AFTER 1 LINE`, and
  `BEFORE PAGE` consumed the `BEFORE`/`AFTER` token and then recorded
  nothing, with a trailing `LINE`/`LINES` surfacing as an "Unparsed
  tokens" content-drop warning. The count/unit parsing now runs whether
  or not `ADVANCING` is present. Pinned by
  `tests/unit/test_write_advancing.py`. Updated `parser.md` and
  `CHANGELOG.md` (Unreleased).

## 2026-07-20 (open-findings M6/M10/M11/M12/M13/M15 batch fix)

The six MEDIUM findings previously deferred as subsystem rewrites are
fixed, each pinned by its own
`tests/regression/test_open_findings_m<N>_regression.py`:

* **M13** — `apply_replacing_clauses` is a context-aware line scanner
  (comment lines and string literals protected); `:ABC:` pseudo-text
  delimiters stripped by `CopyStatementLexer._read_operand` so colon
  operands substitute. Updated `preprocessing.md`.
* **M10** — `preprocess_conditional_compilation` evaluates real `>>IF`
  conditions (comparisons, `AND`/`OR`/`NOT`, `DEFINED`) against valued
  symbols (`dict` accepted; pre-existing CLI `--define NAME=VALUE` values
  now take effect), and implements
  `>>EVALUATE`/`>>WHEN`/`>>WHEN OTHER`/`>>END-EVALUATE`. Obsolete pins
  in `test_tier4_audit_remediations.py` updated. Updated
  `preprocessing.md`.
* **M11** — `ExecCicsStatement.options` dict, `ExecImsStatement` DLI
  function + positional args, tokenizer-based `parse_exec_sql`
  (`select_columns`, `where_present`, `:VAR:IND`). Additive only.
  Updated `parser.md`.
* **M12** — `ComputeStatement.expression_tree` (precedence-parsed) and
  `CobolExpression.condition_tree` for PERFORM UNTIL / IF-fallback
  conditions, via new shared `parsers/statements/_conditions.py`. Raw
  strings and dict output for pre-existing shapes unchanged. Updated
  `parser.md`, `ast-models.md`.
* **M15** — `detect_encoding` plausibility scoring over a 64 KiB prefix;
  `encoding_errors` (`"replace"`/`"strict"`) on `CopybookSearchPath` /
  `expand_copybooks`. Updated `preprocessing.md`.
* **M6** — `tokenize_cobol()`/CLI `tokenize` unified onto
  `normalize_fixed_format` + free-form lexing with COMMENT tokens
  re-emitted at original line numbers (`_tokenize_source`). No Cython
  mirror touched. Updated `lexer.md`.

`reports/open-findings.md` and `CHANGELOG.md` (Unreleased) updated in the
same batch. Remaining open: M17 (coverage debt) and LOW findings.

## 2026-07-17 (VALUE ALL literal clause support)

* **`VALUE ALL <literal>` parsed instead of dropped**
  (`divisions/data_clauses.py`, `parse_value_clause`): `ALL` lexes as a
  `FIGURATIVE_CONSTANT`, so the previous literal branch consumed it as a
  complete value and the repeated literal (`'='`) fell through to the
  unknown-clause loop as an "Unparsed token" content-drop warning —
  which made mockymock refuse the program (PARSE_WARNING, fail-closed).
  Surfaced by the legacy-application corpus re-sweep on `EODPROC.cbl`'s
  report-separator idiom `05 FILLER PIC X(133) VALUE ALL '='.`. New
  handling: `ALL` + string literal → `value_clause='ALL "="'`; `ALL` +
  figurative constant → `'ALL ZEROS'`; bare `ALL` keeps the old
  figurative-constant result. The literal may sit on a continuation line
  (newlines skipped after `ALL`, same as after `VALUE`/`IS`). The Cython
  `_data_fast` path is unaffected — it delegates VALUE parsing back to
  this Python method. Regression suite:
  `tests/regression/test_value_all_clause.py` (6 tests, includes a
  no-warnings assertion). Updated `parser.md` (VALUE ALL note) and
  `CHANGELOG.md` (Unreleased).

## 2026-07-15 (PR #89 review fixes: Area A comment-entry termination, COPY warning wording, REPLACE scanner rewind)

Three small fixes out of the PR #89 self-review:

* **Comment-entry termination completed** (`divisions/identification.py`):
  per COBOL-74, *any* entry starting in Area A ends a comment-entry — not
  just recognized clause keywords. The clause-value loop now stops at a
  line-starting Area A token (tracked via each consumed token's line, so
  same-line values after `AUTHOR.` are unaffected), and the main loop's
  unknown-clause recovery closes `in_comment_entry` on an Area A token.
  Two new tests in `tests/regression/test_comment_entry_area_b.py`
  (unknown Area A word closes the entry; an Area B `AUTHOR` keyword does
  not open one).
* **Un-expanded COPY warning is path-neutral**
  (`preprocess/replace_statement.py`): now `COPY <member> was not
  expanded; ...` — the old "(no copybook path configured)" was wrong when
  expansion ran but couldn't resolve the member. mocky-mock's adapter
  matches on `COPY ` + `not expanded`, unaffected.
* **REPLACE scanner rewind** (`preprocess/replace_statement.py`): a failed
  `_parse_replace_at` now rewinds to just past the matched keyword
  (captured after `_match_word`), not `keyword_start + 7`, which could
  land mid-word when separators preceded the keyword.

Full suite: 6797 passed / 18 skipped / 1 xfailed; ruff/black/mypy clean.

## 2026-07-14 (Area B–aware comment-entry termination; NIST KNOWN_ISSUES emptied)

Made the IDENTIFICATION DIVISION parser's boundary checks comment-entry
aware (`parsers/divisions/identification.py`,
`_at_comment_entry_aware_boundary`): COBOL-74 comment-entries end only at
the next **Area A** entry, and `normalize_fixed_format` preserves Area A/B
as leading indentation. The parser now tracks an `in_comment_entry` state —
opened when an AUTHOR/INSTALLATION/DATE-WRITTEN/DATE-COMPILED/REMARKS/
SECURITY entry itself starts in Area A (at or left of the division's own
header column, stashed by `BaseDivisionParser.parse` as
`_division_header_column`), closed by PROGRAM-ID or an Area A division
header — and **only while that state is active** does an Area B
division-header-shaped sequence count as comment text instead of a
boundary. Fixes NIST `OBNC1M`, whose SECURITY comment-entry embeds an
entire phony program in Area B — previously the phony `ENVIRONMENT
DIVISION.` ended the division early and the phony `IDENTIFICATION
DIVISION.` spawned a bogus program unit failing "PROGRAM-ID is mandatory".
The state-gating matters: suppressing on column geometry alone broke 31
tests whose loosely indented sources put every real division deeper than
the IDENTIFICATION header — outside a comment-entry the column is
deliberately ignored and those keep terminating the division exactly as
before. Pinned by `tests/regression/test_comment_entry_area_b.py`.

Also moved `SM101A` from `KNOWN_ISSUES` to a new
`REQUIRES_COPYBOOK_EXPANSION` set in
`tests/integration/test_nist_cobol85_support.py`: its COPY members are
statement fragments by design, so the strict parametrized test now parses it
through the copybook-expansion pipeline (as a compiler must) and requires
zero errors — a stronger guarantee than the previous strict-xfail.

**`KNOWN_ISSUES` is now empty: all 459 NIST COBOL-85 programs parse
error-free** (517 passed / 0 xfailed in the NIST support suite).

## 2026-07-14 (REPLACE statement + un-expanded COPY pseudo-text substitution)

Implemented COBOL source-text pseudo-text substitution as a preprocessing pass
run before lexing, in a new module `cobolparser/preprocess/replace_statement.py`,
wired into `CobolParser._parse_core` just before `CobolLexer`. Two NIST
COBOL-85 programs (`SM206A`, `SM208A`) now parse error-free and were removed
from `KNOWN_ISSUES` in `tests/integration/test_nist_cobol85_support.py`.

* **`apply_replace_statements`** — the `REPLACE ==a== BY ==b== [ ... ] .`
  compiler-directing statement (one or more operand pairs) with `REPLACE OFF.`
  cancelling the active set. Matching is on a COBOL **text-word** stream via a
  new `_tokenize_text_words`: space/comma/semicolon separators are equivalent
  (not text words), a separator period IS its own text word (so `MOVE WS-A TO
  WS-B.` matches a find of `MOVE WS-A TO WS-B` and keeps the sentence period),
  literals are single words compared case-sensitively, other words compare
  case-insensitively. A single left-to-right scan per segment applies the
  active pairs (first match wins); the REPLACE statements themselves are
  blanked. Fixes `SM208A` (30x `REPLACE`; `MOVE "*" AO ...`, `==MOVE "FAIL"
  TO==`, giant 160-quote literals, multi-line pseudo-text, `,`/`;` separators,
  empty `====` deletion).
* **`strip_unexpanded_copy_statements`** — blanks `COPY` statements the
  standalone (`parse_cobol`) pipeline will not expand, reusing the existing
  pseudo-text-aware `CopyStatementLexer` (single COPY parser, not a divergent
  one). This removes the whole statement — including a `REPLACING
  ==pseudo-text==` operand that legally contains statement keywords/periods —
  so nothing leaks into the token stream. Fixes `SM206A`, whose `COPY KP004
  REPLACING ... BY MOVE ==DELETE== ...` leaked a bare `MOVE` as a MOVE with no
  TO. In the copybook-expansion pipeline COPY is already inlined before this
  point, so the strip is a no-op there (verified: `SM206A` still parses clean
  with expansion, `SM101A`/`SM207A` expansion tests unaffected).

Both passes preserve their input's physical line count (every newline in a
removed/replaced span is re-emitted) so downstream error line numbers stay
aligned. Both are cheap no-ops when the source contains no `REPLACE`/`COPY`
keyword. Full suite stays green (6791 passed / 18 skipped / 3 xfailed; +24 new
tests, and `SM206A`/`SM208A` flipped from strict-xfail to pass). Pinned by
`tests/regression/test_replace_and_copy_pseudo_text.py`.

## 2026-07-14 (H9 refinement: clause-continuation keywords + SQL special registers)

Refined `looks_like_paragraph_boundary()` (`parsers/statements/_utils.py`) so
the H9 missing-period recovery no longer misclassifies two real-world shapes
surfaced by the mockymock legacy-application corpus sweep:

* Added `CLAUSE_CONTINUATION_KEYWORDS` (`DELIMITED`, `TALLYING`, `POINTER`,
  `GIVING`, `ROUNDED`, ...) and `SQL_SPECIAL_REGISTERS` (`SQLCODE`,
  `SQLSTATE`) frozensets, excluded alongside `STATEMENT_KEYWORDS`. These are
  reserved words / precompiler-provided registers that lex as plain
  `IDENTIFIER` but can never legally be a paragraph name, so a multi-source
  `STRING` with each `DELIMITED BY SIZE` clause on its own continuation line,
  or a period-less `DISPLAY` before a bare `SQLCODE`, no longer truncates the
  AST.
* The "next token must be a period or `SECTION`" lookahead is **kept**.
  Dropping it (as the abandoned PR #87 branch did) looked attractive for
  catching unknown-verb shapes, but is a proven real-world regression: a
  continuation-line operand named by an *unexpanded* COPY member is not in
  `known_data_names`, so without the shape check it is misread as a
  boundary and the statement truncated — mocky-mock's copybook fixtures
  (`COMPUTE X =` / newline / `ORD-AMOUNT ...` with `COPY ORDREC.`
  unresolved) caught exactly this.

Pinned by `tests/regression/test_clause_continuation_boundary.py`.

## 2026-07-15 (division-parser god-class refactor)

* [parser.md](parser.md): `DataDivisionParser`
  (`parsers/divisions/data.py`, ~1,467 lines) decomposed into collaborators
  `data_clauses.py` (`DataItemClauseParser`), `data_file_description.py`
  (`FileDescriptionClauseParser`), and `data_special_entries.py`
  (`SpecialEntryParser`). The division parser keeps its import path and the
  `_parse_picture_clause`/`_parse_value_clause`/`_parse_usage_clause`
  wrappers required by the `_data_fast` Cython callback surface. Division
  Parsers table updated; behavior-preserving, no public API change.
* [parser.md](parser.md): `EnvironmentDivisionParser`
  (`parsers/divisions/environment.py`, ~1,133 lines) decomposed into
  `environment_sections.py` (`ConfigurationSectionParser`,
  `InputOutputSectionParser`) and `environment_select.py`
  (`SelectClauseParser`). The division parser keeps its import path and
  delegates; behavior-preserving, no public API change.
* [parser.md](parser.md): `ProcedureDivisionParser`
  (`parsers/divisions/procedure.py`, ~912 lines) decomposed into
  `procedure_registry.py` (`create_statement_registry()`),
  `procedure_boundaries.py` (boundary predicates), and
  `procedure_recovery.py` (`StatementRecoveryHandler`,
  `STRAY_MARKERS`/`UNSUPPORTED_VERBS`). The division parser keeps its
  import path and the paragraph/section dispatch loop; the "Adding a New
  Statement Parser" flow now registers parsers in `procedure_registry.py`.
  Behavior-preserving, no public API change.

## 2026-07-14 (program_flow god-class refactor)

* [analysis.md](analysis.md): `cobolparser/analysis/program_flow.py` (~987-line
  `ProgramFlowAnalyzer` class) decomposed into the package
  `cobolparser/analysis/program_flow/` with focused collaborators —
  `models.py`, `scanner.py` (`ProcedureScanner`), `edges.py`
  (`EdgeCollector` + edge-type category sets), `cycles.py`, `graph.py`,
  `analyzer.py`. Behavior-preserving: public API, import paths, and
  `to_dict()` output unchanged (verified byte-identical against the old
  implementation across all sample programs).

## 2026-07-09 (CobolCheck test generation removed — superseded by mockymock)

Removed the CobolCheck test-generation feature end to end: the
`cobol-parser generate-tests` CLI subcommand, the `generate_cobolcheck_tests()`
Python API, and the `CoverageAnalyzer` / `TestPlanGenerator` /
`CobolCheckGenerator` classes (`cobolparser/analysis/coverage_analyzer.py`,
`cobolparser/analysis/test_plan.py`, `cobolparser/generators/cobolcheck.py`,
all deleted), plus their ~180 dedicated tests across 6 test files. Confirmed
via `interface-contract.md` that the backend adapter never called into this
feature, so no cross-repo consumer was affected. The vendored copy in
`backend/_vendor/cobol-parser/` was re-synced afterward. Full suite still
passes (6,638 passed / 13 skipped / 5 xfailed) at 92.44% coverage, above the
81% floor.

* **Updated** [cli.md](cli.md): removed the "Generate-Tests" subcommand
  section and the CobolCheck mention in Output Identification.
* **Updated** [analysis.md](analysis.md): removed the "CoverageAnalyzer +
  TestPlanGenerator + CobolCheckGenerator" section, its Public API imports,
  and its two Module File Map rows; module count 15 → 13.
* **Updated** [tests.md](tests.md): refreshed pass count and the
  `generators/` directory description (flowchart tests only now).

## 2026-07-09 (ENVIRONMENT/DATA division sections stamped with the wrong line — user-reported)

A user testing the parser noticed that `ENVIRONMENT DIVISION`'s
`CobolDivision` node and its `INPUT-OUTPUT SECTION` `CobolSection` reported
the exact same `line`/`column` in the AST's `to_dict()` output. Confirmed as
a real, consistent bug (not specific to that one division): every
`CobolSection`/`CobolParagraph` built by `environment.py`'s and `data.py`'s
`_create_ast_node()` reused the division's own `start_location` instead of
its own header token's location — `procedure.py` already tracked per-section
locations correctly, so only these two division parsers needed the fix.
Both now capture each section's (and the FILE-CONTROL paragraph's) own
keyword-token location during parsing and thread it through to
`_create_ast_node`. Pinned by new file
`tests/regression/test_section_location_tracking.py` (TDD: written first,
confirmed failing against the old behavior, then fixed).

* **Updated** [parser.md](parser.md): new "Section/Paragraph Location
  Tracking" section describing the root cause and fix.

## 2026-07-09 (H10 fixed: out-of-line `PERFORM ... VARYING ...` dropped, `perform_type` mistagged)

A user reported, and personally verified before reporting, that the
out-of-line form of `PERFORM procedure-name VARYING ...` was not parsed
at all: the clause was silently dropped and `PerformStatement.perform_type`
stayed the default `"SIMPLE"`, indistinguishable from a genuine plain
`PERFORM`. The user's own diagnosis was precise: what actually prevented
this from being a live problem today was an unrelated mechanism — the
generic dropped-clause parse warning tripping an unrelated downstream
refusal gate (in a consuming service, outside this repo) before any
terminator logic there ran — a real but accidental safety net that would
go silent again if the out-of-line VARYING shape were ever parsed without
also fixing the tagging.

Filed as H10 in `reports/open-findings.md` (a new finding, not from this
document's own prior audit passes) and fixed same-day. Root cause:
`perform_type` only became `"VARYING"` as a side effect of
`set_varying_clause()`, which requires a fully-parsed `until_condition` —
confirmed to be a strictly worse, fully silent instance of the *same* bug
already present on the *inline* PERFORM VARYING form (no accidental
warning to mask it there). Fixed via a new `PerformStatement.
mark_varying()`, called the instant the `VARYING` keyword is consumed,
before `FROM`/`BY`/`UNTIL` are attempted — plus a missing out-of-line
`VARYING` dispatch in `perform_parser.py`, and an explicit warning on any
VARYING clause that doesn't fully parse. Pinned by
`TestPerformVaryingOutOfLine` in `tests/regression/test_perform_backward_compat.py`
and a strengthened assertion in `TestPerformVaryingMissingUntil`
(`tests/unit/test_perform_edge_cases.py`) for the inline-form case.

* **Updated** [parser.md](parser.md): H10 added to the "open-findings.md
  HIGH-severity fixes" section (now "H1-H10"), full write-up alongside the
  existing H1-H9 entries.

## 2026-07-09 (open-findings.md MEDIUM-severity remediation: M1, M2, M3, M4, M5, M7, M8, M9, M14, M16 fixed)

Follow-up to the same-day H1-H9 pass above: implemented fixes for 10 of
the 17 MEDIUM findings in `reports/open-findings.md`, chosen (per user
decision) as the ones contained enough to fix with real TDD in one pass;
M6, M10, M11, M12, M13, M15 (each close to its own subsystem rewrite)
deferred to separate plans, and M17 (branch-coverage debt, not a bug) not
attempted. Each pinned by a dedicated test class in new file
`tests/regression/test_open_findings_medium_regressions.py` (30 tests
total, including a Cython/pure-Python parity check). Full per-finding
writeup: `CHANGELOG.md` (Unreleased → Fixed). `reports/open-findings.md`
updated in place — all 10 marked `FIXED 2026-07-09` (left visible for
traceability, per the file's own convention), M3 and M7 marked partial
with residual write-ups appended in place.

M3 (screen positioning / extended ACCEPT clauses) was scoped by grepping
`examples/cobol/shamrice/*.cbl` — the corpus the finding's original hit
counts came from — rather than guessing IBM grammar the finding text
didn't fully specify: `AT` positioning turned out to be 100%
combined-numeric (`AT 0330`) in real usage with zero `AT LINE n COLUMN m`
hits, and `SECURE`/`NO-ECHO` turned out to be semantically distinct
(`SECURE` masks with `*`, `NO-ECHO` shows nothing) per the corpus file's
own comment — both facts the finding text alone didn't establish.

* **Updated** [parser.md](parser.md): new "open-findings.md
  MEDIUM-severity fixes (2026-07-09)" section (mirrors the H1-H9 section
  above it), covering M1 (`DISPLAY` figurative constants —
  `TokenType.FIGURATIVE_CONSTANT` missing from the display-item accepted
  set), M2 (`DISPLAY WITH NO ADVANCING` — `WITH`/`NO`/`ADVANCING` lex as
  dedicated `TokenType`s the item loop didn't handle;
  `DisplayStatement.with_no_advancing` added), M3 (`AT` positioning on
  `DISPLAY`/`ACCEPT` plus `ACCEPT`'s `SECURE`/`NO-ECHO`/`TIMEOUT`/
  `AUTO-SKIP`/`UPPER` — corpus-scoped as above; `IOAcceptStatement`
  gained `secure`/`timeout_value`/`auto_skip`/`upper`, its pre-existing
  `at_line`/`at_column`/`with_no_echo` scaffolding finally wired up), M9
  (`try_parse_nested_statement`'s bare `except Exception` now surfaces a
  warning unless the exception is already `_already_recorded` by
  `report_or_raise` — distinct call site from H4's 5 bare excepts in
  `perform_parser.py`), and M16 (`_PICTURE_SYMBOL_TOKEN_TYPES` used
  `TokenType.DIVIDE`/`MULTIPLY`, the *statement keyword* tokens, instead
  of `TokenType.DIVIDE_OP`/`MULTIPLY_OP`, so `/`- and `*`-edited pictures
  like `PIC 99/99/99` truncated at the first edit symbol and the
  remainder was misparsed as phantom level-99 data items).
* **Updated** [lexer.md](lexer.md): "Warnings" section gained a second
  producer — `read_prefixed_literal_from_text` now validates hex content
  for `X'..'`/`NX'..'` typed literals (odd digit count or non-hex
  characters both now warn; `G'..'`/`N'..'` untouched) — finding M7,
  fixed partially (validation only, not decoding).
* **Updated** [preprocessing.md](preprocessing.md): `normalize_fixed_format`
  gained a `debug_lines_as_comments` keyword (default `True` — `D`/`d` in
  column 7 now treated as a comment, matching
  `copy_statement_parser.is_comment_line()`, closing the M4 two-pipelines-
  disagree gap) and tab-expands each line (`str.expandtabs(8)`) before
  any column-sensitive slicing (M8). Trailing blanks on a line are now
  preserved when a literal remains open at end of line, only stripped
  once confirmed closed (M5) — both the opening-line and
  literal-continuation branches, pure-Python and Cython. Copybook
  Expansion section gained a note on M14: cache hits in
  `_expand_source_recursive` now count toward `context.total_bytes` the
  same as a miss does (previously only misses did, so diamond-dependency
  copybooks under-counted against `max_total_size`).
* **Updated** [tests.md](tests.md): test count refreshed to 6,789 passed
  / 13 skipped / 5 xfailed, 92.65% coverage.
* Cython extension rebuilt (`python setup.py build_ext --inplace`) for
  the M4/M5/M8 `_preprocess_fast.pyx` changes; regenerated `.c` committed
  alongside. Verified both `_lexer_fast`/`_preprocess_fast` report as
  active post-rebuild (`tests/unit/test_fast_import.py`) and a dedicated
  parity test confirms the Cython and pure-Python paths agree on all
  three new behaviors.
* Full suite (6,789 tests) and `ruff`/`black`/`mypy` all pass after the
  batch; the real `examples/cobol/shamrice/accept.cbl`,
  `accept-secure.cbl`, and `mouse_example.cbl` files (the M3 motivating
  corpus) now parse with zero `AT`/`SECURE`/`NO-ECHO`/`TIMEOUT`/
  `AUTO-SKIP`/`UPPER`-related warnings.

## 2026-07-09 (H9 fixed: missing-period paragraph-boundary swallow)

Follow-up to the same-day H1-H8 pass below: fixed H9, the one HIGH finding
that pass had deliberately left open. A statement missing its terminating
period, immediately followed by what should be a new paragraph header, had
the paragraph name absorbed as a trailing operand instead of starting a
new paragraph — confirmed by direct repro in `DISPLAY`'s item list,
`MOVE`'s target list, `COMPUTE`'s expression capture, `STRING`'s operand
list, `UNSTRING`'s `INTO` target list, and `INSPECT`'s `TALLYING`
counter-name loop / outer "consume to period" trailer (not IF-specific,
not a single-statement bug; `SET`, the fixed-arity arithmetic
target/GIVING slots, and `IF` were probed and found already safe). Fixed
via a new `looks_like_paragraph_boundary()` predicate in
`parsers/statements/_utils.py` that mirrors COBOL's own
paragraph-name-vs-operand disambiguator (first token on its source line,
immediately followed by a period/SECTION, not a DATA DIVISION name) rather
than trying to resolve the ambiguity from grammar shape alone — the raw
grammar cannot tell "last operand of an unterminated statement" from "next
paragraph name" since both are just `IDENTIFIER` then `PERIOD`. Applied
only to the six statement parsers confirmed by direct repro, not
universally, per the original finding's own "needs its own scoped
investigation" framing (see [parser.md](parser.md) for the full
per-file breakdown and the deliberately-out-of-scope call sites).
Recovery now warns (matching the H7/H8 "warn, don't silently
reinterpret" precedent) rather than staying silent; where a fix site has
both an inner sub-parser check and an outer trailer that both see the
same un-consumed token (`INSPECT` TALLYING, `UNSTRING` INTO), only the
outer one emits the warning to avoid duplicates.

* **Updated** [parser.md](parser.md): replaced the H9 "not fixed" bullet
  (end of the "open-findings.md HIGH-severity fixes (2026-07-09, H1-H8)"
  section) with the fix writeup — files touched
  (`_utils.py`, `display_parser.py`, `move_parser.py`,
  `arithmetic_parsers.py`, `string_unstring_parsers.py`,
  `initialize_inspect_parsers.py`, `core/interfaces.py`,
  `parsers/divisions/procedure.py`), the first-on-line +
  not-a-data-name disambiguation rule, the
  `ParseContext.known_data_names` threading mechanism, the inner/outer
  warning-dedup split for `INSPECT`/`UNSTRING`, and the deliberate scope
  boundary (only 6 of the 16 `is_statement_boundary()` call sites
  touched; the undeclared-identifier-on-a-continuation-line case remains
  an acknowledged residual ambiguity).
* `reports/open-findings.md`: H9 marked "FIXED 2026-07-09" in place (same
  traceability convention as H1-H8); the HIGH-section summary line updated
  from "H1-H8 fixed... H9 not fixed" to "H1-H9 are all fixed".
* `CHANGELOG.md` (Unreleased → Fixed): added the H9 writeup as its own
  bullet, and updated the H1-H8 entry's "noted but intentionally not fixed
  here" paragraph to point at it instead of describing it as still open.
* Pinned by 9 new tests in
  `tests/regression/test_open_findings_high_regressions.py::TestH9MissingPeriodParagraphBoundary`
  (one repro per fixed statement/clause shape, plus two guard cases proving the
  DATA DIVISION cross-check prevents false positives on undeclared
  same-line operands and declared continuation-line operands). Full suite
  (6759 tests) and `ruff`/`black`/`mypy` all still pass.

## 2026-07-09 (open-findings.md HIGH-severity remediation: H1-H8 fixed, H9 discovered)

Implemented fixes for all 8 HIGH findings in `reports/open-findings.md`'s
2026-07-08 re-verification pass, each pinned by a dedicated test class in
new file `tests/regression/test_open_findings_high_regressions.py` (21
tests total). Full per-finding writeup: `CHANGELOG.md` (Unreleased →
Fixed). `reports/open-findings.md` itself updated in place — H1-H8 marked
resolved (left visible for traceability, per the file's own convention for
prior audits), and a new H9 finding recorded for the one thing discovered
but *not* fixed in this pass.

* **Updated** [lexer.md](lexer.md): added a "Warnings (non-fatal
  diagnostics)" section. `CobolLexer` (pure-Python and `_lexer_fast`
  Cython) now tracks `self.warnings`, exposed via `has_warnings()`/
  `get_warnings()`; `CobolParser.parse()` forwards them into
  `ParseResult.warnings` (prefixed `"Lexer warning: "`). First producer:
  an unterminated string literal in the free-form path (the only lexing
  mode `parse_cobol()` ever uses) used to close silently at the line
  boundary with `errors=0, warnings=0` — now warns instead, without
  promoting to a hard error (H7).
* **Updated** [parser.md](parser.md): new "open-findings.md HIGH-severity
  fixes (2026-07-09, H1-H8)" section, summarizing H1 (`SET ADDRESS OF`
  target-loop `OF`-type gap), H2 (COMPUTE unbalanced-paren boundary-guard
  bypass — additive to the 2026-07-06 COMPUTE-swallow fix already
  documented above it), H3/H4 (PERFORM trailing-TIMES-candidate silent
  discard + 5 unlogged bare excepts in `perform_parser.py`), and H8
  (`CLOSE`'s per-file option if/elif chain converted to a loop so combined
  options like `REEL WITH NO REWIND` all survive). Also records **H9**
  (not fixed): a statement with no terminating period, immediately
  followed by what should be a new paragraph header, gets its name
  absorbed as a trailing operand instead of starting a new paragraph —
  discovered while verifying H7's "unclosed IF" sub-claim (which, on
  investigation, turned out to be legal, correctly-parsed COBOL, not a
  bug). Distinct root cause, not IF-specific, deliberately left unfixed
  (high-blast-radius paragraph-boundary surgery, out of scope for this
  bounded 8-finding pass).
* **Updated** [analysis.md](analysis.md): `MoveTypeChecker` gained
  `MoveTypeReport.unresolved_count` (H5) — previously an unresolvable
  source/target `DataCategory` caused a silent early `return`/`continue`
  with no counter anywhere, so 3 MOVEs on undeclared identifiers produced
  `violations: [], error_count: 0, warning_count: 0`, a false all-clear.
  Also corrected a pre-existing doc error in the same section: the method
  is `.check(ast)`, not `.analyze(ast)`.
* **Updated** [preprocessing.md](preprocessing.md): new "Copybook Path
  Resolution (`path_resolver.py`)" section documenting the 3-tier
  resolution strategy and the H6 fix — the Tier-2 directory-index fast
  path returned an indexed path after only a size check, never calling
  `validate_path_within_directory()` (which Tier 3 does call), so a
  symlink inside a search directory pointing outside it would bypass
  containment checking. Now validated via a new
  `_validate_indexed_result()` at both Tier-2 hit points. Also fixed in
  the same pass: the `".."` traversal guard was substring matching
  (false-flagged `weird..name.cpy`); now a path-segment check.
* **Updated** [tests.md](tests.md): +21 tests
  (`tests/regression/test_open_findings_high_regressions.py`); full suite
  now 6,750 passed / 13 skipped / 5 xfailed, 92.61% coverage.
* Also fixed while verifying H2: `tests/samples/arithmetic_operations.cbl`
  had a `FUNCTION MAX(WS-NUM-1, WS-NUM-2, WS-NUM-3)` line whose closing
  `)` landed in fixed-format column 73 and was silently truncated by
  `normalize_fixed_format` — previously masked by the very H2 bug (the
  truncated, permanently-unbalanced expression silently absorbed the next
  statement instead of erroring); the H2 fix correctly surfaces this now,
  so the sample was corrected (spaces after commas removed to fit column
  72) rather than the detection being weakened.

## 2026-07-09 (silent-drops-and-gaps audit: OCCURS KEY, program-flow clause bodies, REWRITE/START/ACCEPT/STOP operands, DATA warn channel)

Follow-up to the 2026-07-08 audit. Four parallel re-audits (DATA division,
analysis modules, statement parsers, AST serialization) each briefed on the
prior fix lists. AST-serialization review found nothing new; the other three
each surfaced genuine, runtime-reproduced silent drops. Full audit:
`reports/audit-2026-07-09.md`.

* **Updated** [parser.md](parser.md) / [ast-models.md](ast-models.md):
  OCCURS `ASCENDING/DESCENDING KEY IS ...` was dropped entirely, and because
  the OCCURS parser looked for `INDEXED` immediately after DEPENDING, a KEY
  clause sitting between them (standard COBOL order) also caused the following
  `INDEXED BY` to be eaten by the clause loop's `else: consume()`. `INDEXED BY
  a b` also kept only the last index name. Now parsed in both `data.py` and the
  `_data_fast.pyx` mirror (`.c` regenerated with Cython 3.2.4); `OccursClause`
  gained `key_clauses` (list of `{direction, keys}`) and `index_names` (all
  indexes; `indexed_by` keeps the first for compatibility), both serialized.
* **Updated** [analysis.md](analysis.md): `ProgramFlowAnalyzer`'s hand-rolled
  `scan()` recursed only into a subset of container statements (PERFORM inline,
  CALL handlers, IF/EVALUATE/SEARCH/RETURN) and never descended into IO
  (`AT END`/`INVALID KEY`/`AT EOP`), arithmetic (`ON SIZE ERROR`), or
  STRING/UNSTRING (`ON OVERFLOW`) clause bodies. A PERFORM/GO TO/CALL nested
  there produced no edge, cascading into **false `unreachable_nodes`** reports
  and missing flowchart arrows (contrast `DeadCodeAnalyzer`, which uses
  `get_all_statements()`). Fixed with a final `else` branch mirroring
  `coverage_analyzer._nested_statements`'s clause-attribute list.
* **Updated** [parser.md](parser.md) / [ast-models.md](ast-models.md): four
  statement-parser operand drops — `REWRITE rec FROM data` dropped the FROM
  source (`IORewriteStatement` gained `from_clause`); `START f KEY IS ...
  data-name` dropped the KEY data-name (`IOStartStatement` gained `key_name`);
  `ACCEPT x FROM DATE YYYYMMDD` dropped the format phrase and re-parsed it as a
  **phantom paragraph** (now captured into `from_source`); `STOP RUN RETURNING
  x` dropped the return code (`StopStatement` gained `returning`, and a bare
  numeric `STOP n` operand is now captured). `ACCEPT`/`UNLOCK` with a missing
  operand no longer consume the following statement's verb (`is_statement_
  boundary` guard).
* **Updated** [parser.md](parser.md): the DATA division clause loop's
  `else: consume()` fallback now emits an "Unparsed token ... in data item"
  warning for meaningful (non-whitespace) tokens — symmetric with the
  ENVIRONMENT division's SELECT handling. Previously any unsupported data-item
  clause (GROUP-USAGE, VOLATILE, DYNAMIC LENGTH, DESCENDING KEY, ...) vanished
  with `warnings=[]`.
* **Updated** [tests.md](tests.md): +13 tests
  (`tests/regression/test_tier6_silent_drop_audit.py`).

## 2026-07-08 (residual of the 2026-07-07 C2 fix: unsupported-verb boundary gap)

* **Updated** [parser.md](parser.md): closed the mockymock-audit-flagged
  residual of the 2026-07-07 C2 silent-drop fix — "an unknown verb directly
  after a period-less statement can still be swallowed with no warning
  (period-terminated layouts are covered)". C2's
  `ProcedureDivisionParser._warn_unsupported_statement` only fires when the
  top-level dispatch loop directly sees the offending token, which requires
  a period to hand control back to that loop at the right place. Without a
  period, the *previous* statement's own trailing-token loop (MOVE's target
  list, the arithmetic operand collector, etc.) decides for itself whether
  to stop, via `STATEMENT_TOKEN_TYPES`/`STATEMENT_KEYWORDS` (`_utils.py`) —
  and those sets were missing several verbs `_UNSUPPORTED_VERBS` already
  knew how to *label*, so the following statement's tokens were silently
  absorbed as bogus operands before ever reaching the label logic.
  Reproduced and fixed for: `DISABLE`, `ENABLE`, `PURGE`, `RAISE`, `READY`,
  `RECEIVE`, `RESET`, `RESUME`, `SEND`, `SERVICE`, `TRANSFORM` (string
  already in `_UNSUPPORTED_VERBS` but missing from the boundary sets);
  `EXECUTE`/`EXHIBIT`/`INVOKE` (string was already in `STATEMENT_KEYWORDS`,
  but the dedicated lexer `TokenType` was missing from
  `STATEMENT_TOKEN_TYPES`, which `MoveStatementParser`'s type-first check
  needs); `COMMIT`/`ROLLBACK` (have registered parsers, yet were in neither
  set — a fully-supported statement vanished, worse than the
  unsupported-verb case); and `CHAIN`, `ENTER`, `EXAMINE`, `GOTO` (fused
  one-word spelling only), `INITIATE`, `NOTE`, `RECOVER`, `SUPPRESS`,
  `TERMINATE` (real verbs with dedicated `TokenType`s, previously absent
  from every "known verb" set in this file).
  `ProcedureDivisionParser._UNSUPPORTED_VERBS` gained the newly-recognized
  unsupported verbs (not `COMMIT`/`ROLLBACK`, which now dispatch normally).
  Pure clause words that never start a statement (`ON`, `OTHERWISE`,
  `NEXT`, `THEN`, scope-terminator tokens, `DISPLAY-1`) were deliberately
  left out.
* **Updated** [parser.md](parser.md): `PURGE`/`RAISE`/`RESUME` have no
  dedicated lexer `TokenType` at all — they lex as plain `IDENTIFIER`,
  indistinguishable from a data-name — so adding their strings to
  `STATEMENT_KEYWORDS` only closed the gap for parsers whose trailing loop
  already consults it (MOVE, arithmetic). Ten *other* list-collecting loops
  never consulted `STATEMENT_KEYWORDS`/`is_statement_boundary` at all, and
  kept silently folding these three verbs into their list:
  `display_parser.py` (item list),
  `simple_statement_parsers.py::CancelStatementParser` (program-name list),
  `set_parser.py` (target list), `open_parser.py`/`close_parser.py`
  (file-name lists), `initialize_inspect_parsers.py::InitializeStatementParser`
  (target list) — none of these six *main* parse loops consulted the shared
  predicate at all; and `string_unstring_parsers.py::UnstringStatementParser
  ._parse_into_targets` (INTO target list), `sort_merge_parsers.py::
  _parse_keys` / `_parse_file_list` (KEY field list / USING·GIVING file
  lists, shared by SORT and MERGE),
  `initialize_inspect_parsers.py::InspectStatementParser._parse_tallying`
  (TALLYING counter-name loop) — these four are separate nested helper
  loops with their own hand-rolled boundary keyword list (or, for
  `_parse_tallying`, no boundary check at all) that predates/bypasses the
  `is_statement_boundary()` check their statement's *outer* loop already
  had (2026-07-06/2026-07-08 fixes). Each of the ten now breaks on
  `is_statement_boundary(token)` before accepting a bare `IDENTIFIER` as a
  list item.
* **Updated** [parser.md](parser.md): a related, more severe pre-existing
  bug (independent of the `STATEMENT_KEYWORDS` gaps above, found by the
  same sweep) — `PerformStatementParser._parse_until_condition_only` (the
  out-of-line `PERFORM paragraph-name UNTIL condition` form, no inline
  body) had **no boundary check whatsoever**: only a literal period or
  `END-PERFORM` stopped it. A period-less `PERFORM ... UNTIL cond` silently
  swallowed every remaining token in the program into the condition
  string — verified with a normal `DISPLAY`/`STOP RUN` pair, not just an
  unsupported verb, both of which vanished from the AST with
  `result.success == True`, `warnings == []`. Now stops at the same
  `STATEMENT_TOKEN_TYPES`/`STATEMENT_KEYWORDS` boundary the sibling
  `_collect_until_condition_tokens` helper (used by the inline PERFORM
  UNTIL/VARYING forms) already used.
* **Updated** [parser.md](parser.md): a fourth finding, in
  `EvaluateStatementParser` — two independent unguarded loops.
  `_parse_subjects` (subject list before the first `WHEN`) had no boundary
  check, same shape as the ten list-collecting loops above: a malformed/
  period-less `EVALUATE` with no `WHEN` folded a following verb into
  `stmt.subjects` as free text. Fixed the same way as the sibling
  `_parse_selectors` (already correct): `self._is_statement_keyword()`.
  More severe: the *outer* clause-scan loop between `_parse_subjects` and
  the `WHEN` dispatch treated any non-`WHEN`/`END-EVALUATE` token as noise
  to skip past, so a malformed `EVALUATE` could consume forward past entire
  intervening statements hunting for a literal `"WHEN"` — verified with a
  trailing `MOVE 1 TO WS-Y` followed by a second, well-formed `EVALUATE
  WS-Y ... WHEN 1 ... END-EVALUATE`: the first EVALUATE annexed the
  *second* EVALUATE's `WHEN` clause as its own, silently erasing the MOVE
  and merging two EVALUATEs into one, with `errors == []` and
  `warnings == []` (the missing-WHEN error that normally flags a malformed
  EVALUATE never fired, because *a* WHEN was found — just the wrong one's).
  Fixed with the same `self._is_statement_keyword()` break. Probed and
  confirmed safe: `IfStatementParser`'s condition collector (with/without
  `THEN`/`END-IF`) already stops correctly on a following verb.
* **Updated** [tests.md](tests.md) implicitly: +1 new regression file,
  `tests/regression/test_tier7_unsupported_verb_boundary.py` (9 tests
  total, including 2 for the EVALUATE finding). Full suite: 6729 passed,
  0 failed.

## 2026-07-08 (silent-drops-and-gaps audit: SORT/MERGE/ENTRY/CALL swallows, line-number drift, batch/CLI fault isolation)

* **Updated** [parser.md](parser.md): SORT/MERGE's "remaining clauses" loop
  and ENTRY's USING-clause loop now stop at `is_statement_boundary()` instead
  of an `else: consume()` fallback that swallowed a following un-punctuated
  statement (same bug class as the 2026-07-06 INSPECT/STRING/UNSTRING fix,
  but these three parsers were missed at the time). `CallStatementParser`'s
  ON EXCEPTION/NOT ON EXCEPTION/ON OVERFLOW handler-body dispatch
  (`_parse_nested_stmts`) now warns on an unsupported verb via the new
  `_warn_and_skip_handler_statement`, matching the top-level
  `_warn_unsupported_statement` behavior from the 2026-07-07 C2 fix, which
  this nested dispatch loop had never received.
* **Updated** [preprocessing.md](preprocessing.md): `normalize_fixed_format`
  and `preprocess_conditional_compilation` both used to drop certain
  physical lines from their output entirely (blank/comment lines; `>>DEFINE`/
  `>>IF`/`>>ELSE`/`>>END-IF` directive lines; lines inside a skipped `>>IF`
  block) instead of emitting an empty placeholder — silently shifting every
  later line's number in lexer/parser error and warning locations. Every
  real COBOL program has blank/comment lines, so this affected essentially
  all diagnostics past the first one, not just an edge case. Fixed in both
  the pure-Python implementation and the Cython `_preprocess_fast.pyx`
  mirror (checked-in `.c` regenerated).
* **Updated** [lexer.md](lexer.md): `_lexer_fast.pyx`'s `is_line_start_quote`
  check used `str.strip()` (broad whitespace definition) where the
  pure-Python lexer used an explicit `" \t"`-only loop — a stray control
  byte before an unterminated quote could make the compiled build classify
  a VALUE-clause-continuation candidate differently from the fallback path.
  Aligned to the narrower pure-Python check.
* **Produced** [batch.md](batch.md): new OKF concept file (was referenced by
  `scripts/okf_staleness_check.py`'s `OKF_MAP` but never created). Documents
  `parse_files`/`parse_files_with_copybooks` and their per-file fault
  isolation, including two gaps fixed today:
  `parse_files_with_copybooks` had no exception guard around
  `parser.parse(...)` (one poisoned file could abort the whole batch,
  discarding every other file's result — the 2026-07-07 C8 fix only
  reached `parse_files`'s workers) and only caught `OSError` (not
  `ValueError`/`UnicodeDecodeError` under `errors="strict"`) on file reads.
* **Updated** [analysis.md](analysis.md): `IOCoverageReporter.load_pytest_results`
  now raises `ValueError` for a non-dict JSON root instead of an uncaught
  `AttributeError` from the unconditional `data.get("tests", [])` that
  followed.
* **Updated** [cli.md](cli.md): `coverage generate` now catches
  `json.JSONDecodeError`/`ValueError` from the reporter (the same M10 bug
  class already fixed for `coverage status`, but missed here);
  `generate-tests -o` write failures now go through the standard
  `_fail(...)` path instead of an uncaught traceback (it was the one
  output-writing subcommand that bypassed the shared `_text_out()` helper).
* **Updated** [tests.md](tests.md): test count refreshed to ~6,725 tests
  across 241 files (two new regression files:
  `test_tier5_silent_drip_audit.py`, `test_normalize_line_number_preservation.py`).
* Full audit: `reports/audit-2026-07-08.md`.

## 2026-07-07 (mockymock corpus-sweep fixes: SUBTRACT GIVING, DISPLAY subscript, WRITE FROM literal)

* **Updated** [parser.md](parser.md): fixed three content-drop bugs found
  by re-running mocky-mock's corpus sweep (`scripts/corpus_sweep.py`)
  against `legacy-application` now that the EVALUATE blank-selector fix
  (below) is on `main` — all 26 corpus/fixture/example programs now parse
  and `mockymock generate` cleanly with zero refusals (previously 3
  programs carried a `PARSE_WARNING`: `ACCTMNT.cbl`, `GLRECON.cbl`,
  `LOANPMT.cbl`). `SubtractStatementParser`'s `FROM` branch now checks for
  a trailing `GIVING` (mirroring `AddStatementParser`'s `TO` branch), so
  `SUBTRACT a FROM b GIVING c` no longer drops `c`.
  `_utils.consume_keyword_and_operand` now skips leading `NEWLINE` tokens
  before checking for its keyword, not just after, so a clause keyword on
  its own continuation line is no longer missed (this was the actual
  trigger in `LOANPMT.cbl` — `GIVING` on the line after `FROM`).
  `DisplayStatementParser` now folds a following `(subscript)` into the
  preceding identifier as one item instead of aborting the item list on
  the bare `LEFT_PAREN` (`ACCTMNT.cbl`'s `DISPLAY ... SQLERRD(3)`).
  `WriteStatementParser`'s `FROM` clause now also accepts a string literal
  source, not just an identifier (`GLRECON.cbl`'s `WRITE rec FROM
  'literal text'`).
* **Updated** [tests.md](tests.md): test count refreshed to ~6,709 tests
  across 239 files (new `tests/unit/test_display_parser.py`).
* **Addressed PR #80 review comments:** `_consume_subscript` now preserves
  nested parens literally (`TAB(FUNCTION MOD(3 2))` no longer flattens to
  `TAB(FUNCTION MOD 3 2)`) instead of only tracking paren depth without
  recording the parens; `consume_keyword_and_operand` now calls
  `skip_whitespace` (covers `WHITESPACE`/`COMMENT`/`CONTINUATION` too, not
  just `NEWLINE`) so a fixed-format continuation token before an optional
  clause keyword can't hide it, even though `normalize_fixed_format`
  already merges continuation lines before today's standard entry point
  reaches the lexer.

## 2026-07-07 (audit HIGH/MEDIUM remediation: H1, H2, H4, H5, H6a/c, H7, M5, M8, M10)

* **Updated** [parser.md](parser.md): `_parse_size_error_stmts` now
  dispatches ON SIZE ERROR / NOT ON SIZE ERROR bodies through the statement
  registry — every verb is captured, not just DISPLAY/MOVE (H1).
  `perform_parser.py` parses `PERFORM VARYING ... AFTER ...` dimensions
  into `PerformStatement.after_clauses` (H2). ENVIRONMENT division SELECT
  parsing captures ALTERNATE RECORD KEY / PADDING / RESERVE / SHARING /
  LOCK MODE / PASSWORD / RECORD DELIMITER / second FILE STATUS variable,
  populates `assign_device_type`, and warns on unknown SELECT clause
  tokens (H5). `DECIMAL-POINT IS COMMA` warns that it is not honored (H4).
  `BaseDivisionParser` gained a `host` attribute so all division parsers
  can reach `add_warning`/`add_error`.
* **Updated** [ast-models.md](ast-models.md):
  `PerformStatement.after_clauses` (+ `add_after_clause`, serialized when
  non-empty); `CobolExpression.to_dict()` now includes `operands`.
* **Updated** [preprocessing.md](preprocessing.md): the COPY statement
  lexer records warnings for COPY statements it recognizes but drops
  (missing terminating period → never expanded, H6a; unterminated
  `==pseudo-text==`, H6c) and gained a left-side word-boundary check;
  `extract_copy_statements(..., warnings=)` and
  `preprocess_conditional_compilation(..., warnings=)` surface diagnostics
  (unknown `>>IF` conditions, stray `>>ELSE`/`>>END-IF`, malformed
  `>>DEFINE`, unclosed `>>IF`, unknown `>>` directives — H7) into
  `ExpansionStatistics.warnings` / `ParseResult.warnings`.
* **Updated** [cli.md](cli.md): `--define` conditional-compilation warnings
  print to stderr; `coverage status` reports malformed artifact JSON with
  exit 1 instead of a traceback (M10).
* Regression suite: `tests/regression/test_tier4_audit_remediations.py`
  (29 tests). `interface-contract.md` documents real `success`/`ast`
  semantics (M8); `MemoryConfiguration` docstring flags its no-op fields
  (M5).

## 2026-07-07 (audit critical silent-drop fixes: C1–C8, H3, H6)

* **Updated** [parser.md](parser.md): multi-program compilation units are now
  parsed — `parse_program()` consumes `END PROGRAM [name] [.]` and starts a
  new `CobolProgram` at each subsequent IDENTIFICATION DIVISION, attaching
  extras to `ast.contained_programs` with a summary warning (C1). Unknown
  verbs (no registered statement parser) now emit a `ParseResult.warnings`
  entry instead of a silent `logger.debug` skip
  (`procedure.py:_warn_unsupported_statement`, C2). New
  `xml_json_parser.py` handles XML/JSON GENERATE/PARSE (C3) — previously
  mis-parsed as Report Writer GENERATE. `STATEMENT_KEYWORDS` gained
  ALLOCATE/EXHIBIT/FREE/INVOKE/JSON/XML.
* **Updated** [ast-models.md](ast-models.md): `CobolProgram.contained_programs`;
  `condition_names` (level-88) on `CobolDataItem.to_dict()` and
  `renames_items` (level-66) on `CobolSection.to_dict()` (C5);
  `CallStatement.to_dict()` includes `not_on_exception` and handler
  statements are AST children so `find_all_by_type()` sees them (C6);
  `GoStatement.target_paragraphs` keeps all computed-GO-TO targets plus the
  DEPENDING ON variable (C4); new `XmlJsonStatement` node;
  `IOWriteStatement.advancing_clause` populated by the WRITE parser (H3).
* **Updated** [cli.md](cli.md): `parse` exits 2 on a recovered-but-errored
  parse, `batch` exits 2 when any file failed, analyzer subcommands warn on
  stderr when analyzing a partial AST (C7). Batch workers contain
  parse-time exceptions as per-file `read_error` instead of aborting the
  pool (C8).
* **Updated** [preprocessing.md](preprocessing.md):
  `parse_cobol_with_expansion` propagates `expansion.statistics.warnings`
  onto `ParseResult.warnings` (H6).
* Pinned by `tests/regression/test_tier3_silent_drop_fixes.py` (31 tests).
  Full audit: `reports/audit-2026-07-07.md`.

## 2026-07-06 (fixed-format numeric-literal continuation mangled)

* **Updated** [preprocessing.md](preprocessing.md): documented that
  `normalize_fixed_format` joins non-literal continuation lines (indicator
  `-` in column 7) with **no** intervening space, per the COBOL rule that a
  continuation line's first non-blank character is the successor of the
  continued line's last non-blank character. The `else` branch (taken when
  no alphanumeric literal is open) previously did `" " + text_slice.lstrip()`,
  injecting a space before every chunk. A numeric literal split one character
  per continuation line — NIST `NC205A.CBL` writes `-999.777` and `45678`
  this way — normalised to `- 9  9  9  .  7  7  7`: spaced digits plus a
  free-standing `.` that the free-form lexer read as a statement terminator,
  truncating the `MOVE` source and dropping the `TO CONT-B` target. The AST
  silently lost the whole `MOVE -999.777 TO CONT-B` while `result.success`
  stayed `True` (no error surfaced). Changed both branches to
  `text_slice.strip()` (no leading space, both ends trimmed) in the
  pure-Python `preprocess/__init__.py` **and** the Cython
  `_preprocess_fast.pyx` (checked-in `.c` regenerated via
  `setup.py build_ext --inplace`). Alphanumeric literals split with `-` were
  already correct via the open-quote (`pending_literal`) path. The
  pure-Python impl is now reachable as
  `cobolparser.preprocess._normalize_fixed_format_pure` (mirrors
  `lexer._CobolLexerPure`) so both paths can be tested. This resolves the
  `NC205A.CBL` strict-xfail `KNOWN_ISSUES` entry that the same-day H3 MOVE
  fix (below) had just added — NC205A now parses error-free, so its entry is
  removed from `tests/integration/test_nist_cobol85_support.py`
  (`SM206A`/`SM208A`, distinct `COPY REPLACING`/`REPLACE` gaps, remain).
  Pinned by `tests/regression/test_continued_literal_normalization.py`.

## 2026-07-06 (INSPECT/STRING/UNSTRING swallow + EXEC missing-END-EXEC — audit H2)

* **Updated** [parser.md](parser.md): closed the last four rows of audit
  2026-07-06 H2's "swallow the following statement" class.
  - Added a shared `is_statement_boundary(token)` predicate in
    `parsers/statements/_utils.py` (unions `STATEMENT_TOKEN_TYPES` /
    `STATEMENT_KEYWORDS` / `SCOPE_TERMINATORS` / `CONTROL_FLOW_BOUNDARIES`)
    so INSPECT/STRING/UNSTRING share one boundary check instead of the
    per-parser inline copies MOVE/arithmetic use.
  - `InspectStatementParser`'s trailing "consume to period" loop and the
    `StringStatementParser`/`UnstringStatementParser` main-loop
    `else: consume()` fall-throughs now `break` on that predicate, so an
    un-punctuated INSPECT/STRING/UNSTRING immediately followed by another
    statement (or an enclosing `END-IF`/`ELSE`) no longer devours it up to
    the next period. Behavior stays `errors=0` (a legal COBOL sentence may
    hold several statements without separating periods).
  - EXEC SQL/CICS/IMS is intentionally left off that predicate: embedded
    SQL/CICS text legitimately contains COBOL keywords (SET/DELETE/UPDATE/
    CALL/OPEN/CLOSE), so a content boundary would truncate valid SQL. The
    mandatory `END-EXEC` is the only safe delimiter, so
    `collect_exec_sql_text` now detects a missing `END-EXEC` (stream
    exhausted first) and records a non-fatal "Unterminated EXEC block"
    parse error via the stream's parse context — turning the previous
    silent "consume the rest of the program with `errors=0`" into a
    reported error (`result.success == False`). Well-formed blocks and the
    NIST/shamrice/sample corpora (all `END-EXEC`-terminated) are unaffected.
  - Pinned by four new classes in
    `tests/regression/test_tier2_silent_drop_regressions.py`
    (`TestInspectDoesNotSwallowFollowingStatement`,
    `TestStringDoesNotSwallowFollowingStatement`,
    `TestUnstringDoesNotSwallowFollowingStatement`,
    `TestExecMissingEndExecReportsError`). Full suite: 6579 passed.
  - Still-open H2 row: MOVE *source* path (`MOVE A` with no `TO`) — not part
    of this change.

## 2026-07-06 (H5 — unterminated literal no longer aborts the whole parse)

* **Updated** [preprocessing.md](preprocessing.md): documented that
  `normalize_fixed_format(..., merge_continued_literals=False)` is a
  non-raising best-effort fallback and how the parser uses it for recovery.
  Audit finding H5 (`reports/audit-2026-07-06.md`): a single unterminated
  string literal at EOF made `normalize_fixed_format` raise `ValueError`,
  which — called unconditionally before error recovery was active — collapsed
  the whole parse to `ast=None` even under `ErrorRecoveryMode.COLLECT_ALL`.
  Two entry points were affected: `CobolParser._parse_core` (the raise fell
  through to the generic `except Exception` safety net) and the `parse_cobol`
  convenience function (which caught the raise but returned `ast=None`
  regardless of mode, despite a comment claiming graceful COLLECT_ALL
  handling). Fixed by making `_parse_core` the single owner of
  normalize-and-recover: it records the unterminated-literal error and, unless
  `FAIL_FAST`, re-normalizes with `merge_continued_literals=False` (which the
  lexer already tokenizes permissively) so a partial AST survives. `parse_cobol`
  now defers to the parser on the raise instead of returning early — which also
  sidesteps a latent bug where injecting into the result would crash on the
  `(ParseResult, ProfilingResult)` tuple returned when `enable_profiling=True`.
  The direct-call contract (`normalize_fixed_format` still raises by default) is
  unchanged. Pinned by
  `tests/unit/test_critical_fixes.py::TestUnterminatedLiteralDoesNotAbortParse`
  (COLLECT_ALL via both `parse_cobol` and `CobolParser.parse`; FAIL_FAST still
  aborts). No `.pyx`/`.c` change was needed — both paths already accept
  `merge_continued_literals`.

## 2026-07-06 (MOVE silently accepted malformed input — audit H3)

* **Updated** [parser.md](parser.md): the MOVE parser accepted incomplete
  input and produced a plausible-but-wrong node with `errors == 0` — `MOVE A
  TO.` gave a `MoveStatement` with `targets: []`; `MOVE A` (no `TO`) and a
  stream truncated at `MOVE A TO` were also accepted (audit finding H3).
  `MoveStatementParser.parse` now pulls the active `ParseContext` via
  `_utils.get_parse_context` and calls `report_parse_error` (the same
  record-and-continue path GO/CALL use) when `TO` is missing or when zero
  receiving fields follow `TO` (`target_count == 0`). Well-formed MOVEs stay
  clean, including multi-target, subscripted targets, literals, figurative
  constants, and `MOVE CORRESPONDING`. A missing **source** (`MOVE TO X`) is
  intentionally not flagged — indistinguishable from stray `*>`-comment /
  `REPLACE` pseudo-text the preprocessor does not strip; an earlier
  missing-source check faulted a valid shamrice program. Pinned by
  `tests/unit/test_move_malformed_diagnostics.py`. The stricter check exposed
  three NIST programs previously passing the error-free guarantee *only* via
  this silent acceptance, now strict-xfail `KNOWN_ISSUES`: `SM206A` /`SM208A`
  (`COPY REPLACING` / `REPLACE` pseudo-text substitution not implemented) and
  `NC205A` (continuation-line handling shatters the split literal `-999.777`
  — a preprocessing defect, filed separately).

## 2026-07-06 (COMPUTE swallowing a following statement)

* **Updated** [parser.md](parser.md): the prior same-day fix (below)
  explicitly covered MOVE/SUBTRACT/MULTIPLY/DIVIDE but not COMPUTE.
  `ComputeStatementParser.parse()`'s expression-token-collection loop is a
  standalone inline loop (not `parse_arithmetic_operands()`), so it never
  inherited the boundary check: at `paren_depth == 0` it only stopped at a
  `PERIOD` or a value in `("ON", "NOT", "END-COMPUTE")`, with no check
  against `STATEMENT_KEYWORDS`/`CONTROL_FLOW_BOUNDARIES`. A `COMPUTE` with
  no trailing period, immediately followed by another statement (e.g. a
  multi-line `CALL ... USING`), had that statement's tokens silently
  appended to the COMPUTE expression string — the following statement
  vanished from the AST with `result.success == True` and no error
  reported. Found via a real DEPTMQP program (mockymock e2e work):
  `COMPUTE MQ-OPEN-OPTIONS = ...` directly followed by `CALL 'MQOPEN'
  USING ...`, which blocked all DEPTMQP/DEPTMQC testcases since mockymock
  rejects a whole compiled test file if any one testcase's MOCK doesn't
  match a boundary. Fixed by adding a `STATEMENT_KEYWORDS`/
  `CONTROL_FLOW_BOUNDARIES`/`SCOPE_TERMINATORS` check to the expression
  loop. The `SCOPE_TERMINATORS` half of that check fixes a second,
  distinct trigger of the same gap: a COMPUTE nested inside a clause body
  (e.g. `READ ... AT END COMPUTE X = Y + 1 END-READ`) with no trailing
  period before the *enclosing* scope terminator had that terminator
  folded into the expression string instead of ending the clause —
  `STATEMENT_KEYWORDS`/`CONTROL_FLOW_BOUNDARIES` alone don't cover
  `END-READ`/`END-CALL`/etc. Pinned by
  `tests/regression/test_tier2_silent_drop_regressions.py::TestComputeDoesNotSwallowFollowingCall`
  and `::TestComputeDoesNotSwallowEnclosingScopeTerminator`.

## 2026-07-06 (MOVE/SUBTRACT/MULTIPLY/DIVIDE swallowing a following statement)

* **Updated** [parser.md](parser.md): `MoveStatementParser`'s target loop
  now stops on the shared `STATEMENT_TOKEN_TYPES`/`STATEMENT_KEYWORDS`
  (`_utils.py`) instead of a hand-rolled list missing `EXEC`/`EXECUTE`;
  `SubtractStatementParser` and the shared MULTIPLY/DIVIDE helper now call
  `parse_size_error_clauses` instead of the deleted `skip_to_period()`.
  Also fixed two more bugs this exposed in `_parse_size_error_stmts`: its
  DISPLAY mini-parser didn't stop at `NOT ON SIZE ERROR` or other
  boundaries (also fixed a latent `DISPLAY 'ADD'`-style truncation), and its
  outer dispatch loop's fallback branch unconditionally consumed tokens
  instead of stopping at `NOT`/scope-terminators, so a `NOT ON SIZE ERROR`
  clause was merged into the preceding `ON SIZE ERROR` clause instead of
  populating `not_on_size_error`. Also added `TokenType.FIGURATIVE_CONSTANT`
  to
  `ARITHMETIC_OPERAND_TOKEN_TYPES` (a pre-existing, previously-unreached gap
  the fix surfaced via `tests/samples/arithmetic_operations.cbl`'s
  `DIVIDE ... BY ZERO`). Previously, a MOVE/SUBTRACT/MULTIPLY/DIVIDE
  statement with no trailing period, immediately followed by another
  statement (most notably `EXEC SQL`), silently swallowed that statement's
  leading tokens — `result.success` stayed `True` with zero errors reported.
  Found via a real ACCTMNT.cbl banking program (mockymock e2e work): two
  EXEC SQL blocks vanished from the AST. The same class also hit a `CALL
  'CBLTDLI' USING DLI-REPL` in an IMS sample's `ELSE` branch, previously
  misattributed to "ELSE branches aren't traversed" —
  `tests/unit/test_ims_segment_analyzer.py::TestRealWorldBankingAccounts`
  updated (4 → 5 expected calls, new `test_repl_detected_in_else_branch`).
  Pinned by `tests/regression/test_tier2_silent_drop_regressions.py`
  (Group 6).

## 2026-07-05 (IO clause bodies parsed into the AST)

* **Updated** [parser.md](parser.md): documented the new "IO clause bodies"
  behaviour — `collect_clause_stmts` in
  `cobolparser/parsers/statements/_utils.py` now parses the statements
  inside `AT END` / `NOT AT END` / `INVALID KEY` / `NOT INVALID KEY` clause
  bodies via the statement registry instead of discarding the tokens and
  returning `[]`. Clause statements land on the IO node's clause lists and
  as AST children (traversal + serialization). WRITE gained INVALID KEY
  parsing; START now matches comparison keywords by value and consumes the
  KEY data-name; MOVE/DISPLAY/CALL-USING operand loops stop at scope
  terminators. Pinned by `tests/unit/io_statements/test_clause_bodies.py`.

## 2026-07-05 (CALL handler-body termination)

* **Updated** [parser.md](parser.md): documented how
  `CallStatementParser._parse_nested_stmts` terminates ON EXCEPTION /
  NOT ON EXCEPTION / ON OVERFLOW bodies — boundary values (`NOT`,
  `END-CALL`), an inter-statement period, and a post-nested-parse
  `previous_meaningful_token` PERIOD check (a nested statement may consume
  the sentence period itself). `_parse_using_clause` stops at
  `SCOPE_TERMINATORS` so `END-CALL` is not captured as a USING parameter.
  Previously the handler body swallowed following top-level statements
  (`STOP RUN` after `END-CALL.` ended up inside `on_exception`) —
  mockymock then refused to mock them as nested-in-boundary. Pinned by
  `tests/regression/test_call_handler_body_termination.py`.

## 2026-07-05 (program_flow typing fix)

* No concept change needed: `ProgramFlowAnalyzer`'s inner `scan()` helper
  in `analysis/program_flow.py` swapped its mypy-invalid
  `source_id: str = proc_name` default for `str | None = None` with an
  in-body `proc_name` fallback — behaviorally identical, `mypy
  cobolparser/` now clean. [analysis.md](analysis.md) documents behavior,
  not this internal signature, so only this log entry records it.

## 2026-07-05 (multi-mode OPEN file capture)

* **Updated** [parser.md](parser.md): `open_parser.py` now consumes
  subsequent mode keywords (`OPEN INPUT A OUTPUT B EXTEND C`) instead of
  breaking at them, so `IOOpenStatement.file_names` captures the files of
  every mode group; `open_mode` still reports only the first group's mode.
  Previously every file after the second mode keyword was silently dropped
  — mockymock's OPEN-site mock matching (which keys on `file_names`) was
  the motivating consumer. Pinned by
  `tests/unit/io_statements/test_open_read_parsers.py` (multi-mode-group
  tests).

## 2026-07-04 (copybook path on-disk casing)

* **Updated** [preprocessing.md](preprocessing.md): `find_copybook_file()`
  now canonicalises the found file's basename to the on-disk casing via
  `os.scandir` (helper `_on_disk_casing` in `preprocess/path_resolver.py`).
  Previously, on case-insensitive filesystems (Windows/macOS), the
  extension probe order (`.cpy` before `.CPY`) leaked probe-cased paths
  (`MEM.cpy` for an on-disk `MEM.CPY`) into
  `CopybookExpansion.included_copybooks` and warnings. The tier-2
  `PathResolver` directory index already used scandir entry names and was
  unaffected. Pinned by
  `tests/unit/test_path_resolver_gaps.py::TestOnDiskCasing`; the SM207A
  regression tests dropped their `os.path.normcase` tolerance and compare
  paths exactly.

## 2026-07-04 (numeric VALUE clause fix)

* **Updated** [parser.md](parser.md): documented the LEVEL_NUMBER-as-literal
  gotcha in `parsers/divisions/data.py`. `_parse_value_clause` and the
  level-88 value collector now accept `LEVEL_NUMBER` tokens as numeric
  literals, consume an optional `IS`, and handle `MINUS`/`PLUS` sign tokens
  — previously `VALUE 5`, `VALUE 42`, `VALUE IS <n>`, `VALUE -5`, and
  `88 ... VALUE 1` all silently lost the literal and could spawn bogus
  anonymous data items. Motivated by mockymock's working-storage reset,
  which restores items to their declared VALUE clause. Regression suite:
  `tests/regression/test_numeric_value_clause.py`.

## 2026-07-04 (later)

* **NIST known-issues burn-down** (parser/lexer/preprocess fixes; corpus
  now 457/459 error-free, and both SM101A and SM207A parse clean with
  copybook expansion):
  - `parsers/divisions/base.py`: new shared `at_division_boundary()` —
    composite header tokens always match; bare keywords only when the next
    significant token is `DIVISION`. `BaseDivisionParser.parse` now skips
    newlines inside split headers.
  - `parsers/divisions/identification.py`: comment-entries containing bare
    division keywords (OBNC1M's `AUTOMATIC DATA AND ...`) no longer end the
    division; uses `at_division_boundary()`.
  - `parsers/divisions/data.py`: section scanner stops at split division
    headers (NC113M's three-line `PROCEDURE / DIVISION / .`) instead of
    consuming them as noise.
  - `parsers/statements/arithmetic_parsers.py`: COMPUTE accepts
    `{identifier [ROUNDED]}...` receiver lists incl. subscripts (NC252A).
  - `lexer.py` + `_lexer_fast.pyx` (`.c` regenerated, Cython 3.2.4):
    trailing period after a numeric literal is a sentence terminator, not a
    decimal point, unless followed by a digit.
  - `preprocess/__init__.py` `validate_copybook_content`: continued string
    literals (column-7 `-` re-opening quote) no longer flagged unbalanced.
  - `preprocess/path_resolver.py`: `COPY member OF library` falls back to
    the plain search path when no `<dir>/<library>/` subdirectory exists.
  - Tests: `tests/regression/test_nist_edge_case_fixes.py` (minimal repros);
    `KNOWN_ISSUES` in `test_nist_cobol85_support.py` shrunk to OBNC1M
    (Area A/B phony-program, architectural) + SM101A (expansion by design);
    `KNOWN_COPYBOOK_ISSUES` now empty; new SM207A expansion test.

## 2026-07-04

* **Updated** [tests.md](tests.md): added
  `tests/integration/test_nist_cobol85_support.py` to the layout and the
  Example Corpora table. The NIST COBOL-85 corpus (459 `.CBL` + 51 `.CPY`)
  is now strictly pinned: every program must parse error-free under
  COLLECT_ALL; the 4 programs the parser cannot yet handle (`NC113M`,
  `OBNC1M`, `NC252A`, `SM101A`) are strict-xfail `KNOWN_ISSUES` entries so
  the list only ever shrinks. `SM101A` additionally must parse clean with
  copybook expansion, and all `.CPY` files must pass
  `validate_copybook_content` (2 strict-xfail validator limitations).

## 2026-07-03

* **Updated** [ast-models.md](ast-models.md): `find_all_by_type()` /
  `find_first_by_type()` now also match a node's concrete class name
  (`"MoveStatement"`, `"CallStatement"`, `"ExecSQLStatement"`, ...), not just
  the `node_type` attribute. All statement subclasses share the generic
  `node_type` `"Statement"`, so class-name matching is what lets the CLI
  `analyze` subcommand list CALL statements and `--find-type` select specific
  statement kinds (previously both silently returned nothing for statement
  class names). Source: `cobolparser/models/ast_base.py` (`_matches_type`).
* **Updated** [cli.md](cli.md) for the output-identification change: every
  CLI output is now self-describing. Added an "Output Identification" section
  (JSON documents lead with `source_file` + `program_id`; `tokenize` output
  wrapped as `{"source_file", "tokens"}`; `parse` path/`--find-type`
  extraction wrapped as `{"source_file", "program_id", "path"/"node_type",
  "result"/"matches"}`; batch entries carry `program_id`; Mermaid flowcharts
  gained a `%% Program: <name>` header) and corrected the Tokenize
  subcommand's documented output shape. Source: `cobolparser/cli/parse.py`
  (`_identification`, `_emit_report`), `cobolparser/generators/flowchart.py`;
  contract pinned by `tests/unit/cli/test_output_identification.py`.

## 2026-06-30

* **Logged untracked drift from commit `cad4db6` (2026-06-29, "Add integration
  contract documentation for backend API")**: that commit added
  [integration.md](integration.md) and updated [lexer.md](lexer.md) and
  [index.md](index.md), but never got a log.md entry. Backfilling it now:
  - **Produced** [integration.md](integration.md): documents the backend
    adapter contract (`backend/src/parsers/cobol/parser.py`) — entry points
    (`CobolParser(...).parse()`, optional `DynamicCallAnalyzer`/
    `ProgramFlowAnalyzer` analyzers, `CobolParseError`), `ParseResult`/
    `CobolProgram` attribute contract, the `program_structure` output dict
    shape, the `dependencies.*` → Neo4j relationship mapping
    (`CALLS`/`COPYBOOK`/`USES_DB2`/`USES_CICS`/`USES_MQ`), the backend's
    `ParserResult` dataclass, and handled file extensions. Defers to the
    canonical `interface-contract.md` (repo root) via the `resource:`
    frontmatter field for full detail (e.g. copybook-specific
    `is_copybook`/`source_kind`/`copybook_name` fields and the
    `VALIDATION_FAILED`/`PERMISSION_ERROR` error-message prefixes are in the
    canonical doc but intentionally summarized out of the OKF concept).
  - **Updated** [lexer.md](lexer.md) Cython Acceleration section: replaced the
    bare 3-module table with one that lists the actual pure-Python file each
    `.pyx` overrides and the specific accelerated symbols (confirmed against
    `cobolparser/_lexer_fast.pyx`: `check_division_header`,
    `read_word_from_text`, `tokenize_program_text`, `_try_single_line_string`,
    `read_number_from_text`, `tokenize`; `_preprocess_fast.pyx`:
    `normalize_fixed_format`; `_data_fast.pyx`:
    `parse_picture_clause_fast`, `parse_data_item_clauses_fast`). Added the
    guarded `try/except ImportError` activation pattern, the `~3x` throughput
    figure (from `setup.py`), and the `pip install -e ".[fast]"` extra
    (`pyproject.toml`).
  - **Updated** [index.md](index.md): added the "Integration" section linking
    to integration.md.
  - Corrected `timestamp` on lexer.md and integration.md from `2026-06-28` to
    `2026-06-29` to match the commit that actually authored their current
    content.
* **Fixed pre-existing gaps in [cli.md](cli.md)** found while verifying
  concept files against current source (none of these came from a dated
  commit since the last log entry — they predate the OKF bundle itself,
  ranging from 2026-04-17 to 2026-05-06):
  - `analyze` subcommand was documented as running "all static analyzers"
    (dead code, IO, MOVE-type, linkage, LE); it actually only runs
    `DynamicCallAnalyzer` and reports dynamic `CALL` target info
    (`called_program`/`is_dynamic`/`possible_values`) — corrected.
  - `program-flow` was missing its `--format json|mermaid|dot` flag (added in
    commit `842f246`, wired to `generators/flowchart.py`'s
    `MermaidFlowchartGenerator`/`DotFlowchartGenerator`).
  - `parse`, `batch`, `program-flow`, `analyze`, and `dead-code` were missing
    the shared `--profile`/`--profile-top-n`/`--profile-output` flags (added
    in commit `5f2468c`/`13a3f1f`).
  - `batch` was missing `--glob` (repeatable), `--workers`, and `--encoding`.
  - `tokenize` output shape was missing the `column` field.
  Bumped cli.md `timestamp` to 2026-06-30.

## 2026-06-28

* **Initialization**: Created OKF bundle for cobolparser v1.1.0.
  Concepts produced: [lexer](lexer.md), [parser](parser.md),
  [preprocessing](preprocessing.md), [ast-models](ast-models.md),
  [analysis](analysis.md), [cli](cli.md), [tests](tests.md).

