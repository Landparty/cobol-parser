"""The PL/I and assembler programs under the root, read through the sibling
parsers, so the cross-program tools see a mixed codebase whole.

COBOL is only part of a mainframe codebase: a COBOL program CALLs an
assembler date routine, a PL/I batch driver CALLs a COBOL subprogram, a JCL
step runs any of them. With the ``[pl1]`` extra (``landparty-pl1-parser``,
imported as ``pl1_parser``) and the ``[hlasm]`` extra (``hlasmparser``)
installed, every PL/I and assembler source under the root is parsed once and
reduced to the facts the ``programs`` index keeps for a COBOL unit (its
names, its CALL rows with on-disk sites, its ``%INCLUDE`` / ``COPY``
members), plus what a brief shows (procedures or sections, CICS / SQL / MQ /
IMS requests). Without an extra, the files of that language stay "in the
workspace, not analyzed", as before, and the answers name the install
command.

What the sibling parsers do not read is said, not guessed: neither reads a
file declaration or record I/O, so a PL/I or assembler program has no
``files`` and its datasets come from the JCL DISP alone; the PL/I parser does
not recognize ``EXEC SQL`` / ``EXEC CICS``. Every brief carries that as an
``incomplete-analysis`` caveat.

No SDK import, and the parsers are imported only when a file of their
language is read.
"""

from __future__ import annotations

import importlib
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .envelope import Caveat, ToolError
from .workspace import Stamp, Workspace, _assembler_names, _stamp

PLI = "PL/I"
ASSEMBLER = "assembler"

#: Suffix -> language, for the sources read here. ``.mac`` (a macro library
#: member) is not a program and stays a source not analyzed.
LANGUAGE_SUFFIXES: dict[str, str] = {
    ".pli": PLI,
    ".pl1": PLI,
    ".asm": ASSEMBLER,
    ".s": ASSEMBLER,
    ".hlasm": ASSEMBLER,
    ".alc": ASSEMBLER,
}

#: Language -> (module imported, install command).
_PARSERS: dict[str, tuple[str, str]] = {
    PLI: ("pl1_parser", "pip install 'cobol-parser[pl1]'"),
    ASSEMBLER: ("hlasmparser", "pip install 'cobol-parser[hlasm]'"),
}

#: What the sibling parser of each language leaves out, said on every brief.
LIMITS: dict[str, str] = {
    PLI: "the PL/I parser reads procedures, ENTRY, CALL, FETCH and %INCLUDE "
    "only: no DECLARE FILE or record I/O, and no EXEC SQL / EXEC CICS",
    ASSEMBLER: "the assembler parser reads CSECTs, ENTRY, COPY, CALL / LINK / "
    "XCTL / LOAD / ATTACH and EXEC CICS / SQL / DLI, MQ and IMS calls only: no "
    "DCB or record I/O, no BALR / BASR linkage, and macros are not expanded",
}

#: ``PROGRAM('NAME')`` / ``PROGRAM(NAME)`` in an EXEC CICS LINK / XCTL.
_CICS_PROGRAM = re.compile(r"\bPROGRAM\s*\(\s*('?)([^')\s]+)'?\s*\)", re.IGNORECASE)

#: The service requests a brief counts, by the dependency type of the
#: assembler parser.
_SERVICE_KINDS = {"cics": "CICS", "db2_sql": "DB2 SQL", "mq": "MQ", "ims": "IMS"}


def language_of(path: str | Path) -> str | None:
    """The language read here for *path*, by suffix, or None."""
    return LANGUAGE_SUFFIXES.get(Path(path).suffix.lower())


def parser_available(language: str) -> bool:
    """Whether the sibling parser of *language* imports."""
    module = _PARSERS[language][0]
    try:
        importlib.import_module(module)
    except ImportError:
        return False
    return True


def install_hint(language: str) -> str:
    return _PARSERS[language][1]


