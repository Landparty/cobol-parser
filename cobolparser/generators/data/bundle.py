"""Fixture bundle model: the JSON-serializable output of gen-fixtures.

Phase 3 of program-scoped test-data generation (the `gen-fixtures`
initiative). A `FixtureBundle` is the versioned, machine-readable artifact
`ProgramFixtureGenerator` produces -- one bundle per program, one or more
`Scenario`s inside it, each carrying the `BoundaryFixture`s (mock in-data) and
`Expectation`s (assertions) for that scenario.
"""

from __future__ import annotations

import csv
import io
import os
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from .layout import FieldSpec

if TYPE_CHECKING:
    # Deferred: cobolparser.analysis.boundary_inventory imports
    # cobolparser.generators.data.program_layout, so a top-level import here
    # would be circular (this module is reached via generators/__init__.py ->
    # copybook_data.py -> data/__init__.py -> here). `BoundaryRef` is only
    # ever used as a type annotation below -- `from __future__ import
    # annotations` keeps it a lazy string at runtime, so the import only
    # needs to exist for type checkers.
    from ...analysis.boundary_inventory import BoundaryRef

#: Bumped only on a breaking change to the JSON shape. Phase 8 (mockymock
#: integration) checks this before consuming a bundle; fail closed on an
#: unknown version rather than guess at a schema that changed underneath it.
BUNDLE_VERSION = 1


@dataclass
class Expectation:
    """One assertable claim about a scenario's outcome.

    Three confidence tiers (Phase 7 fills tiers 1-2; Phase 3 emits none --
    a "happy path" scenario has no scenario-specific branch outcome to
    assert on yet):

    * ``"call_count"`` -- structural, always safe: a boundary was invoked
      exactly ``value`` times (derivable from the scenario's own sequence
      length).
    * ``"field_equals"`` -- a field's value is knowable by constant-folding
      a chain of MOVE/arithmetic from mock-supplied inputs.
    * ``"stub"`` -- everything else: a placeholder naming the paragraph that
      computes the value, never a live assertion.
    """

    kind: str
    ref: str
    value: str | int | None = None
    note: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "ref": self.ref,
            "value": self.value,
            "note": self.note,
        }


@dataclass
class BoundaryFixture:
    """The mock in-data (or expectation-only stub) for one boundary site."""

    ref: BoundaryRef
    direction: str
    layout: list[FieldSpec] = field(default_factory=list)
    #: One dict per invocation (READ #1, #2, ...), each a column-name ->
    #: generated-value mapping aligned to `layout` -- the same string-cell
    #: convention `GeneratedDataset.rows` uses.
    sequence: list[dict[str, str]] = field(default_factory=list)
    #: What happens after `sequence` is exhausted: AT END / SQLCODE 100 /
    #: a non-zero FILE STATUS. None when the boundary has no such handler.
    terminal: dict[str, str] | None = None
    #: e.g. {"FILE-STATUS": "00"} or {"SQLCODE": "0"} -- present on every
    #: fixture that carries a status concept, not just STATUS_ONLY ones.
    status: dict[str, str] = field(default_factory=dict)
    #: Why these values: "picture-random" (Phase 3's only provenance so far;
    #: Phase 4 adds "constraint:<field>=<value>", "88-domain", ...).
    provenance: str = "picture-random"
    #: Fail-loud: names/reasons this fixture could not fully resolve.
    unresolved: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "category": self.ref.category,
            "key": self.ref.key,
            "paragraph": self.ref.paragraph,
            "line": self.ref.line,
            "direction": self.direction,
            "layout": [f.to_dict() for f in self.layout],
            "sequence": [dict(row) for row in self.sequence],
            "terminal": dict(self.terminal) if self.terminal else None,
            "status": dict(self.status),
            "provenance": self.provenance,
            "unresolved": list(self.unresolved),
        }


