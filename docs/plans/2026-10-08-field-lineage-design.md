# Field-level data lineage across programs

**Status:** design only, nothing implemented. Read against `cobol-parser` main
@ `3fa0212`, `backend` main and `legacy-application` main on 2026-10-08.
**Repos touched:** `cobol-parser` (analysis + CLI), `backend` (storage, join,
API), `frontend` (one view). Also delivers Phase 4 of the backend's
test-data-environments plan
(`backend/docs/superpowers/plans/2026-09-27-test-data-environments.md`).

## The question

"If I change this field, which fields in which other programs, datasets and
tables carry its value?" And the reverse: "where does the value in this field
come from?"

Today the toolchain answers both at the wrong granularity:

- `copybook-impact` (`analysis/codebase.py`, `CodebaseGraph.programs_using`)
  lists every program that COPYs a member. Change one field of `ACCTMAST` and
  it names all four programs that include it in `legacy-application`, whether
  or not they touch that field.
- backend `/relationships/impact/{program_id}` walks program-level edges
  (CALLS, dataset reads/writes). It cannot tell a program that reads
  `TRAN-AMT` from one that only copies the record through.
- `xref` knows every read and write of a field, but only inside one program,
  and only as roles. It never records *which* field a value came from.

## What already exists

Verified against each repo on 2026-10-08.

| Piece | Where | What it gives lineage |
|---|---|---|
| Per-reference roles (write/read/condition/call-argument/host-variable/file-operation) | `analysis/xref.py`, `XrefAnalyzer` | Every touch point of a field, with location and statement. No source→target pairs. |
| Byte layout of every data item, REDEFINES chains | `generators/data/layout_offsets.py`, `compute_program_data_items()` → `LayoutItem(byte_offset, byte_length, redefines_chain, ...)` | Group-move overlap and cross-program record matching by bytes |
| FD → record, qualified-name resolution, level-88 | `generators/data/program_layout.py`, `ProgramLayoutIndex` | Which record a file READ/WRITE moves |
| CALL argument direction (IN/OUT/BIDIRECTIONAL) with provenance | `analysis/boundary_inventory.py`, `CallArg.provenance` | Which way a value crosses a CALL |
| LINKAGE parameters in USING order | `analysis/program_signature.py`, `ProgramSignature` | The callee side of a CALL join |
| Dynamic CALL candidate targets | `analysis/value_tracker.py`, `DynamicCallAnalyzer` | CALL joins through `CALL WS-PGM` |
| SQL host variables ↔ DCLGEN columns | `analysis/host_var_resolver.py`, `dclgen_check.py` | `table.column` ports |
| DD → dataset per step | `jcl/bindings.py`, `resolve_dd_bindings()` → `DatasetBinding(ddname, dataset, step, job, ...)` | File ports joined across jobs |
| Cross-file program/copy graph, parallel build | `analysis/codebase.py`, `CodebaseGraphBuilder` | The scaffolding the cross-program join reuses (workers, fault isolation) |
| Record fields with offsets, FD→layout bindings, COBOL DD→DSN rows | backend `RecordField.offset_bytes/length_bytes`, `FileRecordBinding`, `CobolDatasetResolver` → `COBOL_DATASET_READS/WRITES` | Everything needed to do the cross-program join in SQL |

What is missing is the one thing in the middle: **value-flow edges inside a
program** (`TRAN-AMT` → `WS-TOTAL` → `OUT-TOTAL`), summarised at the
program's ports, plus a join that connects ports between programs.

## Model

### Field identity

Inside one program, a field is its qualified data name
(`TRAN-AMT OF TRAN-REC`), as `ProgramLayoutIndex.resolve()` already returns.

Across programs, a name is not an identity. Two programs routinely read the
same dataset through different copybooks, or the same copybook under
`COPY ... REPLACING`. So across a boundary a field is a **byte range on a
port**:

| Port kind | Key | Field within it |
|---|---|---|
| `file` | dataset name (from JCL), else the program's ddname | `(offset, length)` in the record |
| `call` | callee program id + argument position | `(offset, length)` in the argument |
| `linkage` | own program id + USING position | `(offset, length)` in the parameter |
| `sql` | `table.column` | whole column |
| `cics` | COMMAREA / container name, TS/TD queue | `(offset, length)` |
| `mq` | queue name when literal, else the MQ call site | `(offset, length)` in the message buffer |
| `console` | ACCEPT / DISPLAY | whole item |

Byte ranges come from `compute_program_data_items()`, so the join can never
drift from what `data-items` and the record encoder report.

### Layer 1: per-program flow summary (cobol-parser)

New `analysis/field_lineage.py`, `FieldFlowAnalyzer().analyze(ast, index)` →
`FieldFlowReport`.

