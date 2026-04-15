"""Contract tests for AST statement model to_dict() serialization.

Guards against silent JSON structure regressions in arithmetic, IO, and misc models.
Each test directly constructs a node, calls to_dict(), and asserts the exact set of
keys present plus the values of specific fields. This catches:
- Missing keys (field removed from to_dict)
- Renamed keys (field renamed)
- Wrong default values
- Nested serialization failures

Covers:
- arithmetic: AddStatement, SubtractStatement, MultiplyStatement, DivideStatement,
              ComputeStatement
- io: IOReadStatement, IOWriteStatement, IOOpenStatement, IOCloseStatement,
      IOAcceptStatement, IORewriteStatement, IODeleteStatement, IOStartStatement,
      IOUnlockStatement
- misc: SelectStatement, CopyStatement, ContinueStatement, ExitStatement,
        GobackStatement, CancelStatement, AlterStatement, GenerateStatement,
        ReleaseStatement, ReturnStatement, UseStatement, SortStatement,
        MergeStatement
"""

from cobolparser.models.ast_base import SourceLocation
from cobolparser.models.statements.arithmetic import (
    AddStatement,
    ComputeStatement,
    DivideStatement,
    MultiplyStatement,
    SubtractStatement,
)
from cobolparser.models.statements.io import (
    IOAcceptStatement,
    IOCloseStatement,
    IODeleteStatement,
    IOOpenStatement,
    IOReadStatement,
    IORewriteStatement,
    IOStartStatement,
    IOUnlockStatement,
    IOWriteStatement,
)
from cobolparser.models.statements.misc import (
    AlterStatement,
    CancelStatement,
    ContinueStatement,
    CopyStatement,
    ExitStatement,
    GenerateStatement,
    GobackStatement,
    MergeStatement,
    ReleaseStatement,
    ReturnStatement,
    SelectStatement,
    SortStatement,
    UseStatement,
)


def _loc() -> SourceLocation:
    return SourceLocation(1, 1)


# ===========================================================================
# Arithmetic statement contracts
# ===========================================================================


class TestAddStatementContract:
    def test_to_dict_has_required_keys(self):
        stmt = AddStatement(_loc())
        d = stmt.to_dict()
        assert d["statement_type"] == "ADD"
        assert "operands" in d
        assert "location" in d

    def test_to_dict_target_field(self):
        stmt = AddStatement(_loc())
        stmt.set_target("WS-RESULT")
        d = stmt.to_dict()
        assert d["target"] == "WS-RESULT"

    def test_to_dict_giving_field(self):
        stmt = AddStatement(_loc())
        stmt.set_giving("WS-OUT")
        d = stmt.to_dict()
        assert d["giving"] == "WS-OUT"

    def test_to_dict_no_size_error_by_default(self):
        stmt = AddStatement(_loc())
        d = stmt.to_dict()
        assert "on_size_error" not in d
        assert "not_on_size_error" not in d

    def test_to_dict_with_on_size_error(self):
        stmt = AddStatement(_loc())
        inner = ContinueStatement(_loc())
        stmt.set_on_size_error_clause([inner])
        d = stmt.to_dict()
        assert "on_size_error" in d
        assert isinstance(d["on_size_error"], list)
        assert len(d["on_size_error"]) == 1

    def test_to_dict_with_not_on_size_error(self):
        stmt = AddStatement(_loc())
        inner = ContinueStatement(_loc())
        stmt.set_not_on_size_error_clause([inner])
        d = stmt.to_dict()
        assert "not_on_size_error" in d


class TestSubtractStatementContract:
    def test_statement_type(self):
        stmt = SubtractStatement(_loc())
        assert stmt.to_dict()["statement_type"] == "SUBTRACT"

    def test_target_and_giving(self):
        stmt = SubtractStatement(_loc())
        stmt.set_target("WS-A")
        stmt.set_giving("WS-B")
        d = stmt.to_dict()
        assert d["target"] == "WS-A"
        assert d["giving"] == "WS-B"


class TestMultiplyStatementContract:
    def test_statement_type(self):
        stmt = MultiplyStatement(_loc())
        assert stmt.to_dict()["statement_type"] == "MULTIPLY"


class TestDivideStatementContract:
    def test_statement_type(self):
        stmt = DivideStatement(_loc())
        assert stmt.to_dict()["statement_type"] == "DIVIDE"


