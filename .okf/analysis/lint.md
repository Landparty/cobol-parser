---
type: Module
title: Lint Analyzer
description: LintAnalyzer (analysis/lint.py) -- runs nine analyzers and seven bug-pattern rules (bug_patterns.py) over one parse plus the line-length source rule and the call-check cross-program rule and flattens them into one severity-graded LintFinding stream; per-unit linting, caveats and failed rules, and the source-map origin stamping (apply_source_map, stamp_report_origins, fixed_format_column_offset) shared by every analyzer CLI.
tags: [analysis, lint, findings, severity, source-map, origin]
timestamp: 2026-10-15T00:00:00Z
---

# Lint Analyzer

`cobolparser/analysis/lint.py` is the aggregate view: one call runs the
selected analyzer rules over every program unit of a parsed file and returns a
single, source-ordered list of `LintFinding`s, plus what could not be checked.
It re-implements no analysis -- each rule maps an existing report (the
analyzers themselves are in [flow.md](flow.md), [data-use.md](data-use.md) and
[sql-cics-ims.md](sql-cics-ims.md)). The same module owns the source-map
helpers that stamp each finding (and every analyzer CLI's JSON report) with the
file, line and column it really came from after copybook expansion. Entry
point: `LintAnalyzer(rules=None).analyze(ast)`; CLI `cobol-parser lint`.

## API and rules

```python
report: LintReport = LintAnalyzer().analyze(ast, flow_report=None, copybook_item_names=None)
# LintAnalyzer(rules=None) -- default every rule in RULES; an unknown id raises ValueError
# report.findings: list[LintFinding]  (rule/severity/message/location/symbol/kind)
# report.rules_run / .failed_rules / .caveats
# report.error_count / .warning_count / .info_count / .counts_by_rule() / .worst_severity()
```

The aggregate view for the two callers who want "what is wrong with this
program" rather than one analyzer's answer: a CI gate and an editor. Runs the
selected rules over **one** already-parsed AST and flattens their differently
shaped reports into a single stream of `LintFinding`, ordered by source
position. Re-implements no analysis — each rule is a thin mapping from an
existing analyzer's report, so a fix in (say) `move_type_checker.py` reaches
lint output with no change here.

**Rule ids are the analyzer subcommand names** (`dead-code`,
`unused-variables`, `move-type-check`, `io-sequence`, `linkage-check`,
`recursion-check`, `complexity`, `dclgen-check`, `sql-cics-check`; the `RULES`
tuple, in that order, followed by the seven bug-pattern rules of
[Bug-pattern rules](#bug-pattern-rules), which have no subcommand) rather
than a second private
vocabulary, so
`lint --rule dead-code` and `cobol-parser dead-code` are visibly the same
analyzer. One more id appears in output but not in `RULES`: `parse`, the
error-severity findings `add_parse_errors()` makes from `ParseResult.errors`
(the `lint` CLI adds them; see cli.md, #249). The `sql-cics-check` caveat on a
unit with no PROCEDURE DIVISION says exactly that, instead of counting the
unit's one reason as an "EXEC block" that could not be checked. A rule selection is deduplicated and normalized to `RULES` order, so
flag ordering cannot change the report.

**Severity is per finding, not per rule.** An analyzer that grades itself
keeps its grading: MOVE's ERROR/WARNING kinds map to error/warning,
recursion's HIGH/MEDIUM (HIGH = a cycle with no escape route, i.e. an infinite
loop) to error/warning, complexity's rating to warning (HIGH) / info
(MODERATE), with LOW producing no finding at all. The rest carry a fixed
severity: dead code, I/O `FILE_LEFT_OPEN` and `REWRITE_WITHOUT_READ` (#736)
warn; every other I/O kind
(including the OPEN-mode kinds `*_WRONG_MODE` and `OPEN_AFTER_LOCK`, #548) and
every LINKAGE kind but `UNREFERENCED_LINKAGE` are errors. An unused item is a
warning when the program declares it and only info when it came from a
copybook (`copybook_item_names`) — a copybook describes a whole record and no
one program uses every field of it. The `_SEVERITY_*` tables in the module are
the whole of that policy.

**`LintFinding.symbol`** is the *name* the finding is about (paragraph, data
item, file, called program), not a source excerpt. It is what lets a consumer
whose line numbers have shifted — an editor holding the unexpanded file while
the analyzers ran over copybook-expanded text — re-anchor by searching for the
declaration instead of trusting `location` blindly. `kind` preserves the
underlying analyzer's own category (`READ_BEFORE_OPEN`, `WORKING-STORAGE`,
`HIGH`, ...) so a consumer can filter more finely than by rule without parsing
`message`.

**A quiet report is not automatically a clean program**, and the report says
so structurally rather than in prose: `caveats` carries what an analyzer could
not check (MOVE operands whose data category never resolved, most often an
unresolved COPY; dclgen-check's count of host variables it could not
(fully) check -- since #530 that includes the null-indicator check of a
stored-procedure CALL argument), and `failed_rules` records a rule that raised — it costs
only its own findings, never the other rules'. A consumer gating on `findings`
alone must still surface both lists.

Two rules (`recursion-check`, `complexity`) need the CFG; `LintAnalyzer`
builds it at most once per `analyze()` call and accepts a precomputed
`flow_report`. Findings identical in every visible field collapse to one
(`_deduplicate`) — identical findings from one analyzer are two facts about
the graph but one thing to fix, and two identical squiggles in an editor.
`IOSequenceAnalyzer` reports a violation once per source location (see #371),
so it does not produce such duplicates itself.
Recursion's `LOW` (a self-CALL into an `IS RECURSIVE` program) maps to `info`
(`_SEVERITY_RECURSION`).

CLI: `cobol-parser lint <file.cbl>` (see cli.md), including `--format text`,
`--min-severity`, and `--fail-on` (exit 3).

## Bug-pattern rules

`bug_patterns.py` (`BugPatternAnalyzer(rules=None).analyze(ast, flow_report=None)`
-> `BugPatternReport.findings: list[BugFinding]`) holds seven single-program
rules for classic bugs no per-concern analyzer looks for. They are in
`RULES` (after `sql-cics-check`) and run by default. `_analyze_unit` builds
one `bug_patterns._Context` per unit for all seven, so they share one
`_DataIndex` (name -> declared items, via `collect_declared_items`), one
`XrefAnalyzer` report and lint's cached CFG. Each rule skips what it cannot
resolve (a name declared twice, a variable subscript, a reference
modification, a group, a REDEFINES-overlaid sender) rather than guess.

| Rule | `kind` | Severity | What and what not |
|---|---|---|---|
| `truncation` | `MOVE_LOSES_DIGITS` | warning | sender has more integer digits than the numeric receiver (`field_widening.Capacity.losses`); not for a sender that shares storage through REDEFINES (byte-filled, digit count meaningless) |
| | `MOVE_LOSES_CHARACTERS` | warning for a constant, info for a variable | longer sender than alphanumeric receiver. A constant (literal, or a VALUE item nothing sets) is judged by its value (`PIC X(8) VALUE 'COACTUP'` fits 7 bytes); a variable's content may fit, so info. Alphanumeric to numeric is left to `move-type-check` |
| | `ARITHMETIC_LOSES_DIGITS` | warning | ADD / SUBTRACT (TO, FROM, GIVING) or a COMPUTE of only `+`/`-`, an item operand with more integer digits than the receiver, no ON SIZE ERROR / NOT ON SIZE ERROR. Literal operands are left out (`COMPUTE X = Y - 100` fits) |
| `subscript-range` | `SUBSCRIPT_OUT_OF_RANGE` | error | all-literal subscript list, as many subscripts as OCCURS dimensions (ancestors' first), a value < 1 or > `max_times`. Scanned in every operand string a statement carries (`_statement_strings`, quoted literals blanked) |
| `next-sentence` | `NEXT_SENTENCE_IN_END_IF` | warning | the IF chain around NEXT SENTENCE is END-IF-closed (`IfStatement.ended_by_end_if`) and something follows before the period (`period_after_end_if` False and a statement after the IF in its block). A period-terminated IF is the idiom; EVALUATE / SEARCH / inline PERFORM containers are not judged |
| `perform-range` | `PERFORM_THRU_BACKWARDS` | error | THRU end before its start in `ProcedureIndex` order |
| | `GO_TO_OUT_OF_PERFORM` | warning | a GOTO / GOTO_DEPENDING CFG edge whose source is in a PERFORM / SORT / MERGE / XML range (`FlowEdge.thru_target`, a section = its paragraphs) and whose target is in none of the ranges holding the source; not when the target ends the run (STOP RUN, GOBACK, EXIT PROGRAM, CICS RETURN/XCTL/ABEND, abend CALL, directly or two PERFORM/GO TO levels down), not from DECLARATIVES |
| | `FALLS_INTO_PERFORMED` | warning | walking the main line from the first paragraph (or the unnamed statements before it): a paragraph whose last statement is not an unconditional transfer (or a PERFORM of a range that ends the run) falls into a PERFORM range start. Not when the last statement PERFORMs that very paragraph (NIST's `PERFORM X 9 TIMES` then into X); stops at the first performed paragraph |
| `file-status` | `FILE_STATUS_NOT_CHECKED` | warning | SELECT with FILE STATUS, file has a file-operation reference, and no xref reference other than `write` (or the SELECT itself) to the item, its groups, subfields, level-88s or REDEFINES. Not with DECLARATIVES, not for a LINKAGE / EXTERNAL / GLOBAL status item |
| `uninitialized` | `NUMERIC_NEVER_SET` | warning | elementary numeric WORKING-STORAGE / LOCAL-STORAGE item, no VALUE on it or a group, not EXTERNAL, read (xref `read`/`condition`/`subscript`) and nothing else: no other role on it, its groups or REDEFINES, no ADDRESS OF, not named in SPECIAL-NAMES (CRT STATUS, CURSOR), not an SQLCA field. At the first read |
| `obsolete-verb` | `ALTER` | warning | every ALTER statement |

`IfStatement.ended_by_end_if` / `period_after_end_if` are set by
`if_parser.py` and not serialized.

Measured 2026-11-06 (warnings only; info in brackets): CardDemo `app/cbl` 17
[53] -- the 3 GO TO findings include `COACTUPC` 9700 -> 9600-EXIT and the same
shape in `COCRDUPC`, `CBTRN03C`'s NEXT SENTENCE leaves its inline PERFORM
UNTIL, and 11 balance fields `S9(10)V99` moved into `S9(9)V99` screen
fields; NIST + shamrice (486 files) 786 [169], dominated by the suite's
deliberate truncation and ALTER tests.

## Cross-program rule (`call-check`)

`CALL_CHECK_RULE` (`PROGRAM_SET_RULES`; in `ALL_RULES`, not `RULES`, so
`LintAnalyzer` accepts but never runs it). `add_call_check_findings(report,
path, ast, resolver)` runs `call_interface.CalleeResolver.check_program`:
the program's CALL sites and its own contained programs' interfaces, plus
each CALL target found as a file in the resolver's callee directories
(`find_callee_file`: `NAME`, `NAME.cbl`, `name.cob`, ...; parsed once per
resolver, reduced to interfaces; one with no PROCEDURE DIVISION counts as
unparsed). Findings: rule `call-check`, `kind` the call-check kind
upper-cased (`LENGTH`, `ARGUMENT_COUNT`, ...), line of the CALL, no column
(`column_known` False), `symbol` the callee. A target with no file and a
callee that did not parse are caveats. Run it before `apply_source_map`.
The `lint` CLI runs it only with `--callee-path` (see [../cli.md](../cli.md#lint)).

## Line length (`line-length`)

The one **source rule** (`SOURCE_RULES`; `ALL_RULES = RULES + SOURCE_RULES`):
it reads the files on disk, not the AST, so `LintAnalyzer` accepts the id
(callers pass one selection list everywhere) but never runs it.
`add_line_length_findings(report, main_file, source_map, preprocess_fixed,
copybooks)` does, over the program and every copybook the parse read (the
map's files plus `expansion_copybooks`); the `lint` CLI and `scan`'s lint call
it **after** `apply_source_map`, since its findings are placed on disk
already (`origin` = file, line, column; `location` = the expanded line that
file line became, else the on-disk line). Fixed or free is judged as the
parse judged it (program: `preprocess_fixed`, else the detector; copybook:
`_looks_fixed_format`); a free-format file, or a line after `>>SOURCE FORMAT
FREE`, has no limit. `line_length_findings(path, text, free_lines)` per file:

* `LINE_PAST_COLUMN_80` at column 81: **error**, or **warning** when everything
  past column 72 is comment (comment line, or an inline `*>` outside a literal;
  `_comment_start`). The record is 80 columns on the mainframe.
* `TEXT_PAST_COLUMN_72` at column 73, **warning**: a word runs across the
  72/73 edge (both columns non-blank), so the compiler keeps a cut word.
  Judged as `normalize_fixed_format`'s own warning: not on a comment line or
  inside `*>`, not a lone `.`, not a numeric stamp filling 73-80 (or a shorter
  one under `_has_identification_stamp_convention`), and not a tail with the
  shape of the file's own stamps (`_identification_shapes`: digits `9`,
  letters `A`, seen on at least `MIN_ID_STAMP_EVIDENCE_LINES` lines whose
  column 72 is blank; NIST's `IX2094.2`).

On `examples/cobol/` + `tests/samples/` (566 programs): 0 errors, 86 warnings
(all comment lines past column 80). The CLI's multi-file run reports each
`line-length` finding once per run (`_drop_repeated_layout_findings`): a
copybook COPYed by many programs is one fix.

## Program units

**Every program unit is linted, not just the outermost.** A source file can
hold several `PROGRAM-ID`s (stacked, or nested inside the enclosing program's
PROCEDURE DIVISION); the parse returns the outermost with the rest on
`CobolProgram.contained_programs`. Every rule is program-scoped, so running
them on the outer program alone would leave a contained program *entirely
unexamined* while the report read as clean. `analyze()` iterates
`ast.program_units()` and merges: `_analyze_unit` runs the rule set over one
unit into a shared `LintReport`, `rules_run` and `failed_rules` carry one
entry per rule however many units it ran on (the reader needs to know the
concern went unexamined, not the arithmetic), caveats are deduplicated, and
the sort + dedup happen once at the end. A caller-supplied `flow_report`
describes the outermost unit only; the others build their own. Passing a
contained unit directly lints just that unit, which is what the CLI's
`--program` does. `LinkageChecker.collect_scope_interfaces` runs once per file
and is handed to every unit's `linkage-check` (see [data-use.md](data-use.md)).
Pinned by `tests/regression/test_nested_program_units.py`.

## Finding origins

**A finding says where it really is.** `LintFinding.origin_file` /
`origin_line` are serialized as `"origin": {"file", "line"}` and emitted only
when BOTH are known (a half-filled `{"file": null, "line": 12}` would read as
an answer to a consumer checking for the key). `apply_source_map(report,
source_map)` fills them from `ParseResult.expansion_source_map` (see
[../preprocessing.md](../preprocessing.md)): analyzer locations count lines in
the copybook-*expanded* text, so a finding after an expanded `COPY` is nowhere
near that line on disk and one *inside* an inlined member is not in that file
at all. A `None` map (nothing expanded) and a line the map does not cover both
leave the finding untouched rather than claiming a line nobody vouched for.
The `lint` CLI applies it whenever `--copybook-path` was given, and its `text`
format prints the origin's own `file:line:column:` prefix so the output stays
clickable after expansion. Pinned by
`tests/regression/test_expansion_source_map_and_comments.py::TestApplySourceMap`.

`stamp_report_origins(report_dict, source_map)` is its twin for a serialized
analyzer report: every `"location": {"line": N}` mapping gains a sibling
`"origin"`; xref's `"definition"` gains `"definition_origin"` and
program-flow's `"exit_statement_location"` gains `"exit_statement_origin"`
(`_ORIGIN_KEYS`, see #367). Used by `scan_one` and every analyzer CLI's
`_emit_report`. Field-lineage edges carry a bare `line`, so it does not reach
them; `field_lineage.apply_source_map` stamps those (see
[lineage.md](lineage.md)).

**And at which column** (see #301). `LintFinding.origin_column`, serialized as
`origin.column` only when known, is the column an editor shows.
`apply_source_map(report, source_map, column_offset)` takes a `(file, line) ->
int | None` and adds its answer to `location.column`;
`fixed_format_column_offset()` holds the per-layout table (7 for a
fixed-format line, whose columns 1-7 never reach the analyzers; 0 for a
free-form member in a fixed listing; 6 for a fixed-format member in a
free-form listing). `source_column_offsets(main_file, preprocess_fixed)`
builds that function for one parse -- judging the program the way
`CobolParser` does and each copybook the way the expander did, and leaving a
line after `>>SOURCE FORMAT FREE` unshifted; each file is read through
`read_program_source`, in the encoding the parse detected (an EBCDIC file
read as UTF-8 has no lines to judge) -- and is what both the `lint`
CLI and the MCP server (`cobolparser/mcp/`) pass. `LintFinding.column_known` (not serialized) is False for a
parse error that gave only a line; such a finding gets no `origin_column`.
`stamp_report_origins` leaves an existing `origin` alone so the CLI's dict
pass does not erase it. Detail in [../cli.md](../cli.md).

## SARIF output

`sarif.py` turns the findings-shaped reports into one SARIF 2.1.0 log (one
run): `lint --format sarif`, `scan --format sarif` and `call-check --format
sarif`. `lint_results(report_dict, source_file)` reads a
`LintReport.to_dict()` (so it serves `scan`'s per-file dicts as well as the
CLI's report): a finding's `origin` wins over its `location`, so a finding
inside an expanded copybook points at the copybook and its on-disk column;
without `origin`, the source file and the bare line. `call_check_results`
maps each `CallInterfaceFinding` to rule `call-check/<kind>` at the CALL's
line. `sarif_log(results, notifications, base=cwd)`:

* `level`: error -> `error`, warning -> `warning`, info -> `note`.
* `rules`: one entry per rule id that produced a result, in first-seen
  order, `shortDescription` from `RULE_DESCRIPTIONS`; `ruleIndex` points
  into it.
* Locations: a path under *base* is relative (posix) with `uriBaseId`
  `%SRCROOT%` (declared in `originalUriBaseIds`), which is what GitHub code
  scanning resolves against the checkout; anything else is an absolute
  `file:` URI. No line -> no `locations` (never a made-up line 1).
  `startColumn` only when known.
* `properties` carry `kind` / `symbol` (lint) or `caller` / `callee` /
  `callee_path` / `position` (call-check).
* Lint `caveats` and `failed_rules`, call-check `unchecked` and parse
  `errors`, and `scan`'s failed files are `invocations[0].
  toolExecutionNotifications` (failed ones at `error`), so a quiet log is
  not mistaken for a checked program.

Validated against the OASIS `sarif-schema-2.1.0.json` on 2026-10-28 (not
vendored: the suite runs offline); `tests/unit/analysis/test_sarif.py` pins
the shape. The exit codes of each subcommand are unchanged by the format
(`--fail-on` still exits 3; `scan` exits 2 on a failed file).

In `scan`, `lint` is a *file-level* analyzer (`scan.FILE_ANALYZERS`): it
covers every unit of a file already, so it runs once per file into
`FileScan.reports["lint"]`, with parse errors as findings and every finding
placed on disk, rather than once per unit (which would repeat each
contained program's findings). It does not get the CLI's
`copybook_item_names` (the unexpanded second parse), so an unused copybook
item is graded warning there rather than info. `scan --format sarif` runs
`lint` alone, or adds it to the `--analyzer` list given.

## See also

* [../analysis.md](../analysis.md) -- routing page, calling conventions, module map
* [flow.md](flow.md), [data-use.md](data-use.md), [sql-cics-ims.md](sql-cics-ims.md)
  -- the analyzers behind each rule
* [../cli.md](../cli.md) -- `lint` flags (`--rule`, `--min-severity`,
  `--fail-on`, `--format text`) and parse-error findings
* [../preprocessing.md](../preprocessing.md) -- the expansion source map
* [../batch.md](../batch.md) -- `scan`, which stamps origins per file
* [history](../history/analysis.md) -- dated notes behind these rules
