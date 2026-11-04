"""
Redundancy detection for COBOL programs.

Combines two kinds of "this code is redundant weight, not real work":

- **Unreferenced code/data** -- delegates straight to
  :class:`~.dead_code.DeadCodeAnalyzer` (unreferenced paragraphs/sections)
  and :class:`~.unused_variables.UnusedVariableAnalyzer` (unreferenced DATA
  DIVISION items), reporting both as ratios alongside the underlying items.
- **Duplicate code (clones)** -- new in this module. Two paragraphs are a
  clone pair when their statement trees are structurally identical:

  - **Type-1 (exact)**: same statement types, same operands/conditions,
    verbatim -- and the same everything else each statement does: its
    clause bodies (AT END, ON SIZE ERROR, ...) and the rest of its fields
    (a COMPUTE formula, ROUNDED, UPON, a TIMES count, ...).
  - **Type-2 (renamed)**: same statement types and same control-flow shape,
    but with data-names/paragraph-names consistently substituted (``MOVE
    WS-A TO WS-B`` and ``MOVE WS-X TO WS-Y`` match; a changed *literal*
    never matches, since a literal is behavior, not a name).

  Only whole-paragraph matches are attempted (no sub-paragraph sliding
  window, no near-miss/type-3 similarity scoring) -- this is exactly where
  COBOL copy-paste actually shows up (a whole PERFORM target cloned instead
  of shared), and it is exact: no similarity-threshold tuning, no
  false-positive debate. Clone groups below ``min_clone_statements`` (a tiny
  paragraph like a single ``EXIT.`` matching another) are not reported.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import Any

from .._literals import QUOTED_LITERAL_RE
from ..lexer import CobolLexer
from ..models.ast_base import SourceLocation
from ..models.program import CobolDivision, CobolParagraph, CobolProgram
from ..models.statements.arithmetic import ROUNDING_MODES
from ..models.statements.call import CallStatement
from ..models.statements.control import (
    EvaluateStatement,
    IfStatement,
    PerformStatement,
    SearchStatement,
    StopStatement,
)
from ..models.statements.io import IOAcceptStatement
from ..models.statements.misc import InvokeStatement
from ._names import IDENTIFIER_TOKEN_RE
from ._procedures import ProcedureIndex
from .dead_code import DeadCodeAnalyzer, DeadCodeItem
from .program_flow.condition_text import render_condition_text

# The identifier-vs-literal helpers (``_NON_IDENTIFIER_WORDS``) are reused
# verbatim from unused_variables.py: the same reserved-word/figurative
# -constant/condition-keyword set that module already curated to distinguish
# a real data-name token from COBOL noise words. Re-deriving a second,
# slightly different list here would just drift out of sync with it for no
# benefit -- unlike the walking-discipline tuples other analysis modules
# duplicate (those differ per module's own traversal needs), this is a
# single well-defined "is this token a name" question both modules ask.
from .unused_variables import (
    _NON_IDENTIFIER_WORDS,
    UnusedVariableAnalyzer,
    UnusedVariableItem,
)

_QUOTED_TEXT_RE = QUOTED_LITERAL_RE
_WHITESPACE_RUN_RE = re.compile(r"\s+")

# Clause-list attributes holding statements that run only when the clause
# fires. Each present body is part of what its statement *does*, so it is
# fingerprinted (#262). The same set ``complexity.py``'s ``_CLAUSE_PAIRS``
# names, re-derived here per the analysis package's convention (one walker's
# needs never silently change another's).
_CLAUSE_ATTRS: tuple[str, ...] = (
    "at_end_clause",
    "not_at_end_clause",
    "invalid_key_clause",
    "not_invalid_key_clause",
    "at_eop_clause",
    "not_at_eop_clause",
    "on_size_error",
    "not_on_size_error",
    "on_overflow",
    "not_on_overflow",
    "on_exception",
    "not_on_exception",
)

# ``to_dict()`` keys that are not behaviour: where the statement sits, the
# node bookkeeping, what the fingerprint already holds (type, operands,
# clause bodies), and ``possible_values`` -- an annotation
# ``DynamicCallAnalyzer`` writes onto the AST, which would otherwise make a
# digest depend on which analyzers happened to run first.
_DETAIL_SKIP_KEYS = frozenset(
    {
        "node_type",
        "location",
        "metadata",
        "children",
        "statement_type",
        "operands",
        "possible_values",
        *_CLAUSE_ATTRS,
    }
)

# A ``to_dict()`` field name (``file_name``, ``times_count``) as opposed to a
# dict keyed by data-names (OPEN's file -> mode map).
_FIELD_KEY_RE = re.compile(r"[a-z][a-z0-9_]*")

# Words a statement's detail fields hold as *keywords* (``FOR LEADING``,
# ``DELIMITED BY SIZE``, ``PERFORM ... TIMES``, an OPEN mode, a comparison
# operator). A reserved word is never a data-name, so Type-2 renaming must
# leave it alone: ``FOR ALL`` and ``FOR LEADING`` are different behaviour,
# not a consistent rename. The lexer's keyword table plus the reserved words
# the statement models store as enum-like values that it does not tokenise
# as keywords.
_DETAIL_KEYWORDS = (
    _NON_IDENTIFIER_WORDS
    | frozenset(CobolLexer.KEYWORDS)
    # ``ROUNDED MODE IS NEAREST-EVEN`` vs ``TRUNCATION`` is different
    # behaviour, not a consistent rename (#517).
    | ROUNDING_MODES
    | frozenset(
        {
            "ADVANCING",
            "AFTER",
            "ALL",
            "ARITHMETIC",
            "ASCENDING",
            "BEFORE",
            "BY",
            "CHANNEL",
            "CHARACTERS",
            "COMPARISON",
            "CONDITION",
            "CONDITION_NAME",
            "CONVERTING",
            "DEBUGGING",
            "DESCENDING",
            "DOWN",
            "EQUAL",
            "ERROR",
            "EXCEPTION",
            "EXTEND",
            "FIRST",
            "GREATER",
            "I-O",
            "INLINE",
            "INPUT",
            "LEADING",
            "LESS",
            "LINE",
            "LINES",
            "LOGICAL",
            "MESSAGE",
            "NEXT",
            "OUTPUT",
            "PAGE",
            "REPLACING",
            "REPORTING",
            "RUN",
            "SEGMENT",
            "SIMPLE",
            "SIZE",
            "TALLYING",
            "THAN",
            "TIMES",
            "TO",
            "UNTIL",
            "UP",
            "VARYING",
        }
    )
)


def _normalize_text(
    text: str,
    type2: bool,
    id_map: dict[str, str],
    keywords: frozenset[str] = _NON_IDENTIFIER_WORDS,
) -> str:
    """Normalize one operand/condition-text string for fingerprinting.

    Both types first erase what COBOL itself ignores (#391): every run of
    whitespace outside a literal collapses to one space, and all text
    outside a literal is upper-cased (COBOL words are case-insensitive;
    literal text is not, so quoted substrings are left exactly as written).
    That is all Type-1 (``type2=False``) does. Type-2 then replaces every
    identifier-shaped token (skipping quoted substrings, so literal text is
    never touched) with a per-paragraph positional placeholder (``ID1``,
    ``ID2``, ...), assigned in first-seen order and reused on repeat -- so
    ``MOVE WS-A TO WS-B`` and ``MOVE WS-X TO WS-Y`` both normalize to ``MOVE
    ID1 TO ID2``, but a paragraph that references the same name twice keeps
    that repetition visible (``ID1 ... ID1``, not two different IDs).

    *keywords* is the set of words never substituted: the default suits
    operand and condition text; a statement's detail fields pass the wider
    ``_DETAIL_KEYWORDS`` since they hold reserved words as values.
    """
    if not text:
        return text

    # Protect quoted substrings from case folding, whitespace collapsing and
    # identifier substitution by splitting on them first (mirrors
    # unused_variables.py's own quoted-text handling).
    pieces = []
    last = 0
    for m in _QUOTED_TEXT_RE.finditer(text):
        pieces.append(("text", text[last : m.start()]))
        pieces.append(("quoted", m.group(0)))
        last = m.end()
    pieces.append(("text", text[last:]))

    def repl(m: re.Match[str]) -> str:
        tok = m.group(0)
        if tok in keywords:
            return tok
        return id_map.setdefault(tok, f"ID{len(id_map) + 1}")

    out = []
    for kind, chunk in pieces:
        if kind == "quoted":
            out.append(chunk)
            continue
        chunk = _WHITESPACE_RUN_RE.sub(" ", chunk).upper()
        out.append(IDENTIFIER_TOKEN_RE.sub(repl, chunk) if type2 else chunk)
    return "".join(out).strip()


def _quote(value: str) -> str:
    """Re-quote a literal the parser stored without its quotes, so
    ``_normalize_text`` leaves its case and spelling alone (#391)."""
    return "'" + value.replace("'", "''") + "'"


def _selector_text(selector: Any) -> str:
    """Compact text for one EVALUATE WHEN selector dict."""
    if not isinstance(selector, dict):
        return str(selector)
    sel_type = selector.get("type", "")
    if sel_type == "Range":
        start = str(selector.get("start", ""))
        end = str(selector.get("end", ""))
        if selector.get("start_quoted"):
            start = _quote(start)
        if selector.get("end_quoted"):
            end = _quote(end)
        return f"RANGE:{start}..{end}"
    if sel_type == "Condition":
        return f"COND:{selector.get('text', '')}"
    value = str(selector.get("value", ""))
    if selector.get("quoted"):
        value = _quote(value)
    return f"{sel_type}:{value}"


def _unquoted_literals(stmt: Any) -> dict[str, str]:
    """The ``to_dict()`` fields of *stmt* that hold a literal the parser
    stored without its quotes, keyed by field name.

    Fingerprint text is case-folded outside quotes (#391), so a bare
    ``subp`` from ``CALL 'subp'`` would otherwise fold into ``CALL 'SUBP'``
    -- a different program under PGMNAME(LONGMIXED). Only fields the AST
    marks as literals are listed; ``.okf/analysis.md`` names the spots
    where the AST cannot tell a literal from a name.
    """
    if isinstance(stmt, CallStatement):
        if not stmt.is_dynamic and stmt.called_program:
            return {"called_program": stmt.called_program}
    elif isinstance(stmt, InvokeStatement):
        if stmt.method_is_literal and stmt.method_name:
            return {"method_name": stmt.method_name}
    elif isinstance(stmt, StopStatement):
        if stmt.stop_type and stmt.stop_type.upper() != "RUN":
            return {"stop_type": stmt.stop_type}
    return {}


def _subject_text(subject: Any) -> str:
    if hasattr(subject, "to_dict"):
        return render_condition_text(subject)
    return str(subject)


class _Fingerprinter:
    """Builds a hashable structural fingerprint for one paragraph.

    A fresh instance per paragraph: the type-2 identifier->placeholder map
    is scoped to that one paragraph (never shared across paragraphs, which
    would defeat the point -- two unrelated paragraphs would start
    coincidentally aligning their placeholder numbering).
    """

    def __init__(self, type2: bool) -> None:
        self._type2 = type2
        self._id_map: dict[str, str] = {}
        self.leaf_count = 0

    def _norm(self, text: str) -> str:
        return _normalize_text(text, self._type2, self._id_map)

    def fingerprint_paragraph(self, para: CobolParagraph) -> tuple[Any, ...]:
        return tuple(self._fp(stmt) for stmt in para.statements)

    def _fp(self, stmt: Any) -> Any:
        stype = getattr(stmt, "statement_type", stmt.__class__.__name__)

        if isinstance(stmt, IfStatement):
            cond = self._norm(render_condition_text(stmt.condition))
            then_fp = tuple(self._fp(s) for s in stmt.then_statements)
            else_fp = tuple(self._fp(s) for s in stmt.else_statements)
            return ("IF", cond, then_fp, else_fp)

        if isinstance(stmt, EvaluateStatement):
            subjects = tuple(self._norm(_subject_text(s)) for s in stmt.subjects)
            whens = tuple(
                (
                    tuple(self._norm(_selector_text(sel)) for sel in wc.selectors),
                    tuple(self._fp(s) for s in wc.statements),
                )
                for wc in stmt.when_clauses
            )
            other = (
                tuple(self._fp(s) for s in stmt.default_when.statements)
                if stmt.default_when
                else None
            )
            return ("EVALUATE", subjects, whens, other)

        if isinstance(stmt, SearchStatement):
            search_whens = tuple(
                (
                    self._norm(wc.get("condition", "")),
                    tuple(self._fp(s) for s in wc.get("statements", [])),
                )
                for wc in stmt.when_clauses
            )
            at_end = tuple(self._fp(s) for s in (stmt.at_end_clause or []))
            details = self._details(stmt, frozenset({"when_clauses", "at_end_clause"}))
            # Serial vs binary search is the verb, not a name (#823).
            if (stmt.metadata or {}).get("is_search_all"):
                return ("SEARCH ALL", search_whens, at_end, details)
            return ("SEARCH", search_whens, at_end, details)

        if isinstance(stmt, PerformStatement) and stmt.inline_statements:
            body = tuple(self._fp(s) for s in stmt.inline_statements)
            until = (
                self._norm(render_condition_text(stmt.until_condition))
                if stmt.until_condition
                else ""
            )
            # The TIMES count, VARYING clause and TEST BEFORE/AFTER.
            details = self._details(
                stmt,
                frozenset({"inline_statements", "until_condition", "perform_type"}),
            )
            return ("PERFORM_INLINE", stmt.perform_type, until, body, details)

        # Leaf statement: type + normalized operands, then what the operand
        # list does not carry (#262) -- every present clause body (AT END,
        # ON SIZE ERROR, ...) and the rest of the statement's fields (a
        # COMPUTE formula, ROUNDED, UPON, CORRESPONDING, delimiters, the
        # INSPECT phrase).
        self.leaf_count += 1
        literals = _unquoted_literals(stmt)
        operands = list(getattr(stmt, "operands", []))
        for value in literals.values():
            # The operand list repeats the literal (CALL's target, INVOKE's
            # method name): quote its first occurrence there too.
            if value in operands:
                operands[operands.index(value)] = _quote(value)
        normalized = tuple(self._norm(op) for op in operands)
        details = self._details(stmt, literals=literals)
        fingerprint = (stype, normalized, self._clauses(stmt), details)
        verbatim = _verbatim(stmt)
        return (*fingerprint, verbatim) if verbatim else fingerprint

    def _clauses(self, stmt: Any) -> tuple[Any, ...]:
        return tuple(
            (attr, tuple(self._fp(s) for s in body))
            for attr in _CLAUSE_ATTRS
            if (body := getattr(stmt, attr, None))
        )

    def _details(
        self,
        stmt: Any,
        skip: frozenset[str] = frozenset(),
        literals: dict[str, str] | None = None,
    ) -> Any:
        """The statement's ``to_dict()`` fields, minus position/bookkeeping
        and whatever the caller fingerprints itself (*skip*), with each
        unquoted literal field (*literals*) re-quoted."""
        to_dict = getattr(stmt, "to_dict", None)
        if to_dict is None:
            return None
        data = to_dict()
        for key, value in (literals or {}).items():
            if data.get(key) == value:
                data[key] = _quote(value)
        return self._detail_value(
            {key: value for key, value in data.items() if key not in skip}
        )

    def _detail_value(self, value: Any) -> Any:
        if isinstance(value, dict):
            out = []
            for key, item in value.items():
                key = str(key)
                if _FIELD_KEY_RE.fullmatch(key):
                    if key in _DETAIL_SKIP_KEYS:
                        continue
                else:
                    # A data-name used as a key (OPEN's file -> mode map).
                    key = self._detail_norm(key)
                out.append((key, self._detail_value(item)))
            return tuple(out)
        if isinstance(value, (list, tuple)):
            return tuple(self._detail_value(item) for item in value)
        if isinstance(value, str):
            return self._detail_norm(value)
        if value is None or isinstance(value, (bool, int, float)):
            return value
        return self._detail_norm(str(value))

    def _detail_norm(self, text: str) -> str:
        return _normalize_text(
            text, self._type2, self._id_map, keywords=_DETAIL_KEYWORDS
        )


def _verbatim(stmt: Any) -> tuple[Any, ...]:
    """The words of *stmt* that are keywords, not names, though its detail
    fields hold them as plain values a Type-2 rename would substitute: the
    ACCEPT ... FROM source (DATE, TIME, a mnemonic) and each CALL argument's
    passing mode (BY REFERENCE / CONTENT / VALUE) (#823)."""
    if isinstance(stmt, IOAcceptStatement):
        return (str(getattr(stmt, "from_source", None) or "").upper(),)
    if isinstance(stmt, CallStatement):
        return tuple(str(p.passing_mode).upper() for p in stmt.using_parameters)
    return ()


def _canonical(fingerprint: Any) -> str:
    """Serialize a fingerprint tuple to one deterministic string.

    Written out rather than leaning on ``repr()`` because this string is
    hashed into a digest that travels *between processes and between
    programs* (see :class:`ParagraphFingerprint`): two paragraphs in two
    different files must produce byte-identical text for identical
    structure, on any interpreter, forever. ``repr()`` happens to satisfy
    that today for tuples of ``str``/``None``, but it is a debugging
    representation with no such guarantee, and a future quoting change in
    CPython would silently break every stored digest rather than fail
    loudly.

    Strings are length-prefixed so no content can forge the structure:
    without it, the one-element tuple ``("A,B",)`` and the two-element
    ``("A", "B")`` would serialize alike and two structurally different
    paragraphs would share a digest.
    """
    if fingerprint is None:
        return "N"
    if isinstance(fingerprint, str):
        return f"S{len(fingerprint)}:{fingerprint}"
    if isinstance(fingerprint, tuple):
        return "T(" + ",".join(_canonical(part) for part in fingerprint) + ")"
    # perform_type and friends: a non-str scalar carried through verbatim.
    text = str(fingerprint)
    return f"V{len(text)}:{text}"


# 16 hex characters (64 bits). A workspace scan compares fingerprints across
# every paragraph of every program it read -- tens of thousands in a large
# shop -- and 64 bits keeps the chance of a collision among 100k paragraphs
# around 3e-10. Truncating further to shorten the JSON would trade a real
# correctness property for bytes.
_DIGEST_BYTES = 8


def _digest(fingerprint: Any) -> str:
    return hashlib.blake2b(
        _canonical(fingerprint).encode("utf-8"), digest_size=_DIGEST_BYTES
    ).hexdigest()


@dataclass
class ParagraphFingerprint:
    """One paragraph's structural digests, for clone detection across files.

    :class:`CloneGroup` answers "which paragraphs in *this* program are
    duplicates of each other". The far more common shape of COBOL copy-paste
    is a paragraph cloned into a *different* program, where neither copy is
    duplicated within its own file and no clone group is reported at all.
    Answering that needs the fingerprints themselves rather than the groups
    derived from them, so they are reported here and the grouping is left to
    whoever holds more than one program's report.

    Both digests are always present. A consumer merging across files must
    apply the same precedence the within-program pass does -- group on
    ``type1`` first, and only consider ``type2`` for paragraphs that did not
    land in a Type-1 group -- or a pair of exact clones would be reported
    twice, once under each type.
    """

    name: str
    location: SourceLocation
    statement_count: int
    type1: str
    type2: str
    #: First and last source line of the paragraph's statements (the header
    #: excluded), or None when none carries a location. A scan with copybooks
    #: expanded maps this span through its source map: a body that comes
    #: wholly from one copybook is that copybook's text however many
    #: programs write their own header above it (#470).
    body_lines: tuple[int, int] | None = None

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "name": self.name,
            "location": self.location.to_dict(),
            "statement_count": self.statement_count,
            "type1": self.type1,
            "type2": self.type2,
        }
        if self.body_lines is not None:
            out["body_lines"] = list(self.body_lines)
        return out


@dataclass
class CloneMember:
    """One paragraph participating in a clone group."""

    name: str
    location: SourceLocation
    #: ``"CALC OF S1"`` when the paragraph's name is shared with a paragraph
    #: in another section (the same key ``FlowNode.qualified_name`` and
    #: ``DeadCodeItem.qualified_name`` use), else ``None`` -- the bare name
    #: alone cannot tell the two apart (#555).
    qualified_name: str | None = None

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "name": self.name,
            "location": self.location.to_dict(),
        }
        if self.qualified_name:
            result["qualified_name"] = self.qualified_name
        return result


