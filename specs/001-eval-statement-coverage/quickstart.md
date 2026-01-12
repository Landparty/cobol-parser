# Quickstart — EVALUATE Coverage Feature

1) **Baseline (no changes)**
   - `python -m pytest tests -v`  
   - `python -m pytest --cov=cobolparser --cov-fail-under=90`

2) **Add TDD fixtures first**
   - Positive variants: add to `tests/unit/` (AST assertions) and `tests/contract/` (serialized JSON).
   - Negative variants: add to `tests/unit/` or `tests/contract/` with expected diagnostics.
   - Integration samples: update `tests/samples/control_flow.cbl` or add new sample(s) plus `tests/integration/` coverage gate.

3) **Implement parser/AST**
   - Add `EvaluateStatement` node in `cobolparser/models/statements.py`.
   - Implement EVALUATE parsing in `cobolparser/parser.py` using existing helpers; enforce fixed-format columns and END-EVALUATE.
   - Wire diagnostics to include line/column and category.

4) **Regression & coverage gate**
   - Re-run `python -m pytest tests -v`.
   - Verify coverage report includes new tests; ensure variant coverage gate passes.

5) **Performance sanity**
   - Optional: run existing benchmarks if available; confirm no >10% slowdown.

6) **Docs & changelog**
   - Update statement coverage docs if needed; ensure `to_dict()` schema documented in node docstring.
