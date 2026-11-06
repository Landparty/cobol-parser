"""
Checks IBM Enterprise COBOL's compiler makes, run before the compile.

The compiler (``IGY`` messages) rejects or warns about a set of mistakes it
can see in the program text alone: a name nobody declared, a VALUE that does
not fit its PICTURE, a comparison that can never be true, a SEARCH on a
table with no index, a literal division by zero, a subscript count that does
not match the table. Lint reports them first, so a developer sees them in
the editor or the CI gate instead of in the compile listing of a mainframe
job. The severity mirrors the compiler's: what it rejects (severity S or E)
is an ``error``, what it accepts with a warning is a ``warning``, and its
informational messages are ``info``. Message numbers differ between
compiler releases, so the findings name the problem rather than an ``IGY``
number.

Like every rule in this package these are **exact by construction, or
absent**: an operand that cannot be resolved (declared twice, a variable
subscript, an item whose length is unknown, a program with a COPY member
the parse could not expand) is skipped, never guessed at.

Rules (rule id, ``kind``, severity):

- ``undefined-name``
    - ``DATA_NAME_UNDEFINED`` (error): a data name used in the PROCEDURE
      DIVISION that nothing declares.
    - ``PROCEDURE_NAME_UNDEFINED`` (error): a PERFORM or GO TO of a
      paragraph or section the program does not have.
    - ``FILE_NAME_UNDEFINED`` (error): an OPEN / READ / WRITE / CLOSE of a
      file with no SELECT.
    The rule stays quiet (with a caveat) for a program with a COPY member
    that was not expanded, an EXEC SQL INCLUDE it could not read (other than
    SQLCA / SQLDA), or a SCREEN, REPORT or COMMUNICATION SECTION, whose names
    the cross-reference does not declare.
- ``value-clause``
    - ``VALUE_WRONG_CATEGORY`` (error): a quoted literal, SPACES, QUOTES,
      HIGH-VALUES or LOW-VALUES as the VALUE of a numeric item.
    - ``VALUE_QUOTED_NUMBER`` (warning): a quoted number (``VALUE '000'``)
      for a numeric item; the standard wants it unquoted.
    - ``VALUE_NUMERIC_FOR_ALPHANUMERIC`` (warning): a numeric literal as the
      VALUE of an alphanumeric item (the standard wants a quoted literal).
    - ``VALUE_TOO_LONG`` (warning): a quoted VALUE longer than the item; the
      compiler truncates it.
    - ``VALUE_TOO_MANY_DIGITS`` (warning): a numeric VALUE with more integer
      digits than the PICTURE holds; the high-order digits are lost.
    - ``VALUE_DECIMALS_LOST`` (warning): more decimal places than the
      PICTURE holds.
    - ``VALUE_SIGN_LOST`` (warning): a negative VALUE for an unsigned item.
    - ``VALUE_IGNORED`` (warning): a VALUE on an item in the FILE or LINKAGE
      SECTION, where it gives no initial value.
    - ``CONDITION_NEVER_TRUE`` (warning): a level-88 VALUE its conditional
      variable can never hold (too long, too many digits, negative for an
      unsigned item).
    - ``CONDITION_VALUE_WRONG_CATEGORY`` (error): a quoted level-88 VALUE on
      a numeric item.
- ``data-layout``
    - ``REDEFINES_LARGER`` (warning): below level 01, an item that REDEFINES
      a smaller one; the extra bytes overlay the fields that follow.
    - ``RECORD_CONTAINS_MISMATCH`` (warning): an FD's fixed ``RECORD
      CONTAINS n`` disagrees with the longest record description; the
      compiler uses the record descriptions.
- ``comparison``
    - ``COMPARISON_ALWAYS_FALSE`` / ``COMPARISON_ALWAYS_TRUE`` (warning): a
      numeric item compared with a literal it can never reach (``PIC 9(3)``
      against 5000, an unsigned item against a negative number or ``< 0``),
      or an alphanumeric item compared for equality with a longer literal.
    - ``COMPARISON_NONNUMERIC_LITERAL`` (warning): a numeric item compared
      with a quoted literal that is not a number; the comparison is made
      character by character and is never equal to a valid value.
- ``search-table``
    - ``SEARCH_NOT_A_TABLE`` (error), ``SEARCH_NO_INDEX`` (error): SEARCH on
      an item without OCCURS, or on a table with no INDEXED BY.
    - ``SEARCH_ALL_NO_KEY`` (error): SEARCH ALL on a table with no
      ASCENDING / DESCENDING KEY.
- ``divide-by-zero``
    - ``DIVIDE_BY_ZERO`` (error): DIVIDE by the literal zero, or a COMPUTE
      that divides by it.
- ``subscript-usage``
    - ``SUBSCRIPT_COUNT`` (error): a table element with more or fewer
      subscripts than its OCCURS levels.
    - ``SUBSCRIPT_MISSING`` (error): a table element used with no subscript.
    - ``SUBSCRIPT_NOT_A_TABLE`` (error): a subscript on an item that is not
      in a table.
    - ``REFMOD_OUT_OF_RANGE`` (error): a literal reference modification
      ``(start:length)`` that starts or ends outside the item.
- ``procedure-structure``
    - ``EMPTY_PARAGRAPH`` (info): a paragraph with no statements.
    - ``DUPLICATE_PARAGRAPH``: two paragraphs of one name in one section (or
      both outside sections). An error when the program refers to the name
      without a qualifier, since the compiler cannot tell which is meant; a
      warning otherwise.
- ``corresponding``
    - ``NO_CORRESPONDING_ITEMS`` (warning): MOVE / ADD / SUBTRACT
      CORRESPONDING between groups with no subordinate names in common; the
      statement does nothing.
- ``arithmetic-operand``
    - ``NONNUMERIC_ARITHMETIC_OPERAND`` (error): an alphanumeric or group
      item as an operand of ADD, SUBTRACT, MULTIPLY, DIVIDE or COMPUTE.
    - ``NONNUMERIC_ARITHMETIC_RECEIVER`` (error): an alphanumeric or group
      item receiving an arithmetic result (a numeric-edited item may receive
      a GIVING result).
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Iterator
from typing import Any

from .._literals import QUOTED_LITERAL_RE
from ..models.data_items import CobolDataItem, ConditionNameItem
from ..models.program import CobolProgram, CobolSection
from ..models.statements.arithmetic import (
    AddStatement,
    ComputeStatement,
    DivideStatement,
    MultiplyStatement,
    SubtractStatement,
)
from ..models.statements.base import (
    CobolExpression,
    CobolStatement,
    ConditionalExpression,
)
from ..models.statements.control import SearchStatement
from ..models.statements.data import MoveStatement
from .bug_patterns import (
    _FIGURATIVE,
    BugFinding,
    _all_paragraphs,
    _Context,
    _is_elementary,
    _parse_operand,
    _section_of,
)
from .program_flow import ProgramFlowReport

#: Every rule this module runs, in report order.
COMPILER_RULES: tuple[str, ...] = (
    "undefined-name",
    "value-clause",
    "data-layout",
    "comparison",
    "search-table",
    "divide-by-zero",
    "subscript-usage",
    "procedure-structure",
    "corresponding",
    "arithmetic-operand",
)

#: One-line description per rule (SARIF ``shortDescription``).
COMPILER_RULE_DESCRIPTIONS: dict[str, str] = {
    "undefined-name": "Data, procedure or file name that nothing declares",
    "value-clause": "VALUE clause that does not fit its item's PICTURE",
    "data-layout": "REDEFINES larger than the item it redefines, or RECORD "
    "CONTAINS that disagrees with the record",
    "comparison": "Comparison that can never be true (or never false)",
    "search-table": "SEARCH on a table without INDEXED BY or KEY",
    "divide-by-zero": "Division by the literal zero",
    "subscript-usage": "Wrong number of subscripts, or a reference "
    "modification outside the item",
    "procedure-structure": "Empty or duplicated paragraph",
    "corresponding": "CORRESPONDING with no names in common",
    "arithmetic-operand": "Alphanumeric or group item in arithmetic",
}

_SEVERITY: dict[str, str] = {
    "DATA_NAME_UNDEFINED": "error",
    "PROCEDURE_NAME_UNDEFINED": "error",
    "FILE_NAME_UNDEFINED": "error",
    "VALUE_WRONG_CATEGORY": "error",
    "VALUE_NUMERIC_FOR_ALPHANUMERIC": "warning",
    "VALUE_QUOTED_NUMBER": "warning",
    "VALUE_TOO_LONG": "warning",
    "VALUE_TOO_MANY_DIGITS": "warning",
    "VALUE_DECIMALS_LOST": "warning",
    "VALUE_SIGN_LOST": "warning",
    "VALUE_IGNORED": "warning",
    "CONDITION_NEVER_TRUE": "warning",
    "CONDITION_VALUE_WRONG_CATEGORY": "error",
    "REDEFINES_LARGER": "warning",
    "RECORD_CONTAINS_MISMATCH": "warning",
    "COMPARISON_ALWAYS_FALSE": "warning",
    "COMPARISON_ALWAYS_TRUE": "warning",
    "COMPARISON_NONNUMERIC_LITERAL": "warning",
    "SEARCH_NOT_A_TABLE": "error",
    "SEARCH_NO_INDEX": "error",
    "SEARCH_ALL_NO_KEY": "error",
    "DIVIDE_BY_ZERO": "error",
    "SUBSCRIPT_COUNT": "error",
    "SUBSCRIPT_MISSING": "error",
    "SUBSCRIPT_NOT_A_TABLE": "error",
    "REFMOD_OUT_OF_RANGE": "error",
    "EMPTY_PARAGRAPH": "info",
    "DUPLICATE_PARAGRAPH": "warning",
    "NO_CORRESPONDING_ITEMS": "warning",
    "NONNUMERIC_ARITHMETIC_OPERAND": "error",
    "NONNUMERIC_ARITHMETIC_RECEIVER": "error",
}

#: Usages whose PICTURE does not bound the value the item holds at run time
#: (binary under TRUNC(BIN), COMP-5) or that have no PICTURE digits at all.
_BINARY_USAGES = frozenset(
    {"BINARY", "COMP", "COMPUTATIONAL", "COMP-4", "COMPUTATIONAL-4", "COMP-5"}
)
_NO_PICTURE_USAGES = frozenset(
    {
        "COMP-1",
        "COMP-2",
        "COMPUTATIONAL-1",
        "COMPUTATIONAL-2",
        "INDEX",
        "POINTER",
        "POINTER-32",
        "POINTER-64",
        "PROCEDURE-POINTER",
        "FUNCTION-POINTER",
        "OBJECT REFERENCE",
        "NATIONAL",
        "UTF-8",
        "DISPLAY-1",
    }
)
#: Figurative constants that are not numeric.
_NONNUMERIC_FIGURATIVES = frozenset(
    {
        "SPACE",
        "SPACES",
        "QUOTE",
        "QUOTES",
        "HIGH-VALUE",
        "HIGH-VALUES",
        "LOW-VALUE",
        "LOW-VALUES",
    }
)
#: Subfields of the DEBUG-ITEM special register (USE FOR DEBUGGING).
_DEBUG_ITEM_NAMES = frozenset(
    {
        "DEBUG-ITEM",
        "DEBUG-LINE",
        "DEBUG-NAME",
        "DEBUG-SUB-1",
        "DEBUG-SUB-2",
        "DEBUG-SUB-3",
        "DEBUG-CONTENTS",
    }
)
#: EXEC SQL INCLUDE members the precompiler supplies itself.
_PRECOMPILER_MEMBERS = frozenset({"SQLCA", "SQLDA"})
#: ``PERFORM FOREVER`` (GnuCOBOL / Micro Focus) is a loop, not a procedure.
_PERFORM_EXTENSIONS = frozenset({"FOREVER"})
#: Sections whose names the cross-reference does not declare.
_UNDECLARED_SECTIONS = frozenset({"SCREEN", "REPORT", "COMMUNICATION"})

_NUMERIC_LITERAL_RE = re.compile(r"^([+-]?)(\d*)(?:[.,](\d*))?$")
_QUOTED_RE = re.compile(r"""^(['"])(.*)\1$""", re.DOTALL)
_HEX_RE = re.compile(r"""^[Xx](['"])([0-9A-Fa-f]*)\1$""")
_ZERO_LITERAL_RE = re.compile(r"^[+]?0*(?:[.,]0*)?$")
_COMPUTE_DIVIDE_ZERO_RE = re.compile(r"/\s*\(?\s*[+]?0+(?:[.,]0*)?(?![\w.,])")
_NAME = r"[A-Za-z0-9][A-Za-z0-9-]*"
_WORD_RE = re.compile(rf"(?<![A-Za-z0-9-]){_NAME}(?![A-Za-z0-9-])")
_QUALIFIER_RE = re.compile(rf"\s+(?:OF|IN)\s+{_NAME}", re.IGNORECASE)
_QUALIFIER_BEFORE_RE = re.compile(r"(?<![A-Za-z0-9-])(?:OF|IN)\s+$", re.IGNORECASE)
#: Words after which a data name stands unsubscripted on purpose.
_UNSUBSCRIPTED_CONTEXT_RE = re.compile(
    r"(?:LENGTH|ADDRESS)\s+OF\s*$|FUNCTION\s+LENGTH\s*\(\s*$", re.IGNORECASE
)

_RELATIONS = frozenset(
    {"EQUAL", "NOT_EQUAL", "GREATER", "LESS", "GREATER_OR_EQUAL", "LESS_OR_EQUAL"}
)
_MIRROR = {
    "GREATER": "LESS",
    "LESS": "GREATER",
    "GREATER_OR_EQUAL": "LESS_OR_EQUAL",
    "LESS_OR_EQUAL": "GREATER_OR_EQUAL",
}
_RELATION_TEXT = {
    "EQUAL": "=",
    "NOT_EQUAL": "NOT =",
    "GREATER": ">",
    "LESS": "<",
    "GREATER_OR_EQUAL": ">=",
    "LESS_OR_EQUAL": "<=",
}


def _finding(
    rule: str, kind: str, message: str, location: Any, symbol: str | None = None
) -> BugFinding:
    return BugFinding(
        rule=rule,
        kind=kind,
        message=message,
        location=location,
        symbol=symbol,
        severity=_SEVERITY[kind],
    )


def _usage(item: CobolDataItem) -> str:
    return str(item.usage or "DISPLAY").upper()


def _numeric_picture(item: CobolDataItem) -> Any:
    """The PICTURE of a plain numeric item (not edited, no P scaling, a
    usage whose PICTURE bounds its value), else None."""
    clause = item.picture_clause
    if clause is None or not _is_elementary(item):
        return None
    if _usage(item) in _NO_PICTURE_USAGES:
        return None
    if clause.integer_digits is None or clause.is_edited or clause.has_scaling_factor:
        return None
    return clause


def _alphanumeric_size(item: CobolDataItem) -> int | None:
    """Character count of a plain alphanumeric / alphabetic item."""
    clause = item.picture_clause
    if clause is None or not _is_elementary(item) or clause.size is None:
        return None
    if clause.integer_digits is not None or clause.is_edited or clause.is_national:
        return None
    if _usage(item) not in ("DISPLAY",) or clause.utf8_characters is not None:
        return None
    return int(clause.size)


def _numeric_literal(text: str) -> tuple[bool, str, str] | None:
    """``(negative, integer digits, decimal digits)`` of a numeric literal,
    leading / trailing zeros stripped, or None."""
    match = _NUMERIC_LITERAL_RE.match(text.strip())
    if not match or not (match.group(2) or match.group(3)):
        return None
    return (
        match.group(1) == "-",
        (match.group(2) or "").lstrip("0"),
        (match.group(3) or "").rstrip("0"),
    )


def _quoted(text: str) -> str | None:
    """The characters of a quoted literal, or None for anything else."""
    match = _QUOTED_RE.match(text.strip())
    if not match:
        return None
    quote = match.group(1)
    return match.group(2).replace(quote * 2, quote)


def _literal_length(text: str) -> int | None:
    """Bytes a quoted or X'..' literal occupies, None for anything else."""
    inner = _quoted(text)
    if inner is not None:
        return len(inner)
    match = _HEX_RE.match(text.strip())
    if match and len(match.group(2)) % 2 == 0:
        return len(match.group(2)) // 2
    return None


def _layout_length(item: CobolDataItem) -> int | None:
    """Byte length of *item* (one occurrence), or None when unknown."""
    for node in [item, *_descendants(item)]:
        occurs = node.occurs_clause
        if occurs is not None and (occurs.depending_on or occurs.is_unbounded):
            return None
        if _usage(node) in ("NATIONAL", "UTF-8", "DISPLAY-1"):
            return None
    try:
        from ..generators.data.layout_offsets import compute_record_layout

        layout = compute_record_layout(item)
    except Exception:  # noqa: BLE001 - a length is optional
        return None
    if not layout or not isinstance(layout[0].byte_length, int):
        return None
    length = int(layout[0].byte_length)
    return length or None


def _descendants(item: CobolDataItem) -> Iterator[CobolDataItem]:
    for child in item.children:
        if isinstance(child, CobolDataItem):
            yield child
            yield from _descendants(child)


def _comparisons(value: Any, seen: set[int], depth: int = 0) -> Iterator[Any]:
    """Every relational ConditionalExpression reachable from *value*."""
    if depth > 12 or id(value) in seen:
        return
    if isinstance(value, ConditionalExpression):
        seen.add(id(value))
        if value.operator in _RELATIONS:
            yield value
    if isinstance(value, CobolExpression):
        seen.add(id(value))
        for attr in (
            "condition_tree",
            "left_condition",
            "right_condition",
            "left_operand",
            "right_operand",
        ):
            yield from _comparisons(getattr(value, attr, None), seen, depth + 1)
        for child in value.children:
            yield from _comparisons(child, seen, depth + 1)
    elif isinstance(value, dict):
        for item in value.values():
            yield from _comparisons(item, seen, depth + 1)
    elif isinstance(value, (list, tuple)):
        for item in value:
            if not isinstance(item, CobolStatement):
                yield from _comparisons(item, seen, depth + 1)
    elif hasattr(value, "condition_trees") and not isinstance(value, CobolStatement):
        yield from _comparisons(value.condition_trees, seen, depth + 1)


class CompilerCheckAnalyzer:
    """Run the compiler-check rules over one program unit.

    Usage::

        report = CompilerCheckAnalyzer().analyze(ast)
        report.findings   # list[BugFinding]
        report.caveats    # what a rule could not check

    Program-unit scoped like the other analyzers (lint visits every unit).
    """

    def __init__(self, rules: Iterable[str] | None = None) -> None:
        selected = list(COMPILER_RULES if rules is None else rules)
        unknown = set(selected) - set(COMPILER_RULES)
        if unknown:
            raise ValueError(f"unknown compiler-check rule(s): {sorted(unknown)}")
        self.rules = tuple(r for r in COMPILER_RULES if r in set(selected))

    def analyze(
        self, ast: CobolProgram, *, flow_report: ProgramFlowReport | None = None
    ) -> CompilerCheckReport:
        checks = CompilerChecks(_Context(ast, flow_report))
        report = CompilerCheckReport()
        for rule in self.rules:
            report.findings.extend(checks.run(rule))
        report.caveats = list(dict.fromkeys(checks.caveats))
        return report


class CompilerCheckReport:
    """Findings plus what could not be checked."""

    def __init__(self) -> None:
        self.findings: list[BugFinding] = []
        self.caveats: list[str] = []

    def to_dict(self) -> dict[str, Any]:
        return {
            "findings": [f.to_dict() for f in self.findings],
            "caveats": list(self.caveats),
        }


class CompilerChecks:
    """The rules, over facts shared with :mod:`.bug_patterns`."""

    def __init__(self, context: _Context) -> None:
        self.context = context
        self.ast = context.ast
        self.caveats: list[str] = []

    def run(self, rule: str) -> list[BugFinding]:
        runners: dict[str, Callable[[], list[BugFinding]]] = {
            "undefined-name": self._undefined_name,
            "value-clause": self._value_clause,
            "data-layout": self._data_layout,
            "comparison": self._comparison,
            "search-table": self._search_table,
            "divide-by-zero": self._divide_by_zero,
            "subscript-usage": self._subscript_usage,
            "procedure-structure": self._procedure_structure,
            "corresponding": self._corresponding,
            "arithmetic-operand": self._arithmetic_operand,
        }
        data_rules = ("value-clause", "data-layout")
        if self.ast.procedure_division is None and rule not in data_rules:
            return []
        return runners[rule]()

    # -- helpers -------------------------------------------------------------

    def _item(self, text: Any) -> CobolDataItem | None:
        if not isinstance(text, str):
            return None
        operand = _parse_operand(text)
        if operand is None or operand.reference_modified:
            return None
        if operand.name in _FIGURATIVE or operand.name == "FUNCTION":
            return None
        return self.context.data.resolve(operand)

    def _section_names(self) -> set[str]:
        names: set[str] = set()
        division = self.ast.data_division
        for section in getattr(division, "sections", None) or []:
            name = str(getattr(section, "section_name", "") or "").upper()
            names.add(name.replace(" SECTION", "").strip())
        return names

    # -- undefined-name ------------------------------------------------------

    def _undefined_skip_reason(self) -> str | None:
        if self.ast.omitted_copy_lines:
            return "a COPY member was not expanded"
        for node in self.ast.traverse_depth_first():
            if type(node).__name__ == "ExecSQLStatement" and (
                str(getattr(node, "_sql_type", "") or "").upper() == "INCLUDE"
            ):
                member = str(getattr(node, "sql_text", "") or "").split()
                if len(member) > 1 and member[1].upper() not in _PRECOMPILER_MEMBERS:
                    return f"EXEC SQL INCLUDE {member[1]} was not expanded"
        special = self._section_names() & _UNDECLARED_SECTIONS
        if special:
            return f"the program has a {sorted(special)[0]} SECTION"
        return None

    def _undefined_name(self) -> list[BugFinding]:
        reason = self._undefined_skip_reason()
        if reason is not None:
            self.caveats.append(
                f"undefined-name skipped {self.ast.program_name or 'a program'}: "
                f"{reason}, so a missing declaration may be there"
            )
            return []
        xref = self.context.xref
        undefined = set(xref.undefined)
        files = _file_names(self.ast)
        outer = self._enclosing_names()
        division = self.ast.procedure_division
        first_line = division.location.line if division is not None else 0
        findings: list[BugFinding] = []
        for entry in xref.entries:
            if entry.definition is not None or entry.name not in undefined:
                continue
            name = entry.name.upper()
            if name in _DEBUG_ITEM_NAMES or name in outer:
                continue
            references = [
                r
                for r in entry.references
                if r.location and r.location.line >= first_line
            ]
            if not references:
                continue
            ref = references[0]
            procedure = entry.kind in ("paragraph", "section", "procedure")
            if procedure and name in _PERFORM_EXTENSIONS:
                continue
            if not procedure and entry.kind != "file" and name in files:
                continue  # a file name as a qualifier (``REC IN FILE-A``)
            if procedure:
                kind, what = "PROCEDURE_NAME_UNDEFINED", "paragraph or section"
            elif entry.kind == "file":
                kind, what = "FILE_NAME_UNDEFINED", "file (no SELECT)"
            else:
                kind, what = "DATA_NAME_UNDEFINED", "data item"
            more = len(references) - 1
            also = f" (and {more} more use(s))" if more else ""
            findings.append(
                _finding(
                    "undefined-name",
                    kind,
                    f"{entry.name} is not declared as a {what} anywhere in the "
                    f"program{also}; the compiler rejects the statement",
                    ref.location,
                    entry.name,
                )
            )
        return findings

    def _enclosing_names(self) -> set[str]:
        """Data and file names declared in the programs that contain this
        one: a contained program sees their GLOBAL items."""
        from .unused_variables import collect_declared_items

        names: set[str] = set()
        outer = self.ast.enclosing_program
        while outer is not None:
            names.update(i.name.upper() for i in collect_declared_items(outer))
            names.update(_file_names(outer))
            outer = outer.enclosing_program
        return names

    # -- value-clause --------------------------------------------------------

    def _value_clause(self) -> list[BugFinding]:
        findings: list[BugFinding] = []
        for item in self.context.data.items:
            findings.extend(self._item_value(item))
            for child in item.children:
                if isinstance(child, ConditionNameItem):
                    findings.extend(self._condition_values(item, child))
        return findings

    def _item_value(self, item: CobolDataItem) -> list[BugFinding]:
        value = item.value_clause
        if value is None or item.level in (66, 88):
            return []
        text = str(value).strip()
        section = _section_of(item)
        rule = "value-clause"
        if section in ("FILE", "LINKAGE"):
            return [
                _finding(
                    rule,
                    "VALUE_IGNORED",
                    f"VALUE on {item.name} in the {section} SECTION gives it no "
                    "initial value (only level-88 VALUEs mean something there)",
                    item.location,
                    item.name,
                )
            ]
        upper = text.upper()
        if upper.startswith("ALL ") or not _is_elementary(item):
            return []
        numeric = _numeric_picture(item)
        if numeric is not None:
            quoted = _quoted(text)
            if quoted is not None and re.fullmatch(r"[+-]?\d+(?:[.,]\d+)?", quoted):
                return [
                    _finding(
                        rule,
                        "VALUE_QUOTED_NUMBER",
                        f"VALUE {text} is a quoted literal for numeric item "
                        f"{item.name} (PIC {numeric.pattern}); the standard wants "
                        f"the number unquoted ({quoted})",
                        item.location,
                        item.name,
                    )
                ]
            if upper in _NONNUMERIC_FIGURATIVES or quoted is not None:
                return [
                    _finding(
                        rule,
                        "VALUE_WRONG_CATEGORY",
                        f"VALUE {text} is not numeric, but {item.name} is "
                        f"PIC {numeric.pattern}; the compiler rejects it",
                        item.location,
                        item.name,
                    )
                ]
            literal = _numeric_literal(text)
            if literal is None:
                return []
            return self._numeric_fit(rule, item, numeric, literal, text, condition=None)
        size = _alphanumeric_size(item)
        if size is None:
            return []
        if _numeric_literal(text) is not None:
            return [
                _finding(
                    rule,
                    "VALUE_NUMERIC_FOR_ALPHANUMERIC",
                    f"VALUE {text} is a numeric literal for alphanumeric item "
                    f"{item.name} (PIC {item.picture_clause.pattern}); write it "  # type: ignore[union-attr]
                    "as a quoted literal",
                    item.location,
                    item.name,
                )
            ]
        length = _literal_length(text)
        if length is not None and length > size:
            inner = _quoted(text)
            kept = f" ({inner[:size]!r} is kept)" if inner is not None else ""
            return [
                _finding(
                    rule,
                    "VALUE_TOO_LONG",
                    f"VALUE {text} is {length} characters but {item.name} holds "
                    f"{size}; it is truncated{kept}",
                    item.location,
                    item.name,
                )
            ]
        return []

    def _numeric_fit(
        self,
        rule: str,
        item: CobolDataItem,
        clause: Any,
        literal: tuple[bool, str, str],
        text: str,
        condition: ConditionNameItem | None,
    ) -> list[BugFinding]:
        negative, integer, decimal = literal
        binary5 = _usage(item) == "COMP-5"
        problems: list[tuple[str, str]] = []
        if len(integer) > int(clause.integer_digits) and not binary5:
            problems.append(
                (
                    "VALUE_TOO_MANY_DIGITS",
                    f"{len(integer)} integer digits, PIC {clause.pattern} holds "
                    f"{clause.integer_digits}",
                )
            )
        if len(decimal) > int(clause.decimal_digits or 0):
            problems.append(
                (
                    "VALUE_DECIMALS_LOST",
                    f"{len(decimal)} decimal places, PIC {clause.pattern} holds "
                    f"{clause.decimal_digits or 0}",
                )
            )
        if negative and not clause.is_signed and (integer or decimal):
            problems.append(("VALUE_SIGN_LOST", f"PIC {clause.pattern} has no sign"))
        if not problems:
            return []
        if condition is not None:
            return [
                _finding(
                    rule,
                    "CONDITION_NEVER_TRUE",
                    f"level-88 {condition.name} VALUE {text} can never be true: "
                    f"{problems[0][1]} for {item.name}",
                    condition.location,
                    condition.name,
                )
            ]
        kind, why = problems[0]
        return [
            _finding(
                rule,
                kind,
                f"VALUE {text} does not fit {item.name}: {why}",
                item.location,
                item.name,
            )
        ]

    def _condition_values(
        self, item: CobolDataItem, condition: ConditionNameItem
    ) -> list[BugFinding]:
        kinds = list(condition.value_kinds)
        if len(kinds) != len(condition.values):
            return []
        rule = "value-clause"
        numeric = _numeric_picture(item)
        size = _alphanumeric_size(item)
        for raw, kind in zip(condition.values, kinds, strict=True):
            value = raw[len("THROUGH:") :] if raw.startswith("THROUGH:") else raw
            if kind == "string":
                if numeric is not None:
                    return [
                        _finding(
                            rule,
                            "CONDITION_VALUE_WRONG_CATEGORY",
                            f"level-88 {condition.name} VALUE '{value}' is not "
                            f"numeric, but {item.name} is PIC {numeric.pattern}",
                            condition.location,
                            condition.name,
                        )
                    ]
                length = (
                    _literal_length(value)
                    if value[:2].upper() in ("X'", 'X"')
                    else len(value)
                )
                if size is not None and length is not None and length > size:
                    return [
                        _finding(
                            rule,
                            "CONDITION_NEVER_TRUE",
                            f"level-88 {condition.name} VALUE '{value}' is "
                            f"{length} characters but {item.name} holds {size}; "
                            "the condition can never be true",
                            condition.location,
                            condition.name,
                        )
                    ]
            elif kind == "numeric" and numeric is not None:
                literal = _numeric_literal(value)
                if literal is not None:
                    found = self._numeric_fit(
                        rule, item, numeric, literal, value, condition=condition
                    )
                    if found:
                        return found
        return []

    # -- data-layout ---------------------------------------------------------

    def _data_layout(self) -> list[BugFinding]:
        return self._redefines_larger() + self._record_contains()

    def _redefines_larger(self) -> list[BugFinding]:
        findings: list[BugFinding] = []
        for item in self.context.data.items:
            if not item.redefines or item.level in (1, 77, 66, 88):
                continue
            if item.occurs_clause is not None:
                continue
            parent = item.parent
            siblings = [
                c
                for c in getattr(parent, "children", [])
                if isinstance(c, CobolDataItem)
            ]
            target_name = str(item.redefines).upper()
            target = next(
                (
                    s
                    for s in siblings
                    if s.name.upper() == target_name and s is not item
                ),
                None,
            )
            if target is None or target.occurs_clause is not None:
                continue
            mine, theirs = _layout_length(item), _layout_length(target)
            if mine is None or theirs is None or mine <= theirs:
                continue
            findings.append(
                _finding(
                    "data-layout",
                    "REDEFINES_LARGER",
                    f"{item.name} ({mine} bytes) REDEFINES {target.name} "
                    f"({theirs} bytes); below level 01 the redefining item must "
                    f"not be larger, and the extra {mine - theirs} byte(s) "
                    "overlay the fields that follow",
                    item.location,
                    item.name,
                )
            )
        return findings

    def _record_contains(self) -> list[BugFinding]:
        records: dict[str, list[CobolDataItem]] = {}
        clauses: dict[str, dict[str, Any]] = {}
        for item in self.context.data.items:
            if item.level != 1:
                continue
            file_name = item.get_metadata("fd_file_name")
            fd_clauses = item.get_metadata("fd_clauses")
            if not file_name or not isinstance(fd_clauses, dict):
                continue
            records.setdefault(str(file_name).upper(), []).append(item)
            clauses[str(file_name).upper()] = fd_clauses
        findings: list[BugFinding] = []
        for file_name, items in records.items():
            record = clauses[file_name].get("record")
            if not isinstance(record, dict) or record.get("varying"):
                continue
            declared = record.get("max")
            if not isinstance(declared, int) or record.get("min") is not None:
                continue
            lengths = [_layout_length(i) for i in items]
            if any(length is None for length in lengths):
                continue
            longest = max(int(length or 0) for length in lengths)
            if longest == declared:
                continue
            item = items[[int(x or 0) for x in lengths].index(longest)]
            findings.append(
                _finding(
                    "data-layout",
                    "RECORD_CONTAINS_MISMATCH",
                    f"FD {file_name} says RECORD CONTAINS {declared} CHARACTERS "
                    f"but its longest record, {item.name}, is {longest} bytes; "
                    "the compiler uses the record description",
                    item.location,
                    item.name,
                )
            )
        return findings

    # -- comparison ----------------------------------------------------------

    def _comparison(self) -> list[BugFinding]:
        findings: list[BugFinding] = []
        seen: set[int] = set()
        reported: set[tuple[int, int]] = set()
        for stmt in self.context.statements():
            for name, value in vars(stmt).items():
                if name in ("parent", "children", "location") or name.startswith("_"):
                    continue
                for comparison in _comparisons(value, seen):
                    finding = self._check_comparison(comparison, stmt)
                    if finding is None:
                        continue
                    key = (id(stmt), hash(finding.message))
                    if key not in reported:
                        reported.add(key)
                        findings.append(finding)
        return findings

    def _check_comparison(self, node: Any, stmt: Any) -> BugFinding | None:
        left, right, op = node.left_operand, node.right_operand, node.operator
        if not isinstance(left, str) or not isinstance(right, str):
            return None
        item = self._item(left)
        literal = right
        if item is None:
            item = self._item(right)
            literal = left
            op = _MIRROR.get(op, op)
        if item is None:
            return None
        literal = literal.strip()
        shown = f"{item.name} {_RELATION_TEXT[op]} {literal}"
        numeric = _numeric_picture(item)
        if numeric is not None and _usage(item) not in _BINARY_USAGES:
            inner = _quoted(literal)
            if inner is not None:
                if op not in ("EQUAL", "NOT_EQUAL"):
                    return None
                if inner.strip() and not re.fullmatch(r"[+-]?\d+", inner.strip()):
                    return _finding(
                        "comparison",
                        "COMPARISON_NONNUMERIC_LITERAL",
                        f"{shown}: {item.name} is numeric (PIC {numeric.pattern}) "
                        "and the literal is not a number; the comparison is made "
                        "character by character and is never equal to a valid "
                        "value",
                        stmt.location,
                        item.name,
                    )
                return None
            parsed = _numeric_literal(literal)
            if parsed is None:
                return None
            return self._numeric_bound(item, numeric, parsed, op, shown, stmt)
        size = _alphanumeric_size(item)
        if size is not None and op in ("EQUAL", "NOT_EQUAL"):
            inner = _quoted(literal)
            if inner is not None and len(inner) > size and inner[size:].strip():
                always = "FALSE" if op == "EQUAL" else "TRUE"
                return _finding(
                    "comparison",
                    f"COMPARISON_ALWAYS_{always}",
                    f"{shown} is always {always.lower()}: {item.name} holds "
                    f"{size} characters and the literal is {len(inner)}",
                    stmt.location,
                    item.name,
                )
        return None

    def _numeric_bound(
        self,
        item: CobolDataItem,
        clause: Any,
        literal: tuple[bool, str, str],
        op: str,
        shown: str,
        stmt: Any,
    ) -> BugFinding | None:
        negative, integer, decimal = literal
        is_zero = not integer and not decimal
        unsigned = not clause.is_signed
        # Sign: an unsigned item is never negative.
        if unsigned and (negative and not is_zero or (is_zero and op == "LESS")):
            if op in ("EQUAL", "LESS", "LESS_OR_EQUAL") and not (
                is_zero and op == "LESS_OR_EQUAL"
            ):
                outcome = "FALSE"
            elif op in ("NOT_EQUAL", "GREATER", "GREATER_OR_EQUAL"):
                outcome = "TRUE"
            else:
                return None
            reason = f"{item.name} is unsigned (PIC {clause.pattern}), never negative"
            return self._always(outcome, shown, reason, stmt, item)
        if len(integer) <= int(clause.integer_digits):
            return None
        # The literal's magnitude is beyond anything the item holds.
        bigger = not negative
        if op == "EQUAL":
            outcome = "FALSE"
        elif op == "NOT_EQUAL":
            outcome = "TRUE"
        elif op in ("GREATER", "GREATER_OR_EQUAL"):
            outcome = "FALSE" if bigger else "TRUE"
        else:
            outcome = "TRUE" if bigger else "FALSE"
        reason = (
            f"{item.name} holds at most {clause.integer_digits} integer digit(s) "
            f"(PIC {clause.pattern})"
        )
        return self._always(outcome, shown, reason, stmt, item)

    @staticmethod
    def _always(
        outcome: str, shown: str, reason: str, stmt: Any, item: CobolDataItem
    ) -> BugFinding:
        return _finding(
            "comparison",
            f"COMPARISON_ALWAYS_{outcome}",
            f"{shown} is always {outcome.lower()}: {reason}",
            stmt.location,
            item.name,
        )

    # -- search-table --------------------------------------------------------

    def _search_table(self) -> list[BugFinding]:
        findings: list[BugFinding] = []
        for stmt in self.context.statements():
            if not isinstance(stmt, SearchStatement) or not stmt.table_name:
                continue
            item = self._item(stmt.table_name)
            if item is None:
                continue
            search_all = bool(stmt.get_metadata("is_search_all"))
            verb = "SEARCH ALL" if search_all else "SEARCH"
            occurs = item.occurs_clause
            if occurs is None:
                findings.append(
                    _finding(
                        "search-table",
                        "SEARCH_NOT_A_TABLE",
                        f"{verb} {item.name}: {item.name} has no OCCURS clause",
                        stmt.location,
                        item.name,
                    )
                )
                continue
            if not occurs.index_names and not occurs.indexed_by:
                findings.append(
                    _finding(
                        "search-table",
                        "SEARCH_NO_INDEX",
                        f"{verb} {item.name}: the table has no INDEXED BY "
                        "phrase, which SEARCH needs",
                        stmt.location,
                        item.name,
                    )
                )
            if search_all and not occurs.key_clauses:
                findings.append(
                    _finding(
                        "search-table",
                        "SEARCH_ALL_NO_KEY",
                        f"SEARCH ALL {item.name}: the table has no ASCENDING or "
                        "DESCENDING KEY phrase, which a binary search needs",
                        stmt.location,
                        item.name,
                    )
                )
        return findings

    # -- divide-by-zero ------------------------------------------------------

    def _divide_by_zero(self) -> list[BugFinding]:
        findings: list[BugFinding] = []
        for stmt in self.context.statements():
            divisor: str | None = None
            if isinstance(stmt, DivideStatement):
                mode = str(getattr(stmt, "division_mode", "") or "").upper()
                operands = list(getattr(stmt, "source_operands", None) or [])
                if not operands:
                    operands = list(stmt.operands)
                if mode == "BY" and len(operands) >= 2:
                    divisor = operands[1]
                elif mode == "INTO" and operands:
                    divisor = operands[0]
                if divisor is not None and not _is_zero(divisor):
                    divisor = None
            elif isinstance(stmt, ComputeStatement):
                expression = QUOTED_LITERAL_RE.sub('""', str(stmt.expression or ""))
                if _COMPUTE_DIVIDE_ZERO_RE.search(expression):
                    divisor = "0"
            if divisor is None:
                continue
            findings.append(
                _finding(
                    "divide-by-zero",
                    "DIVIDE_BY_ZERO",
                    f"{stmt.statement_type} divides by the literal zero; it "
                    "always fails at run time (a size error, or abend S0CB "
                    "without ON SIZE ERROR)",
                    stmt.location,
                )
            )
        return findings

    # -- subscript-usage -----------------------------------------------------

    def _subscript_usage(self) -> list[BugFinding]:
        from .bug_patterns import _statement_strings

        findings: list[BugFinding] = []
        reported: set[tuple[int, str, str]] = set()
        for stmt in self.context.statements():
            kind_name = type(stmt).__name__
            if kind_name.startswith("Exec") or isinstance(stmt, SearchStatement):
                continue
            module = type(stmt).__module__.lower()
            if any(part in module for part in ("sql", "cics", "ims", "dli", "dialect")):
                # Embedded SQL / CICS / DL/I: a host-variable array is passed
                # whole (``FETCH ... ROWSET ... INTO :ARR``).
                continue
            if kind_name in (
                "SetStatement",
                "SortStatement",
                "MergeStatement",
                "UseStatement",
            ):
                continue
            texts = list(_statement_strings(stmt))
            subscripted = {
                m.group(1).upper()
                for text in texts
                for m in re.finditer(
                    rf"({_NAME})(?:{_QUALIFIER_RE.pattern})*\s*\(", text, re.IGNORECASE
                )
            }
            for text in texts:
                for finding in self._references(stmt, text, subscripted):
                    key = (id(stmt), finding.kind, finding.symbol or "")
                    if key not in reported:
                        reported.add(key)
                        findings.append(finding)
        return findings

    def _references(
        self, stmt: Any, text: str, subscripted: set[str]
    ) -> Iterator[BugFinding]:
        for match in _WORD_RE.finditer(text):
            name = match.group(0).upper()
            if _QUALIFIER_BEFORE_RE.search(text[: match.start()]):
                continue  # a qualifier: any subscript belongs to the name before
            candidates = self.context.data.by_name.get(name, [])
            if len(candidates) != 1:
                continue
            item = candidates[0]
            rest = text[match.end() :]
            qualifiers = re.match(rf"(?:{_QUALIFIER_RE.pattern})*", rest, re.IGNORECASE)
            after = rest[qualifiers.end() if qualifiers else 0 :]
            groups = _paren_groups(after)
            dims = self.context._dimensions(item)
            subscript = next((g for g in groups if ":" not in g), None)
            refmod = next((g for g in groups if ":" in g), None)
            if groups and groups[0] is not subscript and subscript is not None:
                # ``X(1:2)(3)`` is not a subscript; only the leading group is.
                subscript = None
            if subscript is not None and groups and groups[0] != subscript:
                subscript = None
            if dims is None:
                continue
            if subscript is None and dims:
                before = text[: match.start()]
                if name in subscripted or _UNSUBSCRIPTED_CONTEXT_RE.search(before):
                    continue
                if refmod is None and not after.lstrip().startswith("("):
                    yield _finding(
                        "subscript-usage",
                        "SUBSCRIPT_MISSING",
                        f"{item.name} is an element of a table (OCCURS) and is "
                        "used here without a subscript",
                        stmt.location,
                        item.name,
                    )
                continue
            if subscript is not None:
                count = _subscript_count(subscript)
                if not dims:
                    yield _finding(
                        "subscript-usage",
                        "SUBSCRIPT_NOT_A_TABLE",
                        f"{item.name}({subscript.strip()}) has a subscript, but "
                        f"{item.name} is not in a table (no OCCURS)",
                        stmt.location,
                        item.name,
                    )
                elif count is not None and count != len(dims):
                    yield _finding(
                        "subscript-usage",
                        "SUBSCRIPT_COUNT",
                        f"{item.name}({subscript.strip()}) has {count} "
                        f"subscript(s); {item.name} is in {len(dims)} OCCURS "
                        "level(s)",
                        stmt.location,
                        item.name,
                    )
            if refmod is not None:
                finding = self._refmod(item, refmod, stmt)
                if finding is not None:
                    yield finding

    def _refmod(self, item: CobolDataItem, refmod: str, stmt: Any) -> BugFinding | None:
        start_text, _, length_text = refmod.partition(":")
        if not re.fullmatch(r"\s*\d+\s*", start_text):
            return None
        length_text = length_text.strip()
        if length_text and not re.fullmatch(r"\d+", length_text):
            return None
        size = _layout_length(item) if not _is_elementary(item) else None
        if _is_elementary(item):
            clause = item.picture_clause
            if clause is None or clause.size is None:
                return None
            if _usage(item) != "DISPLAY" or clause.is_national:
                return None
            size = int(clause.size)
        if not size:
            return None
        start = int(start_text)
        length = int(length_text) if length_text else None
        problem = None
        if start < 1 or start > size:
            problem = f"starts at {start}"
        elif length is not None and (length < 1 or start + length - 1 > size):
            problem = f"ends at {start + (length or 0) - 1}"
        if problem is None:
            return None
        return _finding(
            "subscript-usage",
            "REFMOD_OUT_OF_RANGE",
            f"{item.name}({refmod.strip()}) {problem}, outside {item.name}'s "
            f"{size} character(s)",
            stmt.location,
            item.name,
        )

    # -- procedure-structure -------------------------------------------------

    def _procedure_structure(self) -> list[BugFinding]:
        division = self.ast.procedure_division
        if division is None:
            return []
        findings: list[BugFinding] = []
        paragraphs = [p for p in _all_paragraphs(division) if p.paragraph_name]
        groups: dict[tuple[str, str], list[Any]] = {}
        for para in paragraphs:
            if getattr(para, "is_declarative", False):
                continue
            section = self._paragraph_section(para)
            groups.setdefault((section, para.paragraph_name.upper()), []).append(para)
        unqualified = self._unqualified_procedure_refs()
        for (section, name), paras in groups.items():
            if len(paras) < 2:
                continue
            referenced = name in unqualified
            where = f" in section {section}" if section else ""
            finding = _finding(
                "procedure-structure",
                "DUPLICATE_PARAGRAPH",
                f"paragraph {paras[1].paragraph_name} is defined {len(paras)} times"
                f"{where} (first at line {paras[0].location.line})"
                + (
                    "; a PERFORM or GO TO of it cannot tell which is meant"
                    if referenced
                    else ""
                ),
                paras[1].location,
                paras[1].paragraph_name,
            )
            if referenced:
                finding.severity = "error"
            findings.append(finding)
        last = paragraphs[-1] if paragraphs else None
        for para in paragraphs:
            if para.statements or para is last:
                continue
            findings.append(
                _finding(
                    "procedure-structure",
                    "EMPTY_PARAGRAPH",
                    f"paragraph {para.paragraph_name} contains no statements",
                    para.location,
                    para.paragraph_name,
                )
            )
        return findings

    @staticmethod
    def _paragraph_section(para: Any) -> str:
        node = para.parent
        while node is not None and not isinstance(node, CobolSection):
            node = getattr(node, "parent", None)
        if node is None:
            return ""
        return str(getattr(node, "section_name", "") or "").upper()

    def _unqualified_procedure_refs(self) -> set[str]:
        names: set[str] = set()
        for entry in self.context.xref.entries:
            if entry.kind not in ("paragraph", "section", "procedure"):
                continue
            if entry.references:
                names.add(entry.name.upper())
        return names

    # -- corresponding -------------------------------------------------------

    def _corresponding(self) -> list[BugFinding]:
        findings: list[BugFinding] = []
        for stmt in self.context.statements():
            if not getattr(stmt, "is_corresponding", False):
                continue
            if isinstance(stmt, MoveStatement):
                sources = [stmt.source]
            else:
                sources = list(getattr(stmt, "source_operands", None) or [])
            targets = list(getattr(stmt, "targets", None) or [])
            if len(sources) != 1 or not targets:
                continue
            source = self._item(sources[0])
            if source is None or _is_elementary(source):
                continue
            source_names = _corresponding_names(source)
            for target_text in targets:
                target = self._item(target_text)
                if target is None or _is_elementary(target):
                    continue
                if source_names & _corresponding_names(target):
                    continue
                findings.append(
                    _finding(
                        "corresponding",
                        "NO_CORRESPONDING_ITEMS",
                        f"{stmt.statement_type} CORRESPONDING {source.name} to "
                        f"{target.name}: the groups have no subordinate names in "
                        "common, so nothing is moved",
                        stmt.location,
                        target.name,
                    )
                )
        return findings

    # -- arithmetic-operand --------------------------------------------------

    def _arithmetic_operand(self) -> list[BugFinding]:
        findings: list[BugFinding] = []
        arithmetic = (
            AddStatement,
            SubtractStatement,
            MultiplyStatement,
            DivideStatement,
            ComputeStatement,
        )
        for stmt in self.context.statements():
            if not isinstance(stmt, arithmetic) or getattr(
                stmt, "is_corresponding", False
            ):
                continue
            givings = [str(g) for g in (getattr(stmt, "givings", None) or [])]
            targets = [str(t) for t in (getattr(stmt, "targets", None) or [])]
            if isinstance(stmt, ComputeStatement):
                # A COMPUTE result may go to a numeric-edited item, like GIVING.
                givings, targets = givings + targets, []
                sources = _compute_names(str(stmt.expression or ""))
            else:
                sources = [
                    str(o)
                    for o in stmt.operands
                    if str(o) not in givings and str(o) not in targets
                ]
            reported: set[str] = set()
            for text in sources:
                item = self._item(text)
                if item is None or item.name in reported:
                    continue
                problem = _nonnumeric(item, role="source")
                if problem:
                    reported.add(item.name)
                    findings.append(
                        _finding(
                            "arithmetic-operand",
                            "NONNUMERIC_ARITHMETIC_OPERAND",
                            f"{stmt.statement_type} uses {item.name} as a number, "
                            f"but it is {problem}",
                            stmt.location,
                            item.name,
                        )
                    )
            for text in targets + givings:
                item = self._item(text)
                if item is None or item.name in reported:
                    continue
                # A non-GIVING target is an operand too (ADD A TO B adds B).
                problem = _nonnumeric(
                    item, role="giving" if text in givings else "target"
                )
                if problem:
                    reported.add(item.name)
                    findings.append(
                        _finding(
                            "arithmetic-operand",
                            "NONNUMERIC_ARITHMETIC_RECEIVER",
                            f"{stmt.statement_type} stores its result in "
                            f"{item.name}, but it is {problem}",
                            stmt.location,
                            item.name,
                        )
                    )
        return findings


def _file_names(ast: CobolProgram) -> set[str]:
    """Upper-cased names of the files the program SELECTs or describes."""
    from ..models.statements.misc import SelectStatement

    names: set[str] = set()
    for node in ast.traverse_depth_first():
        if isinstance(node, SelectStatement) and node.file_name:
            names.add(str(node.file_name).upper())
        elif isinstance(node, CobolDataItem):
            fd = node.get_metadata("fd_file_name")
            if fd:
                names.add(str(fd).upper())
    return names


def _is_zero(text: str) -> bool:
    text = text.strip().upper()
    return text in ("ZERO", "ZEROS", "ZEROES") or bool(
        _ZERO_LITERAL_RE.match(text) and any(c.isdigit() for c in text)
    )


def _paren_groups(text: str) -> list[str]:
    """The contents of consecutive parenthesised groups at the start of
    *text* (``(1)(2:3)`` -> ``["1", "2:3"]``), nested parentheses kept."""
    groups: list[str] = []
    position = 0
    while True:
        rest = text[position:]
        stripped = rest.lstrip()
        if not stripped.startswith("("):
            return groups
        start = position + (len(rest) - len(stripped))
        depth = 0
        for index in range(start, len(text)):
            char = text[index]
            if char == "(":
                depth += 1
            elif char == ")":
                depth -= 1
                if depth == 0:
                    groups.append(text[start + 1 : index])
                    position = index + 1
                    break
        else:
            return groups


def _subscript_count(text: str) -> int | None:
    """How many subscripts ``(...)`` holds, or None when not countable."""
    if "(" in text or "+" in text or re.search(r"(?<![A-Za-z0-9])-", text):
        # ``(W-1 +1)`` is two subscripts, ``(W-1 + 1)`` one relative
        # subscript, and the parser's text does not keep that spacing.
        return None
    body = _QUALIFIER_RE.sub("", text)
    parts = [p for p in re.split(r"[\s,;]+", body.strip()) if p]
    return len(parts) or None


def _corresponding_names(group: CobolDataItem) -> set[str]:
    """Names CORRESPONDING can pair under *group*: subordinate items that
    are not FILLER, REDEFINES, RENAMES or tables (nor under one)."""
    names: set[str] = set()

    def walk(node: CobolDataItem) -> None:
        for child in node.children:
            if not isinstance(child, CobolDataItem) or child.level in (66, 88):
                continue
            if child.redefines or child.occurs_clause is not None:
                continue
            if not child.is_filler:
                names.add(child.name.upper())
            walk(child)

    walk(group)
    return names


def _compute_names(expression: str) -> list[str]:
    """Data references of a COMPUTE expression, qualifiers kept with their
    name (``HOURS OF MSG-TIME`` is one reference)."""
    text = QUOTED_LITERAL_RE.sub(" ", expression)
    text = _strip_functions(text)
    text = re.sub(rf"\bLENGTH\s+OF\s+{_NAME}", " 0 ", text, flags=re.I)
    pattern = re.compile(
        rf"(?<![A-Za-z0-9-]){_NAME}(?:{_QUALIFIER_RE.pattern})*", re.IGNORECASE
    )
    return [m.group(0) for m in pattern.finditer(text) if not m.group(0)[0].isdigit()]


def _strip_functions(text: str) -> str:
    """*text* with every ``FUNCTION name(...)`` call, nested parentheses
    included, replaced by a blank: its arguments are not arithmetic
    operands."""
    out: list[str] = []
    position = 0
    for match in re.finditer(r"\bFUNCTION\s+[A-Za-z0-9-]+\s*", text, re.IGNORECASE):
        if match.start() < position:
            continue
        out.append(text[position : match.start()])
        end = match.end()
        if end < len(text) and text[end] == "(":
            depth = 0
            for index in range(end, len(text)):
                if text[index] == "(":
                    depth += 1
                elif text[index] == ")":
                    depth -= 1
                    if depth == 0:
                        end = index + 1
                        break
            else:
                end = len(text)
        out.append(" 0 ")
        position = end
    out.append(text[position:])
    return "".join(out)


def _nonnumeric(item: CobolDataItem, *, role: str) -> str | None:
    """Why *item* cannot take part in arithmetic in *role* (``source``,
    ``target`` -- a receiver that is also an operand, as in ``ADD A TO B``
    -- or ``giving``), or None when it can (or when that is not known)."""
    if not _is_elementary(item):
        if any(
            isinstance(c, CobolDataItem) and c.name.upper().startswith("ANONYMOUS-")
            for c in item.children
        ):
            return None  # ``01 X CONSTANT AS 10`` (the parser's shape for it)
        return f"a group item ({item.name} has subordinate fields)"
    clause = item.picture_clause
    if clause is None:
        return None
    if _usage(item) != "DISPLAY":
        return None
    if clause.integer_digits is not None and not clause.is_edited:
        return None
    if clause.is_numeric_edited:
        # IBM de-edits a numeric-edited sending operand; as a receiver it is
        # valid after GIVING (and in COMPUTE) only.
        if role == "target":
            return f"numeric-edited (PIC {clause.pattern}); use GIVING"
        return None
    if clause.is_edited or clause.is_national:
        return None
    return f"alphanumeric (PIC {clause.pattern})"


__all__ = [
    "COMPILER_RULES",
    "COMPILER_RULE_DESCRIPTIONS",
    "CompilerCheckAnalyzer",
    "CompilerCheckReport",
    "CompilerChecks",
]
