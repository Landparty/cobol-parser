# Documentation map

Where each kind of documentation lives, so a fact is written down once.

## User guides (`docs/`)

| Guide | What it covers |
|---|---|
| [public-api.md](public-api.md) | What is public and semver-stable (the facade list, stable subpackages, internals), the `ProgramAnalyzer` interface, and moved names |
| [mcp-server.md](mcp-server.md) | `cobol-parser mcp`: install, connect a client, every tool and prompt, how to read an answer |
| [project-config.md](project-config.md) | `cobol.yml`: where it is looked for, every key and which subcommands it fills |
| [ci-lint.md](ci-lint.md) | Linting in CI: many files, `--changed-since`, GitHub annotations, the `line-length` rule, a workflow and pre-commit hooks |
| [github-action.md](github-action.md) | The COBOL lint GitHub Action (`action.yml`): inputs, new-code vs whole-codebase scope per rule, job summary, SARIF |
| [fixture-bundle-schema.md](fixture-bundle-schema.md) | The JSON bundle `gen-fixtures` writes, field by field |
| [enterprise-program-types.md](enterprise-program-types.md) | The IBM Enterprise COBOL program-type corpus and what each program proves |
| [feature-ideas.md](feature-ideas.md) | The idea backlog, with what has shipped marked |

## Reference (`.okf/`)

[`.okf/index.md`](../.okf/index.md) is the reference for how the library
works: one topic file per area (lexer, preprocessing, parser, AST models,
analyzers, generators, batch and scan, JCL, CLI, MCP server, tests). It is
written for people and for AI agents, who load only the file a task needs.
The full CLI reference, every subcommand with every flag, is
[`.okf/cli.md`](../.okf/cli.md), generated from the argparse tree.

`scripts/okf_check.py` checks what these files say against the code (imports
run, names and paths exist, links resolve, counts match), and the pre-commit
hook blocks a source change whose OKF topic file was not touched. The same
check covers the root `README.md`, `CLAUDE.md`, `interface-contract.md` and
the user guides above.

## Contracts

[`interface-contract.md`](../interface-contract.md) is what the backend
adapter and mocky-mock's fixture generator rely on. Read it before changing a
public API shape.

## History (not kept current)

These record what was planned or found at a point in time. Each design plan
starts with a status line saying whether, and where, it was built.

| Folder | What it holds |
|---|---|
| [plans/](plans/) | Design plans and implementation plans, by date |
| [`reports/`](../reports/) | Codebase audits (`audit-*.md`) and `open-findings.md`, the still-open low-severity findings |
| [`.okf/history/`](../.okf/history/) and [`.okf/log.md`](../.okf/log.md) | Dated fix write-ups moved out of the topic files, and the OKF change log |
| [`CHANGELOG.md`](../CHANGELOG.md) | What changed in each release (release-please) |
