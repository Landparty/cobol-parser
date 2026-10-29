# cobol-parser

A COBOL parser for Python with an IBM Enterprise COBOL focus. It turns COBOL
source into a traversable AST (JSON export, error recovery, copybook
expansion with a source map back to the original lines), and builds static
analyzers, test-data generators, a z/OS JCL front end and an MCP server for AI
agents on top of it.

458 of the 459 NIST COBOL-85 programs in `examples/cobol/` parse cleanly (the
one that does not, SM101A, needs its copybooks expanded first).

[![Python 3.11+](https://img.shields.io/badge/python-3.11%20%7C%203.12%20%7C%203.13-blue.svg)](https://www.python.org/downloads/)
[![PyPI](https://img.shields.io/pypi/v/cobol-parser.svg)](https://pypi.org/project/cobol-parser/)
[![Coverage](https://img.shields.io/badge/coverage-90%25%20enforced-green.svg)](.okf/tests.md)
[![License: AGPL v3](https://img.shields.io/badge/License-AGPL_v3-blue.svg)](LICENSE)

## Install

```bash
pip install cobol-parser                # the library and the cobol-parser CLI
pip install 'cobol-parser[mcp]'         # plus the MCP server
pip install 'cobol-parser[jcl]'         # plus JCL (through jcl-parser)
```

Requires Python 3.11, 3.12 or 3.13. The core library has no runtime
dependencies. Optional extras:

| Extra | Adds |
|---|---|
| `mcp` | `cobol-parser mcp`, the MCP server ([docs/mcp-server.md](docs/mcp-server.md)) |
| `jcl` | `cobol-parser jcl`, and the JCL joins in `field-impact`, `widen-check` and the MCP server |
| `pl1`, `hlasm` | PL/I and assembler programs in the MCP server's call graph |
| `fast` | Cython, to build the optional accelerators from source |
| `dev`, `docs` | the test, lint and docs toolchain for working on this repo |

To get the CLI on your `PATH` without a project virtualenv:

```bash
uv tool install cobol-parser
uv tool install --editable .   # from a clone, picking up code changes
```

The install is pure Python by default. The PyPI wheels also carry three
compiled Cython accelerators (about 3x lexer throughput), used only when
`COBOLPARSER_ACCEL=1` is set at run time. From a clone, the same variable at
build time compiles them:

```bash
pip install -e ".[fast]"
COBOLPARSER_ACCEL=1 python setup.py build_ext --inplace
export COBOLPARSER_ACCEL=1
```

## Quick start

```python
from cobolparser import parse_cobol

result = parse_cobol(source, filename="prog.cbl")
if result.success:
    print(result.ast.program_name)
    print(result.ast.to_json())
for error in result.errors:
    print(error)
```

`parse_cobol` stops at the first error by default. To collect every error and
keep going, use `CobolParser(error_recovery=ErrorRecoveryMode.COLLECT_ALL)`.
To expand `COPY` statements, use `parse_cobol_with_expansion(source,
"prog.cbl", copybook_paths=["copybooks"])`.

Every analyzer has the same shape, `<Analyzer>().analyze(ast)`, and returns a
report with `to_dict()`:

```python
from cobolparser import LintAnalyzer, parse_cobol

report = LintAnalyzer().analyze(parse_cobol(source, filename="prog.cbl").ast)
for finding in report.findings:
    print(finding.rule, finding.severity, finding.message)
```

## What it does

The CLI has one subcommand per analyzer or generator. Every subcommand emits
JSON by default, and takes `--help` with examples and its exit codes. The full
list, with every flag, is in [.okf/cli.md](.okf/cli.md#subcommand-reference).

### Check a program

```bash
cobol-parser lint prog.cbl --format text
```

```text
prog.cbl:5:8: warning [unused-variables] WORKING-STORAGE item WS-NEVER-USED (level 01) is never referenced in the PROCEDURE DIVISION
prog.cbl:10:12: error [move-type-check] Illegal MOVE: cannot move NUMERIC item 'WS-COUNTER' to ALPHABETIC item 'WS-ALPHA'
prog.cbl:12:8: warning [dead-code] paragraph ORPHAN-PARA can never be reached
3 finding(s): 1 error, 2 warning, 0 info (9 rule(s) ran)
```

`lint` runs nine analyzers over one parse: dead code, unused variables, MOVE
type checks, I/O sequencing, LINKAGE checks, recursion risk, complexity,
DCLGEN and SQL/CICS checks. `--rule` narrows the run, `--min-severity` the
output, and `--fail-on error` exits 3 when a finding at that severity was
reported, so it can gate a build. Each analyzer is also its own subcommand
(`dead-code`, `xref`, `program-flow`, `complexity`, `health`, ...).

### Check a whole codebase

```bash
cobol-parser scan --glob 'src/**/*.cbl' --analyzer health --clones --cache-dir .cache
cobol-parser call-check src/ --copybook-path copybooks --fail-on error
cobol-parser codebase-graph src/ --format mermaid
```

- `scan` runs analyzers over many files in one process, with per-file fault
  isolation and cross-file duplicate-paragraph detection. With `--cache-dir`,
  a file whose source, copybooks and copybook directories are unchanged reuses
  its report from the last run.
- `call-check` checks every `CALL` against the `PROCEDURE DIVISION USING` or
  `ENTRY` it reaches in another file: argument count, passing mode
  (`BY VALUE` / `BY REFERENCE`), byte length, USAGE and `RETURNING`. A
  dynamic `CALL` is checked against every target its variable can hold.
- `codebase-graph` and `copybook-impact` give the call graph and the programs
  each copybook reaches.

### Plan a change

```bash
cobol-parser lineage prog.cbl --field CUST-BAL
cobol-parser field-impact CUST-ID src/ --jcl jcl/
cobol-parser widen-check CUST-ID src/ --to '9(9)'
cobol-parser diff old/prog.cbl new/prog.cbl
```

- `lineage` follows one field's values through a program, and `field-impact`
  follows them across programs, files, DB2 columns and JCL datasets.
- `widen-check` answers "what breaks if `CUST-ID` becomes `PIC 9(9)`": every
  field downstream that would truncate the wider value, and, when the byte
  length changes, the records whose later fields shift, the `REDEFINES` that
  overlay it, the files whose LRECL changes (and the other programs reading
  the same dataset), and the CALL / LINKAGE records on both sides.
- `diff` compares two versions by structure, so reformatting and sequence
  numbers are no change.

### SARIF for code scanning

`lint`, `call-check` and `scan` take `--format sarif` and write a SARIF 2.1.0
log, which GitHub code scanning and IDE problem panes read directly:

```bash
cobol-parser lint prog.cbl --format sarif -o lint.sarif
cobol-parser scan --glob 'src/**/*.cbl' --format sarif -o scan.sarif
```

### Generate and read test data

```bash
cobol-parser gen-data CUSTOMER.cpy --rows 100 --seed 7 -o customers.csv
cobol-parser decode CUSTMAST.dat --copybook CUSTOMER.cpy --charset ebcdic
cobol-parser compare expected.dat actual.dat --copybook CUSTOMER.cpy --key CUST-ID
cobol-parser gen-fixtures prog.cbl --scenarios all -o bundle.json
```

`gen-data` writes synthetic records that fit each field's PICTURE, USAGE and
level-88 values (a `seed` makes the output byte-identical across runs).
`decode` and `compare` read record images, ASCII or EBCDIC, fixed or
variable-length. `gen-fixtures` builds a test bundle for a whole program: one
scenario per reachable branch, the values each mocked file, CALL, SQL or CICS
boundary supplies, and the expectations to assert. Its schema is in
[docs/fixture-bundle-schema.md](docs/fixture-bundle-schema.md).

### Give an AI agent exact answers

```bash
pip install 'cobol-parser[mcp]'
claude mcp add cobol -- cobol-parser mcp --root /path/to/checkout
```

`cobol-parser mcp` is a read-only Model Context Protocol server. Its tools
answer "what is this program", "what is this field and where is it used",
"who calls this", "what does a change to this copybook reach" and "show me
this paragraph", with a `file:line` for every fact and a list of what they
could not check. See [docs/mcp-server.md](docs/mcp-server.md).

The repo also ships a `cobol-analysis` agent skill
([.claude/skills/cobol-analysis/SKILL.md](.claude/skills/cobol-analysis/SKILL.md))
that teaches an agent which subcommand answers which question.

### Project config

A `cobol.yml` at the project root sets copybook directories, source format,
`>>DEFINE` symbols, data encodings and lint defaults once, for every
subcommand. `cobol-parser config` shows which file is in effect. See
[docs/project-config.md](docs/project-config.md).

## Language coverage

IBM Enterprise COBOL through 6.4: fixed and free format, `COPY ... REPLACING`
and `REPLACE`, conditional compilation (`>>DEFINE`, `>>IF`, `>>EVALUATE`),
nested and contained programs, object-oriented `CLASS-ID` / `METHOD-ID`,
user-defined functions (`FUNCTION-ID`), DECLARATIVES, Report Writer, XML and
JSON statements, and `EXEC SQL`, `EXEC CICS` and `EXEC DLI` blocks. One
program per IBM program type (batch, VSAM, CICS, IMS, DB2, MQ, ...) runs
through the whole stack in the test suite; the matrix is in
[docs/enterprise-program-types.md](docs/enterprise-program-types.md).

## Documentation

| For | Read |
|---|---|
| Using the MCP server | [docs/mcp-server.md](docs/mcp-server.md) |
| The `cobol.yml` project config | [docs/project-config.md](docs/project-config.md) |
| The `gen-fixtures` bundle format | [docs/fixture-bundle-schema.md](docs/fixture-bundle-schema.md) |
| Every subcommand and flag | [.okf/cli.md](.okf/cli.md) |
| How the library works, area by area | [.okf/index.md](.okf/index.md) |
| What the backend and mocky-mock rely on | [interface-contract.md](interface-contract.md) |
| What changed in each release | [CHANGELOG.md](CHANGELOG.md) |
| Everything under `docs/`, including design plans | [docs/README.md](docs/README.md) |

The `.okf/` folder is the reference documentation: one topic file per area
(lexer, parser, analyzers, generators, CLI, MCP, tests), written so that a
person or an AI agent loads only the file for the task at hand.
`scripts/okf_check.py` checks what those files claim against the code.

## Development

```bash
pip install -e ".[dev,docs]"
git config core.hooksPath .githooks              # the OKF pre-commit check

python -m pytest tests/ -q -n 4 --no-cov         # fast full run
python -m pytest tests/                          # with the 90% coverage floor
COBOLPARSER_PERF=1 python -m pytest tests/performance/test_large_program.py   # 40k-line perf lane

python -m ruff check .
python -m black .
python -m mypy cobolparser/
```

CI is currently switched off (`.github/workflows/ci.yml` is commented out), so
run lint, types and the full suite locally before pushing. Measure coverage on
the pure-Python build: with `COBOLPARSER_ACCEL=1`, coverage.py cannot see the
code the compiled modules replace. Test layout and markers:
[.okf/tests.md](.okf/tests.md).

## License

GNU Affero General Public License v3.0 or later. Copyright © 2026 Samuel Dion.
See [LICENSE](LICENSE).
