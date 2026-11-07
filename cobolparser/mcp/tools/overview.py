"""``codebase_overview``: the whole workspace in one answer -- programs, call
graph, copybooks, health, clones -- optionally scoped by language or path."""

from __future__ import annotations

from typing import Any

from ..envelope import Response, ToolError, clamp_limit
from .common import BaseTools, _carry_index_caveats, _notes

#: Length of the "top" lists in a codebase overview (most called, most used
#: copybooks, worst health, duplicated code); ``limit`` can only lower it.
OVERVIEW_TOP = 10


#: Members shown per duplicated-code group in a codebase overview: enough to
#: see where the copies are; ``member_count`` says how many there are.
OVERVIEW_CLONE_MEMBERS = 3


class OverviewTools(BaseTools):
    """``codebase_overview``."""

    # -- codebase_overview ---------------------------------------------------

    def codebase_overview(
        self,
        limit: int | None = None,
        language: str | None = None,
        path: str | None = None,
    ) -> dict[str, Any]:
        """The programs under the root, how they call each other and share
        copybooks, their health, and the code duplicated between them.
        *language* (COBOL, PL/I, assembler) and *path* (a folder, or a glob
        of root-relative paths) narrow the answer to those programs: the
        call graph, copybooks, health and duplicated code are then counted
        over them alone."""
        from ..codebase_index import health_index, programs_index

        wanted_language = _language_named(language) if language else None
        cap = clamp_limit(limit)
        top = min(cap, OVERVIEW_TOP)
        members_shown = min(top, OVERVIEW_CLONE_MEMBERS)
        response = Response()
        index = programs_index(self.workspace)
        health = health_index(self.workspace)
        graph = index.graph

        grades = {(u["program"] or "", u["file"]): u for u in health.units}
        callers_of: dict[str, set[str]] = {}
        callees_of: dict[str, set[str]] = {}
        for edge in graph.call_edges:
            callers_of.setdefault(edge.callee, set()).add(edge.caller)
            callees_of.setdefault(edge.caller, set()).add(edge.callee)
        programs = []
        scoped = wanted_language is not None or path is not None
        scope_ids: set[str] = set()
        scope_files: set[str] = set()
        for unit in index.units:
            # The graph's id: a nested program's is qualified (#532). A
            # FACTORY / OBJECT / METHOD-ID unit has no graph node of its
            # own (its CALLs are its class's), so a graph id of the same
            # spelling is a different program, never this unit (#500).
            pid = (
                (unit.graph_id or unit.program_id).upper()
                if unit.is_call_target
                else ""
            )
            graded = grades.get((unit.program_id, unit.file), {})
            row: dict[str, Any] = {
                "program": unit.program_id,
                "file": unit.file,
                "grade": graded.get("grade"),
                "score": graded.get("score"),
                # From the graph, like called_by: a dynamic CALL counts its
                # resolved targets, not the data name it calls through.
                "calls": len(callees_of.get(pid, set())),
                "called_by": len(callers_of.get(pid, set())),
            }
            if unit.depth:
                row["contained"] = True
            if unit.unit_kind != "PROGRAM":
                row["unit_kind"] = unit.unit_kind
            if unit.language != "COBOL":
                row["language"] = unit.language
            if wanted_language is not None and unit.language != wanted_language:
                continue
            if path is not None and not _path_matches(unit.file, path):
                continue
            programs.append(row)
            scope_ids.add(pid or unit.program_id.upper())
            scope_files.add(unit.file)

        def in_scope(program_id: str) -> bool:
            return not scoped or program_id.upper() in scope_ids

        _carry_index_caveats(
            index, response, "programs", scope_files if scoped else None
        )
        for file, caveats in health.file_caveats.items():
            if scoped and file not in scope_files:
                continue
            for caveat in caveats:
                if caveat.kind == "analyzer-failed":
                    response.caveat(caveat.kind, caveat.detail, caveat.effect)

        declared = {
            (u.graph_id or u.program_id).upper()
            for u in index.units
            if u.is_call_target
        }
        external: dict[str, set[str]] = {}
        for edge in graph.call_edges:
            if edge.callee not in declared and in_scope(edge.caller):
                external.setdefault(edge.callee, set()).add(edge.caller)
        other_sources = self.workspace.other_sources()
        not_parsed = {p: c for p, c in external.items() if p.upper() in other_sources}
        for program_id in not_parsed:
            del external[program_id]
        languages: dict[str, int] = {}
        for _path, language in {
            entry for entries in other_sources.values() for entry in entries
        }:
            languages[language] = languages.get(language, 0) + 1
        most_called = sorted(
            (
                (p, len(c))
                for p, c in callers_of.items()
                if p in declared and in_scope(p)
            ),
            key=lambda pc: (-pc[1], pc[0]),
        )
        entry = sorted(
            u.program_id
            for u in index.units
            if not u.depth
            and u.program_id.upper() not in callers_of
            and (not scoped or u.file in scope_files)
        )
        dynamic = sum(
            1
            for u in index.units
            if not scoped or u.file in scope_files
            for row in u.calls
            if row.get("dynamic") and not row.get("candidates_complete")
            for _ in row.get("sites") or []
        )

        usage = sorted(
            (
                (
                    m,
                    sum(1 for p in graph.programs_using(m) if in_scope(p)),
                    sum(
                        1
                        for p in graph.programs_using(m, transitive=False)
                        if in_scope(p)
                    ),
                )
                for m in graph.members
            ),
            key=lambda mu: (-mu[1], mu[0]),
        )
        usage = [u for u in usage if u[1]]
        unresolved_members = sorted(
            {
                e.member
                for e in graph.copy_edges
                if e.path is None and not e.nested and in_scope(e.program)
            }
        )
        graded_units = [
            u for u in health.units if not scoped or u["file"] in scope_files
        ]
        clones = [
            {
                **group,
                "member_count": len(group["members"]),
                "members": [
                    m
                    for m in group["members"]
                    if not scoped
                    or (m.get("location") or {}).get("file") in scope_files
                ],
            }
            for group in health.clones
        ]
        clones = [g for g in clones if g["members"]]
        cycles = [c for c in graph.cycles() if any(in_scope(p) for p in c)]
        gaps = [self._relative(note) for note in graph.unresolved]
        if scoped:
            gaps = [g for g in gaps if g.split(":", 1)[0] in scope_files]

        bands: dict[str, int] = {}
        for graded_unit in graded_units:
            grade = graded_unit["grade"] or "ungraded"
            bands[grade] = bands.get(grade, 0) + 1
        worst = sorted(
            (u for u in graded_units if u["score"] is not None),
            key=lambda u: (-u["score"], u["program"] or ""),
        )

        by_language: dict[str, int] = {}
        for unit in index.units:
            by_language[unit.language] = by_language.get(unit.language, 0) + 1
        answer: dict[str, Any] = {
            "index": {
                **index.summary(),
                "program_units": len(index.units),
                **(
                    {"program_units_by_language": dict(sorted(by_language.items()))}
                    if set(by_language) != {"COBOL"}
                    else {}
                ),
                **(
                    {"other_sources_not_analyzed": dict(sorted(languages.items()))}
                    if languages
                    else {}
                ),
            },
            **(
                {
                    "programs_filter": {
                        k: v
                        for k, v in (("language", wanted_language), ("path", path))
                        if v
                    },
                    "programs_matched": len(programs),
                }
                if wanted_language or path
                else {}
            ),
            "programs": response.cap(
                sorted(programs, key=lambda r: (r["program"].upper(), r["file"])),
                cap,
                "programs",
            ),
            "call_graph": {
                "edges": sum(
                    1
                    for e in graph.call_edges
                    if in_scope(e.caller) or in_scope(e.callee)
                ),
                "entry_programs": response.cap(entry, cap, "call_graph.entry_programs"),
                "most_called": [
                    {"program": p, "called_by": n} for p, n in most_called[:top]
                ],
                "not_in_workspace": response.cap(
                    [
                        {"program": p, "called_by": sorted(c)}
                        for p, c in sorted(external.items())
                    ],
                    cap,
                    "call_graph.not_in_workspace",
                ),
                "in_workspace_not_analyzed": response.cap(
                    [
                        {
                            "program": p,
                            "called_by": sorted(c),
                            "sources": [
                                {
                                    "file": self.workspace.display(path),
                                    "language": language,
                                }
                                for path, language in other_sources[p.upper()]
                            ],
                        }
                        for p, c in sorted(not_parsed.items())
                    ],
                    cap,
                    "call_graph.in_workspace_not_analyzed",
                ),
                "cycles": response.cap(cycles, cap, "call_graph.cycles"),
                "unresolved_dynamic_calls": dynamic,
            },
            "copybooks": {
                "members": len(usage),
                "most_used": [
                    {"member": m, "programs": n, "copied_directly_by": d}
                    for m, n, d in usage[:top]
                ],
                "not_found": response.cap(
                    unresolved_members, cap, "copybooks.not_found"
                ),
            },
            "health": {
                "grades": dict(sorted(bands.items())),
                "worst": [
                    {k: u[k] for k in ("program", "file", "grade", "score")}
                    for u in worst[:top]
                ],
                "scale": "score 0-100, higher is more technical debt; "
                "A <= 10 < B <= 25 < C <= 45 < D <= 70 < F",
            },
            "duplicated_code": {
                "group_count": len(clones),
                "groups": [
                    {**group, "members": group["members"][:members_shown]}
                    for group in response.cap(clones, top, "duplicated_code.groups")
                ],
                "ranking": "most duplicated statements first (statements x "
                "copies); a copybook paragraph included by many programs is "
                "one copy",
            },
        }
        cut = [
            g
            for g in answer["duplicated_code"]["groups"]
            if g["member_count"] > len(g["members"])
        ]
        if cut:
            response.truncated.append(
                {
                    "field": "duplicated_code.groups[].members",
                    "shown": members_shown,
                    "groups_cut": len(cut),
                    "note": "member_count is every copy; impact_of_change or "
                    "read_procedure on one member for more",
                }
            )
        if scoped:
            answer["scope"] = "every section is counted over the matched programs only"
        _notes(
            response,
            "incomplete-analysis",
            gaps,
            "call and COPY edges near these are missing or only approximately "
            "attributed",
            lead=f"{len(gaps)} gap(s) in the call and COPY graph",
        )
        if dynamic:
            response.caveat(
                "incomplete-analysis",
                f"{dynamic} dynamic CALL/LINK/XCTL site(s) have targets that "
                "could not all be traced",
                "the call graph may miss edges from them",
            )
        _other_language_caveats(index, response)
        return response.build(answer)


