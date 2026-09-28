---
type: Module
title: JCL
description: z/OS Job Control Language front end — cards, jobs, steps, DD statements, in-stream procedures, and the ddname → dataset binding a COBOL SELECT resolves through.
tags: [jcl, zos, dd, dataset, job, step, proc, symbolic-parameters, bindings]
timestamp: 2026-09-15T00:00:00Z
---

# Overview

`cobolparser/jcl/` is the only part of this library that reads a language
other than COBOL. It exists for one join that nothing in the COBOL source can
make on its own:

```cobol
SELECT INV-FILE ASSIGN TO INVFILE.
```

`INVFILE` is a *DD name*. Which dataset it actually is, how it is disposed,
and what its RECFM/LRECL are, live in the JCL that runs the program — so a
COBOL toolchain that never reads JCL can only ever report the DD name back to
you. This package answers the rest.

**It shares no code with the COBOL lexer or parser.** JCL is a different
language with its own 80-column card format, its own continuation rule and its
own comment convention, and the package adds no runtime dependency.

Two properties hold throughout and are as much of the contract as the shapes
themselves:

* **A quiet result is never a complete one.** A card that cannot be parsed
  goes into `JclParseResult.errors` with its line and a reason. Anything read
  but not fully resolved — a symbolic parameter with no value, a procedure not
  defined in this file, an `INCLUDE` needing library access, a recognised but
  unmodelled statement kind — goes into `JclParseResult.unresolved`. No card is
  dropped and **no dataset name is ever guessed**.
* **Determinism.** The same input always produces a byte-identical `to_dict()`.

# Public API

```python
from cobolparser.jcl import parse_jcl, resolve_dd_bindings, bindings_for_ddname

result = parse_jcl(text, filename="JOB.jcl")     # JclParseResult
result = JclParser().parse_file("JOB.jcl")       # same, from a path

result.jobs[0].steps[0].program          # 'INVUPDT'
result.dd_map()["INVFILE"]               # ['PROD.INVENTORY.MASTER']
result.steps_running("INVUPDT")          # every step running that program
result.success                           # True when every card parsed
result.errors                            # [{line, message}, ...]
result.unresolved                        # what was read but not resolved

# The shape the rest of the toolchain consumes
for b in resolve_dd_bindings(result):
    b.ddname, b.dataset, b.step, b.job, b.disposition
    b.record_format, b.record_length     # when the JCL states them

bindings_for_ddname(result, "INVFILE")   # one DD name, case-insensitively
```

## Model (`jcl/models.py`)

| Class | Holds |
|-------|-------|
| `JclParseResult` | `jobs`, `procedures`, `symbols`, `errors`, `unresolved`, `filename` |
| `JclJob` | `name`, `steps`, `parameters`, job-level `dd_statements` (JOBLIB, JOBCAT), `line` |
| `JobStep` | `name`, `program`, `procedure`, `parm`, `dd_statements`, `condition`, `parameters`, `line` |
| `DDStatement` | `name`, `dataset`, `disposition`, `sysout`, `is_dummy`, `is_instream`, `instream_lines`, `concatenated`, `record_format`, `record_length`, `parameters`, `procstep`, `line` |
| `JclParameter` | `keyword`, `value`, `subparameters`, `positional` |
| `DatasetBinding` | `ddname`, `dataset`, `step`, `job`, `disposition`, `record_format`, `record_length` |

Every node is a plain dataclass with a `to_dict()` whose key order is fixed by
the literal that builds it, so `json.dumps(result.to_dict())` is byte-identical
for byte-identical input.

**`JclParameter` covers three shapes**, readable off the fields without
re-parsing: `DSN=MY.DATA` → `keyword`/`value`; `DISP=(NEW,CATLG,DELETE)` →
`positional`; `DCB=(RECFM=FB,LRECL=80)` → `subparameters`. A mixed sub-list
(`DCB=(MODEL.DSCB,RECFM=FB)`) fills both. `value` is always the text exactly as
coded, apostrophes included — use `unquote()` to read a quoted string's
content.

**`DDStatement.dataset` is `None` whenever no DSN was coded** — the normal case
for SYSOUT, DUMMY and in-stream data, which are flagged by
`sysout` / `is_dummy` / `is_instream` instead. It is never inferred. The value
keeps any member (`PDS(MEMBER)`), relative generation (`GDG(+1)`) or temporary
`&&` prefix as coded.

**Concatenations**: unnamed DD cards following a named one land in
`concatenated`, each repeating the owner's `name`, so a binding lookup on the
DD name finds every dataset in a multi-library STEPLIB. `flatten()` walks a
card and its members in card order.

### Query helpers

* `JclParseResult.all_dd_statements()` — every DD card paired with where it was
  coded, in job → step → card order; job-level cards come back with a `None`
  step, concatenated members follow their owner.
