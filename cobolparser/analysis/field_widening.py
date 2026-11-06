"""
Field-widening impact: what breaks when one field's PICTURE changes.

"Widen ``CUST-ID`` from ``PIC 9(6)`` to ``PIC 9(9)``" is two questions, and
:class:`FieldWideningAnalyzer` answers both from the cross-program
:class:`~.lineage_graph.LineageGraph`:

- **Where is the wider value cut?** Every field the value flows into, in
  any program (through MOVEs, arithmetic, files and datasets, CALL
  arguments, DB2 columns), is checked against the new size: a receiver that
  holds fewer integer digits, decimal places or characters than the new
  PICTURE truncates it (``truncation``). The check follows the path, so a
  narrow field halfway along is reported once, where the cut happens, and
  not again for every field after it. A receiver that already could not
  hold the *old* value is reported as pre-existing (``info``), so the
  findings say what the change itself breaks. A narrowing runs the other
  way: every field feeding the start that holds more than the new PICTURE.
- **What moves?** When the field's byte length changes, its record grows or
  shrinks, and every layout that meets that record byte for byte has to
  change with it (``layout``): a group MOVE / READ INTO / WRITE FROM
  against another record, a REDEFINES over it, the file it is written to
  (and every program bound to the same dataset), the CALL argument it is
  passed in (and the callee's LINKAGE record), or the LINKAGE parameter it
  is (and every caller's argument). Every other program that declares a
  field of the same qualified name and PICTURE -- the same copybook, or a
  copy of it -- is listed too (``same-layout``), and a DB2 column the value
  reaches is a ``column`` finding: its type is not in the source, so it is
  named for review rather than judged.

Nothing is guessed. A receiver with no PICTURE in its report (a report
stored before ``picture`` was recorded, a floating-point or pointer item)
is listed in :attr:`WideningReport.unchecked`; the graph's own caveats are
passed through.

Example:
    ```python
    graph = LineageGraph(reports, bindings)
    report = FieldWideningAnalyzer(graph).analyze("CUST-ID", "9(9)", program="CUSTUPD")
    for finding in report.findings:
        print(finding.severity, finding.program, finding.field, finding.message)
    ```
"""

from __future__ import annotations

import dataclasses
import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from .._storage import storage_size
from ..models.ast_base import SourceLocation
from ..models.data_items import PictureClause
from .field_lineage import ITEM, PORT_CALL, PORT_FILE, PORT_LINKAGE
from .lineage_graph import (
    _DUP_SUFFIX_RE,
    Hop,
    ImpactHit,
    LineageGraph,
    normalize_dataset,
)

WIDENING_VERSION = "1"

SEVERITIES = ("error", "warning", "info")

_PIC_PREFIX_RE = re.compile(r"^\s*(PIC(TURE)?\s+(IS\s+)?)", re.IGNORECASE)
_SUBSCRIPT_RE = re.compile(r"\(.*\)$")
_FLOAT_OR_POINTER = frozenset(
    {
        "COMP-1",
        "COMP-2",
        "COMPUTATIONAL-1",
        "COMPUTATIONAL-2",
        "FLOAT-SHORT",
        "FLOAT-LONG",
        "FLOAT-EXTENDED",
        "POINTER",
        "POINTER-32",
        "POINTER-64",
        "PROCEDURE-POINTER",
        "FUNCTION-POINTER",
        "INDEX",
        "OBJECT REFERENCE",
    }
)


def normalize_picture(text: str) -> str:
    """``"PIC S9(7)V99."`` -> ``"S9(7)V99"``."""
    return _PIC_PREFIX_RE.sub("", text.strip()).rstrip(".").strip().upper()


# --------------------------------------------------------------------------
# Capacity: what a value of an item can hold
# --------------------------------------------------------------------------


#: The loss reported when a noninteger numeric value reaches an elementary
#: alphanumeric item: the MOVE no longer compiles.
INVALID_MOVE = "decimal places (a noninteger MOVE to an alphanumeric item is invalid)"


