---
type: Module
title: CLI
description: cobol-parser command-line subcommands and flags — entry point cobolparser.cli:main.
tags: [cli, command-line, subcommands, output-identification]
timestamp: 2026-08-18T00:00:00Z
---

# Overview

Entry point: `cobol-parser` → `cobolparser.cli:main`

Source: `cobolparser/cli/parse.py` (all subcommands), `cobolparser/cli/coverage.py` (IO coverage tools).

Every subcommand's `--help` now shows a `RawDescriptionHelpFormatter` epilog
with one or two runnable `cobol-parser <name> ...` examples (2026-08-18).
Purely a `--help` UX addition — no flags, defaults, or output shapes changed;
`_build_analyzer_parser()` grew a required `examples` kwarg (a
"cobol-parser <name> ..." block, no leading label) that its 13 callers each
supply, and the remaining hand-built parsers (`parse`, `batch`, `tokenize`,
`preprocess`, `expand`, `gen-data`, `gen-fixtures`, `unused-variables`,
`program-flow`) set their own `epilog=` directly.

# Output Identification

Every output the CLI emits is self-describing — it identifies the source it
was produced from (helper: `_identification()` in `cobolparser/cli/parse.py`;
pinned by `tests/unit/cli/test_output_identification.py`):

* **JSON documents** start with `"source_file"` (the input path as given on
  the command line). Subcommands that parse the source also emit
  `"program_id"` (the PROGRAM-ID, or `null` if the program has none) as the
  second key. Analyzer reports get both via `_emit_report(..., ast=ast)`.
* **`parse`** — full-AST output gets `"source_file"` spliced in (the AST dict
  already carries `program_name`). With `--errors`/`--stats` the wrapper is
  `{"source_file", "program_id", "ast", ...}`. Dotted-path extraction emits
  `{"source_file", "program_id", "path", "result"}`; `--find-type` emits
  `{"source_file", "program_id", "node_type", "matches"}`.
* **`tokenize`** — `{"source_file": ..., "tokens": [...]}` (previously a bare
  token list).
* **`expand`** — expansion dict prefixed with `"source_file"` (no
  `program_id`: the source is not parsed).
* **`batch`** — a JSON list; each entry carries `"path"` and, when the parse
  produced an AST, `"program_id"`.
* **Text outputs** — Mermaid flowcharts start with a `%% Program: <name>`
  comment; DOT names the digraph after the program. `preprocess`
  output is deliberately unidentified (it is transformed source meant to be
  fed onward).
* **`gen-fixtures`** — `--format json` (default) follows the standard
  convention (`{"source_file", "bundle_version", "program_name", ...}`,
  `program_name` already inside the bundle rather than a separate
  `program_id` key). `--format csv-dir` writes a directory instead of
  stdout; its `MANIFEST.json` carries the same identification.

# Subcommand Reference

## Parse

```bash
cobol-parser parse <file.cbl> [json-path] [--compact] \
    [--source-format auto|fixed|free] [--free-form] \
    [--dialect ibm-enterprise] [--errors] [--stats] [--find-type NODE_TYPE] \
    [--profile] [--profile-top-n N] [--profile-output PATH]
```

Parses a COBOL file and prints the AST as JSON. `json-path` (dotted) extracts
a specific subtree. `--errors` shows parse errors only. `--stats` appends
`ParseStatistics`. `--find-type` finds all AST nodes of the given type (e.g.
`MoveStatement`), equivalent to `ast.find_all_by_type()`. `--profile` /
`--profile-top-n` / `--profile-output` wrap the parse in a `ProfilerContext`
(see [parser.md](parser.md)) and embed timing/memory metrics in the output, or
write a binary `.prof` to `PATH`.

Exit codes (2026-07-07): `0` clean parse; `1` hard failure (`ast is None`,
bad arguments); `2` recovered-but-errored parse — the JSON is still printed,
a summary goes to stderr. Previously the CLI exited `0` whenever an AST
existed, even with collected errors, so scripts gating on `$?` saw every
partial parse as success. `batch` likewise exits `2` when any file has a
`read_error` or `success=false`. Analyzer subcommands still exit `0` on a
partial parse but print a stderr warning that analysis may be incomplete.

