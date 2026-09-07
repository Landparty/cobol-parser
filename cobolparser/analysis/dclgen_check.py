"""DCLGEN ``DECLARE TABLE`` vs. COBOL host variable type checking.

DB2's DCLGEN utility emits two things from one table: an ``EXEC SQL DECLARE
… TABLE`` block describing the columns, and a COBOL ``01`` structure whose
fields are the host variables a program binds them to.  They agree the day
they are generated.  They stop agreeing the moment somebody ALTERs the
column, hand-edits the copybook, or copies a structure from a table with a
similar-looking column -- and the precompiler will happily accept most of it,
because DB2 *converts* rather than refuses.  What comes out is a class of bug
that survives every unit test and shows up in production as a truncated key,
a silently rescaled amount, or a value that is off by a factor of a hundred.

This module is the check nobody runs, and it is nearly free here because
both halves are already parsed: :class:`~.host_var_resolver.HostVariableResolver`
pairs every ``:host-var`` with its DATA DIVISION item *and* with the DCLGEN
column of the same name.  All that is left is to say whether the pair agrees.

What it reports, and why each one is a real bug rather than a style note:

``category``
    A ``CHAR`` column bound to a numeric item, or a ``DECIMAL`` column bound
    to a ``PIC X``.  DB2 rejects some of these outright and converts others;
    either way the program does not mean what it says.
``scale``
    ``DECIMAL(9,2)`` into ``PIC S9(7)V9`` -- the cents are quietly rounded
    away on every fetch, and no status code says so.  The single most
    expensive mismatch in the list.
``precision``
    Not enough integer digits for the column's range: the value overflows,
    and DB2 signals SQLCODE -304 only when a row actually exceeds it, which
    is to say in production rather than in test.
``length``
    ``CHAR(30)`` into ``PIC X(20)``: every fetch truncates, and every insert
    pads.  Shorter-than-declared is an error; longer is reported as info,
    since it wastes space but loses nothing.
``usage``
    The column's natural COBOL storage (``COMP-3`` for ``DECIMAL``, ``COMP``
    for the integer types) against what the item actually declares.  A
    warning: DB2 converts, so it works, but every row pays for the
    conversion and DCLGEN would never have written it that way.
``sign``
    An unsigned host variable bound to a signed column.  A negative value
    arrives with its sign dropped -- an absolute value silently substituted
    for the real one.
``null-indicator``
    A nullable column fetched into a host variable with no indicator
    variable.  DB2 raises SQLCODE -305 at runtime the first time the column
    is actually null, which is typically long after the code ships.

Nothing here re-implements type mapping: the expected PICTURE and USAGE come
from :func:`~..models.sql_statements.db2_type_to_cobol_pic` and
:func:`~..models.sql_statements.db2_type_to_cobol_usage`, the same functions
DCLGEN's own mapping is modelled by elsewhere in this package, so a fix to
the mapping fixes the check too.

Typical usage::

    from cobolparser import parse_cobol
    from cobolparser.analysis import DclgenChecker

    report = DclgenChecker().check(parse_cobol(source).ast)
    for violation in report.violations:
        print(violation.severity, violation.message)
    report.unchecked   # host variables no DECLARE TABLE could speak for
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from ..models.data_items import CobolDataItem, PictureClause
from ..models.program import CobolProgram
from ..models.sql_statements import DB2ColumnDefinition, ExecSQLStatement
from .host_var_resolver import HostVariableResolver

#: Severity ordering, shared with :mod:`.lint` so a DCLGEN finding grades on
#: the same scale as every other rule.
SEVERITY_ERROR = "error"
SEVERITY_WARNING = "warning"
SEVERITY_INFO = "info"

#: ``:HOST-VAR:INDICATOR`` and ``:HOST-VAR INDICATOR :IND`` -- the two ways
#: SQL attaches a null indicator to a host variable.  Matched against the
#: statement's own text because :class:`~..models.sql_statements.ExecSQLStatement`
#: keeps the indicator *names* but not which variable each belongs to.
_INDICATOR_RE = re.compile(
    # The separator has to carry the whole burden of telling the two forms
    # apart, so the whitespace between name and separator is matched once,
    # before the alternation -- putting it inside the INDICATOR branch would
    # leave that branch with no space left to match.
    r":\s*([A-Za-z_][\w-]*)\s*(?::|\bINDICATOR\b\s*:)\s*[A-Za-z_][\w-]*",
    re.IGNORECASE,
)

#: DB2 types whose COBOL binding is a group item (a length halfword plus the
#: text), so a comparison against a single elementary PICTURE would be
#: comparing the wrong things.
_GROUP_BOUND_TYPES = frozenset({"VARCHAR", "CLOB", "VARGRAPHIC"})

#: DB2 types the resolver has no PICTURE for -- nothing to compare, and
#: saying so beats inventing a rule.
_OPAQUE_TYPES = frozenset({"BLOB", "BINARY", "VARBINARY", "ROWID", "XML"})


@dataclass
class DclgenViolation:
    """One disagreement between a DB2 column and its COBOL host variable.

    Attributes:
        kind: Which check failed -- ``category``, ``scale``, ``precision``,
            ``length``, ``usage``, ``sign`` or ``null-indicator``.
        severity: ``error``, ``warning`` or ``info``, graded by what the
            mismatch costs at runtime (see the module docstring).
        host_variable: Upper-cased host variable name, as it appears after
            the colon in SQL.
        column: The DB2 column it was matched to, by name.
        table: The ``DECLARE TABLE`` the column came from.
        message: One sentence naming both sides and the consequence.
        expected_picture: The PICTURE DCLGEN would have generated.
        expected_usage: The USAGE DCLGEN would have generated.
        actual_picture: What the DATA DIVISION item actually declares.
        actual_usage: Likewise for USAGE.
        location: Where the host variable is declared, when the item carries
            a source location.
    """

    kind: str
    severity: str
    host_variable: str
    column: str
    table: str | None
    message: str
    expected_picture: str | None = None
    expected_usage: str | None = None
    actual_picture: str | None = None
    actual_usage: str | None = None
    location: Any | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialise the violation."""
        return {
            "kind": self.kind,
            "severity": self.severity,
            "host_variable": self.host_variable,
            "column": self.column,
            "table": self.table,
            "message": self.message,
            "expected_picture": self.expected_picture,
            "expected_usage": self.expected_usage,
            "actual_picture": self.actual_picture,
            "actual_usage": self.actual_usage,
            "location": (
                {"line": self.location.line, "column": self.location.column}
                if self.location is not None
                else None
            ),
        }