1. **Assignment edges.** One walk of PROCEDURE DIVISION, reusing xref's
   operand extraction, emitting `FlowEdge(source, target, kind, location,
   guarded)`:
   - `MOVE a TO b c` → a→b, a→c. `MOVE CORRESPONDING` → pairs by matching
     subordinate names.
   - **Group moves** are byte overlays. `MOVE IN-REC TO WS-REC` becomes one
     edge per pair of elementary fields whose byte ranges overlap, with
     `exact=True` only when the ranges coincide. This is what makes
     "record copied through" visible field by field.
   - `COMPUTE/ADD/SUBTRACT/MULTIPLY/DIVIDE` → every operand → every result
     (`kind="arith"`). `STRING`/`UNSTRING`/`INSPECT ... CONVERTING` →
     sources → targets (`kind="string"`). `INITIALIZE`/literals produce no
     source edge, but are recorded as `kind="literal"` so a backward query
     can say "set to a constant here".
   - `READ f INTO x` → record→x. `WRITE r FROM x` → x→record. `REWRITE`,
     `RELEASE`, `RETURN` the same way.
   - `REDEFINES` adds a bidirectional `alias` edge between overlapping byte
     ranges.
   - Reference modification (`A(5:3)`) narrows the byte range rather than
     widening to the whole field.
   - `guarded=True` when the statement sits under IF/EVALUATE/PERFORM UNTIL,
     so a consumer can rank unconditional flows first.
2. **Port binding.** Each FD record, CALL argument, LINKAGE parameter, SQL
   host variable, CICS/MQ buffer and ACCEPT/DISPLAY operand is attached to its
   port (table above). CALL direction comes from `CallArg`, so an IN-only
   argument gets only a caller→callee edge.
3. **Summary.** Transitive closure from every input port field to every
   output port field, keeping the intermediate path for explanation. This is
   what crosses program boundaries: the summary is small (ports × ports), so
   the cross-program layer never needs an AST.

It is a **may-flow** analysis: flow-insensitive within a paragraph chain,
over-approximating. For impact, a false "might be affected" is cheap and a
missed one is the expensive mistake. Every edge carries its evidence
(statement, line) so a reader can dismiss a false one in seconds.

As with xref, nothing is dropped silently. `FieldFlowReport.caveats` lists
what could not be followed: unresolved dynamic CALL, pointer/`SET ADDRESS`,
`OCCURS DEPENDING ON` ranges, unresolved COPY.

### Layer 2: cross-program join

`analysis/lineage_graph.py`, `LineageGraphBuilder(paths, jcl_paths=...)`,
built like `CodebaseGraphBuilder` (same worker pool, same per-file fault
isolation). It loads one `FieldFlowReport` summary per program and joins
ports:

- **Files through JCL.** A program's `SELECT f ASSIGN TO DDNAME` is bound to
  a dataset by `resolve_dd_bindings()` for each step that runs it. A writer's
  output port and a reader's input port on the same dataset are joined field
  by field on overlapping byte ranges:
  - identical `(offset, length)` → `confidence="exact"`;
  - overlapping → `"overlap"`, with both ranges reported.
  GDG references (`(0)`, `(+1)`) normalise to the base name, with a caveat.
  `&&TEMP` datasets join only within their own job.
  Utility steps that keep record positions are a pass-through: IEBGENER,
  IDCAMS REPRO, and DFSORT whose control statements only reorder or filter
  (`SORT FIELDS`, `INCLUDE`/`OMIT`, `OUTFIL INCLUDE`). `SUM FIELDS=(p,l,...)`
  keeps positions but changes values, so those byte ranges get
  `kind="aggregate"`. Anything that moves bytes (`INREC`/`OUTREC`/`BUILD`/
  `OVERLAY`) stops the flow with a caveat; v1 does not interpret the
  reformat. Both shapes occur in `GLRJOB` and `CTRJOB`.
- **CALL.** Caller argument *i* ↔ callee LINKAGE parameter *i*, field by
  field on byte ranges. Dynamic CALLs fan out to `DynamicCallAnalyzer`
  candidates, marked `"candidate"`. A callee that is not COBOL (ASM, PL/1:
  most callees in `legacy-application`) is an opaque node. Its OUT
  arguments are reported as "set by CURRFMT (ASM), not traced".
- **SQL.** Writer host variable → `table.column` → reader host variable.
  INSERT/UPDATE map host variables to columns by position or by `SET`.
  A SELECT maps each select-list expression to its INTO host variable, and
  every column inside the expression flows into it. In CTRRPT,
  `SUM(CASE ... THEN T.AMOUNT ...)` → `:HV-TOTAL-CASH-IN` is
  `kind="aggregate"`. Without DCLGEN, the column name is the identity.
- **Unjoined ports** (a dataset no JCL names, a CALL to a program not in the
  scan) are listed, never dropped.

### Queries

```python
graph = LineageGraphBuilder(["cobol/"], jcl_paths=["jcl/", "proc/"]).build()
graph.impact("TRAN-AMT OF TRAN-REC", program="FEECALC")   # forward
graph.sources("GL-TOTAL", program="GLRECON")              # backward
graph.key_relationships()  # test-data Phase 4: flows that land in a key
```

Each result is a list of paths. Every hop carries program, field, line,
edge kind and confidence.