* `JclParseResult.dd_map()` — DD name → every dataset bound to it. **Every DD
  name seen is a key**: an empty list means "seen, but not backed by a dataset"
  (SYSOUT/DUMMY/in-stream), while a missing key means "not in this JCL at all".
* `JclParseResult.steps_running(program)` — includes steps produced by expanding
  an in-stream procedure, so a program run only from inside a PROC is found.
* `JclJob.step(name)` / `JobStep.dd(name)` / `DDStatement.parameter(keyword)` —
  all case-insensitive.

# Card scanning (`jcl/lexer.py`)

`scan_cards(text) -> ScanResult` produces one `JclCard` per **logical**
statement: continuation already joined, in-stream data already separated.

| Columns | Meaning |
|---------|---------|
| 1–2 | `//` identifier field (`//*` comment, `/*` delimiter) |
| 3 | first column of the name field; blank means "no name" |
| 3–72 | name, operation and parameter fields, blank-separated |
| 73–80 | identification/sequence field, **discarded before anything reads the card** |

Because columns 73–80 go first, a sequence-numbered deck parses identically to
an unnumbered one. Card kinds are `KIND_STATEMENT`, `KIND_COMMENT`,
`KIND_NULL`, `KIND_JES`.

## Continuation — the rule that is usually got wrong

The *current* card decides whether the next one continues it, in exactly two
situations:

1. **Its parameter field ends with a comma.** The next card must have `//` in
   columns 1–2, a blank in column 3, and its text must resume within columns
   4–16 (`CONTINUATION_MIN_COLUMN` / `CONTINUATION_MAX_COLUMN`).
2. **An apostrophe-quoted string is still open** when the card ends. The next
   card must have `//`, blanks through column 15, and the string resumes at
   column 16 (`STRING_CONTINUATION_COLUMN`) **verbatim, blanks included** —
   those blanks are inside the quoted string. The same holds on the card
   being continued: a continued string is coded through column 71
   (`STRING_LAST_COLUMN`), so blanks between the last character and column 71
   are part of the value even when the file has had trailing blanks stripped.

Anything else ends the statement. A card that promises continuation but is not
followed by a valid continuation card is reported as an error and the statement
is closed where it stands, so the *following* card is still parsed rather than
swallowed.

The parameter field ends at the first blank outside both quotes and
parentheses; the rest of the card is a comment. Blanks *inside* parentheses are
kept. `IF`/`ELSE`/`ENDIF` follow their own rule because their operand is a
relational expression, not a parameter list: `IF`'s expression runs, blanks
included, up to `THEN` — continued onto following cards (text in columns
4-16, a card opening with an operation word is never a continuation) until
`THEN` is found — and whatever follows `THEN` is a comment, so a comment
holding an apostrophe or ending in a comma no longer reads as a continuation.
`ELSE`/`ENDIF` take no operand; the rest of their card is a comment.

## In-stream data

`DD *` and `DD DATA` are followed by data, not JCL, and the scanner switches
modes so data is never parsed as JCL. `DD *` data ends at a delimiter card or
at the first card starting with `//` — unless it coded `DLM=`, in which case,
as on z/OS, only that delimiter ends it and `//` / `/*` cards are data;
`DD DATA` data ends **only** at the delimiter, which is `/*` (`DEFAULT_DELIMITER`) unless the DD coded `DLM=xx`.
Data lines attach to the DD that introduced them and are kept exactly as
written — full width, **not** truncated at column 72.

Helpers `split_top_level()` and `find_top_level_equals()` split a parameter
field without breaking inside quotes or parentheses.

# Parsing (`jcl/parser.py`)

`parse_jcl(text, *, filename="<jcl>")`, or `JclParser().parse()` /
`.parse_file()`.

Understood: `JOB`, `EXEC`, `DD`, `PROC`, `PEND`, `SET`, `INCLUDE`,
`IF`/`THEN`/`ELSE`/`ENDIF`, `JCLLIB`, `OUTPUT`, plus `//*` comments, the null
`//` end-of-job card and `/*` JES control cards.

**Procedure expansion is the load-bearing part.** `EXEC PGM=name` is a program
step; `EXEC procname` and `EXEC PROC=procname` are procedure steps. When the
procedure is defined in-stream in the same file its body is *expanded*: one
extra `JobStep` per procedure step is appended to the job, named
`invocation.procstep` — the same qualified form z/OS itself reports — carrying
the procedure's own `PGM=` and DD statements with this invocation's symbol
values substituted. That is what makes a `ddname -> dataset` lookup work for a
program run out of a procedure. Such a step has **both** `program` and
`procedure` set.

`procstep.ddname` DD cards coded on the invocation override the matching DD of
that procedure step *parameter by parameter* (and `DCB=` *sub-parameter by
sub-parameter*: overriding `DCB=(RECFM=FB,LRECL=80)` with `DCB=(LRECL=100)`
keeps `RECFM=FB`); a DD name the procedure step does not have is an addition. The invocation keeps its own copy of every override
card, so nothing is moved out of sight.