@dataclass
class SourceFacts:
    """One PL/I or assembler program, as the indexes keep it."""

    path: str
    display: str
    language: str
    stamp: Stamp
    #: Why the file produced no program (unreadable, or the parse failed).
    failed: str | None = None
    #: The name a CALL reaches it by: the main procedure's or first CSECT's.
    program_id: str = ""
    #: Other names that reach it: the file stem (a load module is named after
    #: its member), ENTRY names, the other CSECTs. Uppercased, without
    #: *program_id*.
    entries: list[str] = field(default_factory=list)
    #: ``{name, kind, location?, options?}``: PL/I procedures, assembler
    #: CSECT / DSECT names.
    sections: list[dict[str, Any]] = field(default_factory=list)
    #: The same rows as a COBOL unit's ``calls``: program, via, dynamic,
    #: candidates, sites.
    calls: list[dict[str, Any]] = field(default_factory=list)
    #: ``{member, library?, location}`` per ``%INCLUDE`` / ``COPY``.
    includes: list[dict[str, Any]] = field(default_factory=list)
    #: ``{kind, command, target?, location}`` per CICS / SQL / MQ / IMS request.
    services: list[dict[str, Any]] = field(default_factory=list)
    #: Parse errors and warnings, as text.
    errors: list[str] = field(default_factory=list)
    caveats: list[Caveat] = field(default_factory=list)
    line_count: int = 0

    def names(self) -> set[str]:
        return {self.program_id.upper(), *self.entries} - {""}


def _location(display: str, location: Any) -> dict[str, Any] | None:
    line = getattr(location, "line", None)
    return {"file": display, "line": line} if line else None


def _row(
    rows: dict[tuple[str, str], dict[str, Any]],
    program: str,
    via: str,
    location: dict[str, Any] | None,
    **extra: Any,
) -> None:
    key = (program.upper(), via)
    row = rows.get(key)
    if row is None:
        row = {"program": program, "via": via, "dynamic": False, **extra}
        row["sites"] = []
        rows[key] = row
    row["sites"].append({"location": location})


def read_facts(workspace: Workspace, path: Path) -> SourceFacts:
    """The facts of the PL/I or assembler source *path*, from one parse."""
    language = language_of(path)
    if language is None:
        raise ToolError(f"{path.name} is not a PL/I or assembler source")
    display = workspace.display(path)
    facts = SourceFacts(
        path=str(path), display=display, language=language, stamp=_stamp(str(path))
    )
    warnings: list[str] = []
    try:
        text = workspace.read_text(path, warnings)
    except ToolError as exc:
        facts.failed = str(exc)
        return facts
    facts.line_count = text.count("\n") + (0 if text.endswith("\n") else 1)
    for warning in warnings:
        facts.caveats.append(
            Caveat(
                "incomplete-analysis",
                f"{display}: {warning}",
                "names read from the undecodable bytes may be wrong",
            )
        )
    try:
        if language == PLI:
            _read_pli(facts, text, path)
        else:
            _read_assembler(facts, text, path)
    except ImportError:
        raise
    except Exception as exc:  # noqa: BLE001 -- one file must not sink the root
        facts.failed = f"{type(exc).__name__}: {exc}"
    facts.entries = sorted(set(facts.entries) - {facts.program_id.upper(), ""})
    return facts