## Tokenize

```bash
cobol-parser tokenize <file.cbl>
```

Prints the token stream as JSON:
`{"source_file": "...", "tokens": [{"type": "...", "value": "...", "line": N, "column": N}]}`.

## Preprocess

```bash
cobol-parser preprocess <file.cbl> [--define DEBUG]
```

Runs fixed-format normalisation and conditional compilation; prints the resulting
free-form text. `--define` sets compiler flags for conditional blocks.
Under `auto` (the default) normalisation runs only when `_detect_fixed_format`
classifies the source as fixed (it used to run unconditionally, silently
slicing columns off genuine free-form input); `--source-format=fixed` forces
it; `--source-format=free` skips it entirely.

## Source layout (`--source-format`)

The subcommands that parse or lex a program directly — `parse`, `tokenize`,
`preprocess`, every analyzer subcommand built via `_build_analyzer_parser`
(`analyze`, `dead-code`, `complexity`, `health`, ...), `unused-variables`,
and `program-flow` — accept `--source-format {auto,fixed,free}` (default
`auto`). `batch`, `expand`, `gen-data`, and `gen-fixtures` do **not** take
the flag (their underlying APIs — `parse_files`, `ProgramLayoutIndex`,
`CopybookDataGenerator` — expose no layout override yet); they always
auto-detect.

| Value | Behaviour |
|-------|-----------|
| `auto` | Detect via `_detect_fixed_format` (see [parser.md](parser.md)) |
| `fixed` | Always normalise — strips columns 1-6 whatever they hold |
| `free`  | Never normalise |

`--free-form` is retained with its historical, *weaker* semantics — a
lexer-mode hint that auto-detection may still override by normalising
source it classifies as fixed-format (scripts that always passed it
against conventional fixed-format members relied on that lenience). It is
**not** an alias for `--source-format=free`, which hard-disables
normalisation. Passing both flags is rejected by argparse.

Reach for `fixed` when a shop's layout defeats auto-detection — e.g. a
sequence area holding a tag with an internal space. Auto-detection already
handles the common case of a solid change-tracking tag (`SAPR24`, `28486`)
in columns 1-6; before that fix such files were silently treated as
free-form and their tag text lexed as code.

