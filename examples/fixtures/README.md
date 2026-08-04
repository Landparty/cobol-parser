# fixtures/FIXTUREDEMO — the gen-fixtures worked example

The end-to-end worked example for the `gen-fixtures` program-scoped
test-data initiative (Phase 9 of
[`docs/plans/2026-08-02-program-data-generation-implementation.md`](../../docs/plans/2026-08-02-program-data-generation-implementation.md)):
one small program touching all four boundary categories the initiative
supports, with every boundary resolving cleanly.

| Boundary | Statement in `FIXTUREDEMO.cbl` | Category |
|----------|-------------------------------|----------|
| Console input | `ACCEPT WS-CUSTOMER-ID` | `ACCEPT` |
| File open/close | `OPEN INPUT ORDER-FILE` / `CLOSE ORDER-FILE` | `OPEN` / `CLOSE` |
| File read | `READ ORDER-FILE ... AT END ...` | `READ` |
| Embedded SQL | `EXEC SQL SELECT CUST_NAME INTO :WS-CUST-NAME ... END-EXEC` | `SQL` |
| Subprogram call | `CALL "LOGALERT" USING WS-ALERT-STATUS` | `CALL` |

Unlike [`examples/custprog/`](../../../mocky-mock/examples/custprog/) in the
sibling `mocky-mock` repo (which deliberately demonstrates a known DCLGEN
`EXEC SQL INCLUDE` gap), every boundary here resolves with zero entries in
`report.unresolved` / `bundle.unresolved` — this is the clean reference,
not an edge case.

## The golden bundle

`FIXTUREDEMO.bundle.json` is the checked-in `FixtureBundle` JSON,
generated at a fixed seed:

```python
from cobolparser.generators import ProgramFixtureGenerator

bundle = ProgramFixtureGenerator().generate_with_scenarios_from_file(
    "examples/fixtures/FIXTUREDEMO.cbl", mode="happy", seed=42,
)
bundle.to_json()  # byte-identical to FIXTUREDEMO.bundle.json, always
```

Pinned by [`tests/regression/test_fixturedemo_golden.py`](../../tests/regression/test_fixturedemo_golden.py).

## Cross-repo golden

The sibling `samdion1994/mocky-mock` repo copies this exact `.cbl` and
`.bundle.json` pair into its own `examples/fixtures/` and consumes the
bundle JSON directly (`mockymock generate FIXTUREDEMO.cbl --fixtures
FIXTUREDEMO.bundle.json`) to produce `FIXTUREDEMO.cut`, also checked in as
a golden there. If you change `FIXTUREDEMO.cbl` or bump the seed here,
re-copy both files and regenerate `.cut` over there in the same change —
see that repo's own `examples/fixtures/README.md`.
