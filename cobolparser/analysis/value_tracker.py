"""
Value tracking analyzer for dynamic CALL statements.

This module provides analysis capabilities to track possible values for
variables used in dynamic CALL statements by analyzing MOVE statements
and initial VALUE clauses in data definitions.
"""

import re
from typing import Any

from ..models.ast_base import ASTNode
from ..models.data_items import CobolDataItem, ConditionNameItem
from ..models.program import CobolDivision, CobolProgram, CobolSection
from ..models.statements import (
    CallStatement,
    IOReadStatement,
    MoveStatement,
    ReturnStatement,
    SetStatement,
)
from ._names import base_data_name

#: ``:HV =`` in an ``EXEC SQL SET`` / ``GET DIAGNOSTICS`` statement: the host
#: variable on the left of the ``=`` receives the value.
_SQL_ASSIGNED_HOST_VAR_RE = re.compile(
    r":(?:[A-Za-z][A-Za-z0-9_-]*\.)*([A-Za-z][A-Za-z0-9_-]*)\s*="
)
#: EXEC CICS options whose data-name argument CICS writes, on any command.
_CICS_RECEIVING_OPTIONS = frozenset({"INTO", "SET", "RESP", "RESP2"})
#: EXEC CICS commands every data-name option of which is a receiver.
_CICS_ALL_RECEIVING_COMMANDS = frozenset({"ASSIGN"})
#: EXEC CICS commands whose ``PROGRAM(...)`` names the program they reach:
#: a data-name there is a dynamic program reference, like ``CALL WS-PGM``.
CICS_PROGRAM_COMMANDS = frozenset({"LINK", "XCTL", "LOAD"})
#: The data-name a reference starts with, before any subscript, reference
#: modification or ``OF`` / ``IN`` qualifier.
_REFERENCE_NAME_RE = re.compile(r"\s*([A-Za-z0-9][A-Za-z0-9_-]*)(.*)", re.DOTALL)
#: How many table occurrences a REDEFINES table is read for, at most.
_MAX_TABLE_OCCURRENCES = 4096


