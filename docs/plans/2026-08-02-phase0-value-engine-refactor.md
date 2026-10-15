# Phase 0 — Split the value engine out of `copybook_data.py`

**Date:** 2026-08-02
**Status:** Ready to implement
**Parent:** [`2026-08-02-program-data-generation-design.md`](2026-08-02-program-data-generation-design.md)
**Type:** Pure refactor — **zero behavior change**

---

## Why this first

Every later phase needs to generate a value for a `FieldSpec` that did **not**
come from a copybook root: a record hanging off an FD, a `LINKAGE` 01, a single
`ACCEPT` target, a list of SQL `INTO` host variables. Today that capability is
reachable only through `CopybookDataGenerator.generate_from_source()` — parse a
copybook, pick a record, get a CSV. The engine is sound; the entry points are
the problem.

This phase changes no behavior at all. It exists so Phases 1–5 can call
`ValueFactory` and `flatten_record` directly instead of growing a second copy.

**Success is defined negatively:** the full suite passes untouched, and
`gen-data` emits byte-identical CSV for every sample copybook at every seed.

---

## Target structure

`cobolparser/generators/copybook_data.py` (1265 lines) becomes
`cobolparser/generators/data/`:

| Module | Contents | Imports (intra-package) |
|---|---|---|
| `options.py` | `DataGeneratorOptions` | — (leaf) |
| `errors.py` | `CopybookLayoutError` | — (leaf) |
| `layout.py` | `FieldCategory`, `FieldSpec`, `flatten_record`, `_flatten_into`, `_occurrence_indexes`, `_assign_columns`, `_child_items`, `_condition_values`, `_classify`, `_is_signed`, `_digit_counts`, `_strip_literal_quotes`, `_MAX_RANGE_EXPANSION`, `_REPEAT_COUNT_RE`, `_THROUGH_RE`, `_INTEGER_LITERAL_RE` | `options` |
| `values.py` | `ValueFactory` (renamed), all `_*_TOKENS` frozensets, the `_FIRST_NAMES`/`_CITIES`/… corpora, `_FIGURATIVE_CONSTANTS`, `_name_tokens`, `_WORD_SPLIT_RE`, `_MAX_RANDOM_TEXT` | `options`, `layout` |
| `dataset.py` | `GeneratedDataset`, `_DEFAULT_LINE_TERMINATOR` | `layout` |
| `copybook.py` | `parse_copybook_records`, `CopybookDataGenerator`, `_looks_like_program`, `_looks_fixed_format`, `_wrap_fragment`, `_all_data_items`, `_top_level_items`, `_synthesise_record`, `_WRAPPER_HEAD`/`_TAIL`, `_PROGRAM_RE`, `_PROGRAM_ID_RE`, `_FREE_FORM_LEVEL_RE` | all of the above |
| `__init__.py` | re-exports the public names + `ValueFactory` | all |

The dependency graph is a DAG — `options`/`errors` are leaves, `layout` sits
above them, `values` and `dataset` above `layout`, `copybook` on top. Nothing
under `data/` may import `cobolparser.generators` (the package `__init__`), or
the shim below creates a cycle.

**Two refinements to the parent plan's four-module sketch**, both discovered
while reading the code:

- **`dataset.py` is its own module, not part of `copybook.py`.** Phase 6 emits
  one CSV per file boundary per scenario (`out/happy-path/INV-FILE.csv`) —
  that is exactly a `GeneratedDataset`. Keeping it out of the copybook-specific
  module means Phase 6 imports it without dragging in the copybook parser.
- **`errors.py` exists** even though `CopybookLayoutError` is the only tenant.
  Phase 1's `ProgramLayoutIndex` needs a sibling error, and a leaf module now
  saves a second move later.

---

## Symbol-level notes that matter

These are the places a naive cut-and-paste breaks something:

1. **`_strip_literal_quotes` has two callers in two different target modules** —
   `_condition_values` (→ `layout.py`) and `ValueFactory._from_value_clause`
   (→ `values.py`). It goes in `layout.py`; `values.py` imports it. Do not
   duplicate it.

