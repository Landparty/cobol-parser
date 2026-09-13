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
    verbatim.
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

from ..models.ast_base import SourceLocation
from ..models.program import CobolDivision, CobolParagraph, CobolProgram
from ..models.statements.control import (
    EvaluateStatement,
    IfStatement,
    PerformStatement,
    SearchStatement,
)
from ._names import IDENTIFIER_TOKEN_RE
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

_QUOTED_TEXT_RE = re.compile(r"'[^']*'|\"[^\"]*\"")


def _normalize_text(text: str, type2: bool, id_map: dict[str, str]) -> str:
    """Normalize one operand/condition-text string for fingerprinting.

    Type-1 (``type2=False``) returns *text* verbatim. Type-2 replaces every
    identifier-shaped token (skipping quoted substrings, so literal text is
    never touched) with a per-paragraph positional placeholder (``ID1``,
    ``ID2``, ...), assigned in first-seen order and reused on repeat -- so
    ``MOVE WS-A TO WS-B`` and ``MOVE WS-X TO WS-Y`` both normalize to ``MOVE
    ID1 TO ID2``, but a paragraph that references the same name twice keeps
    that repetition visible (``ID1 ... ID1``, not two different IDs).
    """
    if not text or not type2:
        return text

    # Protect quoted substrings from identifier substitution by splitting on
    # them first (mirrors unused_variables.py's own quoted-text handling).
    pieces = []
    last = 0
    for m in _QUOTED_TEXT_RE.finditer(text):
        pieces.append(("text", text[last : m.start()]))
        pieces.append(("quoted", m.group(0)))
        last = m.end()
    pieces.append(("text", text[last:]))

    def repl(m: re.Match[str]) -> str:
        tok = m.group(0)
        if tok.upper() in _NON_IDENTIFIER_WORDS:
            return tok
        return id_map.setdefault(tok.upper(), f"ID{len(id_map) + 1}")

    out = []
    for kind, chunk in pieces:
        if kind == "quoted":
            out.append(chunk)
        else:
            out.append(IDENTIFIER_TOKEN_RE.sub(repl, chunk))
    return "".join(out)


def _selector_text(selector: Any) -> str:
    """Compact text for one EVALUATE WHEN selector dict."""
    if not isinstance(selector, dict):
        return str(selector)
    sel_type = selector.get("type", "")
    if sel_type == "Range":
        return f"RANGE:{selector.get('start', '')}..{selector.get('end', '')}"
    if sel_type == "Condition":
        return f"COND:{selector.get('text', '')}"
    return f"{sel_type}:{selector.get('value', '')}"


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
            return ("SEARCH", search_whens, at_end)

        if isinstance(stmt, PerformStatement) and stmt.inline_statements:
            body = tuple(self._fp(s) for s in stmt.inline_statements)
            until = (
                self._norm(render_condition_text(stmt.until_condition))
                if stmt.until_condition
                else ""
            )
            return ("PERFORM_INLINE", stmt.perform_type, until, body)

        # Leaf statement: type + normalized operands.
        self.leaf_count += 1
        operands = tuple(self._norm(op) for op in getattr(stmt, "operands", []))
        return (stype, operands)


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

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "location": self.location.to_dict(),
            "statement_count": self.statement_count,
            "type1": self.type1,
            "type2": self.type2,
        }


@dataclass
class CloneMember:
    """One paragraph participating in a clone group."""

    name: str
    location: SourceLocation

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "location": self.location.to_dict()}


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
                )
            )
        return out

    def _find_clone_groups(
        self, proc_division: CobolDivision, min_clone_statements: int
    ) -> list[CloneGroup]:
        paragraphs = self._collect_paragraphs(proc_division)

        type1_groups = self._group_by_fingerprint(paragraphs, type2=False)
        # Any pair that's already a Type-1 match is a Type-1 match, not also
        # a "renamed" one -- Type-2 grouping only runs over paragraphs that
        # didn't already land in a Type-1 group of size >= 2, so every
        # paragraph is reported in exactly one clone group.
        type1_names = {
            m.name for g in type1_groups if len(g.members) >= 2 for m in g.members
        }
        remaining = [
            p
            for p in paragraphs
            if p.paragraph_name and p.paragraph_name.upper() not in type1_names
        ]
        type2_groups = self._group_by_fingerprint(remaining, type2=True)

        groups = [g for g in type1_groups if len(g.members) >= 2] + [
            g for g in type2_groups if len(g.members) >= 2
        ]
        return [g for g in groups if g.statement_count >= min_clone_statements]

    @staticmethod
    def _group_by_fingerprint(
        paragraphs: list[CobolParagraph], *, type2: bool
    ) -> list[CloneGroup]:
        buckets: dict[Any, list[CobolParagraph]] = {}
        leaf_counts: dict[Any, int] = {}
        for para in paragraphs:
            if not para.paragraph_name:
                continue
            fp = _Fingerprinter(type2=type2)
            fingerprint = fp.fingerprint_paragraph(para)
            if fp.leaf_count == 0:
                continue
            buckets.setdefault(fingerprint, []).append(para)
            leaf_counts[fingerprint] = fp.leaf_count

        groups = []
        for fingerprint, members in buckets.items():
            groups.append(
                CloneGroup(
                    clone_type="TYPE_2" if type2 else "TYPE_1",
                    statement_count=leaf_counts[fingerprint],
                    members=[
                        # Uppercased to match the convention every other
                        # analyzer uses for procedure names (DeadCodeItem,
                        # FlowNode, ...) -- callers like
                        # TechnicalDebtAnalyzer match clone membership by
                        # name against those always-uppercase sets, and
                        # `_find_clone_groups`'s own Type-1/Type-2 dedup
                        # below compares against `.upper()` too.
                        CloneMember(name=p.paragraph_name.upper(), location=p.location)
                        for p in members
                    ],
                )
            )
        # Deterministic ordering for stable output: largest groups first,
        # then by first member's name.
        groups.sort(key=lambda g: (-len(g.members), g.members[0].name))
        return groups