class TestComputeStatementContract:
    def test_to_dict_required_keys(self):
        stmt = ComputeStatement(_loc())
        d = stmt.to_dict()
        assert d["statement_type"] == "COMPUTE"
        assert "targets" in d
        assert "expression" in d
        assert "operands" in d

    def test_to_dict_targets_list(self):
        stmt = ComputeStatement(_loc())
        stmt.add_target("WS-RESULT")
        d = stmt.to_dict()
        assert "WS-RESULT" in d["targets"]

    def test_to_dict_string_expression(self):
        stmt = ComputeStatement(_loc())
        stmt.set_expression("WS-A + WS-B")
        d = stmt.to_dict()
        assert d["expression"] == "WS-A + WS-B"

    def test_to_dict_with_size_error(self):
        stmt = ComputeStatement(_loc())
        inner = ContinueStatement(_loc())
        stmt.set_on_size_error_clause([inner])
        d = stmt.to_dict()
        assert "on_size_error" in d
        assert len(d["on_size_error"]) == 1


# ===========================================================================
# IO statement contracts
# ===========================================================================


class TestIOReadStatementContract:
    def test_to_dict_required_keys(self):
        stmt = IOReadStatement(_loc())
        d = stmt.to_dict()
        assert d["statement_type"] == "READ"
        expected_keys = {
            "file_name",
            "record_name",
            "into_target",
            "key_name",
            "access_mode",
            "lock_scope",
            "with_lock",
            "with_nowait",
            "at_end_clause",
            "not_at_end_clause",
            "invalid_key_clause",
            "not_invalid_key_clause",
            "retry_count",
        }
        for key in expected_keys:
            assert key in d, f"Missing key: {key}"

    def test_to_dict_defaults(self):
        stmt = IOReadStatement(_loc())
        d = stmt.to_dict()
        assert d["file_name"] is None
        assert d["into_target"] is None
        assert d["with_lock"] is False
        assert d["with_nowait"] is False
        assert d["at_end_clause"] == []
        assert d["invalid_key_clause"] == []
        assert d["retry_count"] is None

    def test_to_dict_with_values(self):
        stmt = IOReadStatement(_loc())
        stmt.set_file_name("CUSTOMER-FILE")
        stmt.set_into("WS-CUSTOMER-REC")
        stmt.set_key("CUST-ID")
        stmt.set_access_mode("NEXT")
        stmt.set_lock_mode(with_lock=True)
        stmt.set_retry(3)
        d = stmt.to_dict()
        assert d["file_name"] == "CUSTOMER-FILE"
        assert d["into_target"] == "WS-CUSTOMER-REC"
        assert d["key_name"] == "CUST-ID"
        assert d["access_mode"] == "NEXT"
        assert d["with_lock"] is True
        assert d["retry_count"] == 3

    def test_to_dict_at_end_clause_serialized(self):
        stmt = IOReadStatement(_loc())
        inner = ContinueStatement(_loc())
        stmt.set_at_end_clause([inner])
        d = stmt.to_dict()
        assert len(d["at_end_clause"]) == 1

    def test_to_dict_invalid_key_clause_serialized(self):
        stmt = IOReadStatement(_loc())
        inner = ContinueStatement(_loc())
        stmt.set_invalid_key_clause([inner])
        d = stmt.to_dict()
        assert len(d["invalid_key_clause"]) == 1


class TestIOWriteStatementContract:
    def test_to_dict_required_keys(self):
        stmt = IOWriteStatement(_loc())
        d = stmt.to_dict()
        assert d["statement_type"] == "WRITE"
        expected_keys = {
            "file_name",
            "record_name",
            "from_clause",
            "advancing_clause",
            "lock_scope",
            "delete_record",
            "with_lock",
            "at_eop_clause",
            "invalid_key_clause",
            "not_invalid_key_clause",
            "retry_count",
        }
        for key in expected_keys:
            assert key in d, f"Missing key: {key}"

    def test_to_dict_advancing_clause(self):
        stmt = IOWriteStatement(_loc())
        stmt.set_record_name("PRINT-REC")
        stmt.set_advancing("BEFORE", lines=2)
        d = stmt.to_dict()
        assert d["advancing_clause"] is not None
        assert d["advancing_clause"]["type"] == "BEFORE"
        assert d["advancing_clause"]["value"] == 2

    def test_to_dict_delete_flag(self):
        stmt = IOWriteStatement(_loc())
        stmt.set_delete(True)
        d = stmt.to_dict()
        assert d["delete_record"] is True

    def test_to_dict_lock_scope(self):
        stmt = IOWriteStatement(_loc())
        stmt.set_lock(True)
        d = stmt.to_dict()
        assert d["with_lock"] is True
        assert d["lock_scope"] == "record"


