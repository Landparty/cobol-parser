"""Tests for SELECT and COPY statement model coverage.

Targets uncovered lines in models/statements/misc.py (70.30%):
  - SelectStatement setters: set_file_status, set_relative_key, set_reserve_areas,
    set_padding_character, set_record_delimiter, set_password, set_lock_mode,
    set_sharing_mode, to_dict
  - CopyStatement: set_copybook_name, set_library_name, add_suppression,
    add_replacement, to_dict
"""

from cobolparser.models.ast_base import SourceLocation
from cobolparser.models.statements.misc import SelectStatement


class TestSelectStatementModel:
    """Cover SelectStatement setters and to_dict."""

    def _make_stmt(self) -> SelectStatement:
        return SelectStatement(SourceLocation(1, 1))

    def test_set_file_status(self):
        stmt = self._make_stmt()
        stmt.set_file_status("WS-STATUS")
        assert stmt.file_status == "WS-STATUS"
        assert stmt.file_status_vsam is None

    def test_set_file_status_with_vsam(self):
        stmt = self._make_stmt()
        stmt.set_file_status("WS-STATUS", vsam_status="WS-VSAM-STATUS")
        assert stmt.file_status == "WS-STATUS"
        assert stmt.file_status_vsam == "WS-VSAM-STATUS"

    def test_set_reserve_areas(self):
        stmt = self._make_stmt()
        stmt.set_reserve_areas(3)
        assert stmt.reserve_areas == 3

    def test_set_padding_character(self):
        stmt = self._make_stmt()
        stmt.set_padding_character("X")
        assert stmt.padding_character == "X"

    def test_set_record_delimiter(self):
        stmt = self._make_stmt()
        stmt.set_record_delimiter("STANDARD-1")
        assert stmt.record_delimiter == "STANDARD-1"

    def test_set_password(self):
        stmt = self._make_stmt()
        stmt.set_password("WS-PWD")
        assert stmt.password == "WS-PWD"

    def test_set_lock_mode_manual(self):
        stmt = self._make_stmt()
        stmt.set_lock_mode("manual", lock_on="RECORD")
        assert stmt.lock_mode == "MANUAL"
        assert stmt.lock_on == "RECORD"
        assert stmt.lock_with_rollback is False

    def test_set_lock_mode_automatic_with_rollback(self):
        stmt = self._make_stmt()
        stmt.set_lock_mode("automatic", with_rollback=True)
        assert stmt.lock_mode == "AUTOMATIC"
        assert stmt.lock_with_rollback is True

    def test_set_lock_mode_exclusive(self):
        stmt = self._make_stmt()
        stmt.set_lock_mode("exclusive")
        assert stmt.lock_mode == "EXCLUSIVE"

    def test_set_sharing_mode(self):
        stmt = self._make_stmt()
        stmt.set_sharing_mode("all")
        assert stmt.sharing_mode == "ALL"

    def test_set_sharing_mode_read_only(self):
        stmt = self._make_stmt()
        stmt.set_sharing_mode("read only")
        assert stmt.sharing_mode == "READ ONLY"
