---
okf_version: "0.1"
---

# cobol-parser OKF Bundle

Knowledge bundle for the **cobolparser** Python library — COBOL → AST for IBM
Enterprise COBOL, plus the static analysis, generators and z/OS JCL front end
built on top of it. Author: Samuel Dion. (The package version lives in
`pyproject.toml`, kept current by release-please; it is deliberately not
mirrored here.)

**Load one topic file per task** — the row below that matches it. Every topic
file is under ~55 KB (~15k tokens); the three big areas (analysis, parser,
generators) are folders with a short routing page in front.

## Which file do I load?

| Task | Load |
|------|------|
| Tokenization, `TokenType`, literal helpers, the Cython fast path | [lexer.md](lexer.md) |
| Fixed-format normalization, directives, conditional compilation, copybook expansion, `REPLACE`, source maps | [preprocessing.md](preprocessing.md) |
| `CobolParser`, `parse_cobol`, `ParseResult`, error recovery, `core/` (token stream, registry, AST factory), config classes, profiling | [parser/orchestration.md](parser/orchestration.md) |
| IDENTIFICATION / ENVIRONMENT / DATA / PROCEDURE division parsing, data clauses, FD/SD/RD | [parser/divisions.md](parser/divisions.md) |
| Statement-parser registry, boundary rules, shared helpers, adding a parser | [parser/statements.md](parser/statements.md) |
| IF, EVALUATE, PERFORM, GO TO, CALL, SEARCH, STOP/EXIT, legacy verbs | [parser/statements-control.md](parser/statements-control.md) |
| MOVE, arithmetic, COMPUTE, SET, INITIALIZE/INSPECT, STRING/UNSTRING, DISPLAY/ACCEPT, XML/JSON | [parser/statements-data.md](parser/statements-data.md) |
| File I/O verbs, SORT/MERGE, EXEC SQL/CICS/IMS, Report Writer | [parser/statements-io.md](parser/statements-io.md) |
| `ASTNode` hierarchy, `CobolProgram`, data items, statement nodes, `to_dict()` / `from_json()` | [ast-models.md](ast-models.md) |
| Program flow (CFG), dead code, recursion risk, complexity, redundancy, health score | [analysis/flow.md](analysis/flow.md) |
| Unused variables, xref, MOVE types, linkage, IO sequence/logging/coverage, CRUD, dynamic CALL values | [analysis/data-use.md](analysis/data-use.md) |
| Host variables, DCLGEN, SQL/CICS lint, IMS segments, LE services | [analysis/sql-cics-ims.md](analysis/sql-cics-ims.md) |
| `LintAnalyzer` and its rules | [analysis/lint.md](analysis/lint.md) |
| Field lineage, `field-impact`, cross-program joins | [analysis/lineage.md](analysis/lineage.md) |
| Business-rule extraction | [analysis/business-rules.md](analysis/business-rules.md) |
| Codebase graph, copybook impact, program signatures, semantic diff | [analysis/codebase.md](analysis/codebase.md) |
| Boundary inventory, constraints/solver, constant folding, invocation counts (`gen-fixtures` analysis side) | [analysis/fixtures-support.md](analysis/fixtures-support.md) |
| Not sure which analyzer file | [analysis.md](analysis.md) (routing page, module map, calling conventions) |
| Dialect tables, EXEC SQL/CICS/IMS node types, intrinsic/LE lookups | [dialects.md](dialects.md) |
| Copybook → CSV / record-image data, encodings, fixed vs variable records | [generators/record-data.md](generators/record-data.md) |
| Decoding record images, REDEFINES views, comparing files | [generators/decode-compare.md](generators/decode-compare.md) |
| `gen-fixtures`: layout index, fixture bundles, scenarios, expectations | [generators/fixtures.md](generators/fixtures.md) |
| Mermaid / DOT flowcharts | [generators/flowchart.md](generators/flowchart.md) |
| `parse_files`, `scan_files`, batch fault isolation, cross-file clones | [batch.md](batch.md) |
| z/OS JCL: jobs, steps, DD → dataset bindings (via jcl-parser) | [jcl.md](jcl.md) |
| CICS CSD and BMS maps, DB2 DDL, IMS DBD/PSB (`cobolparser.definitions`) | [definitions.md](definitions.md) |
| CLI subcommands and flags, exit codes, the `cobol.yml` project config | [cli.md](cli.md) |
| The MCP server for AI agents (`cobol-parser mcp`): tools, prompts, envelope, caveats, workspace guard and cache | [mcp.md](mcp.md) |
| Test layout, markers, fixtures, coverage floor, where behaviour is pinned | [tests.md](tests.md) |
| What the backend adapter and mocky-mock consume (summary of `interface-contract.md`) | [integration.md](integration.md) |

## How each file reads

Every topic file has one shape: frontmatter, a `#` title, a few lines saying
what the area is and where to start, a `## Contents` list (files over ~200
lines), `##` reference sections named for topics, and `## See also` last.
Topic files describe how things **are**. Why a rule exists — the input that
broke a naive version — is kept beside the rule as a one- or two-line
invariant, so a future change does not undo a fix.

## History (not loaded by default)

Point-in-time material lives outside the topic files:

* [history/](history/) — one archive per topic (`history/parser.md`, …): the
  dated fix write-ups, audits and before/after tables that used to sit inside
  the topic files, moved verbatim on 2026-10-15. Read one only when you need
  to know *when* or *why* something changed beyond what the invariant says.
* [log.md](log.md) — the dated bundle update log, newest first. Every change
  to the bundle adds an entry here, not a dated paragraph in a topic file.

## Keeping this bundle honest

Two checks, both run by the pre-commit hook (`.githooks/pre-commit`; enable
it with `git config core.hooksPath .githooks`) and by the test suite:

* **Staleness** — `scripts/okf_staleness_check.py` maps every source module
  to the topic file that documents it (`OKF_MAP`) and blocks a commit that
  changes the module without touching that file.
  `tests/test_okf_staleness_map.py` fails when a module has no entry.
* **Content** — `scripts/okf_check.py` checks what the files *say*: imports
  must run; backticked `cobolparser.*` names, class/function names and repo
  paths must exist; links and anchors must resolve; the CLI table in
  `cli.md` must match argparse; and counts the code can answer (there are
  <!-- okf:gen analysis-module-count -->36<!-- /okf:gen --> analysis
  modules, <!-- okf:gen tokentype-count -->246<!-- /okf:gen --> `TokenType`
  members, <!-- okf:gen cli-subcommand-count -->41<!-- /okf:gen -->
  subcommands) are written as `<!-- okf:gen NAME -->` spans that must equal
  the generator's output. After a code change that moves one, run
  `python scripts/okf_check.py --write`. `tests/test_okf_claims.py` runs the
  same checks. A file documenting another codebase's names declares them with
  `<!-- okf:external Name ... -->`.