@dataclass
class CloneGroup:
    """A set of paragraphs sharing an identical structural fingerprint."""

    clone_type: str  # "TYPE_1" (exact) or "TYPE_2" (renamed)
    statement_count: int
    members: list[CloneMember] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "clone_type": self.clone_type,
            "statement_count": self.statement_count,
            "members": [m.to_dict() for m in self.members],
        }


@dataclass
class RedundancyReport:
    """Program-wide redundancy report."""

    program_name: str = ""
    dead_items: list[DeadCodeItem] = field(default_factory=list)
    total_procedures: int = 0
    unused_items: list[UnusedVariableItem] = field(default_factory=list)
    total_variables: int = 0
    clone_groups: list[CloneGroup] = field(default_factory=list)
    #: Every clone-eligible paragraph's digests, in source order. The raw
    #: material `clone_groups` is derived from, reported so a caller holding
    #: several programs' reports can group across them -- see
    #: :class:`ParagraphFingerprint`.
    paragraph_fingerprints: list[ParagraphFingerprint] = field(default_factory=list)

    @property
    def dead_ratio(self) -> float:
        if self.total_procedures == 0:
            return 0.0
        return len(self.dead_items) / self.total_procedures

    @property
    def unused_ratio(self) -> float:
        if self.total_variables == 0:
            return 0.0
        return len(self.unused_items) / self.total_variables

    @property
    def cloned_statement_count(self) -> int:
        """Total statements sitting in a clone (each member's own share)."""
        return sum(g.statement_count * len(g.members) for g in self.clone_groups)

    def to_dict(self) -> dict[str, Any]:
        return {
            "program_name": self.program_name,
            "dead_code": [item.to_dict() for item in self.dead_items],
            "unused_variables": [item.to_dict() for item in self.unused_items],
            "clone_groups": [g.to_dict() for g in self.clone_groups],
            "paragraph_fingerprints": [
                f.to_dict() for f in self.paragraph_fingerprints
            ],
            "summary": {
                "total_procedures": self.total_procedures,
                "dead_procedure_count": len(self.dead_items),
                "dead_ratio": round(self.dead_ratio, 4),
                "total_variables": self.total_variables,
                "unused_variable_count": len(self.unused_items),
                "unused_ratio": round(self.unused_ratio, 4),
                "clone_group_count": len(self.clone_groups),
                "cloned_statement_count": self.cloned_statement_count,
            },
        }


