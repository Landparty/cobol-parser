---
type: History
title: Backend Integration Contract history
description: Archived dated notes moved out of integration.md; not loaded by default.
tags: [history, integration]
timestamp: 2026-10-15T00:00:00Z
---

# Backend Integration Contract history

Archive of dated notes moved verbatim from [integration.md](../integration.md) on 2026-10-15, when the topic file was restructured to describe only the current state. Every still-valid behaviour, invariant and rationale in these notes is restated in present tense in the topic file; what remains here is the when and the before/after. Newest first. Links inside quoted text point at the topic files as they stood.

## Corrected values that were not `bundle_version` bumps (2026-09-07 audit)

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