class TestIOOpenStatementContract:
    def test_to_dict_required_keys(self):
        stmt = IOOpenStatement(_loc())
        d = stmt.to_dict()
        assert d["statement_type"] == "OPEN"
        assert "open_mode" in d
        assert "file_names" in d
        assert "with_reposition" in d
        assert "reel_unit_control" in d

    def test_to_dict_with_mode_and_files(self):
        stmt = IOOpenStatement(_loc())
        stmt.set_open_mode("INPUT")
        stmt.add_file("CUSTOMER-FILE")
        stmt.add_file("ORDER-FILE")
        d = stmt.to_dict()
        assert d["open_mode"] == "INPUT"
        assert "CUSTOMER-FILE" in d["file_names"]
        assert "ORDER-FILE" in d["file_names"]

    def test_to_dict_reel_unit_control(self):
        stmt = IOOpenStatement(_loc())
        stmt.set_reel_unit_control("REEL")
        d = stmt.to_dict()
        assert d["reel_unit_control"] == "REEL"


class TestIOCloseStatementContract:
    def test_to_dict_required_keys(self):
        stmt = IOCloseStatement(_loc())
        d = stmt.to_dict()
        assert d["statement_type"] == "CLOSE"
        assert "file_names" in d
        assert "close_options" in d

    def test_to_dict_close_with_lock(self):
        stmt = IOCloseStatement(_loc())
        stmt.add_file("CUST-FILE", with_lock=True)
        d = stmt.to_dict()
        assert "CUST-FILE" in d["file_names"]
        assert d["close_options"]["CUST-FILE"]["with_lock"] is True

    def test_to_dict_close_no_rewind(self):
        stmt = IOCloseStatement(_loc())
        stmt.add_file("TAPE-FILE", reel=True, no_rewind=True)
        d = stmt.to_dict()
        opts = d["close_options"]["TAPE-FILE"]
        assert opts["reel"] is True
        assert opts["no_rewind"] is True


class TestIOAcceptStatementContract:
    def test_to_dict_required_keys(self):
        stmt = IOAcceptStatement(_loc())
        d = stmt.to_dict()
        assert d["statement_type"] == "ACCEPT"
        expected_keys = {
            "target",
            "from_source",
            "environment_name",
            "at_line",
            "at_column",
            "with_cursor",
            "color_attribute",
            "with_beep",
            "with_no_echo",
        }
        for key in expected_keys:
            assert key in d, f"Missing key: {key}"

    def test_to_dict_with_from_console(self):
        stmt = IOAcceptStatement(_loc())
        stmt.set_target("WS-INPUT")
        stmt.set_from("CONSOLE")
        d = stmt.to_dict()
        assert d["target"] == "WS-INPUT"
        assert d["from_source"] == "CONSOLE"

    def test_to_dict_with_position(self):
        stmt = IOAcceptStatement(_loc())
        stmt.set_position(line=5, column=10)
        d = stmt.to_dict()
        assert d["at_line"] == 5
        assert d["at_column"] == 10

    def test_to_dict_beep_and_no_echo(self):
        stmt = IOAcceptStatement(_loc())
        stmt.set_beep(True)
        stmt.set_no_echo(True)
        d = stmt.to_dict()
        assert d["with_beep"] is True
        assert d["with_no_echo"] is True

    def test_to_dict_environment_name(self):
        stmt = IOAcceptStatement(_loc())
        stmt.set_environment_name("PATH")
        d = stmt.to_dict()
        assert d["environment_name"] == "PATH"


class TestIORewriteStatementContract:
    def test_to_dict_required_keys(self):
        stmt = IORewriteStatement(_loc())
        d = stmt.to_dict()
        assert d["statement_type"] == "REWRITE_STATEMENT"
        assert "file_name" in d
        assert "record_name" in d
        assert "invalid_key_clause" in d
        assert "not_invalid_key_clause" in d
        assert "with_lock" in d

    def test_to_dict_with_lock(self):
        stmt = IORewriteStatement(_loc())
        stmt.set_lock(True)
        d = stmt.to_dict()
        assert d["with_lock"] is True


