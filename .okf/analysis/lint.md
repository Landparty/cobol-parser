---
type: Module
title: Lint Analyzer
description: LintAnalyzer (analysis/lint.py) -- runs nine analyzers over one parse and flattens them into one severity-graded LintFinding stream; per-unit linting, caveats and failed rules, and the source-map origin stamping (apply_source_map, stamp_report_origins, fixed_format_column_offset) shared by every analyzer CLI.
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
tuple, in that order) rather than a second private
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

## See also

* [../analysis.md](../analysis.md) -- routing page, calling conventions, module map
* [flow.md](flow.md), [data-use.md](data-use.md), [sql-cics-ims.md](sql-cics-ims.md)
  -- the analyzers behind each rule
* [../cli.md](../cli.md) -- `lint` flags (`--rule`, `--min-severity`,
  `--fail-on`, `--format text`) and parse-error findings
* [../preprocessing.md](../preprocessing.md) -- the expansion source map
* [../batch.md](../batch.md) -- `scan`, which stamps origins per file
* [history](../history/analysis.md) -- dated notes behind these rules
