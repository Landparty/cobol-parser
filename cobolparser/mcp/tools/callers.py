"""``callers_of``: who PERFORMs a paragraph or section, or, program-wide, who
CALLs / LINKs / XCTLs a program across the workspace."""

from __future__ import annotations

import difflib
import re
from pathlib import Path
from typing import Any

from ..envelope import Response, ToolError, clamp_limit
from ..link_decks import bound_into
from ..workspace import ParsedProgram
from .common import (
    _CONTROL_EDGES,
    BaseTools,
    _attempt,
    _carry_index_caveats,
    _carry_parse_caveats,
    _coverage,
    _declared_elsewhere,
    _flow,
    _label_runs_as,
    _reachability,
)


class CallersTools(BaseTools):
    """``callers_of``."""

    # -- callers_of ----------------------------------------------------------

    def callers_of(
        self,
        file: str | None,
        name: str,
        program: str | None = None,
        limit: int | None = None,
    ) -> dict[str, Any]:
        """Who transfers control to paragraph or section *name*, and from where.

        A name that is no procedure of *file* (or any name, with no *file*)
        is looked up as a program: which programs under the root CALL, LINK
        or XCTL to it.
        """
        wanted = " ".join(name.split()).upper()
        if not wanted:
            raise ToolError("no paragraph, section or program name given")
        cap = clamp_limit(limit)
        response = Response()
        if file is None:
            return self._program_callers(wanted, response, cap, None, [])
        other = self._other_language_path(file)
        if other is not None:
            # PL/I and assembler procedures are not indexed: a name is a
            # program here.
            return self._program_callers(wanted, response, cap, None, [])
        parsed = self.workspace.program(file)
        _carry_parse_caveats(parsed, response)
        unit = parsed.unit(program, response)
        program_info = parsed.program_info(unit)
        flow = _flow(parsed, unit)

        wanted = wanted.replace(" IN ", " OF ")
        matches = [
            n for n in flow.nodes if n.key.upper() == wanted or n.name.upper() == wanted
        ]
        if len(matches) > 1:
            response.caveat(
                "ambiguous-name",
                f"{len(matches)} procedures are named {wanted}",
                "qualify the name (PARA OF SECTION) to ask about one of them",
            )

        if not matches:
            # Not a procedure here: a program, if any program under the root
            # is called or named so.
            names = sorted({n.key.upper() for n in flow.nodes})
            result = self._program_callers(wanted, response, cap, program_info, names)
            if not result["answer"].get("found"):
                _declared_elsewhere(
                    result["answer"],
                    parsed,
                    unit,
                    lambda other: any(
                        n.key.upper() == wanted or n.name.upper() == wanted
                        for n in _flow(parsed, other).nodes
                    ),
                )
            return result

        # Reachability is DeadCodeAnalyzer's (the same answer as the brief's
        # lint section): the flow graph draws a fall-through out of every
        # non-terminating procedure, PERFORM targets included, so its
        # ``unreachable_nodes`` misses the paragraph after a performed one.
        reach = _reachability(parsed, unit, response)
        if reach is None:
            unreachable = {u.upper() for u in flow.unreachable_nodes}
        else:
            unreachable = {u.upper() for u in reach.unreachable}
        # Where control starts runs on: the first paragraph, or the
        # sentences before it (``PROCEDURE DIVISION``, a node of the flow
        # graph only).
        start = flow.entry_points[0].upper() if flow.entry_points else None
        procedures: list[dict[str, Any]] = []
        for index, node in enumerate(matches):
            key = node.key.upper()
            # A THRU statement is two edges: the opener (to the first
            # paragraph, carrying the whole range) and a ``*_THRU`` closer to
            # the last. One statement is one caller, so only openers count;
            # a paragraph inside the range is run without being named.
            # Each THRU range end, for the note on a fall-through out of one.
            range_ends = {
                edge.target.upper()
                for edge in flow.edges
                if edge.edge_type.value.endswith("_THRU")
            }
            callers = []
            for edge in flow.edges:
                kind = edge.edge_type.value
                if kind not in _CONTROL_EDGES or kind.endswith("_THRU"):
                    continue
                if (
                    kind == "FALL_THROUGH"
                    and reach is not None
                    and edge.source.upper() != start
                    and (edge.source.upper(), edge.target.upper())
                    not in reach.fall_throughs
                ):
                    # Out of a procedure only ever PERFORMed (its end returns
                    # to the performer), or out of one never reached: control
                    # never runs on along this edge.
                    continue
                if edge.target.upper() == key:
                    caller = _edge_caller(edge, parsed, response)
                    if kind == "FALL_THROUGH" and edge.source.upper() in range_ends:
                        _note_range_end_run_on(caller, edge, flow, parsed, response)
                    callers.append(caller)
                elif key in (m.upper() for m in edge.range_members):
                    caller = _edge_caller(edge, parsed, response)
                    caller["via_range"] = [edge.target, edge.thru_target]
                    callers.append(caller)
            by_type: dict[str, int] = {}
            for caller in callers:
                by_type[caller["type"]] = by_type.get(caller["type"], 0) + 1
            procedure: dict[str, Any] = {
                "name": node.name,
                "kind": node.procedure_type.lower(),
                "declared_at": parsed.locate(
                    node.location.line, node.location.column, response
                ),
                "is_entry_point": node.is_entry_point,
                "reachable": key not in unreachable,
                "caller_count": len(callers),
                "callers_by_type": by_type,
                "callers": response.cap(callers, cap, f"procedures[{index}].callers"),
            }
            if node.qualified_name:
                procedure["qualified_name"] = node.qualified_name
            if node.is_declarative:
                procedure["is_declarative"] = True
                procedure["note"] = (
                    "a DECLARATIVES procedure is run by the runtime when its "
                    "USE condition occurs, not by the program's own flow"
                )
            procedures.append(procedure)
        return response.build(
            {"name": wanted, "found": True, "procedures": procedures}, program_info
        )

    # -- callers_of, at program level ---------------------------------------

    def _program_callers(
        self,
        wanted: str,
        response: Response,
        cap: int,
        program_info: dict[str, Any] | None,
        procedures: list[str],
    ) -> dict[str, Any]:
        """Every CALL, LINK and XCTL to program *wanted* under the root."""
        from ..codebase_index import programs_index

        index = programs_index(self.workspace)
        _carry_index_caveats(index, response, "CALL statements")
        callers: list[dict[str, Any]] = []
        unresolved: list[dict[str, Any]] = []
        # A nested program can only be CALLed from its own compilation unit
        # (#532): when every declaration of *wanted* is nested, a CALL that
        # COBOL scope does not send to one reaches a separately compiled
        # program of the same name, not any declared here.
        declared_units = index.units_named(wanted)
        only_nested = bool(declared_units) and all(u.depth for u in declared_units)
        out_of_scope: set[str] = set()
        # A CALL to one of the program's alternate ENTRY names reaches it
        # too (#521); a PROGRAM-ID of that spelling would win instead.
        # A FACTORY / OBJECT / METHOD-ID unit is neither (#500).
        program_ids = {u.program_id.upper() for u in index.units if u.is_call_target}
        entries = {
            entry
            for u in index.units
            if u.is_call_target and u.program_id.upper() == wanted
            for entry in u.entries
            if entry not in program_ids
        }
        names = {wanted} | entries
        for unit in index.units:
            for row in unit.calls:
                target = str(row.get("program") or "").upper()
                candidates = [str(c).upper() for c in row.get("candidates") or []]
                via_entry: str | None = None
                if not row.get("dynamic") and target in names:
                    resolved_from = None
                    reaches_nested = bool(row.get("nested"))
                    via_entry = target if target in entries else None
                elif row.get("dynamic") and names & set(candidates):
                    resolved_from = row.get("program")
                    reaches_nested = wanted in {
                        str(c).upper() for c in row.get("nested_candidates") or []
                    }
                    if wanted not in candidates:
                        via_entry = sorted(names & set(candidates))[0]
                elif row.get("dynamic") and not row.get("candidates_complete"):
                    for site in row.get("sites") or []:
                        unresolved.append(
                            {
                                "program": unit.program_id,
                                "via": row.get("via"),
                                "target_from": row.get("program"),
                                "location": site.get("location"),
                            }
                        )
                    continue
                else:
                    continue
                if only_nested and not reaches_nested:
                    out_of_scope.add(unit.program_id)
                    continue
                for site in row.get("sites") or []:
                    caller: dict[str, Any] = {
                        "program": unit.program_id,
                        "via": row.get("via"),
                        "location": site.get("location"),
                    }
                    copied = _copied_at(index, unit.file, site.get("location"))
                    if copied is not None:
                        caller["copied_at"] = copied
                    if unit.language != "COBOL":
                        caller["language"] = unit.language
                    if reaches_nested:
                        caller["nested"] = True
                    if site.get("paragraph"):
                        # "from", as a paragraph-level caller names its own.
                        caller["from"] = site["paragraph"]
                    if via_entry is not None:
                        caller["entry"] = via_entry
                    if resolved_from is not None:
                        caller["dynamic"] = True
                        caller["target_from"] = resolved_from
                    linkage = _call_type(unit.language, row, resolved_from)
                    if linkage:
                        caller["call_type"] = linkage
                    callers.append(caller)

        declared = []
        for unit in declared_units:
            where: dict[str, Any] = {"file": unit.file}
            if unit.program_id.upper() != wanted:
                # Found through an ENTRY name it declares (#521).
                where["program"] = unit.program_id
            if unit.depth:
                where["contained"] = True
            if unit.unit_kind != "PROGRAM":
                where["unit_kind"] = unit.unit_kind
            if unit.language != "COBOL":
                where["language"] = unit.language
            declared.append(where)
        if not callers and not declared:
            known = sorted(
                {u.program_id.upper() for u in index.units if u.program_id}
                | {
                    str(row.get("program") or "").upper()
                    for u in index.units
                    for row in u.calls
                    if not row.get("dynamic")
                }
            )
            return response.build(
                {
                    "name": wanted,
                    "found": False,
                    "suggestions": difflib.get_close_matches(
                        wanted, sorted(set(procedures) | set(known)), n=5
                    ),
                },
                program_info,
            )

        answer: dict[str, Any] = {
            "name": wanted,
            "found": True,
            "kind": "program",
            "scope": "workspace",
            "declared_in": declared,
            "caller_count": len(callers),
            "calling_programs": sorted({c["program"] for c in callers}),
            "callers": response.cap(callers, cap, "callers"),
            "coverage": _coverage(self.workspace, index),
        }
        if out_of_scope:
            answer["out_of_scope_callers"] = sorted(out_of_scope)
        _label_runs_as(self.workspace, answer, callers, response)
        bound = _attempt(
            response, "link-edit decks", lambda: bound_into(self.workspace, wanted)
        )
        if bound:
            answer["link_edited_into"] = bound
        # Only outermost (or stacked) declarations share one load-module
        # namespace: a nested program is reached from its own compilation
        # unit, whatever else is in the load library (#532).
        top_level = [d for d in declared if not d.get("contained")]
        if len(top_level) > 1:
            response.caveat(
                "duplicate-declaration",
                f"PROGRAM-ID {wanted} is declared in {len(top_level)} places: "
                + ", ".join(d["file"] for d in top_level),
                "which one a CALL reaches depends on the load library order, "
                "which the source does not say",
            )
        other = self.workspace.other_sources().get(wanted.upper())
        if other:
            # Even beside a declaration: a second source of the same name
            # (an assembler twin of a COBOL routine) is what a reader most
            # needs to hear about.
            answer["sources_not_analyzed"] = [
                {"file": self.workspace.display(path), "language": language}
                for path, language in other
            ]
        if other and not declared:
            answer["note"] = (
                f"no COBOL program under the root has PROGRAM-ID {wanted}, but "
                f"its source is here in {other[0][1]} "
                f"({self.workspace.display(other[0][0])}), which these tools "
                "do not parse: read it with read_source" + _install_note(other[0][0])
            )
        elif not declared:
            answer["note"] = (
                f"no program under the root has PROGRAM-ID {wanted}: it is "
                "external to this workspace (a vendor or system program, or "
                "one kept elsewhere)"
            )
        elif not callers and out_of_scope:
            answer["note"] = (
                f"every {wanted} under the root is a nested program, which "
                "only its own compilation unit can CALL; the CALLs from "
                "out_of_scope_callers reach a separately compiled program "
                "of that name"
            )
        elif not callers and bound:
            answer["note"] = (
                "no CALL, LINK or XCTL under the root names it as a literal, but "
                "a link-edit deck binds it into "
                + ", ".join(sorted({b["load_module"] for b in bound}))
                + " (link_edited_into): it runs as part of that load module, "
                "CALLed from it statically or through a data item"
            )
        elif not callers:
            answer["note"] = (
                "no program under the root CALLs, LINKs or XCTLs to it: it is "
                "started some other way (a JCL EXEC PGM=, a CICS transaction, "
                "a scheduler) or is no longer used"
            )
        if unresolved:
            self._unresolved_near(answer, response, cap, wanted, unresolved)
        return response.build(answer, program_info)

    def _unresolved_near(
        self,
        answer: dict[str, Any],
        response: Response,
        cap: int,
        wanted: str,
        unresolved: list[dict[str, Any]],
    ) -> None:
        """The untraced dynamic CALL sites that could reach *wanted*: those in
        the top-level folder of a declaration or a caller of it (an
        application, in a root holding several), and those whose source text
        names it. The others, in folders that never mention it, are counted:
        a value set the analysis could not trace is still built from
        literals somewhere, and none of them spells this name."""
        anchors = {
            _top_folder(str(where["file"]))
            for where in answer.get("declared_in", [])
            if where.get("file")
        } | {
            _top_folder(str(c["location"]["file"]))
            for c in answer.get("callers", [])
            if (c.get("location") or {}).get("file")
        }
        names = re.compile(rf"(?<![\w-]){re.escape(wanted)}(?![\w-])", re.IGNORECASE)
        near: list[dict[str, Any]] = []
        far: list[dict[str, Any]] = []
        for row in unresolved:
            file = str((row.get("location") or {}).get("file") or "")
            if (
                not anchors
                or not file
                or _top_folder(file) in anchors
                or self._file_names(file, names)
            ):
                near.append(row)
            else:
                far.append(row)
        if near:
            answer["unresolved_dynamic_calls"] = response.cap(
                near, cap, "unresolved_dynamic_calls"
            )
        parts: list[str] = []
        effects: list[str] = []
        if near:
            parts.append(
                f"{len(near)} dynamic CALL/LINK/XCTL site(s) near {wanted} take "
                "their target from a data item whose values could not all be "
                "traced"
            )
            effects.append(
                f"any of them may also reach {wanted}; they are listed in "
                "unresolved_dynamic_calls"
            )
        if far:
            folders = sorted({_top_folder(str(r["location"]["file"])) for r in far})
            answer["unresolved_dynamic_calls_elsewhere"] = {
                "count": len(far),
                "folders": folders,
            }
            parts.append(
                f"{len(far)} untraced dynamic CALL/LINK/XCTL site(s) in other "
                f"folders ({', '.join(folders)}), whose source never names "
                f"{wanted}, are only counted"
            )
            effects.append(
                "those could reach it only through a name read at run time "
                "(a file, a commarea, a table)"
            )
        detail, effect = "; ".join(parts), "; ".join(effects)
        response.caveat("incomplete-analysis", detail, effect)

    def _file_names(self, file: str, names: re.Pattern[str]) -> bool:
        """Whether the source *file* (relative to the root) matches *names*."""
        try:
            text = (self.workspace.root / file).read_text(encoding="latin-1")
        except OSError:
            return True  # unreadable: it may well name it
        return bool(names.search(text))


