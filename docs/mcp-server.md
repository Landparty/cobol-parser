# The MCP server

`cobol-parser mcp` lets an AI agent ask exact questions about COBOL source:
what a field is and where it is used, what is wrong with a program, and what
the code at a cited line says. It speaks the
[Model Context Protocol](https://modelcontextprotocol.io) over stdio, so any
MCP client can use it: Claude Code, Claude desktop, Cursor, or an Agent SDK
application.

It is read-only. It never changes a file and never runs anything from the
workspace.

## Install and connect

```bash
pip install 'cobol-parser[mcp]'
```

Claude Code:

```bash
claude mcp add cobol -- cobol-parser mcp --root /path/to/checkout
```

Any client that takes a JSON server list (Claude desktop's
`claude_desktop_config.json`, Cursor's `mcp.json`):

```json
{
  "mcpServers": {
    "cobol": {
      "command": "cobol-parser",
      "args": ["mcp", "--root", "/path/to/checkout"]
    }
  }
}
```

| Flag | Default | Meaning |
|---|---|---|
| `--root DIR` | `.` | The directory the server answers about. Paths outside it, and outside its copybook directories, are refused. |
| `--cache-size N` | 32 | Parsed programs kept in memory. A program is parsed again when it, a copybook it expanded, or a copybook directory changes on disk (so a member added after a "COPY not expanded" caveat is picked up). |
| `--config FILE` / `--no-config` | search from `--root` | Which `cobol.yml` to use. |

Copybook directories, source format and `>>DEFINE` symbols come from the
project's [`cobol.yml`](project-config.md), found from `--root` the same way
the CLI finds it. It is read once when the server starts; restart the server
after editing it. Without copybook paths, every `COPY` is left unexpanded and
each answer says so.

## Tools

| Tool | Ask it |
|---|---|
| `explain_symbol(file, name, program?, limit?)` | "What is `CUST-BAL` and where is it used?" Gives the declaration (PICTURE, USAGE, byte offset and length, REDEFINES, level-88 values) and every reference with its role (read, write, condition, call argument, host variable, ...), statement and paragraph. A name that matches several declarations can be qualified as `X OF Y`. |
| `lint(file, rules?, min_severity?, limit?)` | "What is wrong with this program?" Dead code, unused data items, MOVE mismatches, I/O sequencing, LINKAGE problems, recursion risks, complexity, DCLGEN and SQL/CICS checks, worst first. |
| `read_source(file, line, before?, after?)` | "Show me the code at `COPYREPL.cbl:32`." Up to 200 numbered lines. |

## Reading an answer

Every tool returns the same envelope:

```json
{
  "surface_version": "1",
  "answer": {"...": "the tool's own result"},
  "caveats": [
    {"kind": "unresolved-copybook",
     "detail": "COPY CUSTREC was not expanded; its content is omitted from the parsed program",
     "effect": "declarations from that member are missing; unused and undeclared names are unreliable"}
  ],
  "truncated": [{"field": "findings", "shown": 50, "total": 212}],
  "program": {"file": "src/ACCTUPD.cbl", "program_id": "ACCTUPD"}
}
```

- **Locations** are `{"file", "line", "column"?}` in the file on disk,
  relative to the root. A declaration that came from a copybook names the
  copybook, not the program that copied it. A location that cannot be traced
  back to a file is `null`, with an `unmapped-location` caveat, rather than a
  guessed line.
- **Caveats** say what could not be checked. Their `kind` is one of
  `unresolved-copybook`, `partial-parse`, `analyzer-failed`,
  `incomplete-analysis`, `ambiguous-name`, `duplicate-declaration`,
  `unmapped-location` and `program-unit-selected`. A quiet answer with a
  caveat is not a clean one.
- **Truncated** lists every list that was cut to `limit` (default 50, at most
  500), with its true total.
- A request that cannot be answered at all, such as a path outside the
  workspace or an unknown `program`, comes back as an error result naming the
  problem.

`surface_version` changes whenever a tool, argument or envelope field changes
in a way a client could notice.

## Using the tools from Python

The tools do not need the MCP SDK. The backend, an editor extension or a
script can call them directly and get the same dicts:

```python
from cobolparser.mcp import CobolTools, Workspace

tools = CobolTools(Workspace("/path/to/checkout"))
tools.explain_symbol("src/ACCTUPD.cbl", "CUST-BAL")
```

## Coming next

Program briefs, paragraph callers and record layouts, then cross-program
questions (who calls this program, what a field change affects). See
[the design plan](plans/2026-10-15-mcp-server-design.md).
