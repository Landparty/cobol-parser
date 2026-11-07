"""Data tools: ``decode_record`` (a record image through a copybook) and
``gen_fixtures`` (a program's test-fixture bundle)."""

from __future__ import annotations

import difflib
import os
import re
from pathlib import Path
from typing import Any

from ..envelope import Response, ToolError, clamp_limit
from ..workspace import ParsedProgram, stdout_to_stderr
from .common import (
    BaseTools,
    _attempt,
    _carry_parse_caveats,
    _listed,
    _notes,
    _worth_showing,
)

#: Records ``decode_record`` reads when the caller names no ``max_records``.
DEFAULT_DECODE_RECORDS = 10


#: Most bytes of a data file ``decode_record`` reads: enough for any page
#: of records a model can use, never a whole multi-gigabyte extract.
MAX_DECODE_BYTES = 16 * 1024 * 1024


#: Generated rows per boundary sequence in ``gen_fixtures`` (the CLI's 10
#: is sized for a test run, not for a context window), and the most allowed.
DEFAULT_FIXTURE_ROWS = 3


MAX_FIXTURE_ROWS = 100


class DataTools(BaseTools):
    """``decode_record`` and ``gen_fixtures``."""

    # -- decode_record -------------------------------------------------------

    def decode_record(
        self,
        copybook: str,
        data_file: str | None = None,
        record: str | None = None,
        view: str | None = None,
        skip: int = 0,
        max_records: int | None = None,
        fields: list[str] | None = None,
        charset: str | None = None,
        endian: str | None = None,
        record_format: str | None = None,
        record_separator: str | None = None,
        record_length: int | None = None,
        limit: int | None = None,
    ) -> dict[str, Any]:
        """The records of *data_file* read through *copybook*'s layout, or,
        with no data file, the layout's views (its REDEFINES overlays)."""
        from ...generators.data.decoding import RecordDecoder, RecordDecodingError
        from ...generators.data.encoding import RecordFormat
        from ...generators.data.errors import CopybookLayoutError

        if skip < 0:
            raise ToolError("skip cannot be negative")
        if record_length is not None and record_length <= 0:
            raise ToolError("record_length must be a positive number of bytes")
        opts = self._encoding_options(charset, endian, record_format, record_separator)
        path = self.workspace.resolve(copybook)
        source = self.workspace.read_text(path)
        response = Response()
        try:
            with stdout_to_stderr():
                decoder = RecordDecoder.from_copybook_source(
                    source,
                    filename=str(path),
                    record=record,
                    opts=opts,
                    record_length=record_length,
                    copybook_paths=list(self.workspace.config.copybook_path) or None,
                )
        except CopybookLayoutError as exc:
            raise ToolError(self._relative(str(exc))) from exc
        for warning in decoder.layout_warnings:
            response.caveat(
                "unresolved-copybook",
                self._relative(warning),
                "the layout is short by that member's fields: every record "
                "after the first is framed at the wrong offset",
            )
        try:
            chosen = decoder.resolve_view(view)
        except RecordDecodingError as exc:
            raise ToolError(str(exc)) from exc
        views = decoder.views
        cap = clamp_limit(limit)
        placed = list(chosen.fields)
        if fields:
            asked = {" ".join(f.split()).upper() for f in fields}
            placed = [
                p
                for p in placed
                if p.spec.column.upper() in asked or p.spec.name.upper() in asked
            ]
            missing = (
                asked
                - {p.spec.column.upper() for p in placed}
                - {p.spec.name.upper() for p in placed}
            )
            if missing:
                response.caveat(
                    "incomplete-analysis",
                    f"no field of view {chosen.name} is named "
                    f"{_listed(sorted(missing))}",
                    "those fields are not shown",
                )
        shown_fields = response.cap(placed, cap, "fields")
        answer: dict[str, Any] = {
            "copybook": self.workspace.display(path),
            "record_name": views.record_name,
            "record_length": views.base.length,
            "framing_length": views.framing_length,
            "view": chosen.name,
            "views": [
                {
                    "name": v.name,
                    "redefines": v.redefines,
                    "offset": v.offset,
                    "length": v.length,
                }
                for v in views.views
            ],
            "fields": [
                {
                    "name": p.spec.column,
                    "offset": p.offset,
                    "length": p.length,
                    "picture": p.spec.picture,
                    "usage": p.spec.usage or "DISPLAY",
                }
                for p in shown_fields
            ],
        }
        for caveat in views.caveats:
            response.caveat("incomplete-analysis", caveat)
        if data_file is None:
            answer["note"] = (
                "the layout only: pass data_file to read records through it"
            )
            return response.build(answer)

        data_path = self.workspace.resolve(data_file)
        wanted_records = (
            DEFAULT_DECODE_RECORDS if max_records is None else clamp_limit(max_records)
        )
        # Fixed-length records with nothing between them sit at a known
        # stride, so a page past the read window starts by seeking to it.
        # Any other framing has to be walked from the front, and so stops at
        # the window (said below, with no `next` that would ask again).
        stride = 0
        fmt = opts.resolved_format(
            [placed.spec for placed in decoder.views.base.fields],
            varying=decoder.varying is not None,
        )
        if fmt is RecordFormat.FIXED and not opts.record_separator:
            stride = decoder.record_length or decoder.views.framing_length
        start = skip * stride if stride > 0 else 0
        local_skip = 0 if start else skip
        try:
            size = data_path.stat().st_size
            with data_path.open("rb") as handle:
                handle.seek(start)
                data = handle.read(MAX_DECODE_BYTES)
        except OSError as exc:
            raise ToolError(f"cannot read {data_file}: {exc}") from exc
        cut = size > start + len(data)
        try:
            with stdout_to_stderr():
                result = decoder.decode_bytes(
                    data, view=view, max_records=wanted_records, skip=local_skip
                )
        except RecordDecodingError as exc:
            raise ToolError(str(exc)) from exc
        window_spent = cut and len(result.records) < wanted_records
        for caveat in result.caveats:
            if caveat not in decoder.layout_warnings:
                response.caveat("incomplete-analysis", caveat)
        trailing = 0 if cut else len(result.trailing)
        more = result.bytes_read + len(result.trailing) < len(data) or cut
        if trailing:
            response.caveat(
                "incomplete-analysis",
                f"{trailing} trailing byte(s) are not a whole record",
                "the record length or record format is probably wrong: check "
                "record_length / record_format before trusting the values",
            )
        if window_spent:
            response.caveat(
                "incomplete-analysis",
                f"only {MAX_DECODE_BYTES} bytes of {data_file} ({size} bytes) "
                "are read per call, and under this record format each read "
                "starts at the front of the file: records past "
                f"byte {start + len(data)} cannot be reached",
                "decode a smaller extract of the file, or read it as fixed-"
                "length records with no separator if that is what it holds",
            )
        names = {p.spec.column for p in shown_fields}
        records = []
        for decoded in result.records:
            values = {f.name: f.value for f in decoded.fields if f.name in names}
            entry: dict[str, Any] = {
                "index": decoded.index + (skip if start else 0),
                "file_offset": decoded.file_offset + start,
                "length": decoded.length,
                "values": values,
            }
            absent = [
                f.name for f in decoded.fields if f.name in names and not f.present
            ]
            if absent:
                entry["absent"] = absent
            if decoded.errors:
                entry["errors"] = decoded.errors
            records.append(entry)
        answer.update(
            {
                "data_file": self.workspace.display(data_path),
                "file_bytes": size,
                "skip": skip,
                "record_count": len(records),
                "more_records": more,
                "error_count": result.error_count,
                "records": records,
            }
        )
        if more and not window_spent:
            answer["next"] = (
                f"more records follow: ask again with skip={skip + len(records)}"
            )
        return response.build(answer)

    def _encoding_options(
        self,
        charset: str | None,
        endian: str | None,
        record_format: str | None,
        record_separator: str | None,
    ) -> Any:
        """The EncodingOptions a data file is read through: each argument,
        else ``cobol.yml``'s ``data:`` section, else the built-in default."""
        from ...generators.data.encoding import (
            Charset,
            EncodingOptions,
            Endian,
            RecordFormat,
        )

        data = self.workspace.config.data
        chosen = {
            "charset": (charset or data.charset or "ascii").lower(),
            "endian": (endian or data.endian or "auto").lower(),
            "record_format": (record_format or data.record_format or "fixed").lower(),
            "record_separator": (
                record_separator or data.record_separator or "none"
            ).lower(),
        }
        if chosen["record_separator"] not in ("none", "newline"):
            raise ToolError(
                f"unknown record_separator {chosen['record_separator']!r} "
                "(expected none or newline)"
            )
        try:
            return EncodingOptions(
                charset=Charset(chosen["charset"]),
                endian=Endian(chosen["endian"]),
                record_format=RecordFormat(chosen["record_format"]),
                record_separator=(
                    b"\n" if chosen["record_separator"] == "newline" else b""
                ),
            )
        except ValueError as exc:
            raise ToolError(f"bad encoding option: {exc}") from exc

    # -- gen_fixtures --------------------------------------------------------

    def gen_fixtures(
        self,
        file: str,
        program: str | None = None,
        mode: str = "happy",
        seed: int | None = None,
        rows: int | None = None,
        scenario: str | None = None,
        limit: int | None = None,
    ) -> dict[str, Any]:
        """Test data for *file*: one scenario per path ``mode`` asks for,
        each with the values every mocked boundary supplies and what to
        assert afterwards."""
        from ...analysis.boundary_inventory import BoundaryInventoryAnalyzer
        from ...generators.data.options import DataGeneratorOptions
        from ...generators.data.program_layout import ProgramLayoutIndex
        from ...generators.program_fixtures import ProgramFixtureGenerator

        modes = ("happy", "branches", "all")
        chosen_mode = (mode or "happy").strip().lower()
        if chosen_mode not in modes:
            raise ToolError(
                f"unknown mode {mode!r} (expected one of {', '.join(modes)})"
            )
        row_count = DEFAULT_FIXTURE_ROWS if rows is None else rows
        if not 0 <= row_count <= MAX_FIXTURE_ROWS:
            raise ToolError(f"rows must be between 0 and {MAX_FIXTURE_ROWS}")
        bundle_seed = seed if seed is not None else (self.workspace.config.seed or 0)
        parsed = self.workspace.program(file)
        response = Response()
        _carry_parse_caveats(parsed, response)
        unit = parsed.unit(program, response)
        program_info = parsed.program_info(unit)
        callee_dirs = self.workspace.callee_directories(response)

        refused_callees: list[str] = []

        def accept(found: str) -> bool:
            # The directory is under the root, but a member of it may be a
            # link out of it: vetted like every other file a tool opens.
            if self.workspace.under_root(Path(found)):
                return True
            refused_callees.append(found)
            return False

        def build() -> Any:
            generator = ProgramFixtureGenerator(DataGeneratorOptions(rows=row_count))
            index = ProgramLayoutIndex.build(unit)
            callee_indexes, callee_asts = generator._resolve_callees(
                unit,
                callee_dirs or None,
                debug_lines=bool(self.workspace.config.debug_lines),
                accept=accept,
            )
            report = BoundaryInventoryAnalyzer().analyze(
                unit, index, callee_indexes=callee_indexes, callee_asts=callee_asts
            )
            return generator.generate_with_scenarios(
                unit, index, report, mode=chosen_mode, seed=bundle_seed
            )

        bundle = _attempt(response, "test fixtures", build)
        if refused_callees:
            response.caveat(
                "incomplete-analysis",
                "callee files that resolve outside the workspace were not read: "
                + ", ".join(
                    sorted(
                        {
                            Path(os.path.relpath(f, self.workspace.root)).as_posix()
                            for f in refused_callees
                        }
                    )
                ),
                "CALL arguments to those programs are classified without the "
                "callee's own PROCEDURE DIVISION USING",
            )
        if bundle is None:
            return response.build({"found": False, "scenarios": []}, program_info)
        cap = clamp_limit(limit)
        if bundle.unresolved:
            _notes(
                response,
                "incomplete-analysis",
                [self._relative(note) for note in bundle.unresolved],
                "the fixtures for these boundaries are partial or missing",
                lead=f"{len(bundle.unresolved)} item(s) could not be resolved",
            )
        scenarios = list(bundle.scenarios)
        if scenario:
            wanted = scenario.strip().lower()
            scenarios = [s for s in scenarios if wanted in s.name.lower()]
        shown = response.cap(scenarios, cap, "scenarios")
        answer: dict[str, Any] = {
            "program_id": bundle.program_name,
            "mode": chosen_mode,
            "seed": bundle.seed,
            "bundle_version": bundle.bundle_version,
            "rows_per_sequence": row_count,
            "coverage": bundle.coverage.to_dict(),
            "scenario_count": len(bundle.scenarios),
            "scenarios": [
                _scenario(s, i, parsed, response, cap) for i, s in enumerate(shown)
            ],
            "replay": (
                f"the same file, mode and seed ({bundle.seed}) give the same "
                "data; cobol-parser gen-fixtures writes the bundle to disk "
                "(JSON or one CSV per boundary)"
            ),
        }
        if bundle.scenario_coverage is not None:
            answer["arm_coverage"] = _arm_coverage(
                bundle.scenario_coverage, parsed, response, cap
            )
        if scenario and not scenarios:
            answer["suggestions"] = difflib.get_close_matches(
                scenario, [s.name for s in bundle.scenarios], n=5
            )
        return response.build(answer, program_info)


