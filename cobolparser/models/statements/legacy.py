"""Legacy, dialect, and compiler-directing statement AST nodes.

* OS/VS COBOL verbs still found in migrated IBM code: ``EXHIBIT``,
  ``EXAMINE``, ``TRANSFORM``.
* IBM compiler-directing / debugging statements that syntactically live in
  the PROCEDURE DIVISION: ``READY TRACE`` / ``RESET TRACE``,
  ``SERVICE LABEL`` / ``SERVICE RELOAD``, ``ENTER``, ``TITLE``.
* COBOL-74 ``NOTE`` (a comment statement) and Micro Focus ``CHAIN``.

Every one of these previously reached the PROCEDURE DIVISION's
"unsupported statement" path and was discarded from the AST.
"""

from typing import Any

from ..ast_base import SourceLocation
from .base import CobolStatement


class ExhibitStatement(CobolStatement):
    """AST node for ``EXHIBIT [NAMED | CHANGED NAMED | CHANGED] item...``."""

    def __init__(self, location: SourceLocation):
        super().__init__("EXHIBIT", location)
        self.mode: str | None = None  # NAMED / CHANGED / CHANGED NAMED
        self.items: list[str] = []

    def set_mode(self, mode: str) -> None:
        self.mode = mode.upper()

    def add_item(self, item: str) -> None:
        self.items.append(item)
        self._add_unique_operand(item)

    def to_dict(self) -> dict[str, Any]:
        result = super().to_dict()
        result.update({"mode": self.mode, "items": list(self.items)})
        return result


class ExamineStatement(CobolStatement):
    """AST node for the OS/VS COBOL EXAMINE statement.

    Syntax::

        EXAMINE identifier TALLYING {ALL | LEADING | UNTIL FIRST} literal
                                    [REPLACING BY literal]
        EXAMINE identifier REPLACING {ALL | LEADING | FIRST | UNTIL FIRST}
                                     literal BY literal
    """

    def __init__(self, location: SourceLocation):
        super().__init__("EXAMINE", location)
        self.target: str | None = None
        self.action: str | None = None  # TALLYING / REPLACING
        self.mode: str | None = None  # ALL / LEADING / FIRST / UNTIL FIRST
        self.search_value: str | None = None
        self.replacing_value: str | None = None  # value after BY

    def set_target(self, name: str) -> None:
        self.target = name
        self._add_unique_operand(name)

    def to_dict(self) -> dict[str, Any]:
        result = super().to_dict()
        result.update(
            {
                "target": self.target,
                "action": self.action,
                "mode": self.mode,
                "search_value": self.search_value,
                "replacing_value": self.replacing_value,
            }
        )
        return result


class TransformStatement(CobolStatement):
    """AST node for ``TRANSFORM identifier CHARACTERS FROM x TO y``."""

    def __init__(self, location: SourceLocation):
        super().__init__("TRANSFORM", location)
        self.target: str | None = None
        self.from_value: str | None = None
        self.to_value: str | None = None

    def set_target(self, name: str) -> None:
        self.target = name
        self._add_unique_operand(name)

    def to_dict(self) -> dict[str, Any]:
        result = super().to_dict()
        result.update(
            {
                "target": self.target,
                "from_value": self.from_value,
                "to_value": self.to_value,
            }
        )
        return result


class EnterStatement(CobolStatement):
    """AST node for ``ENTER language-name [routine-name]`` (IBM treats it as
    a comment; kept so the statement is visible rather than discarded)."""

    def __init__(self, location: SourceLocation):
        super().__init__("ENTER", location)
        self.language: str | None = None
        self.routine: str | None = None

    def to_dict(self) -> dict[str, Any]:
        result = super().to_dict()
        result.update({"language": self.language, "routine": self.routine})
        return result


class NoteStatement(CobolStatement):
    """AST node for the COBOL-74 ``NOTE`` comment statement (text up to the
    sentence period)."""

    def __init__(self, location: SourceLocation):
        super().__init__("NOTE", location)
        self.text: str = ""

    def to_dict(self) -> dict[str, Any]:
        result = super().to_dict()
        result["text"] = self.text
        return result


class ChainStatement(CobolStatement):
    """AST node for the Micro Focus ``CHAIN {literal | identifier} [USING ...]``
    statement (transfer control to another program without return)."""

    def __init__(self, location: SourceLocation):
        super().__init__("CHAIN", location)
        self.program: str | None = None
        self.is_dynamic: bool = False
        self.using_parameters: list[str] = []

    def set_program(self, name: str, *, is_dynamic: bool) -> None:
        self.program = name
        self.is_dynamic = is_dynamic
        self._add_unique_operand(name)

    def add_using_parameter(self, name: str) -> None:
        self.using_parameters.append(name)
        self._add_unique_operand(name)

    def to_dict(self) -> dict[str, Any]:
        result = super().to_dict()
        result.update(
            {
                "program": self.program,
                "is_dynamic": self.is_dynamic,
                "using_parameters": list(self.using_parameters),
            }
        )
        return result


class TraceStatement(CobolStatement):
    """AST node for the IBM debugging statements ``READY TRACE`` and
    ``RESET TRACE``. ``action`` is ``"READY"`` or ``"RESET"``."""

    def __init__(self, location: SourceLocation, action: str):
        super().__init__("TRACE", location)
        self.action: str = action.upper()

    def to_dict(self) -> dict[str, Any]:
        result = super().to_dict()
        result["action"] = self.action
        return result


class ServiceStatement(CobolStatement):
    """AST node for IBM ``SERVICE LABEL`` and ``SERVICE RELOAD identifier``."""

    def __init__(self, location: SourceLocation):
        super().__init__("SERVICE", location)
        self.kind: str | None = None  # LABEL / RELOAD
        self.operand: str | None = None  # RELOAD's identifier

    def to_dict(self) -> dict[str, Any]:
        result = super().to_dict()
        result.update({"kind": self.kind, "operand": self.operand})
        return result


class TitleStatement(CobolStatement):
    """AST node for the IBM ``TITLE literal`` compiler-directing statement
    (listing title; no runtime effect -- the same class as EJECT/SKIP)."""

    def __init__(self, location: SourceLocation):
        super().__init__("TITLE", location)
        self.title: str | None = None

    def to_dict(self) -> dict[str, Any]:
        result = super().to_dict()
        result["title"] = self.title
        return result


__all__ = [
    "ExhibitStatement",
    "ExamineStatement",
    "TransformStatement",
    "EnterStatement",
    "NoteStatement",
    "ChainStatement",
    "TraceStatement",
    "ServiceStatement",
    "TitleStatement",
]
