---
type: Module
title: Field Lineage
description: Field-level data lineage -- FieldFlowAnalyzer (field_lineage.py, one program's value-flow graph between data items and ports), LineageGraph (lineage_graph.py, cross-program joins through datasets, CALL arguments and DB2 columns, impact queries), lineage_jcl.py (DD bindings from jcl-parser jobs) and _sql_flow.py (embedded SQL host variable <-> column flows).
tags: [analysis, field-lineage, lineage-graph, impact, jcl, sql-flow, ports]
timestamp: 2026-10-16T00:00:00Z
---

# Field Lineage

Answers "if I change this field, what else changes?" at field granularity,
across programs, in two layers: `FieldFlowAnalyzer().analyze(ast)` builds one
program's may-flow value graph between data items and *ports* (files, CALL
arguments, linkage, SQL columns, console), and `LineageGraph(reports,
bindings, passthroughs)` joins many programs' reports and answers impact
queries. DD-to-dataset bindings come from JCL via `lineage_jcl.py`. Backs the
`lineage` and `field-impact` CLI subcommands and `scan --analyzer lineage`.
Start with [API](#api), then the layer you need.

## API

```python
from cobolparser.analysis.field_lineage import FieldFlowAnalyzer
from cobolparser.analysis.lineage_graph import LineageGraph
from cobolparser.analysis.lineage_jcl import bindings_from_jobs, load_jobs

flow = FieldFlowAnalyzer().analyze(ast)   # FieldFlowReport: program_id/items/ports/
                                          # edges/summary/key_uses/caveats
jobs, errors = load_jobs(["JOB1.jcl"], proc_path="procs/")
bindings, passthroughs = bindings_from_jobs(jobs)
graph = LineageGraph([flow, ...], bindings, passthroughs)
hits = graph.impact("CUST-ID", program="PROG1", direction="forward", depth=None)
graph.impact_table("CUSTOMER.CUST_ID") / graph.impact_dataset("PROD.CUST.MASTER")
graph.key_relationships() / graph.join_edges() / graph.join_state()
```

## Layer 1: one program

**Layer 1 -- one program (`FieldFlowAnalyzer`).** A may-flow,
flow-insensitive value graph. Nodes are data items (qualified name, with
the record-relative byte offset/length `layout_offsets` computes) and
*ports*, where a value enters or leaves the program:

| Port kind | Key | From |
|-----------|-----|------|
| `file` | DD name (`normalize_ddname`: `UT-S-` / `S-` prefixes stripped, the backend's rule) | READ / WRITE / REWRITE / RELEASE / RETURN / SORT-MERGE USING-GIVING, one byte range per record field; Report Writer GENERATE / TERMINATE: the `SOURCE` / `SUM` operands of the printed groups (the GENERATEd DETAIL group plus every non-DETAIL group of its report -- headings, footings and control breaks can fire at any GENERATE), offset-less and inexact (`_visit_report_writer`, #499) |
| `call` | `CALLEE#n`, `CALLEE#RETURNING` | CALL USING (BY REFERENCE goes both ways, except a `FUNCTION ...` argument: a temporary, so it only goes in, #579); a dynamic CALL fans out over `DynamicCallAnalyzer`'s candidates (run inside `analyze`; SPACES / LOW-VALUES / HIGH-VALUES / ZERO candidates are the "no program" sentinel and are dropped by `_names.callee_names`), else `?IDENT#n` plus a caveat |
| `linkage` | `PROGRAM#n` / `ENTRY#n`, `PROGRAM#RETURNING` (out only) | PROCEDURE DIVISION USING / RETURNING, via `ProgramSignatureExtractor`; the edge's line is the entry point's own (the USING line, or the ENTRY statement), not the program's first line |
| `sql` | `[SCHEMA.]TABLE.COLUMN` | `_sql_flow.analyze_sql` (SELECT INTO, FETCH through its DECLARE CURSOR, INSERT, UPDATE SET; MERGE/CTE are caveats, as is a FROM sub-select or a `TABLE(...)` table function -- matched on `TABLE` followed by `(`, so an ordinary table named `TABLE_CUST` / `TABLES_CFG` is traced, #340) |
| `console` | `SYSIN` / `SYSOUT` (or the ACCEPT's `FROM` source) | ACCEPT / DISPLAY; `ACCEPT FROM DATE` / `DAY` / `DAY-OF-WEEK` / `TIME` (with or without a format qualifier) make no port -- the runtime's clock, not data entering the program |

Edge kinds: `move` (group MOVE is a byte overlay; CORRESPONDING pairs by
name; literal reference modification narrows the range; a non-literal
start or length -- `REC(WS-POS:10)` -- is `_Ref.loose_window`: the operand
reaches every field under it, every pair inexact (`_pieces` marks its
pieces inexact, so STRING / DISPLAY / arithmetic operands too), with a
caveat naming it, #527 -- it used to be read as `REC(1:10)`), `arith`,
`string`, `init`, `set`, `aggregate` / `sql-expr` (SQL `SUM(...)` /
expressions), `read`, `write`, `redefines` (two-way, including several 01
records under one FD, and the records of every file one `I-O-CONTROL. SAME
RECORD AREA` clause names, #497 -- one buffer across FDs), `occurrence` (two-way, inexact: a literal-subscript
occurrence node and its table field), `call`, `linkage`, `sql`, `accept`,
`display`, `xml`. `LINEAGE_VERSION` is `"2"` (occurrence nodes,
`#RETURNING` linkage ports, `#n` item keys). `VALUE_CHANGING_KINDS` (`arith`, `string`, `aggregate`, `sql-expr`)
make a flow *derived*. Each edge carries `line`, `paragraph`, `guarded`
(inside IF/EVALUATE/SEARCH) and `exact` (byte ranges coincide).
`apply_source_map` stamps `origin` on every edge after copybook expansion
-- edges carry a bare `line`, so `lint.stamp_report_origins` does not
reach them. `summary` is every input-port field -> output-port field the
program connects; `key_uses` are items used as READ/START/RECORD KEY or in
a SQL `WHERE col = :hv`.

**Operands** (`_refs`) go through one path for MOVE, arithmetic, STRING,
CALL arguments, DISPLAY/ACCEPT, READ INTO / WRITE FROM: xref's
`_split_operand`, keeping only the base names minus `_qualifier_names`, so
a subscript, a reference-modifier offset/length or an `OF` qualifier is
never a value source (`COMPUTE X = Y(I)` does not flow `I` into `X`;
`LENGTH OF X` / `ADDRESS OF X` flow nothing). A literal reference modifier
narrows the byte range; literal subscripts are kept (`_constant_subscripts`).

**Level-66 RENAMES** (#485, `_index_renames`). `66 R-AB RENAMES R-A THRU
R-B` becomes an item keyed `R-AB` (level 66, `record` = the renamed record,
no parent) whose children are the elementary fields lying in the run from
the start of `R-A` to the end of `R-B`, so a MOVE to or from it flows
through them like a group. `_redefines_edges` skips it (its bytes are its
record's). One that cannot be placed (operand not found or ambiguous, in
another record, unknown offset, empty range) gets a `RENAMES item X not
traced: ...` caveat -- never a silent drop now that xref declares it.

**OCCURS tables.** A table field's node (`T.E`) stands for *any*
occurrence. Its bytes are every occurrence's (`_placements`: one range per
occurrence, or a single spanning range past `_PLACEMENT_CAP` = 1024), so a
group MOVE / READ / WRITE / CALL maps each occurrence where it really lies,
and every edge through a table field is **inexact** -- never a wrong exact
field. A reference with literal subscripts (`AMT(3)`, `T(2,1)`, one per
OCCURS level, within bounds) on an elementary field gets its own item node
`R.AMT(3)` at the occurrence's offset, joined both ways to `R.AMT` by
inexact `occurrence` edges, and an exact edge to its own bytes on every port
its record or group reaches (`_PortLink`s, resolved after the walk in
`_link_occurrences`). Nodes order by `LineageNode.sort_key()` (an unknown
offset -- a field after an `OCCURS DEPENDING ON` -- sorts first; such a field
maps to a port with no byte range).

**Item keys** are qualified names, except that the n-th item sharing one
(two `01 FILLER` groups, two same-named subordinates) is keyed `NAME#n`;
`_index_items` splits the layout into record blocks and finds each item's
parent by position (a group follows its children in the layout), so two
FILLER records are two buffers, not one with a spurious redefines.
`MOVE CORRESPONDING` pairs same-path subordinates when at least one of the
two is elementary (a group against an elementary item is a byte overlay),
skipping FILLER, REDEFINES and OCCURS items and what is under them.
`ADD` / `SUBTRACT CORRESPONDING` walk the same pairing
(`_visit_arith_corresponding`) but keep only elementary pairs whose sending
item is numeric and receiving item numeric or numeric-edited (`_Item.category`,
from PICTURE / USAGE), one `arith` edge each; the generic reads-to-writes
path would join every subordinate to every other one (issue #337).
In that generic path (`_reads_to_writes`) a receiver that only accumulates
into itself feeds nothing else the statement writes (`_self_feeding`,
#535, #534): the receivers of ADD / SUBTRACT / MULTIPLY / DIVIDE without GIVING
(taken from the model, not xref roles; with no `source_operands` recorded,
MULTIPLY / DIVIDE take their first operand as the sender), and a
read-and-written operand of
INSPECT (counters; the inspected item excepted), STRING or UNSTRING
(POINTER, TALLYING IN). `ADD 1 TO A B` is `A = A + 1; B = B + 1`, and
`MULTIPLY n BY b c` is `b = b * n; c = c * n`. COMPUTE
(`COMPUTE A B = A + 1` feeds B), a GIVING form, and a receiver that is also
a sending operand keep their edges.

**Alias edges are never chained with one of their own class**
(`overlay_class`; summary BFS and `LineageGraph._trace` both carry the
class of the edge a node was reached over): two `redefines` in a row would
carry one field of a record into every other through an alias covering the
whole record, two `occurrence` edges `T(1)` into `T(3)` through `T`, two
`table-alias` edges `PROD.T.C` into `TEST.T.C` through `T.C`.

## Layer 2: across programs

**Layer 2 -- across programs (`LineageGraph`).** Takes the reports (objects
or their `to_dict()`, which is what the backend stores) plus
`DatasetBinding`s and `Passthrough`s. Joins: dataset (writer and reader
ports meet on overlapping byte ranges of the same normalized dataset --
GDG `(+1)`/`(0)`/`.GnnnnVnn` fold to the base, `&&TEMP`s are job-scoped);
utility pass-throughs carry ranges both ways to a fixpoint, `SUM FIELDS`
ranges become `aggregate`, a `reformat` stops the flow with a caveat;
datasets nothing in scope writes are seeded from their readers' ranges;
CALL argument *n* meets callee linkage *n* (and `CALLEE#RETURNING` meets
`PROGRAM#RETURNING`); a callee with no report is an
*opaque* pass-through (every argument sent reaches every argument back,
`confidence="opaque"`) unless `_INTERFACE_RE` names it a system interface
(the MQI verbs by name -- not every `MQ*` -- *TDLI, CEE*, DSN*...). DB2:
`SCHEMA.TABLE.COLUMN` and an unqualified `TABLE.COLUMN` join both ways by
`table-alias` edges with `confidence="candidate"`; two schemas never join.
`NULLFILE` / `DUMMY` bindings and pass-throughs are ignored (the DD counts
as unbound). A PROGRAM-ID seen in more than one report keeps the first and
adds a caveat, which `impact()` returns only when the query reaches that
program. Queries `impact(field, program, direction,
depth)`, `impact_table` (schema optional), `impact_dataset` run a 0-1 BFS
where *depth* counts entries into a program. `key_relationships()` names
candidate dataset/table key relationships with the program and line as
evidence. Joins iterate ports in sorted order so output is identical on
every run, whatever `PYTHONHASHSEED`.
`join_edges()` exports every edge the joins added (JSON-shaped); passing
them back as `LineageGraph(reports, join_edges=...)` skips the joins, so
the backend joins once at upload and queries later without the JCL.
Key-relationship labels come from the dataset edges, not the bindings, so
both forms answer the same (pinned in `TestStoredJoinEdges`).
`join_state()` -> `{"edges", "caveats", "unjoined"}` adds the joins' own
caveats (reformat stops, opaque callees; `_join_caveats`) and the unjoined
DDs; `LineageGraph(reports, join_edges=..., join_caveats=...,
unjoined=...)` restores them so the rebuilt graph's `to_dict()` equals the
original's (pinned in `TestStoredJoinState`). Without `join_caveats` only
the opaque-callee caveat is re-derived and `unjoined` is empty. A rebuilt
graph records the edges it loads, so its own `join_edges()` re-exports them.
`ImpactResult.start_found` is False when nothing matched the start. A
declared item that no edge touches (set only from literals / VALUE, or only
tested in a condition) is found: `impact()` returns no hits and a
`notes` entry saying no value flows through it (#546; `_start_groups`
answers "declared?" in its `matched` half and "in the graph?" in its groups).
`ImpactResult.notes` is in `to_dict()` and a `Notes:` block of `to_text()`.
A bare name matching several items of one program (`AMT` in IN-REC and
OUT-REC) is traced once per matched qualified name (`_start_groups`; a
copybook field is one group across every program that COPYs it), so a
field one match reaches is a hit even when it is another match -- one
multi-source trace never reported a start. `impact()` adds the caveat
`PROG: AMT matches N fields: ...; qualify with OF to trace one`, also
listed in `ImpactResult.ambiguous` (#540) -- on the no-flow path too.
`ImpactResult.to_text()` lists every hit `to_dict()` does: items and ports
(prefixed `port `) under their program, tables and datasets on their own
lines (#528: ports were dropped, so a DISPLAY-only field read as feeding
nothing).
A port is a hit only where the trail ends at it: `_reach` drops it when
some onward edge is a join (`cross`, or to a dataset / table node or
another program). An edge back into the same program is no join, so a
two-way port -- an unbound DD opened I-O, a BY REFERENCE argument to a
program outside the scan, a `PROCEDURE DIVISION USING` parameter -- is
reported (#510: any onward edge used to hide it).
`Hop.origin_file` (from `_EdgeInfo.origin_file`, the report edge's
`origin.file` after `apply_source_map`, set in `_reach`) says which file a
hop's line is in; it is not in `Hop.to_dict()` (#489, used by the MCP server).

## Bindings from JCL

**Bindings (`lineage_jcl.py`).** `bindings_from_jobs(jobs)` turns
**jcl-parser** `Job`s (duck-typed; imported only in `load_jobs`, through
`importlib`, so cobol-parser keeps no runtime or mypy dependency on it)
into bindings and pass-throughs: DFSORT/ICEMAN/SYNCSORT (`SORTIN*` ->
`SORTOUT` + `OUTFIL FNAMES` + `OUTFIL FILES=nn` as DD `SORTOFnn`; a
`JOINKEYS` step reads `SORTJNF1`/`SORTJNF2` or its `F1=`/`F2=` DDs and is
always a `reformat`, #585), ICETOOL (each `TOOLIN` `COPY` / `SORT` / `MERGE`
/ `SELECT` / `SUBSET` / `DATASORT` operator `FROM(dd)` -> `TO(dd...)` +
`DISCARD(dd)`, classified through its `USING(xxxx)` `xxxxCNTL` statements;
`SPLICE` / `RESIZE` are reformats, #566), IEBGENER/ICEGENER, IDCAMS REPRO
(operands in any order, `-` continuations joined; a command word starts a
command only at a statement start -- newline, `;`, or after
`THEN`/`ELSE`/`DO` -- outside parentheses, after `/* */` comments are
dropped, so `PROD.DELETE.MASTER` does not end the REPRO, #338), IKJEFT01
`RUN PROGRAM(x)` (every one in the SYSTSIN, each bound to the step's DDs, #584).
A
blank-named DD continues the concatenation of the DD before it (`_named`);
`DD DUMMY` / `DSN=NULLFILE` bind nothing (`_dataset`); `DSN=*.STEP.DD`
referbacks resolve to the earlier step's dataset (`_referback_keys`: the
current step's PROC-invocation prefix + the referback first, so an in-PROC
`*.S1.DD` from `RUNA.S2` is `RUNA.S1`; then the full path, so
`*.RUNB.S1.DD` works from outside; then the last two parts), and one that
names no earlier DD binds nothing -- never the literal `*.` text -- and is
a caveat (#565); quoted literals in
DFSORT/IEBGENER control statements are blanked before keywords are matched
(`INCLUDE COND=(...,C'BUILD')` is not a reformat). Control statements that
live in a dataset (`SYSIN DD DSN=PROD.CNTL(X)`, a `DFSPARM` dataset) are not
read, so a SORT / IEBGENER step with one is a `reformat` plus a caveat naming
it, never an assumed copy (#339, option (a)); an in-stream `DFSPARM` is read
with `SYSIN`. A `DFSRRC00` step (the IMS region
controller) binds its DDs to the application program named by the second
`PARM` positional when the region is `DLI` / `DBB` / `BMP`, not to
`DFSRRC00` itself, so an IMS batch program's files join. `load_jobs(paths, proc_path)` reads a flat PROC
folder (`NAME.prc`) as well as a JCLLIB base -- jcl-parser's own loader
only searches `JCLLIB ORDER=` libraries. `jobs_from_sources(jcl, procs)`
does the same from in-memory text (the backend's stored members). Not built
on `cobolparser/jcl/`'s model; it shares only `jcl/programs.py` (the
IKJEFT01 / DFSRRC00 launched-program rules), so `jcl --program` and lineage
agree about a deck (#493).

**JCL caveats.** `bindings_from_jobs(jobs, caveats)` appends one line per
step whose flow it could not read (`<PROGRAM> step <STEP> in job <JOB>:
...`), so a step left out never reads as a step that moves nothing: a sort
step with no recognised input or output DD (`SORT step S2 in job J1:
outputs not recognised; the flow through it is not traced`), an ICETOOL
`TOOLIN` (or `USING` `xxxxCNTL`, then read as a reformat) that is not
in-stream, an operator whose DDs bind nothing, an IKJEFT01 step whose
`SYSTSIN` is a dataset (its programs are unknown, #566), and a referback
that names no earlier DD (#565). `field-impact --jcl` and the MCP lineage
index pass them as `LineageGraph(join_caveats=...)`, which -- without
`join_edges` -- adds them to the joins' caveats (so `join_state()` exports
them too). Invariant: a caveat there must not start with `PROGRAM:`, or
`impact()` would show it only to queries reaching that program.

Tests: `tests/unit/analysis/test_field_lineage.py`, `test_lineage_graph.py`,
`test_lineage_jcl.py`, `test_sql_flow.py`, `tests/unit/cli/test_lineage_cli.py`;
fixtures in `tests/samples/lineage/`.

## See also

* [../analysis.md](../analysis.md) -- routing page, calling conventions, module map
* [data-use.md](data-use.md) -- xref's `_split_operand` and `_names.callee_names`,
  which the operand and CALL handling reuse
* [codebase.md](codebase.md) -- `ProgramSignatureExtractor` (linkage ports)
* [../jcl.md](../jcl.md) -- the separate `cobolparser.jcl` adapter (not used here)
* [../cli.md](../cli.md) -- `lineage`, `field-impact`
* [../batch.md](../batch.md) -- `scan --analyzer lineage`
* `docs/plans/2026-10-08-field-lineage-design.md` -- design
* [history](../history/analysis.md) -- archived dated notes
