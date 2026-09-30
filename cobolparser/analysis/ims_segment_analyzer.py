"""
IMS DLI segment name analyzer.

Analyzes COBOL programs that use the IMS DLI (Data Language Interface) to
identify the IMS database segment names accessed by each call to CBLTDLI,
AIBTDLI, or CEETDLI.  The analysis is entirely static: segment names are
extracted from the first 8 bytes of SSA (Segment Search Argument) data-item
definitions and, when those bytes are set dynamically, from MOVE-statement
value tracking.

IMS DLI CALL parameter convention
----------------------------------
    CALL 'CBLTDLI' USING func-code   <- 1st  : function code (GU, ISRT, …)
                          pcb-name    <- 2nd  : PCB (database view)
                          io-area     <- 3rd  : data area for segment I/O
                          ssa-1       <- 4th+ : Segment Search Arguments
                          ssa-2
                          ...

The segment name is *always* the first 8 bytes of an SSA.  Unqualified SSAs
consist only of those 8 bytes plus a trailing space; qualified SSAs follow
with a parenthesised field/operator/value expression.
"""

import re
from dataclasses import dataclass, field

from ..models.ast_base import ASTNode, SourceLocation
from ..models.data_items import CobolDataItem
from ..models.program import CobolProgram
from ..models.statements import CallStatement, MoveStatement
from ._names import base_data_name

# ── Constants ────────────────────────────────────────────────────────────────

_IMS_FUNCTION_CODES: frozenset[str] = frozenset(
    {
        "GU",
        "GN",
        "GNP",
        "GHU",
        "GHN",
        "GHNP",
        "ISRT",
        "DLET",
        "REPL",
        "CHKP",
        "XRST",
        "XDLT",
        "XRPL",
        "TERM",
        "ROLLB",
        "PURG",
    }
)

# Positional indices within the USING parameter list
_PARAM_FUNC_CODE = 0
_PARAM_PCB = 1
_PARAM_IO_AREA = 2
_PARAM_SSA_START = 3

# Segment name occupies the first 8 bytes of every SSA
_SSA_SEGMENT_NAME_LEN = 8

# Interfaces that accept an optional leading parameter-count operand
# (`CALL 'CBLTDLI' USING parmcount, function, ...`). CEETDLI takes none.
_PARMCOUNT_INTERFACES: frozenset[str] = frozenset({"CBLTDLI", "AIBTDLI"})
#: The group names an ``OF``/``IN`` qualifier chain names in a MOVE target.
_QUALIFIER_RE = re.compile(r"\b(?:OF|IN)\s+([A-Za-z0-9][A-Za-z0-9-]*)", re.IGNORECASE)
_NUMERIC_PICTURE_RE = re.compile(r"^S?[9()0-9]+$")


# ── Result dataclass ──────────────────────────────────────────────────────────


@dataclass
class IMSDLICall:
    """Analysis result for a single IMS DLI CALL statement.

    Attributes:
        location:          Source location of the CALL statement.
        interface:         IMS interface name without quotes (e.g. ``"CBLTDLI"``).
        function_code:     Resolved DLI verb (e.g. ``"GU"``, ``"ISRT"``), or
                           ``None`` when it cannot be determined statically.
        function_code_var: Name of the variable that holds the function code.
        pcb_name:          Variable name of the PCB parameter.
        io_area_name:      Variable name of the I/O area parameter.
        ssa_names:         Variable names of the SSA parameters (may be empty).
        segment_names:     Resolved segment names in the same order as
                           *ssa_names*.  An entry is ``None`` when the name
                           cannot be determined statically.
    """

    location: SourceLocation
    interface: str
    function_code: str | None
    function_code_var: str | None
    pcb_name: str | None
    io_area_name: str | None
    ssa_names: list[str] = field(default_factory=list)
    segment_names: list[str | None] = field(default_factory=list)

    @property
    def primary_segment(self) -> str | None:
        """First resolved segment name, or ``None`` if none could be resolved."""
        return next((s for s in self.segment_names if s), None)


