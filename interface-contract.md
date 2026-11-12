# Backend Integration Contract — cobol-parser

This document describes exactly what two external consumers call into `cobolparser`, and what shapes they expect back. Change these APIs or their return shapes in `cobolparser` and the consumer breaks.

1. **`backend/src/parsers/cobol/parser.py`** (the `CobolLegacyParser` adapter) — the LegacyLens backend service. See "Entry Points Called by the Adapter" through "File Extensions Handled" below.
2. **The sibling `mocky-mock` repo's generators surface** (`mockymock generate --with-data` / `mockymock fixtures`) — see "Generators Surface (mocky-mock)" near the end of this document.
3. **MCP clients** of `cobol-parser mcp` (AI agents) — see "MCP Surface" at the end of this document.

<!-- okf:external CobolLegacyParser ParserResult program_structure CopybookResolver parse_content UnsupportedBundleVersionError -- backend adapter and mocky-mock names, not this package's -->

**Adapter source:** `backend/src/parsers/cobol/parser.py`
**Import path in backend:** `from ..dependencies import CobolParser, CobolProgram, DialectType, ErrorRecoveryMode, DynamicCallAnalyzer, ProgramFlowAnalyzer, CobolParseError`

---

## Entry Points Called by the Adapter

### 1. Parser construction
```python
from cobolparser import CobolParser, DialectType, ErrorRecoveryMode

parser = CobolParser(
    dialect=DialectType.IBM_ENTERPRISE,
    error_recovery=ErrorRecoveryMode.COLLECT_ALL,
)
```
- `DialectType.IBM_ENTERPRISE` must exist
- `ErrorRecoveryMode.COLLECT_ALL` must exist
- Constructor must not raise on these values

### 2. Parsing
```python
parse_result = parser.parse(cleaned_content)                 # no filename
parse_result = parser.parse(cleaned_content, filename)       # with filename str
```
Returns a `ParseResult` object. The adapter accesses:

| Attribute | Type | Notes |
|-----------|------|-------|
| `parse_result.success` | `bool` | True = AST was built **and** `errors` is empty |
| `parse_result.ast` | `CobolProgram \| None` | May be **non-None even when `success` is False**: under `COLLECT_ALL` recovery (and after partial `FAIL_FAST` parses) a partial AST is returned alongside populated `errors`. `ast is None` only on a lexer, preprocessing, I/O or internal failure (or a `FAIL_FAST` stop). When the text parsed but **no division was recognised** (`"hello world"`, `""`, a fixed-format file read as free-form), `ast` is an empty `CobolProgram` with `program_name == "UNKNOWN"` and no divisions, and `errors` holds "No recognizable COBOL division found". Check `success` for "complete and error-free"; check `ast is not None and ast.divisions` for "something usable exists" -- `ast is not None` alone is not enough. |
| `parse_result.errors` | `list` | Each item must have `.line_number` (int or None) and `.message` (str) |
| `parse_result.warnings` | `list` | Items are stringified with `str()` |
| `parse_result.statistics` | object or None | Must have `.to_dict() -> dict` if not None |

### 3. Dynamic call analysis (optional, fault-isolated)
```python
from cobolparser import DynamicCallAnalyzer

analyzer = DynamicCallAnalyzer()
analyzer.analyze(parse_result.ast)   # mutates AST nodes in-place
```
- If `DynamicCallAnalyzer` does not exist the adapter falls back silently.
- Call is wrapped in try/except — failure does not block the parse.
- What it writes: a dynamic `CallStatement` gets `possible_values` (sorted
  `list[str]`) and, when that list is not exhaustive,
  `get_metadata("possible_values_incomplete") is True`. An `ExecCicsStatement`
  for `LINK` / `XCTL` / `LOAD` whose `PROGRAM(...)` is a data-name (not in
  `literal_options`) gets the same two answers as metadata,
  `get_metadata("possible_values")` and
  `get_metadata("possible_values_incomplete")`, also emitted by its
  `to_dict()` (keys absent on every other EXEC CICS node). The operand may be
  subscripted (`PROGRAM(OPT-PGM(IDX))`): every occurrence of the table is a
  candidate, including the entries of a FILLER/VALUE table it `REDEFINES`.
  Candidates keep figurative sentinels (`" "`, `"\x00"`); filter them as
  `_names.callee_names` does.

