# The MCP server

`cobol-parser mcp` lets an AI agent ask exact questions about COBOL source:
what a field is and where it is used, what is wrong with a program, what the
code at a cited line says, and, across the whole workspace, which programs
call a program and what a copybook or field change reaches. It also extracts
a program's business rules, diffs two versions of a program, decodes data
files through a copybook and generates test data. It speaks the
[Model Context Protocol](https://modelcontextprotocol.io) over stdio, so any
MCP client can use it: Claude Code, Claude desktop, Cursor, or an Agent SDK
application.

It is read-only. It never changes a file and never runs anything from the
workspace: generated test data and decoded records come back in the answer.

## Install and connect

```bash
pip install 'cobol-parser[mcp]'
# with the JCL tools (jobs_running, dataset_users, jcl_job):
pip install 'cobol-parser[mcp,jcl]'
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
| `--tools SPEC` | `auto` | Which tools to offer. `auto` is the `core` group, plus the `jcl` group when the root holds a `.jcl` / `.job` / `.prc` / `.proc` file or `cobol.yml` names a `proc_path`. `all` offers every tool; otherwise give a comma-separated list of groups (`core`: the reading tools, `data`: `decode_record`, `gen_fixtures`, `diff_programs`, `jcl`: the JCL tools) and tool names. Each tool's definition is sent to the model on every turn, so a smaller set costs fewer input tokens. |
| `--max-answer-bytes N` | 24000 | Size budget of one tool result; `0` turns it off. See [Reading an answer](#reading-an-answer). |
| `--workers N` | CPUs, at most 8 | Processes that parse the root for the cross-program answers; `1` parses in the server itself. |
| `--cache-dir DIR` | `$XDG_CACHE_HOME/cobol-parser/mcp` (else `~/.cache/cobol-parser/mcp`) | Where what each program gave is kept between starts, one file per root. It is only ever read from a directory you chose, never from under the root. |
| `--no-disk-cache` | | Keep that in memory only: every start parses the whole root. |
| `--no-warm-up` | | Do not parse the root at start; the first cross-program question does it. |
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
| `callers_of(name, file?, program?, limit?)` | "Who runs `2100-VALIDATE`?" Every `PERFORM` (including a `PERFORM ... THRU` range it sits inside), `GO TO`, SORT/MERGE procedure, CICS `HANDLE`, SQL `WHENEVER` and fall-through into the paragraph or section, and whether it is reachable at all (the same answer as `dead-code`). A fall-through out of a paragraph that is only ever `PERFORM`ed is not listed: control returns to the performer instead. A fall-through is cited at the header of the paragraph that falls in. For a program (no `file`, or a name that is no paragraph of `file`): every `CALL`, `EXEC CICS LINK` and `XCTL` to it from any program under the root, with the dynamic `CALL`s whose traced targets include it, the files that declare it, and the dynamic calls whose targets could not be traced. |
| `record_layout(file, record, program?, limit?)` | "What are the bytes of `CUST-REC`?" Every field in source order with level, PICTURE, USAGE, byte offset and length from the start of the 01 record, OCCURS, REDEFINES and level-88 values, each with where it is declared. A group inside a record, or an FD name for all of the file's records, works too. |
| `lint(file, rules?, min_severity?, limit?)` | "What is wrong with this program?" Dead code, unused data items, MOVE mismatches, I/O sequencing, LINKAGE problems, recursion risks, complexity, DCLGEN and SQL/CICS checks, worst first. |
| `read_procedure(file, name, program?)` | "Show me `2100-VALIDATE`." One whole paragraph or section, from its header to the line before the next one (for a section, the next section), numbered. Lines a COPY brought in are a segment of their own, cited in the copybook. At most 300 lines. |
| `find_statements(verb?, operand?, role?, literal?, paragraph?, file?, program?, limit?)` | "Every `WRITE` of `REPORT-REC`", "every `EXEC CICS LINK`", "who sets `WS-EOF`?" Searches the parsed statements, so a statement in a copybook is found and a comment is not. `verb` matches a verb or the start of one (`EXEC CICS`, `EXEC SQL SELECT`), `operand` a data or file name the statement uses (qualified or not; `role` narrows it to read, write, condition, ...), `literal` text on the statement's first line, `paragraph` its paragraph. Every filter given must match. Without `file`, it searches every program under the root through an index built on first use. |
| `read_source(file, line, before?, after?)` | "Show me the code at `COPYREPL.cbl:32`." Up to 200 numbered lines, always including `line` itself: a larger window is cut from the far end of `before` first. |

### Beyond reading code

| Tool | Ask it |
|---|---|
| `business_rules(file, program?, kind?, procedure?, include_technical?, limit?)` | "What business rules does this program implement?" Every IF / EVALUATE / SEARCH as a decision table (one branch per condition, with the actions it runs and their lines), promoted to a `validation` when a branch rejects input, and paragraph-level arithmetic as a `calculation` with its formula. Each rule has its inputs and outputs, the conditions that guard it (`guards`), the branches elsewhere that PERFORM its paragraph (`reached_via`) and why it was classified as it was; level-88 names it tests are spelled out under `condition_names`. File status, end-of-file and SQLCODE / EIB checks are counted but left out unless `include_technical` is true. `kind` and `procedure` narrow the list; the `summary` always counts the whole program. |
| `diff_programs(old_file, new_file, old_program?, new_program?, category?, rename_threshold?, limit?)` | "What changed between these two versions?" The behaviour, not the lines: PROGRAM-ID and USING interface, files (organization, keys, status), data items (PICTURE, USAGE, VALUE, OCCURS, REDEFINES, level-88 values, field order with the byte offsets before and after), paragraphs added, removed, renamed (by body similarity, `rename_threshold`) or moved, and changed statements (PERFORM and CALL targets, MOVE targets, conditions). Each side is cited in its own file. Reformatting, comments and sequence numbers are no change. |
| `decode_record(copybook, data_file?, record?, view?, skip?, max_records?, fields?, charset?, endian?, record_format?, record_separator?, record_length?, limit?)` | "What does this record image say?" Reads a data file under the root through a copybook's (or a program's) byte layout: the fields with offsets once, then each record's values, with bytes that do not decode as their PICTURE reported per record under `errors`. COMP-3, binary, zoned and signed fields, ASCII or EBCDIC, fixed or RDW-framed variable records. `charset`, `endian`, `record_format` and `record_separator` default to `cobol.yml`'s `data:` section. Pages of 10 records (`max_records`, `skip`, and `next` says where the next page starts); at most the first 16 MiB of a file are read. `view` reads the same bytes through a REDEFINES overlay; without `data_file`, the answer is the layout and its views alone. |
| `gen_fixtures(file, program?, mode?, seed?, rows?, scenario?, limit?)` | "Give me test data for this program." The `gen-fixtures` bundle, inline: scenarios (`happy`: one; `branches`: one per reachable branch arm; `all`: those plus empty-input, error-status and boundary-value scenarios), each with the values every mocked boundary supplies (file records as `columns` and `rows`, CALL parameters, SQL rows, CICS data, FILE STATUS / SQLCODE) and the expectations to assert (`call_count`, constant-folded `field_equals`). A branch scenario carries a `verification` saying whether its own data reaches the branch it is named for, and `arm_coverage` lists every arm no scenario reaches, with the reason. Deterministic: the seed defaults to `cobol.yml`'s `seed`, else 0. `rows` (default 3) is per READ / FETCH sequence. `cobol-parser gen-fixtures` writes the full bundle to disk. |

`gen_fixtures` searches `cobol.yml`'s `callee_path` for the programs a CALL
names, to read their USING parameters; a callee directory outside the root
is skipped with a caveat.

### Across programs

These answer over every program under the root (by `cobol.yml`'s
`extensions`, default `.cbl`, `.cob` and `.cobol`; hidden directories and the
copybook directories are skipped).

| Tool | Ask it |
|---|---|
| `codebase_overview(limit?)` | "What is in this checkout?" Every program unit with its health grade and how many programs it calls and is called by; the call graph's entry programs, most-called programs, programs called but not present (vendor, system, or kept elsewhere), programs called whose source is under the root in a language the tools do not parse (assembler, PL/I, BMS, REXX, C, Easytrieve; matched by file name and, for assembler, `CSECT` and `ENTRY` names) and call cycles; the most-used and missing copybooks; the worst health scores; and paragraphs duplicated between programs, most duplicated code first. |
| `impact_of_change(name, file?, program?, depth?, limit?)` | "What breaks if I change `CUSTREC`?" For a copybook member (a name a COPY names, or `CUSTREC.cpy`): every program that COPYs it, with the COPY lines, the programs that reach it through another member (with the chain), and the fields it declares. For a field (with `file`, or a name no COPY names): everything its value flows into, across programs, each hit with the path of statements that carries it. |
| `where_from(field, file?, program?, depth?, limit?, full_paths?)` | "Where does `FEE-FEE` come from?" The same paths, backward: every field, file, dataset, DB2 column and CALL argument that flows into it. |

Both lineage answers list exact hits first, count them by confidence
(`by_confidence`), and name the `trail_ends`: the hits no other trail runs
through, which for `where_from` are the original sources. A hit whose path
begins with an earlier hit's path names that hit (`from_hit`, 0-based) and
how many of its steps it shares (`after_step`), and lists only the rest;
`full_paths: true` gives every path whole. A hit with `may_be_overwritten`
names a statement that replaces the value on the way, in the same paragraph,
before the path reads it again: `MOVE A TO WS-X`, then `MOVE B TO WS-X`,
then `DISPLAY WS-X` does not display A. Such hits come after the others of
their confidence, and the answer counts them; they stay listed because a
`SELECT INTO` that finds no row, or a `READ INTO` at end of file, leaves the
old value in place.

Field flows cross programs through `CALL ... USING` arguments, DB2 columns,
and datasets. Datasets are joined through the JCL under the root (`.jcl` and
`.job` files), which needs the `[jcl]` extra (`pip install
'cobol-parser[jcl]'`); without it, or without JCL, a flow stops at the file it
is written to, and the caveats name each unbound file. A step that runs a
cataloged PROC (`EXEC REPROC`) is expanded from the same procedure libraries
the JCL tools below read, all inside the root; otherwise the caveats say
which PROC was not found. An IDCAMS step
whose commands are read from a dataset rather than in-stream `SYSIN` is not
traced, and the caveats name that dataset. `depth` caps how many
program boundaries a path may cross (`0` stays in the program).

Cross-program answers come from every program under the root, each parsed
once: who-calls-what, field lineage, health and the statement search all
take what they need from that one parse. The server starts parsing the root
in the background as soon as it starts (`--no-warm-up` turns that off), in
several processes (`--workers`), so the first cross-program question
usually finds the work done or under way; on an 80-program root that is
about 10 seconds in one process and 3 with four. What each file gave is kept
on disk (`--cache-dir`), so a restarted server answers at once and parses
only the files that changed since. After an edit, only the changed program
(or the programs that COPY the changed copybook) is parsed again. While the
root is read the server sends MCP progress
notifications (one per file read, at most once a second) to a client that
asked for them, so a client that resets its timeout on progress keeps
waiting. A symlink under the root that leads outside it is skipped, as
`read_source` would refuse it.

### How programs are run (JCL)

These read the JCL under the root (`.jcl` and `.job` files) and need the
`[jcl]` extra (`pip install 'cobol-parser[jcl]'`). Without it each answers
with a tool error naming that command, never with an empty answer that would
read as "no JCL". In-stream procedures are always expanded, and cataloged ones are
looked up like a PROCLIB concatenation, first member of a name winning:

1. the libraries the job's own `JCLLIB ORDER=` names, each a folder under the
   root named exactly as the library (`PROD.MY.PROCS/`);
2. the folders `cobol.yml` lists as `project.proc_path`, and any folder whose
   name contains `PROCLIB` (`SYS1.PROCLIB/`);
3. every other folder holding a `.prc` / `.proc` member.

Members are files named after the procedure: in the first two kinds of
folder with no suffix, `.prc`, `.proc`, `.jcl` or `.cntl` (a `.jcl` file
there is a procedure, not a job); elsewhere only `.prc` / `.proc`, so a
program source of the same name is never read as one. Symbolic parameters
(`&HLQ`) are substituted from the `EXEC` and the `PROC` defaults, nested
procedures are expanded too, and `jcl_job` lists the `procedure_libraries` it
searched. A `JCLLIB` library with no folder under the root is a caveat. A
step expanded from a cataloged procedure is cited in the member, and an
override DD coded on the invocation in the job file. An IBM-supplied procedure found in none of
those (`DLIBATCH`, `IMSBATCH`, `DBBBATCH`, `DSNUPROC`, `IGYWCL`, ...) is
expanded from jcl-parser's generic template of it, so `EXEC DLIBATCH,MBR=PROG`
still counts as a step running `PROG`. The template is not your PROCLIB
member, so each such answer carries an `incomplete-analysis` caveat saying
so, and the template's own DD cards are cited at no line; put the real member
under the root for an exact answer.

| Tool | Ask it |
|---|---|
| `jobs_running(program, limit?)` | "How is `INVUPDT` run?" Every step that runs the program (`PGM=`, or launched through IKJEFT01's `RUN PROGRAM` or DFSRRC00's `PARM`), with its PARM, condition and DD statements. When the program's source is under the root (a file named after it, else the program whose PROGRAM-ID it is), its `files` list each `SELECT` with its DD name, each DD row says which COBOL file it backs (`cobol_files`), and `dds_not_coded` lists the files the step gives no DD (OPTIONAL files and SORT work files left out). |
| `dataset_users(dataset, limit?)` | "Who reads or writes `PROD.INV.MASTER`?" Every DD naming the dataset: file, job, step, programs, DD name, DISP, and what the step does with it (`access`), with `by_access` grouping the programs. `access` comes from the program when its COBOL source is under the root (its OPEN mode for that DD: `read`, `write`, `update`, `extend`, or `create` when DISP=NEW), from the utility for SORT, IEBGENER, ICETOOL and IDCAMS REPRO (which DD it reads and which it writes), and otherwise from DISP alone (`read` SHR, `exclusive` OLD, `create` NEW, `extend` MOD); `access_from` says which (`program`, `utility`, `disp`), so a DISP=SHR dataset a program opens OUTPUT reads as a write. A GDG generation or member is matched by its base name unless the name you give has one. Wildcards follow z/OS dataset filters: `%` is one character, `*` any characters within one qualifier (`PROD.INV.*`), `**` any number of qualifiers (`PROD.**`, `**.MASTER`). |
| `jcl_job(file, job?, step?, limit?)` | "What does this JCL do?" One file's jobs and steps: program, PARM, COND / IF condition, every DD (dataset, DISP, SYSOUT, DUMMY, in-stream data with its first lines, RECFM / LRECL, concatenations), the procedures expanded and where they were read, the `SET` symbols, and `program_sources`: the COBOL file under the root for each program run. |

The JCL is parsed once and kept until a JCL file or procedure member changes.

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
  500), with its true total. The server also keeps each result under a size
  budget (`--max-answer-bytes`, default 24000, about 6k tokens): while a
  result is over it, its longest list is halved from the end, and the cut is
  listed here with `"reason": "answer budget"`.
- **Next** (`next`, when present) lists one or two ready-made calls that
  usually answer the follow-up question, such as
  `read_source(file="ORDEDIT.cbl", line=75)` after `explain_symbol`. They
  only name tools the server offers. They are suggestions, not facts.
- A request that cannot be answered at all, such as a path outside the
  workspace, an unknown `program` or a `cobol.yml` that no longer reads,
  comes back as an error result naming the problem.

Each call runs on a worker thread, one at a time, so a long parse does not
stop the server from answering pings or a cancellation.

`surface_version` changes whenever a tool, argument or envelope field changes
in a way a client could notice.

## Prompts

The server also offers prompts, for clients that show them as a menu (`/`
commands in Claude Code). Each one asks for a task and spells out which tools
to call and how to cite the answer, the way the `cobol-analysis` skill does
for clients that have skills:

| Prompt | Arguments | Asks for |
|---|---|---|
| `explain_program` | `file`, `program?` | What a program does, for someone new to it |
| `review_program` | `file`, `program?` | Defects and risks, worst first, each confirmed in the source |
| `plan_change` | `name`, `file?` | Everything a change to a field or copybook reaches |
| `document_business_rules` | `file`, `program?` | The program's business rules in plain language |
| `onboard_codebase` | none | An overview of the whole workspace |

## Using the tools from Python

The tools do not need the MCP SDK. The backend, an editor extension or a
script can call them directly and get the same dicts:

```python
from cobolparser.mcp import CobolTools, Workspace

tools = CobolTools(Workspace("/path/to/checkout"))
tools.explain_symbol("src/ACCTUPD.cbl", "CUST-BAL")
```

## Coming next

Program slicing (only the statements that can affect a field), once the
library has it. See [the design plan](plans/2026-10-15-mcp-server-design.md).