`key_relationships()` is the derived view the test-data plan's Phase 4
calls `data_relationships`: flows whose target is a `RECORD KEY`, a
`READ ... KEY`, a `START ... KEY` or an SQL `WHERE` host variable. It needs
no separate inference pass.

### CLI

```
cobol-parser lineage <file.cbl> [--field NAME] [--format json|text]
cobol-parser field-impact FIELD PATH... --program NAME [--jcl DIR]...
    [--direction forward|backward] [--depth N] [--format json|text|mermaid]
    [--workers N] [--copybook-path DIR]
```

`lineage` is the single-program report (Layer 1). `field-impact` is the
cross-program query (Layer 2) over a checkout, which is useful without
LegacyLens and is what the `cobol-analysis` skill would call for "what breaks
if I change this field".

## Backend integration

The backend already stores everything the join needs except the per-program
summary:

Both steps run during upload and are stored in Postgres:

- **Per program, at parse time.** The parse worker that already handles the
  COBOL file (behind the adapter in `src/parsers/cobol/`) also runs
  `FieldFlowAnalyzer` and saves its port-to-port summary to a new
  `field_flows` table: one row per edge (program, source field and byte
  range, target field and byte range, port, kind, line, guarded). Re-parsing
  a program replaces only its own rows.
- **Across programs, after extraction.** A post-extraction step in
  `UnifiedUploadOrchestrator`, next to `CobolDatasetResolver` and reusing its
  `COBOL_DATASET_READS/WRITES` rows and the `RecordField` offsets, runs the
  Layer 2 join over the stored summaries and writes `field_lineage_edges`
  (from program/field → to program/field, via dataset/call/table,
  confidence). It reruns whenever any program in the application is
  re-parsed.
- Queries walk `field_lineage_edges` with a recursive CTE. Nothing is parsed
  at query time.
- `GET /api/v1/record-fields/{id}/impact?direction=forward|backward&depth=N`;
- frontend: from a field in the code viewer or record-layout view, a
  "Field impact" panel listing affected programs and fields with the evidence
  line, each clickable into the viewer.

`interface-contract.md` gains the summary shape with a `lineage_version`
field. The join logic stays in cobol-parser as a pure function over
summaries, so the CLI and the backend cannot disagree.

## Validation

`legacy-application` has the shapes this has to get right:

- `BANK.PROD.TRAN.DAILY` is read by `FEECALCJ` directly and by `EODJOB`,
  `GLRJOB` and `CTRJOB` through DFSORT steps into `&&` temporaries
  (`GLRJOB` STEP010 → `&&GLAGG` → GLRECON, with `INCLUDE` and
  `SUM FIELDS=(43,10,ZD)`). This covers file joins, temporaries, sort
  pass-through and aggregation.
- `ACCTMAST.cpy` is COPYed by four programs. Field impact must name fewer
  programs than `copybook-impact` does, or it adds nothing.
- `EODPROC` → `CURRFMT` (ASM) ×6 and `DATEUTIL`: CALL arguments into an
  opaque callee.
- `JOBDISP`: dynamic CALL dispatch through candidates.
- `BANK.TRANSACTION_HIST.AMOUNT`: written by CHKCLR, INTCALC, LOANPMT,
  ACCTMNT, ACHPROC and DEPTMQC, each from its own differently named host
  variable. Read by CTRRPT (aggregated into the $10,000 CTR check and
  `BANK.REGULATORY_RPT.TRAN_AMOUNT`), GLRECON and EODPROC. Only FEECALC
  COPYs `TRANREC`, so name and copybook search find almost none of this.

Golden tests: one hand-checked forward and backward query per bullet, plus a
pass over `tests/samples/enterprise/` asserting no analyzer exception and
caveats where expected. Unit tests per edge kind, with group-move overlap
and REDEFINES alias given their own cases.

## Phases

| # | Deliverable | Repo | Size |
|---|---|---|---|
| 1 | `FieldFlowAnalyzer` + `lineage` CLI (Layer 1) | cobol-parser | M |
| 2 | `LineageGraphBuilder` + `field-impact` CLI: files via JCL, CALL, SQL (Layer 2) | cobol-parser | M |
| 3 | `key_relationships()`, which is test-data Phase 4's inference half | cobol-parser | S |
| 4 | Summary storage, join over stored summaries, impact endpoint, editable key relationships | backend | M |
| 5 | Field impact panel | frontend | S |

Phases 1 to 3 are useful on their own from the CLI and the skill. Phase 4
releases test-data Phases 5 (subset/mask) and 6 (cross-file synthetic data).

## Decisions taken (change any of them before Phase 1)

1. **May-flow, not must-flow.** Over-approximate and show evidence. Exact
   value tracking stays in `const_fold`.
2. **Bytes across boundaries, names within a program.** This is the only
   identity that survives different copybooks over one dataset.
3. **Join logic lives in cobol-parser**, and the backend calls it over stored
   summaries. It does not reimplement it in SQL.
4. **Non-COBOL callees are opaque in v1.** hlasm-parser and pl1-parser
   don't extract parameter layouts yet. They can supply summaries later
   through the same port shape.