def _copied_at(
    index: Any, file: str, location: dict[str, Any] | None
) -> dict[str, Any] | None:
    """Where *file* COPYs the copybook a call site at *location* sits in:
    the line in the program that brings the CALL in. None for a site in
    the program itself, or one copied in through another member."""
    if not location or location.get("file") in (None, file):
        return None
    member = Path(str(location["file"])).stem.upper()
    for site in index.copy_sites.get(member, []):
        if site["file"] == file:
            return {"file": site["file"], "line": site["line"]}
    return None


def _call_type(language: str, row: dict[str, Any], resolved_from: Any) -> str | None:
    """How a CALL links to its target, said so a reader need not guess:
    a COBOL CALL literal is static unless the DYNAM compiler option is on,
    a CALL identifier is always dynamic, a PL/I CALL to an ENTRY declared
    OPTIONS(FETCHABLE) fetches the module at run time."""
    via = str(row.get("via") or "")
    if via.startswith("EXEC CICS"):
        return "dynamic: CICS loads the program it LINKs or XCTLs to"
    if via != "CALL":
        return None
    if language == "COBOL":
        if resolved_from is not None or row.get("dynamic"):
            return "dynamic: CALL of a data item, its value traced"
        return "CALL literal: static, unless compiled with the DYNAM option"
    if language == "PL/I":
        if row.get("fetchable"):
            return (
                "dynamic: the ENTRY is declared OPTIONS(FETCHABLE), so the "
                "module is fetched at run time on the first CALL"
            )
        if row.get("dynamic"):
            return "dynamic: CALL of an ENTRY variable"
        return "static: an EXTERNAL ENTRY without FETCHABLE, resolved when linked"
    return None