@dataclass
class IMSEntryPoint:
    """An ENTRY 'DLITCBL' declaration — the IMS batch program entry point.

    Attributes:
        entry_name:  Always ``"DLITCBL"`` (normalised to uppercase).
        pcb_names:   PCB parameter names from the USING clause, in order
                     (IO-PCB first, then DB-PCBs / alternate PCBs).
        location:    Source location of the ENTRY statement.
    """

    entry_name: str
    pcb_names: list[str] = field(default_factory=list)
    location: SourceLocation | None = None


# ── Analyzer ─────────────────────────────────────────────────────────────────


class IMSSegmentAnalyzer:
    """Resolve IMS segment names for every DLI CALL in a COBOL program.

    The analyzer performs three passes over the AST:

    1. **Data collection** – record every ``CobolDataItem`` and its VALUE clause.
    2. **MOVE tracking** – propagate literal values through MOVE statements so
       that dynamically-assigned SSA names can also be resolved.
    3. **DLI call analysis** – for each CALL to an IMS interface, map the SSA
       parameters to segment names using the information gathered above.

    Example::

        from cobolparser import parse_cobol
        from cobolparser.analysis import IMSSegmentAnalyzer

        result = parse_cobol(source)
        analyzer = IMSSegmentAnalyzer()
        dli_calls = analyzer.analyze(result.ast)

        for call in dli_calls:
            print(call.interface, call.function_code, call.segment_names)

        all_segments = analyzer.get_all_segment_names(dli_calls)
    """

    def __init__(self) -> None:
        self._data_items: dict[str, CobolDataItem] = {}
        self._variable_values: dict[str, set[str]] = {}
        # Values a variable received via MOVE only (no VALUE clauses).
        # Needed by the group-SSA segment-name merge: VALUE clauses are
        # keyed by bare name, so two SSAs whose child fields share a name
        # (both called SSA-SEG-NAME, qualified differently) would cross-
        # contaminate each other's static values if merged from
        # _variable_values.
        self._moved_values: dict[str, set[str]] = {}
        # ``MOVE 'ORDER' TO SEG-NAME OF SSA2``: bare target name -> (its
        # OF/IN qualifiers, the values moved), so the move lands on the SSA
        # it names rather than on no SSA at all (the qualified text never
        # matched a child's bare name) or on every same-named child.
        self._qualified_moves: dict[str, list[tuple[frozenset[str], set[str]]]] = {}

    # ── Public API ───────────────────────────────────────────────────────────

    def analyze(self, ast: CobolProgram) -> list[IMSDLICall]:
        """Analyze *ast* and return one :class:`IMSDLICall` per DLI CALL.

        Args:
            ast: Parsed COBOL program AST.

        Returns:
            List of :class:`IMSDLICall` objects in source order.
        """
        self._data_items = {}
        self._variable_values = {}
        self._moved_values = {}
        self._qualified_moves = {}

        self._collect_data_items(ast)
        self._track_move_statements(ast)
        return self._build_dli_calls(ast)

    def get_all_segment_names(self, results: list[IMSDLICall]) -> list[str]:
        """Return a sorted list of all distinct resolved segment names.

        Args:
            results: Output of :meth:`analyze`.

        Returns:
            Sorted list of unique, non-``None`` segment names.
        """
        names: set[str] = set()
        for r in results:
            for name in r.segment_names:
                if name:
                    names.add(name)
        return sorted(names)

    def get_entry_points(self, ast: CobolProgram) -> list[IMSEntryPoint]:
        """Return all ENTRY 'DLITCBL' declarations found in *ast*.

        Each returned :class:`IMSEntryPoint` captures the entry name (always
        ``"DLITCBL"``) and the PCB parameter list from the USING clause, which
        identifies the program as an IMS DL/I batch transaction entry point.

        Args:
            ast: Parsed COBOL program AST.

        Returns:
            List of :class:`IMSEntryPoint` objects in source order.
        """
        from ..models.statements import EntryStatement

        points: list[IMSEntryPoint] = []
        for stmt in ast.get_all_statements():
            if (
                isinstance(stmt, EntryStatement)
                and (stmt.entry_name or "").upper() == "DLITCBL"
            ):
                points.append(
                    IMSEntryPoint(
                        entry_name=stmt.entry_name.upper(),  # type: ignore[union-attr]
                        pcb_names=list(stmt.using_parameters),
                        location=stmt.location,
                    )
                )
        return points

    # ── Pass 1: collect data items ───────────────────────────────────────────

    def _collect_data_items(self, node: ASTNode) -> None:
        if isinstance(node, CobolDataItem) and node.name:
            key = node.name.upper()
            self._data_items[key] = node
            if node.value_clause is not None:
                value = str(node.value_clause).strip("\"'")
                self._variable_values.setdefault(key, set()).add(value)

        if hasattr(node, "children"):
            for child in node.children:
                self._collect_data_items(child)

    # ── Pass 2: track MOVE statements ───────────────────────────────────────

    def _track_move_statements(self, node: ASTNode) -> None:
        if isinstance(node, MoveStatement) and node.source and node.targets:
            src_key = node.source.upper()
            values: set[str] = set()
            if src_key in self._variable_values:
                # Propagate known values from source variable to targets
                values = set(self._variable_values[src_key])
            else:
                # Only propagate when source is a genuine literal (quoted string,
                # numeric, or figurative constant).  Bare identifiers that are not
                # yet in _variable_values are unresolved variable references whose
                # value is unknown; recording their name as a value would cause
                # false segment-name resolution (e.g. "WS-SEG" → segment "WS-SEG").
                literal = _extract_literal(node.source)
                if literal is not None:
                    values = {literal}
            if values:
                for tgt in node.targets:
                    self._variable_values.setdefault(tgt.upper(), set()).update(values)
                    qualifiers = frozenset(
                        q.upper() for q in _QUALIFIER_RE.findall(tgt)
                    )
                    if qualifiers:
                        base = base_data_name(tgt).upper()
                        self._qualified_moves.setdefault(base, []).append(
                            (qualifiers, values)
                        )
                    else:
                        self._moved_values.setdefault(tgt.upper(), set()).update(values)

        if hasattr(node, "children"):
            for child in node.children:
                self._track_move_statements(child)

    # ── Pass 3: build IMSDLICall results ─────────────────────────────────────

    def _build_dli_calls(self, ast: CobolProgram) -> list[IMSDLICall]:
        results: list[IMSDLICall] = self._build_exec_dli_calls(ast)
        for stmt in ast.get_ims_interface_calls():
            if not isinstance(stmt, CallStatement):
                # Bare CobolStatement stubs (e.g. from unit-test fixtures) are
                # skipped; only fully-parsed CallStatement nodes are processed.
                continue

            params = stmt.using_parameters
            interface = (_strip_quotes(stmt.called_program or "") or "").upper()
            if (
                interface in _PARMCOUNT_INTERFACES
                and params
                and self._is_parmcount(params[0].name)
            ):
                # `CALL 'CBLTDLI' USING parmcount, function, pcb, ...`: the
                # optional leading count shifts every positional operand.
                params = params[1:]
            func_var = (
                params[_PARAM_FUNC_CODE].name
                if len(params) > _PARAM_FUNC_CODE
                else None
            )
            pcb_name = params[_PARAM_PCB].name if len(params) > _PARAM_PCB else None
            io_area = (
                params[_PARAM_IO_AREA].name if len(params) > _PARAM_IO_AREA else None
            )
            ssa_names = [p.name for p in params[_PARAM_SSA_START:]]

            results.append(
                IMSDLICall(
                    location=stmt.location,
                    interface=interface,
                    function_code=self._resolve_func_code(func_var),
                    function_code_var=func_var,
                    pcb_name=pcb_name,
                    io_area_name=io_area,
                    ssa_names=ssa_names,
                    segment_names=[self._resolve_ssa_segment(n) for n in ssa_names],
                )
            )
        results.sort(key=lambda call: (call.location.line, call.location.column))
        return results

    @staticmethod
    def _build_exec_dli_calls(ast: CobolProgram) -> list[IMSDLICall]:
        """One :class:`IMSDLICall` per ``EXEC DLI`` statement.

        The command-level interface names everything the CALL form hides
        in an SSA: the function is the command word, the PCB is
        ``USING PCB(n)``, the I/O area is ``INTO(...)`` / ``FROM(...)`` and
        each ``SEGMENT(name)`` option names a segment on the path. Program
        control commands (``SCHD``, ``TERM``, ``CHKP``, ...) are reported
        too, with no segment, so a program's full DL/I surface is visible.
        """
        calls: list[IMSDLICall] = []
        for stmt in ast.find_all_by_type("ExecImsStatement"):
            command = (getattr(stmt, "ims_command", "") or "").upper()
            if not command:
                continue
            pcb_name: str | None = None
            io_area: str | None = None
            segments: list[str | None] = []
            for argument in getattr(stmt, "arguments", None) or []:
                keyword, _, rest = argument.partition("(")
                keyword = keyword.strip().upper()
                value = rest[:-1].strip() if rest.endswith(")") else rest.strip()
                if keyword == "PCB" and value:
                    pcb_name = f"PCB({value})"
                elif keyword in ("INTO", "FROM") and value and io_area is None:
                    io_area = value
                elif keyword == "SEGMENT" and value:
                    segments.append(value.upper())
            calls.append(
                IMSDLICall(
                    location=stmt.location,
                    interface="EXEC DLI",
                    function_code=command,
                    function_code_var=None,
                    pcb_name=pcb_name,
                    io_area_name=io_area,
                    ssa_names=[],
                    segment_names=segments,
                )
            )
        return calls

    # ── Resolution helpers ───────────────────────────────────────────────────

    def _is_parmcount(self, name: str | None) -> bool:
        """True when *name* is the optional leading parameter-count operand.

        IMS takes it as a binary fullword (``PIC S9(9) BINARY``), while a
        function code is always 4 alphanumeric bytes, so a numeric literal
        or a data item with a purely numeric PICTURE can only be the count.
        """
        if not name:
            return False
        text = name.strip()
        if text.lstrip("+-").isdigit():
            return True
        item = self._data_items.get(text.upper())
        if item is None or item.picture_clause is None:
            return False
        return bool(_NUMERIC_PICTURE_RE.match(item.picture_clause.pattern.upper()))

    def _resolve_func_code(self, var_name: str | None) -> str | None:
        """Resolve a function-code variable/literal to an IMS verb like ``"GU"``."""
        if not var_name:
            return None

        # Case 1: quoted inline literal (e.g. USING "'GU  '" still with quotes)
        stripped_of_quotes = _strip_quotes(var_name)
        if stripped_of_quotes != var_name.strip():  # quotes were present
            return stripped_of_quotes.strip().upper() or None

        # Case 2: unquoted literal whose quotes the CALL parser already stripped
        # (e.g. USING 'GU  ' in COBOL arrives here as var_name="GU  ").
        # Recognise it directly when the normalised value is a known DLI verb.
        normalized = var_name.strip().upper()
        if normalized in _IMS_FUNCTION_CODES:
            return normalized

        # Case 3: variable name – look up its tracked values
        if normalized in self._variable_values:
            candidates = {v.strip().upper() for v in self._variable_values[normalized]}
            # Prefer known IMS verbs; fall back to any tracked value
            pool = candidates & _IMS_FUNCTION_CODES or candidates
            if pool:
                return "/".join(sorted(pool)) if len(pool) > 1 else next(iter(pool))
        return None

    def _resolve_ssa_segment(self, ssa_var: str) -> str | None:
        """Return the segment name (first 8 bytes) for *ssa_var*, or ``None``."""
        if not ssa_var:
            return None
        var = ssa_var.upper()

        item = self._data_items.get(var)
        if item is not None:
            # Group item: the segment name lives in the first child field.
            # Merge its static VALUE clause with any MOVE-tracked values on
            # that child — programs routinely MOVE a new segment name into
            # the child (MOVE 'SEGB' TO SSA1-SEG-NAME), and reporting only
            # the static VALUE would state a stale name with full
            # confidence. Multiple candidates use the "/" convention.
            data_children = [c for c in item.children if isinstance(c, CobolDataItem)]
            if data_children:
                child = data_children[0]
                candidates: set[str] = set()
                if child.value_clause is not None:
                    raw = str(child.value_clause).strip("\"'")
                    name = raw[:_SSA_SEGMENT_NAME_LEN].rstrip()
                    if name:
                        candidates.add(name)
                child_name = (child.name or "").upper()
                moved_in = set(self._moved_values.get(child_name, ()))
                for qualifiers, values in self._qualified_moves.get(child_name, []):
                    if qualifiers <= {var}:
                        moved_in |= values
                for v in moved_in:
                    name = v[:_SSA_SEGMENT_NAME_LEN].rstrip()
                    if name:
                        candidates.add(name)
                if candidates:
                    ordered = sorted(candidates)
                    return "/".join(ordered) if len(ordered) > 1 else ordered[0]

            # Elementary item: VALUE clause holds the whole SSA; take first 8 bytes
            if item.value_clause is not None:
                raw = str(item.value_clause).strip("\"'")
                return raw[:_SSA_SEGMENT_NAME_LEN].rstrip() or None

        # Fall back to MOVE-tracked values (dynamic assignment). Mirrors
        # `_resolve_func_code`'s handling of a multi-valued variable: report
        # every candidate rather than silently picking one, so a variable
        # set to different segment names on different branches doesn't read
        # as a single certain answer.
        if var in self._variable_values:
            moved = sorted(
                {
                    v[:_SSA_SEGMENT_NAME_LEN].rstrip()
                    for v in self._variable_values[var]
                    if v[:_SSA_SEGMENT_NAME_LEN].rstrip()
                }
            )
            if moved:
                return "/".join(moved) if len(moved) > 1 else moved[0]

        return None


