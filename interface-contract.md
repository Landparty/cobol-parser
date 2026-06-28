# Backend Integration Contract — cobol-parser

This document describes exactly what `backend/src/parsers/cobol/parser.py` (the `CobolLegacyParser` adapter) calls into `cobolparser`, and what shapes it expects back. Change these APIs or their return shapes in `cobolparser` and the adapter breaks.

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
| `parse_result.success` | `bool` | True = AST was built |
| `parse_result.ast` | `CobolProgram \| None` | None when `success` is False |
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

### 4. Program flow analysis (optional, fault-isolated)
```python
from cobolparser import ProgramFlowAnalyzer

flow_report = ProgramFlowAnalyzer().analyze(parse_result.ast)
flow_dict = flow_report.to_dict()    # must return dict
```
- Result is stored in `metadata["program_flow_data"]`.
- Wrapped in try/except — failure returns None without blocking.

### 5. Exception type
```python
from cobolparser import CobolParseError
```
Adapter catches `CobolParseError` specifically and maps it to a structured error result.

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
