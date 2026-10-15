# Feature Ideas

Brainstormed extensions to the parser, grounded in gaps found while reading the
current pipeline (`preprocess -> lexer -> parser -> AST -> analysis/generators`).
Nothing here is committed to; each idea notes the concrete hook point in the
existing codebase and a rough size so a future planning pass can pick from the
list rather than start from a blank page.

Sizes: **S** = days, **M** = one to two weeks, **L** = multi-week initiative
(would want its own `docs/plans/` design doc, following the
`program-data-generation-*` precedent).

## 1. Finish the advertised dialect abstraction (S/M)

`cobolparser/dialects/__init__.py` already documents "IBM Enterprise COBOL,
ANSI COBOL standards, Micro Focus COBOL, and GnuCOBOL extensions," but
`dialects/` only contains `ibm_enterprise.py`. `DialectType` in
`plugins/core.py` already has `IBM_ENTERPRISE`, `ANSI_COBOL`, and
`MICRO_FOCUS` members (no dialect *class* backs the latter two yet, and
there's no `GNU_COBOL` member at all — it'd need adding to the enum too).
The lexer and parser don't currently branch on dialect beyond IBM-specific
tokens (COMP-3, EXEC SQL/CICS/DLI). A `GnuCobolDialect` (open-source COBOL
used in most modernization/OSS pipelines — different reserved words,
`SCREEN SECTION`, `>>DEFINE`/`>>IF` free-form directives) and an
`AnsiCobolDialect` (rejects the IBM-only extensions so users can validate
portability) would make the `dialect=` parameter on `CobolParser` actually
mean something. Good on-ramp
for expanding sample coverage beyond the IBM-flavored NIST/shamrice corpora.

## 2. Cyclomatic complexity & maintainability metrics (S) — SHIPPED

> **Shipped** as `analysis/complexity.py` (`ComplexityAnalyzer`) and
> `analysis/technical_debt.py` (`TechnicalDebtAnalyzer`), behind
> `cobol-parser complexity` and `cobol-parser health`. See `.okf/analysis.md`.


`analysis/program_flow/` already builds a CFG with typed edges and classified
cycles (`ProgramFlowAnalyzer`). Cyclomatic complexity per
paragraph/section (`edges - nodes + 2`) and a program-level maintainability
score fall out of that graph almost for free — no new parsing needed, just a
new report class consuming `flow_report.edges`. Pairs naturally with
`DeadCodeAnalyzer` and `UnusedVariableAnalyzer` for a combined
`cobol-parser health <file.cbl>` subcommand that flags "this paragraph has
complexity 40 and three PERFORM cycles" the way a modernization audit would.

## 3. Whole-codebase call graph and copybook dependency graph (M) — SHIPPED

> **Shipped** as `analysis/codebase.py` (`CodebaseGraphBuilder`), behind
> `cobol-parser codebase-graph` with JSON/DOT/Mermaid output. See
> `.okf/analysis.md`.


`batch.py` parses many files in parallel but nothing aggregates the results
into a cross-*program* graph — `DynamicCallAnalyzer` (in
`analysis/value_tracker.py`) resolves CALL targets within one AST, and
`copybook_expander.py` resolves COPY statements at parse time but discards
the dependency edges once expansion is done. A `CodebaseGraphBuilder` that
runs `parse_files_with_copybooks` over a directory tree and emits "program A
calls program B" / "program A copies X.CPY" as a graph (DOT/Mermaid, reusing
`generators/flowchart.py`'s renderer) would answer the first question any
COBOL modernization engagement asks: *what depends on what*. This is the
natural foundation for change-impact analysis (idea 8 below).

## 4. AST-based COBOL pretty-printer / formatter (M/L)

There's no round-trip from `CobolProgram` back to normalized source. Every
statement node already carries enough structure (`to_dict()`) to regenerate
free-form COBOL with consistent indentation and casing — useful both as a
"canonicalize legacy fixed-format source" tool and as the base for
`gen-fixtures`-style codemods (e.g. auto-inserting a generated test hook).
Scope carefully: full-fidelity round-trip (preserving comments, exact
spacing) is a size-L undertaking; a "good enough for diffing and review"
formatter that ignores comments is closer to M.

## 5. XREF / cross-reference report (S) — SHIPPED

> **Shipped** as `analysis/xref.py` (`XrefAnalyzer`), behind
> `cobol-parser xref`, with per-reference roles and
> `duplicate_declarations`. See `.okf/analysis.md`.