@dataclass
class CoverageSummary:
    """How much of the program this bundle accounts for.

    Phase 3 only ever emits one "happy path" scenario, so there is no
    per-branch arm accounting yet -- this is a coarse boundary-level count.
    Phase 5's `ScenarioPlanner` extends this with arm-level targeted/merged/
    missed accounting once branch-directed scenarios exist; the keys added
    there are additive, not a breaking change to this shape.
    """

    total_boundaries: int = 0
    resolved_boundaries: int = 0
    unresolved_boundaries: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_boundaries": self.total_boundaries,
            "resolved_boundaries": self.resolved_boundaries,
            "unresolved_boundaries": self.unresolved_boundaries,
        }


@dataclass
class Scenario:
    """One named path through the program, with its mocks and assertions."""

    name: str
    intent: str
    entry: str | None = None
    fixtures: list[BoundaryFixture] = field(default_factory=list)
    expectations: list[Expectation] = field(default_factory=list)
    #: Branches/boundaries this scenario could not target, with reasons.
    #: Phase 3's single "happy path" scenario always leaves this empty --
    #: it does not attempt branch coverage; Phase 5 populates it.
    unconstrained: list[str] = field(default_factory=list)
    #: The self-verification verdict: does this scenario's OWN generated data
    #: actually satisfy the branch it is named for? `None` for the Phase 3
    #: happy path, which targets no branch and so has nothing to verify.
    #: `generators.verification.ScenarioVerification.to_dict()` when set.
    #:
    #: Typed as a plain dict so `bundle.py` keeps its "serializable shapes
    #: only, no analysis imports" posture -- the verifier depends on this
    #: module, not the other way round.
    verification: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "name": self.name,
            "intent": self.intent,
            "entry": self.entry,
            "fixtures": [f.to_dict() for f in self.fixtures],
            "expectations": [e.to_dict() for e in self.expectations],
            "unconstrained": list(self.unconstrained),
        }
        if self.verification is not None:
            result["verification"] = self.verification
        return result


