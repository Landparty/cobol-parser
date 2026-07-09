"""Regression tests for the MEDIUM-severity findings in reports/open-findings.md.

Mirrors tests/regression/test_open_findings_high_regressions.py's convention:
one TestM<N>... class per finding, named for direct traceability.
"""

from __future__ import annotations

import textwrap

from cobolparser import parse_cobol
from cobolparser.models.statements import DisplayStatement


def _data_program(data_item_line: str) -> str:
    """Wrap a single WORKING-STORAGE data-item line in a minimal program."""
    return textwrap.dedent(f"""\
        IDENTIFICATION DIVISION.
        PROGRAM-ID. REGTEST.
        DATA DIVISION.
        WORKING-STORAGE SECTION.
        {data_item_line}
        PROCEDURE DIVISION.
        MAIN-PARA.
            DISPLAY "OK".
            STOP RUN.
        """)


def _proc_program(procedure_body: str) -> str:
    """Wrap bare PROCEDURE DIVISION statements in a minimal COBOL program."""
    return textwrap.dedent(f"""\
        IDENTIFICATION DIVISION.
        PROGRAM-ID. REGTEST.
        DATA DIVISION.
        WORKING-STORAGE SECTION.
        01 WS-X PIC X(20).
        PROCEDURE DIVISION.
        MAIN-PARA.
        {procedure_body}
        """)


def _statements(result):
    proc = result.ast.procedure_division
    if proc.paragraphs:
        return proc.paragraphs[0].statements
    if proc.sections and proc.sections[0].paragraphs:
        return proc.sections[0].paragraphs[0].statements
    return []


class TestM16SlashEditedPicture:
    """M16 -- PIC 99/99/99 corrupted DATA DIVISION structure.

    _PICTURE_SYMBOL_TOKEN_TYPES used TokenType.DIVIDE/MULTIPLY (the DIVIDE/
    MULTIPLY *statement* keywords) instead of TokenType.DIVIDE_OP/
    MULTIPLY_OP (what '/' and '*' actually lex to), so picture pattern
    collection stopped at the first edit symbol and the remainder was
    misparsed as phantom level-99 data items.
    """

    def test_slash_edited_picture_pattern_is_not_truncated(self):
        result = parse_cobol(
            _data_program("    05 WS-FIELD PIC 99/99/99.")
        )
        assert result.errors == []
        items = result.ast.find_all_by_type("CobolDataItem")
        names = [i.name for i in items]
        assert "WS-FIELD" in names
        assert not any(n.startswith("ANONYMOUS-99") for n in names), names
        field = next(i for i in items if i.name == "WS-FIELD")
        assert field.picture_clause.pattern == "99/99/99"
        assert not any("Unparsed token" in w for w in result.warnings), result.warnings

    def test_check_protect_asterisk_picture_pattern_is_not_truncated(self):
        result = parse_cobol(
            _data_program("    01 WS-AMT PIC $***,**9.99.")
        )
        assert result.errors == []
        items = result.ast.find_all_by_type("CobolDataItem")
        field = next(i for i in items if i.name == "WS-AMT")
        assert field.picture_clause.pattern == "$***,**9.99"
        assert not any("Unparsed token" in w for w in result.warnings), result.warnings


class TestM14CacheHitBytesAccounting:
    """M14 -- copybook cache hits bypassed total_bytes accounting.

    context.total_bytes was only incremented on a cache miss; a copybook
    served from the intra-expansion cache (diamond dependency: the same
    member COPYd multiple times) contributed zero bytes to the running
    total, so max_total_size was never enforced against the true expanded
    content size.
    """

    def test_repeated_copy_of_same_member_counts_every_inclusion(self, tmp_path):
        from cobolparser.preprocess import (
            TotalExpansionSizeExceededError,
            expand_copybooks,
        )

        copybook_dir = tmp_path / "copybooks"
        copybook_dir.mkdir()
        payload = "01 WS-FIELD-" + "X" * 60 + " PIC X.\n"
        content_size = len(payload.encode("utf-8"))
        (copybook_dir / "MEMBER.cpy").write_text(payload)

        source = (
            "IDENTIFICATION DIVISION.\n"
            "PROGRAM-ID. REGTEST.\n"
            "DATA DIVISION.\n"
            "WORKING-STORAGE SECTION.\n"
            "       COPY MEMBER.\n"
            "       COPY MEMBER.\n"
            "       COPY MEMBER.\n"
        )
        # Limit set strictly between 1x and 3x the single-copybook size:
        # under the M14 bug, only the first (cache-miss) inclusion counted,
        # so 3 inclusions never tripped a limit sized for ~1.5 copies.
        limit = int(content_size * 1.5)

        raised = False
        try:
            expand_copybooks(
                source,
                copybook_paths=[str(copybook_dir)],
                max_total_size=limit,
            )
        except TotalExpansionSizeExceededError:
            raised = True
        assert raised, (
            "3x inclusion of a copybook whose combined size exceeds "
            "max_total_size must raise, even when later inclusions are "
            "served from the intra-expansion cache"
        )


class TestM9NestedStatementSwallowedException:
    """M9 -- try_parse_nested_statement's bare except Exception had no
    trace at all (not even a warning) for exceptions that bypass
    report_or_raise, e.g. TokenMismatch/UnexpectedEndOfInput raised
    directly by token_stream.expect().
    """

    def test_unrecorded_exception_surfaces_as_warning(self, monkeypatch):
        from cobolparser.parsers.statements import _utils

        class _FakeRegistry:
            def find_parser(self, stream):
                return self

            def parse(self, stream):
                raise ValueError("boom -- not routed through report_or_raise")

        class _FakeStream:
            _registry = _FakeRegistry()
            context = None

        collected_warnings = []

        class _FakeHost:
            def add_warning(self, message):
                collected_warnings.append(message)

        class _FakeContext:
            host = _FakeHost()

        monkeypatch.setattr(
            _utils, "get_parse_context", lambda stream: _FakeContext()
        )

        result = _utils.try_parse_nested_statement(_FakeStream())

        assert result is None
        assert len(collected_warnings) == 1
        assert "boom" in collected_warnings[0]

    def test_already_recorded_exception_does_not_double_warn(self, monkeypatch):
        from cobolparser.parsers.statements import _utils

        class _AlreadyRecordedError(Exception):
            _already_recorded = True

        class _FakeRegistry:
            def find_parser(self, stream):
                return self

            def parse(self, stream):
                raise _AlreadyRecordedError("already handled by report_or_raise")

        class _FakeStream:
            _registry = _FakeRegistry()
            context = None

        collected_warnings = []

        class _FakeHost:
            def add_warning(self, message):
                collected_warnings.append(message)

        class _FakeContext:
            host = _FakeHost()

        monkeypatch.setattr(
            _utils, "get_parse_context", lambda stream: _FakeContext()
        )

        result = _utils.try_parse_nested_statement(_FakeStream())

        assert result is None
        assert collected_warnings == []
