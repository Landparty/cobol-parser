# Documentation Audit Design

**Date:** 2026-03-30
**Goal:** Bring all live, user-facing documentation up to date with the current codebase state (v1.x post-refactor, 2975 tests, 81%+ coverage enforced, BC aliases removed).

---

## Scope

Live documentation only. Archived content in `docs/archived_docs/` is excluded.

### Doc Clusters (parallel audit streams)

| Stream | Files |
|--------|-------|
| **A — Project root** | `README.md`, `CHANGELOG.md` |
| **B — Docs hub** | `docs/README.md`, `docs/PARSER_INVOCATION_GUIDE.md`, `docs/cookbook.md` |
| **C — Statement guides** | `docs/call-statements.md`, `docs/perform-statements.md`, `docs/sql-statements.md`, `docs/cics-ims-statements.md`, `docs/copy-statements.md`, `docs/complete-program.md` |
| **D — Data & factory guides** | `docs/data-items.md`, `docs/file-control.md`, `docs/ibm-enterprise.md`, `docs/copybook-expansion.md`, `docs/factory-api.md`, `docs/factory-performance.md`, `docs/factory-extension-guide.md`, `docs/ibm-dialect-registration.md` |

---

## What Each Agent Checks

Each agent reads its assigned docs **and** the relevant source files to verify:

1. **Metric accuracy** — test counts, coverage %, version numbers, badges
2. **API accuracy** — import paths, class/function names, constructor signatures, removed aliases
3. **Broken internal links** — references to deleted files (e.g. `.specify/memory/constitution.md`)
4. **Content currency** — "Most Critical Gaps" lists, feature status claims, roadmap items that are now complete
5. **CHANGELOG** (stream A only) — write new entries for all changes since v1.1.0 based on git log

---

## Known Staleness (pre-audit baseline)

| Location | Stale Content |
|----------|---------------|
| `README.md` badges | "618 passing" tests → now 2,975; "57%+ coverage" → now 81%+ enforced |
| `README.md` body | Multiple "618 tests" mentions |
| `docs/README.md` | Stats dated 2026-01-11; "27% of COBOL statements" claim; references deleted `.specify/memory/constitution.md`; "Most Critical Gaps" list includes items that are now implemented |
| `CHANGELOG.md` | Last entry v1.1.0 (2026-01-29); 3+ months of BC removals, refactors, new parsers, edge-case fixes undocumented |

---

## Architecture

- Four subagents run in parallel, one per stream.
- Each agent reads the doc(s) in its stream, reads relevant source files to verify API accuracy, then edits the docs in place.
- No production code changes — documentation files only.
- After all agents complete, a single verification pass confirms no broken links remain.

---

## Success Criteria

- All test count references reflect 2,975 (or "2,900+" if rounded).
- All coverage references reflect the 81% minimum enforcement.
- No references to deleted files (`.specify/memory/constitution.md`, removed aliases).
- CHANGELOG has entries for all significant changes since v1.1.0.
- All code examples in topic guides use current import paths and API signatures.
- No "Most Critical Gaps" entries for features that are now implemented.