class DynamicCallAnalyzer:
    """Analyzer for tracking possible values in dynamic CALL statements.

    This analyzer traverses the AST to:
    1. Find all dynamic CALL statements (using variables)
    2. Track MOVE statements that assign values to those variables
    3. Track initial VALUE clauses in data definitions
    4. Populate the possible_values list for each dynamic CALL

    Example:
        ```python
        from cobolparser import parse_cobol
        from cobolparser.analysis import DynamicCallAnalyzer

        result = parse_cobol(cobol_source)
        analyzer = DynamicCallAnalyzer()
        analyzer.analyze(result.ast)

        # Now CallStatement nodes have populated possible_values
        for call in result.ast.find_statements("CALL"):
            if call.is_dynamic:
                print(f"Dynamic call to {call.called_program}")
                print(f"Possible values: {call.possible_values}")
        ```
    """

    def __init__(self) -> None:
        """Initialize the value tracker."""
        self._variable_values: dict[str, set[str]] = {}
        # Variables whose tracked value set is known to be INCOMPLETE: they
        # received a MOVE from an identifier-shaped source this analyzer does
        # not track (e.g. `MOVE WS-INPUT-PROG TO WS-TARGET` where
        # WS-INPUT-PROG has no VALUE clause and no tracked MOVE). Recording
        # the source's own *name* as a possible value -- the old behavior --
        # polluted the value set with a data-name that is not a value at all.
        self._incomplete_variables: set[str] = set()
        self._dynamic_calls: list[CallStatement] = []
        # Level-88 condition names by name: ``SET cond TO TRUE`` writes the
        # condition's VALUE into its parent item (#511).
        self._conditions: dict[str, list[ConditionNameItem]] = {}
        # id(MoveStatement) -> {item name: value} for a literal MOVE to a
        # group: the slice of the literal each tracked subordinate receives.
        self._group_slices: dict[int, dict[str, str]] = {}
        # The program unit being analysed: the walks stop at any other
        # (contained) CobolProgram node.
        self._unit: CobolProgram | None = None
        self._declared_names: set[str] | None = None

    def _is_other_unit(self, node: ASTNode) -> bool:
        return isinstance(node, CobolProgram) and node is not self._unit

    def analyze(self, ast: CobolProgram) -> None:
        """Analyze AST and populate possible values for dynamic CALL statements.

        Args:
            ast: The parsed COBOL program AST
        """
        # Procedure and data names are local to a program unit: each
        # contained program is tracked on its own data and MOVEs, never on
        # its container's (and vice versa). Innermost first, so the tracked
        # state left behind (``get_variable_values``) is *ast*'s own.
        units = ast.program_units() if isinstance(ast, CobolProgram) else [ast]
        if not isinstance(units, list) or not units:
            units = [ast]  # a hand-built node tree
        for unit in reversed(units):
            self._analyze_unit(unit)

    def _analyze_unit(self, ast: CobolProgram) -> None:
        """Track values and populate the dynamic CALLs of one program unit."""
        # Reset state
        self._variable_values = {}
        self._incomplete_variables = set()
        self._dynamic_calls = []
        self._conditions = {}
        self._group_slices = {}
        self._unit = ast
        # In a contained unit (analysed on its own or as part of its
        # container), a CALL variable it does not declare itself is a
        # container's GLOBAL item, whose writes are not tracked here.
        contained = isinstance(getattr(ast, "parent", None), CobolProgram)
        self._declared_names = (
            {
                node.name.upper()
                for node in self._walk(ast)
                if isinstance(node, CobolDataItem) and node.name
            }
            if contained
            else None
        )

        # First pass: collect initial values from data definitions
        self._collect_initial_values(ast)
        # ... and the values a REDEFINES gives the items it lays over storage
        # initialised by VALUE clauses (a FILLER-built program table).
        self._collect_redefines_values(self._walk(ast))

        # Storage the program does not fill itself -- the caller's (LINKAGE),
        # a READ/RETURN's (FD/SD records), DB2's (SQL INTO) or CICS's (INTO /
        # SET) -- holds values no MOVE here shows. Marked before the MOVE
        # pass so a MOVE out of such an item carries the flag along.
        self._mark_externally_supplied(ast)

        self._group_slices = self._literal_group_slices(self._walk(ast))

        # Second pass: track MOVE statements. The walk is in source order,
        # not execution order (a MOVE in a paragraph PERFORMed earlier may
        # sit later in the source), so it runs to a fixpoint: every MOVE
        # then copies its source's complete value set. The sets only grow,
        # so an unchanged size means nothing changed.
        while True:
            before = self._tracked_size()
            self._track_move_statements(ast)
            if self._tracked_size() == before:
                break

        # Every other way a CALL variable's storage can change (ACCEPT,
        # STRING/UNSTRING INTO, INITIALIZE, READ INTO, CALL ... USING, a
        # MOVE to its group or a subordinate item) supplies a value this
        # analyzer cannot know -- the value set is incomplete, not exact.
        self._mark_untracked_writes(ast)
        # ... and an item those writes made incomplete passes that on to
        # every item it is MOVEd to (#511).
        self._propagate_incomplete(self._walk(ast))

        # Third pass: find dynamic CALL statements and populate values
        self._populate_dynamic_calls(ast)

    def _tracked_size(self) -> tuple[int, int]:
        """How much the MOVE pass has recorded (values, incomplete names)."""
        return (
            sum(len(values) for values in self._variable_values.values()),
            len(self._incomplete_variables),
        )

    def _mark_externally_supplied(self, ast: CobolProgram) -> None:
        """Mark incomplete every item whose storage overlaps one the program
        does not write itself: a LINKAGE item (the caller supplies it), a
        record of a file the program READs or RETURNs, an EXEC SQL ``INTO``
        (or ``SET :hv =``, or ``CALL`` argument) host variable, and an EXEC
        CICS ``INTO`` / ``SET`` receiver."""
        nodes = self._walk(ast)
        supplied: set[str] = set()
        read_files: set[str] = set()
        for node in nodes:
            if isinstance(node, IOReadStatement | ReturnStatement):
                if node.file_name:
                    read_files.add(base_data_name(node.file_name).upper())
            elif getattr(node, "node_type", None) == "EXEC_CICS":
                supplied.update(self._cics_receivers(node))
            elif isinstance(getattr(node, "sql_text", None), str):
                supplied.update(self._sql_receivers(node))
        data_division = getattr(ast, "data_division", None)
        sections = (
            data_division.sections if isinstance(data_division, CobolDivision) else []
        )
        for section in sections:
            if not isinstance(section, CobolSection):
                continue
            linkage = "LINKAGE" in (section.section_name or "").upper()
            for item in section.data_items:
                if not isinstance(item, CobolDataItem) or not item.name:
                    continue
                fd_file = item.get_metadata("fd_file_name")
                if linkage or (fd_file and str(fd_file).upper() in read_files):
                    supplied.add(item.name.upper())
        if not supplied:
            return
        overlapping = self._overlapping_names(
            [node for node in nodes if isinstance(node, CobolDataItem)]
        )
        for node in nodes:
            if isinstance(node, CobolDataItem) and node.name:
                name = node.name.upper()
                if name in supplied or overlapping.get(name, set()) & supplied:
                    self._incomplete_variables.add(name)
        # A receiver the data walk did not see (a hand-built tree) still counts.
        self._incomplete_variables.update(supplied)

    @staticmethod
    def _cics_receivers(node: ASTNode) -> set[str]:
        """Data-names an EXEC CICS command writes."""
        command = (getattr(node, "cics_command", "") or "").upper()
        literal = {o.upper() for o in getattr(node, "literal_options", None) or ()}
        names: set[str] = set()
        for option, argument in (getattr(node, "options", None) or {}).items():
            key = option.upper()
            if not argument or key in literal:
                continue
            if (
                key in _CICS_RECEIVING_OPTIONS
                or command in _CICS_ALL_RECEIVING_COMMANDS
            ):
                names.add(base_data_name(argument).upper())
        return names

    @staticmethod
    def _sql_receivers(node: ASTNode) -> set[str]:
        """Host variables an EXEC SQL statement writes."""
        names = {v.upper() for v in getattr(node, "into_variables", None) or ()}
        text = (getattr(node, "sql_text", "") or "").lstrip().upper()
        if text.startswith(("SET", "GET")):
            names.update(_SQL_ASSIGNED_HOST_VAR_RE.findall(text))
        elif text.startswith("CALL"):
            # A stored procedure's OUT / INOUT parameters: which ones they
            # are is declared in DB2, not in the program.
            names.update(v.upper() for v in getattr(node, "host_variables", None) or ())
        return names

    def _collect_initial_values(self, node: ASTNode) -> None:
        """Collect initial values from VALUE clauses in data items."""
        if self._is_other_unit(node):
            return
        if isinstance(node, CobolDataItem):
            # Check if this data item has an initial value
            if node.value_clause is not None:
                var_name = node.name.upper() if node.name else None
                if var_name:
                    if var_name not in self._variable_values:
                        self._variable_values[var_name] = set()
                    # Route through the same literal-resolution path as MOVE
                    # sources so a figurative constant (VALUE SPACES, VALUE
                    # ZERO, ...) collapses to one canonical value instead of
                    # surviving as its own raw keyword text alongside the
                    # resolved value a MOVE of the same constant would add
                    # (e.g. both "SPACES" and " " for the same variable).
                    value = self._extract_literal_value(str(node.value_clause))
                    if value is None:
                        # A VALUE this does not read (X'..', N'..', ALL ..):
                        # no made-up candidate, the value is just unknown,
                        # as for a MOVE of the same literal.
                        self._incomplete_variables.add(var_name)
                    else:
                        self._variable_values[var_name].add(value)
        elif isinstance(node, ConditionNameItem) and node.name:
            self._conditions.setdefault(node.name.upper(), []).append(node)

        # Recursively process children
        if hasattr(node, "children"):
            for child in node.children:
                self._collect_initial_values(child)

    # -- REDEFINES tables ---------------------------------------------------

    def _collect_redefines_values(self, nodes: list[ASTNode]) -> None:
        """Values of the items a ``REDEFINES`` lays over VALUE-initialised
        storage: the FILLER-built program table.

        ``05 OPTS-DATA. 10 FILLER PIC X(08) VALUE 'PGMA'. ...`` followed by
        ``05 OPTS REDEFINES OPTS-DATA. 10 OPT OCCURS n. 15 OPT-PGM PIC
        X(08).`` gives every ``OPT-PGM`` occurrence the bytes the VALUE
        clauses put at its offset, so ``CALL OPT-PGM(IDX)`` (or ``EXEC CICS
        XCTL PROGRAM(OPT-PGM(IDX))``) can reach each of them. An occurrence
        whose bytes no VALUE clause fixes (a FILLER without VALUE, a non-
        DISPLAY item, past the end of the redefined item) marks the item
        incomplete instead. Layouts this does not size exactly (SYNC, OCCURS
        DEPENDING ON, a nested REDEFINES) are left alone.
        """
        for item in nodes:
            if (
                not isinstance(item, CobolDataItem)
                or not item.redefines
                or item.value_clause is not None
            ):
                continue
            base = self._redefined_item(item)
            if base is None:
                continue
            image = self._value_image(base)
            occurrences = self._occurrence_offsets(item)
            if (
                image is None
                or all(cell is None for cell in image)
                or occurrences is None
            ):
                # Storage a VALUE initialises but whose bytes are not read
                # here: the redefining items hold something unknown, not
                # nothing (#793).
                if self._has_value(base):
                    self._mark_tree_incomplete(item)
                continue
            for sub, starts in occurrences:
                if sub.is_filler or not sub.name or sub.value_clause is not None:
                    continue
                name = sub.name.upper()
                if (sub.usage or "DISPLAY").upper() != "DISPLAY":
                    self._incomplete_variables.add(name)
                    continue
                length = self._item_length(sub)
                for start in starts:
                    cells = image[start : start + length]
                    if len(cells) < length or any(c is None for c in cells):
                        self._incomplete_variables.add(name)
                        continue
                    value = "".join(c for c in cells if c is not None).rstrip()
                    self._variable_values.setdefault(name, set()).add(value or " ")

    @classmethod
    def _has_value(cls, item: CobolDataItem) -> bool:
        """True when *item* or an item under it has a VALUE clause."""
        if item.value_clause is not None:
            return True
        return any(
            cls._has_value(c)
            for c in item.children
            if isinstance(c, CobolDataItem) and not c.redefines
        )

    def _mark_tree_incomplete(self, item: CobolDataItem) -> None:
        """Mark *item* and every named item under it incomplete."""
        if item.name and not item.is_filler:
            self._incomplete_variables.add(item.name.upper())
        for child in item.children:
            if isinstance(child, CobolDataItem):
                self._mark_tree_incomplete(child)

    @staticmethod
    def _redefined_item(item: CobolDataItem) -> CobolDataItem | None:
        """The item whose storage *item* redefines -- the original one, at
        the end of a ``REDEFINES`` chain -- or None when it is not found."""
        current: CobolDataItem = item
        for _ in range(16):
            siblings = [
                c
                for c in getattr(current.parent, "children", None) or []
                if isinstance(c, CobolDataItem)
            ]
            if current not in siblings or not current.redefines:
                return None
            index = siblings.index(current)
            target = next(
                (
                    c
                    for c in reversed(siblings[:index])
                    if (c.name or "").upper() == current.redefines.upper()
                ),
                None,
            )
            if target is None:
                return None
            if not target.redefines:
                return target
            current = target
        return None

    @staticmethod
    def _item_length(item: CobolDataItem) -> int:
        """One occurrence's storage length of an elementary item."""
        # Imported here: the generators package imports the analysis one.
        from ..layout.offsets import elementary_byte_length

        return elementary_byte_length(item)

    @classmethod
    def _item_size(cls, item: CobolDataItem) -> int | None:
        """*item*'s storage size, every occurrence included, or None for a
        layout not sized exactly here (SYNC, OCCURS DEPENDING ON, a nested
        REDEFINES)."""
        occurs = item.occurs_clause
        if item.synchronized or (occurs is not None and occurs.depending_on):
            return None
        children = [c for c in item.children if isinstance(c, CobolDataItem)]
        if children:
            one = 0
            for child in children:
                size = None if child.redefines else cls._item_size(child)
                if size is None:
                    return None
                one += size
        else:
            one = cls._item_length(item)
        if occurs is not None:
            one *= occurs.max_times or occurs.min_times or 1
        return one

    @classmethod
    def _occurrence_offsets(
        cls, root: CobolDataItem
    ) -> list[tuple[CobolDataItem, list[int]]] | None:
        """``(elementary item, byte offset of every occurrence)`` for every
        elementary item under *root*, offsets relative to *root*'s start;
        None when the layout is not sized exactly."""
        found: list[tuple[CobolDataItem, list[int]]] = []

        def walk(item: CobolDataItem, starts: list[int]) -> bool:
            occurs = item.occurs_clause
            if occurs is not None:
                size = cls._item_size(item)
                if size is None:
                    return False
                times = occurs.max_times or occurs.min_times or 1
                one = size // times
                starts = [s + k * one for s in starts for k in range(times)]
                if len(starts) > _MAX_TABLE_OCCURRENCES:
                    return False
            children = [c for c in item.children if isinstance(c, CobolDataItem)]
            if not children:
                found.append((item, starts))
                return True
            cursor = 0
            for child in children:
                size = None if child.redefines else cls._item_size(child)
                if size is None or not walk(child, [s + cursor for s in starts]):
                    return False
                cursor += size
            return True

        if root.occurs_clause is not None or cls._item_size(root) is None:
            return None
        return found if walk(root, [0]) else None

    @classmethod
    def _value_image(cls, base: CobolDataItem) -> list[str | None] | None:
        """The bytes *base*'s VALUE clauses initialise, one character per
        byte (None where no VALUE fixes it), or None when *base* is not
        laid out exactly here."""
        cells: list[str | None] = []

        def fill(item: CobolDataItem) -> bool:
            if item.occurs_clause is not None or item.synchronized:
                return False
            children = [c for c in item.children if isinstance(c, CobolDataItem)]
            start = len(cells)
            if children:
                for child in children:
                    if child.redefines or not fill(child):
                        return False
                if item.value_clause is not None:
                    text = cls._value_text(item, len(cells) - start, group=True)
                    cells[start:] = (
                        list(text)
                        if text is not None
                        else [None] * (len(cells) - start)
                    )
                return True
            length = cls._item_length(item)
            text = cls._value_text(item, length, group=False)
            cells.extend(list(text) if text is not None else [None] * length)
            return True

        return cells if fill(base) else None

    @staticmethod
    def _value_text(item: CobolDataItem, length: int, group: bool) -> str | None:
        """The *length* DISPLAY characters *item*'s VALUE clause stores, or
        None when they are not known exactly here."""
        raw = (item.value_clause or "").strip()
        if not raw or item.justified:
            return None
        if not group and (item.usage or "DISPLAY").upper() != "DISPLAY":
            return None
        picture = None if group else item.picture_clause
        if picture is not None and (picture.is_national or picture.is_edited):
            return None
        upper = raw.upper()
        figuratives = {
            "SPACE": " ",
            "SPACES": " ",
            "ZERO": "0",
            "ZEROS": "0",
            "ZEROES": "0",
            "LOW-VALUE": "\x00",
            "LOW-VALUES": "\x00",
            "HIGH-VALUE": "\xff",
            "HIGH-VALUES": "\xff",
        }
        if upper in figuratives:
            return figuratives[upper] * length
        repeat = upper.startswith("ALL ")
        literal = raw[4:].strip() if repeat else raw
        quoted = len(literal) >= 2 and literal[0] == literal[-1] and literal[0] in "'\""
        numeric_picture = picture is not None and bool(
            re.fullmatch(r"(?:9(?:\(\d+\))?)+", picture.pattern.upper())
        )
        if quoted and not numeric_picture:
            text = literal[1:-1]
            if repeat and text:
                text = text * (length // len(text) + 1)
            return text.ljust(length)[:length]
        if numeric_picture and not repeat and literal.isdigit():
            return literal.zfill(length) if len(literal) <= length else None
        return None

    def _track_move_statements(self, node: ASTNode) -> None:
        """Track MOVE statements to collect possible values for variables."""
        if self._is_other_unit(node):
            return
        if isinstance(node, MoveStatement):
            # Get source and target(s)
            source = node.source
            targets = node.targets

            # A reference-modified receiver (``WS-PROG(1:4)``) only
            # overwrites part of the item: the MOVE's value is not the
            # item's value, and what the rest holds is not known here.
            partial = [t for t in targets if ":" in t]
            for target in partial:
                self._incomplete_variables.add(base_data_name(target).upper())
            targets = [t for t in targets if ":" not in t]

            if source and targets:
                # A qualified/subscripted reference string ("WS-PROG OF
                # GRP-1") is keyed by its base data name -- a later bare
                # `CALL WS-PROG` looks the variable up by that bare name,
                # so keying the folded string would silently miss it.
                source_upper = base_data_name(source).upper()

                # Check if source is a known variable (propagate its values)
                if source_upper in self._variable_values:
                    source_values = self._variable_values[source_upper]
                    source_incomplete = source_upper in self._incomplete_variables
                    for target in targets:
                        target_name = base_data_name(target).upper()
                        if target_name not in self._variable_values:
                            self._variable_values[target_name] = set()
                        self._variable_values[target_name].update(source_values)
                        if source_incomplete:
                            self._incomplete_variables.add(target_name)
                elif self._is_definite_literal(source):
                    # A quoted string, numeric literal, or figurative
                    # constant: an actual value, safe to record.
                    source_value = self._extract_literal_value(source)

                    if source_value:
                        for target in targets:
                            target_name = base_data_name(target).upper()
                            if target_name not in self._variable_values:
                                self._variable_values[target_name] = set()
                            self._variable_values[target_name].add(source_value)
                    # A group receiver: each tracked subordinate gets its
                    # own slice of the literal (#511).
                    for name, value in self._group_slices.get(id(node), {}).items():
                        self._variable_values.setdefault(name, set()).add(value)
                else:
                    # Identifier-shaped source with no tracked values: the
                    # target now holds a value this analyzer cannot know.
                    # Recording the source's NAME as a value would pollute
                    # the set (`MOVE WS-INPUT-PROG TO WS-TARGET` is not a
                    # MOVE of the literal "WS-INPUT-PROG") -- instead the
                    # target's value set is marked incomplete, surfaced on
                    # dynamic CALL nodes via the
                    # "possible_values_incomplete" metadata flag.
                    for target in targets:
                        self._incomplete_variables.add(base_data_name(target).upper())
        elif isinstance(node, SetStatement):
            self._track_condition_set(node)
            self._track_pointer_set(node)

        # Recursively process children
        if hasattr(node, "children"):
            for child in node.children:
                self._track_move_statements(child)

    @staticmethod
    def _condition_sets(stmt: SetStatement) -> list[tuple[str, bool]]:
        """``(target, to_true)`` for every ``SET ... TO TRUE | FALSE``
        receiver of *stmt*, across all of its target groups."""
        found: list[tuple[str, bool]] = []
        groups = [(stmt.targets, stmt.set_type)] + [
            (group.get("targets") or [], group.get("set_type")) for group in stmt.groups
        ]
        for targets, set_type in groups:
            if set_type in ("TRUE", "FALSE"):
                found += [(target, set_type == "TRUE") for target in targets]
        return found

    def _condition_set_value(
        self, condition: ConditionNameItem, to_true: bool
    ) -> str | None:
        """The value ``SET condition TO TRUE | FALSE`` moves into the
        condition's parent item, or None when it is not known exactly.

        TO TRUE moves the first literal of the VALUE clause (the low end of
        a THRU range); TO FALSE moves the ``WHEN SET TO FALSE`` literal. A
        group parent is not resolved here: its subordinates take slices.
        """
        parent = getattr(condition, "parent", None)
        if not isinstance(parent, CobolDataItem) or any(
            isinstance(child, CobolDataItem) for child in parent.children
        ):
            return None
        if to_true:
            raw = condition.values[0] if condition.values else None
        else:
            raw = condition.false_value
        if raw is None or raw.upper().startswith("THROUGH:"):
            return None
        value = self._extract_literal_value(raw)
        return value if value is not None else raw.strip("\"'")

    def _track_condition_set(self, stmt: SetStatement) -> None:
        """``SET cond TO TRUE | FALSE`` writes the condition's value into
        its parent item (#511): a known value is a candidate, anything else
        leaves the parent's value set incomplete."""
        for target, to_true in self._condition_sets(stmt):
            conditions = self._conditions.get(base_data_name(target).upper(), [])
            for condition in conditions:
                parent = getattr(condition, "parent", None)
                if not isinstance(parent, CobolDataItem) or not parent.name:
                    continue
                parent_name = parent.name.upper()
                value = self._condition_set_value(condition, to_true)
                if value is None or len(conditions) > 1:
                    # Unknown, or an unqualified name several 88s share:
                    # not resolved to one value here.
                    self._incomplete_variables.add(parent_name)
                else:
                    self._variable_values.setdefault(parent_name, set()).add(value)

    @staticmethod
    def _set_groups(
        stmt: SetStatement,
    ) -> list[tuple[list[str], str | None, str | None, bool, bool]]:
        """``(targets, set_type, value, value_is_address_of, value_is_entry)``
        for every target/value group of *stmt*, the first one included."""
        groups = [
            (
                stmt.targets,
                stmt.set_type,
                stmt.value,
                stmt.value_is_address_of,
                bool(stmt.metadata.get("value_is_entry")),
            )
        ]
        groups += [
            (
                group.get("targets") or [],
                group.get("set_type"),
                group.get("value"),
                bool(group.get("value_is_address_of")),
                bool(group.get("value_is_entry")),
            )
            for group in stmt.groups
        ]
        return groups

    @staticmethod
    def _is_null(value: str) -> bool:
        return value.strip().upper() in ("NULL", "NULLS")

    @staticmethod
    def _pointer_copies(stmt: SetStatement) -> list[tuple[str, list[str]]]:
        """``(source name, receivers)`` of every ``SET p TO identifier`` /
        ``SET p TO ENTRY identifier`` group of *stmt*: a copy of the
        source's value, the same as a MOVE from it (#593)."""
        if stmt.targets_are_address_of:
            return []
        return [
            (base_data_name(value).upper(), targets)
            for targets, set_type, value, address_of, _ in (
                DynamicCallAnalyzer._set_groups(stmt)
            )
            if set_type == "TO"
            and value
            and not address_of
            and not DynamicCallAnalyzer._is_definite_literal(value)
            and not DynamicCallAnalyzer._is_null(value)
        ]

    def _track_pointer_set(self, stmt: SetStatement) -> None:
        """``SET p TO ENTRY 'NAME'`` gives ``p`` the value ``NAME`` (the
        program a later ``CALL p`` reaches); ``SET p TO [ENTRY] identifier``
        copies the identifier's value set like a MOVE (#593). Every other
        ``SET`` write to an item (``UP BY``, ``ADDRESS OF``, a non-ENTRY
        literal) leaves its value set incomplete; ``TO NULL`` adds no
        target."""
        groups = self._set_groups(stmt)
        if stmt.targets_are_address_of:
            for targets, *_ in groups:
                for target in targets:
                    self._incomplete_variables.add(base_data_name(target).upper())
            return
        for targets, set_type, value, address_of, is_entry in groups:
            if set_type in ("TRUE", "FALSE"):
                continue
            names = [base_data_name(t).upper() for t in targets]
            if set_type != "TO" or not value or address_of:
                self._incomplete_variables.update(names)
            elif self._is_definite_literal(value):
                literal = self._extract_literal_value(value) if is_entry else None
                if literal:
                    for name in names:
                        self._variable_values.setdefault(name, set()).add(literal)
                else:
                    self._incomplete_variables.update(names)
            elif self._is_null(value):
                continue
            else:
                source = base_data_name(value).upper()
                if source in self._variable_values:
                    for name in names:
                        self._variable_values.setdefault(name, set()).update(
                            self._variable_values[source]
                        )
                if (
                    source not in self._variable_values
                    or source in self._incomplete_variables
                ):
                    self._incomplete_variables.update(names)

    @staticmethod
    def _identifier_moves(nodes: list[ASTNode]) -> list[tuple[str, list[str]]]:
        """``(source name, receivers)`` of every MOVE from a data item, and
        of every ``SET`` that copies one (#593)."""
        moves = [
            (base_data_name(node.source).upper(), node.targets)
            for node in nodes
            if isinstance(node, MoveStatement)
            and node.source
            and not DynamicCallAnalyzer._is_definite_literal(node.source)
        ]
        for node in nodes:
            if isinstance(node, SetStatement):
                moves += DynamicCallAnalyzer._pointer_copies(node)
        return moves

    def _value_sources(self, nodes: list[ASTNode]) -> set[str]:
        """Every dynamic CALL variable, and every item whose value reaches
        one through a chain of MOVEs: a write this analyzer cannot track to
        any of them leaves the CALL's candidate list incomplete (#511)."""
        names = {
            self.reference_name(call.called_program)[0]
            for call in nodes
            if isinstance(call, CallStatement)
            and call.is_dynamic
            and call.called_program
        }
        # EXEC CICS LINK / XCTL / LOAD PROGRAM(data-name) reaches a program
        # through its operand exactly as a dynamic CALL does.
        names.update(
            self.reference_name(operand)[0]
            for _, operand in self._cics_program_operands(nodes)
        )
        moves = self._identifier_moves(nodes)
        changed = bool(names)
        while changed:
            changed = False
            for source, targets in moves:
                if source not in names and any(
                    ":" not in t and base_data_name(t).upper() in names for t in targets
                ):
                    names.add(source)
                    changed = True
        return names

    def _propagate_incomplete(self, nodes: list[ASTNode]) -> None:
        """Carry an incomplete value set from a MOVE's identifier source to
        its receivers, to a fixpoint: the MOVE pass ran before
        :meth:`_mark_untracked_writes` found the source incomplete."""
        moves = self._identifier_moves(nodes)
        changed = True
        while changed:
            changed = False
            for source, targets in moves:
                if source not in self._incomplete_variables:
                    continue
                for target in targets:
                    name = base_data_name(target).upper()
                    if name not in self._incomplete_variables:
                        self._incomplete_variables.add(name)
                        changed = True

    def _literal_group_slices(self, nodes: list[ASTNode]) -> dict[int, dict[str, str]]:
        """id(MoveStatement) -> {subordinate: value} for every literal MOVE
        to a group with a tracked subordinate whose bytes are known.

        ``MOVE 'PGMX' TO WS-CTL`` is an alphanumeric MOVE to the group: each
        subordinate receives the slice of the (space-padded) literal at its
        own offset, and a figurative constant fills every one of them. A
        subordinate whose bytes are not exact (under an OCCURS, an ambiguous
        offset, a name declared twice, a non-DISPLAY usage) gets no slice,
        and :meth:`_mark_untracked_writes` marks it incomplete instead.
        """
        tracked = self._value_sources(nodes)
        if not tracked:
            return {}
        # Imported here: the generators package imports the analysis one.
        from ..layout.offsets import compute_record_layout

        items: dict[str, list[CobolDataItem]] = {}
        for node in nodes:
            if isinstance(node, CobolDataItem) and node.name:
                items.setdefault(node.name.upper(), []).append(node)
        layouts: dict[int, dict[str, Any]] = {}
        slices: dict[int, dict[str, str]] = {}
        for move in nodes:
            if not isinstance(move, MoveStatement) or not move.source:
                continue
            source = move.source.strip()
            if not self._is_definite_literal(source):
                continue
            figurative = source[:1] not in ("'", '"') and not (
                source[:1].isdigit() or source[:1] in "+-."
            )
            text = self._extract_literal_value(source) or ""
            for target in move.targets:
                declared = items.get(base_data_name(target).upper(), [])
                if ":" in target or len(declared) != 1:
                    continue
                group = declared[0]
                for sub in self._walk(group)[1:]:
                    if not isinstance(sub, CobolDataItem) or not sub.name:
                        continue
                    name = sub.name.upper()
                    if name not in tracked or len(items.get(name, [])) != 1:
                        continue
                    if not self._exact_bytes(group, sub):
                        continue
                    value = (
                        text
                        if figurative
                        else self._slice_of(
                            group, sub, text, layouts, compute_record_layout
                        )
                    )
                    if value is not None:
                        slices.setdefault(id(move), {})[name] = value
        return slices

    @staticmethod
    def _exact_bytes(group: CobolDataItem, sub: CobolDataItem) -> bool:
        """Whether *sub* is one run of DISPLAY bytes at a fixed place in
        *group* (no OCCURS between them)."""
        node: Any = sub
        while node is not group:
            if not isinstance(node, CobolDataItem) or node.occurs_clause:
                return False
            node = node.parent
        return not group.occurs_clause and (
            (sub.usage or "DISPLAY").upper() == "DISPLAY"
        )

    @staticmethod
    def _slice_of(
        group: CobolDataItem,
        sub: CobolDataItem,
        text: str,
        layouts: dict[int, dict[str, Any]],
        compute_record_layout: Any,
    ) -> str | None:
        """The part of *text*, MOVEd to *group*, that lands in *sub*."""
        root: CobolDataItem = group
        while isinstance(root.parent, CobolDataItem):
            root = root.parent
        if id(root) not in layouts:
            layouts[id(root)] = {
                item.name.upper(): item
                for item in compute_record_layout(root)
                if item.level != 88
            }
        layout = layouts[id(root)]
        whole = layout.get((group.name or "").upper())
        part = layout.get((sub.name or "").upper())
        if (
            whole is None
            or part is None
            or whole.byte_offset is None
            or part.byte_offset is None
            or whole.offset_ambiguous
            or part.offset_ambiguous
        ):
            return None
        start = part.byte_offset - whole.byte_offset
        padded = text.ljust(whole.byte_length)[: whole.byte_length]
        return padded[start : start + part.byte_length].rstrip() or " "

    def _mark_untracked_writes(self, ast: CobolProgram) -> None:
        """Mark a dynamic CALL variable incomplete when anything but a MOVE
        to the item itself writes its storage."""
        nodes = self._walk(ast)
        # The CALL variables and every item MOVEd into one (#511): an
        # untracked write to a MOVE source reaches the CALL just the same.
        call_vars = self._value_sources(nodes)
        if not call_vars:
            return
        # Imported here: xref imports the analysis package's siblings.
        from .xref import ROLE_CALL_ARGUMENT, ROLE_WRITE, XrefAnalyzer

        overlapping = self._overlapping_names(
            [node for node in nodes if isinstance(node, CobolDataItem)]
        )
        # The cross-reference needs a parsed PROCEDURE DIVISION to walk; a
        # hand-built node tree without one has only the MOVEs below.
        has_procedure = isinstance(
            getattr(ast, "procedure_division", None), CobolDivision
        )
        report = XrefAnalyzer().analyze(ast) if has_procedure else None
        for var in call_vars:
            for name in {var} | overlapping.get(var, set()):
                entry = report.entry_for(name) if report is not None else None
                if entry is None:
                    continue
                for ref in entry.references:
                    if ref.role not in (ROLE_WRITE, ROLE_CALL_ARGUMENT):
                        continue
                    if ref.statement == "MoveStatement":
                        # Read off the MOVE itself below: xref also records
                        # an OF/IN qualifier as written, which is not a
                        # write to the group.
                        continue
                    if ref.statement == "SetStatement" and name == var:
                        # A SET to the item itself was tracked (or marked
                        # incomplete) by _track_pointer_set (#593).
                        continue
                    self._incomplete_variables.add(var)
        for move in nodes:
            if not isinstance(move, MoveStatement):
                continue
            sliced = self._group_slices.get(id(move), {})
            for target in move.targets:
                written = base_data_name(target).upper()
                for var in call_vars:
                    if var in sliced:
                        # A literal MOVE to its group: the slice it
                        # receives was recorded as a value.
                        continue
                    if written in overlapping.get(var, ()):
                        self._incomplete_variables.add(var)
        # SET cond TO TRUE | FALSE writes the condition's parent item: a
        # parent sharing storage with a tracked item (its group, a
        # subordinate, a REDEFINES) is a write not tracked as a value.
        for stmt in nodes:
            if not isinstance(stmt, SetStatement):
                continue
            for target, _ in self._condition_sets(stmt):
                for condition in self._conditions.get(
                    base_data_name(target).upper(), []
                ):
                    parent = getattr(condition, "parent", None)
                    written = (getattr(parent, "name", "") or "").upper()
                    for var in call_vars:
                        if written in overlapping.get(var, ()):
                            self._incomplete_variables.add(var)

    @staticmethod
    def _walk(root: ASTNode) -> list[ASTNode]:
        """Every node under *root* (the same ``children`` walk the other
        passes make)."""
        found: list[ASTNode] = []
        stack = [root]
        while stack:
            node = stack.pop()
            if isinstance(node, CobolProgram) and node is not root:
                # A contained program: its names are its own.
                continue
            found.append(node)
            stack.extend(reversed(list(getattr(node, "children", None) or [])))
        return found

    @staticmethod
    def _overlapping_names(items: list[CobolDataItem]) -> dict[str, set[str]]:
        """Item name -> names of the items sharing its storage: its group
        ancestors and subordinate items, and every item on either side of a
        ``REDEFINES`` it (or an ancestor) takes part in."""
        overlapping: dict[str, set[str]] = {}

        def walk(item: CobolDataItem, ancestors: list[str]) -> None:
            name = (item.name or "").upper()
            for child in item.children:
                if isinstance(child, CobolDataItem):
                    walk(child, [*ancestors, name] if name else ancestors)
            if not name:
                return
            related = overlapping.setdefault(name, set())
            related.update(ancestors)
            for ancestor in ancestors:
                overlapping.setdefault(ancestor, set()).add(name)

        for item in items:
            if item.level in (1, 77):
                walk(item, [])

        # REDEFINES: the redefining item and the item it redefines share
        # bytes, and so does every subordinate on either side. Byte-range
        # precision is not attempted -- like the hierarchy rule above, any
        # write to the overlay counts as a write to every item in it.
        def subtree(item: CobolDataItem) -> set[str]:
            names: set[str] = set()
            stack = [item]
            while stack:
                node = stack.pop()
                if node.name:
                    names.add(node.name.upper())
                stack.extend(c for c in node.children if isinstance(c, CobolDataItem))
            return names

        by_name: dict[tuple[str, int], list[CobolDataItem]] = {}
        for item in items:
            if item.name:
                by_name.setdefault((item.name.upper(), item.level), []).append(item)
        # Union-find over items, so every redefinition of one area (and a
        # REDEFINES of a REDEFINES) lands in a single storage cluster.
        parent: dict[int, int] = {}

        def find(key: int) -> int:
            while parent.get(key, key) != key:
                key = parent[key]
            return key

        members: dict[int, CobolDataItem] = {}
        for item in items:
            if not item.redefines:
                continue
            for target in by_name.get((item.redefines.upper(), item.level), []):
                members[id(item)] = item
                members[id(target)] = target
                parent[find(id(item))] = find(id(target))
        clusters: dict[int, set[str]] = {}
        for key, item in members.items():
            clusters.setdefault(find(key), set()).update(subtree(item))
        for names in clusters.values():
            for name in names:
                overlapping.setdefault(name, set()).update(names)

        for name, related in overlapping.items():
            related.discard(name)
        return overlapping

    @staticmethod
    def _cics_program_operand(node: ASTNode) -> str | None:
        """The data-name operand of an ``EXEC CICS LINK | XCTL | LOAD
        PROGRAM(...)``, or None (another command, or a literal program)."""
        if getattr(node, "node_type", None) != "EXEC_CICS":
            return None
        command = (getattr(node, "cics_command", "") or "").upper()
        if command not in CICS_PROGRAM_COMMANDS:
            return None
        options = getattr(node, "options", None) or {}
        operand = next((v for k, v in options.items() if k.upper() == "PROGRAM"), None)
        literal = {o.upper() for o in getattr(node, "literal_options", None) or ()}
        if not isinstance(operand, str) or not operand.strip() or "PROGRAM" in literal:
            return None
        return operand.strip()

    @classmethod
    def _cics_program_operands(cls, nodes: list[ASTNode]) -> list[tuple[ASTNode, str]]:
        """``(statement, operand)`` of every dynamic EXEC CICS program
        reference among *nodes*."""
        found: list[tuple[ASTNode, str]] = []
        for node in nodes:
            operand = cls._cics_program_operand(node)
            if operand is not None:
                found.append((node, operand))
        return found

    def _populate_dynamic_calls(self, node: ASTNode) -> None:
        """Find dynamic CALL statements and populate their possible values."""
        if self._is_other_unit(node):
            return
        operand = self._cics_program_operand(node)
        if operand is not None:
            # EXEC CICS XCTL PROGRAM(WS-PGM): the same candidates a
            # ``CALL WS-PGM`` would get, on the statement's metadata.
            values, incomplete = self.resolve_variable(operand)
            node.set_metadata("possible_values", values)
            if incomplete:
                node.set_metadata("possible_values_incomplete", True)
            else:
                node.metadata.pop("possible_values_incomplete", None)
        if isinstance(node, CallStatement):
            if node.is_dynamic and node.called_program:
                # Look up the variable name in our tracked values
                values, incomplete = self.resolve_variable(node.called_program)
                # Always (re)set: an earlier analysis of an enclosing unit,
                # or of this one, must not leave its values or its
                # incomplete flag behind.
                node.set_possible_values(values)
                if incomplete:
                    node.set_metadata("possible_values_incomplete", True)
                else:
                    node.metadata.pop("possible_values_incomplete", None)

        # Recursively process children
        if hasattr(node, "children"):
            for child in node.children:
                self._populate_dynamic_calls(child)

    def resolve_variable(self, variable_name: str) -> tuple[list[str], bool]:
        """``(possible values, incomplete)`` for a data-name in the last unit
        :meth:`analyze` tracked -- the same answer a dynamic ``CALL`` on it
        gets, for any other statement that names a program through a
        data-name (``EXEC CICS LINK PROGRAM(WS-PGM)``).

        ``incomplete`` is True when the variable also received a value this
        analyzer could not resolve, or is not declared in this unit at all
        (a container's GLOBAL item): the values, even when present, are then
        not exhaustive.
        """
        var_name, partial = self.reference_name(variable_name)
        if partial:
            # ``PROGRAM(WS-PGM(1:5))`` reads part of the item: its values
            # are not the operand's.
            return [], True
        incomplete = var_name in self._incomplete_variables or (
            self._declared_names is not None and var_name not in self._declared_names
        )
        return sorted(self._variable_values.get(var_name, ())), incomplete

    @staticmethod
    def reference_name(reference: str) -> tuple[str, bool]:
        """``(data-name, partial)`` of an operand as a statement spells it.

        ``OPT-PGM(WS-IDX)``, ``OPT-PGM ( WS-IDX )`` and ``OPT-PGM OF GRP``
        all name ``OPT-PGM`` (upper-cased); every occurrence of a table item
        is a candidate. *partial* is True for a reference-modified operand
        (``WS-PGM(1:5)``), which reads part of the item only.
        """
        match = _REFERENCE_NAME_RE.match(reference or "")
        if match is None:
            return (reference or "").strip().upper(), False
        return match.group(1).upper(), ":" in match.group(2)

    @staticmethod
    def _is_definite_literal(source: str) -> bool:
        """True only for a source that is certainly a VALUE, never a name:
        a quoted string literal, a numeric literal, or a figurative constant.

        An identifier-shaped source (``PROGRAM-A``, ``WS-INPUT-PROG``) is NOT
        definite -- the parser keeps quotes on ``MoveStatement.source``, so an
        unquoted hyphenated token is a data-name reference, not a literal.
        ``_track_move_statements`` uses this gate before recording a value;
        sources failing it mark the target's value set incomplete instead.
        """
        if not source:
            return False
        s = source.strip()
        if len(s) >= 2 and ((s[0] == s[-1] == '"') or (s[0] == s[-1] == "'")):
            return True
        if s and s.replace("-", "").replace("+", "").replace(".", "").isdigit():
            return True
        return s.upper() in (
            "ZERO",
            "ZEROS",
            "ZEROES",
            "SPACE",
            "SPACES",
            "LOW-VALUE",
            "LOW-VALUES",
            "HIGH-VALUE",
            "HIGH-VALUES",
        )

    def _extract_literal_value(self, source: str) -> str | None:
        """Extract literal value from source string.

        Note: the trailing identifier-shaped fallback below is deliberately
        permissive (it echoes back any name-shaped token); callers recording
        values must first gate on :meth:`_is_definite_literal` so a bare
        data-name is never recorded as if it were a value.

        Args:
            source: Source string that might be a literal

        Returns:
            The literal value without quotes, or None if not a literal
        """
        if not source:
            return None

        source = source.strip()

        # Check for string literals (quoted)
        if (source.startswith('"') and source.endswith('"')) or (
            source.startswith("'") and source.endswith("'")
        ):
            return source[1:-1]

        # Check for numeric literals
        if source.replace("-", "").replace("+", "").replace(".", "").isdigit():
            return source

        # Check for ZERO/ZEROS/ZEROES, SPACE/SPACES
        upper_source = source.upper()
        if upper_source in ("ZERO", "ZEROS", "ZEROES"):
            return "0"
        if upper_source in ("SPACE", "SPACES"):
            return " "
        if upper_source in ("LOW-VALUE", "LOW-VALUES"):
            return "\x00"
        if upper_source in ("HIGH-VALUE", "HIGH-VALUES"):
            return "\xff"

        # If the source contains a hyphen and doesn't match a known figurative constant,
        # it's likely an unquoted string literal (parser strips quotes from STRING_LITERAL tokens)
        # Examples: PROGRAM-A, SUB-PROG, MY-VALUE
        # We treat any alphanumeric string with hyphens as a potential literal value
        if "-" in source or source.replace("-", "").isalnum():
            # Only treat it as a literal if it's not already tracked as a variable
            # (this check happens in the caller)
            return source

        # Not a literal
        return None

    def get_variable_values(self, variable_name: str) -> list[str]:
        """Get all tracked values for a specific variable.

        Args:
            variable_name: Name of the variable to look up

        Returns:
            List of possible values for the variable
        """
        var_name = variable_name.upper()
        if var_name in self._variable_values:
            return sorted(self._variable_values[var_name])
        return []

    def get_all_tracked_variables(self) -> list[str]:
        """Get names of all variables being tracked.

        Returns:
            List of variable names that have tracked values
        """
        return sorted(self._variable_values.keys())