2. **`_MAX_RANGE_EXPANSION` and `_DEFAULT_LINE_TERMINATOR` are declared at
   lines 382–388, *after* `_condition_values` uses the former.** That works
   today only because the use is at call time, not import time. They split to
   different modules (`layout.py` and `dataset.py` respectively) — move each to
   the top of its new module rather than preserving the odd placement.

3. **`FieldCategory` is referenced by both `layout` and `values`.** It is a
   classification of layout, so it lives in `layout.py` and `values.py` imports
   it. Do not put it in `options.py` "because it's an enum".

4. **`_ValueFactory` → `ValueFactory`.** Nothing outside the module references
   it (verified: no test, no CLI import), so the rename is free. Export it from
   `cobolparser.generators.data` **only** — not from `cobolparser.generators`.
   Widening the top-level package API is a Phase 3 decision, made when there is
   a caller.

5. **`GeneratedDataset` is a `@dataclass`** whose `to_csv`/`write_csv` both
   default to `_DEFAULT_LINE_TERMINATOR`. They must keep sharing one constant —
   this is the invariant behind the byte-identical guarantee, and the source of
   a bug already fixed once (commit `2736ae4`).

6. **Every new module needs `from __future__ import annotations`.** The
   original has it; each split file needs its own.

---

## The compatibility shim

`cobolparser/generators/copybook_data.py` is replaced by:

```python
"""Backwards-compatible re-exports.

The canonical home is :mod:`cobolparser.generators.data`.  This module is
kept because `tests/unit/test_copybook_data_generator.py`, the CLI's lazy
import in `cli/parse.py`, and the vendored backend copy all import from
this path.
"""

from __future__ import annotations

from .data.copybook import CopybookDataGenerator, parse_copybook_records
from .data.dataset import GeneratedDataset
from .data.errors import CopybookLayoutError
from .data.layout import FieldCategory, FieldSpec, flatten_record
from .data.options import DataGeneratorOptions

__all__ = [
    "CopybookDataGenerator",
    "CopybookLayoutError",
    "DataGeneratorOptions",
    "FieldCategory",
    "FieldSpec",
    "GeneratedDataset",
    "flatten_record",
    "parse_copybook_records",
]
```

`__all__` must stay **exactly** today's list — same names, same order.

Ruff detail: this is not an `__init__.py`, so the `F401` per-file ignore does
not apply. Listing every imported name in `__all__` is what keeps ruff quiet;
do not add a blanket `# noqa`.

`cobolparser/generators/__init__.py` stays **unchanged** — it keeps importing
`from .copybook_data import …`, now transitively. That is deliberate: it proves
the shim works, since the contract test imports from `cobolparser.generators`.

---

## Execution order

Seven steps, each independently green — after every step, `pytest tests/unit
tests/contracts -q` passes. Move one module out at a time and leave a
re-export behind in `copybook_data.py` until the final step swaps the whole
file for the shim.

| # | Step | Verify |
|---|---|---|
| 1 | Create `data/__init__.py`, `options.py`, `errors.py`; move `DataGeneratorOptions` + `CopybookLayoutError`; re-export from `copybook_data.py` | unit + contract |
| 2 | Move layout: `FieldCategory`, `FieldSpec`, flattening, classification, the four regexes, `_strip_literal_quotes` | unit + contract |
| 3 | Move `values.py`: rename `_ValueFactory` → `ValueFactory`, move the corpora and token sets | unit + contract |
| 4 | Move `dataset.py`: `GeneratedDataset` + `_DEFAULT_LINE_TERMINATOR` | unit + contract + **CSV golden** |
| 5 | Move `copybook.py`: parsing, wrapping, `CopybookDataGenerator` | full suite |
| 6 | Replace `copybook_data.py` with the shim; populate `data/__init__.py`'s `__all__` | full suite + lint + mypy |
| 7 | Docs: `.okf/generators.md`, `CLAUDE.md`, `CHANGELOG.md` | pre-commit hook passes |