@dataclass(frozen=True)
class Capacity:
    """What a field can hold: digits on each side of the decimal point for a
    numeric (or numeric-edited) item, characters for anything else."""

    numeric: bool
    integer_digits: int = 0
    decimal_digits: int = 0
    chars: int = 0
    signed: bool = False
    #: A group item: a MOVE to it copies the sender's bytes, sign included.
    group: bool = False

    def describe(self) -> str:
        if self.numeric:
            sign = "signed " if self.signed else ""
            if self.decimal_digits:
                return (
                    f"{sign}{self.integer_digits} integer + "
                    f"{self.decimal_digits} decimal digits"
                )
            return f"{sign}{self.integer_digits} digits"
        return f"{self.chars} characters"

    @property
    def digits(self) -> int:
        return self.integer_digits + self.decimal_digits

    def losses(self, receiver: Capacity) -> list[str]:
        """What part of a value this capacity holds *receiver* cannot keep
        (MOVE rules: numeric aligns on the decimal point, alphanumeric on
        the left)."""
        lost: list[str] = []
        if self.numeric and receiver.numeric:
            if receiver.integer_digits < self.integer_digits:
                lost.append("high-order digits")
            if receiver.decimal_digits < self.decimal_digits:
                lost.append("decimal places")
            if self.signed and not receiver.signed:
                lost.append("sign")
        elif self.numeric:
            # A numeric value moved to an alphanumeric item is its digits.
            if receiver.chars < self.digits:
                lost.append("characters")
            if not receiver.group:
                # An elementary receiver gets the digits only: the sign is
                # lost (#765), and a noninteger sender makes the MOVE itself
                # invalid (IBM, GnuCOBOL: "invalid MOVE statement", #822).
                # A group receiver copies the bytes as they are.
                if self.signed:
                    lost.append("sign")
                if self.decimal_digits:
                    lost.append(INVALID_MOVE)
        elif receiver.numeric:
            if receiver.integer_digits < self.chars:
                lost.append("high-order digits")
        elif receiver.chars < self.chars:
            lost.append("characters")
        return lost

    def through(self, receiver: Capacity) -> Capacity:
        """What of a value this capacity holds is left once it has passed
        through *receiver*."""
        if self.numeric and receiver.numeric:
            return Capacity(
                True,
                min(self.integer_digits, receiver.integer_digits),
                min(self.decimal_digits, receiver.decimal_digits),
                signed=self.signed and receiver.signed,
            )
        if self.numeric:
            return Capacity(False, chars=min(self.digits, receiver.chars))
        if receiver.numeric:
            return Capacity(True, min(self.chars, receiver.integer_digits))
        return Capacity(False, chars=min(self.chars, receiver.chars))


def capacity_of(
    picture: str | None, usage: str | None, length: int | None, is_group: bool
) -> Capacity | None:
    """The capacity of an item from its PICTURE / USAGE (a group holds its
    bytes as characters); None when it cannot be known."""
    if is_group:
        return Capacity(False, chars=int(length or 0), group=True) if length else None
    if str(usage or "").upper() in _FLOAT_OR_POINTER or not picture:
        return None
    clause = PictureClause(normalize_picture(picture), SourceLocation(0, 0))
    if not clause.is_valid and clause.size is None:
        return None
    if clause.is_alphanumeric_edited or clause.integer_digits is None:
        chars = clause.size or 0
        if clause.is_national:
            chars //= 2
        if clause.utf8_characters is not None:
            chars = clause.utf8_characters
        return Capacity(False, chars=chars) if chars else None
    return Capacity(
        True,
        max(0, clause.integer_digits),
        max(0, clause.decimal_digits or 0),
        signed=clause.is_signed
        or (clause.is_numeric_edited and _edited_sign(clause.pattern or "")),
    )


def _edited_sign(pattern: str) -> bool:
    """True when a numeric-edited PICTURE shows a sign (``+``, ``-``, ``CR``,
    ``DB``); ``ZZ,ZZ9`` drops it (#757)."""
    upper = pattern.upper()
    return "+" in upper or "-" in upper or "CR" in upper or "DB" in upper


def _byte_size(picture: str, usage: str | None) -> int | None:
    clause = PictureClause(normalize_picture(picture), SourceLocation(0, 0))
    if clause.size is None:
        return None
    return storage_size(
        usage,
        picture_size=clause.size,
        total_digits=clause.total_digits,
        is_signed=clause.is_signed,
        national_picture=clause.is_national,
    )


def _aliased(hit: ImpactHit) -> bool:
    """True when the path passes a REDEFINES: the field shares storage rather
    than receiving a value, which is a layout question (see
    ``FieldWideningAnalyzer._layout``). An ``occurrence`` hop (``T.A`` ->
    ``T.A(2)``) is no alias: it is the same field at one subscript, and what
    that reference feeds receives the value (#759)."""
    return any(hop.kind == "redefines" for hop in hit.path)