def _edge_caller(
    edge: Any, parsed: ParsedProgram, response: Response
) -> dict[str, Any]:
    caller: dict[str, Any] = {
        "from": edge.source,
        "type": edge.edge_type.value,
        "location": parsed.locate(edge.location.line, None, response),
    }
    if edge.perform_type and edge.perform_type != "SIMPLE":
        caller["perform_type"] = edge.perform_type
    if edge.condition:
        caller["condition"] = edge.condition
    if edge.is_loop:
        caller["loop"] = True
    if edge.thru_target:
        caller["thru"] = edge.thru_target
    return caller


def _note_range_end_run_on(
    caller: dict[str, Any],
    edge: Any,
    flow: Any,
    parsed: ParsedProgram,
    response: Response,
) -> None:
    """Say why control runs on past a ``PERFORM ... THRU`` range end.

    Under a PERFORM of the range the end returns, so this fall-through is
    only real when the end is reached some other way: a GO TO onto it from
    outside the range (often a paragraph PERFORMed without THRU that jumps
    to its exit), a longer range that runs through it, or the main line.
    DeadCodeAnalyzer has already decided that one of those can happen (the
    edge is kept only then); the note names the GO TOs, the usual cause,
    so the caller can be checked against the source.
    """
    source = edge.source.upper()
    gotos = [
        {
            "from": other.source,
            "location": parsed.locate(other.location.line, None, response),
        }
        for other in flow.edges
        if other.edge_type.value in ("GOTO", "GOTO_DEPENDING")
        and other.target.upper() == source
    ]
    caller["note"] = (
        f"{edge.source} ends a PERFORM ... THRU range, where control returns; "
        f"it runs on into {edge.target} only when {edge.source} is reached "
        "outside a PERFORM of that range (a GO TO from outside it, a longer "
        "range that passes through it, or the main line)"
    )
    if gotos:
        caller["entered_by_goto"] = gotos


def _install_note(path: Path) -> str:
    """How to have *path* analyzed, when only a missing parser stops it."""
    from ..languages import install_hint, language_of

    language = language_of(path)
    return (
        ""
        if language is None
        else f" (or install its parser: {install_hint(language)})"
    )


def _top_folder(file: str) -> str:
    """The first folder of a root-relative *file*, "" for one at the root."""
    head, sep, _rest = file.partition("/")
    return head if sep else ""