### 4. Program flow analysis (optional, fault-isolated)
```python
from cobolparser import ProgramFlowAnalyzer

flow_report = ProgramFlowAnalyzer().analyze(parse_result.ast)
flow_dict = flow_report.to_dict()    # must return dict
```
- Result is stored in `metadata["program_flow_data"]`.
- Wrapped in try/except — failure returns None without blocking.
- Node `name` is the bare procedure name. When two paragraphs share a name
  (different sections), each node also has `qualified_name` (`"X1 OF S2"`),
  and edges, `entry_points`, `exit_points`, `cycles`, `unreachable_nodes`
  and branch `parent_proc` refer to it by that `qualified_name`. Join edges
  to nodes on `qualified_name ?? name`. Absent for every node whose name is
  unique, so such programs serialize exactly as before (issue #258).

### 4b. Field lineage (optional, fault-isolated; 2026-10-08)
```python
from cobolparser.analysis.field_lineage import FieldFlowAnalyzer
from cobolparser.analysis.lineage_graph import LineageGraph
from cobolparser.analysis.lineage_jcl import bindings_from_jobs, jobs_from_sources

report = FieldFlowAnalyzer().analyze(parse_result.ast).to_dict()   # per program
jobs, problems = jobs_from_sources({name: jcl_text}, {proc: proc_text})
graph = LineageGraph(reports, *bindings_from_jobs(jobs))           # per organization
stored = graph.join_edges()                                         # list[dict]
graph = LineageGraph(reports, join_edges=stored)                    # query time
graph.impact(field, program=..., direction="forward"|"backward", depth=N).to_dict()

# Optional (added 2026-10-08): keep the joins' caveats and unjoined DDs too
state = graph.join_state()      # {"edges": [...], "caveats": [str], "unjoined": [str]}
graph = LineageGraph(reports, join_edges=state["edges"],
                     join_caveats=state["caveats"], unjoined=state["unjoined"])
```
- The report dict carries `lineage_version` (currently `"2"`). A change to
  its shape (ports, edges, node keys) bumps it; a stored report of another
  version must be recomputed, not read. `"2"` (2026-10-08) added: item nodes
  for literal-subscript occurrences of table fields (`name` like
  `"R.AMT(3)"`, joined to `"R.AMT"` by inexact `kind="occurrence"` edges),
  `PROGRAM#RETURNING` linkage ports (`PROCEDURE DIVISION ... RETURNING`),
  `#n`-suffixed `qualified_name`s for the n-th item sharing a name
  (`"FILLER#2"`), an optional `occurs` key on `items` entries, and table
  fields mapped to every occurrence's bytes (inexact) instead of the first.
- Additive, `lineage_version` unchanged (2026-10-29): `items` entries carry
  optional `picture`, `usage` and `redefines` (the redefined name) keys, and
  the report a top-level `overlays` list -- group-level byte-for-byte
  transfers between two records (`{source, target, source_length,
  target_length, line, statement, origin?}`). A stored report without them
  still loads; `FieldWideningAnalyzer` then lists its fields as unchecked.
- `join_edges()` is unchanged. `join_state()` adds what the joins said besides
  their edges; `LineageGraph(..., join_edges=..., join_caveats=...,
  unjoined=...)` restores it, and both keyword arguments are optional
  (without them a rebuilt graph re-derives only the opaque-callee caveat and
  has an empty `unjoined`, as before). A rebuilt graph's own `join_edges()` /
  `join_state()` now return the edges it was built from.
- Join edge kinds: `dataset`, `copy`, `aggregate`, `call`, `table`,
  `opaque-call`, and (2026-10-08) `table-alias` (`SCHEMA.T.C` <-> `T.C`,
  `confidence="candidate"`).
- `ImpactResult.to_dict()` gained `start_found` (False when nothing matched
  the start field / table / dataset).
- `join_edges()` entries: `{source, target, kind, line, statement,
  confidence, cross}`, node keys as lists (`["P", program, kind, name,
  offset, length]`, `["D", dataset, offset, length]`, `["T", "TABLE.COLUMN"]`,
  and (2026-10-30) `["O", program, callee]`: the hub of a program's
  `opaque-call` edges to one callee, which replaces the edge per argument
  pair. Stored edges of either shape load. An `O` key belongs to `program`
  but is neither a hit nor a hop of an impact path.
- Additive, `lineage_version` unchanged (2026-10-30): `FieldFlowAnalyzer`
  takes `summary_limit` (default `DEFAULT_SUMMARY_LIMIT`, 10,000); past it
  `summary` stops, a caveat says so and `statistics.summary_truncated` is
  true.
- `jobs_from_sources` needs jcl-parser importable; it raises `ImportError`
  otherwise.

### 5. Exception type
```python
from cobolparser import ParseError
```
Adapter catches `ParseError` (the canonical base exception, defined in `cobolparser/_errors.py`) and maps it to a structured error result. `CobolParseError` is exported as a backward-compatible alias of `ParseError` for adapters written against the older name — both resolve to the same class.

---

## CobolProgram AST Contract

The adapter calls these on `parse_result.ast` (a `CobolProgram`):

| Access | Expected |
|--------|----------|
| `program.program_name` | `str \| None` |
| `program.get_statistics()` | `dict` with at least `"total_lines": int` |

Everything else (divisions, sections, paragraphs, data items, CALL/COPY/SQL nodes) is accessed by the extractor modules inside `backend/src/parsers/cobol/extractors/`. Those extractors are in the backend, not the library, so they can be updated there when AST shapes change. The adapters in `extractors/` are the real interface documentation for the full AST — but the five points above are the minimum the main adapter needs.

---

## Extra Keyword Args the Adapter Passes via `parse_content()`

```python
adapter.parse_content(
    content,                           # str — source code
    filename=filename,                 # str | None
    copybook_registry=registry,        # CopybookResolver | None
)
```

`copybook_registry` is NOT passed to the underlying `cobolparser` library — the adapter handles COPY injection itself before calling `parser.parse()`. It calls:
```python
registry.resolve(copybook_name: str) -> str | None
```
Any object with a `resolve(name)` method satisfies this (duck-typed via `CopybookResolver` Protocol in the adapter).

---

## Output: program_structure Shape

The adapter produces this dict (stored in `ParserResult.program_structure`). Downstream services read these paths:

```python
{
    "program_info": {
        "name": str,                      # from program.program_name
        "type": "COBOL",
        "language_version": "IBM Enterprise COBOL",
        "encoding": "utf-8",
        "line_count": int,
        "complexity_score": float,
        "uses_cics": bool,
        "uses_ims": bool,
        "uses_mq": bool,
        "is_transactional_likely": bool,
        "is_batch_likely": bool,
        "is_bmp_program": bool,
        # copybook-only fields (when is_copybook == True):
        "is_copybook": bool,
        "source_kind": str,               # "copybook" | "procedure_copybook" | "program"
        "copybook_name": str,
    },
    "structure": {
        "sections": [{"name": str, "type": str, "start_line": int, "end_line": int}],
        "variables": [{"name": str, "type": str, "definition_line": int, ...}],
        "procedures": [{"name": str, "start_line": int, "end_line": int, "calls": list, "called_by": list, ...}],
    },
    "dependencies": {
        "includes": [str],               # copybook names
        "calls": [str],                  # called program names
        "databases": [{"name": str, "type": str, "tables": list}],
        "copy_statements": [...],
        "file_io": [...],
        "cics_commands": [...],
        "mq_operations": [...],
    },
    "analysis": {
        "metrics": {...},
        "issues": [...],
        "modernization_hints": [...],
        "classification_hints": {...},
        "cics_indicators": {...},
        "ims_indicators": {...},
        "mq_indicators": {...},
    },
}
```

**Critical paths read by backend relationship extractors** (`backend/src/services/relationships/`):
- `dependencies.calls` — list of `str` program names → `CALLS` relationship
- `dependencies.includes` — list of `str` copybook names → `COPYBOOK` relationship
- `dependencies.databases` — list of `{name, type, tables}` → `USES_DB2` relationship
- `dependencies.cics_commands` — → `USES_CICS` relationship
- `dependencies.mq_operations` — → `USES_MQ` relationship
- `program_info.name` — used as the program's canonical name in the DB

---

## ParserResult Container

The adapter wraps everything in `backend/src/parsers/base.ParserResult`:

```python
@dataclass
class ParserResult:
    success: bool
    program_structure: dict | None   # the shape above
    error_message: str | None        # prefixed: "COBOL_PARSE_ERROR: ...", "SYNTAX_ERROR: ...", etc.
    metadata: dict                   # parse timing, dialect, version, injection stats, etc.
```

Error message prefixes the backend uses to classify failures: `EMPTY_CONTENT`, `VALIDATION_FAILED`, `COBOL_PARSE_ERROR`, `SYNTAX_ERROR`, `PARSE_FAILED`, `PERMISSION_ERROR`, `PARSER_INTERNAL_ERROR`, `INTERNAL_ERROR`.

---

## File Extensions Handled

`.cbl`, `.cob`, `.cobol`, `.cpy`, `.copy` (and uppercase variants).

`.cpy`/`.copy` files are detected as copybooks and wrapped in a synthetic COBOL program shell before parsing; line numbers are shifted back to the original after conversion.

---

## Generators Surface (mocky-mock)

Unlike the backend adapter above, `mocky-mock`'s `mockymock generate
--with-data` and `mockymock fixtures` subcommands call the **generators**
package directly, not the parser/analyzer entry points sections 1-5
describe. This section pins that surface. The canonical, exhaustive schema
for the `FixtureBundle` shape this surface returns lives in
[`docs/fixture-bundle-schema.md`](docs/fixture-bundle-schema.md) — this
section names the symbols mocky-mock imports and the one gate it checks
before consuming a bundle; it does not restate the full key table (see that
document for every `FixtureBundle`/`Scenario`/`BoundaryFixture`/
`Expectation` key, the versioning policy, and a worked example).
`mocky-mock`'s own `.okf/integration.md` summarizes this same surface from
the consumer side.

```python
from cobolparser.generators import DataGeneratorOptions, ProgramFixtureGenerator

generator = ProgramFixtureGenerator(DataGeneratorOptions(rows=10))  # rows= optional
bundle = generator.generate_with_scenarios_from_file(
    "PROGRAM.cbl",
    copybook_paths=["path/to/copybooks"],   # optional, same convention as expand_copybooks
    # callee_paths=[...],                    # optional; mocky-mock never passes this (defaults apply)
    mode="happy",                            # "happy" | "branches" | "all"
    seed=7,                                  # optional; a drawn seed is reported on bundle.seed
)

bundle.to_dict()   # dict -- consumed by mockymock.generation.with_data.scaffold_cut_with_data
bundle.to_json()   # str  -- printed verbatim as `mockymock fixtures`'s entire stdout output
# Both take bundle_version=1 for the version 1 shape (the default is 2).
```

| Symbol | mocky-mock use |
|---|---|
| `cobolparser.generators.ProgramFixtureGenerator` | constructor; optionally takes a `DataGeneratorOptions` |
| `cobolparser.generators.DataGeneratorOptions` | `rows=` is the only field mocky-mock ever overrides (from its own `--rows` flag; only passed when given, so the generator's own default otherwise applies) |
| `ProgramFixtureGenerator.generate_with_scenarios_from_file(path, *, copybook_paths=None, callee_paths=None, mode="happy", seed=None) -> FixtureBundle` | the single entry point both mocky-mock subcommands call; mocky-mock only ever passes `copybook_paths`, `mode`, `seed` — `callee_paths` exists for other callers and defaults to `None` |
| `FixtureBundle.to_dict() -> dict` | input to `mockymock generate --with-data`'s bundle→surface join |
| `FixtureBundle.to_json() -> str` | `mockymock fixtures`'s entire stdout output |
| `dict["bundle_version"]` | **the gate**: mocky-mock raises its own `UnsupportedBundleVersionError` and refuses to consume the bundle (stderr + exit 1) the moment this isn't a version it reads, rather than guess at a schema that may have changed meaning underneath it. **Now `2` by default (2026-11-11)**: a mocky-mock that reads only `1` refuses a default bundle until it is updated; until then it can call `to_dict(bundle_version=1)` / `to_json(bundle_version=1)`, or turn a version 2 dict back into version 1 with `cobolparser.generators.expand_shared_fixtures()` |
| `dict["fixtures"]` (version 2) | every distinct `BoundaryFixture` once, by id (`CATEGORY:KEY`, `CATEGORY:KEY#2`, ...); each scenario's `"fixtures"` is the list of ids it uses, in order. The fixture dicts themselves are unchanged from version 1 |
| `BoundaryFixture` keys `"category"`, `"key"`, `"direction"`, `"layout"`, `"sequence"`, `"terminal"`, `"status"` (also carries `"line"`, `"paragraph"`, `"provenance"`, `"unresolved"`, which mocky-mock's loader reads into memory but does not join on) | joined against mocky-mock's own `mock_surface.BoundarySite`s uniformly by `(category, key)`, including SQL/CICS/DLI — for those, `key` holds a normalized shortest-unique-prefix of the EXEC statement's text (mocky-mock's surface records no stable identifier-style key for those sites), computed independently by the same prefix rule on both sides so they land on the same string. See `docs/fixture-bundle-schema.md`'s `BoundaryFixture` table for every key's full type and meaning. |

| `FieldSpec` keys `"odo_controls"`, `"odo_counter_bounds"` (2026-09-05) | additive, inside every `"layout"`. `odo_controls` is one `{depending_on, subscript_index, min_times, max_times}` per `OCCURS ... DEPENDING ON` dimension the field sits inside (`[]` for most fields); `odo_counter_bounds` is `[min, max]` on a field that is itself such a counter, else `null`. mocky-mock does not read either — they exist so a consumer that writes *record images* can decide which occurrences a given record contains. A bundle produced before these keys existed is still a valid v1 bundle. |

| `Scenario` key `"verification"` (2026-09-04) | additive, present only for a `"branches"`/`"all"` scenario: cobol-parser's own verdict on whether that scenario's generated data actually satisfies the branch it is named for. mocky-mock reads it defensively (`Scenario.verification` defaults to `None`) and renders an `unverified` verdict as a `*> UNVERIFIED:` comment above the generated TESTCASE. A bundle produced before this key existed is still a valid v1 bundle. |

**No bump for the 2026-09-07 audit fixes, and why.** That pass changed which
arms a bundle reports as `targeted` vs `missed`, and removed scenarios for
arms whose constraints turned out not to be modellable at all (see
`reports/audit-2026-09-07.md`, H1/H2). No key was added, removed, retyped, or
given a new meaning: `targeted` still means "a scenario pins this arm",
`missed` still means "it does not, and here is why". What changed is that
both are now *true* — arms were previously reported targeted on the strength
of a constraint fabricated from an operand's source text, and scenarios were
emitted carrying witnesses that did not satisfy their own branch. A consumer
gated on `bundle_version == 1` parses these bundles exactly as before, so the
gate correctly does not fire.

What a consumer *will* notice: a program using the affected constructs (a
comparison against a subscripted table element, `IF <PIC X field> IS
NUMERIC`, an ordering comparison on an alphanumeric field) yields fewer
scenarios and a lower `targeted` count than it did before. That is the
corrected number, not a regression — the previous count included arms nothing
reached.

**No bump for the 2026-10-29 `field_equals` change, and why.** A
`field_equals` is now offered only when the field still holds its value when
the entry paragraph returns, and the fold now follows IF/EVALUATE branches
the scenario's data decides and observes every field of a written group
record. No key was added, removed or retyped. The meaning of `value` gained
a condition that makes it true for the way mocky-mock uses it: mocky-mock
renders a `field_equals` as an `EXPECT`, which runs after the PERFORM of the
entry paragraph, so a field shown as 1 and then set to 2 used to produce an
`EXPECT` that failed on its first run. A consumer gated on
`bundle_version == 1` parses these bundles exactly as before.

**No bump for the `PIC N`/`PIC G` byte-width fix, and why.** `PIC N(n)`/`PIC
G(n)` items now size at 2 bytes per character instead of 1 — correct for IBM
Enterprise COBOL's national/DBCS storage, where each `N`/`G` position is one
double-byte character (`models/data_items.py`'s `PictureClause._parse_pattern`).
No key was removed, retyped, or given a new meaning: `FieldSpec`/`layout`'s
`"length"`/`"byte_offset"`-shaped keys are still `int` byte counts with the
same meaning as before. What changed is the *value* those keys carry for a
record containing such an item — the same shape of change the 2026-09-07 note
above describes, so the same reasoning applies and the gate correctly does not
fire.

What a consumer *will* notice: a program with a `PIC N`/`PIC G` field now
generates (`gen-data`), reports (`data-items`), and lays out
(`FixtureBundle.layout`) that field at twice its previous byte width, and
every field after it in the same record shifts to a correspondingly higher
byte offset. That is the corrected width, not a regression — the previous
width silently treated a double-byte national character as single-byte.

**Versioning contract this surface must honor:** any change to
`generate_with_scenarios_from_file`'s signature, a key removed or
retyped from `FixtureBundle`/`Scenario`/`BoundaryFixture`/`Expectation`, or
a key's meaning changed under an unchanged name, is a breaking change for
mocky-mock exactly as it would be for the backend adapter above — bump
`bundle_version` (see `docs/fixture-bundle-schema.md`'s "Versioning and
compatibility policy") so mocky-mock's gate catches it instead of silently
emitting corrupted `.cut` data.

---

## MCP Surface

`cobol-parser mcp` (`cobolparser/mcp/`, added 2026-10-15) serves tools to MCP
clients: AI agents in Claude Code, Claude desktop, Cursor and similar. The
same tools are callable without the SDK as `cobolparser.mcp.CobolTools`
methods returning the same dicts. User guide: `docs/mcp-server.md`.

What a client depends on:

- The tool names `codebase_overview`, `program_brief`, `explain_symbol`,
  `callers_of`, `impact_of_change`, `where_from`, `record_layout`, `lint`,
  `read_source`, `business_rules`, `diff_programs`, `decode_record` and
  `gen_fixtures` (the last four added 2026-10-27), `jcl_job`,
  `jobs_running` and `dataset_users` (added 2026-10-28; they answer only
  with the `[jcl]` extra installed, and otherwise raise a tool error naming
  `pip install 'cobol-parser[jcl]'`), and their argument names. (`callers_of`'s `file` became optional on 2026-10-15, which no
  existing call notices.)
- The prompt names `explain_program`, `review_program`, `plan_change`,
  `document_business_rules` and `onboard_codebase`, and their argument
  names (`cobolparser/mcp/prompts.py`). A prompt's text may change freely.
- The envelope every tool returns: `surface_version`, `answer`, `caveats`
  (`kind`, `detail`, optional `effect`), `truncated` (`field`, `shown`,
  `total`) and, for tools about a program, `program` (`file`,
  `program_id`, `program_units`).
- Locations as `{"file", "line", "column"?}`, root-relative paths on disk.
- With the `[pl1]` / `[hlasm]` extras (added 2026-10-28), PL/I and assembler
  programs appear in the cross-program answers with an optional `language`
  key (absent means COBOL), and `program_brief` on such a file answers with
  `language`, `procedures` or `sections`, `calls`, `includes`, `services`,
  `called_by` instead of the COBOL sections. Every other file tool refuses
  such a file with a tool error, as it refused it before as a failed parse.
- The closed `caveats[].kind` vocabulary, `cobolparser.mcp.CAVEAT_KINDS`.

**Versioning contract:** removing or renaming a tool or argument, removing or
retyping an envelope key, changing a key's meaning, or adding a caveat kind
bumps `MCP_SURFACE_VERSION` (`cobolparser/mcp/envelope.py`). Adding a new tool
or a new optional key to an `answer` does not.