class TestIODeleteStatementContract:
    def test_to_dict_required_keys(self):
        stmt = IODeleteStatement(_loc())
        d = stmt.to_dict()
        assert d["statement_type"] == "DELETE_STATEMENT"
        assert "file_name" in d
        assert "invalid_key_clause" in d
        assert "not_invalid_key_clause" in d
        assert "with_lock" in d

    def test_to_dict_file_name(self):
        stmt = IODeleteStatement(_loc())
        stmt.set_file_name("ORDER-FILE")
        d = stmt.to_dict()
        assert d["file_name"] == "ORDER-FILE"

    def test_to_dict_invalid_key_clause(self):
        stmt = IODeleteStatement(_loc())
        inner = ContinueStatement(_loc())
        stmt.set_invalid_key_clause([inner])
        d = stmt.to_dict()
        assert len(d["invalid_key_clause"]) == 1


class TestIOStartStatementContract:
    def test_to_dict_required_keys(self):
        stmt = IOStartStatement(_loc())
        d = stmt.to_dict()
        assert d["statement_type"] == "START_STATEMENT"
        assert "file_name" in d
        assert "key_condition" in d
        assert "invalid_key_clause" in d
        assert "not_invalid_key_clause" in d

    def test_to_dict_key_condition(self):
        stmt = IOStartStatement(_loc())
        stmt.set_file_name("IDX-FILE")
        stmt.set_key_condition("EQUAL")
        d = stmt.to_dict()
        assert d["file_name"] == "IDX-FILE"
        assert d["key_condition"] == "EQUAL"


class TestIOUnlockStatementContract:
    def test_to_dict_required_keys(self):
        stmt = IOUnlockStatement(_loc())
        d = stmt.to_dict()
        assert d["statement_type"] == "UNLOCK_STATEMENT"
        assert "file_name" in d
        assert "record_scope" in d

    def test_to_dict_record_scope(self):
        stmt = IOUnlockStatement(_loc())
        stmt.set_file_name("CUST-FILE")
        stmt.set_record_scope("record")
        d = stmt.to_dict()
        assert d["file_name"] == "CUST-FILE"
        assert d["record_scope"] == "RECORD"


# ===========================================================================
# Misc statement contracts
# ===========================================================================


class TestSelectStatementContract:
    def test_to_dict_required_keys(self):
        stmt = SelectStatement(_loc())
        d = stmt.to_dict()
        assert d["statement_type"] == "SELECT"
        expected_keys = {
            "file_name",
            "is_optional",
            "assign_to",
            "assign_device_type",
            "assign_external_name",
            "organization",
            "access_mode",
            "record_key",
            "record_key_source",
            "alternate_keys",
            "file_status",
            "file_status_vsam",
            "relative_key",
            "reserve_areas",
            "padding_character",
            "record_delimiter",
            "password",
            "lock_mode",
            "lock_on",
            "lock_with_rollback",
            "sharing_mode",
        }
        for key in expected_keys:
            assert key in d, f"Missing key: {key}"

    def test_to_dict_optional_flag(self):
        stmt = SelectStatement(_loc())
        stmt.set_file_name("CUST-FILE", is_optional=True)
        d = stmt.to_dict()
        assert d["is_optional"] is True
        assert d["file_name"] == "CUST-FILE"

    def test_to_dict_organization_indexed(self):
        stmt = SelectStatement(_loc())
        stmt.set_organization("indexed")
        d = stmt.to_dict()
        assert d["organization"] == "INDEXED"

    def test_to_dict_alternate_keys(self):
        stmt = SelectStatement(_loc())
        stmt.add_alternate_key("ALT-KEY-1", duplicates_allowed=True)
        stmt.add_alternate_key("ALT-KEY-2")
        d = stmt.to_dict()
        assert len(d["alternate_keys"]) == 2
        assert d["alternate_keys"][0]["duplicates_allowed"] is True

    def test_to_dict_lock_mode(self):
        stmt = SelectStatement(_loc())
        stmt.set_lock_mode("MANUAL", lock_on="RECORD", with_rollback=True)
        d = stmt.to_dict()
        assert d["lock_mode"] == "MANUAL"
        assert d["lock_on"] == "RECORD"
        assert d["lock_with_rollback"] is True


