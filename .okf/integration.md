---
type: Integration Contract
title: Backend Integration Contract
description: Summary of interface-contract.md — what the LegacyLens backend adapter (parser, DynamicCallAnalyzer, ProgramFlowAnalyzer, field lineage, program_structure dict) and mocky-mock (ProgramFixtureGenerator / FixtureBundle, bundle_version gate) call into cobolparser and expect back.
tags: [integration, backend, contract, cobol-parser, mocky-mock, fixtures, lineage]
timestamp: 2026-10-15T00:00:00Z
resource: ../interface-contract.md
---
# Backend Integration Contract

Two external consumers call into `cobolparser`; changing what they call, or
the shapes they get back, breaks them:

1. **The LegacyLens backend adapter** — `CobolLegacyParser` in
   `backend/src/parsers/cobol/parser.py`. Sections "Entry Points" through
   "File Extensions Handled" below.
2. **The sibling `mocky-mock` repo** — `mockymock generate --with-data` /
   `mockymock fixtures` call the generators package directly. Section
   "Generators Surface (mocky-mock)".

> Canonical, authoritative text: [`interface-contract.md`](../interface-contract.md)
> (repo root, the `resource` field above). This file is a summary; when they
> disagree the contract wins. Read it before changing any public API shape —
> a breaking change means bumping the relevant version field
> (`lineage_version`, `bundle_version`).

**Integration method:** the backend **vendors** `cobolparser` into
`backend/_vendor/cobol-parser/` (it does not install from PyPI). Changes reach
it only by a manual sync:
```bash
cp -r cobolparser/ ../backend/_vendor/cobol-parser/cobolparser/
```

**Import path in backend:**
```python
from ..dependencies import CobolParser, CobolProgram, DialectType, ErrorRecoveryMode, \
    DynamicCallAnalyzer, ProgramFlowAnalyzer, CobolParseError
```

---

## Entry Points (backend adapter)

### 1. Parser construction + parse
```python
from cobolparser import CobolParser, DialectType, ErrorRecoveryMode

parser = CobolParser(
    dialect=DialectType.IBM_ENTERPRISE,       # must exist
    error_recovery=ErrorRecoveryMode.COLLECT_ALL,  # must exist
)                                              # must not raise on these values
parse_result = parser.parse(cleaned_content)           # no filename
parse_result = parser.parse(cleaned_content, filename) # with filename str
```

### 2. `ParseResult` attributes the adapter reads

| Attribute | Type | Notes |
|-----------|------|-------|
| `result.success` | `bool` | `True` = AST built **and** `errors` empty (`ast is not None and not errors`) |
| `result.ast` | `CobolProgram \| None` | May be **non-None when `success` is False**: `COLLECT_ALL` (and a partial `FAIL_FAST` parse) returns a partial AST alongside populated `errors`. `None` only when nothing could be parsed. `success` = "complete and error-free"; `ast is not None` = "something usable exists" |
| `result.errors` | `list` | Each item has `.line_number` (`int \| None`) and `.message` (`str`) |
| `result.warnings` | `list` | Items stringified with `str()` |
| `result.statistics` | object \| None | Must have `.to_dict() -> dict` if not `None` |

### 3. `DynamicCallAnalyzer` (optional, fault-isolated)
```python
from cobolparser import DynamicCallAnalyzer
DynamicCallAnalyzer().analyze(parse_result.ast)   # mutates AST nodes in place
```
Absent -> the adapter falls back silently; wrapped in try/except.