def _read_pli(facts: SourceFacts, text: str, path: Path) -> None:
    from pl1_parser import ErrorRecoveryMode, parse_pl1

    result = parse_pl1(
        text, filename=path.name, error_recovery=ErrorRecoveryMode.COLLECT_ALL
    )
    facts.errors = [str(e) for e in result.errors]
    program = result.ast
    if program is None:
        facts.failed = "; ".join(facts.errors) or "the PL/I parse produced no program"
        return
    if facts.errors:
        facts.caveats.append(
            Caveat(
                "partial-parse",
                f"{facts.display}: {len(facts.errors)} PL/I parse error(s): "
                + facts.errors[0],
                "CALLs and %INCLUDEs after the error may be missing",
            )
        )
    display = facts.display
    facts.program_id = (program.program_name or path.stem).upper()
    entries = {path.stem.upper()}
    entries.update(str(e.name).upper() for e in program.entry_points if e.name)
    for procedure in program.procedures:
        row: dict[str, Any] = {
            "name": procedure.name,
            "kind": "PROCEDURE",
            "location": _location(display, procedure.location),
        }
        options = getattr(procedure, "options_detail", None) or {}
        if options:
            row["options"] = dict(options)
        facts.sections.append(row)
        if str(procedure.name).upper() == facts.program_id:
            entries.update(str(n).upper() for n in procedure.entry_names or [])
    facts.entries = sorted(entries)

    rows: dict[tuple[str, str], dict[str, Any]] = {}
    for via, statements in (("CALL", program.calls), ("FETCH", program.fetches)):
        for statement in statements:
            # An aliased call appears twice: as written (external_name set)
            # and resolved to the real program, which is the one kept.
            if getattr(statement, "external_name", None):
                continue
            location = _location(display, statement.location)
            extra: dict[str, Any] = {}
            local = getattr(statement, "local_name", None)
            if local:
                extra["local_name"] = local
            if getattr(statement, "is_entry_variable", False) or getattr(
                statement, "is_dynamic", False
            ):
                _row(
                    rows,
                    statement.target,
                    via,
                    location,
                    candidates=[],
                    candidates_complete=False,
                    **extra,
                )
                rows[(statement.target.upper(), via)]["dynamic"] = True
                continue
            _row(rows, statement.target.upper(), via, location, **extra)
    facts.calls = list(rows.values())
    for include in program.includes:
        row = {
            "member": str(include.member_name).upper(),
            "location": _location(display, include.location),
        }
        if include.library:
            row["library"] = include.library
        facts.includes.append(row)


def _read_assembler(facts: SourceFacts, text: str, path: Path) -> None:
    from hlasmparser import parse_hlasm

    # COLLECT_ALL is accepted by HlasmParser but behaves like FAIL_FAST, so
    # the default is asked for.
    result = parse_hlasm(text, filename=path.name)
    facts.errors = [str(e) for e in result.errors]
    program = result.ast
    if not result.success or program is None:
        facts.failed = (
            "; ".join(facts.errors) or "the assembler parse produced no program"
        )
        return
    display = facts.display
    facts.program_id = (program.program_name or path.stem).upper()
    facts.entries = sorted(
        {path.stem.upper(), *(c.upper() for c in program.csects)}
        | _assembler_names(path)
    )
    facts.sections = [{"name": c, "kind": "CSECT"} for c in program.csects] + [
        {"name": d, "kind": "DSECT"} for d in program.dsects
    ]

    rows: dict[tuple[str, str], dict[str, Any]] = {}
    for dep in program.get_dependencies():
        kind = getattr(dep.dep_type, "value", str(dep.dep_type))
        location = _location(display, dep.location)
        target = str(dep.target or "")
        if kind == "subprogram_call":
            via = str(dep.command or "CALL").upper()
            resolved_from = getattr(dep, "resolved_from", None)
            if resolved_from:
                # EPLOC= a field holding the name: resolved through its DC.
                _row(
                    rows,
                    resolved_from,
                    via,
                    location,
                    candidates=[target.upper()],
                    candidates_complete=True,
                )
                rows[(resolved_from.upper(), via)]["dynamic"] = True
            else:
                _row(rows, target.upper(), via, location)
        elif kind == "copybook":
            facts.includes.append({"member": target.upper(), "location": location})
        elif kind in _SERVICE_KINDS:
            command = str(dep.command or "")
            service: dict[str, Any] = {"kind": _SERVICE_KINDS[kind], "command": command}
            if kind in ("mq", "ims") and target:
                service["target"] = target.upper()
            service["location"] = location
            facts.services.append(service)
            verb = command.split()[-1].upper() if command else ""
            if kind == "cics" and verb in ("LINK", "XCTL"):
                linked = _CICS_PROGRAM.search(str(dep.raw_operands or ""))
                if linked is None:
                    continue
                name, literal = linked.group(2), bool(linked.group(1))
                via = f"EXEC CICS {verb}"
                if literal:
                    _row(rows, name.upper(), via, location)
                else:
                    _row(
                        rows,
                        name,
                        via,
                        location,
                        candidates=[],
                        candidates_complete=False,
                    )
                    rows[(name.upper(), via)]["dynamic"] = True
    facts.calls = list(rows.values())


