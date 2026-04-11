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

from dataclasses import dataclass, field

from ..models.ast_base import ASTNode, SourceLocation
from ..models.data_items import CobolDataItem
from ..models.program import CobolProgram
from ..models.statements import CallStatement, MoveStatement

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
            if src_key in self._variable_values:
                # Propagate known values from source variable to targets
                src_values = self._variable_values[src_key]
                for tgt in node.targets:
                    self._variable_values.setdefault(tgt.upper(), set()).update(
                        src_values
                    )
            else:
                # Treat source as a literal (may or may not be quoted)
                literal = _strip_quotes(node.source)
                if literal is not None:
                    for tgt in node.targets:
                        self._variable_values.setdefault(tgt.upper(), set()).add(
                            literal
                        )

        if hasattr(node, "children"):
            for child in node.children:
                self._track_move_statements(child)

    # ── Pass 3: build IMSDLICall results ─────────────────────────────────────

    def _build_dli_calls(self, ast: CobolProgram) -> list[IMSDLICall]:
        results: list[IMSDLICall] = []
        for stmt in ast.get_ims_interface_calls():
            if not isinstance(stmt, CallStatement):
                # Bare CobolStatement stubs (e.g. from unit-test fixtures) are
                # skipped; only fully-parsed CallStatement nodes are processed.
                continue

            params = stmt.using_parameters
            func_var = params[_PARAM_FUNC_CODE].name if len(params) > _PARAM_FUNC_CODE else None
            pcb_name = params[_PARAM_PCB].name if len(params) > _PARAM_PCB else None
            io_area = params[_PARAM_IO_AREA].name if len(params) > _PARAM_IO_AREA else None
            ssa_names = [p.name for p in params[_PARAM_SSA_START:]]

            results.append(
                IMSDLICall(
                    location=stmt.location,
                    interface=(_strip_quotes(stmt.called_program or "") or "").upper(),
                    function_code=self._resolve_func_code(func_var),
                    function_code_var=func_var,
                    pcb_name=pcb_name,
                    io_area_name=io_area,
                    ssa_names=ssa_names,
                    segment_names=[self._resolve_ssa_segment(n) for n in ssa_names],
                )
            )
        return results

    # ── Resolution helpers ───────────────────────────────────────────────────

    def _resolve_func_code(self, var_name: str | None) -> str | None:
        """Resolve a function-code variable/literal to an IMS verb like ``"GU"``."""
        if not var_name:
            return None
        # Quoted inline literal (unusual but valid)
        lit = _strip_quotes(var_name)
        if lit != var_name:  # quotes were present
            return lit.strip().upper() or None
        var = var_name.upper()
        if var in self._variable_values:
            candidates = {v.strip().upper() for v in self._variable_values[var]}
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
            # Group item: segment name is in the VALUE clause of the first child
            data_children = [c for c in item.children if isinstance(c, CobolDataItem)]
            if data_children and data_children[0].value_clause is not None:
                raw = str(data_children[0].value_clause).strip("\"'")
                return raw[:_SSA_SEGMENT_NAME_LEN].rstrip() or None

            # Elementary item: VALUE clause holds the whole SSA; take first 8 bytes
            if item.value_clause is not None:
                raw = str(item.value_clause).strip("\"'")
                return raw[:_SSA_SEGMENT_NAME_LEN].rstrip() or None

        # Fall back to MOVE-tracked values (dynamic assignment)
        if var in self._variable_values:
            candidates = sorted(self._variable_values[var])
            if candidates:
                return candidates[0][:_SSA_SEGMENT_NAME_LEN].rstrip() or None

        return None


# ── Module-level helper ───────────────────────────────────────────────────────


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
