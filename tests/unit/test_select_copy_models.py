"""Tests for SELECT and COPY statement model coverage.

Targets uncovered lines in models/statements/misc.py (70.30%):
  - SelectStatement setters: set_file_status, set_relative_key, set_reserve_areas,
    set_padding_character, set_record_delimiter, set_password, set_lock_mode,
    set_sharing_mode, to_dict
  - CopyStatement: set_copybook_name, set_library_name, add_suppression,
    add_replacement, to_dict
"""

from cobolparser.models.ast_base import SourceLocation
from cobolparser.models.statements.misc import CopyStatement, SelectStatement


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

    def test_set_relative_key(self):
        stmt = self._make_stmt()
        stmt.set_relative_key("WS-REL-KEY")
        assert stmt.relative_key == "WS-REL-KEY"

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

    def test_to_dict_full(self):
        stmt = self._make_stmt()
        stmt.set_file_name("EMPLOYEE-FILE", is_optional=True)
        stmt.set_assign_to("EMPFILE", device_type="DISK", external_name="EMP.DAT")
        stmt.set_organization("INDEXED")
        stmt.set_access_mode("DYNAMIC")
        stmt.set_record_key("EMP-ID", source="EMP-KEY-SRC")
        stmt.add_alternate_key("EMP-NAME", duplicates_allowed=True, password="PWD1")
        stmt.set_file_status("WS-STATUS", vsam_status="WS-VSAM")
        stmt.set_relative_key("WS-REL")
        stmt.set_reserve_areas(2)
        stmt.set_padding_character("*")
        stmt.set_record_delimiter("STANDARD-1")
        stmt.set_password("WS-PWD")
        stmt.set_lock_mode("manual", lock_on="RECORD", with_rollback=True)
        stmt.set_sharing_mode("no other")

        d = stmt.to_dict()
        assert d["file_name"] == "EMPLOYEE-FILE"
        assert d["is_optional"] is True
        assert d["assign_to"] == "EMPFILE"
        assert d["assign_device_type"] == "DISK"
        assert d["assign_external_name"] == "EMP.DAT"
        assert d["organization"] == "INDEXED"
        assert d["access_mode"] == "DYNAMIC"
        assert d["record_key"] == "EMP-ID"
        assert d["record_key_source"] == "EMP-KEY-SRC"
        assert len(d["alternate_keys"]) == 1
        assert d["alternate_keys"][0]["duplicates_allowed"] is True
        assert d["file_status"] == "WS-STATUS"
        assert d["file_status_vsam"] == "WS-VSAM"
        assert d["relative_key"] == "WS-REL"
        assert d["reserve_areas"] == 2
        assert d["padding_character"] == "*"
        assert d["record_delimiter"] == "STANDARD-1"
        assert d["password"] == "WS-PWD"
        assert d["lock_mode"] == "MANUAL"
        assert d["lock_on"] == "RECORD"
        assert d["lock_with_rollback"] is True
        assert d["sharing_mode"] == "NO OTHER"


class TestCopyStatementModel:
    """Cover CopyStatement setters and to_dict."""

    def _make_stmt(self) -> CopyStatement:
        return CopyStatement(SourceLocation(1, 1))

    def test_set_copybook_name(self):
        stmt = self._make_stmt()
        stmt.set_copybook_name("EMPLOYEE")
        assert stmt.copybook_name == "EMPLOYEE"
        assert "EMPLOYEE" in stmt.operands

    def test_set_copybook_name_no_duplicate(self):
        stmt = self._make_stmt()
        stmt.set_copybook_name("EMPLOYEE")
        stmt.set_copybook_name("EMPLOYEE")
        assert stmt.operands.count("EMPLOYEE") == 1

    def test_set_library_name(self):
        stmt = self._make_stmt()
        stmt.set_library_name("MYLIB")
        assert stmt.library_name == "MYLIB"
        assert "MYLIB" in stmt.operands

    def test_set_library_name_no_duplicate(self):
        stmt = self._make_stmt()
        stmt.set_library_name("MYLIB")
        stmt.set_library_name("MYLIB")
        assert stmt.operands.count("MYLIB") == 1

    def test_add_suppression(self):
        stmt = self._make_stmt()
        stmt.add_suppression("SUPPRESS")
        assert stmt.suppressions == ["SUPPRESS"]

    def test_add_replacement(self):
        stmt = self._make_stmt()
        stmt.add_replacement("==OLD-TEXT==", "==NEW-TEXT==")
        assert len(stmt.replacements) == 1
        assert stmt.replacements[0]["old_text"] == "==OLD-TEXT=="
        assert stmt.replacements[0]["new_text"] == "==NEW-TEXT=="

    def test_add_multiple_replacements(self):
        stmt = self._make_stmt()
        stmt.add_replacement("A", "B")
        stmt.add_replacement("C", "D")
        assert len(stmt.replacements) == 2

    def test_to_dict(self):
        stmt = self._make_stmt()
        stmt.set_copybook_name("EMPLOYEE")
        stmt.set_library_name("COPYLIB")
        stmt.add_suppression("SUPPRESS")
        stmt.add_replacement("==OLD==", "==NEW==")

        d = stmt.to_dict()
        assert d["copybook_name"] == "EMPLOYEE"
        assert d["library_name"] == "COPYLIB"
        assert d["suppressions"] == ["SUPPRESS"]
        assert len(d["replacements"]) == 1
