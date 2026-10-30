---
type: Module
title: Field Lineage
description: Field-level data lineage -- FieldFlowAnalyzer (field_lineage.py, one program's value-flow graph between data items and ports), LineageGraph (lineage_graph.py, cross-program joins through datasets, CALL arguments and DB2 columns, impact queries), FieldWideningAnalyzer (field_widening.py, what a PICTURE change truncates or misaligns), lineage_jcl.py (DD bindings from jcl-parser jobs) and _sql_flow.py (embedded SQL host variable <-> column flows).
tags: [analysis, field-lineage, lineage-graph, impact, widening, jcl, sql-flow, ports]
timestamp: 2026-10-16T00:00:00Z
---

# Field Lineage

Answers "if I change this field, what else changes?" at field granularity,
across programs, in two layers: `FieldFlowAnalyzer().analyze(ast)` builds one
program's may-flow value graph between data items and *ports* (files, CALL
arguments, linkage, SQL columns, console), and `LineageGraph(reports,
bindings, passthroughs)` joins many programs' reports and answers impact
queries. DD-to-dataset bindings come from JCL via `lineage_jcl.py`. Backs the
`lineage`, `field-impact` and `widen-check` CLI subcommands and `scan
--analyzer lineage`. Start with [API](#api), then the layer you need;
[Field widening](#field-widening) is built on layer 2.

## API

```python
from cobolparser.analysis.field_lineage import FieldFlowAnalyzer
from cobolparser.analysis.lineage_graph import LineageGraph
from cobolparser.analysis.lineage_jcl import bindings_from_jobs, load_jobs

flow = FieldFlowAnalyzer().analyze(ast)   # FieldFlowReport: program_id/items/ports/
                                          # edges/summary/key_uses/in_place/caveats
jobs, errors = load_jobs(["JOB1.jcl"], proc_path="procs/")
bindings, passthroughs = bindings_from_jobs(jobs)
graph = LineageGraph([flow, ...], bindings, passthroughs)
hits = graph.impact("CUST-ID", program="PROG1", direction="forward", depth=None)
graph.impact_table("CUSTOMER.CUST_ID") / graph.impact_dataset("PROD.CUST.MASTER")
graph.key_relationships() / graph.join_edges() / graph.join_state()

from cobolparser.analysis.field_widening import FieldWideningAnalyzer
widen = FieldWideningAnalyzer(graph).analyze("CUST-ID", "9(9)", program="PROG1")
widen.findings   # WideningFinding: kind/severity/program/field/message/line/...
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
| `sql` | `[SCHEMA.]TABLE.COLUMN` | `_sql_flow.analyze_sql` (SELECT INTO, FETCH through its DECLARE CURSOR, INSERT, UPDATE SET; MERGE/CTE are caveats, as is a FROM sub-select, a `FINAL` / `NEW` / `OLD TABLE (...)` data-change table reference, or a `TABLE(...)` table function -- matched on `TABLE` followed by `(`, so an ordinary table named `TABLE_CUST` / `TABLES_CFG` is traced, #340; a column qualified by such an item's correlation name, or by a name that is no FROM table or alias, gives no flow rather than a phantom table, #782) |
| `console` | `SYSIN` / `SYSOUT` (or the ACCEPT's `FROM` source) | ACCEPT / DISPLAY; `ACCEPT FROM DATE` / `DAY` / `DAY-OF-WEEK` / `TIME` (with or without a format qualifier) make no port -- the runtime's clock, not data entering the program |

A contained program's nodes include its containers' GLOBAL records
(`unused_variables.inherited_data_records`, laid out from the owning
program's `compute_program_data_items`), so `DISPLAY A` of a GLOBAL `A` in
the inner unit is an `A -> SYSOUT` edge, not a "not declared" caveat
(#504). The item is keyed in the inner report like its own; no cross-program
join links it to the container's node yet.

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
`display`, `xml`. `WRITE flat-REC FROM group` (`_writes_through`): when
the FD record is elementary and the FROM operand a group no longer than it,
the file port is reached from the group's own fields at their bytes,
exactly, not through the record (which mapped every field onto the whole
record, inexactly, and so onto every byte of the dataset -- the overlap
blow-up behind a 44 KB MCP `where_from` answer). `LINEAGE_VERSION` is `"2"` (occurrence nodes,
`#RETURNING` linkage ports, `#n` item keys). `VALUE_CHANGING_KINDS` (`arith`, `string`, `aggregate`, `sql-expr`)
make a flow *derived*. Each edge carries `line`, `paragraph`, `guarded`
(inside IF/EVALUATE/SEARCH) and `exact` (byte ranges coincide).
`apply_source_map` stamps `origin` on every edge after copybook expansion
-- edges carry a bare `line`, so `lint.stamp_report_origins` does not
reach them. `summary` is every input-port field -> output-port field the
program connects, up to `FieldFlowAnalyzer(summary_limit=...)` flows
(`DEFAULT_SUMMARY_LIMIT` 10,000; `None` unlimited, `0` none): it is quadratic
in a program's fields (604k flows, 272 MB of JSON, for one real program), so
past the limit it stops with a caveat and `summary_truncated` /
`statistics.summary_truncated` set. `LineageGraph` never reads it; `key_uses` are items used as READ/START/RECORD KEY or in
a SQL `WHERE col = :hv`. `overwrites` (JSON `"overwrites"`, edge dicts) are
the edges into an item that replace all of it: exact, unguarded, in a named
paragraph, statement in `OVERWRITING_STATEMENTS` (MOVE, READ INTO, RETURN
INTO, EXEC SQL, ACCEPT; not ADD or the string verbs, which keep part of the
old value); `apply_source_map` stamps them too.

`overlays` (JSON `"overlays"`, `Overlay`) are the byte-for-byte transfers
between two *different* records where at least one operand is a group
(group MOVE, READ INTO, WRITE FROM, RETURN INTO), recorded in `_overlay`
with both operands' qualified names and lengths, stamped by
`apply_source_map` (`origin`). Items also carry optional `picture`, `usage`
and `redefines` (the redefined name, last of the chain) -- what
`field_widening` sizes receivers with. All additive: `LINEAGE_VERSION` stays
"2", `mcp/facts.py`'s `FACTS_VERSION` moved to "7".

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
field. That includes EXEC SQL host-variable edges (`_visit_sql`, #507: a
multi-row FETCH writes every occurrence). A reference with literal subscripts (`AMT(3)`, `T(2,1)`, one per
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

**A value changed in place is derived** (#748). `edges` never loop, so
the rule above left `MOVE IN TO WS` / `MULTIPLY 100 BY WS` / `MOVE WS TO
OUT` reading as a plain copy. Each such change is recorded in the report's
`in_place` (a source == target `LineageEdge`, one per statement and kind;
`apply_source_map` stamps them too): every receiver of ADD / SUBTRACT /
MULTIPLY / DIVIDE without GIVING, and any value-changing read-and-write of
one item (`COMPUTE WS = WS * 2`, an INSPECT'd / STRING-pointer item).
`_summarize` adds the change's kind to a port flow that passes through the
item, and `LineageGraph._with_in_place` inserts a hop for it into every
impact path through the item, so `derived` holds. The hop is `exact` when
the change's line lies between the hops into and out of the item, else
`candidate` (it may run before the value arrives, or on a later loop
iteration). The text form shows it as `WS-AMT (MULTIPLY line 22)`. An
added key: `LINEAGE_VERSION` stays "2". Pinned by
`tests/regression/test_lineage_in_place_change_issue_748.py`.

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
`confidence="opaque"`), routed through one hub node `("O", program, callee)`
per program and callee so the join is sent + back edges, not sent x back
(the hub is never a hit or a hop of an impact path, and costs no depth),
unless `_INTERFACE_RE` names it a system interface
(the MQI verbs by name -- not every `MQ*` -- *TDLI, CEE*, DSN*...). DB2:
`SCHEMA.TABLE.COLUMN` and an unqualified `TABLE.COLUMN` join both ways by
`table-alias` edges with `confidence="candidate"`; two schemas never join.
`NULLFILE` / `DUMMY` bindings and pass-throughs are ignored (the DD counts
as unbound). A PROGRAM-ID seen in more than one report keeps the first and
adds a caveat, which `impact()` returns only when the query reaches that
program. Queries `impact(field, program, direction,
depth)`, `impact_table` (schema optional), `impact_dataset` run a 0-1 BFS
where *depth* counts entries into a program. Flow-sensitivity is a mark,
not a cut: `_overwritten()` checks each field a hit's path passes through,
and when the edge writing it and the edge reading it next are in one
paragraph with an overwrite of that field strictly between (parsed lines,
`_EdgeInfo.seq_line` / `paragraph`), the hit carries an `Overwrite`
(`ImpactHit.overwritten`; `"overwritten"` in `to_dict()` only when set).
Across paragraphs (a PERFORM) nothing is claimed; the start field itself is
never checked (it holds each of its values in turn). Only the path shown
is checked, the BFS's shortest. `key_relationships()` names
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
The start name is split by `_names.split_qualified_name`, so `IN` works
wherever `OF` does (`field-impact "AMT IN IN-REC"`, #541; `FieldFlowAnalyzer`
`_resolve` shares it).
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

## Field widening

`FieldWideningAnalyzer(graph).analyze(field, new_picture, program=None,
new_usage=None, depth=None)` -> `WideningReport` (`WIDENING_VERSION` "1";
`starts`, `findings`, `unchecked`, `caveats`, `start_found`,
`worst_severity()`, `to_dict()` / `to_text()`). Backs `widen-check`. One
start per field the name matches (`LineageGraph._start_groups`); a group, a
PICTURE `PictureClause` cannot size, or an item with no `picture` in its
report is a caveat and no start. Finding kinds:

* `truncation` -- forward `impact()` hits that are items: the new capacity
  is carried along the path (`Capacity.through` at every item hop), so a cut
  is reported where it happens, once. `Capacity` is integer / decimal digits
  (+ sign) for numeric and numeric-edited items, characters for the rest
  (a group: its bytes, `group=True`); `losses()` follows MOVE alignment. A
  signed numeric MOVEd to an elementary alphanumeric item loses its sign
  (#765); a group receiver copies the bytes, sign included. Severity: `info`
  when the old value lost the same things (`pre_existing`), `warning` when
  only decimal places are new, the path is derived (arithmetic) or not
  `exact`, else `error`. A derived pre-existing loss is dropped (a rate, a
  running total: the arithmetic's business). A path through a `redefines`
  hop is aliasing, not a receiver: skipped. An `occurrence` hop (`T.A` ->
  `T.A(2)`) is the same field at one subscript, so what `MOVE A(2) TO X`
  feeds is checked (#759); the start at a subscript is not a hit of its own.
  A numeric-edited item is signed only with a `+`, `-`, `CR` or `DB` in its
  PICTURE (`ZZ,ZZ9` drops the sign, #757). When the new
  PICTURE is narrower in any way (`old.losses(new)`), a backward trace flags
  the nearest feeders holding more than the new capacity.
* `layout` -- only when the byte length changes (`storage_size` of old and
  new PICTURE x enclosing OCCURS): the record's later fields shift (`info`);
  a REDEFINES over or by the record, or one inside it whose bytes hold the
  changed field (a REDEFINES after the field only shifts with its target,
  #760), and each `overlays` entry touching it (`warning`); file ports a record field meets -> LRECL (`warning`) plus
  every *other* program bound to the same dataset (`error`); CALL ports ->
  the callee's LINKAGE record (`warning`); LINKAGE ports -> every caller's
  argument record (`error`: the callee addresses past it). Both match the
  port key `NAME#n` exactly, so a CALL of an ENTRY name meets the record the
  ENTRY's USING names, and an ENTRY's LINKAGE record meets the callers of
  that ENTRY, not of the PROGRAM-ID (#761).
* `same-layout` (`info`) -- another program's item with the same qualified
  name (minus `#n`) and PICTURE: a shared copybook or a copy.
* `column` (`warning`) -- a DB2 column the value reaches; its type is not in
  the source, so it is named for review.

Findings are de-duplicated on (program, field, kind) and sorted by severity.
Tests: `tests/unit/analysis/test_field_widening.py`,
`tests/unit/cli/test_widen_check_cli.py`; samples in `tests/samples/widening/`.

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
dropped, so `PROD.DELETE.MASTER` does not end the REPRO, #338; commands read
from a `SYSIN` *dataset* are not traced, and a note names the dataset), IKJEFT01
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
only searches `JCLLIB ORDER=` libraries. `proc_path` may be one folder or
several, searched in order (the first that has a member wins; the first
folder is the JCLLIB base). `jobs_from_sources(jcl, procs)`
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
* [../cli.md](../cli.md) -- `lineage`, `field-impact`, `widen-check`
* [../batch.md](../batch.md) -- `scan --analyzer lineage`
* `docs/plans/2026-10-08-field-lineage-design.md` -- design
* [history](../history/analysis.md) -- archived dated notes
