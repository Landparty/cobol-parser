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

from ...layout.fields import FieldSpec

if TYPE_CHECKING:
    # Type-only: `BoundaryRef` appears only in annotations, and keeping the
    # data package free of runtime analysis imports keeps the verifier light.
    from ...analysis.boundary_inventory import BoundaryRef

#: Bumped only on a breaking change to the JSON shape. Phase 8 (mockymock
#: integration) checks this before consuming a bundle; fail closed on an
#: unknown version rather than guess at a schema that changed underneath it.
#:
#: 2 (2026-11-11): each distinct fixture is written once, in the top-level
#: ``fixtures`` table, and a scenario's ``fixtures`` lists the ids of the
#: ones it uses. In version 1 every scenario repeated every fixture in
#: full, so a branches/all bundle repeated the same unchanged READ
#: sequences once per scenario. :func:`expand_shared_fixtures` turns a
#: version 2 dict back into the version 1 shape.
BUNDLE_VERSION = 2

#: The versions :meth:`FixtureBundle.to_dict` can write.
SUPPORTED_BUNDLE_VERSIONS: tuple[int, ...] = (1, 2)


@dataclass
class Expectation:
    """One assertable claim about a scenario's outcome.

    Three confidence tiers (Phase 7 fills tiers 1-2; Phase 3 emits none --
    a "happy path" scenario has no scenario-specific branch outcome to
    assert on yet):

    * ``"call_count"`` -- structural: a boundary was invoked exactly
      ``value`` times, merged over every statement invoking it. Emitted only
      when control flow makes the count exact (the invoking statements sit
      on the unconditional path, or a read-until-end-of-file loop reads the
      scenario's whole sequence); absent otherwise.
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
    #: The values a caller passes through the program's own PROCEDURE
    #: DIVISION USING parameters -- one row over every elementary field of
    #: every USING item, with the scenario's witnesses pinned in it. Its ref
    #: has category ``"ENTRY"`` and the PROGRAM-ID as key. Only set when the
    #: generator was asked for it (``entry_parameters=True``), so a bundle
    #: that never asked keeps its shape: the key is absent, not null.
    entry_parameters: BoundaryFixture | None = None

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
        if self.entry_parameters is not None:
            result["entry_parameters"] = self.entry_parameters.to_dict()
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

    def to_dict(self, *, bundle_version: int | None = None) -> dict[str, Any]:
        """The bundle as JSON-ready data, in *bundle_version*'s shape
        (default: :attr:`bundle_version`, which defaults to
        :data:`BUNDLE_VERSION`). Version 1 repeats every fixture inside every
        scenario; version 2 writes each distinct fixture once in
        ``fixtures`` and has each scenario list fixture ids."""
        version = self.bundle_version if bundle_version is None else bundle_version
        if version not in SUPPORTED_BUNDLE_VERSIONS:
            raise ValueError(
                f"unsupported bundle_version {version} (supported: "
                f"{', '.join(str(v) for v in SUPPORTED_BUNDLE_VERSIONS)})"
            )
        scenarios = [s.to_dict() for s in self.scenarios]
        result: dict[str, Any] = {
            "bundle_version": version,
            "program_name": self.program_name,
            "seed": self.seed,
            "scenarios": scenarios,
        }
        if version >= 2:
            result["fixtures"] = _share_fixtures(scenarios)
        result.update(
            {
                "layouts": {
                    name: [f.to_dict() for f in fields]
                    for name, fields in self.layouts.items()
                },
                "coverage": self.coverage.to_dict(),
                "unresolved": list(self.unresolved),
                "scenario_coverage": self.scenario_coverage,
            }
        )
        return result

    def to_json(
        self, *, indent: int | None = 2, bundle_version: int | None = None
    ) -> str:
        import json

        return json.dumps(self.to_dict(bundle_version=bundle_version), indent=indent)

    def write_csv_dir(self, path: str | os.PathLike[str]) -> None:
        """Emit ``<path>/<scenario-slug>/<KEY>.csv``, one CSV per file-shaped
        boundary fixture per scenario, plus a ``MANIFEST.json`` at the root
        (the bundle minus row data) so a consumer can discover scenarios
        without listing directories."""
        import json as _json

        root = str(path)
        os.makedirs(root, exist_ok=True)
        # Computed once and shared with the manifest pass below, so a
        # `csv_path` always names the file this pass actually wrote.
        slugs = _unique_names([_slugify(s.name) for s in self.scenarios])
        csv_names = [_csv_names(scenario.fixtures) for scenario in self.scenarios]
        for scenario, slug, names in zip(self.scenarios, slugs, csv_names, strict=True):
            scenario_dir = os.path.join(root, slug)
            os.makedirs(scenario_dir, exist_ok=True)
            for fixture, safe_key in zip(scenario.fixtures, names, strict=True):
                if not _writes_csv(fixture):
                    continue
                header = [f.column for f in fixture.layout]
                rows = [
                    [row.get(col, "") for col in header] for row in fixture.sequence
                ]
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

        # The manifest keeps the version 1 shape: each scenario's fixtures
        # inline, each with the path of the CSV written for it there.
        manifest = self.to_dict(bundle_version=1)
        for scenario, scenario_dict, slug, names in zip(
            self.scenarios, manifest["scenarios"], slugs, csv_names, strict=True
        ):
            for fixture, fixture_dict, safe_key in zip(
                scenario.fixtures, scenario_dict["fixtures"], names, strict=True
            ):
                wrote_csv = _writes_csv(fixture)
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
                    f"{slug}/{safe_key}.csv" if wrote_csv else None
                )
        with open(os.path.join(root, "MANIFEST.json"), "w", encoding="utf-8") as handle:
            _json.dump(manifest, handle, indent=2)
            handle.write("\n")


def _share_fixtures(scenarios: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Move each scenario dict's fixtures into one table, in place.

    Each distinct fixture (same content, compared as canonical JSON) is
    kept once under an id, ``CATEGORY:KEY``, or ``CATEGORY:KEY#2``,
    ``#3``, ... for a second, third variant of the same boundary; each
    scenario's ``fixtures`` becomes the list of its fixtures' ids, in the
    same order. Ids are given in first-use order, so the same bundle always
    gets the same ids."""
    import json

    table: dict[str, dict[str, Any]] = {}
    by_content: dict[str, str] = {}
    variants: dict[str, int] = {}
    for scenario in scenarios:
        ids: list[str] = []
        for fixture in scenario["fixtures"]:
            content = json.dumps(fixture, sort_keys=True, default=str)
            fixture_id = by_content.get(content)
            if fixture_id is None:
                base = f"{fixture['category']}:{fixture['key']}"
                count = variants[base] = variants.get(base, 0) + 1
                fixture_id = base if count == 1 else f"{base}#{count}"
                by_content[content] = fixture_id
                table[fixture_id] = fixture
            ids.append(fixture_id)
        scenario["fixtures"] = ids
    return table