@dataclass
class FixtureBundle:
    """The complete gen-fixtures output for one program."""

    program_name: str | None
    seed: int
    scenarios: list[Scenario] = field(default_factory=list)
    #: Record name -> its resolved field layout, emitted once per record
    #: (scenarios reference layouts by name rather than repeating them).
    layouts: dict[str, list[FieldSpec]] = field(default_factory=dict)
    coverage: CoverageSummary = field(default_factory=CoverageSummary)
    #: Program-level gaps (not tied to one scenario/boundary) -- an
    #: unresolved COPY, a dynamic CALL with no traceable target, etc.
    unresolved: list[str] = field(default_factory=list)
    bundle_version: int = BUNDLE_VERSION
    #: Phase 5's ScenarioPlanner arm-coverage accounting
    #: (`ScenarioCoverage.to_dict()`), present only for a `branches`/`all`
    #: -mode bundle; `None` for a "happy"-mode bundle, which never attempts
    #: branch targeting. Additive (2026-08-04, Phase 6) -- `bundle_version`
    #: stays 1, since existing consumers reading known keys are unaffected
    #: by one more key appearing.
    scenario_coverage: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "bundle_version": self.bundle_version,
            "program_name": self.program_name,
            "seed": self.seed,
            "scenarios": [s.to_dict() for s in self.scenarios],
            "layouts": {
                name: [f.to_dict() for f in fields]
                for name, fields in self.layouts.items()
            },
            "coverage": self.coverage.to_dict(),
            "unresolved": list(self.unresolved),
            "scenario_coverage": self.scenario_coverage,
        }

    def to_json(self, *, indent: int | None = 2) -> str:
        import json

        return json.dumps(self.to_dict(), indent=indent)

    def write_csv_dir(self, path: str | os.PathLike[str]) -> None:
        """Emit ``<path>/<scenario-slug>/<KEY>.csv``, one CSV per file-shaped
        boundary fixture per scenario, plus a ``MANIFEST.json`` at the root
        (the bundle minus row data) so a consumer can discover scenarios
        without listing directories."""
        import json as _json

        root = str(path)
        os.makedirs(root, exist_ok=True)
        for scenario in self.scenarios:
            slug = _slugify(scenario.name)
            scenario_dir = os.path.join(root, slug)
            os.makedirs(scenario_dir, exist_ok=True)
            for fixture in scenario.fixtures:
                if not fixture.layout or not fixture.sequence:
                    continue
                header = [f.column for f in fixture.layout]
                rows = [
                    [row.get(col, "") for col in header] for row in fixture.sequence
                ]
                safe_key = _sanitize_key(fixture.ref.key)
                csv_path = os.path.join(scenario_dir, f"{safe_key}.csv")
                if os.path.dirname(os.path.abspath(csv_path)) != os.path.abspath(
                    scenario_dir
                ):
                    raise ValueError(
                        f"boundary key {fixture.ref.key!r} would escape the "
                        "output directory"
                    )
                with open(csv_path, "w", encoding="utf-8", newline="") as handle:
                    writer = csv.writer(handle, lineterminator="\n")
                    writer.writerow(header)
                    writer.writerows(rows)

        manifest = self.to_dict()
        for scenario, scenario_dict in zip(
            self.scenarios, manifest["scenarios"], strict=True
        ):
            slug = _slugify(scenario.name)
            for fixture, fixture_dict in zip(
                scenario.fixtures, scenario_dict["fixtures"], strict=True
            ):
                wrote_csv = bool(fixture.layout and fixture.sequence)
                # Keep `sequence`'s type identical to the normal bundle schema
                # (always a list) rather than overwriting it with a hint
                # string -- a consumer that runs MANIFEST.json through the
                # same deserializer as a real bundle (a reasonable thing to
                # try, since the top-level shape otherwise matches) would
                # silently iterate a string character-by-character instead
                # of getting a type error, rather than crash cleanly. The
                # path hint lives in its own key instead, `None` when this
                # fixture had no CSV written for it (mirrors the skip
                # condition above exactly).
                fixture_dict["sequence"] = []
                fixture_dict["csv_path"] = (
                    f"{slug}/{_sanitize_key(fixture.ref.key)}.csv"
                    if wrote_csv
                    else None
                )
        with open(os.path.join(root, "MANIFEST.json"), "w", encoding="utf-8") as handle:
            _json.dump(manifest, handle, indent=2)
            handle.write("\n")


def _slugify(name: str) -> str:
    """Deterministic, filesystem-safe scenario name -- lowercase, spaces and
    anything not alphanumeric/hyphen collapsed to a single hyphen."""
    out = io.StringIO()
    previous_was_sep = False
    for ch in name.lower():
        if ch.isalnum():
            out.write(ch)
            previous_was_sep = False
        elif not previous_was_sep:
            out.write("-")
            previous_was_sep = True
    slug = out.getvalue().strip("-")
    return slug or "scenario"


_UNSAFE_KEY_CHARS = re.compile(r"[\\/\x00]+")


def _sanitize_key(key: str) -> str:
    """Make a boundary key safe as a single filesystem path component.

    Most boundary keys are COBOL identifiers and already filesystem-safe,
    but a static CALL boundary's key is the literal's raw source text with
    no character restrictions -- e.g. ``CALL "/etc/passwd"`` or
    ``CALL "../../../etc/passwd"`` round-trips straight through to here.
    Collapsing every path separator (and stray NUL) into a single ``_``
    guarantees the key can never introduce an extra path segment, so
    ``os.path.join(scenario_dir, f"{key}.csv")`` can never resolve outside
    ``scenario_dir`` regardless of what the source literal contains.
    """
    sanitized = _UNSAFE_KEY_CHARS.sub("_", key).strip()
    return sanitized or "boundary"


__all__ = [
    "BUNDLE_VERSION",
    "Expectation",
    "BoundaryFixture",
    "CoverageSummary",
    "Scenario",
    "FixtureBundle",
]
