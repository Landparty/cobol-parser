---
type: Module
title: Batch Parsing
description: parse_files() / parse_files_with_copybooks() — parallel multi-file COBOL parsing.
tags: [batch, parallel, process-pool, copybook]
timestamp: 2026-07-08T00:00:00Z
---

# Overview

`cobolparser/batch.py` — parses many COBOL files (500–5000+) without the
caller having to manage a process pool or per-file error handling by hand.
All worker functions are module-level (not lambdas/closures) so they pickle
under Windows spawn-based multiprocessing.

# Public API

```python
from cobolparser.batch import parse_files, BatchResult
from cobolparser.batch import parse_files_with_copybooks

results: list[BatchResult] = parse_files(["a.cbl", "b.cbl"], workers=4)

# Executor reuse (avoids spawn overhead across repeated batches)
from concurrent.futures import ProcessPoolExecutor
with ProcessPoolExecutor(max_workers=4) as executor:
    batch1 = parse_files(files1, executor=executor)
    batch2 = parse_files(files2, executor=executor)

# Copybook-aware batch parsing with a shared expansion cache — runs
# sequentially in the main process to maximize cache hits across files that
# share copybooks.
results = parse_files_with_copybooks(files, copybook_paths=["/path/to/cpy"])
```

`BatchResult` — `path`, `result: ParseResult | None`, `read_error: str | None`
(always a plain `str`, pickle-safe on Windows spawn), `profiling:
ProfilingResult | None`.

With `enable_profiling=True, prof_output=DIR`, each file's cProfile dump is
`DIR/<stem>.prof`; inputs sharing a stem (`a/PROG.cbl` + `b/PROG.cbl`, or
`PROG.cbl` + `PROG.cob`) get `<stem>-2.prof`, `<stem>-3.prof`, ... in input
order (`_prof_file_names`, case-insensitive). Before 2026-09-28 they all
wrote `<stem>.prof` and overwrote one another. `profiling.prof_file` names
each result's own file.

# Per-File Fault Isolation

Both entry points guarantee that **one poisoned file cannot abort the whole
batch** — every other file's result still comes back. Each per-file stage is
wrapped so a failure becomes a `BatchResult(result=None, read_error=...)`
entry instead of an exception propagating out of the batch call:

* File read (`OSError`, `ValueError` — the latter covers `UnicodeDecodeError`
  under `errors="strict"`, a documented `errors=` use case).
* Parsing itself (`parser.parse(...)` / `parse_cobol(...)` raising).
* Copybook expansion (`expand_copybooks` raising) — this one degrades rather
  than failing: it falls back to parsing the raw, unexpanded source, and
  logs a warning (`"Copybook expansion failed for %s..."`) so the
  degradation is observable rather than silent. Expansion runs with
  `process_conditionals=True` (2026-09-28), so a COPY inside an excluded
  `>>IF` block is never resolved -- before, a member that only exists for
  the other branch (`COPY DFHAID` under `>>IF CICS DEFINED`) pushed the
  whole file onto this unexpanded fallback.

**Audit fix (2026-07-08):** `parse_files_with_copybooks` used to only catch
`OSError` on the file-read step (missing the `ValueError`/
`UnicodeDecodeError` case `parse_files`'s workers already handled) and had
*no* exception guard at all around the `parser.parse(...)` call — a parse-time
exception on any file propagated out of the function, discarding every
other file's already-computed `BatchResult`. Both gaps are now closed the
same way `parse_files`'s `_parse_one`/`_parse_one_reuse` workers already
handle them. Pinned by
`tests/integration/test_batch_coverage_gaps.py::TestParseFilesWithCopybooksParseException`
and `::TestParseFilesWithCopybooksDecodeError`.

# Multi-file analysis: `scan.py` (2026-09-13)

```python
from cobolparser import scan_files, ScanOptions, cross_file_clone_groups

report = scan_files(paths, ScanOptions(analyzers=("health", "redundancy")), workers=8)
report.ok_files / report.failed_files
groups = cross_file_clone_groups(report)     # across programs, not within one
```

**A separate module from `batch.py`, deliberately.** `parse_files` hands
every `ParseResult` -- and therefore every AST -- back to the caller, which
is the right shape for a caller that wants the trees and the wrong one for
"grade this whole checkout": a 5,000-file shop's ASTs do not usefully fit in
one process, and pickling them out of each worker costs far more than the
analysis does. `scan.py` inverts it -- parse and analyze both inside the
worker, only the small JSON-shaped report dicts come back.

Three properties it owes its caller, all pinned by `tests/unit/test_scan.py`:

* **Fault isolation is per file.** A scan of a real legacy checkout WILL hit
  files that do not parse (a half-migrated member, a JCL file with a `.cbl`
  extension, an EBCDIC artifact), and one that aborts on the first can never
  be run at all. Same principle as `parse_files` above, one level up.
* **Every program unit is reported**, contained programs included, each with
  its `depth`. Reporting only the outermost would present a contained
  program as clean because nothing looked at it.
* **Nothing is silently omitted.** An analyzer that raises on one unit lands
  in that unit's `failed_analyzers`; the summary's
  `file_count == scanned + failed` identity lets a consumer prove every file
  was accounted for.
* **Locations say where the code really is.** With `copybook_paths`, every
  report dict's `"location"` counts lines of the expanded text; `scan_one`
  stamps a sibling `"origin": {"file", "line"}` from the expander's source
  map (`analysis.lint.stamp_report_origins`), and `CrossFileCloneMember`
  carries it as `origin_file`/`origin_line` (serialized as `"origin"`).
  Before 2026-09-27 a paragraph after a `COPY` reported the expanded line,
  and one inside a member claimed a line of the program file.

`ScanOptions` carries both layout knobs `parse_cobol` takes: `free_form`
(the lexer hint) and `preprocess_fixed` (`None` auto-detects, `True`/`False`
force or disable normalization). The second was missing before 2026-09-28,
so `scan --source-format fixed|free` silently auto-detected.

A file whose copybook expansion fails is NOT dropped -- it falls back to the
unexpanded parse, the same degradation `parse_files_with_copybooks` makes
above. The reason is kept as the file's `copybook_error`
(`FileScan.copybook_error`, serialized only when set): the unexpanded parse
is usually error-free -- a COPY statement parses without its member -- so
before 2026-09-28, when the fallback was a bare `pass`, such a file's
reports were indistinguishable from an expanded scan's. Copybook paths matter more here than they look: an unexpanded
program's WORKING-STORAGE is missing whatever its COPY members declare, so
`unused-variables` (and therefore `health`'s redundancy component, and
therefore the grade a portfolio table sorts on) would grade a program
against a record layout it cannot see.

Backs `cobol-parser scan` (see cli.md) and the COBOL Analyzer extension's
Analyze Workspace.

# See Also

* [parser.md](parser.md) — `CobolParser`/`parse_cobol` used per file
* [analysis.md](analysis.md) — the analyzers `scan` runs, and the paragraph
  fingerprints `cross_file_clone_groups` groups on
* [preprocessing.md](preprocessing.md) — `expand_copybooks` used by the
  copybook-aware entry point