### 4. `ProgramFlowAnalyzer` (optional, fault-isolated)
```python
from cobolparser import ProgramFlowAnalyzer
flow_dict = ProgramFlowAnalyzer().analyze(parse_result.ast).to_dict()  # must be a dict
```
Stored in `metadata["program_flow_data"]`; failure returns `None` without
blocking. Node `name` is the bare procedure name; when two paragraphs share a
name (different sections) each such node also has `qualified_name`
(`"X1 OF S2"`), and edges, `entry_points`, `exit_points`, `cycles`,
`unreachable_nodes` and branch `parent_proc` refer to it by that. Join edges
to nodes on `qualified_name ?? name`. The key is absent for unique names, so
such programs serialize unchanged (#258).

### 4b. Field lineage (optional, fault-isolated)
```python
from cobolparser.analysis.field_lineage import FieldFlowAnalyzer
from cobolparser.analysis.lineage_graph import LineageGraph
from cobolparser.analysis.lineage_jcl import bindings_from_jobs, jobs_from_sources

report = FieldFlowAnalyzer().analyze(parse_result.ast).to_dict()   # per program
jobs, problems = jobs_from_sources({name: jcl_text}, {proc: proc_text})  # needs jcl-parser
graph = LineageGraph(reports, *bindings_from_jobs(jobs))           # per organization
stored = graph.join_edges()                                         # list[dict]
graph = LineageGraph(reports, join_edges=stored)                    # query time
graph.impact(field, program=..., direction="forward"|"backward", depth=N).to_dict()

# Optional: keep the joins' caveats and unjoined DDs too
state = graph.join_state()      # {"edges": [...], "caveats": [str], "unjoined": [str]}
graph = LineageGraph(reports, join_edges=state["edges"],
                     join_caveats=state["caveats"], unjoined=state["unjoined"])
```
* The report dict carries **`lineage_version`** (currently `"2"`); any shape
  change (ports, edges, node keys) bumps it, and a stored report of another
  version must be recomputed, not read. `"2"` added literal-subscript
  occurrence nodes (`"R.AMT(3)"`, joined to `"R.AMT"` by inexact
  `kind="occurrence"` edges), `PROGRAM#RETURNING` linkage ports, `#n`
  suffixes on `qualified_name`s shared by several items (`"FILLER#2"`), an
  optional `occurs` key on `items`, and table fields mapped to every
  occurrence's bytes (inexact).
* `join_edges()` entries: `{source, target, kind, line, statement,
  confidence, cross}`, node keys as lists (`["P", program, kind, name,
  offset, length]`, `["D", dataset, offset, length]`, `["T", "TABLE.COLUMN"]`).
  Kinds: `dataset`, `copy`, `aggregate`, `call`, `table`, `opaque-call`,
  `table-alias` (`SCHEMA.T.C` <-> `T.C`, `confidence="candidate"`).
* `join_caveats=` / `unjoined=` are optional; without them a rebuilt graph
  re-derives only the opaque-callee caveat and has an empty `unjoined`. A
  rebuilt graph's `join_edges()` / `join_state()` return the edges it was
  built from.
* `ImpactResult.to_dict()` has `start_found` (False when nothing matched the
  start field / table / dataset).
* `jobs_from_sources` raises `ImportError` when jcl-parser is not importable.

### 5. Exception type
```python
from cobolparser import ParseError   # canonical base, cobolparser/_errors.py
```
The adapter catches `ParseError` and maps it to a structured error result.
`CobolParseError` (what the backend's import line names) is a
backward-compatible alias — the same class.

---

## `CobolProgram` attributes the adapter reads

| Attribute | Expected |
|-----------|----------|
| `program.program_name` | `str \| None` |
| `program.get_statistics()` | `dict` with at least `"total_lines": int` |

Everything else in the AST is read by the backend's own extractors
(`backend/src/parsers/cobol/extractors/`), which are updated there when AST
shapes change; they are the real documentation of the full-AST surface.

## `parse_content()` keyword arguments

```python
adapter.parse_content(content, filename=filename, copybook_registry=registry)
```
`copybook_registry` is **not** passed to `cobolparser`: the adapter injects
COPY members itself before `parser.parse()`, via any object with
`resolve(copybook_name: str) -> str | None` (the adapter's `CopybookResolver`
Protocol).

---

## Output: `program_structure` dict (built by the adapter)

```json
{
  "program_info": {
    "name": "<str>", "type": "COBOL",
    "language_version": "IBM Enterprise COBOL", "encoding": "utf-8",
    "line_count": 1200, "complexity_score": 12.5,
    "uses_cics": true, "uses_ims": false, "uses_mq": false,
    "is_transactional_likely": true, "is_batch_likely": false,
    "is_bmp_program": false,
    "is_copybook": true, "source_kind": "copybook", "copybook_name": "<str>"
  },
  "structure": {
    "sections": [{"name": "MAIN", "type": "section", "start_line": 10, "end_line": 50}],
    "variables": [{"name": "WS-COUNTER", "type": "PIC 9(4)", "definition_line": 20}],
    "procedures": [{"name": "MAIN-PARA", "start_line": 100, "end_line": 150, "calls": [], "called_by": []}]
  },
  "dependencies": {
    "includes": ["COPYBOOK-A"], "calls": ["SUBPROG1"],
    "databases": [{"name": "MYDB", "type": "DB2", "tables": ["ACCOUNTS"]}],
    "copy_statements": [], "file_io": [], "cics_commands": [], "mq_operations": []
  },
  "analysis": {
    "metrics": {}, "issues": [], "modernization_hints": [],
    "classification_hints": {}, "cics_indicators": {}, "ims_indicators": {},
    "mq_indicators": {}
  }
}
```
`is_copybook`, `source_kind` (`"copybook"` | `"procedure_copybook"` |
`"program"`) and `copybook_name` are present only for copybooks.
`variables` / `procedures` entries may carry further keys.

### Paths read by the backend relationship extractors (`backend/src/services/relationships/`)

| Path | Neo4j relationship |
|------|--------------------|
| `dependencies.calls` (list of `str`) | `CALLS` |
| `dependencies.includes` (list of `str`) | `COPYBOOK` |
| `dependencies.databases` (`{name, type, tables}`) | `USES_DB2` |
| `dependencies.cics_commands` | `USES_CICS` |
| `dependencies.mq_operations` | `USES_MQ` |
| `program_info.name` | the program's canonical name in the DB |

## `ParserResult` container (backend, `backend/src/parsers/base.py`)

```python
@dataclass
class ParserResult:
    success: bool
    program_structure: dict | None
    error_message: str | None   # prefixed, e.g. "COBOL_PARSE_ERROR: ..."
    metadata: dict              # parse timing, dialect, version, injection stats, program_flow_data
```
Error prefixes: `EMPTY_CONTENT`, `VALIDATION_FAILED`, `COBOL_PARSE_ERROR`,
`SYNTAX_ERROR`, `PARSE_FAILED`, `PERMISSION_ERROR`, `PARSER_INTERNAL_ERROR`,
`INTERNAL_ERROR`.

## File Extensions Handled

`.cbl`, `.cob`, `.cobol`, `.cpy`, `.copy` (and uppercase variants).
`.cpy`/`.copy` files are copybooks: the adapter wraps them in a synthetic
COBOL program shell before parsing and shifts line numbers back afterwards.

---

## Generators Surface (mocky-mock)

`mockymock generate --with-data` and `mockymock fixtures` call the
generators package, not the parser/analyzer entry points above. The full
`FixtureBundle` key-by-key schema, versioning policy and worked example live
in [`docs/fixture-bundle-schema.md`](../docs/fixture-bundle-schema.md); see
also [generators.md](generators.md).

```python
from cobolparser.generators import DataGeneratorOptions, ProgramFixtureGenerator

generator = ProgramFixtureGenerator(DataGeneratorOptions(rows=10))  # options optional
bundle = generator.generate_with_scenarios_from_file(
    "PROGRAM.cbl",
    copybook_paths=["path/to/copybooks"],   # optional
    mode="happy",                            # "happy" | "branches" | "all"
    seed=7,                                  # optional; a drawn seed is reported on bundle.seed
)
bundle.to_dict()   # input to mocky-mock's bundle -> mock-surface join (--with-data)
bundle.to_json()   # `mockymock fixtures`'s entire stdout
```

| Symbol / key | mocky-mock use |
|---|---|
| `ProgramFixtureGenerator(options: DataGeneratorOptions \| None = None)` | constructor |
| `DataGeneratorOptions` | only `rows=` is ever overridden (from mocky-mock's `--rows`, passed only when given) |
| `generate_with_scenarios_from_file(path, *, copybook_paths=None, callee_paths=None, mode="happy", seed=None) -> FixtureBundle` | the single entry point; mocky-mock passes only `copybook_paths`, `mode`, `seed` |
| `dict["bundle_version"]` | **the gate**: mocky-mock refuses the bundle (`UnsupportedBundleVersionError`, exit 1) unless it is `1` (`BUNDLE_VERSION`) |
| `BoundaryFixture` keys `category`, `key`, `direction`, `layout`, `sequence`, `terminal`, `status` (also `line`, `paragraph`, `provenance`, `unresolved`, read but not joined on) | joined to mocky-mock's `mock_surface.BoundarySite`s by `(category, key)`; for SQL/CICS/DLI, `key` is a normalized shortest-unique-prefix of the EXEC text, computed by the same rule on both sides |
| `FieldSpec` keys `odo_controls`, `odo_counter_bounds` (additive, in every `layout`) | not read by mocky-mock; let a record-image writer pick which `OCCURS ... DEPENDING ON` occurrences a record holds |
| `Scenario` key `verification` (additive, `branches`/`all` only) | cobol-parser's verdict on whether the scenario's data satisfies its branch; mocky-mock renders an unverified one as a `*> UNVERIFIED:` comment |

**Versioning contract:** a change to `generate_with_scenarios_from_file`'s
signature, a key removed or retyped from `FixtureBundle` / `Scenario` /
`BoundaryFixture` / `Expectation`, or a key's meaning changed under an
unchanged name, is breaking — bump `bundle_version` so mocky-mock's gate
fires. Additive keys and corrected *values* under unchanged meanings are not
bumps; the contract records two such cases and why:

* **2026-09-07 audit** — fewer scenarios / lower `targeted` counts for
  programs comparing against subscripted table elements, `IF <PIC X> IS
  NUMERIC`, or ordering comparisons on alphanumeric fields (arms were
  previously reported targeted on fabricated constraints). Same keys, same
  meanings; now true.
* **`PIC N` / `PIC G` width** — such fields are 2 bytes per character (IBM
  national/DBCS), so their `layout` length doubles and later fields' offsets
  shift. Same `int` byte-count keys; corrected values.

---

# Citations
- [`interface-contract.md`](../interface-contract.md) (repo root, canonical)
- [`docs/fixture-bundle-schema.md`](../docs/fixture-bundle-schema.md)
- [../../backend/.okf/services/](../../backend/.okf/services/)