A concatenation is overridden by position: the unnamed cards following a
`procstep.ddname` override merge into the procedure's concatenated members in
order (a parameterless card leaves its member alone), extra cards are
additions, and members no override reaches stay exactly as coded.

`PARM` and `COND` coded on the invoking `EXEC` follow the z/OS rules too:
`PARM.procstep=` / `COND.procstep=` override that one procedure step (a
procstep the procedure does not have is noted in `unresolved`); unqualified
`COND=` overrides every step, while unqualified `PARM=` goes to the *first*
step and nullifies `PARM` on every later one. A `keyword.procstep` form of
any `EXEC_KEYWORDS` entry is never read as a symbolic override.

**Symbolic parameters** (`&SYM`, `&SYM.`) are substituted from `SET` values,
then procedure defaults, then `EXEC` overrides — increasing precedence. The
`SET` values a procedure sees are the ones in effect at its `EXEC` card; a
`SET` coded after it does not reach back into it.
`&&` is left alone (a temporary dataset name, not a symbol). Substitution is
deliberately **not** performed on the `JOB` card, matching z/OS, so
`NOTIFY=&SYSUID` does not read as an unresolved user symbol.
`EXEC_KEYWORDS` is the set of `EXEC` keywords that belong to the step itself;
anything else coded with a value on an `EXEC` is a symbolic override for the
procedure being invoked.

`JobStep.condition` carries `COND=` when coded, otherwise the text of the
enclosing `IF`/`ELSE` (`NOT (...)` inside an `ELSE`, nested conditions joined
with `AND`), otherwise `None`.

An unnamed `// PROC` header marks a **cataloged** procedure: its keywords seed
the symbolic defaults, and the JOB-less body is a note in `unresolved`, not an
error.

## What it deliberately does not do

Nothing reaches outside the file it was handed. A procedure not defined
in-stream is **not** searched for in a PROCLIB, an `INCLUDE` group is not
expanded, and `JCLLIB ORDER=` is recorded but not honoured — each lands in
`unresolved` naming what could not be resolved and why. `OUTPUT`,
`CNTL`/`ENDCNTL`, `COMMAND`, `XMIT`, `NOTIFY` and JES control cards are
recognised, kept out of the error list, and reported as not modelled
(`_UNMODELLED_OPERATIONS`). A DSN whose symbols could not all be resolved is
stored exactly as coded and reported in `unresolved`.

# Known gaps

* A **named** `PROC` with no `PEND` before EOF is reported as an error (the
  body is still stored and usable).
* **`DSN=*.step.ddname` backward references are not resolved** — the text is
  kept as coded and reported.

# DUMMY and overrides

`DUMMY` and `DSN=NULLFILE` both mark a DD `is_dummy` with `dataset=None`,
whatever DSN is also coded. `DSN`/`DSNAME`, `DUMMY`, `SYSOUT` and in-stream
data (`*` / `DATA`) are mutually exclusive: an overriding `procstep.ddname`
card that codes any of them drops whichever the procedure DD coded, so
`//S.IN DD DUMMY` really dummies out a procedure dataset (it used to leave
`IN -> A.B` in `dd_map()`), `//S.SYSIN DD *` replaces a procedure `DSN=`
(it used to keep it alongside the data), and a `DSN=` override of a
procedure `DD *` is no longer still flagged in-stream.
* Datasets are not resolved across *files*: a job that `INCLUDE`s a member or
  `EXEC`s a cataloged procedure from a PROCLIB gets an `unresolved` entry, not
  a lookup.

# CLI

```bash
cobol-parser jcl JOB.jcl                  # the whole job structure as JSON
cobol-parser jcl JOB.jcl --dd-map         # only ddname -> datasets
cobol-parser jcl JOB.jcl --bindings       # one row per DD binding
cobol-parser jcl JOB.jcl --program INVUPDT  # only steps running that program
cobol-parser jcl JOB.jcl --strict         # exit 3 when any card failed to parse
```

`jcl` is the only subcommand reading a language other than COBOL, so it shares
none of the COBOL parse flags — no `--dialect`, no `--source-format`, no
`--copybook-path`. `--strict`'s exit 3 is kept distinct from exit 1, which
still means the run itself failed. `--compact` and `-o` work as elsewhere.
See [cli.md](cli.md).

# Not yet joined to the codebase graph

`analysis/codebase.py` builds its cross-program graph from `ProgramNode` /
`CallEdge` / `CopyEdge` only, and does not read JCL. So today "which dataset
does this program's `INVFILE` resolve to" is answerable, but "which job
populates the dataset this program reads" is not — the two halves exist and are
simply not wired together. See [analysis.md](analysis.md).

# Tests

`tests/unit/test_jcl.py`.