Classic mainframe tooling (and most COBOL IDEs) produce a cross-reference
listing: every data item and paragraph, where it's defined, and every line
that reads/writes/PERFORMs it. `UnusedVariableAnalyzer` already builds most
of the reference-collection machinery to answer "is this used at all" —
extending it to record *where* (line numbers, statement kind: MOVE-source vs
MOVE-target vs condition vs subscript) turns "unused" into "fully
cross-referenced." Backs a `cobol-parser xref <file.cbl>` subcommand and is a
common ask when onboarding someone to an unfamiliar program.

## 6. Copybook change-impact analysis (S, depends on idea 3) — SHIPPED

> **Shipped** as `CopybookImpactAnalyzer` in `analysis/codebase.py`, behind
> `cobol-parser copybook-impact`, including transitive COPY chains. See
> `.okf/analysis.md`.


Given a copybook path, answer "which programs in this tree COPY it, directly
or via a nested COPY, and which of their data items does that expansion
touch?" This is the reverse direction of `copybook_expander.py` and is the
single most common "can I safely change this?" question for a shared
copybook in a real mainframe codebase. Straightforward once idea 3's
dependency graph exists; a scoped version (just direct COPY edges, no
transitive nesting) is doable standalone against `parse_files_with_copybooks`.

## 7. Security/lint analyzer for EXEC SQL and EXEC CICS (M) — SHIPPED

> **Shipped** as `analysis/sql_cics_lint.py` (`SqlCicsAnalyzer`), behind
> `cobol-parser sql-cics-check` and as the `sql-cics-check` lint rule. Two
> known gaps remain, recorded in `.okf/analysis.md`.


`dialects/ibm_enterprise.py` already parses `ExecSQLStatement` with
`sql_type` classification and host variable extraction
(`analysis/host_var_resolver.py`). A lint pass over that structure could flag
common legacy-COBOL security smells: dynamic SQL built by string
concatenation feeding `EXEC SQL EXECUTE IMMEDIATE` (injection risk),
hardcoded credentials in `CONNECT`/`EXEC SQL CONNECT TO ... USER ...
USING`, and CICS commands missing `RESP`/`NOHANDLE` error checks. This fits
the existing `analysis/` module shape (`<Analyzer>().analyze(ast) ->
Report`) and slots into the same CLI pattern as `move-type-check` /
`linkage-check`.

## 8. Turn `gen-fixtures` bundles into runnable test files (M)

`ProgramFixtureGenerator` (Phase 3/6/7, see `.okf/generators.md`) already
produces a `FixtureBundle` with generated mock data and computed
expectations (`call_count`, `field_equals`). It stops at the data — nothing
emits an actual pytest/mockymock test module wired to that bundle. A
`--emit-test` mode on the `gen-fixtures` CLI subcommand that renders a
runnable test file (import the program's mock harness, load the bundle,
assert the `Expectation` list) closes the loop from "here's test data" to
"here's a test," which is the actual deliverable most users of that feature
want.

## 9. Structural AST diff between two program versions (M) — SHIPPED

> **Shipped** as `analysis/ast_diff.py` (`ProgramDiffer`), behind
> `cobol-parser diff`, with fingerprint-based rename matching. Contained
> programs are not yet compared. See `.okf/analysis.md`.


Line-based `git diff` on COBOL source is noisy (COBOL is column-sensitive
and reformatting shifts everything). A semantic diff over two `CobolProgram`
ASTs — added/removed/renamed paragraphs, changed PICTURE clauses, changed
PERFORM targets — would let a migration or code-review workflow answer "what
actually changed in program behavior" instead of "what lines moved." Can
reuse `find_all_by_type` and `to_dict()` for a straightforward tree diff;
the interesting design work is matching nodes across versions when
paragraphs get renamed or reordered.

## 10. Formalize the plugin/extension API (S)

`plugins/core.py` already has a `PluginManager`, but it's not documented as
a public extension point anywhere in `.okf/` or the README, and there's no
entry-point (`pyproject.toml` `[project.entry-points]`) discovery mechanism
for third-party analyzers. Given the analyzer shape is already consistent
(`<Analyzer>().analyze(ast) -> Report`), documenting + wiring up
entry-point discovery would let downstream consumers (like the vendored
`backend/_vendor/cobol-parser` integration) register custom analyzers
without forking this repo. Low implementation cost, mostly a documentation
and `pyproject.toml` change plus a discovery test.