def expand_shared_fixtures(bundle: dict[str, Any]) -> dict[str, Any]:
    """A copy of a bundle dict in the version 1 shape: every scenario's
    fixtures inline. A version 1 dict comes back as an equal copy. For a
    consumer written against version 1, and for reading a scenario's
    fixtures without looking each id up."""
    import copy

    result = copy.deepcopy(bundle)
    table = result.pop("fixtures", None)
    if result.get("bundle_version") == 1 or table is None:
        return result
    for scenario in result.get("scenarios", []):
        scenario["fixtures"] = [
            copy.deepcopy(table[fixture_id]) for fixture_id in scenario["fixtures"]
        ]
    result["bundle_version"] = 1
    return result


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


def _unique_names(names: list[str]) -> list[str]:
    """*names* with every repeat suffixed ``-2``, ``-3``, ... in order.

    Scenario names are not unique -- two IFs in one paragraph both yield a
    ``"<PARA>: ELSE"`` scenario -- and neither are slugs of distinct names
    (``"A: B"`` / ``"A-B"``). (Boundary keys get the same treatment in
    :func:`_csv_names`.)
    Written as-is, the later scenario's CSV silently overwrote the earlier
    one's and both manifest entries pointed at the survivor. Compared
    case-insensitively, so a case-insensitive filesystem cannot merge two
    names either. The first occurrence keeps its plain name, so a bundle
    with no collision is written exactly as before.
    """
    taken: set[str] = set()
    out: list[str] = []
    for name in names:
        candidate, n = name, 1
        while candidate.lower() in taken:
            n += 1
            candidate = f"{name}-{n}"
        taken.add(candidate.lower())
        out.append(candidate)
    return out


def _writes_csv(fixture: BoundaryFixture) -> bool:
    """Whether :meth:`FixtureBundle.write_csv_dir` writes a CSV for *fixture*.

    Any fixture with a layout and at least one row; and also an IN or
    BIDIRECTIONAL one with a layout and **no** rows, as a header-only CSV
    (#568): that is the "empty input" scenario's zero-record file, and
    writing nothing left it indistinguishable in the manifest from a
    STATUS_ONLY boundary (``csv_path: null``) and its scenario directory
    empty. STATUS_ONLY and OUT fixtures have nothing to bind and still get
    none.
    """
    if not fixture.layout:
        return False
    return bool(fixture.sequence) or fixture.direction in ("IN", "BIDIRECTIONAL")


def _csv_names(fixtures: list[BoundaryFixture]) -> list[str]:
    """One CSV base name per fixture: ``<KEY>`` unless another fixture that
    writes *different* rows already took it.

    Only fixtures that get a CSV at all (see :func:`_writes_csv`)
    compete for a name, so the OPEN/CLOSE of a file never displaces its
    READ. Two fixtures with the same key and byte-identical content (the
    same READ boundary reached from two places) keep sharing one file, as
    they always have; only a key whose fixtures disagree gets a ``-2``.
    """
    names = [_sanitize_key(f.ref.key) for f in fixtures]
    taken: dict[str, tuple[Any, ...]] = {}
    for i, fixture in enumerate(fixtures):
        if not _writes_csv(fixture):
            continue
        header = tuple(f.column for f in fixture.layout)
        content = (
            header,
            tuple(tuple(row.get(c, "") for c in header) for row in fixture.sequence),
        )
        base, n = names[i], 1
        candidate = base
        while candidate.lower() in taken and taken[candidate.lower()] != content:
            n += 1
            candidate = f"{base}-{n}"
        taken[candidate.lower()] = content
        names[i] = candidate
    return names


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
    "SUPPORTED_BUNDLE_VERSIONS",
    "expand_shared_fixtures",
    "Expectation",
    "BoundaryFixture",
    "CoverageSummary",
    "Scenario",
    "FixtureBundle",
]
