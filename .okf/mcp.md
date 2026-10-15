---
type: Module
title: MCP Server
description: cobolparser/mcp/ and `cobol-parser mcp` -- an MCP server (stdio) that lets AI agents question COBOL source; tools as plain functions (tools.py), the response envelope and caveat kinds (envelope.py), the workspace guard, cobol.yml and parse cache (workspace.py), and the one SDK-importing module (server.py).
tags: [mcp, ai, agents, tools, stdio, caveats, source-map]
timestamp: 2026-10-15T00:00:00Z
---

# MCP Server

<!-- okf:external add_tool FastMCP -->

`cobol-parser mcp --root DIR` serves COBOL analysis tools to AI agents over
the Model Context Protocol, on stdin/stdout. Design and later phases:
`docs/plans/2026-10-15-mcp-server-design.md`; user guide:
`docs/mcp-server.md`. Start with `CobolTools` in `cobolparser/mcp/tools.py`.

| Module | Holds | Imports the SDK |
|---|---|---|
| `cobolparser/mcp/envelope.py` | `Response` (caveats + truncation), `Caveat`, `CAVEAT_KINDS`, `ToolError`, `MCP_SURFACE_VERSION`, limits | no |
| `cobolparser/mcp/workspace.py` | `Workspace` (path guard, `cobol.yml`, LRU parse cache), `ParsedProgram` (unit selection, `locate()`), `stdout_to_stderr()` | no |
| `cobolparser/mcp/tools.py` | `CobolTools`: `read_source`, `lint`, `explain_symbol` | no |
| `cobolparser/mcp/server.py` | `build_server()`, `run_stdio()`: typed wrappers registered on `FastMCP` | **yes** (`[mcp]` extra) |

## Contents

- [Tools](#tools)
- [Envelope](#envelope)
- [Workspace](#workspace)
- [Packaging and tests](#packaging-and-tests)
- [See also](#see-also)

## Tools

Tools answer questions, not subcommands: one call joins analyzers and
returns a small payload. Every list is capped (`limit`, default 50, max 500).

| Tool | Answers | Built on |
|---|---|---|
| `read_source(file, line, before, after)` | numbered lines around a citation, at most `MAX_SOURCE_LINES` (200) | the file, through the guard |
| `lint(file, rules, min_severity, limit)` | findings worst first, `summary` counts, `rules_run` | `LintAnalyzer` over **every** unit, `add_parse_errors`; defaults from `cobol.yml`'s `lint:` |
| `explain_symbol(file, name, program, limit)` | each declaration matching `name` (or `X OF Y`): `declared_at`, `layout` (PICTURE, USAGE, `byte_offset`, `byte_length`, REDEFINES, level-88 values), `references` with role/statement/paragraph, `references_by_role`; `suggestions` when not found | `XrefAnalyzer`, `compute_program_data_items` |

Invariants:

- A reference location carries **no column**: xref's column is the
  statement's, not the operand's, and would mislead.
- `byte_offset` 0 is reported (`_worth_showing`): `0 in (None, [], False)` is
  True in Python.
- xref's notes about undeclared names are passed on only when the answer is
  about an undeclared or unknown name (`_UNDECLARED_CAVEATS`); elsewhere they
  are tokens a model pays for and cannot use.
- Lint keeps errors when the list is cut: ordering is severity, then source.

## Envelope

Every tool returns `{"surface_version", "answer", "caveats", "truncated",
"program"?}` (`Response.build`). A location anywhere in `answer` is
`{"file", "line", "column"?}` in the file on disk, root-relative when it can
be; `null` with an `unmapped-location` caveat when the source map has no
entry. `caveats[].kind` is closed: <!-- okf:gen mcp-caveat-kinds -->`unresolved-copybook`, `partial-parse`, `analyzer-failed`, `incomplete-analysis`, `ambiguous-name`, `duplicate-declaration`, `unmapped-location`, `program-unit-selected`<!-- /okf:gen -->.
A new kind or a changed shape bumps `MCP_SURFACE_VERSION`. A request that
cannot be answered at all (path outside the workspace, unknown program unit,
bad severity) raises `ToolError`, which the SDK returns as an error result.

## Workspace

- **Guard.** `Workspace.resolve()` resolves symlinks, then refuses anything
  not under the root or a `cobol.yml` copybook directory.
- **Config.** `load_project_config(root)` unless the CLI was given
  `--config`/`--no-config` (`args._config_explicit`). Copybook paths, source
  format, `debug_lines` and `define` come from it; no tool takes them.
- **Parse.** Always `COLLECT_ALL`. With copybook paths it expands; a
  `PreprocessingError` (missing member) falls back to a plain parse with an
  `unresolved-copybook` caveat rather than failing. Each "COPY X was not
  expanded" parse warning becomes its own caveat; parse errors become
  `partial-parse`. `>>DEFINE` symbols are applied before a plain parse, as
  the CLI does.
- **Locations.** `ParsedProgram.locate()` maps an expanded-text line through
  `expansion_source_map` (identity when nothing expanded) and adds
  `source_column_offsets()` ([analysis/lint.md](analysis/lint.md)) to a
  known column.
- **Cache.** LRU keyed by resolved path (`--cache-size`, default 32). An
  entry is reused only while the `(mtime_ns, size)` of the program **and of
  every copybook its source map names** is unchanged.
- **stdout.** Over stdio stdout is the protocol; tools run library code
  under `stdout_to_stderr()`, and the server logs at WARNING.

## Packaging and tests

- `[mcp]` extra (`mcp>=1.10,<2`, also in `[dev]`). mypy ignores missing
  `mcp`/`pydantic` imports, so the typecheck job needs no extra. Tools are
  registered with `add_tool()` rather than decorators, which
  `disallow_untyped_decorators` would reject when the SDK is untyped.
- `cobol-parser mcp` without the extra exits 1 naming the install command.
- Tests: `tests/unit/mcp_server/` (`test_mcp_tools.py` needs no SDK;
  `test_mcp_server.py` drives an in-memory client session and the CLI). The
  directory is not named `mcp`: a test package of that name shadows the SDK.

## See also

- [cli.md](cli.md) -- the `mcp` subcommand row, `cobol.yml`
- [analysis/lint.md](analysis/lint.md) -- `LintAnalyzer`, source-map origins
- [analysis/data-use.md](analysis/data-use.md) -- `XrefAnalyzer`
- [integration.md](integration.md) -- the other external surfaces
