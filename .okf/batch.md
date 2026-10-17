---
type: Module
title: Batch Parsing
description: Many files at once — parse_files() / parse_files_with_copybooks() (batch.py) hand back every ParseResult; scan_files() / cross_file_clone_groups() (scan.py) run analyzers inside the workers and hand back only report dicts.
tags: [batch, parallel, process-pool, copybook, scan, clones]
timestamp: 2026-10-15T00:00:00Z
---

# Batch Parsing

Two modules parse many COBOL files (500–5000+) without the caller managing a
process pool or per-file error handling:

| Module | Entry points | Returns | Use when |
|--------|--------------|---------|----------|
| `cobolparser/batch.py` | `parse_files`, `parse_files_with_copybooks` | `list[BatchResult]`, one `ParseResult` (AST included) per file | the caller wants the trees |
| `cobolparser/scan.py` | `scan_files`, `scan_one`, `cross_file_clone_groups` | `ScanReport` of JSON-shaped analyzer report dicts | "grade this whole checkout" (`cobol-parser scan`) |

`parse_files`, `parse_files_with_copybooks`, `BatchResult`, `scan_files`,
`ScanOptions`, `ScanReport` and `cross_file_clone_groups` are also
re-exported from the top-level `cobolparser` package (`scan_one` is not). Both modules share two rules: **one poisoned file
never aborts the batch** (it costs its own entry), and **every worker
function is module-level** (no lambdas/closures), so it pickles under Windows
spawn-based multiprocessing.

Start with `parse_files(paths)` if you need ASTs, `scan_files(paths)` if you
need grades/findings across a codebase.

## Contents