def _under(qname: str, group: str) -> bool:
    """True when item *qname* is *group* or lies under it."""
    return qname == group or qname.startswith(group + ".")


def _common_group(qnames: list[str]) -> str:
    """The longest qualified name every one of *qnames* is or lies under."""
    parts = [_base(q).split(".") for q in qnames]
    common: list[str] = []
    for level in zip(*parts, strict=False):
        if len(set(level)) != 1:
            break
        common.append(level[0])
    return ".".join(common)


def _base(node: str) -> str:
    """An item key without its literal subscripts: ``T.A(2)`` -> ``T.A``."""
    return _SUBSCRIPT_RE.sub("", node)


# --------------------------------------------------------------------------
# Report shapes
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class WideningFinding:
    """One place the change breaks, or has to be repeated."""

    kind: str
    severity: str
    program: str | None
    field: str
    message: str
    line: int = 0
    statement: str = ""
    #: The receiver could not hold the *old* value either: the change does
    #: not make it worse in kind, only in size.
    pre_existing: bool = False
    #: How sure the value path is (``exact`` / ``overlap`` / ``candidate``
    #: / ``opaque``, the lineage graph's own grading).
    confidence: str = "exact"
    path: tuple[Hop, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "kind": self.kind,
            "severity": self.severity,
            "program": self.program,
            "field": self.field,
            "message": self.message,
            "line": self.line,
            "statement": self.statement,
            "pre_existing": self.pre_existing,
            "confidence": self.confidence,
        }
        if self.path:
            data["path"] = [hop.to_dict() for hop in self.path]
        return data


@dataclass
class WideningReport:
    field: str
    new_picture: str
    new_usage: str | None
    #: One entry per field the name matched: program, qualified name, old
    #: and new PICTURE / USAGE, bytes before and after.
    starts: list[dict[str, Any]] = dataclasses.field(default_factory=list)
    findings: list[WideningFinding] = dataclasses.field(default_factory=list)
    #: Fields the value reaches whose capacity could not be judged.
    unchecked: list[str] = dataclasses.field(default_factory=list)
    caveats: list[str] = dataclasses.field(default_factory=list)
    start_found: bool = True

    def worst_severity(self) -> str | None:
        for severity in SEVERITIES:
            if any(f.severity == severity for f in self.findings):
                return severity
        return None

    @property
    def programs(self) -> list[str]:
        return sorted({f.program for f in self.findings if f.program})

    def to_dict(self) -> dict[str, Any]:
        counts = {s: sum(f.severity == s for f in self.findings) for s in SEVERITIES}
        return {
            "widening_version": WIDENING_VERSION,
            "field": self.field,
            "new_picture": self.new_picture,
            "new_usage": self.new_usage,
            "start_found": self.start_found,
            "starts": self.starts,
            "programs": self.programs,
            "summary": {"findings": len(self.findings), **counts},
            "findings": [f.to_dict() for f in self.findings],
            "unchecked": list(self.unchecked),
            "caveats": list(self.caveats),
        }

    def to_text(self) -> str:
        lines = [f"{self.field} -> PIC {self.new_picture}"]
        for start in self.starts:
            lines.append(
                f"  {start['program']}:{start['qualified_name']}  "
                f"PIC {start['old_picture']} ({start['old_bytes']} bytes) -> "
                f"PIC {start['new_picture']} ({start['new_bytes']} bytes)"
            )
        if not self.start_found:
            lines.append("  no such field in any report")
        if not self.findings:
            lines.append("No findings.")
        for finding in self.findings:
            where = f"{finding.program}:" if finding.program else ""
            at = f" (line {finding.line})" if finding.line else ""
            tag = " [pre-existing]" if finding.pre_existing else ""
            lines.append(
                f"{finding.severity.upper():7} {finding.kind:12} "
                f"{where}{finding.field}{at}{tag}"
            )
            lines.append(f"        {finding.message}")
        if self.unchecked:
            lines.append("Unchecked:")
            lines += [f"  - {u}" for u in self.unchecked]
        if self.caveats:
            lines.append("Caveats:")
            lines += [f"  - {c}" for c in self.caveats]
        return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------
# Analyzer
# --------------------------------------------------------------------------


@dataclass
class _Start:
    program: str
    qname: str
    item: dict[str, Any]
    old: Capacity
    new: Capacity
    old_bytes: int
    new_bytes: int

    @property
    def delta(self) -> int:
        return self.new_bytes - self.old_bytes