# ── Module-level helpers ──────────────────────────────────────────────────────

# Figurative constants and their resolved literal values
_FIGURATIVE_CONSTANTS: dict[str, str] = {
    "ZERO": "0",
    "ZEROS": "0",
    "ZEROES": "0",
    "SPACE": " ",
    "SPACES": " ",
    "LOW-VALUE": "\x00",
    "LOW-VALUES": "\x00",
    "HIGH-VALUE": "\xff",
    "HIGH-VALUES": "\xff",
}


def _strip_quotes(value: str) -> str:
    """Remove surrounding single or double quotes from *value*.

    Returns the original string unchanged if it is not quoted.
    """
    s = value.strip()
    if len(s) >= 2 and (
        (s.startswith("'") and s.endswith("'"))
        or (s.startswith('"') and s.endswith('"'))
    ):
        return s[1:-1]
    return s


def _extract_literal(source: str) -> str | None:
    """Return the literal value for genuine literals only; ``None`` for identifiers.

    Recognises:
    * Quoted strings (single or double quotes) – the COBOL MOVE parser retains
      quotes on string literals, so ``MOVE 'X' TO Y`` yields ``source='"X"'``.
    * Figurative constants (``ZERO``, ``SPACE``, ``LOW-VALUE``, …).
    * Numeric literals (optionally signed, with optional decimal point).

    Bare identifiers (e.g. ``WS-SEG-NAME``) return ``None`` so that unresolved
    variable references are never silently recorded as segment-name candidates.
    """
    if not source:
        return None
    s = source.strip()

    # Quoted string
    if len(s) >= 2 and (
        (s.startswith("'") and s.endswith("'"))
        or (s.startswith('"') and s.endswith('"'))
    ):
        return s[1:-1]

    # Figurative constant
    upper = s.upper()
    if upper in _FIGURATIVE_CONSTANTS:
        return _FIGURATIVE_CONSTANTS[upper]

    # Numeric literal  (digits only, optional leading sign, optional decimal)
    core = s.lstrip("+-")
    if core.replace(".", "", 1).isdigit():
        return s

    # Bare identifier – value unknown
    return None
