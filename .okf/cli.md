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
    [--blank-rate RATE] [--format csv|json|record|hex] \
    [--charset ascii|ebcdic] [--endian auto|big|little|native] \
    [--record-format fixed|variable|variable-bare|auto] \
    [--record-varying MIN:MAX] \
    [--record-separator none|newline] [--compact] [--output FILE]
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

### `--format record` / `--format hex`: real record bytes

`csv` (default) and `json` emit **display** values — `72436.21` regardless of
whether the field is `PIC 9(7)V99` or `PIC S9(7)V99 COMP-3`. The other two
emit the **record image**: the bytes a COBOL program would actually read,
with `COMP-3` packed into nibbles, `COMP`/`COMP-4` as big-endian binary,
`COMP-5` and the floats in host order, and signed DISPLAY overpunched. See
[generators.md](generators.md)'s "Record images" section for the full
encoding table and its verified-against-GnuCOBOL provenance.

* `record` writes raw bytes — through `sys.stdout.buffer` on stdout and in
  binary mode to `--output`, since a `COMP` field routinely contains `0x0A`
  and a text-mode write would corrupt it. The image is encoded **once** and
  the same bytes go to whichever destination applies; the `--output` branch
  deliberately does *not* call `GeneratedDataset.write_records()`, which
  would encode the whole dataset a second time and hold both copies at once
  (a real ceiling on a large `--rows`, and a review finding on PR #200).
  `write_records()` itself is unchanged and still right for a caller that
  has not already encoded. `hex` is the same image annotated
  field by field (offset, length, name, PICTURE, USAGE, value, bytes), which
  is the form that survives being opened in an editor.
* `--charset ebcdic` encodes every DISPLAY byte as cp037 and switches the
  zoned-sign convention to EBCDIC zones; the sign convention is **not** a
  separate flag, it follows the charset.
* `--endian` (default `auto`) applies to `COMP-5` and `COMP-1`/`COMP-2` only
  — `COMP`/`COMP-4` are always big-endian. `auto` reads the charset as
  intent: big-endian for `ebcdic` (z/OS-bound), host order otherwise.
* `--record-format` picks fixed- or variable-length records — see the next
  section.
* `--record-separator newline` appends `\n` per record for readability;
  the default `none` is a true fixed-length RECFM=F image.
* Both formats force the byte-complete layout (`DataGeneratorOptions
  .for_record_image()`: FILLER in, REDEFINES out, every OCCURS occurrence
  expanded) and print a note to stderr saying so, since otherwise
  `--include-filler`/`--max-occurs` would look silently ignored.
* Anything not modelled (`SYNCHRONIZED` alignment, IEEE-vs-hex float,
  `OCCURS DEPENDING ON` written at maximum under `--record-format fixed`) is
  printed to stderr for `--format record` and inlined in the header for
  `--format hex` — never swallowed.

### `--record-format`: fixed- vs variable-length files

A copybook says how long a record *can* be, not whether the file holding it
is RECFM=F/FB or RECFM=V/VB. This flag says which one to write; it applies
to `--format record|hex` only (CSV and JSON have no notion of record length).

| Value | Records | Framing |
|-------|---------|---------|
| `fixed` (default) | every `OCCURS ... DEPENDING ON` occurrence written, one length for the whole file | none |
| `variable` | only the occurrences each record's own counter names | 4-byte RDW per record |
| `variable-bare` | the same trimmed records | none |
| `auto` | `variable` if the record varies at all, else `fixed` | follows the resolved value |

* **`fixed` is the default so existing output does not move.** A record that
  cannot vary writes identical bytes under every value bar the RDW, so the
  choice only matters where records genuinely can vary. `--record-varying` is
  the exception: it *says* records vary, so passing it alone reaches `auto`
  rather than writing a fixed file; an explicit `--record-format fixed` still
  wins.

**Two ways a record varies**, and `gen-data` handles both:

1. `OCCURS ... DEPENDING ON` in the record — the count of occurrences decides
   the length, and the counter is generated inside the table's bounds.
2. `FD ... RECORD VARYING FROM min TO max DEPENDING ON item` on the file —
   the record layout is flat and the length is simply how many of its bytes
   each record carries. Given a **whole COBOL program**, the FD clause is read
   off the record with no flag at all. Given a bare **copybook**, which has no
   FD, `--record-varying MIN:MAX` supplies the range (`MIN-MAX` is accepted
   too, since that is how it reads in the FD). The cut can fall mid-field —
   which is exactly what a program reading `REC(1:LEN)` sees — and
   `--format hex` marks the fields past it as `(past record length)`.
* **The RDW** is `LL LL 00 00` — a big-endian 16-bit length *including the
  four RDW bytes*, then two reserved zero bytes — regardless of `--charset`
  and `--endian`. A record whose total would exceed 65 535 bytes errors out
  rather than writing a wrapped length; that needs RECFM=VS (spanned), which
  is not generated.
* **The counter is generated inside the table's own bounds**, so `OCCURS 1 TO
  50 DEPENDING ON WS-N` never emits a `WS-N` of 8 731 — under `fixed` too.
* **The resulting LRECL (or LRECL range) is printed to stderr** for
  `--format record`, because raw bytes carry no header to state it in. When a
  range is declared, the *declared* LRECL is printed alongside the span the
  generated file happens to contain — a short `--rows` may never hit the
  maximum, but the dataset still has to be allocated for it.
  `--format hex` puts it in its own header, along with a `(RDW)` row per
  record so field offsets stay true.
* A DEPENDING ON counter that is **not part of the record** (declared in
  WORKING-STORAGE, say) is named on stderr and its table written at full
  length — nothing generated can set it.

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

## Lint

```bash
cobol-parser lint <file.cbl> [--rule RULE]... [--min-severity error|warning|info] \
    [--fail-on error|warning|info|never] [--format json|text] [--copybook-path DIR]
```

Runs `LintAnalyzer` (see `.okf/analysis.md`) — several analyzers over **one**
parse — and reports every finding as a single severity-graded list, instead of
one subcommand (and one re-parse) per concern.

`--rule` (repeatable) selects rules; the ids are deliberately the analyzer
subcommand names themselves: `dead-code`, `unused-variables`,
`move-type-check`, `io-sequence`, `linkage-check`, `recursion-check`,
`complexity`. Argparse `choices` rejects an unknown id, so a typo can never
read as "that rule found nothing". Ordering and duplicates in the flags do not
affect the report — the selection is normalized to the canonical rule order.

`--min-severity` (default `info`, i.e. everything) drops lower-severity
findings *after* the rules run, so the summary counts always describe what was
actually shown.

`--format json` (default) emits the standard identification header plus
`findings` / `rules_run` / `failed_rules` / `caveats` / `summary`. `--format
text` emits one `file:line:column: severity [rule] message` line per finding —
the prefix an editor's or build log's error parser already understands —
followed by `note:` lines for caveats and failed rules, then a summary line.
A finding with no location (a recursion cycle spans procedures) prints as
`file: severity ...`; the column is omitted rather than faked as 0.

**Exit codes.** `0` ran to completion (findings alone never change it); `1`
the file could not be read or parsed, or its output could not be written
(`_fail`); `2` argparse rejected the arguments — an unknown `--rule` or flag,
which argparse exits on itself before `_cmd_lint` ever runs (pinned by
`test_lint_subcommand.py::test_unknown_rule_is_rejected_by_argparse`); `3`
`--fail-on` was given and a finding at or above that severity was reported.
`3` rather than the conventional `1` on purpose: a CI gate must be able to
tell "this program has problems" from "lint never ran", and `1`/`2` already
mean something else across this CLI (see *Exit codes* above).

`--copybook-path` does double duty here: it expands COPY members so MOVE
operands resolve *and* it lets lint tell a copybook-sourced unused item (info)
from one the program declares itself (warning), via the same unexpanded-parse
set difference `unused-variables` uses.

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
