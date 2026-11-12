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

import copy
import json
from collections.abc import Iterator
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


#: Default size budget of one serialized result, in bytes (``--max-answer-
#: bytes``): about 6k tokens. A larger answer is mostly lists a model skims.
DEFAULT_ANSWER_BYTES = 24_000


def _size(value: Any) -> int:
    return len(json.dumps(value, default=str, separators=(",", ":")))


def wire_text(result: dict[str, Any]) -> str:
    """The text copy of *result* the server sends beside its structured
    copy: compact JSON, so the two together cost about twice the answer
    rather than the three times a pretty-printed copy would."""
    return json.dumps(result, default=str, separators=(",", ":"))


def wire_size(result: dict[str, Any]) -> int:
    """Bytes *result* costs on the wire: its ``structuredContent`` plus its
    text copy, the latter once more JSON-escaped inside the response."""
    return _size(result) + len(json.dumps(wire_text(result)))


#: A string is shortened by the budget only when it is longer than this.
_MIN_CUT_CHARS = 200


def _strings(node: Any, path: str) -> Iterator[tuple[str, str, Any, Any]]:
    """Every string under *node* as ``(dotted path, text, parent, key)``."""
    if isinstance(node, dict):
        for key, value in node.items():
            sub = f"{path}.{key}" if path else str(key)
            if isinstance(value, str):
                yield sub, value, node, key
            else:
                yield from _strings(value, sub)
    elif isinstance(node, list):
        for number, value in enumerate(node):
            sub = f"{path}[{number}]"
            if isinstance(value, str):
                yield sub, value, node, number
            else:
                yield from _strings(value, sub)


def _lists(node: Any, path: str) -> Iterator[tuple[str, list[Any], Any, Any]]:
    """Every list under *node* as ``(dotted path, list, parent, key)``."""
    if isinstance(node, dict):
        for key, value in node.items():
            sub = f"{path}.{key}" if path else str(key)
            if isinstance(value, list):
                yield sub, value, node, key
            yield from _lists(value, sub)
    elif isinstance(node, list):
        for number, value in enumerate(node):
            yield from _lists(value, f"{path}[{number}]")


def fit_budget(result: dict[str, Any], max_bytes: int | None) -> dict[str, Any]:
    """*result* with its answer's longest lists halved until the whole
    result fits in *max_bytes*, each cut recorded in ``truncated`` (with
    ``reason: "answer budget"``) like a ``limit`` cut. Lists are cut from
    the end, so an item that refers to an earlier one (``from_hit``) still
    finds it. A list is never cut below one item.

    The size measured is the wire size (:func:`wire_size`): the structured
    copy plus the text copy the server sends with it. When every list is
    down to one item and the result is still over, the answer's longest
    strings (source text, long descriptions) are halved in turn, each cut
    recorded with ``shown_chars`` and ``total_chars``. Then the envelope
    is trimmed (:func:`_trim_envelope`): hints, caveats, the cut records."""
    if not max_bytes or wire_size(result) <= max_bytes:
        return result
    answer = result.get("answer")
    truncated: list[dict[str, Any]] = result.setdefault("truncated", [])
    while wire_size(result) > max_bytes:
        candidates = [
            (_size(items), path, items, parent, key)
            for path, items, parent, key in _lists(answer, "")
            if len(items) > 1
        ]
        if not candidates:
            break
        _, path, items, parent, key = max(candidates, key=lambda c: c[0])
        keep = len(items) // 2
        entry = next((t for t in truncated if t.get("field") == path), None)
        if entry is None:
            truncated.append(
                {
                    "field": path,
                    "shown": keep,
                    "total": len(items),
                    "reason": "answer budget",
                }
            )
        else:
            entry["shown"] = keep
            entry["reason"] = "answer budget"
        parent[key] = items[:keep]
    while wire_size(result) > max_bytes:
        texts = [
            (len(text), path, text, parent, key)
            for path, text, parent, key in _strings(answer, "")
            if len(text) > _MIN_CUT_CHARS
        ]
        if not texts:
            break
        _, path, text, parent, key = max(texts, key=lambda c: c[0])
        keep = len(text) // 2
        entry = next((t for t in truncated if t.get("field") == path), None)
        if entry is None:
            truncated.append(
                {
                    "field": path,
                    "shown_chars": keep,
                    "total_chars": len(text),
                    "reason": "answer budget",
                }
            )
        else:
            entry["shown_chars"] = keep
        parent[key] = text[:keep]
    if wire_size(result) > max_bytes:
        _trim_envelope(result, max_bytes, truncated)
    return result


def _trim_envelope(
    result: dict[str, Any], max_bytes: int, truncated: list[dict[str, Any]]
) -> None:
    """Last resort once the answer is down to one item per list and still
    over: the envelope around it, which a small budget on a large root could
    not fit (``codebase_overview`` asked for 2 KB answered 4.4 KB, most of it
    caveats and the record of its own cuts).

    In order, each step only while the result is still over: the ``next``
    hints go (they only suggest calls); the caveats are halved from the end,
    never below one, with a ``caveats`` entry in ``truncated``; the ``answer
    budget`` entries are folded into one that names every cut field
    (``field``, comma-separated) and counts them (``fields``); and the
    answer's one-item lists are emptied, largest first, each named in that
    folded entry -- only when emptying them all would fit, else they keep
    their one item. Scalars and short strings are never dropped, so a budget
    below them still cannot be met."""
    if result.get("next"):
        result.pop("next")
    caveats = result.get("caveats")
    if isinstance(caveats, list) and len(caveats) > 1:
        total = len(caveats)
        while wire_size(result) > max_bytes and len(caveats) > 1:
            del caveats[max(1, len(caveats) // 2) :]
        if len(caveats) < total:
            truncated.append(
                {
                    "field": "caveats",
                    "shown": len(caveats),
                    "total": total,
                    "reason": "answer budget",
                }
            )
    if wire_size(result) <= max_bytes:
        return
    fields = [
        str(t.get("field")) for t in truncated if t.get("reason") == "answer budget"
    ]
    folded: dict[str, Any] = {"field": "", "fields": 0, "reason": "answer budget"}
    truncated[:] = [t for t in truncated if t.get("reason") != "answer budget"]
    truncated.append(folded)

    def refold() -> None:
        folded["field"] = ", ".join(fields)
        folded["fields"] = len(fields)

    refold()
    answer = result.get("answer")
    if not _fits_without_lists(result, max_bytes):
        # Emptying every list still would not fit: keep the one item each
        # rather than lose them for nothing.
        return
    while wire_size(result) > max_bytes:
        candidates = [
            (_size(items), path, items, parent, key)
            for path, items, parent, key in _lists(answer, "")
            if items
        ]
        if not candidates:
            break
        _, path, _items, parent, key = max(candidates, key=lambda c: c[0])
        parent[key] = []
        if path not in fields:
            fields.append(path)
            refold()


def _fits_without_lists(result: dict[str, Any], max_bytes: int) -> bool:
    """Whether *result* would fit with every list in its answer emptied."""
    trial = copy.deepcopy(result)
    for _path, _items, parent, key in list(_lists(trial.get("answer"), "")):
        parent[key] = []
    return wire_size(trial) <= max_bytes