# ---------------------------------------------------------------------------
# The index
# ---------------------------------------------------------------------------


@dataclass
class LanguagesIndex:
    """Every PL/I and assembler source under the root."""

    sources: list[SourceFacts] = field(default_factory=list)
    #: Language -> files of it left unread because its parser is missing.
    not_installed: dict[str, list[str]] = field(default_factory=dict)
    seconds: float = 0.0

    def analyzed(self) -> list[SourceFacts]:
        return [s for s in self.sources if s.failed is None]

    def named(self, name: str) -> list[SourceFacts]:
        """The sources a CALL to *name* reaches: by their program name, else
        by an entry name (the file stem, an ENTRY, another CSECT)."""
        wanted = name.strip().upper()
        found = self.analyzed()
        by_id = [s for s in found if s.program_id.upper() == wanted]
        return by_id or [s for s in found if wanted in s.entries]

    def by_path(self, path: Path) -> SourceFacts | None:
        return next((s for s in self.sources if s.path == str(path)), None)


def source_files(workspace: Workspace) -> list[Path]:
    """The PL/I and assembler sources under the root, sorted; a suffix
    ``cobol.yml`` counts as COBOL stays COBOL."""
    programs = workspace._program_suffixes()
    return workspace.files_named(tuple(set(LANGUAGE_SUFFIXES) - programs))


def languages_index(workspace: Workspace) -> LanguagesIndex:
    """The languages index, rebuilt once a source under the root changes.
    Each file is read again only when its own stamp changed."""

    def build() -> tuple[LanguagesIndex, dict[str, Stamp]]:
        return _build(workspace)

    index: LanguagesIndex = workspace.index("languages", build)
    return index


def _build(workspace: Workspace) -> tuple[LanguagesIndex, dict[str, Stamp]]:
    started = time.monotonic()
    index = LanguagesIndex()
    stamps = workspace.tree_stamps()
    previous = workspace.built_index("languages")
    held = (
        {s.path: s for s in previous.sources}
        if isinstance(previous, LanguagesIndex)
        else {}
    )
    available: dict[str, bool] = {}
    for path in source_files(workspace):
        language = LANGUAGE_SUFFIXES[path.suffix.lower()]
        stamps[str(path)] = _stamp(str(path))
        if language not in available:
            available[language] = parser_available(language)
        if not available[language]:
            index.not_installed.setdefault(language, []).append(workspace.display(path))
            continue
        old = held.get(str(path))
        if old is not None and old.stamp == stamps[str(path)]:
            index.sources.append(old)
            continue
        index.sources.append(read_facts(workspace, path))
    index.seconds = time.monotonic() - started
    return index, stamps


def facts_for(workspace: Workspace, path: Path) -> SourceFacts:
    """*path*'s facts: the index's when current, else read now."""
    language = language_of(path)
    if language is None:
        raise ToolError(f"{path.name} is not a PL/I or assembler source")
    if not parser_available(language):
        raise ToolError(
            f"{workspace.display(path)} is {language} source, which is read "
            f"only with the parser installed: {install_hint(language)}"
        )
    built = workspace.built_index("languages")
    if isinstance(built, LanguagesIndex):
        held = built.by_path(path)
        if held is not None and held.stamp == _stamp(str(path)):
            return held
    return read_facts(workspace, path)