All subcommands that run conditional compilation (`parse`, `preprocess`,
`expand` with `--define`) print any conditional-compilation diagnostics
(unknown `>>IF` conditions, stray `>>ELSE`/`>>END-IF`, malformed
`>>DEFINE`, unclosed `>>IF` — audit 2026-07-07 H7) to **stderr** as
`warning: ...` lines, so deleted guarded blocks are no longer silent.
`preprocess` (fixed-format branch only) additionally prints
`normalize_fixed_format`'s column-72 overflow diagnostics the same way
(2026-08-14 — see [preprocessing.md](preprocessing.md)'s "Column 73+
overflow warning" section): a non-comment line whose real content ran past
column 72 and was silently truncated.
`coverage status` reports malformed artifact JSON (or a non-object
artifact) with a clean error and exit code 1 instead of an uncaught
traceback (M10). `coverage generate` had the same gap (a malformed or
non-object pytest-results JSON file raised uncaught inside
`IOCoverageReporter.load_pytest_results`) — fixed the same way, audit
2026-07-08.

## Expand

```bash
cobol-parser expand <file.cbl> --copybook-path ./copybooks
```

Runs copybook expansion and prints the expanded source. `--copybook-path` may be
specified multiple times for multiple search directories.

## Gen-Data

```bash
cobol-parser gen-data <file.cpy> [--rows N] [--seed N] [--record NAME] \
    [--list-records] [--describe] [--header-style short|path] \
    [--include-filler] [--include-redefines] [--no-expand-occurs] \
    [--max-occurs N] [--no-semantic] [--ignore-values] [--unique FIELD] \
    [--blank-rate RATE] [--compact] [--output FILE]
```

Generates synthetic CSV test data from a copybook record layout — see
[generators.md](generators.md) for the generation rules. Emits **CSV on
stdout** (not JSON), so it pipes directly into a fixture file; `--output`
writes through the `csv` module so quoted cells round-trip.

* `--rows`/`-n` — record count (default 10). `--seed` pins the RNG; the same
  seed and copybook always produce byte-identical CSV.
* `--list-records` and `--describe` are the two JSON modes.
  `--list-records` emits `{"source_file", "records": [{name, level, size}]}`;
  `--describe` emits the resolved layout plus rows, including the `seed`
  actually used — the way to recover the seed of an unseeded run.
* `--record NAME` picks among multiple level-01 records (default: the first).
  An unknown name errors and lists what is available.
* Layout errors (`CopybookLayoutError`) exit 1 with the message on stderr.

## Gen-Fixtures

```bash
cobol-parser gen-fixtures <file.cbl> [--copybook-path DIR]... [--callee-path DIR]... \
    [--rows N] [--seed N] [--scenarios happy|branches|all] [--format json|csv-dir] \
    [--list-boundaries] [--strict] [--compact] [--output PATH]
```

Phase 3 of the `gen-fixtures` program-scoped test-data initiative (see
[generators.md](generators.md)'s "Program fixtures" section): points at a
whole **program** rather than a copybook, and produces mock in-data /
assert-on stubs for every boundary it touches (files, CALL/DYNCALL, SQL,
CICS, DLI, console ACCEPT) — not just one record's CSV rows.

* `--copybook-path DIR` (repeatable) expands COPY statements before
  analysis; an unresolved COPY member refuses (`ProgramLayoutError`, exit 1)
  rather than generate a bundle from a layout with a hole in it.
* `--callee-path DIR` (repeatable) searches for a statically-CALLed
  program's own source (tries `NAME`, `name` × `""`/`.cbl`/`.CBL`/`.cob`/
  `.COB` in each directory) to resolve its LINKAGE writes for the CALL
  argument-direction ladder's "callee source" rung. A caller/callee pair
  already bundled in one compilation unit (`CobolProgram.contained_programs`,
  e.g. `subprogram_demo.cbl`) needs no `--callee-path` at all.
* `--rows`/`-n` — rows generated per **READ** boundary's sequence (default
  10); every other IN boundary (SQL SELECT/FETCH, ACCEPT, a CALL argument)
  generates exactly one value, matching one invocation in the "happy path"
  scenario.
