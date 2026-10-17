---
type: Module
title: Codebase and Interface Analyzers
description: Cross-program and program-comparison analyzers -- CodebaseGraphBuilder / CopybookImpactAnalyzer (codebase.py, the CALL/COPY graph over a whole tree), ProgramSignatureExtractor (program_signature.py, what a callee expects from its callers), and ProgramDiffer (ast_diff.py, behaviour-level diff of two ASTs); plus a pointer to the JCL adapter.
tags: [analysis, codebase-graph, copybook-impact, program-signature, ast-diff, call-graph]
timestamp: 2026-10-15T00:00:00Z
---

# Codebase and Interface Analyzers

The analyzers that look beyond one program's internals: the call and copy
graph of a whole source tree and the impact of changing a copybook
(`CodebaseGraphBuilder`, `CopybookImpactAnalyzer`), the calling interface a
program offers to *other* programs (`ProgramSignatureExtractor`), and what
changed in a program's behaviour between two versions (`ProgramDiffer`). Entry
points: `CodebaseGraphBuilder(...).build_from_directory(root)`,
`ProgramSignatureExtractor().analyze(ast)` / `extract_signatures(ast)`,
`ProgramDiffer().diff(old_ast, new_ast)`. Field-level cross-program impact is
in [lineage.md](lineage.md).

## Contents

