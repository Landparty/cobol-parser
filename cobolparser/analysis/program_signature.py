"""
Call-site signature of a COBOL program: what a caller must pass it.

Every other analyzer in this package answers a question about the program
it is given. This one answers a question about the program *someone else*
is calling: given ``CALL "SUBPGM" USING ...``, what does SUBPGM actually
expect -- how many operands, in what order, each of what shape, and which
of them it writes back.

That question cannot be answered from the caller alone, which is exactly
why ``LinkageChecker`` (this package's existing LINKAGE analyzer) is scoped
to entry points *declared in the same source unit*: it correlates CALL
statements against ENTRY statements it can see. A caller and its callee
almost never share a source file on a real mainframe, so the answer has to
be extracted from the callee and carried across.

This module is that extraction. Point it at the callee and it produces a
:class:`ProgramSignature` -- a small, serializable, source-file-independent
description of the program's calling interface, built from three sources
that must agree and often do not:

  1. ``PROCEDURE DIVISION USING`` -- the primary (implicit) entry point.
     The parser records its operand list as the PROCEDURE division's
     ``using_parameters`` metadata (same place ``LinkageChecker`` reads it).
  2. ``ENTRY "NAME" USING`` statements -- alternate entry points, each with
     its own operand list.
  3. The LINKAGE SECTION -- where each of those operand names is declared,
     and therefore the only place the *shape* of a parameter lives: its
     PICTURE, USAGE, byte length, and whether it is a group.

A parameter named in (1) or (2) but absent from (3) is undeclared, and a
01-item present in (3) but named by neither is unused by any entry point.
Both are reported rather than smoothed over: a caller that passes an
operand the callee never declared is a real defect, and it is invisible
from either side alone.

Direction (does the callee read this parameter, write it, or both) is
derived from how the PROCEDURE DIVISION uses each parameter, reusing the
same role vocabulary the boundary inventory uses for CALL arguments. It is
graded, never guessed: a parameter the analyzer cannot classify is reported
as ``"unknown"`` and listed in :attr:`ProgramSignature.unchecked`, because
a caller told "input-only" about a field the callee actually overwrites has
been told something worse than nothing.

Multi-program files: :func:`extract_signatures` walks ``program_units()``
and returns one signature per unit, so a copybook-style source holding
several PROGRAM-IDs yields a signature for each rather than for the
outermost only.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..models.ast_base import SourceLocation
from ..models.data_items import CobolDataItem, ConditionNameItem
from ..models.program import CobolProgram, CobolSection
from ..models.statements.call import EntryStatement
from ._names import QUALIFIER_SEPARATOR
from .context import ProgramContext
from .unused_variables import _ancestor_names
from .xref import ROLE_CALL_ARGUMENT, ROLE_HOST_VARIABLE

#: Roles that may read *or* write the operand: graded ``unknown``.
_AMBIGUOUS_ROLES = frozenset({ROLE_CALL_ARGUMENT, ROLE_HOST_VARIABLE})

#: Section name the DATA DIVISION parser assigns to the LINKAGE SECTION.
#: Matches the convention ``LinkageChecker``/``UnusedVariableAnalyzer`` use.
_LINKAGE_SECTION = "LINKAGE"

#: Direction values. ``input`` = the callee only reads the operand;
#: ``output`` = it only writes it; ``input-output`` = both; ``unknown`` =
#: the analyzer could not classify it and says so rather than picking one.
DIRECTIONS: tuple[str, ...] = ("input", "output", "input-output", "unknown")


@dataclass
class SignatureParameter:
    """One operand of one entry point, joined to its LINKAGE declaration."""

    name: str
    position: int
    #: ``None`` when the operand is named by USING but never declared in the
    #: LINKAGE SECTION -- the mismatch this module exists to surface.
    declared: bool = False
    level: int | None = None
    picture: str | None = None
    usage: str | None = None
    #: Byte length of the item as declared, when it could be computed.
    byte_length: int | None = None
    is_group: bool = False
    occurs: int | None = None
    direction: str = "unknown"
    #: Passing mode the callee declares for this operand -- ``"REFERENCE"``
    #: or ``"VALUE"`` -- from ``PROCEDURE DIVISION USING [BY VALUE] ...``.
    #: An ENTRY statement's operands carry the mode its own ``USING [BY]
    #: VALUE/REFERENCE`` phrase declares.
    by_clause: str | None = None
    location: SourceLocation | None = None

    def declaration(self) -> str:
        """The operand's COBOL declaration, as a caller would have to write it.

        Group items have no PICTURE of their own, so they are described by
        their level and length instead of a fabricated picture string.
        """
        if not self.declared:
            return f"{self.name} (not declared in LINKAGE SECTION)"
        parts = [f"{self.level:02d}" if self.level is not None else "01", self.name]
        if self.picture:
            parts.append(f"PIC {self.picture}")
        elif self.is_group:
            size = f" ({self.byte_length} bytes)" if self.byte_length else ""
            parts.append(f"group item{size}")
        if self.usage and self.usage.upper() != "DISPLAY":
            parts.append(f"USAGE {self.usage}")
        if self.occurs:
            parts.append(f"OCCURS {self.occurs}")
        return " ".join(parts)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "position": self.position,
            "declared": self.declared,
            "level": self.level,
            "picture": self.picture,
            "usage": self.usage,
            "byte_length": self.byte_length,
            "is_group": self.is_group,
            "occurs": self.occurs,
            "direction": self.direction,
            "by_clause": self.by_clause,
            "declaration": self.declaration(),
            "location": self.location.to_dict() if self.location else None,
        }


@dataclass
class EntryPoint:
    """One callable entry: the primary PROCEDURE DIVISION or an ENTRY."""

    name: str
    #: ``"procedure-division"`` for the implicit primary entry,
    #: ``"entry-statement"`` for an explicit ``ENTRY "NAME"``.
    kind: str
    parameters: list[SignatureParameter] = field(default_factory=list)
    location: SourceLocation | None = None
    #: The ``RETURNING`` operand of ``PROCEDURE DIVISION USING ... RETURNING``
    #: (``None`` when there is none).
    returning: str | None = None
    #: True for a user-defined function (a FUNCTION-ID unit): it is invoked
    #: as ``FUNCTION name(arg ...)`` rather than CALLed.
    is_function: bool = False

    @property
    def parameter_count(self) -> int:
        return len(self.parameters)

    def call_example(self) -> str:
        """A ``CALL`` statement that would satisfy this entry point.

        The shape an editor shows at the call site, and the reason the
        operand *order* is preserved verbatim from the USING clause rather
        than sorted anywhere in this module. A user-defined function's is
        the ``FUNCTION name(arg ...)`` reference that invokes it.
        """
        if self.is_function:
            arguments = " ".join(p.name for p in self.parameters)
            return f"FUNCTION {self.name}({arguments})"
        text = f'CALL "{self.name}"'
        if self.parameters:
            # A BY phrase governs every following operand until the next
            # one, so it is written only where the mode changes from the
            # one in force (COBOL's default, BY REFERENCE, at the start). A
            # BY VALUE parameter passed without the phrase would be passed
            # by reference -- the callee would read an address as a value.
            pieces: list[str] = []
            mode = "REFERENCE"
            for parameter in self.parameters:
                wanted = (parameter.by_clause or mode).upper()
                piece = parameter.name
                if wanted != mode:
                    piece = f"BY {wanted} {piece}"
                    mode = wanted
                pieces.append(piece)
            text = f"{text} USING {', '.join(pieces)}"
        if self.returning:
            text = f"{text} RETURNING {self.returning}"
        return text

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "kind": self.kind,
            "parameter_count": self.parameter_count,
            "parameters": [p.to_dict() for p in self.parameters],
            "returning": self.returning,
            "call_example": self.call_example(),
            "location": self.location.to_dict() if self.location else None,
            **({"is_function": True} if self.is_function else {}),
        }


@dataclass
class ProgramSignature:
    """Everything a caller needs to know to call one program correctly."""

    program_id: str
    entry_points: list[EntryPoint] = field(default_factory=list)
    #: LINKAGE 01-items declared but named by no entry point's USING clause.
    #: Not an error on its own -- a program may address a LINKAGE item set up
    #: by ``SET ADDRESS OF`` -- but it is the other half of the mismatch
    #: picture and a caller should see it.
    unreferenced_linkage: list[str] = field(default_factory=list)
    #: Operands named by a USING clause with no LINKAGE declaration behind
    #: them. A caller passing one of these is passing into nothing.
    undeclared_parameters: list[str] = field(default_factory=list)
    #: What could not be determined exactly, and why. A quiet signature is
    #: never to be mistaken for a complete one.
    unchecked: list[str] = field(default_factory=list)

    @property
    def primary(self) -> EntryPoint | None:
        """The PROCEDURE DIVISION entry, which is what ``CALL "PROG"`` hits."""
        for entry in self.entry_points:
            if entry.kind == "procedure-division":
                return entry
        return None

    def entry(self, name: str) -> EntryPoint | None:
        """Look one entry point up by name, case-insensitively."""
        target = name.upper()
        for candidate in self.entry_points:
            if candidate.name.upper() == target:
                return candidate
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "program_id": self.program_id,
            "entry_points": [e.to_dict() for e in self.entry_points],
            "unreferenced_linkage": list(self.unreferenced_linkage),
            "undeclared_parameters": list(self.undeclared_parameters),
            "unchecked": list(self.unchecked),
        }


def _linkage_records(ast: CobolProgram) -> list[CobolDataItem]:
    """Every top-level item declared in the LINKAGE SECTION."""
    data_div = ast.get_division("DATA")
    if data_div is None:
        return []
    section = data_div.get_section_by_name(_LINKAGE_SECTION)
    if not isinstance(section, CobolSection):
        return []
    return [item for item in section.data_items if isinstance(item, CobolDataItem)]


def _byte_length(item: CobolDataItem) -> int | None:
    """Byte length of a LINKAGE item, or ``None`` when it cannot be computed.

    Defers to the generators package's layout machinery -- the single
    authority in this codebase on how many bytes a data item occupies -- so
    a signature's length and a record image's byte position cannot drift
    apart. Returns ``None`` rather than a guess when the layout cannot be
    computed (an unresolved OCCURS DEPENDING ON, a pictureless item the
    layout walker declines to size).
    """
    try:
        from ..layout.offsets import compute_record_layout

        layout = compute_record_layout(item)
    except Exception:  # noqa: BLE001 - length is optional, never fatal
        return None
    if not layout:
        return None
    root = layout[0]
    length = root.byte_length
    return int(length) if isinstance(length, int) else None


def _flatten(item: CobolDataItem) -> list[CobolDataItem]:
    """*item* and every data item nested under it, depth first."""
    out = [item]
    for child in getattr(item, "children", None) or []:
        if isinstance(child, CobolDataItem):
            out.extend(_flatten(child))
    return out


def _as_passed(direction: str, by_clause: str | None) -> str:
    """*direction* as the caller sees it, given the entry point's passing
    mode for the operand.

    A ``BY VALUE`` operand is a copy: nothing the callee writes to it
    reaches the caller, so from the caller's side it is input only (#490).
    ``unknown`` stays ``unknown``. Graded per entry point, since the same
    item can be BY VALUE on one entry and BY REFERENCE on another.
    """
    if (by_clause or "").upper() == "VALUE" and direction in (
        "input-output",
        "output",
    ):
        return "input"
    return direction


def _subordinate_names(item: CobolDataItem) -> list[tuple[str, str]]:
    """``(name, qualified name)`` of every data item and level-88 condition
    name beneath *item*, plus *item*'s own level-88s (not *item* itself).

    The qualified name (``"CUST-ID OF LK-CUST"``) is how xref names an item
    whose name another record also declares (``XrefEntry.qualified_name``).
    """
    names: list[tuple[str, str]] = []
    for index, node in enumerate(_flatten(item)):
        if index and node.name and not node.is_filler:
            names.append((node.name.upper(), _qualified(node)))
        for child in getattr(node, "children", None) or []:
            if isinstance(child, ConditionNameItem) and child.name:
                names.append((child.name.upper(), _qualified(child)))
    return names


def _qualified(node: Any) -> str:
    return QUALIFIER_SEPARATOR.join([node.name.upper(), *_ancestor_names(node)])


class ProgramSignatureExtractor:
    """Extracts the calling interface of a program from the callee's source.

    Follows this package's ``<Analyzer>().analyze(ast) -> <Report>`` shape.
    Single program unit, like every other analyzer here -- use
    :func:`extract_signatures` for a file holding several PROGRAM-IDs.
    """

    def __init__(self) -> None:
        # Per-analysis state set by ``_parameter_directions``: which roles
        # left a parameter's direction unknown, and which names xref saw
        # declared more than once.
        self._ambiguous_roles: dict[str, list[str]] = {}
        self._duplicate_declarations: set[str] = set()
        # Bare names xref split into one qualified entry per record.
        self._qualified_names: set[str] = set()

    def analyze(self, ast: CobolProgram | ProgramContext) -> ProgramSignature:
        """The external interface of *ast* (one program unit), or of a
        :class:`~.context.ProgramContext`'s unit, reusing its
        cross-reference."""
        ctx = ProgramContext.of(ast)
        ast = ctx.ast
        signature = ProgramSignature(program_id=ast.program_name or "")
        self._ambiguous_roles = {}
        self._duplicate_declarations = set()

        records = _linkage_records(ast)
        # Name -> declaration, over the whole LINKAGE subtree: a USING
        # clause may name a subordinate item, not only an 01-level record.
        declarations: dict[str, CobolDataItem] = {}
        for record in records:
            for node in _flatten(record):
                if node.name and not node.is_filler:
                    declarations.setdefault(node.name.upper(), node)

        directions = self._parameter_directions(ctx, signature)

        named: set[str] = set()
        for entry in self._entry_points(ast, signature):
            if entry.returning:
                # The RETURNING item is part of the calling interface too,
                # not an unreferenced LINKAGE record.
                named.add(entry.returning.upper())
            for parameter in entry.parameters:
                key = parameter.name.upper()
                named.add(key)
                declaration = declarations.get(key)
                if declaration is None:
                    if key not in signature.undeclared_parameters:
                        signature.undeclared_parameters.append(key)
                    continue
                self._apply_declaration(parameter, declaration)
                parameter.direction = _as_passed(
                    self._direction_for(key, declaration, directions, signature),
                    parameter.by_clause,
                )
            signature.entry_points.append(entry)

        for record in records:
            if record.name and not record.is_filler:
                if record.name.upper() not in named:
                    signature.unreferenced_linkage.append(record.name.upper())

        if not signature.entry_points:
            signature.unchecked.append(
                "no PROCEDURE DIVISION USING clause and no ENTRY statement: "
                "this program declares no calling interface, so a CALL to it "
                "may pass no operands"
            )
        return signature

    def _direction_for(
        self,
        key: str,
        declaration: CobolDataItem,
        directions: dict[str, str],
        signature: ProgramSignature,
    ) -> str:
        """The direction to report for one parameter.

        A group operand is passed whole but almost never *referenced* whole:
        ``PROCEDURE DIVISION USING LK-REC`` followed by ``MOVE LK-ACCT OF
        LK-REC TO ...`` touches the group only through its fields. Reporting
        that group as ``unknown`` would be true of the name and useless to
        the caller, who wants to know whether the callee writes into the
        record it is handing over. So a group with no reference of its own
        takes the union of its subordinate fields' directions -- reads plus
        writes anywhere inside the record are reads and writes of the record.

        Still never a guess: a group none of whose fields were classified
        either stays ``unknown`` and says so in ``unchecked``.
        """
        own = directions.get(key)
        if own == "unknown":
            roles = ", ".join(self._ambiguous_roles.get(key, []))
            signature.unchecked.append(
                f"{key}: direction not classified (referenced as {roles}, "
                "which may read or write it)"
            )
            return own
        if own == "input-output":
            return own

        # The operand's own references are not the whole story: ``DISPLAY
        # LK-REC`` plus ``MOVE 1 TO LK-FIELD`` reads the record *and* writes
        # into it, and a level-88 under the operand (``SET LK-OK TO TRUE``,
        # ``IF LK-OK``) writes / reads the operand itself.
        # A field another record also declares has a direction of its own,
        # under its qualified name; anything else is keyed by bare name.
        child_names = [
            qualified if name in self._qualified_names else name
            for name, qualified in _subordinate_names(declaration)
        ]
        child_names = [name for name in child_names if name in directions]
        if own is not None and not child_names:
            return own
        duplicated = sorted(
            name for name in child_names if name in self._duplicate_declarations
        )
        if duplicated:
            # The same field name is declared elsewhere too (a copybook in
            # both WORKING-STORAGE and LINKAGE): every reference to it was
            # attributed to the first declaration, so nothing here says
            # whether it was *this* group's field that was touched.
            signature.unchecked.append(
                f"{key}: direction not classified (its field(s) "
                f"{', '.join(duplicated)} are declared more than once, so their "
                "references cannot be attributed to this group)"
            )
            return "unknown"
        child_directions = {directions[name] for name in child_names}
        if own is not None:
            child_directions.add(own)
        if "unknown" in child_directions:
            signature.unchecked.append(
                f"{key}: direction not classified (a field under it is "
                "referenced only in a way that may read or write it)"
            )
            return "unknown"
        if not child_directions:
            signature.unchecked.append(
                f"{key}: direction not classified (the operand and every field "
                "under it are unreferenced in the PROCEDURE DIVISION)"
            )
            return "unknown"
        reads = {"input", "input-output"} & child_directions
        writes = {"output", "input-output"} & child_directions
        if reads and writes:
            return "input-output"
        return "output" if writes else "input"

    @staticmethod
    def _apply_declaration(
        parameter: SignatureParameter, declaration: CobolDataItem
    ) -> None:
        """Copy the LINKAGE declaration's shape onto the parameter."""
        parameter.declared = True
        parameter.level = declaration.level
        picture = declaration.picture_clause
        parameter.picture = picture.pattern if picture is not None else None
        parameter.usage = declaration.usage
        parameter.location = declaration.location
        children = [
            c
            for c in (getattr(declaration, "children", None) or [])
            if isinstance(c, CobolDataItem)
        ]
        parameter.is_group = bool(children) and picture is None
        occurs = declaration.occurs_clause
        if occurs is not None and isinstance(occurs.max_times, int):
            parameter.occurs = occurs.max_times
        parameter.byte_length = _byte_length(declaration)

    def _entry_points(
        self, ast: CobolProgram, signature: ProgramSignature
    ) -> list[EntryPoint]:
        """The primary PROCEDURE DIVISION entry plus every ENTRY statement.

        Operand order is the calling convention, so it is preserved exactly
        as written and never sorted.
        """
        entries: list[EntryPoint] = []

        proc_div = ast.get_division("PROCEDURE")
        if proc_div is not None:
            raw = proc_div.get_metadata("using_parameters") or []
            names = [str(p) for p in raw if str(p).strip()]
            # ``PROCEDURE DIVISION USING a b RETURNING r``: the parser keeps
            # RETURNING and its operand in the USING list. The operand is
            # the value the callee hands back, not a fourth USING operand.
            returning: str | None = None
            declared_returning = proc_div.get_metadata("returning_parameter")
            if declared_returning:
                returning = str(declared_returning).upper()
            upper_names = [n.upper() for n in names]
            if "RETURNING" in upper_names:
                at = upper_names.index("RETURNING")
                rest = names[at + 1 :]
                returning = rest[0].upper() if rest else None
                names = names[:at]
            raw_modes = proc_div.get_metadata("using_parameter_modes") or {}
            modes = (
                {str(k).upper(): str(v).upper() for k, v in raw_modes.items()}
                if isinstance(raw_modes, dict)
                else {}
            )
            if names or returning:
                entries.append(
                    EntryPoint(
                        name=ast.program_name or "",
                        kind="procedure-division",
                        parameters=[
                            SignatureParameter(
                                name=n.upper(),
                                position=i,
                                by_clause=modes.get(n.upper()),
                            )
                            for i, n in enumerate(names, start=1)
                        ],
                        returning=returning,
                        location=proc_div.location,
                        is_function=ast.unit_kind == "FUNCTION",
                    )
                )

        inner = {
            id(node)
            for contained in ast.contained_programs
            for node in contained.traverse_depth_first()
        }
        for stmt in ast.find_all_by_type("EntryStatement"):
            if not isinstance(stmt, EntryStatement):  # pragma: no cover - defensive
                continue
            if id(stmt) in inner:
                # A contained program's ENTRY is its own entry point.
                continue
            name = (stmt.entry_name or "").strip().strip("'\"")
            if not name:
                signature.unchecked.append(
                    "an ENTRY statement carries no resolvable entry name, so "
                    "its calling interface is not described here"
                )
                continue
            entry_modes = list(getattr(stmt, "parameter_modes", None) or [])
            params = [
                (str(p), entry_modes[i] if i < len(entry_modes) else None)
                for i, p in enumerate(stmt.using_parameters or [])
                if str(p).strip()
            ]
            entries.append(
                EntryPoint(
                    name=name.upper(),
                    kind="entry-statement",
                    parameters=[
                        SignatureParameter(name=n.upper(), position=i, by_clause=mode)
                        for i, (n, mode) in enumerate(params, start=1)
                    ],
                    location=stmt.location,
                )
            )
        return entries

    def _parameter_directions(
        self, ctx: ProgramContext, signature: ProgramSignature
    ) -> dict[str, str]:
        """Classify each LINKAGE name as read, written, or both.

        Built from one walk of the PROCEDURE DIVISION, using the cross-
        reference analyzer's role vocabulary so "what writes a field" is
        decided in exactly one place in this package rather than twice.
        A name the walk never sees stays ``"unknown"`` and is recorded in
        ``unchecked``: silence here means "not classified", never
        "input-only".
        """
        try:
            report = ctx.xref
        except Exception as exc:  # noqa: BLE001 - degrade, never fail
            signature.unchecked.append(
                f"parameter direction not classified ({type(exc).__name__}); "
                "every parameter is reported as unknown"
            )
            return {}

        directions: dict[str, str] = {}
        self._ambiguous_roles = {}
        self._qualified_names = {
            entry.name for entry in report.entries if entry.qualified_name
        }
        for entry in report.entries:
            # ``ENTRY "ALT" USING X`` names X as the entry's own parameter;
            # xref files that under the CALL-argument role, but it neither
            # reads nor writes X, and counting it as a (possibly-writing)
            # CALL argument graded every ENTRY parameter ``unknown``.
            roles = {
                ref.role
                for ref in entry.references
                if not (
                    ref.role == ROLE_CALL_ARGUMENT and ref.statement == "EntryStatement"
                )
            }
            if not roles:
                continue
            # Handed to a sub-CALL (BY REFERENCE by default) or to SQL as a
            # host variable (``INTO :X`` writes it), the operand may have
            # been written by something this analyzer does not see; that is
            # graded ``unknown`` and said so, never guessed as ``input``.
            ambiguous = roles & _AMBIGUOUS_ROLES
            writes = "write" in roles
            reads = bool(roles - {"write"} - ambiguous)
            key = (entry.qualified_name or entry.name).upper()
            if writes and reads:
                directions[key] = "input-output"
            elif ambiguous:
                directions[key] = "unknown"
                self._ambiguous_roles[key] = sorted(ambiguous)
            elif writes:
                directions[key] = "output"
            elif reads:
                directions[key] = "input"
        self._duplicate_declarations = set(report.duplicate_declarations)
        return directions


def extract_signatures(ast: CobolProgram) -> list[ProgramSignature]:
    """One :class:`ProgramSignature` per program unit in *ast*.

    A file holding several PROGRAM-IDs holds several callable programs; a
    caller may target any of them, so every unit gets a signature rather
    than the outermost only.
    """
    extractor = ProgramSignatureExtractor()
    units = ast.program_units() if hasattr(ast, "program_units") else [ast]
    return [extractor.analyze(unit) for unit in units]
