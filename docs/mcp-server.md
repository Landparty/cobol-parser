# The MCP server

`cobol-parser mcp` lets an AI agent ask exact questions about COBOL source:
what a field is and where it is used, what is wrong with a program, what the
code at a cited line says, and, across the whole workspace, which programs
call a program and what a copybook or field change reaches. It speaks the
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
| `--root DIR` | `.` | The directory the server answers about. Paths outside it, and outside its copybook directories, are refused; see [What the server can read](#what-the-server-can-read). |
| `--cache-size N` | 32 | Parsed programs kept in memory. A program is parsed again when it, a copybook it expanded, or a copybook directory changes on disk (so a member added after a "COPY not expanded" caveat is picked up). |
| `--config FILE` / `--no-config` | `cobol.yml` in `--root` | Which `cobol.yml` to use. |

Copybook directories, source format and `>>DEFINE` symbols come from the
project's [`cobol.yml`](project-config.md) (or `cobol.yaml`) in `--root`.
Unlike the CLI, the server does not look for one in the directories above
the root. An edit to it takes effect on the next call, with no
restart (unless `--config` or `--no-config` was given). Without copybook
paths, every `COPY` is left unexpanded and each answer says so; a member that
cannot be found is left unexpanded and named, while the others still expand.

## What the server can read

The server is meant for agents reading code they did not write, where a
comment in the source can ask the agent to "check `~/.ssh/id_rsa`". And
`cobol.yml` is often part of that same code. So a file in the analysed tree
cannot make arbitrary files readable. The boundary is:

- **Under `--root`**: every file is readable. Paths are resolved first
  (symlinks included), so `../` and a symlink that leads out of the root are
  judged by where they really point.
- **`cobol.yml` is read from `--root` only.** A `cobol.yml` in a parent
  directory is ignored, unlike the CLI, which walks up to find one.
- **Under a copybook directory outside `--root`** (a shared copy library),
  only copybook members are readable. A member is a file named with one of
  the suffixes COPY resolution itself tries: `.cpy`, `.cbl`, `.cob` (any
  case), or no suffix at all, since COPY resolves extensionless members and
  mainframe downloads often have none. A file or subdirectory whose name
  starts with `.` is refused, so `.env` or `.git/` inside the library are not
  readable. Anything else there (`secret.txt`, `notes.md`) is refused with a
  "not a copybook member" error.
- **Some copybook directories are refused outright**: neither searched for
  COPY members nor readable. These are the filesystem root `/`; the home
  directory, or any directory that contains it; any directory that contains
  `--root`; any hidden directory (one with a `.`-named component, such as
  `~/.ssh`); and the system directories `/etc`, `/proc`, `/sys`, `/dev`,
  `/boot`, `/run` and `/var/run`, along with anything under them. The
  server prints one warning on stderr per refused directory. Every program
  with an unexpanded COPY gets an `unresolved-copybook` caveat naming the
  refused directories and why each was refused.
- **A library under the home directory is fine**, for example
  `~/copylib`. It still serves members only, and a dotfile beside it is
  outside it.

Extensionless members carry a cost. In a copybook directory outside the
root, any file without a suffix is readable. Point `copybook_path` only at
directories that hold copybooks.

The rules are the same whoever wrote the config: a `cobol.yml` in `--root`, a
`--config FILE` anywhere, or a `ProjectConfig` passed to `Workspace` from
Python.

## Tools

| Tool | Ask it |
|---|---|
| `program_brief(file, program?, limit?)` | "What is this program?" Size, entry points, the calling interface (USING parameters with direction and a `CALL` example), files with organization, keys and C/R/U/D use, SQL tables, called programs (including the possible targets of a dynamic `CALL` and CICS `LINK`/`XCTL`), CICS and DL/I commands, unreachable paragraphs, health grade and the five worst lint findings. Start here. |
| `explain_symbol(file, name, program?, limit?)` | "What is `CUST-BAL` and where is it used?" Gives the declaration (PICTURE, USAGE, byte offset and length, REDEFINES, level-88 values) and every reference with its role (read, write, condition, call argument, host variable, ...), statement and paragraph. A name that matches several declarations can be qualified as `X OF Y`. A special register such as `RETURN-CODE` is answered as one (`special_register: true`), not as a misspelling. |
| `callers_of(name, file?, program?, limit?)` | "Who runs `2100-VALIDATE`?" Every `PERFORM` (including a `PERFORM ... THRU` range it sits inside), `GO TO`, SORT/MERGE procedure, CICS `HANDLE`, SQL `WHENEVER` and fall-through into the paragraph or section, and whether it is reachable at all. A fall-through is cited at the header of the paragraph that falls in. For a program (no `file`, or a name that is no paragraph of `file`): every `CALL`, `EXEC CICS LINK` and `XCTL` to it from any program under the root, with the dynamic `CALL`s whose traced targets include it, the files that declare it, and the dynamic calls whose targets could not be traced. |
| `record_layout(file, record, program?, limit?)` | "What are the bytes of `CUST-REC`?" Every field in source order with level, PICTURE, USAGE, byte offset and length from the start of the 01 record, OCCURS, REDEFINES and level-88 values, each with where it is declared. A group inside a record, or an FD name for all of the file's records, works too. |
| `lint(file, rules?, min_severity?, limit?)` | "What is wrong with this program?" Dead code, unused data items, MOVE mismatches, I/O sequencing, LINKAGE problems, recursion risks, complexity, DCLGEN and SQL/CICS checks, worst first. |
| `read_source(file, line, before?, after?)` | "Show me the code at `COPYREPL.cbl:32`." Up to 200 numbered lines. |

### Across programs

These answer over every program under the root (by `cobol.yml`'s
`extensions`, default `.cbl`, `.cob` and `.cobol`; hidden directories and the
copybook directories are skipped).

| Tool | Ask it |
|---|---|
| `codebase_overview(limit?)` | "What is in this checkout?" Every program unit with its health grade and how many programs it calls and is called by; the call graph's entry programs, most-called programs, programs called but not present (vendor, system, or kept elsewhere) and call cycles; the most-used and missing copybooks; the worst health scores; and paragraphs duplicated between programs, most duplicated code first. |
| `impact_of_change(name, file?, program?, depth?, limit?)` | "What breaks if I change `CUSTREC`?" For a copybook member (a name a COPY names, or `CUSTREC.cpy`): every program that COPYs it, with the COPY lines, the programs that reach it through another member (with the chain), and the fields it declares. For a field (with `file`, or a name no COPY names): everything its value flows into, across programs, each hit with the path of statements that carries it. |
| `where_from(field, file?, program?, depth?, limit?)` | "Where does `FEE-FEE` come from?" The same paths, backward: every field, file, dataset, DB2 column and CALL argument that flows into it. |

Field flows cross programs through `CALL ... USING` arguments, DB2 columns,
and datasets. Datasets are joined through the JCL under the root (`.jcl` and
`.job` files), which needs the `[jcl]` extra (`pip install
'cobol-parser[jcl]'`); without it, or without JCL, a flow stops at the file it
is written to, and the caveats name each unbound file. `depth` caps how many
program boundaries a path may cross (`0` stays in the program).

The first cross-program call indexes every program under the root: on a
root of a few hundred programs that takes on the order of a minute. The
index is kept and reused until a program or copybook it read changes, or a
program is added or removed. Who-calls-what, field lineage and health are
three separate indexes, so asking only who calls a program never pays for
the other two. While an index is built the server sends MCP progress
notifications (one per file read, at most once a second) to a client that
asked for them, so a client that resets its timeout on progress keeps
waiting. A symlink under the root that leads outside it is skipped, as
`read_source` would refuse it.

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
  workspace, an unknown `program` or a `cobol.yml` that no longer reads,
  comes back as an error result naming the problem.

Each call runs on a worker thread, one at a time, so a long parse does not
stop the server from answering pings or a cancellation.

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

Business rules, record decoding, inline test fixtures, program diffs and
program slicing. See [the design plan](plans/2026-10-15-mcp-server-design.md).