class TestCopyStatementContract:
    def test_to_dict_required_keys(self):
        stmt = CopyStatement(_loc())
        d = stmt.to_dict()
        assert d["statement_type"] == "COPY"
        assert "copybook_name" in d
        assert "library_name" in d
        assert "suppressions" in d
        assert "replacements" in d

    def test_to_dict_with_replacements(self):
        stmt = CopyStatement(_loc())
        stmt.set_copybook_name("EMPREC")
        stmt.add_replacement(":TAG:", "EMP")
        d = stmt.to_dict()
        assert d["copybook_name"] == "EMPREC"
        assert len(d["replacements"]) == 1
        assert d["replacements"][0]["old_text"] == ":TAG:"
        assert d["replacements"][0]["new_text"] == "EMP"


class TestContinueStatementContract:
    def test_to_dict_statement_type(self):
        stmt = ContinueStatement(_loc())
        d = stmt.to_dict()
        assert d["statement_type"] == "CONTINUE"


class TestExitStatementContract:
    def test_to_dict_required_keys(self):
        stmt = ExitStatement(_loc())
        d = stmt.to_dict()
        assert d["statement_type"] == "EXIT"
        assert "exit_type" in d

    def test_to_dict_exit_program(self):
        stmt = ExitStatement(_loc())
        stmt.set_exit_type("PROGRAM")
        d = stmt.to_dict()
        assert d["exit_type"] == "PROGRAM"


class TestGobackStatementContract:
    def test_to_dict_required_keys(self):
        stmt = GobackStatement(_loc())
        d = stmt.to_dict()
        assert d["statement_type"] == "GOBACK"
        assert "returning_value" in d

    def test_to_dict_with_returning_value(self):
        stmt = GobackStatement(_loc())
        stmt.set_returning_value("WS-RETURN-CODE")
        d = stmt.to_dict()
        assert d["returning_value"] == "WS-RETURN-CODE"


class TestCancelStatementContract:
    def test_to_dict_required_keys(self):
        stmt = CancelStatement(_loc())
        d = stmt.to_dict()
        assert d["statement_type"] == "CANCEL"
        assert "program_names" in d

    def test_to_dict_multiple_program_names(self):
        stmt = CancelStatement(_loc())
        stmt.add_program_name("PROG-A")
        stmt.add_program_name("PROG-B")
        d = stmt.to_dict()
        assert "PROG-A" in d["program_names"]
        assert "PROG-B" in d["program_names"]


class TestAlterStatementContract:
    def test_to_dict_required_keys(self):
        stmt = AlterStatement(_loc())
        d = stmt.to_dict()
        assert d["statement_type"] == "ALTER"
        assert "alterations" in d

    def test_to_dict_alterations(self):
        stmt = AlterStatement(_loc())
        stmt.add_alteration("PARA-A", "PARA-B")
        d = stmt.to_dict()
        assert len(d["alterations"]) == 1
        assert d["alterations"][0]["from_paragraph"] == "PARA-A"
        assert d["alterations"][0]["to_paragraph"] == "PARA-B"


class TestGenerateStatementContract:
    def test_to_dict_required_keys(self):
        stmt = GenerateStatement(_loc())
        d = stmt.to_dict()
        assert d["statement_type"] == "GENERATE"
        assert "report_name" in d

    def test_to_dict_report_name(self):
        stmt = GenerateStatement(_loc())
        stmt.set_report_name("MONTHLY-REPORT")
        d = stmt.to_dict()
        assert d["report_name"] == "MONTHLY-REPORT"


class TestReleaseStatementContract:
    def test_to_dict_required_keys(self):
        stmt = ReleaseStatement(_loc())
        d = stmt.to_dict()
        assert d["statement_type"] == "RELEASE"
        assert "record_name" in d
        assert "from_source" in d

    def test_to_dict_from_source(self):
        stmt = ReleaseStatement(_loc())
        stmt.set_record_name("SORT-REC")
        stmt.set_from_source("WS-INPUT-AREA")
        d = stmt.to_dict()
        assert d["record_name"] == "SORT-REC"
        assert d["from_source"] == "WS-INPUT-AREA"