## Shipped but never listed here

**z/OS JCL front end** (`cobolparser/jcl/`, `cobol-parser jcl`) — card
scanning, jobs/steps/DD statements, in-stream procedure expansion, and the
`ddname -> dataset` binding a COBOL `SELECT ... ASSIGN TO` resolves through.
Roughly 1,900 lines, and it reached `main` without ever appearing on this
list. Its natural follow-up is joining it to idea 3's graph: `codebase.py`
today has no job, step or dataset node, so "which dataset does this program's
INVFILE resolve to" is answerable and "which job populates the dataset this
program reads" is not. See `.okf/jcl.md`.

---

# Batch 2 — 2026-09-17

Everything below was added in one pass after re-reading both repos at
`cobol-parser@bda94e7` and `cobol-analyzer@3e89db1`. Ideas 1-10 above are the
original list and keep their numbers; these continue it. Same rules: each entry
names what already exists, the concrete hook point, and a size.

## Analysis depth

### 11. Cross-program CALL interface checking (S/M)

`LinkageChecker` correlates CALL ↔ ENTRY *within one source unit* only — its
own docstring says so. `ProgramSignatureExtractor` already derives a callee's
real interface from `PROCEDURE DIVISION USING` / `ENTRY` / LINKAGE with graded
operand directions, and `CodebaseGraphBuilder` already knows which program
calls which; `codebase.py` never consults a signature. Joining them answers
"this CALL passes 2 operands where the callee declares 3, and operand 2 is
`PIC X(20)` against a `PIC S9(9) COMP` parameter" — a storage-corruption class
nothing in the estate catches today. Cheapest high-value item on this list,
because both halves are built and tested.

### 12. Field-level data lineage / def-use (M/L)

Nothing answers "where does this field's value come from, and everywhere it
flows to." `xref` has references with roles but no propagation; `const_fold`
is one forward path under one scenario's seed values; `value_tracker` only
chases dynamic CALL targets. A def-use graph over MOVE / COMPUTE / READ INTO /
CALL USING / SQL host variables is the missing primitive — and the prerequisite
for 13 and 31 below. The biggest genuine capability gap in the analysis suite.

### 13. Field-widening impact check (M, depends on 12)

"Widen `CUST-ID` from `PIC 9(6)` to `PIC 9(9)` — which programs, copybooks,
file record layouts and DCLGEN columns break?" Joins 12's lineage with
`layout_offsets.py`'s byte arithmetic, `CopybookImpactAnalyzer`'s COPY graph
and `DclgenChecker`'s column facts. This is the single question legacy
modernization engagements are actually paid to answer.

### 14. Join JCL to the codebase graph (S/M)

`.okf/jcl.md` names this gap itself: DD → dataset resolution exists,
`analysis/codebase.py` has no job, step or dataset node. So "which dataset does
this program's `INVFILE` resolve to" is answerable and "which job populates the
dataset this program reads" is not. Adding job/step/dataset nodes gives
end-to-end batch flow. Pairs with closing the two JCL gaps that block it:
`DSN=*.step.ddname` backward references, and cross-file PROCLIB / `INCLUDE`
resolution.

### 15. SARIF output for `lint` and `scan` (S)

`LintFinding` already carries rule id, severity, message, symbol and a
source-map-corrected location, and `apply_source_map()` already resolves a
finding inside an expanded copybook back to its real file and line. SARIF is a
serializer away, and it is what puts these analyzers into GitHub code scanning
and CI gates instead of a terminal.

### 16. An LSP server (L)

The VS Code extension is a pure in-process TypeScript scan — which is why a
dynamic `CALL WS-PROGRAM-NAME` resolves only as far as the literals in the same
file, and why free-format source is out of scope there. `XrefReport`
(definitions and references with line/column/length) and `LintReport` are
already exactly an LSP's required inputs. Would also make the parser usable
from Vim, Emacs and Eclipse rather than VS Code alone. Natural successor to 25.

## Schema and data interop

### 17. Copybook → JSON Schema / Avro / Protobuf / OpenAPI component (S/M)

`flatten_record` + `FieldSpec` + `storage.py` already resolve PIC / USAGE /
OCCURS / REDEFINES into a fully typed layout with exact byte sizes; nothing
emits a modern schema from it. This is day-one work on every "put an API in
front of the mainframe" project, and it is a serializer over data already
computed. The same machinery gives **copybook → SQL DDL**, which is
`DclgenChecker` run backwards.

