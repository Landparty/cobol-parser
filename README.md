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

## Contents

- [Install](#install)
- [Quick start](#quick-start)
- [Every command, with an example](#every-command-with-an-example)
  - [Parse and preprocess](#parse-and-preprocess)
  - [Lint and CI](#lint-and-ci)
  - [Analyze one program](#analyze-one-program)
  - [Analyze a codebase](#analyze-a-codebase)
  - [Test data](#test-data)
  - [Reference and integrations](#reference-and-integrations)
  - [Exit codes](#exit-codes)
- [The Python API, with examples](#the-python-api-with-examples)
- [Language coverage](#language-coverage)
- [Documentation](#documentation)
- [Development](#development)

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

```bash
cobol-parser parse src/ORDPOST.cbl --copybook-path copybooks -o ordpost.json
cobol-parser lint src/*.cbl --format text --fail-on error
cobol-parser --help                  # every command, grouped by task
cobol-parser lint --help             # every flag of one command, with examples
```

```python
from cobolparser import parse_cobol

result = parse_cobol("src/ORDPOST.cbl")      # a path, or the source text itself
if result.success:
    print(result.ast.program_name)           # ORDPOST
for error in result.errors:
    print(error)
```

## Every command, with an example

`cobol-parser` has <!-- okf:gen cli-subcommand-count -->41<!-- /okf:gen -->
subcommands, one per analyzer or generator. Every one writes JSON to stdout
by default (`-o FILE` writes a file, `--compact` drops the indentation), and
`cobol-parser <command> --help` lists all its flags with more examples. The full flag reference is the generated table in
[.okf/cli.md](.okf/cli.md#subcommand-reference).

The examples below are run from the root of a project laid out like this.
The `cobol.yml` saves passing `--copybook-path copybooks` and
`--proc-path proclib` to every command (a flag on the command line always
wins over it):

```text
cobol.yml          copybook_path: [copybooks], proc_path: [proclib]
src/               ORDEDIT.cbl ORDVAL.cbl ORDPOST.cbl POSTDOM.cbl POSTINTL.cbl ...
copybooks/         ORDREC.cpy HISTREC.cpy ADDRREC.cpy ...
jcl/               ORDNIGHT.jcl ORDMONTH.jcl
proclib/           ORDEDITP ORDRPTP          (cataloged PROCs)
```

```yaml
# cobol.yml
version: 1
project:
  copybook_path: [copybooks]
  proc_path: [proclib]
```

The order programs come from [tests/eval/shop/](tests/eval/shop/), and the
SQL, CICS, IMS and LE examples use the programs in
[tests/samples/enterprise/](tests/samples/enterprise/).
[tests/test_readme_examples.py](tests/test_readme_examples.py) builds this
project from them and runs every example in this section and the next.

Flags most commands share: `--copybook-path DIR` (repeatable),
`--define SYMBOL[=VALUE]` for `>>DEFINE`, `--source-format auto|fixed|free`,
`--encoding ENC`, `--program NAME` (pick one unit of a nested program),
`--error-recovery fail-fast|collect-all` (the CLI defaults to `collect-all`)
and, on any command, `--config FILE` / `--no-config`.

### Parse and preprocess

| Command | What it gives you |
|---|---|
| `parse` | The whole program as AST JSON (`--find-type` to keep one node type, `--errors`, `--stats`) |
| `batch` | Many programs parsed in parallel, one JSON entry per file |
| `expand` | The source with every `COPY` expanded, and optionally a map back to the original lines |
| `preprocess` | Fixed-format source turned into free-form text (columns 8-72, continuations merged) |
| `tokenize` | The lexer's token stream |

```bash
cobol-parser parse src/ORDPOST.cbl -o ordpost.json
cobol-parser parse src/ORDPOST.cbl --find-type CallStatement
cobol-parser batch --glob 'src/*.cbl' --workers 4 -o asts.json
cobol-parser expand src/ORDPOST.cbl --source-map
cobol-parser preprocess src/ORDPOST.cbl --define DEBUG
cobol-parser tokenize src/ORDPOST.cbl
```

`cobol-parser src/ORDPOST.cbl`, with no command, is `parse`.

### Lint and CI

| Command | What it gives you |
|---|---|
| `lint` | Every checker in one pass, one severity-graded finding list (`json`, `text`, `sarif`, `github`) |
| `scan` | Analyzers over a whole source tree, with per-file fault isolation, cross-file duplicate paragraphs and an on-disk cache |
| `config` | The `cobol.yml` in effect, and where it came from |

```bash
cobol-parser lint src/ORDPOST.cbl --format text
cobol-parser lint src/*.cbl --format text --min-severity warning --fail-on error
cobol-parser lint --glob 'src/**/*.cbl' --rule dead-code --rule move-type-check
cobol-parser lint src/ORDRPT.cbl src/ORDEDIT.cbl --rule truncation --rule file-status --format text
cobol-parser lint src/ORDPOST.cbl --callee-path src --format text   # also checks each CALL against its callee
cobol-parser lint --changed-since origin/main --format github --fail-on error
cobol-parser lint --new-code-since origin/main --scope call-check=all --format github --fail-on error
cobol-parser lint src/*.cbl --format sarif -o lint.sarif
cobol-parser lint --glob 'src/**/*.cbl' --write-baseline lint-baseline.json
cobol-parser lint --glob 'src/**/*.cbl' --baseline lint-baseline.json --fail-on warning
cobol-parser scan --glob 'src/*.cbl' --analyzer health --clones --cache-dir .cache
cobol-parser scan src/*.cbl --format sarif -o scan.sarif
cobol-parser config
```

```text
$ cobol-parser lint src/ORDPOST.cbl --format text
src/ORDPOST.cbl:54:8: warning [dead-code] paragraph 9000-OLD-RECALC can never be reached
src/ORDPOST.cbl:56:8: warning [dead-code] paragraph 9100-OLD-AUDIT can never be reached
2 finding(s): 0 error, 2 warning, 0 info (17 rule(s) ran)
```

```text
$ cobol-parser lint src/ORDRPT.cbl src/ORDEDIT.cbl --rule truncation --rule file-status --format text
src/ORDRPT.cbl:35:12: warning [truncation] MOVE WS-TOTAL (signed 11 integer + 2 decimal digits) TO RPT-TOTAL (signed 10 integer + 2 decimal digits) loses high-order digits
src/ORDRPT.cbl:36:12: warning [truncation] MOVE WS-FEES (signed 7 integer + 2 decimal digits) TO RPT-FEES (signed 6 integer + 2 decimal digits) loses high-order digits
src/ORDEDIT.cbl:7:12: warning [file-status] file ORDER-IN declares FILE STATUS WS-IN-STAT, but the program never tests it: a failed OPEN, READ or WRITE goes unnoticed
...
5 finding(s) in 2 file(s): 0 error, 5 warning, 0 info
```

`lint` runs nine analyzers over one parse: dead code, unused variables, MOVE
type checks, I/O sequencing, LINKAGE checks, recursion risk, complexity,
DCLGEN and SQL/CICS checks, plus `line-length` (fixed-format text past
column 80, or a word cut at column 72, in the program and its copybooks).
Seven bug-pattern rules look for classic production bugs that compile
cleanly:

| Rule | Finds |
|---|---|
| `truncation` | A MOVE, ADD, SUBTRACT or COMPUTE that cuts digits or characters (`9(9)` into `9(3)`; a literal longer than its receiver) |
| `subscript-range` | A literal subscript outside the OCCURS bounds (`WS-ENT(11)` on `OCCURS 10`) |
| `next-sentence` | NEXT SENTENCE inside an IF closed by END-IF, which skips the statements after the END-IF |
| `perform-range` | `PERFORM B THRU A` backwards, a GO TO out of a PERFORM range, a main line that falls into a PERFORMed paragraph |
| `file-status` | A FILE STATUS the program never tests |
| `uninitialized` | A numeric item read but never set, with no VALUE |
| `obsolete-verb` | ALTER |

Eight more rules check what other COBOL linters (SonarQube, IBM Developer for
z/OS code review) check:

| Rule | Finds |
|---|---|
| `constant-condition` | A condition that is always true or false: `IF WS-A = WS-A`, `WS-A = 'X' AND WS-A = 'Y'` |
| `duplicate-branch` | An EVALUATE WHEN or an ELSE IF that repeats an earlier test, so its statements never run |
| `self-assignment` | `MOVE X TO X` |
| `stop-run-in-subprogram` | STOP RUN in a CALLed program (PROCEDURE DIVISION USING, or nested), which ends the whole run unit |
| `string-pointer` | A STRING/UNSTRING pointer set to 0 just before, or whose PICTURE cannot reach the field's length + 1 |
| `loop-variable` | A PERFORM VARYING body that changes its own control variable |
| `evaluate-other` | EVALUATE without WHEN OTHER (info) |
| `nesting-depth` | IF/EVALUATE/PERFORM nested more than 5 deep (info) |

With `--callee-path DIR` (or `callee_path` in `cobol.yml`), the `call-check`
rule also compares every CALL with the program it calls (argument count,
passing mode, byte length, usage), so a caller passing 8 bytes to a 10-byte
LINKAGE item fails the lint gate.
`--rule` narrows the run, `--min-severity` the output, and `--fail-on error`

`--rule` and `--disable` narrow the run, `--severity RULE=LEVEL` re-grades a
rule, `--min-severity` trims the output (by default `text` and `github` show
warnings and errors, `json` and `sarif` everything), and `--fail-on error`
exits 3 when a finding at that severity was reported, so it can gate a build.
A comment silences one finding where it is (`*> cobol-lint:
disable-next-line=dead-code`), and `--write-baseline` / `--baseline` record
today's findings so a gate on a legacy codebase fails only on new ones.
IBM's CICS copybooks `DFHAID` and `DFHBMSCA` are built in, and a copybook
that cannot be found is named in the report's caveats instead of failing the
file (`--strict-copybooks` restores the failure).
It takes many files at once (`FILE...`, `--glob`, `--files-from`),
`--changed-since REF` lints only the programs a git change touched (and those
that `COPY` a changed copybook), and `--format github` annotates the pull
request. `--new-code-since REF` keeps only the findings on lines a change
added or edited, like a Sonar new-code gate, and `--scope RULE=all` judges
chosen rules on the whole codebase instead. `lint`, `scan` and `call-check`
write SARIF 2.1.0 with `--format sarif`, which GitHub code scanning and IDE
problem panes read directly. CI recipe and pre-commit hooks:
[docs/ci-lint.md](docs/ci-lint.md). This repository is also a GitHub Action
(`uses: landparty/cobol-parser@main`, or a release tag) that runs the gate in a few lines:
[docs/github-action.md](docs/github-action.md).

`scan` runs `health` and `redundancy` by default; `--analyzer` picks others
(`dead-code`, `complexity`, `lint`, ...). With `--cache-dir`, a file whose
source, copybooks and copybook directories are unchanged reuses its report
from the last run.

### Analyze one program

Each command reads one program (or, for `data-items`, a bare copybook) and
writes one report.

| Command | What it gives you |
|---|---|
| `dead-code` | Paragraphs and sections no path reaches |
| `unused-variables` | Data items the PROCEDURE DIVISION never references |
| `program-flow` | The control-flow graph (PERFORM, GO TO, CALL, fall-through) as JSON, Mermaid or DOT |
| `recursion-check` | PERFORM and GO TO cycles, recursive CALLs |
| `complexity` | Cyclomatic complexity per paragraph and section |
| `health` | A composite technical-debt score with its worst offenders |
| `redundancy` | Dead code, unused data and duplicated paragraphs together |
| `io-sequence` | OPEN / READ / WRITE / CLOSE ordering mistakes |
| `move-type-check` | MOVEs between incompatible categories |
| `linkage-check` | LINKAGE items against the `USING` of the PROCEDURE DIVISION and ENTRY |
| `sql-cics-check` | Embedded SQL and CICS pitfalls (unchecked SQLCODE, missing RESP, ...) |
| `dclgen-check` | SQL host variables against their DCLGEN columns |
| `analyze` | The targets a dynamic `CALL identifier` can reach |
| `language-env` | Intrinsic functions and LE callable services the program uses |
| `ims-dli` | IMS DL/I calls and the segments they reference |
| `data-items` | Every data item's byte offset, length, USAGE, REDEFINES and level-88 values |
| `program-signature` | The program's calling interface, with a ready-made `CALL` |
| `xref` | A cross-reference of every symbol: where it is defined, read and written |
| `business-rules` | The decisions, validations and calculations, as rules |
| `lineage` | Where one field's value flows inside the program |
| `diff` | What changed in behavior between two versions (reformatting is no change) |

```bash
cobol-parser dead-code src/ORDPOST.cbl
cobol-parser unused-variables src/ORDPOST.cbl --exclude-copybook-variables
cobol-parser program-flow src/ORDPOST.cbl --format mermaid -o flow.mmd
cobol-parser recursion-check src/ORDPOST.cbl
cobol-parser complexity src/ORDPOST.cbl
cobol-parser health src/ORDPOST.cbl
cobol-parser redundancy src/ORDPOST.cbl --min-clone-statements 5
cobol-parser io-sequence src/ORDPOST.cbl
cobol-parser move-type-check src/ORDPOST.cbl
cobol-parser linkage-check src/POSTDOM.cbl
cobol-parser sql-cics-check src/DB2BATCH.cbl
cobol-parser dclgen-check src/DB2BATCH.cbl
cobol-parser analyze src/ORDPOST.cbl
cobol-parser language-env src/LESERV.cbl
cobol-parser ims-dli src/IMSMPP.cbl
cobol-parser data-items copybooks/ORDREC.cpy
cobol-parser program-signature src/POSTDOM.cbl
cobol-parser xref src/ORDPOST.cbl
cobol-parser business-rules src/ORDVAL.cbl --format text
cobol-parser lineage src/ORDPOST.cbl --field ORD-AMT --format text
cobol-parser diff old/ORDPOST.cbl src/ORDPOST.cbl --format text
```

```text
$ cobol-parser diff old/ORDPOST.cbl src/ORDPOST.cbl --format text
PROGRAM ORDPOST -> ORDPOST
3 changes

data:
  ~ [value-changed] WS-OLD-RATE: WS-OLD-RATE VALUE changed from 0.0150 to 0.0125

procedure:
  ~ [condition-changed] 2000-POST: IF condition changed: IF ORD-HELD OR ORD-REJECTED -> IF ORD-HELD
  ~ [paragraph-body-changed] 2000-POST: paragraph 2000-POST body changed
...
```

### Analyze a codebase

| Command | What it gives you |
|---|---|
| `codebase-graph` | The CALL / LINK / XCTL and COPY graph of a source tree (JSON, DOT, Mermaid) |
| `copybook-impact` | Every program a copybook change reaches, through nested `COPY` chains |
| `call-check` | Every `CALL` against the callee's `USING`: argument count, BY VALUE / BY REFERENCE, byte length, USAGE, `RETURNING` |
| `field-impact` | Where a field's value flows across programs, files, DB2 columns and JCL datasets |
| `widen-check` | What breaks if a field's PICTURE changes |
| `jcl` | Which program each JCL step runs, and each DD's dataset (needs the `[jcl]` extra) |

```bash
cobol-parser codebase-graph src/ --format mermaid -o graph.mmd
cobol-parser copybook-impact ORDREC src/
cobol-parser call-check src/ --format text --fail-on error
cobol-parser field-impact ORD-AMT src/ --jcl jcl/ --format text
cobol-parser field-impact --dataset PROD.ORD.HISTORY src/ --jcl jcl/ --format text
cobol-parser widen-check ORD-CUST-ID src/ --to '9(10)' --jcl jcl/ --format text
cobol-parser jcl jcl/ORDNIGHT.jcl --bindings
cobol-parser jcl jcl/ORDNIGHT.jcl --dd-map
```

```text
$ cobol-parser widen-check ORD-CUST-ID src/ --to '9(10)' --jcl jcl/ --format text
ORD-CUST-ID -> PIC 9(10)
  ORDEDIT:ORD-REC.ORD-CUST-ID  PIC 9(8) (8 bytes) -> PIC 9(10) (10 bytes)
  ...
ERROR   truncation   ORDPOST:HIST-REC.HIST-CUST-ID (line 48)
        the value reaches a field holding 8 digits; the new PICTURE carries 10 digits: loses high-order digits
...
```

A dynamic `CALL` is followed to every target its variable can hold. When the
byte length changes, `widen-check` also lists the records whose later fields
shift, the `REDEFINES` that overlay the field, the files whose LRECL changes
(and the other programs reading the same dataset), and the CALL / LINKAGE
records on both sides.

### Test data

| Command | What it gives you |
|---|---|
| `gen-data` | Synthetic records that fit each field's PICTURE, USAGE and level-88 values, as CSV, JSON, record bytes or hex |
| `decode` | A record file (ASCII or EBCDIC, fixed or variable) read back through a copybook |
| `compare` | Two record files compared field by field, matched on a key |
| `gen-fixtures` | A test bundle for a whole program: one scenario per branch, the data each file, CALL, SQL or CICS boundary supplies, and what to assert |

```bash
cobol-parser gen-data copybooks/ORDREC.cpy --rows 100 --seed 7 -o orders.csv
cobol-parser gen-data copybooks/ORDREC.cpy --rows 100 --seed 7 --format record --charset ebcdic -o expected.dat
cobol-parser gen-data copybooks/ORDREC.cpy --rows 99 --seed 7 --format record --charset ebcdic -o actual.dat
cobol-parser decode expected.dat --copybook copybooks/ORDREC.cpy --charset ebcdic --max-records 5
cobol-parser compare expected.dat actual.dat --copybook copybooks/ORDREC.cpy --charset ebcdic --key ORD-ID
cobol-parser gen-fixtures src/ORDPOST.cbl --list-boundaries
cobol-parser gen-fixtures src/ORDPOST.cbl --scenarios all --seed 7 -o bundle.json
cobol-parser gen-fixtures src/ORDPOST.cbl --scenarios branches --format csv-dir -o fixtures/
```

```text
$ cobol-parser compare expected.dat actual.dat --copybook copybooks/ORDREC.cpy --charset ebcdic --key ORD-ID
compare ORD-REC (view ORD-REC), key ORD-ID, comparing values
expected: 100 records, actual: 99 records
matched 99, changed 0, missing 1, extra 0
...
```

A `--seed` makes `gen-data` and `gen-fixtures` output byte-identical across
runs. `compare` exits like `cmp`: 0 when the files match, 1 when they differ,
2 when the run failed. The bundle format is in
[docs/fixture-bundle-schema.md](docs/fixture-bundle-schema.md).

### Reference and integrations

| Command | What it gives you |
|---|---|
| `le-info` | The signature of an LE callable service or intrinsic function, from the built-in catalogue |
| `mcp` | A read-only MCP server that gives AI agents these analyzers (needs the `[mcp]` extra) |

```bash
cobol-parser le-info CEEDAYS
cobol-parser le-info NUMVAL-C
cobol-parser le-info --kind service
claude mcp add cobol -- cobol-parser mcp --root /path/to/checkout
```

The MCP server's tools answer "what is this program", "what is this field and
where is it used", "who calls this", "what does a change to this copybook
reach" and "show me this paragraph", with a `file:line` for every fact and a
list of what they could not check. See [docs/mcp-server.md](docs/mcp-server.md).
The repo also ships a `cobol-analysis` agent skill
([.claude/skills/cobol-analysis/SKILL.md](.claude/skills/cobol-analysis/SKILL.md))
that teaches an agent which subcommand answers which question.

### Exit codes

| Code | Meaning |
|---|---|
| 0 | Success. Analyzer findings alone never fail a run |
| 1 | A file could not be read, parsed or written |
| 2 | The command line was rejected, or some input only partly parsed (the output is still written) |
| 3 | A gate tripped: `--fail-on` (`lint`, `call-check`, `widen-check`) or `jcl --strict` |

`compare` is the exception: 1 means "the files differ".

## The Python API, with examples

Everything the CLI does is a library call. Each block below runs on its own
from the project root shown above.

### Parse

```python
from cobolparser import CobolParser, ErrorRecoveryMode, parse_cobol

result = parse_cobol("src/ORDVAL.cbl")             # FAIL_FAST: stops at the first error
print(result.success, result.errors, result.warnings)
print(result.ast.program_name)                     # ORDVAL
print(len(result.ast.find_all_by_type("CallStatement")))
json_text = result.ast.to_json()

parser = CobolParser(error_recovery=ErrorRecoveryMode.COLLECT_ALL)
result = parser.parse("       IDENTIFICATION DIVISION.\n       PROGRAM-ID. HELLO.\n")
print(result.ast.program_name)                     # HELLO
```

`parse_cobol` takes a path or the source text. `ParseResult` also carries
`statistics` and, after copybook expansion, `expansion_source_map`.

### Copybooks, preprocessing and tokens

```python
from pathlib import Path

from cobolparser import (
    expand_copybooks,
    normalize_fixed_format,
    parse_cobol_with_expansion,
    tokenize_cobol,
)

source = Path("src/ORDPOST.cbl").read_text()

result = parse_cobol_with_expansion(source, "src/ORDPOST.cbl", copybook_paths=["copybooks"])
print(result.success)

expansion = expand_copybooks(source, ["copybooks"])
print(expansion.included_copybooks)                # the copybook files it read

free_form = normalize_fixed_format(source)         # columns 8-72, comments dropped
tokens = tokenize_cobol(source)
print(tokens[0].type.name, tokens[0].value)        # IDENTIFICATION_DIVISION IDENTIFICATION
```

### Many files

```python
from glob import glob

from cobolparser import ScanOptions, cross_file_clone_groups, parse_files, scan_files

for item in parse_files(glob("src/*.cbl"), workers=4):
    print(item.path, item.result.success if item.result else item.read_error)

report = scan_files(
    glob("src/*.cbl"),
    ScanOptions(analyzers=("health", "dead-code"), copybook_paths=("copybooks",)),
)
print(len(report.ok_files), len(report.failed_files))
print(cross_file_clone_groups(report))
```

`cobolparser.batch.parse_files_with_copybooks(paths, copybook_paths=[...])`
parses many files with their copybooks expanded.

### Analyze one program

Every analyzer takes a parsed `CobolProgram` and returns a report with
`to_dict()`. Most are `<Analyzer>().analyze(ast)`; the checkers are
`.check(ast)`.

```python
from cobolparser import (
    BusinessRuleExtractor,
    ComplexityAnalyzer,
    CRUDMatrixGenerator,
    DclgenChecker,
    DeadCodeAnalyzer,
    DynamicCallAnalyzer,
    IOLogger,
    LanguageEnvironmentAnalyzer,
    LintAnalyzer,
    ProgramFlowAnalyzer,
    RecursionRiskAnalyzer,
    RedundancyAnalyzer,
    TechnicalDebtAnalyzer,
    UnusedVariableAnalyzer,
    parse_cobol_with_expansion,
)
from cobolparser.analysis import (
    HostVariableResolver,
    IMSSegmentAnalyzer,
    IOSequenceAnalyzer,
    LinkageChecker,
    MoveTypeChecker,
)
from cobolparser.analysis.field_lineage import FieldFlowAnalyzer
from cobolparser.analysis.program_signature import extract_signatures
from cobolparser.analysis.sql_cics_lint import SqlCicsAnalyzer
from cobolparser.analysis.xref import XrefAnalyzer
from cobolparser.generators.data.layout_offsets import compute_program_data_items


def load(path):
    with open(path) as f:
        return parse_cobol_with_expansion(f.read(), path, copybook_paths=["copybooks"]).ast


ast = load("src/ORDPOST.cbl")

lint = LintAnalyzer().analyze(ast)                  # every checker below, in one pass
for finding in lint.findings:
    print(finding.rule, finding.severity, finding.location, finding.message)

DeadCodeAnalyzer().analyze(ast)                     # dead-code
UnusedVariableAnalyzer().analyze(ast)               # unused-variables
flow = ProgramFlowAnalyzer().analyze(ast)           # program-flow
RecursionRiskAnalyzer().analyze(ast)                # recursion-check
ComplexityAnalyzer().analyze(ast)                   # complexity
TechnicalDebtAnalyzer().analyze(ast)                # health
RedundancyAnalyzer().analyze(ast)                   # redundancy
IOSequenceAnalyzer().analyze(ast)                   # io-sequence
MoveTypeChecker().check(ast)                        # move-type-check
XrefAnalyzer().analyze(ast)                         # xref
FieldFlowAnalyzer().analyze(ast)                    # lineage
compute_program_data_items(ast)                     # data-items
IOLogger().analyze(ast)                             # every file operation, in order
CRUDMatrixGenerator().analyze(ast)                  # which file or table each program creates/reads/updates/deletes
DynamicCallAnalyzer().analyze(ast)                  # analyze: annotates each CALL with its possible targets

LinkageChecker().check(load("src/POSTDOM.cbl"))                  # linkage-check
print(extract_signatures(load("src/POSTDOM.cbl"))[0].to_dict())  # program-signature
BusinessRuleExtractor().analyze(load("src/ORDVAL.cbl"))          # business-rules

db2 = load("src/DB2BATCH.cbl")
SqlCicsAnalyzer().analyze(db2)                      # sql-cics-check
DclgenChecker().check(db2)                          # dclgen-check
HostVariableResolver().resolve(db2)                 # each SQL host variable -> its data item
LanguageEnvironmentAnalyzer().analyze(load("src/LESERV.cbl"))  # language-env
IMSSegmentAnalyzer().analyze(load("src/IMSMPP.cbl"))           # ims-dli
```

Flowcharts and diffs:

```python
from cobolparser import ProgramFlowAnalyzer, parse_cobol
from cobolparser.analysis.ast_diff import ProgramDiffer
from cobolparser.generators import DotFlowchartGenerator, MermaidFlowchartGenerator

ast = parse_cobol("src/ORDPOST.cbl").ast
flow = ProgramFlowAnalyzer().analyze(ast)
print(MermaidFlowchartGenerator().generate(flow))
dot = DotFlowchartGenerator().generate(flow)

diff = ProgramDiffer().diff(parse_cobol("old/ORDPOST.cbl").ast, ast)
print(diff.to_text())
```

### Analyze a codebase

```python
from glob import glob

from cobolparser.analysis.call_interface import CallInterfaceChecker
from cobolparser.analysis.codebase import CodebaseGraphBuilder, CopybookImpactAnalyzer
from cobolparser.analysis.field_lineage import FieldFlowAnalyzer
from cobolparser.analysis.field_widening import FieldWideningAnalyzer
from cobolparser.analysis.lineage_graph import LineageGraph
from cobolparser.analysis.lineage_jcl import bindings_from_jobs, load_jobs
from cobolparser import parse_cobol_with_expansion

programs = sorted(glob("src/*.cbl"))

graph = CodebaseGraphBuilder(copybook_paths=["copybooks"]).build(programs)
print(graph.callers_of("ORDVAL"))                   # codebase-graph
print(graph.to_mermaid())

impact = CopybookImpactAnalyzer(graph).analyze("ORDREC")      # copybook-impact
print(impact.direct_programs)

calls = CallInterfaceChecker(copybook_paths=["copybooks"]).check_files(programs)
print(calls.to_text())                              # call-check

# field-impact and widen-check: one lineage graph over every program and the JCL
flows = []
for path in programs:
    with open(path) as f:
        ast = parse_cobol_with_expansion(f.read(), path, copybook_paths=["copybooks"]).ast
    flows.append(FieldFlowAnalyzer().analyze(ast))
jobs, errors = load_jobs(glob("jcl/*.jcl"), proc_path="proclib")
bindings, passthroughs = bindings_from_jobs(jobs)
lineage = LineageGraph(flows, bindings, passthroughs)

print(lineage.impact("ORD-AMT", direction="forward"))         # field-impact
widen = FieldWideningAnalyzer(lineage).analyze("ORD-CUST-ID", "9(10)")
for finding in widen.findings:                                # widen-check
    print(finding.severity, finding.kind, finding.program, finding.message)
```

### Test data

```python
from cobolparser.generators import (
    Charset,
    CopybookDataGenerator,
    DataGeneratorOptions,
    EncodingOptions,
    ProgramFixtureGenerator,
    RecordDecoder,
    compare_files,
)

options = DataGeneratorOptions(rows=100, seed=7)
generator = CopybookDataGenerator(options)
dataset = generator.generate_from_file("copybooks/ORDREC.cpy", copybook_paths=["copybooks"])
dataset.write_csv("orders.csv")                                # gen-data

# A record image needs every byte (FILLER too): use the record-image options.
ebcdic = EncodingOptions(charset=Charset.EBCDIC)
image = CopybookDataGenerator(options.for_record_image()).generate_from_file(
    "copybooks/ORDREC.cpy", copybook_paths=["copybooks"]
)
image.write_records("expected.dat", ebcdic)                    # gen-data --format record

decoder = RecordDecoder.from_copybook_file(
    "copybooks/ORDREC.cpy", opts=ebcdic, copybook_paths=["copybooks"]
)
decoded = decoder.decode_file("expected.dat", max_records=5)   # decode
print(decoded.to_csv())

result = compare_files(decoder, "expected.dat", "expected.dat", key=["ORD-ID"])
print(result.equal)                                            # compare: True

bundle = ProgramFixtureGenerator().generate_with_scenarios_from_file(
    "src/ORDPOST.cbl", copybook_paths=["copybooks"], mode="all", seed=7
)                                                              # gen-fixtures
print([scenario.name for scenario in bundle.scenarios])
bundle.write_csv_dir("fixtures/")
```

### JCL, CICS, DB2 and IMS definitions

```python
from pathlib import Path

from cobolparser.definitions import parse_definitions
from cobolparser.jcl import parse_jcl, resolve_dd_bindings

jcl = parse_jcl(Path("jcl/ORDNIGHT.jcl").read_text(), filename="ORDNIGHT.jcl", proc_paths=["proclib"])
for binding in resolve_dd_bindings(jcl):                       # jcl --bindings
    print(binding.step, binding.ddname, binding.dataset)
print(jcl.steps_running("ORDPOST"))

ddl = parse_definitions(Path("defs/BANKDDL.ddl").read_text())  # DB2 DDL
print([table.name for table in ddl.tables])
```

`parse_definitions` detects the kind itself and also reads CICS CSD
(`DEFINE PROGRAM/TRANSACTION/FILE ...`), BMS maps, and IMS DBD and PSB
sources (`parse_csd`, `parse_bms`, `parse_ddl`, `parse_dbd`, `parse_psb` for
one kind). The CLI has no subcommand for these; the MCP server and the
LegacyLens backend use them. Sample sources are in
[tests/samples/definitions/](tests/samples/definitions/).

### LE catalogue, SARIF and project config

```python
from pathlib import Path

from cobolparser import LintAnalyzer, parse_cobol
from cobolparser.analysis.sarif import lint_results, sarif_log
from cobolparser.config.project import load_project_config
from cobolparser.dialects.le_signatures import intrinsic_signature, le_service_signature

print(le_service_signature("CEEDAYS").to_dict())               # le-info CEEDAYS
print(intrinsic_signature("NUMVAL-C").to_dict())

report = LintAnalyzer().analyze(parse_cobol("src/ORDPOST.cbl").ast)
log = sarif_log(lint_results(report.to_dict(), "src/ORDPOST.cbl"))  # lint --format sarif

config = load_project_config(Path.cwd())                       # config: the cobol.yml in effect
print(config.source, config.copybook_path)
```

The per-module reference, with every report field, is in the OKF topic
files ([.okf/analysis.md](.okf/analysis.md),
[.okf/generators.md](.okf/generators.md), [.okf/batch.md](.okf/batch.md),
[.okf/jcl.md](.okf/jcl.md), [.okf/definitions.md](.okf/definitions.md)).

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
| Linting COBOL in CI | [docs/ci-lint.md](docs/ci-lint.md) |
| The GitHub Action (new code or whole codebase, per rule) | [docs/github-action.md](docs/github-action.md) |
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

CI runs only on manual dispatch (`.github/workflows/ci.yml` has no push or PR
trigger), so run lint, types and the full suite locally before pushing. Measure coverage on
the pure-Python build: with `COBOLPARSER_ACCEL=1`, coverage.py cannot see the
code the compiled modules replace. Test layout and markers:
[.okf/tests.md](.okf/tests.md).

## License

GNU Affero General Public License v3.0 or later. Copyright © 2026 Samuel Dion.
See [LICENSE](LICENSE).
