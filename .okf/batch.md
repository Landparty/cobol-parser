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
  degradation is observable rather than silent.

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

# See Also

* [parser.md](parser.md) — `CobolParser`/`parse_cobol` used per file
* [preprocessing.md](preprocessing.md) — `expand_copybooks` used by the
  copybook-aware entry point