### 18. `cobol-parser convert` — data file migration in one command (S)

`decoding.py` reads a real EBCDIC / COMP-3 / RDW record image and
`encoding.py` writes one, but the CLI exposes only `decode` → csv/json/hex. A
convert subcommand (EBCDIC fixed ↔ CSV/JSON/Parquet, copybook-driven, both
directions, with a per-field report of what failed to decode) is the "get this
tape extract into the data lake" tool, and it is mostly CLI surface over
shipped code.

### 19. PII / sensitive-field classification (S/M)

Nothing classifies data items today. Name-pattern plus PIC-shape heuristics
(`*-SSN`, a `PIC 9(16)` named `*-CARD*`, `*-IBAN`, `*-DOB`, `*-SALARY`) over
`ProgramLayoutIndex`, surfaced three ways: a lint rule ("this PII field is
DISPLAYed, or written to a file with no encryption"), a `gen-data --mask` mode,
and a redaction flag on `decode`. "Where does customer data live in the estate"
is currently answered with grep.

## Documentation — the deliverable nobody emits

### 20. `cobol-parser doc <file.cbl>` — a generated program specification (M)

Every analyzer returns JSON for machines; there is no Markdown or HTML output
anywhere in the CLI. A doc subcommand assembling what already exists — program
signature, files touched, CRUD matrix, copybook inventory, Mermaid flowchart,
complexity/health, xref index, SQL/CICS/DLI touchpoints, lint summary — into
one readable page is pure assembly, and it is the artifact a "document the
legacy estate" engagement ships. Extension side: "Open Program Spec" in a
webview.

### 21. Business-rule extraction as decision tables (M)

> **Shipped** as `analysis/business_rules.py` (`BusinessRuleExtractor`) and
> `cobol-parser business-rules`. Built on the AST directly rather than on
> `constraints.py`, which only models conditions on boundary-fed fields and
> would miss rules on computed WORKING-STORAGE items. See `.okf/analysis.md`.

`constraints.py` already parses IF / EVALUATE / SEARCH conditions into a
structured model for scenario planning. Rendering them per paragraph as a
condition × outcome decision table answers the question analysts actually ask
("what are the rules in this program?") and is a second use of the same
extractor, not new analysis.

## Verification

### 22. Runtime trace ingestion → observed arm coverage (M)

`generators/verification.py` checks that a scenario's *data* satisfies its
planned constraints, which is honest but still static. Ingesting a GnuCOBOL
trace (or a `READY TRACE` listing) and mapping executed paragraphs back onto
`ProgramFlowAnalyzer`'s CFG turns claimed coverage into observed coverage — and
settles the cross-record-correlation problem (see below) empirically rather
than by design doc.

### 23. Differential test lane against GnuCOBOL (S/M)

`encoding.py`'s byte-level behavior was verified against GnuCOBOL by hand. A CI
lane that compiles a sample, runs it against generated fixtures and compares
makes the generator stack self-checking rather than trusting one manual pass.
mockymock already runs GnuCOBOL in Docker, so the runner exists in the family.

## Scale and ops

### 24. Incremental scan cache (S)

`scan.py` has no caching of any kind — no mtime check, no cache file. Every
"Analyze Workspace" in the extension and every CI run re-parses the whole
checkout. Key on `(path, mtime, size, analyzer set, parser version)` → cached
report dicts. On a 5,000-program estate this is the difference between a coffee
break and a keystroke.

### 25. `cobol-parser serve` — a resident process (M)

The extension spawns the CLI per save and per command. A long-lived process
holding parsed ASTs removes that cost, and is the stepping stone to 16 (same
index, different protocol).

## Platform depth — the JCL precedent, repeated

The JCL front end proved the pattern: read a *second* z/OS language, then join
it to the COBOL side. Three more sit right there.

### 26. BMS mapset front end (M)

`EXEC CICS SEND MAP('MAP1') MAPSET('SET1')` parses as structured options, but
nothing reads the `DFHMSD` / `DFHMDI` / `DFHMDF` macros that define the screen.
Parsing them joins a SEND/RECEIVE MAP to its symbolic-map copybook and its
fields — and catches the classic "symbolic map is stale against the BMS source"
break.

### 27. IMS PSB / DBD front end (M)

`IMSSegmentAnalyzer` reads DL/I calls but has no view of the PSB (the PCB list
the program indexes into) or the DBD (the segment hierarchy). So "does `USING
PCB(3)` match the PSB", "is this SSA valid for this segment's key" and "is the
processing option sufficient for this call" are all unanswerable. Same shape of
win as DD → dataset.

### 28. DB2 DDL ingest (S)

`DclgenChecker` can only speak for host variables a `DECLARE TABLE` covers.
Real shops have the DDL; parsing `CREATE TABLE` gives it an authoritative
second source and catches the failure it cannot see today — **the DCLGEN itself
being stale against the table**.

## Migration

### 29. Record-class emitter, the honest half of a transpiler (M)

Full COBOL → Java/Python transpilation is a trap. Copybook → typed record
class, with the exact COMP-3 / zoned codecs from `encoding.py` attached, is
bounded, useful, and what a strangler-fig migration needs first: the modern
side has to read the old bytes. Also the natural first consumer of idea 4's
emitter.

---

# Where AI belongs in this codebase

Ideas 30-43 are about making *someone else's* model good at COBOL. They share a
design rule worth stating once:

**No model calls inside `cobolparser`.** The library has zero runtime
dependencies, byte-identical outputs pinned by tests, and ships as
closed-source wheels; an LLM dependency breaks all three. What the library adds
is the substrate an AI layer stands on — exact slices, citations, budgets and
verdicts. The model calls live in the extension, in a sibling tool, or in the
consumer.

The unusual advantage here is that every analyzer already distinguishes "this
is false" from "I could not check this" (`caveats`, `unresolved`,
`failed_rules`, `const_fold`'s "exact by construction, or absent"). That
distinction is what models lack, and what makes them trustworthy when they are
handed it.

## Feed the model — context is the binding constraint

### 30. An agent-shaped MCP server (S/M)

The naive version exposes each subcommand and spends the whole context on the
first call. The useful version exposes *questions* — `explain_symbol`, `slice`,
`impact_of_change`, `callers_of`, `program_brief` — each returning a small
payload where **every fact carries its `file:line`**, plus an explicit caveats
envelope naming what could not be resolved. A model told "the COPY for CUSTREC
did not resolve, so unused-variable results are incomplete" writes a different,
better answer. Nothing MCP-related exists in either repo today.

### 31. Program slicing (M, depends on 12)

`cobol-parser slice --field CUST-BAL --direction backward` → only the
statements that can affect that field, with their paragraph context. A
20,000-line program does not fit in any useful working context, and truncation
is what makes models hallucinate about COBOL specifically. Slicing converts
"summarize this program" into "read these 140 lines." Highest-leverage AI
feature on this list, and the flagship consumer of 12.

### 32. Structure-aware chunking for retrieval (S)

`cobol-parser chunks`: paragraph/section-bounded chunks with copybooks already
expanded, each carrying its xref neighbourhood, callers, and the data items it
touches, under a stable id. Sliding-window chunking is uniquely wrong for
COBOL — a paragraph's meaning lives in a DATA DIVISION entry 4,000 lines above
it and in a copybook that is not in the file. Emit chunks and metadata only;
leave embedding to the consumer, so the zero-dependency rule holds.

### 33. A typed query surface (M)

`cobol-parser query` over xref + codebase graph + JCL. Models are reliable at
writing a query against a documented schema and unreliable at reading source to
answer the same question. "Which programs write the dataset this job creates"
becomes one tool call with a checkable answer instead of a plausible guess.

### 34. `doc --for-agent --budget N` (S, on top of 20)

The same generated spec, facts-only, ordered by relevance to a stated question
and cut to a token budget. A deterministic pre-digest beats letting a model read
raw source and hope.

## Check the model — the actual differentiator

### 35. Fixture bundles as an equivalence oracle for AI-written migrations (M/L)

The pieces exist across the family: `gen-fixtures` produces seeded scenarios
with expectations, and mockymock already runs GnuCOBOL in Docker. Wire them
into: run the COBOL program and the model-generated Java/Python against the
*same* fixture rows, diff the outputs field by field. That turns "the AI
rewrote this program" from a leap of faith into a test result. Strategically
the most valuable item in this batch.

### 36. A claim checker for model-written prose (M)

Feed it generated documentation, a PR description, or a chat answer about a
program; it validates the checkable assertions against the AST — "says it
updates the ledger file, but the program never OPENs it", "says this paragraph
is unreachable, the CFG disagrees" — and returns unverifiable claims as
unverifiable rather than as true. The natural product of an analyzer suite
built on "exact or absent".

### 37. `diff --expect` as an agent guardrail (S)

`ProgramDiffer` already reports what changed *semantically* after an edit. A
mode that fails when the change touches anything outside a declared scope
("only `2100-CALC-TAX` should differ") converts human diff review into a gate
CI can hold.

### 38. Standardize the caveat envelope across every report (S)

Some reports carry `caveats` / `unresolved` / `failed_rules`; not all do, and
the shapes differ. Making it a uniform contract is a footnote for a human and
the difference between a grounded answer and a confident wrong one for an
agent. Cheapest item here, and it improves every other entry in this section.

## AI proposes, the parser disposes

The pattern that works on COBOL: the model supplies intent and naming, the
deterministic engine supplies correctness and applies the edit.

### 39. Rename suggestions (S)

The model proposes meaningful names for `WS-FLG-01` / `WS-SW-3`; the existing
rename machinery applies them across the declaration and every reference. The
model never edits text.

### 40. Model-proposed scenarios, solver-vetted (M)

The model proposes business-meaningful test cases — "month-end, negative
balance, overseas address" — and `ConstraintExtractor` + `domains.solve()`
decide whether that combination is satisfiable and pin the witnesses.
Unsatisfiable suggestions are rejected with a reason instead of producing a
fixture that tests nothing. The solver fact-checks the model.

Idea 21's decision tables belong to this pattern too: the extraction is exact,
the rule's *name* is the model's, and every rule cites its lines.

## Distribution

### 41. A Claude Code skill and plugin in this repo (S) — SHIPPED

> **Shipped** as `.claude/skills/cobol-analysis/SKILL.md`.

A skill that teaches an agent working in a COBOL checkout which subcommand
answers which question (`scan` vs `lint` vs `xref` vs `slice`), and to cite
`file:line` and read the caveats before asserting. Precedent: mockymock already
ships one.

### 42. An eval corpus you already own (S/M)

NIST COBOL-85 (459 files), shamrice (24), and the 22-program enterprise corpus,
plus analyzer output as ground truth, is a "can this model actually read COBOL"
benchmark with labels at a granularity nobody else has. Useful internally for
picking a model, and unusually good marketing.

### 43. Extension-side "Ask about this program" (M)

Build the context pack deterministically (slice + brief + caveats) and hand it
to whatever assistant the user already has, rather than bundling a key and a
vendor. The extension's job is the grounding, not the inference.

## What not to build

Do not let a model compute record layouts, byte offsets, PIC arithmetic or
COMP-3 encodings — `storage.py` is exact and a model is not. Do not summarize
where you can slice. And do not add an "explain this code" button whose output
nothing checks: 31 and 36 are what make the explanation worth reading.

---

# Correctness debt worth funding as a feature

Not new capability — shipped features that are quietly less true than they look.

* **Cross-record correlation in `ScenarioPlanner`.** The design doc landed
  (`docs/plans/2026-09-04-cross-record-correlation-design.md`) and
  `PlannedScenario.row_witnesses` is groundwork nothing populates, so scenarios
  are still *named* for arms they provably never reach. Idea 22 would at least
  make the failure visible.
* **Free-format source in the extension.** The parser handles it; the
  extension's outline, navigation and focus mode read by column position and
  report little or nothing.
* **`ProgramDiffer`** skips contained programs and statements outside any named
  paragraph.
* **`DclgenChecker`'s VARCHAR host-structure gap**, and the JCL front end's
  named `PROC` without `PEND` reported as an error.

# Suggested next step

Ideas 2, 3, 5, 6, 7 and 9 shipped, as did the JCL front end that was never on
the list, and 41 shipped with this batch. What remains from the original ten is
**1** (dialect classes), **4** (pretty-printer/formatter), **8**
(`gen-fixtures --emit-test`) and **10** (plugin entry-points).

Across both batches, in the order I would actually do them:

1. **11** (cross-program CALL checking) — days of wiring between two shipped
   components, and it produces findings nothing else in the pipeline can.
2. **24** (scan cache) and **38** (caveat envelope) — each about a day, each
   felt everywhere.
3. **12** (lineage/def-use) — the one structural investment, because **13**
   (field widening) and **31** (slicing) both wait on it.
4. **35** (fixtures as an equivalence oracle) — the strategic bet: it is what
   makes an AI-assisted migration defensible rather than hopeful.

**8** remains the cheapest closed loop of the original ten, and **4** is worth
more than its own description suggests now that a lint stream exists — an AST
pretty-printer is what a `lint --fix` would need.