@dataclass
class DclgenReport:
    """Everything one DCLGEN cross-check found, and everything it could not.

    Attributes:
        violations: The disagreements, in source order where a location is
            known and by name otherwise.
        checked: Host variables that had both a DATA DIVISION item and a
            DCLGEN column, and were therefore actually compared.
        unchecked: ``name: reason`` for every host variable that could not
            be compared -- no ``DECLARE TABLE`` names a column of that name,
            the column's type has no COBOL equivalent, or the binding is a
            group item.  Reported so a clean report is never mistaken for a
            checked one.
        tables: The ``DECLARE TABLE`` blocks found, with their column counts.
        ambiguous_columns: ``column: [tables]`` where the same column name is
            declared by more than one table.  The comparison uses the first
            table declaring it, which may be the wrong one -- said out loud
            rather than assumed away.
    """

    violations: list[DclgenViolation] = field(default_factory=list)
    checked: list[str] = field(default_factory=list)
    unchecked: dict[str, str] = field(default_factory=dict)
    tables: dict[str, int] = field(default_factory=dict)
    ambiguous_columns: dict[str, list[str]] = field(default_factory=dict)

    @property
    def has_violations(self) -> bool:
        """True when anything at all disagreed."""
        return bool(self.violations)

    def worst_severity(self) -> str | None:
        """The highest severity present, or ``None`` for a clean report."""
        for severity in (SEVERITY_ERROR, SEVERITY_WARNING, SEVERITY_INFO):
            if any(v.severity == severity for v in self.violations):
                return severity
        return None

    def to_dict(self) -> dict[str, Any]:
        """Serialise the report (backs ``dclgen-check``'s JSON output)."""
        return {
            "violation_count": len(self.violations),
            "checked_count": len(self.checked),
            "unchecked_count": len(self.unchecked),
            "worst_severity": self.worst_severity(),
            "tables": dict(self.tables),
            "violations": [v.to_dict() for v in self.violations],
            "checked": list(self.checked),
            "unchecked": dict(self.unchecked),
            "ambiguous_columns": {
                k: list(v) for k, v in self.ambiguous_columns.items()
            },
        }