* [CodebaseGraphBuilder / CopybookImpactAnalyzer](#codebasegraphbuilder--copybookimpactanalyzer)
* [ProgramSignatureExtractor](#programsignatureextractor)
* [ProgramDiffer](#programdiffer)
* [JCL](#jcl)
* [See also](#see-also)

## CodebaseGraphBuilder / CopybookImpactAnalyzer

The cross-program module. It walks a whole tree of COBOL source, parses every
file through `batch.py` (parallel, per-file fault isolation) and aggregates the
results into one graph with two kinds of edge:

* **Call edges** — `program A calls program B`, from static `CALL "B"` and from
  dynamic `CALL WS-TARGET` resolved through `DynamicCallAnalyzer`. A dynamic
  call whose value set that analyzer could not fully resolve still contributes
  its known targets, each marked `resolved=False`, so the edge set is never
  mistaken for an exhaustive one. `EXEC CICS LINK PROGRAM(...)` and `EXEC
  CICS XCTL PROGRAM(...)` are call edges too (#315), told apart by
  `CallEdge.kind` (`call` / `cics-link` / `cics-xctl`; `to_dict()` carries
  it). `PROGRAM('X')` is static (read off `ExecCicsStatement.literal_options`,
  since `options` holds literals unquoted); `PROGRAM(WS-X)` takes
  `DynamicCallAnalyzer.resolve_variable("WS-X")`, the same values and
  incomplete flag `CALL WS-X` would get, or is reported in `unresolved`.
  `cycles()` skips XCTL edges: XCTL never returns, so a menu loop of XCTLs is
  not recursion; LINK cycles count. Chosen over a separate `transfer_edges`
  list so `callers_of` and impact questions see CICS callers with no change.
* **Copy edges** — `program A copies member X`, and `member X copies member Y`
  for nested copybooks. Collected by **re-scanning** each source with
  `extract_copy_statements()` rather than from an expanded parse, because
  expansion *consumes* the COPY statement and discards exactly the edge we are
  after. Members resolve to real files through the same `PathResolver` the
  expander uses, and with the member **as written** (`statement.member_name`,
  `_resolve_member(..., written=...)`), not the upper-cased basename that is
  the graph key -- `COPY ordrec.` on a case-sensitive filesystem and
  `COPY "sub/REC.cpy"` were unresolved here while the expander inlined them
  (#580). A nested chain is followed to its leaves and a circular pair
  (`A COPY B`, `B COPY A`) is reported, not looped on.
  A DB2 `EXEC SQL INCLUDE X END-EXEC` is a copy edge too (the scan passes
  `sql_include=True`), with the same `COPY` label and the same unresolved-member
  reporting as a COPY -- it is how SQLCA and DCLGEN members are normally pulled
  in, and `copybook-impact` on a DCLGEN returned nothing without it (#295).
  Nothing in the JSON/DOT/Mermaid output tells a COPY edge from an INCLUDE
  edge. An INCLUDE of `SQLCA` / `SQLDA` (`_PRECOMPILER_MEMBERS`) that is not on
  the path keeps its edge but adds no `unresolved` note. That is narrower than
  the expander, which skips *every* unresolvable INCLUDE silently: here a COPY
  of either, or an INCLUDE of any other missing member (a DCLGEN), is still
  reported -- once per member and referrer, even when one file both COPYs and
  INCLUDEs it.

```python
from cobolparser.analysis.codebase import CodebaseGraphBuilder, CopybookImpactAnalyzer

builder = CodebaseGraphBuilder(copybook_paths=["./copybooks"])   # also workers=, chunk_size=200,
                                                        # encoding="utf-8", debug_lines=False
graph = builder.build_from_directory("./src", extensions=(".cbl", "cob"))
graph = builder.build(["a.cbl", "b.cbl"])       # or an explicit file list

graph.program_ids / graph.members
graph.callers_of("VALIDATE") / graph.callees_of("MAIN")
graph.programs_using("CUSTREC", transitive=True)   # through nested COPY chains
graph.cycles()                                     # CALL cycles
graph.to_dict() / graph.to_dot() / graph.to_mermaid()
graph.unresolved / graph.errors
graph.programs / graph.call_edges / graph.copy_edges   # the raw dataclass fields

report = CopybookImpactAnalyzer(graph).analyze("CUSTREC")   # ImpactReport
report.direct_programs / report.transitive_programs
report.chains          # the COPY nesting path to each affected program
report.fields          # data items the member contributes, when its file resolved
report.program_count
```

`ProgramNode` holds `program_id` (uppercased; the **file stem** when the file
would not parse, recorded as such in `unresolved`), `path`, `calls`, `copies`
and `parse_failed` — with `parse_failed` true, `calls` is "empty and unknown",
not "empty and known". `CallEdge` carries `is_dynamic` / `resolved` / `kind`; `CopyEdge`
carries `member`, `path` and `nested`, where for a nested edge `program` is the
*outer member name*, which is what makes a `PROG1 -> OUTER -> INNER` chain
walkable in either direction.

**Library-qualified COPY (#351).** `COPY REC OF LIBA` and `COPY REC IN LIBB`
are two different files, so the builder's caches are keyed by more than the
member name: `_member_paths` / `_member_failures` on `(member as written,
library)`, and `_member_copies` on the resolved file path (its entries carry
the written spelling too, #580). A nested COPY is resolved with its
own `library_qualifier`, as the expander does. `CopyEdge` carries `library`
(the qualifier as written, case kept) and, for a nested edge, `parent_path` --
the outer member's file. `programs_using()` and `CopybookImpactAnalyzer` walk
up *edge by edge* (`CopyEdge._is_parent`: same name, and same file whenever the nested
edge has a `parent_path`), so `LIBB/REC -> INNER` reaches only the programs
whose `REC` resolved to `LIBB/REC.cpy` -- never a program whose `REC` did not
resolve at all. A hand-built nested edge with no `parent_path` matches by name
alone. `ImpactReport.paths`
lists every file the member name resolved to; with more than one, `fields` is
their union and `unresolved` says so. The DOT/Mermaid renderings still draw
one node per member *name*, and draw each `(program, member, nested)` edge once
(`_rendered_copy_edges`), however many files sit behind it.

Two rules hold throughout:

1. **A quiet report is never a complete one.** A file that would not parse lands
   in `errors` and still contributes its COPY edges (the COPY scan does not need
   a successful parse); a COPY whose member is off the search path, a dynamic
   CALL with no resolvable target, a duplicate `PROGRAM-ID`, a file holding
   several units — each lands in `unresolved` with a reason. So does a
   `copybook-impact` member whose data items are named by IBM `:TAG:`
   REPLACING placeholders (`05 :Q:-AMT ...`, #356): their real names exist
   only once a `COPY ... REPLACING` fills the tag in, so they are left out of
   `fields` (the record parser renames them `ANONYMOUS-*`, which the
   declared-in-the-member filter drops) and named in `unresolved` instead of
   vanishing.
2. **Determinism.** The same tree produces byte-identical `to_dict()`,
   `to_dot()` and `to_mermaid()`. Files are parsed in sorted order, every
   emitted list is sorted, and no `ProcessPoolExecutor` completion order reaches
   the output.

Paths are keyed by `str(Path(p))` — the spelling `BatchResult.path` returns — so
`./X.cbl` matches its parsed units instead of yielding a phantom program.
Extensions are accepted with or without a leading dot (`extensions` is
keyword-only, defaulting to `DEFAULT_PROGRAM_EXTENSIONS`). `_member_paths` /
`_member_copies` reset per build. `build_from_directory` raises
`NotADirectoryError` for a root that is not a directory — a mistyped root must
not read as "a codebase with no programs".

`build_from_results(paths, results)` is `build()` without the parse: the
caller hands one `BatchResult` per path (an iterable, consumed one at a time,
so a generator keeps one AST live). The MCP server's `programs` index feeds
it its own parses ([../mcp.md](../mcp.md)). `CodebaseGraph.copy_sites` (file
-> `(member, line)` of each COPY / EXEC SQL INCLUDE written in a program
file, source order) records the COPY scan's lines; it is not in `to_dict()`.

Backs the `codebase-graph` and `copybook-impact` CLI subcommands. Tests:
`tests/unit/analysis/test_codebase.py`.

**Not yet joined to JCL.** The graph has `ProgramNode` / `CallEdge` / `CopyEdge`
and no job, step or dataset node, while `cobolparser/jcl/` already resolves
DD → dataset and step → program. So "which dataset does this program's INVFILE
resolve to" is answerable and "which job populates the dataset this program
reads" is not. See [jcl.md](../jcl.md).

## ProgramSignatureExtractor

Every other program-scoped analyzer here answers a question about the program
it is given. This one answers a question about the program *someone else* is
calling: given `CALL "SUBPGM" USING ...`, what does SUBPGM actually expect —
how many operands, in what order, of what shape, and which of them it writes
back.

That is why `LinkageChecker` cannot cover it: that analyzer correlates CALL
statements against ENTRY statements *in the same source unit*, and on a real
mainframe a caller and its callee almost never share a file. The answer has to
be extracted from the callee and carried across, which is what this module
produces — a small, serializable, source-file-independent description.

Built from three sources that must agree and often do not:

1. `PROCEDURE DIVISION USING` — the primary (implicit) entry point, read from
   the division's `using_parameters` metadata (same place `LinkageChecker`
   reads).
2. `ENTRY "NAME" USING` statements — alternate entry points, each with its own
   operand list.
3. The LINKAGE SECTION — where those operands are declared, and therefore the
   only place a parameter's *shape* lives (PICTURE, USAGE, byte length, group).

```python
from cobolparser.analysis.program_signature import (
    ProgramSignatureExtractor, extract_signatures,
)

sig = ProgramSignatureExtractor().analyze(ast)      # ProgramSignature
sigs = extract_signatures(ast)                      # one per program_units()

sig.primary                     # the PROCEDURE DIVISION entry — what CALL "PROG"
                                # hits; None when it has no USING clause
sig.entry("ALTENTRY")           # look one up, case-insensitively
sig.entry_points[0].call_example()   # 'CALL "SUBPGM" USING WS-A, WS-B RETURNING WS-RC'
sig.entry_points[0].returning        # PROCEDURE DIVISION ... RETURNING operand
sig.undeclared_parameters       # named by USING, absent from LINKAGE
sig.unreferenced_linkage        # LINKAGE 01-items no USING clause names
sig.unchecked                   # what could not be determined exactly
```

`SignatureParameter` carries `name`, `position`, `declared`, `level`,
`picture`, `usage`, `byte_length`, `is_group`, `occurs`, `direction`,
`by_clause`, `location`, and a `declaration()` rendering the operand as a
caller would have to write it (a group item is described by level and length
rather than a fabricated picture). `EntryPoint.kind` is `"procedure-division"`
or `"entry-statement"`. `by_clause` is the callee's declared passing mode
(`"REFERENCE"` / `"VALUE"`, from the division's `using_parameter_modes`
metadata) on the primary entry, and from `EntryStatement.parameter_modes` on
an ENTRY statement's operands (see #402);
`call_example()` writes a `BY VALUE` / `BY REFERENCE` phrase only where the
mode changes (`CALL "E1" USING LK-A, BY VALUE LK-B RETURNING LK-R`). The
RETURNING item counts as named, so it is never `unreferenced_linkage`.

**Direction is graded, never guessed.** It comes from how the PROCEDURE
DIVISION uses each parameter, reusing xref's role vocabulary:

* `write` plus any read → `input-output`.
* A reference as a BY REFERENCE CALL argument or SQL host variable
  (`_AMBIGUOUS_ROLES`), with no write elsewhere → `unknown`, and listed in
  `unchecked`. A `BY CONTENT` / `BY VALUE` CALL argument is not ambiguous:
  the callee gets a copy, so xref records it `read` (as `call-argument` it
  would grade a parameter only passed on BY CONTENT `unknown`). A caller told
  "input-only" about a
  field the callee overwrites has been told something worse than nothing.
  xref files `ENTRY "X" USING p` itself under the CALL-argument role
  (`statement == "EntryStatement"`); those refs are dropped before grading,
  since naming an entry's own parameter neither reads nor writes it.
* A group whose fields xref reports as duplicated → `unknown`, rather than
  inferred from a same-named WORKING-STORAGE field.

Operand *order* is preserved verbatim from the USING clause and is sorted
nowhere in the module — it is the whole point of `call_example()`.

A parameter named in (1)/(2) but absent from (3) is `undeclared_parameters`
(a caller passing one is passing into nothing); a LINKAGE 01-item named by
neither is `unreferenced_linkage` (not an error on its own — `SET ADDRESS OF`
is legitimate — but the other half of the mismatch picture). ENTRY statements
belonging to *contained* programs are not the outer unit's.

The `program-signature` CLI subcommand reports **every** unit in the file by
default rather than the outermost: a caller may target a contained program as
readily as the outer one, and reporting only the outermost would hide the other
entry points from exactly the consumer that needs them. `--program` still
narrows. Tests: `tests/unit/analysis/test_program_signature.py`.

## ProgramDiffer

A line-based `diff` over COBOL answers "what lines moved", which is almost never
the question: COBOL is column-sensitive, so a reformat, a renumbered sequence
area or a re-indented Area B shifts every line without changing anything the
program does. This module answers the other question — *what changed in the
program's behavior* — by comparing two `CobolProgram` ASTs into a flat, sorted
`DiffChange` list.

```python
from cobolparser.analysis.ast_diff import ProgramDiffer

report = ProgramDiffer(rename_threshold=0.8).diff(old_ast, new_ast)
report.changes                  # sorted list[DiffChange]
report.changes_by_category()    # "program" | "file" | "data" | "procedure"
report.counts_by_kind()
report.to_text()                # the +/-/~ summary behind --format text
report.caveats                  # what could not be compared exactly
```

`DiffChange`: `kind`, `category`, `symbol`, `detail`, `old`, `new`,
`old_location`, `new_location`, and a `sign` property (`+` for `*-added`, `-`
for `*-removed`, `~` otherwise).

**What is compared.** Program level (`PROGRAM-ID`, which divisions exist, the
`PROCEDURE DIVISION USING` interface); files (per `SELECT`/`FD` name:
ORGANIZATION, ACCESS MODE, RECORD KEY, ALTERNATE keys, RELATIVE KEY, FILE
STATUS, ASSIGN, OPTIONAL, plus the FD's presence, record size, recording mode
and FD-vs-SD kind); data items keyed by section plus qualified path
(`WORKING-STORAGE:WS-TAB.WS-ENT` — PICTURE/USAGE/level/VALUE/OCCURS/REDEFINES
plus the SIGN / JUSTIFIED / SYNCHRONIZED / BLANK WHEN ZERO / EXTERNAL / GLOBAL
flags and level-88 names and values — an entry with no data-name, which the
parser names `ANONYMOUS-<level>-<line>`, is keyed as a positional `FILLER`,
so a line shift does not report it removed and re-added);
procedures (added, removed, renamed,
**moved** — reordered without a body change, reported separately so a pure
reshuffle never reads as a rewrite — and body-changed); and statements within
matched paragraphs.

**Matching, in three stages**, each looking only at what the previous left over:

1. **By name**, case-insensitively (`Main-Para` *is* `MAIN-PARA`). Settles the
   overwhelming majority.
2. **By structural similarity.** Each leftover paragraph/section reduces to a
   *fingerprint* — the ordered sequence of statement kinds plus primary
   operands, nested branch bodies flattened in and tagged by branch (`IF/THEN`,
   `EVALUATE/WHEN2`, `READ/AT-END`). Pairs are scored with
   `difflib.SequenceMatcher`, considered best-score-first (ties broken by name,
   so the result never depends on dict or set ordering) and greedily paired at
   or above `rename_threshold` (default 0.8). An identical fingerprint under a
   different name is a **rename**, not an add plus a remove.
3. Whatever is still unmatched is a genuine add or remove.

Two deliberate refusals in stage 2: an **empty body never rename-matches**
(`SequenceMatcher` happily scores two empty sequences 1.0, and two paragraphs
that both contain nothing are evidence of nothing), and a **below-threshold pair
is reported as remove + add, never as a speculative rename** — an add+remove for
a rename is honest and easy to read past, a wrong rename actively misleads. The
near-miss is not discarded: it goes to `caveats` with its score, so a reader can
see the pair was considered and declined.

**Positions are relative order, not line numbers.** Matched procedures from both
sides run through `SequenceMatcher` and only those outside its matching blocks
are reported moved — so inserting one paragraph at the top does not report every
following paragraph as moved, and a pure reformat reports nothing at all.

**Spellings are not changes.** A PICTURE is compared by
its character positions, repeat factors written out (`_picture_positions`:
`X(2)` = `XX`, `S9(3)V9(2)` = `S999V99`), and a USAGE by its storage format
(`_canonical_usage`, the `_storage.py` synonym sets: `COMP` = `BINARY` =
`COMP-4` = `COMPUTATIONAL`, `COMP-3` = `PACKED-DECIMAL`). `COMP-5` stays
distinct from `COMP` (no truncation to the PICTURE). The change still reports
both strings as coded. A VALUE is still compared as written (`+12` vs `12`,
`'AB'` vs `'AB  '` on `PIC X(4)` read as changes).

Statement comparison has dedicated signatures for MOVE, PERFORM, CALL, GO TO,
IF, EVALUATE, SEARCH, OPEN, EXEC SQL, EXEC CICS, COMPUTE,
INSPECT, UNSTRING, ACCEPT and DISPLAY. **Every other statement compares on its
operands, its rendered text *and* its own `to_dict()` fields** (locations and
nested statement bodies stripped — those are compared on their own), so an
unmodelled edit over-reports rather than reading as unchanged. The rendered
text alone is not enough: it is a truncated summary that omits STRING's INTO,
READ's INTO/KEY, WRITE's FROM, ..., so `STRING ... INTO A` → `INTO B` would
diff as no change.

The dedicated signatures carry the markers a value alone hides (#316): CALL
includes `is_dynamic` (`CALL 'X'` → `CALL X` is a `call-target-changed`, and
the detail text quotes a static target), and UNSTRING includes
`delimiter_all` (`DELIMITED BY ALL ','`) with a detail text spelling out
source, delimiters and INTO targets. (WHEN selectors carry theirs via
`_selector_text`'s `FIG:` / `ID:` / quoted renderings, #313.)

Determinism: the same pair always produces byte-identical `to_dict()` — changes
sorted by category, symbol, kind then remaining fields (`_sort_key` is a total
order); caveats deduplicated and sorted; no set iterated without sorting.

Anything not compared exactly goes to `caveats`: a contained program unit, an
unrecognised nested clause, REPORT SECTION group clauses, level-66 RENAMES,
ENVIRONMENT/IDENTIFICATION content beyond the above, a duplicate procedure name,
a near-miss rename. Tests: `tests/unit/analysis/test_ast_diff.py`.

A `WHEN` selector's text carries the parser's markers (see #313):
`FIG:SPACES` for a figurative constant, `ID:WS-B` for a data name,
`Literal:'SPACES'` for a quoted literal. The values alone are identical
once the lexer strips quotes, so without the markers `WHEN SPACES` ->
`WHEN 'SPACES'` would diff as "No structural changes".

**Known gaps**: statements outside any named paragraph are not compared, and
neither are contained programs (`diff` has no `--program` flag yet) — both are
recorded as caveats rather than silently skipped.

## JCL

The `ddname -> dataset` binding a COBOL `SELECT ... ASSIGN TO` resolves
through, read from z/OS JCL by the `jcl-parser` package (optional extra
`cobol-parser[jcl]`); `cobolparser.jcl` is the adapter. It is not an analyzer
and shares no code with the COBOL pipeline; it has its own OKF file:
**[jcl.md](../jcl.md)**.
The codebase graph is not joined to it: see "Not yet joined to JCL" above.

## See also

* [../analysis.md](../analysis.md) -- routing page, calling conventions, module map
* [lineage.md](lineage.md) -- field-level impact across programs, datasets and tables
* [data-use.md](data-use.md) -- `LinkageChecker` (same-source CALL/ENTRY
  checks), `XrefAnalyzer` roles, `DynamicCallAnalyzer` and `_names.callee_names`
* [../batch.md](../batch.md) -- `parse_files`, which the graph builder uses
* [../preprocessing.md](../preprocessing.md) -- `extract_copy_statements`,
  `PathResolver`
* [../jcl.md](../jcl.md) -- DD → dataset bindings
* [../cli.md](../cli.md) -- `codebase-graph`, `copybook-impact`,
  `program-signature`, `diff`
* [history](../history/analysis.md) -- archived dated notes
