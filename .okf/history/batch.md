---
type: History
title: Batch Parsing history
description: Archived dated notes moved out of batch.md; not loaded by default.
tags: [history, batch]
timestamp: 2026-10-15T00:00:00Z
---

# Batch Parsing history

Archive of dated notes moved verbatim from [batch.md](../batch.md) on 2026-10-15, when the topic file was restructured to describe only the current state. Every still-valid behaviour, invariant and rationale in these notes is restated in present tense in the topic file; what remains here is the when and the before/after. Newest first. Links inside quoted text point at the topic files as they stood.

## `scan.py` copybook-expansion fallback (2026-09-28)

**Copybook expansion failure degrades, as in `batch.py`.** The file falls
back to the unexpanded parse and keeps the reason as
`FileScan.copybook_error` (the unexpanded parse is usually error-free, so
without it the reports would be indistinguishable from an expanded scan's;
until 2026-09-28 the fallback was a bare `pass`). Copybook paths matter more
than they look: an unexpanded program's WORKING-STORAGE is missing whatever
its COPY members declare, so `unused-variables` (and therefore `health`'s
redundancy component, and therefore the portfolio grade) would grade a
program against a record layout it cannot see.

## `parse_files_with_copybooks` fault isolation (2026-07-08 audit)

History: until the 2026-07-08 audit `parse_files_with_copybooks` caught only
`OSError` on the read and had no guard around `parser.parse(...)`, so one
bad file discarded every other file's result. Pinned by
`tests/integration/test_batch_coverage_gaps.py::TestParseFilesWithCopybooksParseException`
and `::TestParseFilesWithCopybooksDecodeError`.