class DclgenChecker:
    """Compares every host variable against the DCLGEN column of its name.

    Runs :class:`~.host_var_resolver.HostVariableResolver` once and grades
    the pairs it produced; it resolves nothing itself, so a change to how
    host variables are matched to columns changes both at once.
    """

    def check(self, ast: CobolProgram) -> DclgenReport:
        """Cross-check *ast*'s host variables against its DECLARE TABLEs."""
        resolution = HostVariableResolver().resolve(ast)
        report = DclgenReport(
            tables={
                name: len(table.columns)
                for name, table in resolution.declare_tables.items()
            },
        )
        columns = _column_index(resolution)
        report.ambiguous_columns = {
            name: sorted({table for table, _ in bindings})
            for name, bindings in columns.items()
            if len({table for table, _ in bindings}) > 1
        }
        names = sorted(set(resolution.resolved) | set(resolution.unresolved))
        if not resolution.declare_tables:
            # Nothing to check against. Said as a caveat rather than as a
            # clean bill of health: a program with no DECLARE TABLE has not
            # been checked, it has merely not been checkable.
            for name in names:
                report.unchecked[name] = "no DECLARE TABLE in this program"
            return report

        indicators = _indicator_bindings(ast)
        for name in names:
            info = resolution.resolved.get(name)
            item = info.data_item if info is not None else None
            binding = columns.get(_normalize(name))
            if binding is None:
                report.unchecked[name] = (
                    "no DECLARE TABLE declares a column of this name"
                )
                continue
            table, column = binding[0]
            if item is None:
                report.unchecked[name] = (
                    "no DATA DIVISION item declares this host variable"
                )
                continue
            reason = _unsupported(column)
            if reason is not None:
                report.unchecked[name] = reason
                continue
            report.checked.append(name)
            report.violations.extend(
                _compare(name, item, column, table, has_indicator=name in indicators)
            )
        report.violations.sort(key=_violation_order)
        return report


# ---------------------------------------------------------------------------
# The comparisons
# ---------------------------------------------------------------------------