def _scenario(
    scenario: Any, index: int, parsed: ParsedProgram, response: Response, cap: int
) -> dict[str, Any]:
    """One fixture scenario: rows as lists aligned to ``columns`` (a dict
    per row would repeat every column name in every row)."""
    fixtures = []
    for number, fixture in enumerate(
        response.cap(list(scenario.fixtures), cap, f"scenarios[{index}].fixtures")
    ):
        ref = fixture.ref
        columns = [spec.column for spec in fixture.layout]
        if not columns and fixture.sequence:
            columns = list(fixture.sequence[0])
        entry: dict[str, Any] = {
            "boundary": f"{ref.category}:{ref.key}",
            "paragraph": ref.paragraph,
            "location": parsed.locate(ref.line, None, response, column_known=False),
            "direction": fixture.direction,
            "provenance": fixture.provenance,
            "columns": columns,
            "rows": [
                [row.get(column, "") for column in columns]
                for row in response.cap(
                    list(fixture.sequence),
                    cap,
                    f"scenarios[{index}].fixtures[{number}].rows",
                )
            ],
            "terminal": fixture.terminal,
            "status": fixture.status,
            "unresolved": list(fixture.unresolved),
        }
        fixtures.append(
            {key: value for key, value in entry.items() if _worth_showing(value)}
        )
    result: dict[str, Any] = {
        "name": scenario.name,
        "intent": scenario.intent,
        "entry": scenario.entry,
        "fixtures": fixtures,
        "expectations": [
            {
                key: value
                for key, value in expectation.to_dict().items()
                if value is not None
            }
            for expectation in response.cap(
                list(scenario.expectations), cap, f"scenarios[{index}].expectations"
            )
        ],
        "unconstrained": list(scenario.unconstrained),
    }
    if scenario.entry_parameters is not None:
        result["entry_parameters"] = scenario.entry_parameters.to_dict()
    verification = scenario.verification
    if verification is not None:
        result["verification"] = {
            "status": verification.get("status"),
            "reasons": [
                f"{entry['field']}: {entry['detail']}"
                for entry in verification.get("fields", [])
                if entry.get("status") != "satisfied"
            ]
            + list(verification.get("gaps", [])),
        }
    return {key: value for key, value in result.items() if _worth_showing(value)}


#: ``<procedure>@<line>:<column>/...``: where an arm key's branch sits, in
#: the parse's (copybook-expanded) lines.
_ARM_KEY = re.compile(r"^(?P<proc>.*)@(?P<line>\d+):\d+/")


def _arm_coverage(
    coverage: dict[str, Any], parsed: ParsedProgram, response: Response, cap: int
) -> dict[str, Any]:
    """The branch-arm accounting, every missed arm with its reason."""
    missed = [d for d in coverage.get("details", []) if d.get("status") == "missed"]
    rows = []
    for detail in response.cap(missed, cap, "arm_coverage.missed_arms"):
        match = _ARM_KEY.match(detail.get("arm_key") or "")
        rows.append(
            {
                "arm": detail.get("arm_key"),
                "procedure": detail.get("parent_proc"),
                "location": (
                    parsed.locate(
                        int(match.group("line")), None, response, column_known=False
                    )
                    if match
                    else None
                ),
                "reason": detail.get("reason"),
            }
        )
    return {
        "total_arms": coverage.get("total_arms"),
        "targeted": coverage.get("targeted"),
        "merged": coverage.get("merged"),
        "missed": coverage.get("missed"),
        "missed_arms": rows,
    }