Run `black` after **every** step. A move plus a reformat in one commit makes
the diff unreviewable, and reviewability is most of this phase's value.

---

## Verification

### The CSV golden — the load-bearing gate

A refactor claiming zero behavior change should be *proved*, not asserted.
Before touching anything, capture the current output:

```bash
# tools/dev/capture_gen_data_baseline.py  (throwaway, not committed)
for cpy in tests/samples/copybooks/*.cpy examples/cobol/*.CPY; do
  for seed in 1 7 2024; do
    cobol-parser gen-data "$cpy" --rows 25 --seed $seed
  done
done | sha256sum
```

Re-run after step 6. **The hash must match.** This catches every class of
mistake this refactor can make — a reordered `_make` dispatch, a lost
`allow_random_sign=False`, a different line terminator, an RNG draw that moved
— none of which the existing assertions necessarily catch, because most of them
check *properties* of values (fits the picture, in the 88 domain), not the
exact bytes.

Also compare `--output` against stdout for one copybook, byte for byte. That is
the specific invariant `write_csv` broke before.

### Standing gates

- `python -m pytest tests/ -v` — full suite, 81% coverage floor holds
  (moving code between modules does not change which lines execute).
- `tests/contracts/test_copybook_data_generator_contract.py` — **not edited**.
  It imports from `cobolparser.generators`, pins exported names, signatures,
  `to_dict()` key sets, and seed reproducibility. If it needs a change, the
  refactor broke the API.
- `ruff check .`, `black --check .`, `mypy cobolparser/`.

### One new test

`tests/contracts/test_copybook_data_module_paths.py` — asserts the old and new
import paths resolve to the **same object**, not merely equal ones:

```python
@pytest.mark.parametrize("name", [...the eight public names...])
def test_shim_and_canonical_are_the_same_object(name):
    from cobolparser.generators import copybook_data
    from cobolparser.generators import data
    assert getattr(copybook_data, name) is getattr(data, name)
```

Two copies of `FieldSpec` that pass `==` but fail `is` would break every
downstream `isinstance` check — exactly the failure a shim introduces if
someone later "fixes" it by re-defining rather than re-exporting.

---

## Risks

| Risk | Mitigation |
|---|---|
| Reformat noise swamps the move diff | `black` after each step; never mix a move and an edit in one commit |
| Circular import via `generators/__init__` | Nothing under `data/` imports the parent package; step 6 is where this would surface, and the full suite catches it |
| Silent RNG-sequence change | The CSV golden. A reordered call to `self._rng` changes every subsequent draw |
| mypy strict on the new modules | Config has no `no_implicit_reexport`, so re-exports are fine; moved code already type-checks |
| Pre-commit OKF staleness hook blocks the commit | Step 7 updates `.okf/generators.md` in the same commit as the source move — this is a real source change, so `--no-verify` is not appropriate |
| Vendored backend copy drifts | `cp -r cobolparser/ ../backend/_vendor/cobol-parser/cobolparser/` per `CLAUDE.md`; the shim means the adapter needs no edit |

No interaction with the Cython modules: `_data_fast` accelerates the DATA
DIVISION picture/clause loops in the *parser*, not the generator.

---

## Definition of done

- `cobolparser/generators/data/` exists with the seven modules above.
- `copybook_data.py` is a shim whose `__all__` matches today's exactly.
- `generators/__init__.py` is unchanged.
- `ValueFactory` and `flatten_record` are importable from
  `cobolparser.generators.data` and usable against **any** `CobolDataItem` —
  the capability Phase 1 consumes.
- CSV golden hash matches pre-refactor.
- Full suite, lint, typecheck green; contract test unedited.
- `.okf/generators.md` documents the new layout; `CHANGELOG.md` records it
  under Unreleased as an internal restructure with no API change.

**Size:** ~1265 lines moved, roughly 60 lines of new code (module docstrings,
`__init__` re-exports, the one new test). One PR, seven commits.