class TestReturnStatementContract:
    def test_to_dict_required_keys(self):
        stmt = ReturnStatement(_loc())
        d = stmt.to_dict()
        assert d["statement_type"] == "RETURN"
        assert "file_name" in d
        assert "into_target" in d

    def test_to_dict_at_end_clause(self):
        stmt = ReturnStatement(_loc())
        stmt.set_file_name("SORT-FILE")
        inner = ContinueStatement(_loc())
        stmt.set_at_end_clause([inner])
        d = stmt.to_dict()
        assert "at_end_clause" in d
        assert len(d["at_end_clause"]) == 1


class TestUseStatementContract:
    def test_to_dict_required_keys(self):
        stmt = UseStatement(_loc())
        d = stmt.to_dict()
        assert d["statement_type"] == "USE"
        assert "use_type" in d
        assert "is_global" in d
        assert "file_names" in d

    def test_to_dict_global_exception(self):
        stmt = UseStatement(_loc())
        stmt.set_use_type("EXCEPTION")
        stmt.set_global(True)
        stmt.add_file_name("CUST-FILE")
        d = stmt.to_dict()
        assert d["use_type"] == "EXCEPTION"
        assert d["is_global"] is True
        assert "CUST-FILE" in d["file_names"]


class TestSortStatementModelContract:
    def test_to_dict_required_keys(self):
        stmt = SortStatement(_loc())
        d = stmt.to_dict()
        assert d["statement_type"] == "SORT"
        expected_keys = {
            "file_name",
            "keys",
            "duplicates_in_order",
            "collating_sequence",
            "input_procedure",
            "input_procedure_thru",
            "output_procedure",
            "output_procedure_thru",
            "using_files",
            "giving_files",
        }
        for key in expected_keys:
            assert key in d, f"Missing key: {key}"

    def test_to_dict_keys(self):
        stmt = SortStatement(_loc())
        stmt.set_file_name("SORT-FILE")
        stmt.add_key("FIELD-A", "ASCENDING")
        stmt.add_key("FIELD-B", "DESCENDING")
        d = stmt.to_dict()
        assert d["file_name"] == "SORT-FILE"
        assert len(d["keys"]) == 2
        assert d["keys"][0] == {"field": "FIELD-A", "order": "ASCENDING"}
        assert d["keys"][1] == {"field": "FIELD-B", "order": "DESCENDING"}

    def test_to_dict_procedures(self):
        stmt = SortStatement(_loc())
        stmt.set_input_procedure("IN-PARA", "IN-PARA-END")
        stmt.set_output_procedure("OUT-PARA", None)
        d = stmt.to_dict()
        assert d["input_procedure"] == "IN-PARA"
        assert d["input_procedure_thru"] == "IN-PARA-END"
        assert d["output_procedure"] == "OUT-PARA"
        assert d["output_procedure_thru"] is None

    def test_to_dict_using_giving(self):
        stmt = SortStatement(_loc())
        stmt.add_using_file("FILE-A")
        stmt.add_using_file("FILE-B")
        stmt.add_giving_file("OUT-FILE")
        d = stmt.to_dict()
        assert d["using_files"] == ["FILE-A", "FILE-B"]
        assert d["giving_files"] == ["OUT-FILE"]


class TestMergeStatementModelContract:
    def test_to_dict_required_keys(self):
        stmt = MergeStatement(_loc())
        d = stmt.to_dict()
        assert d["statement_type"] == "MERGE"
        expected_keys = {
            "file_name",
            "keys",
            "collating_sequence",
            "output_procedure",
            "output_procedure_thru",
            "using_files",
            "giving_files",
        }
        for key in expected_keys:
            assert key in d, f"Missing key: {key}"

    def test_to_dict_values(self):
        stmt = MergeStatement(_loc())
        stmt.set_file_name("MERGE-FILE")
        stmt.add_key("KEY-FIELD", "ASCENDING")
        stmt.add_using_file("FILE-A")
        stmt.add_using_file("FILE-B")
        stmt.add_giving_file("OUT")
        stmt.set_output_procedure("PROC-OUT", "PROC-END")
        d = stmt.to_dict()
        assert d["file_name"] == "MERGE-FILE"
        assert len(d["keys"]) == 1
        assert len(d["using_files"]) == 2
        assert d["giving_files"] == ["OUT"]
        assert d["output_procedure"] == "PROC-OUT"
        assert d["output_procedure_thru"] == "PROC-END"