* [Public API (`batch.py`)](#public-api-batchpy)
* [Per-file fault isolation](#per-file-fault-isolation)
* [Multi-file analysis: `scan.py`](#multi-file-analysis-scanpy) —
  [entry points and options](#entry-points-and-options),
  [report shape](#report-shape),
  [properties](#properties-it-owes-its-caller-pinned-by-testsunittest_scanpy),
  [cross-file clone groups](#cross-file-clone-groups)
* [See also](#see-also)

## Public API (`batch.py`)

```python
from cobolparser.batch import parse_files, parse_files_with_copybooks, BatchResult

results: list[BatchResult] = parse_files(["a.cbl", "b.cbl"], workers=4)

# Executor reuse (avoids spawn overhead across repeated batches; the caller
# owns the pool's lifecycle)
from concurrent.futures import ProcessPoolExecutor
with ProcessPoolExecutor(max_workers=4) as executor:
    batch1 = parse_files(files1, executor=executor)
    batch2 = parse_files(files2, executor=executor)

# Copybook-aware: sequential in the main process, shared resolver cache
results = parse_files_with_copybooks(files, copybook_paths=["/path/to/cpy"])
```

Signatures (all keyword arguments after `paths` have defaults):

* `parse_files(paths, workers=None, error_recovery=COLLECT_ALL,
  dialect=IBM_ENTERPRISE, encoding="utf-8", errors="replace", executor=None,
  enable_profiling=False, top_n=50, prof_output=None, debug_lines=False)`.
  `workers=None` uses `os.cpu_count()`; `workers <= 0` raises `ValueError`.
  With no `executor` and one worker it takes a **sequential fast path** in
  the caller's process (no pickling, clean tracebacks) reusing one
  module-level `CobolParser` (`_get_reusable_parser`, re-created when
  `error_recovery` / `dialect` / `debug_lines` change). Otherwise
  `ProcessPoolExecutor.map` with `chunksize = max(1, n // (workers*4))`.
  File I/O happens inside the workers, so large source strings are never
  pickled.
* `parse_files_with_copybooks(paths, copybook_paths, workers=None,
  error_recovery=..., dialect=..., encoding="utf-8", errors="replace",
  max_nesting_depth=100, copybook_cache_size=1024, enable_profiling=False,
  top_n=50, prof_output=None, debug_lines=False)`. Runs **sequentially** in
  the main process (`workers` is accepted but unused, reserved) to maximize
  cache hits: one `PathResolver` (resolution + directory-index caches) and
  one `CobolParser` are reused for every file, and copybook reads go through
  the copybook expander's module-level LRU file cache. Expansion runs with
  `validate_content=False` (speed), `process_conditionals=True`,
  `preserve_source_locations=True, source_file=<path>` and `debug_lines`.

Both return results **in input order**.

`BatchResult` (dataclass) — `path: Path`, `result: ParseResult | None`,
`read_error: str | None` (always a plain `str`, pickle-safe on Windows
spawn), `profiling: ProfilingResult | None`, `copybook_error: str | None`
(copybook-aware path only: `"<ExcType>: <message>"` when expansion failed and
the file was parsed unexpanded).

**What `parse_files_with_copybooks` attaches to each result** — the same
things `parse_cobol_with_expansion` attaches (#255), so the two entry points
cannot disagree about a line:

* `result.expansion_source_map` — expanded line -> `(file, original line)`.
* the expansion's `statistics.warnings`, merged (deduplicated) into
  `result.warnings`.
* the dropped-`D`-lines warning the expansion hid from the parser
  (`warn_dropped_debug_lines`, see [preprocessing.md](preprocessing.md)).

**`debug_lines`** (both functions) is `parse_cobol`'s `debug_lines`: compile
fixed-format `D`-in-column-7 lines as code; the copybook-aware path passes it
through the expansion as well.

**Profiling.** With `enable_profiling=True` each `BatchResult.profiling` is a
`ProfilingResult` (top `top_n` functions). With `prof_output=DIR` (must be a
directory; a value ending in `.prof` raises `ValueError`; created if absent)
each file's cProfile dump is `DIR/<stem>.prof`; inputs sharing a stem
(`a/PROG.cbl` + `b/PROG.cbl`, or `PROG.cbl` + `PROG.cob`) get
`<stem>-2.prof`, `<stem>-3.prof`, ... in input order (`_prof_file_names`,
case-insensitive), so none overwrites another. `profiling.prof_file` names
each result's own file.

## Per-file fault isolation

Both `batch.py` entry points guarantee that **one poisoned file cannot abort
the whole batch** — every other file's result still comes back. Each
per-file stage is wrapped so a failure becomes a
`BatchResult(result=None, read_error=...)` entry instead of an exception
propagating out of the batch call:

* **File read** — `OSError` and `ValueError` (the latter covers
  `UnicodeDecodeError` under `errors="strict"`, a documented `errors=` use
  case).
* **Parsing itself** — `parser.parse(...)` / `parse_cobol(...)` raising;
  `read_error` is then `"parse error: <ExcType>: <message>"`.
* **Copybook expansion** (`expand_copybooks` raising) — this one *degrades*
  rather than failing: the file is parsed from its raw, unexpanded source, a
  warning is logged (`"Copybook expansion failed for %s..."`), and the reason
  reaches the result as `BatchResult.copybook_error` plus a
  `copybook expansion failed (...); the file was parsed without expanding
  any COPY statement` entry in `result.warnings`. The reason must be visible
  because the fallback un-expands *every* COPY in the file, not just the bad
  one, and the unexpanded parse is usually error-free.

Why degrade instead of failing the file (as `parse_cobol_with_expansion`
does by raising): `codebase-graph` / `copybook-impact` read a file's CALL
edges and program id off the unexpanded parse; failing the file would make it a
`parse_failed` node named after its file. Expansion runs with
`process_conditionals=True` so a COPY inside an excluded `>>IF` block is
never resolved — otherwise a member that only exists for the other branch
(`COPY DFHAID` under `>>IF CICS DEFINED`) would push the whole file onto
this fallback.

Pinned by
`tests/integration/test_batch_coverage_gaps.py::TestParseFilesWithCopybooksParseException`
and `::TestParseFilesWithCopybooksDecodeError`.

## Multi-file analysis: `scan.py`

```python
from cobolparser import scan_files, ScanOptions, cross_file_clone_groups

report = scan_files(paths, ScanOptions(analyzers=("health", "redundancy")), workers=8)
report.ok_files / report.failed_files          # list[FileScan]
report.to_dict()                               # the `cobol-parser scan` document
groups = cross_file_clone_groups(report)       # across programs, not within one
```

**A separate module from `batch.py`, deliberately.** `parse_files` hands
every `ParseResult` — and therefore every AST — back to the caller. For
"grade this whole checkout" that is the wrong shape: a 5,000-file shop's ASTs
do not usefully fit in one process, and pickling them out of each worker
costs far more than the analysis does. `scan.py` inverts it: parse *and*
analyze inside the worker; only the small report dicts come back, so a
worker's peak memory is one file's AST.

### Entry points and options

* `scan_files(paths, options=None, workers=None, executor=None) -> ScanReport`
  — same pool rules as `parse_files` (`workers=None` = CPU count, `1` and no
  executor = sequential with no pool, `<= 0` raises, same chunksize rule,
  caller-owned `executor` reused). Raises `ValueError` up front naming any
  analyzer not in `ANALYZERS`. Files come back in input order.
* `scan_one(path, options) -> FileScan` — one file; **never raises**. This is
  what runs in each worker.
* `ANALYZERS` = `("health", "redundancy", "complexity", "dead-code",
  "unused-variables", "lineage")`, each keyed by its single-file subcommand
  name (`health` = `TechnicalDebtAnalyzer`, `redundancy` =
  `RedundancyAnalyzer` honouring `min_clone_statements`, `lineage` =
  `FieldFlowAnalyzer`). `DEFAULT_ANALYZERS` = `("health", "redundancy")`:
  `health` is the grade a portfolio sorts on; `redundancy` is the only one
  that emits the paragraph fingerprints cross-file clones need. Analyzer
  imports are local to each branch, so a scan pays only for what it runs.
* `parse_analyzer_list(raw)` — the CLI's `--analyzer` parser: repeatable
  and/or comma-separated, first-seen order, duplicates dropped, empty ->
  `DEFAULT_ANALYZERS`.

`ScanOptions` (dataclass, one picklable object rather than positional worker
arguments, so a worker signature cannot drift from its call site):

| Field | Default | Meaning |
|-------|---------|---------|
| `analyzers` | `DEFAULT_ANALYZERS` | which analyzers run per unit |
| `dialect` | `IBM_ENTERPRISE` | |
| `error_recovery` | `COLLECT_ALL` | |
| `copybook_paths` | `()` | non-empty -> `parse_cobol_with_expansion` |
| `min_clone_statements` | `3` | passed to `RedundancyAnalyzer` |
| `encoding` / `errors` | `"utf-8"` / `"replace"` | `Path.read_text` |
| `free_form` | `False` | lexer hint (auto-detection may still normalize) |
| `preprocess_fixed` | `None` | `None` auto-detects, `True`/`False` force/disable fixed-format normalization (CLI `--source-format fixed\|free`, cobol.yml `source_format:`) |
| `debug_lines` | `False` | compile `D`-in-column-7 lines (CLI `--debug-lines`, cobol.yml `project.debug_lines`) |
| `defined_symbols` | `()` | conditional-compilation `(name, value)` pairs (CLI `--define`, cobol.yml `project.define`): handed to the expander with copybook paths, else evaluated by `preprocess_conditional_compilation` before `parse_cobol` (#324) |

### Report shape

`ScanReport(options, files)`; `to_dict()` gives
`{scan_version, analyzers, min_clone_statements, summary, files, failures}`.
`SCAN_VERSION` (currently `1`) is bumped whenever the document's shape
changes; the COBOL Analyzer extension reads it before any other key.
`summary` = `{file_count, scanned_file_count, failed_file_count,
program_unit_count}`, and `file_count == scanned + failed` always — a
consumer can prove every file it handed over was accounted for.

* `FileScan` — `path`, `units: list[UnitScan]`, `error` (unreadable /
  unparseable / parsed to nothing; a file with an error has no units and is
  listed under `failures`), `parse_error_count` (errors `COLLECT_ALL`
  recovered from — the grade is worth labelling, not dropping),
  `copybook_error` (serialized only when set).
* `UnitScan` — `program_name`, `depth` (0 = outermost, 1 = contained in it,
  ...), `reports: {analyzer: dict}`, `failed_analyzers: {analyzer:
  "<ExcType>: <message>"}` (serialized only when non-empty).

### Properties it owes its caller (pinned by `tests/unit/test_scan.py`)

* **Fault isolation is per file.** A scan of a real legacy checkout WILL hit
  files that do not parse (a half-migrated member, a JCL file with a `.cbl`
  extension, an EBCDIC artifact); a read failure, a parse exception or an
  AST of `None` becomes that file's `error`, nothing more.
* **Every program unit is reported**, contained programs included, each with
  its `depth` (`_units_with_depth`; `CobolProgram.program_units()` drops the
  depth). Reporting only the outermost would present a contained program as
  clean because nothing looked at it.
* **Nothing is silently omitted.** An analyzer that raises on one unit lands
  in that unit's `failed_analyzers` (deliberately broad `except Exception`);
  its other reports are intact.
* **Locations say where the code really is.** With `copybook_paths`, every
  report dict's `"location"` counts lines of the expanded text; `scan_one`
  stamps a sibling `"origin": {"file", "line"}` from the expander's source
  map (`analysis.lint.stamp_report_origins`). The `lineage` analyzer is the
  exception to that generic pass — its edges carry a bare `line`, not a
  `location` — so `_run_analyzer` receives the source map and applies
  `field_lineage.apply_source_map` itself.

**Copybook expansion failure degrades, as in `batch.py`.** The file falls
back to the unexpanded parse and keeps the reason as
`FileScan.copybook_error` (the unexpanded parse is usually error-free, so
without it the reports would be indistinguishable from an expanded scan's).
The fallback must never be a bare `pass`. Copybook paths matter more
than they look: an unexpanded program's WORKING-STORAGE is missing whatever
its COPY members declare, so `unused-variables` (and therefore `health`'s
redundancy component, and therefore the portfolio grade) would grade a
program against a record layout it cannot see.

### Cross-file clone groups

`cross_file_clone_groups(report, *, min_members=2) -> list[CrossFileCloneGroup]`
merges every scanned paragraph's `redundancy.paragraph_fingerprints` (the
`type1` exact / `type2` renamed-identifier digests) into groups spanning
programs. Requires the `redundancy` analyzer; a unit without that report
contributes nothing.

* `CrossFileCloneMember` — `path`, `program_name`, `paragraph`, `line`,
  `origin_file` / `origin_line` (where the paragraph really is when
  copybooks were expanded; serialized as `"origin"`). `source_key` is the
  on-disk position: the copybook position when the paragraph came from one,
  else `(path, line)`.
* `CrossFileCloneGroup` — `clone_type` (`"TYPE_1"` / `"TYPE_2"`),
  `statement_count`, `fingerprint`, `members`; properties `file_count`
  (distinct files) and `source_count` (distinct `source_key`s).
* **Type-1 wins**: a paragraph claimed by an exact group is not also offered
  as a renamed match (same precedence as `RedundancyAnalyzer` within one
  program).
* **One source, one copy** (#352): `min_members` counts distinct
  `source_key`s, so a PROCEDURE DIVISION copybook paragraph included by
  every program is shared code and forms no group on its own; its
  inclusions still appear as members of a group that has another real copy.
* **Ranking**: by duplicated volume, `statement_count x source_count`
  descending, then `source_count`, member count, `TYPE_1` before `TYPE_2`,
  fingerprint (stable across runs). Deliberately *not* by `file_count`:
  every shop's near-identical `0000-MAIN-PROCESS` scaffold spans every file
  and would bury a sixteen-statement paragraph copy-pasted into two
  programs — the finding the feature exists for.

Backs `cobol-parser scan` (`--analyzer`, `--clones`, `--min-clone-members`,
`--min-clone-statements`, `--workers`, `--glob`, `--files-from`; see
[cli.md](cli.md)) and the COBOL Analyzer extension's Analyze Workspace.

## See also

* [parser.md](parser.md) — `CobolParser`/`parse_cobol` used per file;
  `ProfilingResult`
* [analysis.md](analysis.md) — the analyzers `scan` runs, and the paragraph
  fingerprints `cross_file_clone_groups` groups on
* [preprocessing.md](preprocessing.md) — `expand_copybooks`, the source map,
  `warn_dropped_debug_lines`
* [cli.md](cli.md) — `batch` and `scan` subcommands
* [history](history/batch.md) — archived dated notes