class FieldWideningAnalyzer:
    """Checks one PICTURE change against a :class:`LineageGraph`."""

    def __init__(self, graph: LineageGraph) -> None:
        self.graph = graph
        self._items: dict[str, dict[str, dict[str, Any]]] = {
            program: {
                str(item["qualified_name"]).upper(): item
                for item in data.get("items") or []
            }
            for program, data in graph.reports.items()
        }

    # -- entry point -------------------------------------------------------

    def analyze(
        self,
        field_name: str,
        new_picture: str,
        program: str | Sequence[str] | None = None,
        new_usage: str | None = None,
        depth: int | None = None,
    ) -> WideningReport:
        """Check changing *field_name* (in *program*, or every program
        declaring it) to ``PIC new_picture`` (and ``USAGE new_usage``, when
        given; otherwise its own usage is kept)."""
        picture = normalize_picture(new_picture)
        report = WideningReport(field_name.upper(), picture, new_usage)
        programs = [program] if isinstance(program, str) else program
        _groups, matched = self.graph._start_groups(field_name, programs)
        if not matched:
            report.start_found = False
            report.caveats.append(f"{field_name.upper()}: no such field in any report")
            return report
        seen: set[tuple[str | None, str, str]] = set()
        for prog in sorted(matched):
            for qname in sorted(set(matched[prog])):
                start = self._start(prog, qname, picture, new_usage, report)
                if start is None:
                    continue
                report.starts.append(
                    {
                        "program": prog,
                        "qualified_name": qname,
                        "old_picture": start.item.get("picture"),
                        "old_usage": start.item.get("usage"),
                        "new_picture": picture,
                        "new_usage": new_usage or start.item.get("usage"),
                        "old_capacity": start.old.describe(),
                        "new_capacity": start.new.describe(),
                        "old_bytes": start.old_bytes,
                        "new_bytes": start.new_bytes,
                    }
                )
                for finding in self._check(start, depth, report):
                    key = (finding.program, finding.field, finding.kind)
                    if key not in seen:
                        seen.add(key)
                        report.findings.append(finding)
        if len(report.starts) > 1:
            report.caveats.append(
                f"{field_name.upper()} matches {len(report.starts)} fields; each is "
                "checked as if it were changed the same way (qualify with OF, or "
                "name --program, to check one)"
            )
        report.findings.sort(
            key=lambda f: (
                SEVERITIES.index(f.severity),
                f.kind,
                f.program or "",
                f.field,
                f.line,
            )
        )
        report.unchecked = sorted(set(report.unchecked))
        return report

    def _start(
        self,
        program: str,
        qname: str,
        picture: str,
        new_usage: str | None,
        report: WideningReport,
    ) -> _Start | None:
        item = self._items.get(program, {}).get(qname)
        if item is None:
            return None
        if item.get("is_group"):
            report.caveats.append(
                f"{program}:{qname} is a group item: only an elementary item's "
                "PICTURE can change; name one of its fields"
            )
            return None
        old_picture = item.get("picture")
        usage = new_usage or item.get("usage")
        old = capacity_of(old_picture, item.get("usage"), item.get("length"), False)
        new = capacity_of(picture, usage, None, False)
        new_bytes = _byte_size(picture, usage)
        if new is None or new_bytes is None:
            report.caveats.append(f"PIC {picture}: not a PICTURE this check can size")
            return None
        if old is None or not old_picture:
            report.caveats.append(
                f"{program}:{qname} has no PICTURE in its lineage report (a report "
                "stored before PICTUREs were recorded, or a floating-point or "
                "pointer item): not checked"
            )
            return None
        old_bytes = _byte_size(str(old_picture), item.get("usage"))
        return _Start(
            program,
            qname,
            item,
            old,
            new,
            old_bytes if old_bytes is not None else int(item.get("length") or 0),
            new_bytes,
        )

    # -- checks ------------------------------------------------------------

    def _check(
        self, start: _Start, depth: int | None, report: WideningReport
    ) -> list[WideningFinding]:
        findings: list[WideningFinding] = []
        forward = self.graph.impact(start.qname, start.program, "forward", depth)
        for caveat in forward.caveats:
            if caveat not in report.caveats:
                report.caveats.append(caveat)
        findings += self._truncations(start, forward.hits, report)
        if start.old.losses(start.new):
            # Narrower in some way: what feeds the field may now be cut.
            backward = self.graph.impact(start.qname, start.program, "backward", depth)
            findings += self._narrowings(start, backward.hits, report)
        for hit in forward.hits:
            if hit.node_kind == "table":
                findings.append(
                    WideningFinding(
                        "column",
                        "warning",
                        None,
                        hit.field,
                        f"the value is stored in DB2 column {hit.field}: check its "
                        f"column type holds {start.new.describe()} and regenerate "
                        "the DCLGEN",
                        *self._at(hit.path),
                        confidence=hit.confidence,
                        path=hit.path,
                    )
                )
        if start.delta:
            findings += self._layout(start)
        findings += self._same_layout(start)
        return findings

    @staticmethod
    def _at(path: Sequence[Hop]) -> tuple[int, str]:
        for hop in reversed(path):
            if hop.line:
                return hop.line, hop.statement
        return 0, ""

    def _capacity(self, program: str | None, node: str) -> Capacity | None | str:
        """The capacity of an item hop, ``None`` for a hop that is no item of a
        program in the graph (a port, a dataset, a table), or ``"?"`` when the
        item's capacity cannot be known."""
        if program is None:
            return None
        items = self._items.get(program)
        if items is None:
            return None
        item = items.get(node) or items.get(_SUBSCRIPT_RE.sub("", node))
        if item is None:
            return None
        cap = capacity_of(
            item.get("picture"),
            item.get("usage"),
            item.get("length"),
            bool(item.get("is_group")),
        )
        return "?" if cap is None else cap

    def _truncations(
        self, start: _Start, hits: list[ImpactHit], report: WideningReport
    ) -> list[WideningFinding]:
        found: list[WideningFinding] = []
        for hit in hits:
            if hit.node_kind != "item" or _aliased(hit):
                continue
            if (hit.program, _base(hit.field)) == (start.program, start.qname):
                continue  # the start itself, at one subscript
            # What of the new (and old) value survives up to the hit.
            carried_new, carried_old = start.new, start.old
            previous: tuple[str | None, str] | None = None
            last: Capacity | None | str = None
            for hop in hit.path:
                here = (hop.program, _base(hop.node))
                if here == previous or here == (start.program, start.qname):
                    continue
                previous = here
                cap = self._capacity(hop.program, hop.node)
                last = cap
                if hop is hit.path[-1] or here == (hit.program, _base(hit.field)):
                    break
                if isinstance(cap, Capacity):
                    carried_new = carried_new.through(cap)
                    carried_old = carried_old.through(cap)
            if last == "?":
                report.unchecked.append(
                    f"{hit.program}:{hit.field}: no PICTURE in its report"
                )
                continue
            if not isinstance(last, Capacity):
                continue
            if hit.path and hit.path[-1].confidence == "overlap" and not last.numeric:
                # Bytes laid over it by a MOVE to an enclosing group: a group
                # move, sign and decimal point included (#822).
                last = dataclasses.replace(last, group=True)
            lost = carried_new.losses(last)
            if not lost:
                continue
            # Only what the old value kept is the change's doing.
            new_losses = [x for x in lost if x not in carried_old.losses(last)]
            pre_existing = not new_losses
            derived = hit.derived
            if pre_existing and derived:
                # A computed value the old PICTURE already overflowed is the
                # arithmetic's business (a rate, a running total), not the
                # change's.
                continue
            line, statement = self._at(hit.path)
            if pre_existing:
                severity = "info"
            elif (
                new_losses == ["decimal places"] or derived or hit.confidence != "exact"
            ):
                severity = "warning"
            else:
                severity = "error"
            verb = "a value computed from it" if derived else "the value"
            message = (
                f"{verb} reaches a field holding {last.describe()}; the new "
                f"PICTURE carries {carried_new.describe()}: loses " + ", ".join(lost)
            )
            if pre_existing:
                message += " (it could not hold the old value either)"
            found.append(
                WideningFinding(
                    "truncation",
                    severity,
                    hit.program,
                    hit.field,
                    message,
                    line,
                    statement,
                    pre_existing,
                    hit.confidence,
                    hit.path,
                )
            )
        return found

    def _narrowings(
        self, start: _Start, hits: list[ImpactHit], report: WideningReport
    ) -> list[WideningFinding]:
        found: list[WideningFinding] = []
        flagged: set[tuple[str | None, str]] = set()
        # Nearest feeders first: one cut is reported where it happens.
        for hit in sorted(hits, key=lambda h: len(h.path)):
            if hit.node_kind != "item" or _aliased(hit):
                continue
            if (hit.program, _base(hit.field)) == (start.program, start.qname):
                continue
            cap = self._capacity(hit.program, hit.field)
            if cap == "?":
                report.unchecked.append(
                    f"{hit.program}:{hit.field}: no PICTURE in its report"
                )
                continue
            if not isinstance(cap, Capacity):
                continue
            if any((hop.program, hop.node) in flagged for hop in hit.path[:-1]):
                continue
            carried = cap
            for hop in hit.path[:-1]:
                between = self._capacity(hop.program, hop.node)
                if isinstance(between, Capacity):
                    carried = carried.through(between)
            lost = carried.losses(start.new)
            if not lost:
                continue
            flagged.add((hit.program, hit.field))
            pre_existing = not [x for x in lost if x not in carried.losses(start.old)]
            if pre_existing and hit.derived:
                continue
            line, statement = self._at(hit.path)
            found.append(
                WideningFinding(
                    "truncation",
                    "info" if pre_existing else "warning" if hit.derived else "error",
                    hit.program,
                    hit.field,
                    f"feeds {start.qname} with {carried.describe()}; the new PICTURE "
                    f"holds {start.new.describe()}: loses " + ", ".join(lost),
                    line,
                    statement,
                    pre_existing,
                    hit.confidence,
                    hit.path,
                )
            )
        return found

    # -- layout ------------------------------------------------------------

    def _layout(self, start: _Start) -> list[WideningFinding]:
        """Every layout that meets the start's record byte for byte."""
        found: list[WideningFinding] = []
        program, items = start.program, self._items[start.program]
        data = self.graph.reports[program]
        record = str(start.item.get("record") or start.qname).upper()
        record_item = items.get(record, {})
        old_len = int(record_item.get("length") or 0)
        new_len = old_len + start.delta * self._occurrences(start, items)
        grow = "grows" if start.delta > 0 else "shrinks"
        size = f"{record} {grow} from {old_len} to {new_len} bytes"
        offset = start.item.get("offset")
        end = (offset or 0) + start.old_bytes
        shifted = sorted(
            qname
            for qname, item in items.items()
            if item.get("record") == record
            and not item.get("is_group")
            and item.get("offset") is not None
            and offset is not None
            and item["offset"] >= end
        )
        if shifted:
            found.append(
                WideningFinding(
                    "layout",
                    "info",
                    program,
                    record,
                    f"{size}; {len(shifted)} field(s) after "
                    f"{start.qname} move by {start.delta:+d} bytes: "
                    + ", ".join(shifted[:8])
                    + (" ..." if len(shifted) > 8 else ""),
                )
            )
        # REDEFINES over the record (or the record over another).
        for qname, item in items.items():
            redefined = str(item.get("redefines") or "").upper()
            if not redefined:
                continue
            target = self._resolve_raw(items, redefined)
            if target is None:
                continue
            if target == record:
                other = qname  # another record over this one
            elif qname == record:
                other = target  # this record over another
            elif item.get("record") == record:
                # Inside the record: only a REDEFINES whose bytes hold the
                # changed field is out of step; one after it just shifts
                # with its target (#760).
                if _under(start.qname, qname):
                    other = target
                elif _under(start.qname, target):
                    other = qname
                else:
                    continue
            else:
                continue
            if other == record:
                continue
            found.append(
                WideningFinding(
                    "layout",
                    "warning",
                    program,
                    other,
                    f"{qname} REDEFINES {redefined}: {size}, and {other} still "
                    "describes the old layout of the same bytes",
                )
            )
        # Group moves against another record.
        for overlay in data.get("overlays") or []:
            src, tgt = str(overlay["source"]).upper(), str(overlay["target"]).upper()
            src_root = str(items.get(src, {}).get("record") or src)
            tgt_root = str(items.get(tgt, {}).get("record") or tgt)
            if record not in (src_root, tgt_root):
                continue
            other = tgt if src_root == record else src
            line = int((overlay.get("origin") or {}).get("line") or overlay["line"])
            found.append(
                WideningFinding(
                    "layout",
                    "warning",
                    program,
                    other,
                    f"{overlay['statement']} {src} -> {tgt} pairs bytes by position: "
                    f"{size}, so the fields of {other} after the change no longer "
                    "line up unless it changes too",
                    line,
                    str(overlay["statement"]),
                )
            )
        found += self._interfaces(start, record, size)
        return found

    @staticmethod
    def _occurrences(start: _Start, items: dict[str, dict[str, Any]]) -> int:
        """How many times the start's bytes repeat in its record (OCCURS on
        it or an enclosing group)."""
        count = 1
        name = start.qname
        while True:
            item = items.get(name)
            if item is None:
                break
            count *= int(item.get("occurs") or 1)
            if "." not in name:
                break
            name = name.rsplit(".", 1)[0]
        return count

    @staticmethod
    def _resolve_raw(items: dict[str, dict[str, Any]], raw: str) -> str | None:
        if raw in items:
            return raw
        for qname, item in items.items():
            if str(item.get("name") or "").upper() == raw:
                return qname
        return None

    def _record_ports(self, start: _Start, record: str) -> dict[tuple[str, str], str]:
        """(port kind, port key) -> the item passed, of every file / CALL /
        LINKAGE port a field of *record* meets in the start's program.

        A file port takes the whole record, so any field of it counts. A CALL
        or LINKAGE argument is passed by its own address and length: only one
        whose bytes hold the changed field changes for the other side. A field
        before or after it in the same record (``CALL X USING ORD-CUST-ID``
        when ``ORD-AMOUNT`` widens) keeps its own layout."""
        program = start.program
        items = self._items.get(program, {})
        met: dict[tuple[str, str], list[dict[str, Any]]] = {}
        for edge in self.graph.reports[program].get("edges") or []:
            for side, other in (("source", "target"), ("target", "source")):
                node, port = edge[side], edge[other]
                if node["kind"] != ITEM or port["kind"] not in (
                    PORT_FILE,
                    PORT_CALL,
                    PORT_LINKAGE,
                ):
                    continue
                item = items.get(str(node["name"]).upper()) or items.get(
                    _SUBSCRIPT_RE.sub("", str(node["name"]).upper())
                )
                if item is not None and item.get("record") == record:
                    met.setdefault((port["kind"], str(port["name"])), []).append(item)
        ports: dict[tuple[str, str], str] = {}
        for key, pieces in met.items():
            if key[0] != PORT_FILE and not any(
                self._holds(start, item) for item in pieces
            ):
                continue
            # The argument is the group around every piece that meets the
            # port (edges run per elementary item): REC when REC is passed.
            names = [str(i.get("qualified_name") or record).upper() for i in pieces]
            ports[key] = _common_group(names) or record
        return ports

    @staticmethod
    def _holds(start: _Start, item: dict[str, Any]) -> bool:
        """True when *item*'s bytes include the start's (old) bytes: the item
        is the start or a group around it, or (by offset) a REDEFINES over
        them. Without offsets, only the name decides."""
        qname = str(item.get("qualified_name") or "").upper()
        if qname and _under(start.qname, qname):
            return True
        offset, length = item.get("offset"), item.get("length")
        start_offset = start.item.get("offset")
        if offset is None or length is None or start_offset is None:
            return not qname
        return bool(
            int(offset) < int(start_offset) + start.old_bytes
            and int(start_offset) < int(offset) + int(length)
        )

    def _interfaces(
        self, start: _Start, record: str, size: str
    ) -> list[WideningFinding]:
        found: list[WideningFinding] = []
        program = start.program
        for (kind, key), argument in sorted(self._record_ports(start, record).items()):
            if kind == PORT_FILE:
                datasets = sorted(
                    {
                        normalize_dataset(b.dataset, b.job)
                        for b in self.graph.bindings
                        if b.program.upper() == program and b.ddname.upper() == key
                    }
                )
                found.append(
                    WideningFinding(
                        "layout",
                        "warning",
                        program,
                        f"file:{key}",
                        f"{record} is a record of DD {key}: {size}, so the file's "
                        "record length (LRECL) changes"
                        + (f"; dataset {', '.join(datasets)}" if datasets else ""),
                    )
                )
                for dataset in datasets:
                    for other in sorted(
                        {
                            b.program.upper()
                            for b in self.graph.bindings
                            if normalize_dataset(b.dataset, b.job) == dataset
                            and b.program.upper() != program
                        }
                    ):
                        found.append(
                            WideningFinding(
                                "layout",
                                "error",
                                other,
                                f"dataset:{dataset}",
                                f"also reads or writes {dataset}, whose records "
                                f"{program} now lays out differently ({size}): its "
                                "record layout must change in step",
                            )
                        )
            elif kind == PORT_CALL:
                callee, _, position = key.rpartition("#")
                found.append(
                    WideningFinding(
                        "layout",
                        "warning",
                        program,
                        f"call:{key}",
                        (
                            (
                                f"{record} is passed as argument {position} of CALL "
                                f"{callee}: {size}; the callee's LINKAGE record must "
                                "change too, or it reads the fields after the change "
                                "at their old offsets"
                            )
                            if argument == record
                            else (
                                f"{argument} is passed as argument {position} of CALL "
                                f"{callee} and "
                                + (
                                    ""
                                    if argument == start.qname
                                    else f"holds {start.qname}, which "
                                )
                                + f"{'grows' if start.delta > 0 else 'shrinks'} by "
                                f"{start.delta:+d} bytes; the callee's LINKAGE item "
                                "must change too"
                            )
                        ),
                    )
                )
                for owner, callee_record in self._linkage_records(key):
                    found.append(
                        WideningFinding(
                            "layout",
                            "warning",
                            owner,
                            callee_record,
                            f"LINKAGE parameter {position}, passed {record} by "
                            f"{program}: {size}, and {callee_record} still "
                            "describes the old layout",
                        )
                    )
            elif kind == PORT_LINKAGE:
                entry, _, position = key.rpartition("#")
                for caller, argument in self._callers(program, key):
                    found.append(
                        WideningFinding(
                            "layout",
                            "error",
                            caller,
                            argument,
                            f"passes argument {position} to {entry}, whose "
                            f"LINKAGE record {record} {size.split(' ', 1)[1]}: "
                            "the callee now addresses bytes past the argument "
                            "unless the caller's record changes too",
                        )
                    )
        return found

    def _linkage_records(self, port_key: str) -> list[tuple[str, str]]:
        """(program, LINKAGE record) of every program whose entry point
        *port_key* (``NAME#n``: a PROGRAM-ID or an ENTRY name) receives, so
        a CALL of an ENTRY finds the record the ENTRY's USING names (#761)."""
        out: set[tuple[str, str]] = set()
        wanted = port_key.upper()
        for program, data in self.graph.reports.items():
            items = self._items[program]
            for edge in data.get("edges") or []:
                port, node = edge["source"], edge["target"]
                if (
                    port["kind"] == PORT_LINKAGE
                    and str(port["name"]).upper() == wanted
                    and node["kind"] == ITEM
                ):
                    item = items.get(str(node["name"]).upper())
                    if item is not None:
                        out.add((program, str(item.get("record") or node["name"])))
        return sorted(out)

    def _callers(self, program: str, port_key: str) -> list[tuple[str, str]]:
        """(caller, argument record) of every CALL in the graph passing the
        argument the LINKAGE port *port_key* (``NAME#n``, the PROGRAM-ID or
        an ENTRY name) receives."""
        out: set[tuple[str, str]] = set()
        wanted = port_key.upper()
        for caller, data in self.graph.reports.items():
            if caller == program:
                continue
            items = self._items[caller]
            for edge in data.get("edges") or []:
                node, port = edge["source"], edge["target"]
                if (
                    port["kind"] == PORT_CALL
                    and str(port["name"]).upper() == wanted
                    and node["kind"] == ITEM
                ):
                    name = str(node["name"]).upper()
                    item = items.get(name) or items.get(_base(name)) or {}
                    out.add((caller, str(item.get("record") or name)))
        return sorted(out)

    def _same_layout(self, start: _Start) -> list[WideningFinding]:
        """Other programs declaring the same field (the same qualified name
        and PICTURE): the same copybook, or a copy of it."""
        raw = _DUP_SUFFIX_RE.sub("", start.qname)
        found: list[WideningFinding] = []
        for program in sorted(self._items):
            if program == start.program:
                continue
            for qname, item in self._items[program].items():
                if _DUP_SUFFIX_RE.sub("", qname) != raw:
                    continue
                if normalize_picture(str(item.get("picture") or "")) != (
                    normalize_picture(str(start.item.get("picture") or ""))
                ):
                    continue
                found.append(
                    WideningFinding(
                        "same-layout",
                        "info",
                        program,
                        qname,
                        f"declares the same field with PIC {item.get('picture')} "
                        "(the same copybook, or a copy of it): change it there "
                        "too, or the programs disagree about the record",
                    )
                )
        return found