* `--seed` pins the RNG; the same seed and program always produce
  byte-identical JSON (`ProgramFixtureGenerator.generate`'s own per-boundary
  sub-seed scheme -- see generators.md -- means adding one boundary never
  reshuffles another's already-generated values).
* `--scenarios happy` (default) emits the single unconstrained "happy path"
  scenario (Phase 3). `branches` targets every reachable, satisfiable branch
  arm with its own (or a merged) scenario; `all` additionally adds the fixed
  empty-input / error-status / boundary-values scenario families -- both
  route through `cobolparser.generators.scenarios.ScenarioPlanner` (Phase 5)
  via `ProgramFixtureGenerator.generate_with_scenarios_from_file` (Phase 6)
  and populate the bundle's `scenario_coverage` key (`null` under `happy`).
  See generators.md's "Scenario Planning" and "Scenario-mode generation"
  sections, and `docs/fixture-bundle-schema.md` for the full JSON shape.
* `--format json` (default) emits the full bundle; `--format csv-dir`
  requires `--output DIR` and emits one CSV per file-shaped boundary fixture
  under `DIR/<scenario-slug>/<KEY>.csv` plus a `DIR/MANIFEST.json` (the
  bundle with every fixture's `sequence` emptied to `[]` -- never replaced
  with a hint string, so the manifest stays type-compatible with a normal
  bundle -- and a new `csv_path` key per fixture: the relative CSV path, or
  `null` for a fixture with no CSV written, e.g. a STATUS_ONLY boundary).
* `--list-boundaries` runs Phases 1-2 only (no value generation) and emits
  `{"source_file", "boundaries": [{category, key, paragraph, line,
  direction}, ...]}` — the cheap debugging view, and the natural cross-check
  against a downstream consumer's own boundary walk.
* `--strict` exits **2** (not 1 -- that stays "could not run at all") when
  `bundle.unresolved` is non-empty: anything Phase 1's index, Phase 2's
  inventory, or Phase 3's own field resolution could not pin down. The
  CI-friendly "no silent gaps" switch.

## Analyze

```bash
cobol-parser analyze <file.cbl>
```

Runs `DynamicCallAnalyzer` and prints a JSON summary of dynamic `CALL`
targets only (`called_program`, `is_dynamic`, and `possible_values` when
dynamic; a dynamic entry also carries `"possible_values_incomplete": true`
when the analyzer flagged the value set as not fully resolvable — see
`.okf/analysis.md`'s DynamicCallAnalyzer section — so the list is never
silently presented as exhaustive; added in the 2026-08-16 audit). Despite
the generic name, this is *not* an all-analyzers summary —
dead code, IO, MOVE-type, linkage, and LE checks each have their own
dedicated subcommand below.

## Dead-Code

```bash
cobol-parser dead-code <file.cbl>
```

Runs `DeadCodeAnalyzer` and lists unreferenced paragraphs/sections.

## Unused-Variables

```bash
cobol-parser unused-variables <file.cbl> [--copybook-path DIR ...] \
    [--exclude-copybook-variables] [--profile ...]
```

Runs `UnusedVariableAnalyzer` (see `.okf/analysis.md`) and lists DATA
DIVISION items never referenced in the PROCEDURE DIVISION.
`--exclude-copybook-variables` filters out unused items that came from an
expanded COPY; it only has an effect together with `--copybook-path`
(otherwise a stderr warning notes the no-op) since copybook provenance is
determined by parsing the source a second time *without* expansion
(`_parse_without_copybook_expansion`) and diffing declared item names
against the expanded AST — `expand_copybooks`'s own line-tracking
(`preserve_source_locations`) doesn't work (see `.okf/analysis.md`).

## Program-Flow

```bash
cobol-parser program-flow <file.cbl> [--format json|mermaid|dot] [--profile ...]
```

Runs `ProgramFlowAnalyzer` and emits the control-flow graph. `--format`
selects the output: `json` (default, raw `report.to_dict()` edges), `mermaid`
(via `generators/flowchart.py`'s `MermaidFlowchartGenerator`), or `dot`
(Graphviz DOT via `DotFlowchartGenerator`). Also accepts the shared
profiling flags (`--profile`, `--profile-top-n`, `--profile-output`);
`--profile` metrics can only be embedded in `json` output, so combining it
with `mermaid`/`dot` prints a stderr warning instead of silently
discarding the profiler result (2026-08-16 audit).

## Recursion-Check

```bash
cobol-parser recursion-check <file.cbl> [--profile ...]
```

Runs `RecursionRiskAnalyzer` (see `.okf/analysis.md`) and reports recursion-
driven infinite-loop risks: PERFORM/GO TO cycles reused from
`ProgramFlowAnalyzer`'s `cycle_details` (`PERFORM_RECURSION` always `HIGH`;
`GOTO_LOOP`/`MIXED` graded `HIGH`/`MEDIUM` by whether the cycle has an
escape route) and self-recursive CALL statements (static or dynamic,
targeting the program's own `PROGRAM-ID`, always `HIGH`). Registered the
same way as `dead-code`/`data-items` (via `_build_analyzer_parser(...,
profiling=True)`), so it also accepts the shared profiling flags.

## Complexity

```bash
cobol-parser complexity <file.cbl> [--profile ...]
```

Runs `ComplexityAnalyzer` (see `.okf/analysis.md`) and reports per-paragraph
McCabe cyclomatic complexity, an AND/OR-aware `extended_complexity`, max
nesting depth, fan-in/fan-out (from `ProgramFlowAnalyzer`'s PERFORM/GO TO
edges), and a LOW/MODERATE/HIGH `rating` per procedure, plus a program-level
summary (`total_complexity`, `mean_complexity`, `goto_density`, ...).
Registered the same way as `recursion-check` (`_build_analyzer_parser(...,
profiling=True)`).

## Health

```bash
cobol-parser health <file.cbl> [--profile ...]
```

Runs `TechnicalDebtAnalyzer` (see `.okf/analysis.md`) and reports a
composite 0-100 technical-debt score with an A-F letter grade, a per-
component breakdown (`complexity`/`redundancy`/`control_flow`/`size`, each
with its own findings), and a `top_offenders` list of the worst procedures
with the specific reasons (dead code, clone membership, GO TO count, no-
escape recursion cycle, ...) that put them there. Embeds the underlying
`ComplexityReport`/`RedundancyReport` summaries (`complexity_summary`/
`redundancy_summary`) rather than the full per-procedure detail -- run
`complexity` directly for that. Registered the same way as
`recursion-check`.

## Batch

```bash
cobol-parser batch [prog1.cbl prog2.cbl ...] [--glob PATTERN] [--workers N] \
    [--encoding utf-8] [--stats] [--errors] [--profile ...]
```

Parallel multi-file parsing via `ProcessPoolExecutor`. Files may be given
positionally and/or collected via repeatable `--glob` patterns (e.g.
`--glob 'src/**/*.cbl'`). `--workers` sets the process-pool size (default: CPU
count). `--encoding` sets file read encoding (default `utf-8`). Prints one
JSON result per file. `--errors` includes parse errors/warnings per file;
`--stats` appends per-file `ParseStatistics`. `--profile-output` in batch mode
must be a directory (one `.prof` per file), not a single file path.

## IO-Sequence

```bash
cobol-parser io-sequence <file.cbl>
```

Runs `IOSequenceAnalyzer` and reports sequencing violations.

## Move-Type-Check

```bash
cobol-parser move-type-check <file.cbl>
```

Runs `MoveTypeChecker` and reports type-incompatible MOVE statements.

## Linkage-Check

```bash
cobol-parser linkage-check <file.cbl>
```

Runs `LinkageChecker` and reports LINKAGE SECTION violations.

## Language-Env

```bash
cobol-parser language-env <file.cbl>
```

Runs `LanguageEnvironmentAnalyzer` and reports IBM LE function/service usage.

## IMS-DLI

```bash
cobol-parser ims-dli <file.cbl>
```

Runs `IMSSegmentAnalyzer` and reports IMS DLI segment calls.

## Data-Items

```bash
cobol-parser data-items <file.cbl> [--profile ...]
```

Runs `compute_program_data_items()` (see [generators.md](generators.md)'s
`layout_offsets.py` entry) and reports `{"items": [...], "unresolved":
[...]}` — byte offset, byte length, REDEFINES chain, OCCURS min/max, and
level-88 condition values for every data item across every DATA DIVISION
section (FILE/WORKING-STORAGE/LOCAL-STORAGE/LINKAGE) of the program.
Registered the same way as `dead-code`/`io-sequence` (via
`_build_analyzer_parser(..., profiling=True)`), so it also accepts the
shared profiling flags. Added 2026-08-14 (Task 9 of the data-item-layout
plan) as the final wiring step for Tasks 1-8's `layout_offsets.py` module.

# See Also

* [analysis.md](analysis.md) — the underlying analyzers, including
  `BoundaryInventoryAnalyzer` (`gen-fixtures`, Phase 2) and
  `ConstraintExtractor`/`domains.solve()` (Phase 4, feeds `--scenarios`)
* [parser.md](parser.md) — `parse_cobol` used by most subcommands
* [generators.md](generators.md) — `ProgramLayoutIndex` / `ProgramFixtureGenerator`
  / `FixtureBundle` / `ScenarioPlanner` (`gen-fixtures`, Phases 1, 3, 5-6)
* [`docs/fixture-bundle-schema.md`](../docs/fixture-bundle-schema.md) — the
  full `FixtureBundle` JSON shape `gen-fixtures --format json` produces