class RedundancyAnalyzer:
    """Detects unreferenced code/data and duplicate (cloned) paragraphs.

    Example:
        ```python
        from cobolparser import parse_cobol
        from cobolparser.analysis.redundancy import RedundancyAnalyzer

        result = parse_cobol(source)
        report = RedundancyAnalyzer().analyze(result.ast)
        print(f"{report.dead_ratio:.0%} dead, {len(report.clone_groups)} clone groups")
        ```
    """

    def analyze(
        self, ast: CobolProgram, *, min_clone_statements: int = 3
    ) -> RedundancyReport:
        """Analyze a COBOL program for redundancy.

        Args:
            ast: The parsed COBOL program AST.
            min_clone_statements: Minimum leaf-statement count a paragraph
                must have to be eligible for clone-group reporting; below
                this, two trivially-small paragraphs (e.g. a bare ``EXIT.``)
                matching each other isn't meaningful redundancy.

        Returns:
            A RedundancyReport combining dead-code/unused-variable ratios
            with detected duplicate-paragraph clone groups.
        """
        dead_report = DeadCodeAnalyzer().analyze(ast)
        unused_report = UnusedVariableAnalyzer().analyze(ast)

        report = RedundancyReport(
            program_name=ast.program_name,
            dead_items=dead_report.dead_items,
            total_procedures=dead_report.total_procedures,
            unused_items=unused_report.unused_items,
            total_variables=unused_report.total_variables,
        )

        proc_division = ast.procedure_division
        if proc_division is not None:
            report.clone_groups = self._find_clone_groups(
                proc_division, min_clone_statements
            )
            report.paragraph_fingerprints = self._paragraph_fingerprints(
                proc_division, min_clone_statements
            )

        return report

    @staticmethod
    def _collect_paragraphs(proc_division: CobolDivision) -> list[CobolParagraph]:
        paragraphs: list[CobolParagraph] = []
        for section in proc_division._sections.values():
            paragraphs.extend(section.paragraphs)
        paragraphs.extend(proc_division.paragraphs)
        return paragraphs

    def _paragraph_fingerprints(
        self, proc_division: CobolDivision, min_clone_statements: int
    ) -> list[ParagraphFingerprint]:
        """Both digests for every paragraph large enough to be a clone.

        A pass of its own rather than a restructuring of
        ``_find_clone_groups`` to compute and return both at once. That
        would save one fingerprinting sweep, but it would also rewrite the
        Type-1/Type-2 precedence logic that this module's tests pin
        precisely, and fingerprinting is a tuple walk over an already-parsed
        AST -- immaterial next to the parse that produced it. The two agree
        because both build their fingerprints through the same
        ``_Fingerprinter`` over the same ``_collect_paragraphs`` order.

        ``min_clone_statements`` is applied here for the same reason
        ``_find_clone_groups`` applies it: a paragraph too small to be
        meaningful redundancy inside one program is no more meaningful
        across two, and emitting every three-line paragraph in a 5,000-file
        shop would dominate a scan's output for nothing.
        """
        out: list[ParagraphFingerprint] = []
        for para in self._collect_paragraphs(proc_division):
            if not para.paragraph_name:
                continue
            exact = _Fingerprinter(type2=False)
            exact_fp = exact.fingerprint_paragraph(para)
            # leaf_count is only populated by the walk above, so read it
            # after fingerprinting, never before.
            if exact.leaf_count == 0 or exact.leaf_count < min_clone_statements:
                continue
            renamed = _Fingerprinter(type2=True)
            renamed_fp = renamed.fingerprint_paragraph(para)
            out.append(
                ParagraphFingerprint(
                    # Uppercased to match CloneMember and every other
                    # analyzer's procedure-name convention, so a consumer can
                    # join a fingerprint to a dead-code or complexity entry
                    # by name without re-casing either side.
                    name=para.paragraph_name.upper(),
                    location=para.location,
                    statement_count=exact.leaf_count,
                    type1=_digest(exact_fp),
                    type2=_digest(renamed_fp),
                    body_lines=self._body_lines(para),
                )
            )
        return out

    @staticmethod
    def _body_lines(para: CobolParagraph) -> tuple[int, int] | None:
        """The span of source lines *para*'s statements occupy, nested ones
        included; None when no statement has a line."""
        lines = [
            node.location.line
            for stmt in para.statements
            for node in stmt.traverse_depth_first()
            if getattr(node, "location", None) is not None and node.location.line > 0
        ]
        return (min(lines), max(lines)) if lines else None

    def _find_clone_groups(
        self, proc_division: CobolDivision, min_clone_statements: int
    ) -> list[CloneGroup]:
        paragraphs = self._collect_paragraphs(proc_division)
        qualified = {
            id(entry.node): entry.qualified_name
            for entry in ProcedureIndex.build(proc_division).entries
        }

        type1_buckets = self._bucket_by_fingerprint(paragraphs, type2=False)
        type1_groups = self._groups_from_buckets(
            type1_buckets, type2=False, qualified=qualified
        )
        # Any pair that's already a Type-1 match is a Type-1 match, not also
        # a "renamed" one -- Type-2 grouping only runs over paragraphs that
        # didn't already land in a Type-1 group of size >= 2, so every
        # paragraph is reported in exactly one clone group. Excluded by
        # identity, never by name: a paragraph name may repeat across
        # sections, and one ``P1`` in a Type-1 group must not take every
        # other section's ``P1`` out of Type-2 grouping with it (#353).
        type1_ids = {
            id(p)
            for members, _ in type1_buckets.values()
            if len(members) >= 2
            for p in members
        }
        remaining = [p for p in paragraphs if id(p) not in type1_ids]
        type2_groups = self._group_by_fingerprint(
            remaining, type2=True, qualified=qualified
        )

        groups = [g for g in type1_groups if len(g.members) >= 2] + [
            g for g in type2_groups if len(g.members) >= 2
        ]
        return [g for g in groups if g.statement_count >= min_clone_statements]

    @staticmethod
    def _bucket_by_fingerprint(
        paragraphs: list[CobolParagraph], *, type2: bool
    ) -> dict[Any, tuple[list[CobolParagraph], int]]:
        """Paragraphs bucketed by fingerprint, each with its leaf count."""
        buckets: dict[Any, tuple[list[CobolParagraph], int]] = {}
        for para in paragraphs:
            if not para.paragraph_name:
                continue
            fp = _Fingerprinter(type2=type2)
            fingerprint = fp.fingerprint_paragraph(para)
            if fp.leaf_count == 0:
                continue
            members, _ = buckets.get(fingerprint, ([], 0))
            members.append(para)
            buckets[fingerprint] = (members, fp.leaf_count)
        return buckets

    @classmethod
    def _group_by_fingerprint(
        cls,
        paragraphs: list[CobolParagraph],
        *,
        type2: bool,
        qualified: dict[int, str | None] | None = None,
    ) -> list[CloneGroup]:
        return cls._groups_from_buckets(
            cls._bucket_by_fingerprint(paragraphs, type2=type2),
            type2=type2,
            qualified=qualified,
        )

    @staticmethod
    def _groups_from_buckets(
        buckets: dict[Any, tuple[list[CobolParagraph], int]],
        *,
        type2: bool,
        qualified: dict[int, str | None] | None = None,
    ) -> list[CloneGroup]:
        qualified = qualified or {}
        groups = []
        for members, leaf_count in buckets.values():
            groups.append(
                CloneGroup(
                    clone_type="TYPE_2" if type2 else "TYPE_1",
                    statement_count=leaf_count,
                    members=[
                        # Uppercased to match the convention every other
                        # analyzer uses for procedure names (DeadCodeItem,
                        # FlowNode, ...) -- callers like
                        # TechnicalDebtAnalyzer match clone membership by
                        # name against those always-uppercase sets.
                        CloneMember(
                            name=p.paragraph_name.upper(),
                            location=p.location,
                            qualified_name=qualified.get(id(p)),
                        )
                        for p in members
                    ],
                )
            )
        # Deterministic ordering for stable output: largest groups first,
        # then by first member's name.
        groups.sort(key=lambda g: (-len(g.members), g.members[0].name))
        return groups
