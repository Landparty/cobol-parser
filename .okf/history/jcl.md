---
type: History
title: JCL history
description: Archived dated notes moved out of jcl.md; not loaded by default.
tags: [history, jcl]
timestamp: 2026-10-15T00:00:00Z
---

# JCL history

Archive of dated notes moved verbatim from [jcl.md](../jcl.md) on 2026-10-15, when the topic file was restructured to describe only the current state. Every still-valid behaviour, invariant and rationale in these notes is restated in present tense in the topic file; what remains here is the when and the before/after. Newest first. Links inside quoted text point at the topic files as they stood.

## In-repo JCL scanner replaced by jcl-parser (2026-10-08)

**This package does not parse JCL.** The JCL is read by the sibling
**`jcl-parser`** package (`jclparser`), the same library the LegacyLens
backend uses. `cobolparser.jcl` converts its `Job` model into the
`JclParseResult` shape below and adds the bindings. JCL parsing fixes belong
in jcl-parser. (Until 2026-10-08 this package carried its own ~1,800-line card
scanner and statement parser, `jcl/lexer.py` and the old `jcl/parser.py`;
that copy is gone.)

Also exported: `unquote(text)` (strip JCL apostrophe quoting). The card-level
helpers of the old scanner (`scan_cards`, `JclCard`, `ScanResult`,
`split_top_level`, `find_top_level_equals`, the column constants) and
`EXEC_KEYWORDS` no longer exist.

## Known gaps (jcl-parser is silent, the old scanner was not)

Not reported at all now: IF without THEN, a continuation card in the wrong
columns or missing, `DD DATA` / `DLM=` data never terminated, SET with no
operands, positional parameters on EXEC, a nameless DD with nothing to
concatenate to, nested PROC definitions and PEND without PROC. A quoted string
continued from a trailing-blank-stripped card loses the blanks up to column 71
(`PARM='ABC` + `DEF'` reads `ABCDEF`). These are jcl-parser's to fix.
