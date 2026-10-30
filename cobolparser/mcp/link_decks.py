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


def parse_deck(text: str, file: str) -> LinkDeck:
    """The INCLUDE, NAME and ENTRY statements of one deck (columns 2-71;
    ``*`` comment lines skipped)."""
    from .._lines import split_source_lines

    name: str | None = None
    entry: str | None = None
    includes: list[dict[str, Any]] = []
    for number, line in enumerate(split_source_lines(text), start=1):
        card = line[:72].strip().upper()
        if not card or card.startswith("*"):
            continue
        found = _INCLUDE_RE.match(card)
        if found:
            for item in _INCLUDED_RE.finditer(found.group(1).split(" ")[0]):
                library, members = item.group(1), item.group(2)
                if members is None:
                    includes.append(
                        {"member": library, "library": None, "line": number}
                    )
                    continue
                for member in members.split(","):
                    if member.strip():
                        includes.append(
                            {
                                "member": member.strip(),
                                "library": library,
                                "line": number,
                            }
                        )
            continue
        found = _NAME_RE.match(card)
        if found:
            name = found.group(1)
            continue
        found = _ENTRY_RE.match(card)
        if found:
            entry = found.group(1)
    return LinkDeck(
        file=file,
        load_module=name or Path(file).stem.upper(),
        entry=entry,
        includes=includes,
    )


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
                decks.append(parse_deck(text, workspace.display(path)))
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
