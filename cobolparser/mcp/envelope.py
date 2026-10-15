"""The one response shape every MCP tool returns.

A model reading a tool result needs three things besides the answer: where
each fact is (``file:line`` in the file on disk), what could *not* be checked,
and whether a list it is reading was cut short. Each tool builds its own
``answer``; this module owns the rest, so the three are spelled the same way
in every tool and a client can branch on them without reading prose.

``caveats[].kind`` is a closed vocabulary (:data:`CAVEAT_KINDS`). A new kind
is a change to the surface, so it bumps :data:`MCP_SURFACE_VERSION`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, TypeVar

#: Version of the tool names, argument names and envelope shape. Bumped on
#: any change a client could notice, the way ``bundle_version`` is for
#: fixture bundles.
MCP_SURFACE_VERSION = "1"

#: Every ``caveats[].kind`` a tool may emit.
CAVEAT_KINDS: tuple[str, ...] = (
    # A COPY member was not expanded: its declarations are missing, so
    # anything about unused / undeclared names is incomplete.
    "unresolved-copybook",
    # The parse recovered from errors; part of the program is unexamined.
    "partial-parse",
    # An analyzer raised; its part of the answer is missing, the rest stands.
    "analyzer-failed",
    # An analyzer ran but says it could not examine everything.
    "incomplete-analysis",
    # More than one declaration matches the name asked about.
    "ambiguous-name",
    # The name is declared more than once in one namespace, and every
    # reference was attributed to the first declaration.
    "duplicate-declaration",
    # A location that the source map could not place in a file on disk.
    "unmapped-location",
    # The file holds several program units and the answer covers one.
    "program-unit-selected",
)

#: Default and maximum length of any list in an answer.
DEFAULT_LIMIT = 50
MAX_LIMIT = 500

T = TypeVar("T")


class ToolError(Exception):
    """A request the tool cannot answer at all (bad path, unknown program).

    Returned to the client as an error result naming the problem, never as
    an empty answer that would read as "nothing found".
    """


@dataclass(frozen=True)
class Caveat:
    """One limit on how far an answer can be trusted."""

    kind: str
    detail: str
    effect: str | None = None

    def __post_init__(self) -> None:
        if self.kind not in CAVEAT_KINDS:
            raise ValueError(f"unknown caveat kind: {self.kind}")

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {"kind": self.kind, "detail": self.detail}
        if self.effect:
            result["effect"] = self.effect
        return result


def clamp_limit(limit: int | None) -> int:
    """*limit* as a usable list length: the default for None, within bounds."""
    if limit is None:
        return DEFAULT_LIMIT
    return max(1, min(int(limit), MAX_LIMIT))


class Response:
    """Collects caveats and truncations while a tool builds its answer."""

    def __init__(self) -> None:
        self.caveats: list[Caveat] = []
        self.truncated: list[dict[str, Any]] = []

    def caveat(self, kind: str, detail: str, effect: str | None = None) -> None:
        candidate = Caveat(kind, detail, effect)
        if candidate not in self.caveats:
            self.caveats.append(candidate)

    def cap(self, items: list[T], limit: int, field_name: str) -> list[T]:
        """The first *limit* of *items*, recording the cut when there is one."""
        if len(items) <= limit:
            return items
        self.truncated.append(
            {"field": field_name, "shown": limit, "total": len(items)}
        )
        return items[:limit]

    def build(
        self, answer: dict[str, Any], program: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        result: dict[str, Any] = {
            "surface_version": MCP_SURFACE_VERSION,
            "answer": answer,
            "caveats": [c.to_dict() for c in self.caveats],
            "truncated": list(self.truncated),
        }
        if program is not None:
            result["program"] = program
        return result