def _compare(
    name: str,
    item: CobolDataItem,
    column: DB2ColumnDefinition,
    table: str | None,
    *,
    has_indicator: bool,
) -> list[DclgenViolation]:
    """Grade one host variable against one column."""
    picture = item.picture_clause
    actual_usage = (item.usage or "DISPLAY").upper()
    expected_usage = (column.cobol_usage or "DISPLAY").upper()
    common: dict[str, Any] = {
        "host_variable": name,
        "column": column.name,
        "table": table,
        "expected_picture": column.cobol_picture,
        "expected_usage": column.cobol_usage,
        "actual_picture": picture.pattern if picture else None,
        "actual_usage": actual_usage,
        "location": item.location,
    }
    out: list[DclgenViolation] = []

    if picture is None:
        # A group item, or a USAGE-only item (COMP-1/COMP-2, POINTER). The
        # first is how VARCHAR binds and is filtered out earlier; anything
        # else reaching here has no PICTURE to compare, so only the usage
        # check applies.
        if actual_usage != expected_usage:
            out.append(
                DclgenViolation(
                    kind="usage",
                    severity=SEVERITY_WARNING,
                    message=(
                        f":{name} is USAGE {actual_usage} but column "
                        f"{column.name} ({column.db2_type}) binds to "
                        f"{expected_usage}; DB2 converts every row"
                    ),
                    **common,
                )
            )
        return out

    column_numeric = expected_usage in ("COMP", "COMP-3", "COMP-1", "COMP-2") or (
        column.precision is not None
    )
    item_numeric = _is_numeric(picture)

    if column_numeric != item_numeric:
        kinds = (
            ("numeric", "alphanumeric") if column_numeric else ("character", "numeric")
        )
        out.append(
            DclgenViolation(
                kind="category",
                severity=SEVERITY_ERROR,
                message=(
                    f":{name} is {kinds[1]} (PIC {picture.pattern}) but column "
                    f"{column.name} is {kinds[0]} ({column.db2_type}); the "
                    "binding does not mean what it says"
                ),
                **common,
            )
        )
        # Every later check compares digits against characters or vice
        # versa, so it would only restate this one in a more confusing way.
        return out

    if column_numeric:
        out.extend(_compare_numeric(name, picture, column, common))
    else:
        out.extend(_compare_character(name, picture, column, common))

    if actual_usage != expected_usage:
        out.append(
            DclgenViolation(
                kind="usage",
                severity=SEVERITY_WARNING,
                message=(
                    f":{name} is USAGE {actual_usage} but DCLGEN generates "
                    f"{expected_usage} for {column.db2_type}; DB2 converts "
                    "every row rather than moving it"
                ),
                **common,
            )
        )

    if column.nullable and not has_indicator:
        out.append(
            DclgenViolation(
                kind="null-indicator",
                severity=SEVERITY_WARNING,
                message=(
                    f"column {column.name} is nullable but :{name} is used "
                    "with no indicator variable; DB2 raises SQLCODE -305 the "
                    "first time the column is actually null"
                ),
                **common,
            )
        )
    return out


def _compare_numeric(
    name: str,
    picture: PictureClause,
    column: DB2ColumnDefinition,
    common: dict[str, Any],
) -> list[DclgenViolation]:
    """Scale, precision and sign, for a numeric column."""
    out: list[DclgenViolation] = []
    expected = PictureClause(column.cobol_picture or "", picture.location)
    expected_scale = (
        column.scale if column.scale is not None else (expected.decimal_digits or 0)
    )
    actual_scale = picture.decimal_digits or 0
    if expected_scale != actual_scale:
        out.append(
            DclgenViolation(
                kind="scale",
                severity=SEVERITY_ERROR,
                message=(
                    f":{name} has {actual_scale} decimal place(s) but column "
                    f"{column.name} has {expected_scale}; every value is "
                    "silently rescaled"
                ),
                **common,
            )
        )

    expected_integer = _integer_digits(expected, column, expected_scale)
    actual_integer = _integer_digits(picture, None, actual_scale)
    if expected_integer > actual_integer:
        out.append(
            DclgenViolation(
                kind="precision",
                severity=SEVERITY_ERROR,
                message=(
                    f":{name} holds {actual_integer} integer digit(s) but "
                    f"column {column.name} holds {expected_integer}; a large "
                    "value overflows (SQLCODE -304)"
                ),
                **common,
            )
        )

    if not picture.is_signed:
        out.append(
            DclgenViolation(
                kind="sign",
                severity=SEVERITY_WARNING,
                message=(
                    f":{name} is unsigned (PIC {picture.pattern}) but every "
                    f"DB2 numeric column is signed; a negative "
                    f"{column.name} arrives as its absolute value"
                ),
                **common,
            )
        )
    return out