def _other_language_caveats(index: Any, response: Response) -> None:
    """What the programs index could not read of the PL/I and assembler
    sources under the root, and what it read of them only in part."""
    from ..languages import LIMITS, install_hint

    for language, files in sorted(index.not_installed.items()):
        response.caveat(
            "incomplete-analysis",
            f"{len(files)} {language} file(s) under the root were not read: "
            f"the {language} parser is not installed ({install_hint(language)})",
            "CALLs from them are missing; CALLs to them count as "
            "in_workspace_not_analyzed",
        )
    for language in sorted(index.other_language_files):
        response.caveat(
            "incomplete-analysis",
            f"{index.other_language_files[language]} {language} file(s) read "
            f"through a sibling parser: {LIMITS[language]}",
            f"{language} programs are in the call graph, but have no health "
            "grade, no field lineage and no file I/O",
        )


#: Spellings a ``language`` argument may use, upper-cased.
_LANGUAGE_NAMES = {
    "COBOL": "COBOL",
    "CBL": "COBOL",
    "PL/I": "PL/I",
    "PLI": "PL/I",
    "PL1": "PL/I",
    "PL/1": "PL/I",
    "ASSEMBLER": "assembler",
    "ASM": "assembler",
    "HLASM": "assembler",
}


def _language_named(text: str) -> str:
    """The language *text* names, as answers spell it."""
    found = _LANGUAGE_NAMES.get(text.strip().upper())
    if found is None:
        raise ToolError(f"unknown language {text!r}: give COBOL, PL/I or assembler")
    return found


def _path_matches(file: str, pattern: str) -> bool:
    """Whether root-relative *file* is under folder *pattern*, or matches it
    as a glob (``*``, ``?``, ``[...]``)."""
    import fnmatch

    wanted = pattern.strip().strip("/").replace("\\", "/")
    if any(c in wanted for c in "*?["):
        return fnmatch.fnmatchcase(file, wanted) or fnmatch.fnmatchcase(
            file.lower(), wanted.lower()
        )
    return file == wanted or file.startswith(wanted + "/")
