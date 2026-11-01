"""Link-edit control decks under the root (``link/epsmlist.lnk``).

A binder deck says which object modules are bound into one load module:

    INCLUDE SYSLMOD(EPSMPMT)
    INCLUDE SYSLIB(EPSMLIST)
    NAME EPSMLIST(R)

so EPSMLIST's load module carries EPSMPMT with it, statically bound: a
``CALL 'EPSMPMT'`` from it resolves at bind time, not through the load
library. Only decks kept as files of their own are read (by suffix), not
SYSLIN in-stream in a JCL step.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .workspace import Stamp, Workspace

#: Suffixes of the files read as link-edit decks.
LINK_DECK_SUFFIXES = frozenset({".lnk", ".lked", ".lkd", ".lkedit", ".link", ".bind"})

_INCLUDE_RE = re.compile(r"^INCLUDE\s+(.*)$")
#: ``DDNAME(MEMBER,MEMBER)`` or a bare ``MEMBER`` (an object from SYSLIN).
_INCLUDED_RE = re.compile(r"([A-Z0-9@#$]+)\s*(?:\(([^)]*)\))?")
_NAME_RE = re.compile(r"^NAME\s+([A-Z0-9@#$]+)")
_ENTRY_RE = re.compile(r"^ENTRY\s+([A-Z0-9@#$]+)")


@dataclass
class LinkDeck:
    """One deck: the load module it names and what it binds into it."""

    file: str
    #: The ``NAME`` statement's member, or the file's stem when it has none.
    load_module: str
    entry: str | None = None
    #: ``{"member", "library", "line"}`` per INCLUDEd member, in order.
    includes: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        row: dict[str, Any] = {
            "deck": self.file,
            "load_module": self.load_module,
            "includes": [
                f"{i['member']}"
                + (f" (from {i['library']})" if i["library"] else "")
                + f" at line {i['line']}"
                for i in self.includes
            ],
        }
        if self.entry:
            row["entry"] = self.entry
        return row


def parse_decks(text: str, file: str) -> list[LinkDeck]:
    """The load modules one deck builds (columns 2-71; ``*`` comment lines
    skipped).

    Each ``NAME`` statement closes the load module built so far: it gets
    the INCLUDE and ENTRY statements read since the previous ``NAME``.
    Statements after the last ``NAME`` (or in a deck with none) form a load
    module named after the file's stem. A statement whose operand field
    ends with a comma continues on the next record (``INCLUDE
    SYSLIB(MODA,`` / ``MODB)``).
    """
    decks: list[LinkDeck] = []
    entry: str | None = None
    includes: list[dict[str, Any]] = []
    for number, card in _statements(text):
        found = _INCLUDE_RE.match(card)
        if found:
            includes.extend(_included(found.group(1).split(" ")[0], number))
            continue
        found = _NAME_RE.match(card)
        if found:
            decks.append(LinkDeck(file, found.group(1), entry, includes))
            entry, includes = None, []
            continue
        found = _ENTRY_RE.match(card)
        if found:
            entry = found.group(1)
    if includes or entry or not decks:
        decks.append(LinkDeck(file, Path(file).stem.upper(), entry, includes))
    return decks


def parse_deck(text: str, file: str) -> LinkDeck:
    """The first load module of a deck (see :func:`parse_decks`)."""
    return parse_decks(text, file)[0]


def _statements(text: str) -> list[tuple[int, str]]:
    """``(line of its first record, statement text)`` per control statement,
    continuation records joined on."""
    from .._lines import split_source_lines

    statements: list[tuple[int, str]] = []
    pending: tuple[int, str] | None = None
    for number, line in enumerate(split_source_lines(text), start=1):
        card = line[:72].strip().upper()
        if not card or card.startswith("*"):
            continue
        if pending is not None:
            card = pending[1] + card.split(" ")[0]
            number = pending[0]
            pending = None
        operand = card.split(None, 1)[1].split(" ")[0] if " " in card else ""
        if operand.endswith(","):
            pending = (number, card)
            continue
        statements.append((number, card))
    if pending is not None:
        statements.append(pending)
    return statements


def _included(operand: str, number: int) -> list[dict[str, Any]]:
    """The members an INCLUDE operand field names."""
    out: list[dict[str, Any]] = []
    for item in _INCLUDED_RE.finditer(operand):
        library, members = item.group(1), item.group(2)
        if members is None:
            out.append({"member": library, "library": None, "line": number})
            continue
        for member in members.split(","):
            if member.strip():
                out.append(
                    {"member": member.strip(), "library": library, "line": number}
                )
    return out


def link_decks(workspace: Workspace) -> list[LinkDeck]:
    """Every link-edit deck under the root, rebuilt when a directory
    changes."""

    def build() -> tuple[list[LinkDeck], dict[str, Stamp]]:
        decks: list[LinkDeck] = []
        for directory, names in workspace._walk():
            for entry in names:
                path = Path(directory, entry)
                if path.suffix.lower() not in LINK_DECK_SUFFIXES:
                    continue
                try:
                    text = Workspace.read_text(path)
                except OSError:
                    continue
                decks.extend(parse_decks(text, workspace.display(path)))
        return decks, workspace.tree_stamps()

    held: list[LinkDeck] = workspace.index("link-decks", build)
    return held


def bound_into(workspace: Workspace, program: str) -> list[dict[str, Any]]:
    """The load modules whose deck INCLUDEs *program* (other than its own),
    each with the deck and line."""
    wanted = program.upper()
    out = []
    for deck in link_decks(workspace):
        if deck.load_module == wanted:
            continue
        for include in deck.includes:
            if include["member"] == wanted:
                out.append(
                    {
                        "load_module": deck.load_module,
                        "deck": deck.file,
                        "line": include["line"],
                    }
                )
    return out


def own_decks(workspace: Workspace, program: str) -> list[dict[str, Any]]:
    """The decks that bind load module *program*."""
    wanted = program.upper()
    return [d.to_dict() for d in link_decks(workspace) if d.load_module == wanted]
