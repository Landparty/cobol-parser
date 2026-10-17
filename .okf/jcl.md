---
type: Module
title: JCL
description: The ddname -> dataset join a COBOL SELECT resolves through, read from z/OS JCL by the jcl-parser package; cobolparser.jcl is the adapter that shapes its model for this toolchain.
tags: [jcl, zos, dd, dataset, job, step, proc, bindings, jcl-parser]
timestamp: 2026-10-15T00:00:00Z
---

# JCL

`cobolparser/jcl/` exists for one join nothing in the COBOL source can make:

```cobol
SELECT INV-FILE ASSIGN TO INVFILE.
```

`INVFILE` is a *DD name*; which dataset it is, how it is disposed and what its
RECFM/LRECL are live in the JCL that runs the program.

**This package does not parse JCL.** The JCL is read by the sibling
**`jcl-parser`** package (`jclparser`), the same library the LegacyLens
backend uses. `cobolparser.jcl` converts its `Job` model into the
`JclParseResult` shape below and adds the bindings. JCL parsing fixes belong
in jcl-parser; this package has no card scanner or statement parser of its
own, and must not grow one.

Modules: `jcl/parser.py` (the adapter: `JclParser`, `parse_jcl`),
`jcl/models.py` (the dataclasses), `jcl/bindings.py` (DD name -> dataset),
`jcl/programs.py` (the program a launcher step runs: `run_programs(systsin)`
for IKJEFT01/1A/1B `RUN PROGRAM(x)`, `ims_program(parm)` for DFSRRC00
`PARM='DLI|DBB|BMP,x,...'`; pure text, shared with field lineage's
`lineage_jcl` so the two JCL consumers agree, #493).
Entry points: `parse_jcl(text, *, filename="<jcl>", proc_paths=None)`,
`JclParser(proc_paths=None).parse(text, *, filename=...)` / `.parse_file(path)`,
then `resolve_dd_bindings(result)`. CLI: `cobol-parser jcl` (below).

`jcl-parser` is an **optional extra**: `pip install 'cobol-parser[jcl]'`
(`jcl-parser>=2.0.0`; the `dev` extra pulls it too). The rest of the library
keeps its no-runtime-dependency rule. `cobolparser.jcl`'s models and bindings
import without it; `parse_jcl` raises `ImportError` naming the extra.
1.x releases of jcl-parser (compiled, pre-2.0 API) do not work.

Two properties hold throughout:

* **A quiet result is never a complete one.** What jclparser rejects lands in
  `JclParseResult.errors`; what it read but could not resolve lands in
  `unresolved` (see "What the adapter adds"). No dataset name is guessed.
* **Determinism.** The same input (and the same `proc_paths` contents) always
  produces a byte-identical `to_dict()`.

## Public API

```python
from cobolparser.jcl import parse_jcl, JclParser, resolve_dd_bindings, bindings_for_ddname

result = parse_jcl(text, filename="JOB.jcl", proc_paths=["proclib/"])
result = JclParser(proc_paths=["proclib/"]).parse_file("JOB.jcl")

result.jobs[0].steps[0].program          # 'INVUPDT'
result.dd_map()["INVFILE"]               # ['PROD.INVENTORY.MASTER']
result.steps_running("INVUPDT")          # includes steps expanded from PROCs
result.success                           # True when errors is empty (says nothing about unresolved)
result.errors                            # [{line, message}, ...]
result.unresolved                        # what was read but not resolved

for b in resolve_dd_bindings(result):
    b.ddname, b.dataset, b.step, b.job, b.disposition, b.record_format, b.record_length
bindings_for_ddname(result, "INVFILE")   # case-insensitive
```

Also exported: `unquote(text)` (strip JCL apostrophe quoting). Card-level
scanning (columns, continuations, top-level `=` splitting) is jcl-parser's job;
this package exposes none of it.

### Model (`jcl/models.py`)

| Class | Holds |
|-------|-------|
| `JclParseResult` | `jobs`, `procedures`, `symbols`, `errors`, `unresolved`, `filename` |
| `JclJob` | `name`, `steps`, `parameters`, job-level `dd_statements` (JOBLIB), `line` |
| `JobStep` | `name`, `program`, `procedure`, `parm`, `dd_statements`, `condition`, `parameters`, `line` |
| `DDStatement` | `name`, `dataset`, `disposition`, `sysout`, `is_dummy`, `is_instream`, `instream_lines`, `concatenated`, `record_format`, `record_length`, `parameters`, `procstep`, `line` |
| `JclParameter` | `keyword`, `value`, `subparameters`, `positional` |
| `DatasetBinding` | `ddname`, `dataset`, `step`, `job`, `disposition`, `record_format`, `record_length` |

Every class has `to_dict()`. Lookup helpers: `JclParseResult.dd_map()` (DD
name -> every dataset bound to it, across steps), `.steps_running(program)`
(`PGM=`, or the program a launcher runs: `JobStep.effective_programs()` --
every `RUN PROGRAM` of an in-stream IKJEFT01 SYSTSIN, the DFSRRC00 `PARM`
program),
`.all_dd_statements()` (`(job, step | None, dd)` triples, `step=None` for
job-level DDs); `JclJob.step(name)`, `JobStep.dd(name)` (both
case-insensitive); `DDStatement.flatten()` (the DD then its concatenated
members) and `.parameter(keyword)`.

### Bindings (`jcl/bindings.py`)

`resolve_dd_bindings(result)` emits one `DatasetBinding` per DD card,
exhaustive and ordered: job order, step order, card order, each concatenated
member right after the card that owns it, job-level DDs (JOBLIB, ...) first
with `step=""`. Steps expanded from a procedure appear under their
`invocation.procstep` names. SYSOUT / DUMMY / in-stream DDs yield
`dataset=None` rows, kept rather than dropped (knowing `SYSPRINT` is SYSOUT is
an answer). `bindings_for_ddname(result, ddname)` filters it
case-insensitively.

## Conversion (`jcl/parser.py`)

* **Steps.** `IF`/`ELSE` blocks are flattened; `JobStep.condition` is `COND=`
  when coded, else the enclosing conditions as jclparser keeps them
  (`(S1.RC = 0)`; in the ELSE `NOT (...)` around the whole expression; nested
  ones each parenthesised and joined with ` AND `). jclparser normalises
  unparenthesised expressions (`RC = 0` reads `RC=0`).
* **Procedure invocations** keep their own step (`program=None`,
  `procedure=NAME`, the invocation's override DDs with `procstep` set),
  followed by one step per procedure step, named `invocation.procstep` (nested:
  `RUN.S2.S1`), with both `program` and `procedure` (the innermost procedure)
  set. Each invocation is exploded on its own (`explode_job` over a one-step
  job), so one missing procedure does not stop the others.
* **Concatenations.** jclparser keeps unnamed DD cards as separate DDs named
  `""`; the adapter folds each into the `concatenated` list of the named DD
  ahead of it, repeating its name.
* **Parameters.** jclparser's dict values are turned back into
  `JclParameter`s: a list value becomes `positional` (items with `=` go to
  `subparameters`), `True` (`*`) a bare keyword, `_pos_N` a bare word. `value`
  is reconstructed, not the exact coded text (jclparser does not keep it).
  The JOB card's positionals (accounting information, programmer name) are
  the exception: jclparser drops their quotes, so they are read back from the
  merged JOB statement as coded (`'S DION'`, `1`, `(1,'X,Y')`).
* **Line numbers** are the deck's (each job's are offset by where it starts).
  Steps expanded from a *library* procedure carry the member's own line
  numbers.
* **`procedures`** maps each in-stream PROC to its steps expanded with its own
  defaults (names without the invocation prefix).

## What the adapter adds

* **Several jobs per deck.** jclparser reads one job (a second JOB card is a
  hard error), so the deck is split at each JOB card (named or not) that is not in-stream
  data (located with jclparser's own `_merge_source_lines`, a private helper,
  hence the `>=2.0.0` floor). Each job is parsed on its own; SET symbols and
  in-stream PROCs do not cross jobs. A PROC coded before the first JOB card is
  visible to every job, with its own (file) line numbers.
* **Card-level recovery.** jclparser raises on the first card it cannot read;
  the adapter records `{line, message}`, blanks that card and re-reads (up to
  `JclParser.MAX_RECOVERIES` = 50 times per job), so one bad card costs one
  card.
* **Procedure libraries, no guessing.** Lookup order: in-stream, then
  `proc_paths` (directories; one member per file named after it, any
  extension, first directory wins; the member name is what `EXEC` resolves,
  whatever the member's PROC label says, and a member with no PROC statement
  is its own body; each member is read once per parse), else the invocation
  is kept unexpanded and
  noted (`PROC NAME (line N): ... neither defined in this file nor found on the
  procedure path`). `INCLUDE MEMBER=` reads from the same directories.
  jclparser's bundled IBM-utility PROC templates, `JCLLIB ORDER` library
  lookup and the `JCL_PROCLIB_PATH` environment variable are **not** used.
* **Notes in `unresolved`:** every jclparser warning (unmatched ELSE/ENDIF,
  missing PEND, unrecognised statements, override naming no step, a symbol
  substituted with nothing, ...); a DSN still holding `&SYM`; a backward
  reference `DSN=*.step.dd`; a non-numeric LRECL; an IKJEFT01/1A/1B
  `SYSTSIN` that is a dataset (the programs it runs are unknown, so
  `steps_running` cannot see them); a PROC defined twice in one
  job (EXEC runs the last definition); a member with no JOB card. A JOB card
  with no name is an error.

### Known gaps

jcl-parser does not report these at all: IF without THEN, a continuation card in the wrong
columns or missing, `DD DATA` / `DLM=` data never terminated, SET with no
operands, positional parameters on EXEC, a nameless DD with nothing to
concatenate to, nested PROC definitions and PEND without PROC. A quoted string
continued from a trailing-blank-stripped card loses the blanks up to column 71
(`PARM='ABC` + `DEF'` reads `ABCDEF`). These are jcl-parser's to fix.

## CLI

```bash
cobol-parser jcl JOB.jcl                          # the whole job structure
cobol-parser jcl JOB.jcl --dd-map                 # ddname -> datasets
cobol-parser jcl JOB.jcl --bindings               # one row per binding
cobol-parser jcl JOB.jcl --program INVUPDT        # only steps running it
cobol-parser jcl JOB.jcl --proc-path proclib/     # expand cataloged PROCs
cobol-parser jcl JOB.jcl --strict                 # exit 3 on any error
```

See [cli.md](cli.md).

## Other JCL consumers

* **Field lineage reads jcl-parser directly, not through this package.**
  `analysis/lineage_jcl.py` (`load_jobs`, `jobs_from_sources`,
  `bindings_from_jobs`) is duck-typed over jclparser's own `Job` model and
  produces `lineage_graph.DatasetBinding` / `Passthrough` objects — a
  *different* `DatasetBinding` class from `cobolparser.jcl.models.DatasetBinding`
  — plus utility pass-throughs (DFSORT/ICEMAN, IEBGENER, IDCAMS REPRO,
  IKJEFT01 `RUN PROGRAM`, DFSRRC00). Backs `field-impact --jcl`. See
  [analysis.md](analysis.md) (field lineage); tests in
  `tests/unit/analysis/test_lineage_jcl.py`.
* **Not joined to the codebase graph.** `analysis/codebase.py` has no job,
  step or dataset node, so `codebase-graph` cannot answer "which job
  populates the dataset this program reads"; only field lineage joins
  programs through datasets.

## Tests

`tests/unit/test_jcl.py` (the shape and semantics through the adapter),
`tests/regression/test_issue_493_jcl_program_under_launchers.py` (programs
under IKJEFT01 / DFSRRC00, `--program` matching nothing),
`tests/unit/test_jcl_adapter.py` (what the adapter adds), the CLI in
`tests/unit/cli/test_jcl_cli.py`, and `tests/unit/test_bug_hunt_r11_jcl_config.py`.
Sample decks: `tests/samples/jcl/` (`invupdt.jcl`, `payproc.jcl`).

## See also

* [cli.md](cli.md) — the `jcl` subcommand
* [analysis.md](analysis.md) — field lineage, which reads jcl-parser directly (`lineage_jcl.py`)
* [history](history/jcl.md) — archived dated notes (the in-repo JCL scanner that jcl-parser replaced)
