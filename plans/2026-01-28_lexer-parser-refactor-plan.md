# Lexer/Parser Modularization Plan (Minimal-Move, Plugin-Managed Dialects)

Date: 2026-01-28

## Goal
Refactor the lexer and parser into smaller, maintainable modules while retaining all public APIs (`CobolLexer`, `CobolParser`, `tokenize_cobol`, `parse_cobol`). IBM Enterprise COBOL specifics should be isolated into dialect modules loaded via `PluginManager` with minimal behavioral change.

## Constraints
- **Minimal-move:** No public API changes.
- **TDD:** Add or relocate tests alongside refactor steps; preserve coverage ≥ 90%.
- **Dialect priority:** IBM Enterprise COBOL support remains the default behavior.
- **Performance:** Avoid extra passes over token streams; no regression in memory usage.

## Current Hotspots (Audit Summary)
- `cobolparser/lexer.py` mixes base COBOL keywords with IBM Enterprise tokens and keyword mappings, making dialect-specific behavior hard to isolate.
- `cobolparser/parser.py` contains IBM EXEC SQL/CICS parsing inside core parser logic, increasing complexity and coupling.
- Cross-cutting: `PluginManager` exists but dialect parsing is still embedded inside the main parser.

## Target Module Boundaries
### Lexer
1) **Base keyword map (ANSI-ish)**
   - **Keep in:** `cobolparser/lexer.py`
   - Purpose: standard COBOL keywords only.

2) **IBM keyword/token map**
   - **New:** `cobolparser/dialects/ibm_lexer_keywords.py`
   - Contents:
     - `IBM_KEYWORDS: dict[str, TokenType]`
     - `IBM_RESERVED_WORDS: set[str]`
   - **New:** `cobolparser/dialects/ibm_lexer_tokens.py`
   - Contents:
     - Any IBM token aliases/expansions for EXEC/SQL/CICS/COPY/REPLACING

3) **Keyword resolution hook**
   - **In:** `CobolLexer.__init__` (minimal change)
   - Merge base keywords with dialect keywords from `PluginManager` (dialect-specific map overrides base entries only when required).

### Parser
1) **IBM EXEC parsing**
   - **New:** `cobolparser/dialects/ibm_exec_parser.py`
   - Class: `IBMExecParser`
   - Move from `parser.py`:
     - `_parse_exec_inline`
     - `_parse_exec_sql_inline`
     - `_parse_exec_cics_inline`
     - `_parse_exec_ims_inline`
     - `_skip_to_end_exec`

2) **Dialect hook for EXEC**
   - **In:** `CobolParser` (internal only)
   - When `TokenType.EXEC` found, delegate to `self.dialect_parser.parse_exec_inline(...)`.
   - If no dialect parser, fallback to current behavior (fail-fast or skip).

3) **Optional IBM data clause hook**
   - **New (optional):** `cobolparser/dialects/ibm_data_parser.py`
   - Hook `_parse_usage_clause` for IBM-specific validation or COMP-3 storage logic.

## PluginManager Integration
- Extend `PluginManager` to provide optional dialect hooks:
  - `get_lexer_keywords(dialect: DialectType) -> dict[str, TokenType]`
  - `get_lexer_reserved_words(dialect: DialectType) -> set[str]`
  - `get_exec_parser(dialect: DialectType) -> object | None`
- `CobolLexer` and `CobolParser` request dialect hooks from `PluginManager` at init.

## Test Reorganization
- Add IBM-specific tests under:
  - `tests/dialects/ibm/`
- Move/duplicate existing EXEC/SQL/CICS tests there; retain existing test paths if used by CI.
- Create new tests for:
  - keyword map merge behavior
  - `PluginManager` hook presence/absence
  - EXEC parser delegation when dialect is IBM

## Implementation Steps (Order)
1. **Add dialect keyword modules**
   - Create `ibm_lexer_keywords.py` and `ibm_lexer_tokens.py` with IBM mappings.
   - Update `lexer.py` to merge base + dialect maps.

2. **Add IBM EXEC parser module**
   - Create `ibm_exec_parser.py` with `IBMExecParser` class.
   - Move EXEC-related functions from `parser.py` into this class.

3. **Add PluginManager hooks**
   - Implement accessors for dialect lexer keywords and exec parser.
   - Wire `CobolLexer` and `CobolParser` to use plugin hooks.

4. **Update parser delegation**
   - Replace inline EXEC parsing call sites with `self.dialect_parser` call.

5. **Tests**
   - Add/relocate tests for IBM keyword loading and EXEC parsing.
   - Ensure tests cover fallback behavior when dialect hooks are missing.

6. **Stabilization**
   - Run full test suite and coverage.
   - Verify no public API changes; existing imports remain valid.

## Risk Mitigation
- **Minimal-move:** Keep public signatures and entry points unchanged.
- **Fallback behavior:** If dialect hook is missing, parser should use legacy parsing or safe skip with warning.
- **Coverage:** Ensure IBM-specific functionality is fully exercised in new dialect tests.

## Deliverables
- New dialect modules:
  - `cobolparser/dialects/ibm_lexer_keywords.py`
  - `cobolparser/dialects/ibm_lexer_tokens.py`
  - `cobolparser/dialects/ibm_exec_parser.py`
  - (optional) `cobolparser/dialects/ibm_data_parser.py`
- Updated `PluginManager` integration
- Updated tests under `tests/dialects/ibm/`

## Acceptance Criteria
- All existing tests pass with coverage ≥ 90%.
- IBM EXEC/SQL/CICS parsing still functions identically.
- Lexer keyword behavior unchanged except the new modular source.
- `CobolLexer`, `CobolParser`, `tokenize_cobol`, and `parse_cobol` APIs remain unchanged.
