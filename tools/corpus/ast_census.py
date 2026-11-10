"""The same census as ``census.py``, read from a parsed AST instead of source.

Each count here has a counterpart in :class:`census.Census` so the harness can
diff the two. Statement nodes are mapped back to the verb that starts them.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from census import LISTING_WORDS

from cobolparser.models.walk import all_paragraphs, own_statements

# Statement class name -> verb, where stripping "Statement" is not enough.
_CLASS_VERB = {
    "GoStatement": "GO",
    "ExecCicsStatement": "EXEC",
    "ExecSQLStatement": "EXEC",
    "ExecImsStatement": "EXEC",
    "DynamicSQLStatement": "EXEC",
    "DeclareCursorStatement": "EXEC",
    "DeclareTableStatement": "EXEC",
    "FetchStatement": "EXEC",
    "NextSentenceStatement": "NEXT SENTENCE",
    "IOAcceptStatement": "ACCEPT",
    "IOCloseStatement": "CLOSE",
    "IODeleteStatement": "DELETE",
    "IOOpenStatement": "OPEN",
    "IOReadStatement": "READ",
    "IORewriteStatement": "REWRITE",
    "IOStartStatement": "START",
    "IOUnlockStatement": "UNLOCK",
    "IOWriteStatement": "WRITE",
    "SkipStatement": "SKIP1",
}

_DATA_NODE_TYPES = frozenset({"CobolDataItem", "ConditionNameItem", "RenamesItem"})

# Statement classes that are not statements of the PROCEDURE DIVISION.
_NOT_PROCEDURE = frozenset({"SelectStatement", "CopyStatement"})

# Node class names that mean "the parser gave up here".
_ERROR_HINTS = ("Unknown", "Unparsed", "Error", "Invalid")


@dataclass
class AstCensus:
    verbs: Counter[str] = field(default_factory=Counter)
    paragraphs: list[str] = field(default_factory=list)
    sections: list[str] = field(default_factory=list)
    data_entries: int = 0
    data_entries_by_level: Counter[int] = field(default_factory=Counter)
    units: int = 0
    error_nodes: list[str] = field(default_factory=list)


def statement_verb(stmt: Any) -> str:
    cls = type(stmt).__name__
    if cls in _CLASS_VERB:
        return _CLASS_VERB[cls]
    if cls == "XmlJsonStatement":
        return str(stmt.verb).upper()
    if cls == "TraceStatement":
        return str(stmt.action).upper()
    if cls == "StopStatement":
        return "STOP"
    return cls.removesuffix("Statement").upper()


def _walk(node: Any) -> Any:
    stack = [node]
    seen: set[int] = set()
    while stack:
        cur = stack.pop()
        if id(cur) in seen:
            continue
        seen.add(id(cur))
        yield cur
        stack.extend(reversed(getattr(cur, "children", []) or []))


def ast_census(program: Any) -> AstCensus:
    result = AstCensus()
    for unit in program.program_units():
        result.units += 1
        for stmt in own_statements(unit):
            cls = type(stmt).__name__
            if cls in _NOT_PROCEDURE:
                continue
            verb = statement_verb(stmt)
            if verb in LISTING_WORDS:
                continue
            result.verbs[verb] += 1
        proc = unit.procedure_division
        if proc is not None:
            for para in all_paragraphs(proc):
                name = getattr(para, "paragraph_name", "")
                # A nameless paragraph holds the statements written before
                # the first header of a division or section; the source has
                # no header for it to match.
                if name:
                    result.paragraphs.append(str(name).upper())
            for node in _walk(proc):
                if type(node).__name__ == "CobolSection":
                    result.sections.append(str(node.section_name or "").upper())
        data = unit.data_division
        if data is not None:
            for node in _walk(data):
                cls = type(node).__name__
                if cls in _DATA_NODE_TYPES and not _in_skipped_section(node):
                    result.data_entries += 1
                    level = getattr(node, "level", None)
                    if level is None and cls == "ConditionNameItem":
                        level = 88
                    if level is None and cls == "RenamesItem":
                        level = 66
                    if isinstance(level, int):
                        result.data_entries_by_level[level] += 1
        for node in _walk(unit):
            cls = type(node).__name__
            if any(h in cls for h in _ERROR_HINTS):
                result.error_nodes.append(cls)
    return result


def _in_skipped_section(node: Any) -> bool:
    cur = node.parent
    while cur is not None:
        if type(cur).__name__ == "CobolSection":
            name = str(cur.section_name or "").upper()
            return name.split("-")[0].split(" ")[0] in {
                "REPORT",
                "SCREEN",
                "COMMUNICATION",
            }
        cur = cur.parent
    return False
