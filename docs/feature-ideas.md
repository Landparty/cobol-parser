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

## Suggested next step

*(Superseded — ideas 2, 3, 5, 6, 7 and 9 have all shipped, as has the JCL
front end that was never on the list.)* What remains from the original ten is
**1** (dialect classes), **4** (pretty-printer/formatter), **8**
(`gen-fixtures --emit-test`) and **10** (plugin entry-points).

Of those, **8** is the cheapest real win: `ProgramFixtureGenerator` already
computes `call_count` and `field_equals` expectations, and nothing yet emits a
runnable test from them. **4** is worth more than its own description suggests
now that a lint stream exists — an AST pretty-printer is what a `lint --fix`
would need.

Ideas worth adding that post-date this list: a field-level data-lineage /
def-use analyzer (nothing today answers "where does this field's value come
from, and everywhere it flows to" — `xref` has references without propagation,
`const_fold` is one forward path, `value_tracker` only chases dynamic CALL
targets); the field-widening impact check that would build on it; joining JCL
to the codebase graph (above); SARIF output for `lint`/`scan`; and an LSP
server, for which `XrefReport` (definitions + references with
line/column/length) and `LintReport` are already the required inputs.