def _compare_character(
    name: str,
    picture: PictureClause,
    column: DB2ColumnDefinition,
    common: dict[str, Any],
) -> list[DclgenViolation]:
    """Length, for a character column."""
    declared = column.length
    if declared is None:
        expected = PictureClause(column.cobol_picture or "", picture.location)
        declared = expected.size
    actual = picture.size
    if declared is None or actual is None or declared == actual:
        return []
    if actual < declared:
        return [
            DclgenViolation(
                kind="length",
                severity=SEVERITY_ERROR,
                message=(
                    f":{name} is {actual} characters but column "
                    f"{column.name} is {declared}; every fetch truncates"
                ),
                **common,
            )
        ]
    return [
        DclgenViolation(
            kind="length",
            severity=SEVERITY_INFO,
            message=(
                f":{name} is {actual} characters where column "
                f"{column.name} is {declared}; the extra positions are "
                "always blank"
            ),
            **common,
        )
    ]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _is_numeric(picture: PictureClause) -> bool:
    """Whether a PICTURE holds a number rather than characters."""
    if picture.is_numeric_edited:
        return True
    if picture.is_alphanumeric_edited:
        return False
    pattern = re.sub(r"\(\d+\)", "", (picture.pattern or "").upper())
    symbols = set(pattern)
    return "9" in symbols and not symbols & {"X", "A", "N"}


def _integer_digits(
    picture: PictureClause, column: DB2ColumnDefinition | None, scale: int
) -> int:
    """Digit positions left of the (implied) decimal point.

    A column's own ``precision`` wins where it has one: ``DECIMAL(9,2)`` is
    nine digits total whatever PICTURE the mapping chose to express it with.
    """
    if column is not None and column.precision is not None:
        return max(0, column.precision - scale)
    if picture.integer_digits is not None:
        return max(0, picture.integer_digits)
    total = picture.total_digits or 0
    return max(0, total - scale)


def _unsupported(column: DB2ColumnDefinition) -> str | None:
    """Why this column cannot be compared, or ``None`` when it can."""
    upper = column.db2_type.upper()
    if upper in _OPAQUE_TYPES:
        return f"{column.db2_type} has no COBOL PICTURE to compare against"
    if upper in _GROUP_BOUND_TYPES:
        return (
            f"{column.db2_type} binds to a group item (a length halfword plus "
            "the text), which this check does not compare field by field"
        )
    if column.cobol_picture is None:
        return f"no COBOL PICTURE is known for DB2 type {column.db2_type}"
    return None


def _normalize(name: str) -> str:
    """A name in the form both sides can be compared in.

    DB2 column names are underscored (``CUST_ID``); the COBOL host variables
    DCLGEN generates for them are hyphenated (``CUST-ID``), because ``_`` is
    not a COBOL data-name character.  DCLGEN does that substitution itself,
    so a checker that compared the two verbatim would report that no column
    matches *any* host variable -- which is to say, it would check nothing
    while looking like it had.
    """
    return name.strip().upper().replace("_", "-")


def _column_index(resolution: Any) -> dict[str, list[tuple[str, DB2ColumnDefinition]]]:
    """Every DCLGEN column, keyed the way a host variable names it.

    The value is a list because two tables may declare the same column name;
    the first declaration wins the comparison (matching
    :class:`~.host_var_resolver.HostVariableResolver`'s own rule) and the
    rest are reported as :attr:`DclgenReport.ambiguous_columns`.
    """
    index: dict[str, list[tuple[str, DB2ColumnDefinition]]] = {}
    for table_name, table in resolution.declare_tables.items():
        for column in table.columns:
            index.setdefault(_normalize(column.name), []).append(
                (str(table_name), column)
            )
    return index


def _indicator_bindings(node: Any) -> set[str]:
    """Host variables that carry a null indicator somewhere in the program.

    Program-wide rather than per-statement: a variable given an indicator on
    its ``FETCH`` and not on its ``SELECT INTO`` is a different (and much
    rarer) bug than never having one at all, and flagging the second
    statement would bury the finding that matters under a false one.
    """
    found: set[str] = set()
    if isinstance(node, ExecSQLStatement):
        for match in _INDICATOR_RE.finditer(node.sql_text or ""):
            found.add(match.group(1).upper())
    for child in getattr(node, "children", []):
        found |= _indicator_bindings(child)
    return found


def _violation_order(violation: DclgenViolation) -> tuple[int, int, str, str]:
    """Source order where known, then by variable, so output is stable."""
    location = violation.location
    line = getattr(location, "line", 0) or 0
    column = getattr(location, "column", 0) or 0
    return (line, column, violation.host_variable, violation.kind)
