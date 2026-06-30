# OKF Update Log

## 2026-06-30

* **Logged untracked drift from commit `cad4db6` (2026-06-29, "Add integration
  contract documentation for backend API")**: that commit added
  [integration.md](integration.md) and updated [lexer.md](lexer.md) and
  [index.md](index.md), but never got a log.md entry. Backfilling it now:
  - **Produced** [integration.md](integration.md): documents the backend
    adapter contract (`backend/src/parsers/cobol/parser.py`) — entry points
    (`CobolParser(...).parse()`, optional `DynamicCallAnalyzer`/
    `ProgramFlowAnalyzer` analyzers, `CobolParseError`), `ParseResult`/
    `CobolProgram` attribute contract, the `program_structure` output dict
    shape, the `dependencies.*` → Neo4j relationship mapping
    (`CALLS`/`COPYBOOK`/`USES_DB2`/`USES_CICS`/`USES_MQ`), the backend's
    `ParserResult` dataclass, and handled file extensions. Defers to the
    canonical `interface-contract.md` (repo root) via the `resource:`
    frontmatter field for full detail (e.g. copybook-specific
    `is_copybook`/`source_kind`/`copybook_name` fields and the
    `VALIDATION_FAILED`/`PERMISSION_ERROR` error-message prefixes are in the
    canonical doc but intentionally summarized out of the OKF concept).
  - **Updated** [lexer.md](lexer.md) Cython Acceleration section: replaced the
    bare 3-module table with one that lists the actual pure-Python file each
    `.pyx` overrides and the specific accelerated symbols (confirmed against
    `cobolparser/_lexer_fast.pyx`: `check_division_header`,
    `read_word_from_text`, `tokenize_program_text`, `_try_single_line_string`,
    `read_number_from_text`, `tokenize`; `_preprocess_fast.pyx`:
    `normalize_fixed_format`; `_data_fast.pyx`:
    `parse_picture_clause_fast`, `parse_data_item_clauses_fast`). Added the
    guarded `try/except ImportError` activation pattern, the `~3x` throughput
    figure (from `setup.py`), and the `pip install -e ".[fast]"` extra
    (`pyproject.toml`).
  - **Updated** [index.md](index.md): added the "Integration" section linking
    to integration.md.
  - Corrected `timestamp` on lexer.md and integration.md from `2026-06-28` to
    `2026-06-29` to match the commit that actually authored their current
    content.
* **Fixed pre-existing gaps in [cli.md](cli.md)** found while verifying
  concept files against current source (none of these came from a dated
  commit since the last log entry — they predate the OKF bundle itself,
  ranging from 2026-04-17 to 2026-05-06):
  - `analyze` subcommand was documented as running "all static analyzers"
    (dead code, IO, MOVE-type, linkage, LE); it actually only runs
    `DynamicCallAnalyzer` and reports dynamic `CALL` target info
    (`called_program`/`is_dynamic`/`possible_values`) — corrected.
  - `program-flow` was missing its `--format json|mermaid|dot` flag (added in
    commit `842f246`, wired to `generators/flowchart.py`'s
    `MermaidFlowchartGenerator`/`DotFlowchartGenerator`).
  - `parse`, `batch`, `program-flow`, `analyze`, and `dead-code` were missing
    the shared `--profile`/`--profile-top-n`/`--profile-output` flags (added
    in commit `5f2468c`/`13a3f1f`).
  - `batch` was missing `--glob` (repeatable), `--workers`, and `--encoding`.
  - `tokenize` output shape was missing the `column` field.
  Bumped cli.md `timestamp` to 2026-06-30.

## 2026-06-28

* **Initialization**: Created OKF bundle for cobolparser v1.1.0.
  Concepts produced: [lexer](lexer.md), [parser](parser.md),
  [preprocessing](preprocessing.md), [ast-models](ast-models.md),
  [analysis](analysis.md), [cli](cli.md), [tests](tests.md).
