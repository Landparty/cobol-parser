"""Comprehensive unit tests for IBM Enterprise COBOL dialect.

This module provides 100% test coverage for cobolparser/dialects/ibm_enterprise.py
including all classes, methods, properties, and edge cases.
"""

import pytest
from typing import Dict, List, Optional, Any

from cobolparser.dialects.ibm_enterprise import (
    IBMDataType,
    ExecSQLStatement,
    ExecCICSStatement, 
    IBMDataItem,
    IBMEnterpriseCobol
)
from cobolparser.models.ast_base import SourceLocation
from cobolparser.models.data_items import PictureClause
from cobolparser.plugins.core import DialectType


class TestIBMDataType:
    """Test IBMDataType enum."""
    
    def test_ibm_data_type_values(self):
        """Test all IBMDataType enum values."""
        assert IBMDataType.COMP.value == "COMP"
        assert IBMDataType.COMP_1.value == "COMP-1"
        assert IBMDataType.COMP_2.value == "COMP-2"
        assert IBMDataType.COMP_3.value == "COMP-3"
        assert IBMDataType.COMP_4.value == "COMP-4"
        assert IBMDataType.COMP_5.value == "COMP-5"
        assert IBMDataType.DISPLAY.value == "DISPLAY"
        assert IBMDataType.POINTER.value == "POINTER"
        assert IBMDataType.PROCEDURE_POINTER.value == "PROCEDURE-POINTER"
        assert IBMDataType.FUNCTION_POINTER.value == "FUNCTION-POINTER"
        assert IBMDataType.OBJECT_REFERENCE.value == "OBJECT REFERENCE"
    
    def test_ibm_data_type_enumeration(self):
        """Test enum iteration and membership."""
        data_types = list(IBMDataType)
        assert len(data_types) == 11
        assert IBMDataType.COMP_3 in data_types
        assert IBMDataType.POINTER in data_types
    
    def test_ibm_data_type_string_representation(self):
        """Test string representation of enum values."""
        assert str(IBMDataType.COMP_3) == "IBMDataType.COMP_3"
        assert repr(IBMDataType.COMP_3) == "<IBMDataType.COMP_3: 'COMP-3'>"
    
    def test_ibm_data_type_comparison(self):
        """Test enum comparison."""
        assert IBMDataType.COMP == IBMDataType.COMP
        assert IBMDataType.COMP != IBMDataType.COMP_3
        assert IBMDataType.DISPLAY != IBMDataType.POINTER


class TestExecSQLStatement:
    """Test ExecSQLStatement class."""
    
    def test_exec_sql_statement_creation(self):
        """Test basic creation of ExecSQLStatement."""
        location = SourceLocation("test.cob", 10, 5)
        stmt = ExecSQLStatement(location)
        
        assert stmt.node_type == "Statement"
        assert stmt.statement_type == "EXEC-SQL"
        assert stmt.location == location
        assert stmt.sql_text == ""
        assert stmt.sql_type == "UNKNOWN"
        assert stmt.host_variables == []
    
    def test_set_sql_text_basic(self):
        """Test setting basic SQL text."""
        location = SourceLocation("test.cob", 10, 5)
        stmt = ExecSQLStatement(location)
        
        stmt.set_sql_text("SELECT * FROM EMPLOYEE")
        
        assert stmt.sql_text == "SELECT * FROM EMPLOYEE"
        assert stmt.sql_type == "SELECT"
    
    def test_set_sql_text_with_whitespace(self):
        """Test setting SQL text with leading/trailing whitespace."""
        location = SourceLocation("test.cob", 10, 5)
        stmt = ExecSQLStatement(location)
        
        stmt.set_sql_text("   INSERT INTO EMPLOYEE VALUES (1, 'John')   ")
        
        assert stmt.sql_text == "INSERT INTO EMPLOYEE VALUES (1, 'John')"
        assert stmt.sql_type == "INSERT"
    
    def test_set_sql_text_all_types(self):
        """Test SQL type detection for all supported types."""
        location = SourceLocation("test.cob", 10, 5)
        stmt = ExecSQLStatement(location)
        
        test_cases = [
            ("SELECT * FROM TABLE", "SELECT"),
            ("INSERT INTO TABLE VALUES (1)", "INSERT"),
            ("UPDATE TABLE SET COL=1", "UPDATE"),
            ("DELETE FROM TABLE", "DELETE"),
            ("CREATE TABLE TEST (ID INT)", "CREATE"),
            ("DROP TABLE TEST", "DROP"),
            ("ALTER TABLE TEST ADD COLUMN", "ALTER"),
            ("COMMIT", "UNKNOWN"),  # Not in recognized types
            ("", "UNKNOWN")  # Empty string
        ]
        
        for sql_text, expected_type in test_cases:
            stmt.set_sql_text(sql_text)
            assert stmt.sql_type == expected_type, f"Failed for: {sql_text}"
    
    def test_add_host_variable(self):
        """Test adding host variables."""
        location = SourceLocation("test.cob", 10, 5)
        stmt = ExecSQLStatement(location)
        
        stmt.add_host_variable("WS-EMP-ID")
        stmt.add_host_variable("WS-EMP-NAME")
        
        assert "WS-EMP-ID" in stmt.host_variables
        assert "WS-EMP-NAME" in stmt.host_variables
        assert len(stmt.host_variables) == 2
    
    def test_add_host_variable_duplicate(self):
        """Test adding duplicate host variables."""
        location = SourceLocation("test.cob", 10, 5)
        stmt = ExecSQLStatement(location)
        
        stmt.add_host_variable("WS-EMP-ID")
        stmt.add_host_variable("WS-EMP-ID")  # Duplicate
        
        assert stmt.host_variables == ["WS-EMP-ID"]
        assert len(stmt.host_variables) == 1
    
    def test_exec_sql_to_dict(self):
        """Test converting ExecSQLStatement to dictionary."""
        location = SourceLocation("test.cob", 10, 5)
        stmt = ExecSQLStatement(location)
        stmt.set_sql_text("SELECT * FROM EMPLOYEE WHERE ID = :WS-EMP-ID")
        stmt.add_host_variable("WS-EMP-ID")
        
        result = stmt.to_dict()
        
        assert result["statement_type"] == "EXEC-SQL"
        assert result["sql_text"] == "SELECT * FROM EMPLOYEE WHERE ID = :WS-EMP-ID"
        assert result["sql_type"] == "SELECT"
        assert result["host_variables"] == ["WS-EMP-ID"]
        assert "location" in result
    
    def test_exec_sql_inheritance(self):
        """Test that ExecSQLStatement properly inherits from CobolStatement."""
        location = SourceLocation("test.cob", 10, 5)
        stmt = ExecSQLStatement(location)
        
        # Test inherited properties
        assert hasattr(stmt, 'operands')
        assert hasattr(stmt, 'add_operand')
        assert stmt.location == location


class TestExecCICSStatement:
    """Test ExecCICSStatement class."""
    
    def test_exec_cics_statement_creation(self):
        """Test basic creation of ExecCICSStatement."""
        location = SourceLocation("test.cob", 15, 8)
        stmt = ExecCICSStatement(location)
        
        assert stmt.node_type == "Statement"
        assert stmt.statement_type == "EXEC-CICS"
        assert stmt.location == location
        assert stmt.cics_command == ""
        assert stmt.cics_options == {}
    
    def test_set_command(self):
        """Test setting CICS command."""
        location = SourceLocation("test.cob", 15, 8)
        stmt = ExecCICSStatement(location)
        
        stmt.set_command("receive")
        assert stmt.cics_command == "RECEIVE"
        
        stmt.set_command("SEND")
        assert stmt.cics_command == "SEND"
    
    def test_add_option_without_value(self):
        """Test adding CICS option without value."""
        location = SourceLocation("test.cob", 15, 8)
        stmt = ExecCICSStatement(location)
        
        stmt.add_option("NOHANDLE")
        
        assert "NOHANDLE" in stmt.cics_options
        assert stmt.cics_options["NOHANDLE"] == ""
    
    def test_add_option_with_value(self):
        """Test adding CICS option with value."""
        location = SourceLocation("test.cob", 15, 8)
        stmt = ExecCICSStatement(location)
        
        stmt.add_option("INTO", "WS-DATA")
        stmt.add_option("length", "100")
        
        assert stmt.cics_options["INTO"] == "WS-DATA"
        assert stmt.cics_options["LENGTH"] == "100"
    
    def test_add_multiple_options(self):
        """Test adding multiple CICS options."""
        location = SourceLocation("test.cob", 15, 8)
        stmt = ExecCICSStatement(location)
        
        stmt.add_option("INTO", "WS-BUFFER")
        stmt.add_option("LENGTH", "80")
        stmt.add_option("NOHANDLE")
        
        assert len(stmt.cics_options) == 3
        assert stmt.cics_options["INTO"] == "WS-BUFFER"
        assert stmt.cics_options["LENGTH"] == "80"
        assert stmt.cics_options["NOHANDLE"] == ""
    
    def test_exec_cics_to_dict(self):
        """Test converting ExecCICSStatement to dictionary."""
        location = SourceLocation("test.cob", 15, 8)
        stmt = ExecCICSStatement(location)
        stmt.set_command("RECEIVE")
        stmt.add_option("INTO", "WS-COMMAREA")
        stmt.add_option("LENGTH", "100")
        
        result = stmt.to_dict()
        
        assert result["statement_type"] == "EXEC-CICS"
        assert result["cics_command"] == "RECEIVE"
        assert result["cics_options"]["INTO"] == "WS-COMMAREA"
        assert result["cics_options"]["LENGTH"] == "100"
        assert "location" in result
    
    def test_exec_cics_inheritance(self):
        """Test that ExecCICSStatement properly inherits from CobolStatement."""
        location = SourceLocation("test.cob", 15, 8)
        stmt = ExecCICSStatement(location)
        
        # Test inherited properties
        assert hasattr(stmt, 'operands')
        assert hasattr(stmt, 'add_operand')
        assert stmt.location == location


class TestIBMDataItem:
    """Test IBMDataItem class."""
    
    def test_ibm_data_item_creation(self):
        """Test basic creation of IBMDataItem."""
        location = SourceLocation("test.cob", 20, 12)
        item = IBMDataItem("WS-AMOUNT", 5, location)
        
        assert item.name == "WS-AMOUNT"
        assert item.level == 5
        assert item.location == location
        assert item.ibm_usage is None
        assert item.sign_clause is None
        assert item.synchronized is False
        assert item.justified is False
        assert item.blank_when_zero is False
    
    def test_set_ibm_usage(self):
        """Test setting IBM-specific USAGE clause."""
        location = SourceLocation("test.cob", 20, 12)
        item = IBMDataItem("WS-AMOUNT", 5, location)
        
        item.set_ibm_usage(IBMDataType.COMP_3)
        
        assert item.ibm_usage == IBMDataType.COMP_3
        assert item.usage == "COMP-3"
    
    def test_set_all_ibm_usage_types(self):
        """Test setting all IBM usage types."""
        location = SourceLocation("test.cob", 20, 12)
        
        for usage_type in IBMDataType:
            item = IBMDataItem(f"WS-{usage_type.name}", 5, location)
            item.set_ibm_usage(usage_type)
            
            assert item.ibm_usage == usage_type
            assert item.usage == usage_type.value
    
    def test_calculate_storage_size_no_picture(self):
        """Test storage size calculation without picture clause."""
        location = SourceLocation("test.cob", 20, 12)
        item = IBMDataItem("WS-AMOUNT", 5, location)
        
        size = item.calculate_storage_size()
        assert size == 0
    
    def test_calculate_storage_size_comp3(self):
        """Test COMP-3 storage size calculation."""
        location = SourceLocation("test.cob", 20, 12)
        item = IBMDataItem("WS-AMOUNT", 5, location)
        item.picture_clause = PictureClause("9(5)V99", location)
        item.set_ibm_usage(IBMDataType.COMP_3)
        
        # COMP-3: (digits + 1) / 2 = (7 + 1) / 2 = 4 bytes
        size = item.calculate_storage_size()
        assert size == 4
    
    def test_calculate_storage_size_comp3_odd_digits(self):
        """Test COMP-3 storage size with odd number of digits."""
        location = SourceLocation("test.cob", 20, 12)
        item = IBMDataItem("WS-COUNT", 5, location)
        item.picture_clause = PictureClause("9(5)", location)
        item.set_ibm_usage(IBMDataType.COMP_3)
        
        # COMP-3: (digits + 1) / 2 = (5 + 1) / 2 = 3 bytes
        size = item.calculate_storage_size()
        assert size == 3
    
    def test_calculate_storage_size_comp_binary(self):
        """Test COMP/COMP-4 binary storage size calculation."""
        location = SourceLocation("test.cob", 20, 12)
        
        # Test cases for binary storage sizes
        test_cases = [
            ("9(3)", 2),    # <= 4 digits: halfword (2 bytes)
            ("9(4)", 2),    # <= 4 digits: halfword (2 bytes)
            ("9(7)", 4),    # <= 9 digits: fullword (4 bytes)
            ("9(9)", 4),    # <= 9 digits: fullword (4 bytes)
            ("9(12)", 8),   # > 9 digits: doubleword (8 bytes)
        ]
        
        for picture, expected_size in test_cases:
            item = IBMDataItem(f"WS-{picture.replace('(', '').replace(')', '')}", 5, location)
            item.picture_clause = PictureClause(picture, location)
            item.set_ibm_usage(IBMDataType.COMP)
            
            size = item.calculate_storage_size()
            assert size == expected_size, f"Failed for {picture}: expected {expected_size}, got {size}"
    
    def test_calculate_storage_size_comp1_comp2(self):
        """Test COMP-1 and COMP-2 floating point storage sizes."""
        location = SourceLocation("test.cob", 20, 12)
        
        # COMP-1: single precision (4 bytes)
        item1 = IBMDataItem("WS-FLOAT", 5, location)
        item1.picture_clause = PictureClause("9(3)", location)
        item1.set_ibm_usage(IBMDataType.COMP_1)
        assert item1.calculate_storage_size() == 4
        
        # COMP-2: double precision (8 bytes)
        item2 = IBMDataItem("WS-DOUBLE", 5, location)
        item2.picture_clause = PictureClause("9(5)", location)
        item2.set_ibm_usage(IBMDataType.COMP_2)
        assert item2.calculate_storage_size() == 8
    
    def test_calculate_storage_size_comp5(self):
        """Test COMP-5 native binary storage size."""
        location = SourceLocation("test.cob", 20, 12)
        
        # Test different digit ranges for COMP-5
        test_cases = [
            ("9(3)", 2),    # <= 4 digits: halfword (2 bytes)
            ("9(5)", 4),    # <= 9 digits: fullword (4 bytes) 
            ("9(12)", 8),   # > 9 digits: doubleword (8 bytes) - covers line 136
        ]
        
        for picture, expected_size in test_cases:
            item = IBMDataItem("WS-NATIVE", 5, location)
            item.picture_clause = PictureClause(picture, location)
            item.set_ibm_usage(IBMDataType.COMP_5)
            
            size = item.calculate_storage_size()
            assert size == expected_size, f"Failed for {picture}: expected {expected_size}, got {size}"
    
    def test_calculate_storage_size_pointer(self):
        """Test POINTER storage size."""
        location = SourceLocation("test.cob", 20, 12)
        item = IBMDataItem("WS-PTR", 5, location)
        item.picture_clause = PictureClause("X(10)", location)  # Picture doesn't matter for pointer
        item.set_ibm_usage(IBMDataType.POINTER)
        
        size = item.calculate_storage_size()
        assert size == 4  # 32-bit pointer on z/OS
    
    def test_calculate_storage_size_display(self):
        """Test DISPLAY storage size (uses base picture size)."""
        location = SourceLocation("test.cob", 20, 12)
        item = IBMDataItem("WS-NAME", 5, location)
        item.picture_clause = PictureClause("X(30)", location)
        item.set_ibm_usage(IBMDataType.DISPLAY)
        
        size = item.calculate_storage_size()
        assert size == 30  # Base picture size
    
    def test_calculate_storage_size_non_ibm_usage(self):
        """Test storage size for non-IBM usage types (covers else clause)."""
        location = SourceLocation("test.cob", 20, 12)
        item = IBMDataItem("WS-TEST", 5, location)
        item.picture_clause = PictureClause("X(25)", location)
        
        # Set a non-IBM usage by directly setting usage without ibm_usage
        item.usage = "SOME-OTHER-USAGE"
        # Don't set item.ibm_usage, so it stays None
        
        size = item.calculate_storage_size()
        assert size == 25  # Should use base_size (covers line 140)
    
    def test_ibm_data_item_properties(self):
        """Test setting IBM-specific properties."""
        location = SourceLocation("test.cob", 20, 12)
        item = IBMDataItem("WS-TEST", 5, location)
        
        # Test modifying properties
        item.sign_clause = "LEADING"
        item.synchronized = True
        item.justified = True
        item.blank_when_zero = True
        
        assert item.sign_clause == "LEADING"
        assert item.synchronized is True
        assert item.justified is True
        assert item.blank_when_zero is True
    
    def test_ibm_data_item_to_dict(self):
        """Test converting IBMDataItem to dictionary."""
        location = SourceLocation("test.cob", 20, 12)
        item = IBMDataItem("WS-AMOUNT", 5, location)
        item.picture_clause = PictureClause("9(7)V99", location)
        item.set_ibm_usage(IBMDataType.COMP_3)
        item.sign_clause = "TRAILING"
        item.synchronized = True
        
        result = item.to_dict()
        
        assert result["name"] == "WS-AMOUNT"
        assert result["level"] == 5
        assert result["ibm_usage"] == "COMP-3"
        assert result["sign_clause"] == "TRAILING"
        assert result["synchronized"] is True
        assert result["justified"] is False
        assert result["blank_when_zero"] is False
        assert result["storage_size"] == 5  # (9 + 1) / 2
        assert "location" in result
    
    def test_ibm_data_item_to_dict_no_usage(self):
        """Test converting IBMDataItem to dictionary without IBM usage."""
        location = SourceLocation("test.cob", 20, 12)
        item = IBMDataItem("WS-NAME", 5, location)
        
        result = item.to_dict()
        
        assert result["ibm_usage"] is None
        assert result["storage_size"] == 0
    
    def test_ibm_data_item_inheritance(self):
        """Test that IBMDataItem properly inherits from CobolDataItem."""
        location = SourceLocation("test.cob", 20, 12)
        item = IBMDataItem("WS-TEST", 5, location)
        item.picture_clause = PictureClause("X(10)", location)  # Make it elementary
        
        # Test inherited properties and methods
        assert hasattr(item, 'value_clause')
        assert hasattr(item, 'occurs_clause')
        assert hasattr(item, 'redefines')
        assert hasattr(item, 'add_child')
        assert item.is_elementary_item() is True


class TestIBMEnterpriseCobol:
    """Test IBMEnterpriseCobol dialect class."""
    
    def test_ibm_enterprise_cobol_initialization(self):
        """Test basic initialization of IBMEnterpriseCobol."""
        dialect = IBMEnterpriseCobol()
        
        assert dialect.dialect_type == DialectType.IBM_ENTERPRISE
        assert "comp_3_packed_decimal" in dialect.supported_features
        assert "exec_sql" in dialect.supported_features
        assert "exec_cics" in dialect.supported_features
        assert "ibm_intrinsic_functions" in dialect.supported_features
        assert "pointer_data_types" in dialect.supported_features
        assert "object_oriented_cobol" in dialect.supported_features
        assert "zos_file_handling" in dialect.supported_features
    
    def test_ibm_reserved_words(self):
        """Test IBM reserved words are defined."""
        dialect = IBMEnterpriseCobol()
        
        # Test some key IBM reserved words
        assert "COMP-3" in dialect.IBM_RESERVED_WORDS
        assert "COMP-4" in dialect.IBM_RESERVED_WORDS
        assert "PACKED-DECIMAL" in dialect.IBM_RESERVED_WORDS
        assert "EXEC" in dialect.IBM_RESERVED_WORDS
        assert "SQL" in dialect.IBM_RESERVED_WORDS
        assert "CICS" in dialect.IBM_RESERVED_WORDS
        assert "END-EXEC" in dialect.IBM_RESERVED_WORDS
        assert "SQLCA" in dialect.IBM_RESERVED_WORDS
        assert "DFHCOMMAREA" in dialect.IBM_RESERVED_WORDS
        
        assert len(dialect.IBM_RESERVED_WORDS) >= 15
    
    def test_ibm_intrinsic_functions(self):
        """Test IBM intrinsic functions are defined."""
        dialect = IBMEnterpriseCobol()
        
        # Test some key IBM intrinsic functions
        assert "CURRENT-DATE" in dialect.IBM_INTRINSIC_FUNCTIONS
        assert "LENGTH" in dialect.IBM_INTRINSIC_FUNCTIONS
        assert "NUMVAL" in dialect.IBM_INTRINSIC_FUNCTIONS
        assert "UPPER-CASE" in dialect.IBM_INTRINSIC_FUNCTIONS
        assert "LOWER-CASE" in dialect.IBM_INTRINSIC_FUNCTIONS
        assert "SQRT" in dialect.IBM_INTRINSIC_FUNCTIONS
        assert "RANDOM" in dialect.IBM_INTRINSIC_FUNCTIONS
        
        assert len(dialect.IBM_INTRINSIC_FUNCTIONS) >= 25
    
    def test_cics_commands(self):
        """Test CICS commands are defined."""
        dialect = IBMEnterpriseCobol()
        
        # Test some key CICS commands
        assert "RECEIVE" in dialect.CICS_COMMANDS
        assert "SEND" in dialect.CICS_COMMANDS
        assert "RETURN" in dialect.CICS_COMMANDS
        assert "READ" in dialect.CICS_COMMANDS
        assert "WRITE" in dialect.CICS_COMMANDS
        assert "DELETE" in dialect.CICS_COMMANDS
        assert "LINK" in dialect.CICS_COMMANDS
        assert "XCTL" in dialect.CICS_COMMANDS
        
        assert len(dialect.CICS_COMMANDS) >= 20
    
    def test_validate_data_item_comp3_valid(self):
        """Test validation of valid COMP-3 data item."""
        dialect = IBMEnterpriseCobol()
        location = SourceLocation("test.cob", 25, 10)
        
        # Create valid COMP-3 item
        item = IBMDataItem("WS-AMOUNT", 5, location)
        item.picture_clause = PictureClause("9(7)V99", location)
        item.usage = "COMP-3"
        
        warnings = dialect.validate_data_item(item)
        assert len(warnings) == 0
    
    def test_validate_data_item_comp3_no_picture(self):
        """Test validation of COMP-3 data item without picture clause."""
        dialect = IBMEnterpriseCobol()
        location = SourceLocation("test.cob", 25, 10)
        
        # Create COMP-3 item without picture
        item = IBMDataItem("WS-AMOUNT", 5, location)
        item.usage = "COMP-3"
        
        warnings = dialect.validate_data_item(item)
        assert "COMP-3 items should have PICTURE clause" in warnings
    
    def test_validate_data_item_comp3_non_numeric_picture(self):
        """Test validation of COMP-3 data item with non-numeric picture."""
        dialect = IBMEnterpriseCobol()
        location = SourceLocation("test.cob", 25, 10)
        
        # Create COMP-3 item with alphanumeric picture
        item = IBMDataItem("WS-NAME", 5, location)
        item.picture_clause = PictureClause("X(30)", location)
        item.usage = "COMP-3"
        
        warnings = dialect.validate_data_item(item)
        assert "COMP-3 items should have numeric PICTURE" in warnings
    
    def test_validate_data_item_level_77_with_parent(self):
        """Test validation of level 77 item with parent (invalid)."""
        dialect = IBMEnterpriseCobol()
        location = SourceLocation("test.cob", 25, 10)
        
        # Create level 77 item with parent
        parent = IBMDataItem("WS-GROUP", 1, location)
        item = IBMDataItem("WS-INDEPENDENT", 77, location)
        item.parent = parent
        
        warnings = dialect.validate_data_item(item)
        assert "Level 77 items must be independent" in warnings
    
    def test_validate_data_item_level_77_without_parent(self):
        """Test validation of level 77 item without parent (valid)."""
        dialect = IBMEnterpriseCobol()
        location = SourceLocation("test.cob", 25, 10)
        
        # Create valid level 77 item
        item = IBMDataItem("WS-INDEPENDENT", 77, location)
        
        warnings = dialect.validate_data_item(item)
        # Should not contain the level 77 warning
        level_77_warnings = [w for w in warnings if "Level 77" in w]
        assert len(level_77_warnings) == 0
    
    def test_create_comp3_data_item(self):
        """Test creating COMP-3 data item."""
        dialect = IBMEnterpriseCobol()
        location = SourceLocation("test.cob", 30, 5)
        
        item = dialect.create_comp3_data_item("WS-AMOUNT", "9(7)V99", location)
        
        assert item.name == "WS-AMOUNT"
        assert item.level == 1
        assert item.location == location
        assert item.ibm_usage == IBMDataType.COMP_3
        assert item.usage == "COMP-3"
        assert item.picture_clause.pattern == "9(7)V99"
        assert item.calculate_storage_size() == 5  # (9 + 1) / 2
    
    def test_parse_exec_sql_basic(self):
        """Test parsing basic EXEC SQL statement."""
        dialect = IBMEnterpriseCobol()
        location = SourceLocation("test.cob", 35, 8)
        
        sql_text = "SELECT * FROM EMPLOYEE WHERE ID = 123"
        stmt = dialect.parse_exec_sql(sql_text, location)
        
        assert stmt.statement_type == "EXEC-SQL"
        assert stmt.location == location
        assert stmt.sql_text == sql_text
        assert stmt.sql_type == "SELECT"
        assert len(stmt.host_variables) == 0
    
    def test_parse_exec_sql_with_host_variables(self):
        """Test parsing EXEC SQL with host variables."""
        dialect = IBMEnterpriseCobol()
        location = SourceLocation("test.cob", 35, 8)
        
        sql_text = "SELECT EMP_ID, EMP_NAME INTO :WS-EMP-ID, :WS-EMP-NAME FROM EMPLOYEE WHERE DEPT = :WS-DEPT"
        stmt = dialect.parse_exec_sql(sql_text, location)
        
        assert stmt.sql_type == "SELECT"
        assert "WS-EMP-ID" in stmt.host_variables
        assert "WS-EMP-NAME" in stmt.host_variables
        assert "WS-DEPT" in stmt.host_variables
        assert len(stmt.host_variables) == 3
    
    def test_parse_exec_sql_host_variables_with_hyphens(self):
        """Test parsing host variables with hyphens."""
        dialect = IBMEnterpriseCobol()
        location = SourceLocation("test.cob", 35, 8)
        
        sql_text = "INSERT INTO EMPLOYEE VALUES (:WS-EMPLOYEE-ID, :WS-LAST-NAME)"
        stmt = dialect.parse_exec_sql(sql_text, location)
        
        assert "WS-EMPLOYEE-ID" in stmt.host_variables
        assert "WS-LAST-NAME" in stmt.host_variables
        assert len(stmt.host_variables) == 2
    
    def test_parse_exec_cics_basic(self):
        """Test parsing basic EXEC CICS statement."""
        dialect = IBMEnterpriseCobol()
        location = SourceLocation("test.cob", 40, 8)
        
        cics_text = "RECEIVE INTO(WS-COMMAREA) LENGTH(100)"
        stmt = dialect.parse_exec_cics(cics_text, location)
        
        assert stmt.statement_type == "EXEC-CICS"
        assert stmt.location == location
        assert stmt.cics_command == "RECEIVE"
        assert stmt.cics_options["INTO"] == "WS-COMMAREA"
        assert stmt.cics_options["LENGTH"] == "100"
    
    def test_parse_exec_cics_no_options(self):
        """Test parsing EXEC CICS with command only."""
        dialect = IBMEnterpriseCobol()
        location = SourceLocation("test.cob", 40, 8)
        
        cics_text = "RETURN"
        stmt = dialect.parse_exec_cics(cics_text, location)
        
        assert stmt.cics_command == "RETURN"
        assert len(stmt.cics_options) == 0
    
    def test_parse_exec_cics_options_without_values(self):
        """Test parsing EXEC CICS with options without values."""
        dialect = IBMEnterpriseCobol()
        location = SourceLocation("test.cob", 40, 8)
        
        cics_text = "READ DATASET NOHANDLE"
        stmt = dialect.parse_exec_cics(cics_text, location)
        
        assert stmt.cics_command == "READ"
        assert stmt.cics_options["DATASET"] == ""
        assert stmt.cics_options["NOHANDLE"] == ""
    
    def test_parse_exec_cics_empty_text(self):
        """Test parsing empty EXEC CICS text."""
        dialect = IBMEnterpriseCobol()
        location = SourceLocation("test.cob", 40, 8)
        
        cics_text = ""
        stmt = dialect.parse_exec_cics(cics_text, location)
        
        assert stmt.cics_command == ""
        assert len(stmt.cics_options) == 0
    
    def test_validate_program_structure_complete(self):
        """Test program structure validation with complete program."""
        dialect = IBMEnterpriseCobol()
        
        # Mock program object
        class MockProgram:
            def __init__(self):
                self.divisions = {"IDENTIFICATION": True, "DATA": True, "PROCEDURE": True}
                self.data_division = MockDataDivision()
            
            def has_division(self, name):
                return name in self.divisions
            
            def get_division_by_name(self, name):
                if name == "DATA":
                    return self.data_division
                return None
        
        class MockDataDivision:
            def __init__(self):
                self.sections = {"WORKING-STORAGE": True}
            
            def has_section(self, name):
                return name in self.sections
        
        program = MockProgram()
        warnings = dialect.validate_program_structure(program)
        
        # Should have no warnings for complete program
        assert len(warnings) == 0
    
    def test_validate_program_structure_missing_divisions(self):
        """Test program structure validation with missing divisions."""
        dialect = IBMEnterpriseCobol()
        
        # Mock program with missing divisions
        class MockProgram:
            def __init__(self):
                self.divisions = {"IDENTIFICATION": True}  # Missing DATA and PROCEDURE
            
            def has_division(self, name):
                return name in self.divisions
            
            def get_division_by_name(self, name):
                return None
        
        program = MockProgram()
        warnings = dialect.validate_program_structure(program)
        
        assert "Missing required DATA DIVISION" in warnings
        assert "Missing required PROCEDURE DIVISION" in warnings
        assert len(warnings) == 2
    
    def test_validate_program_structure_missing_working_storage(self):
        """Test program structure validation with missing WORKING-STORAGE section."""
        dialect = IBMEnterpriseCobol()
        
        # Mock program with DATA division but no WORKING-STORAGE
        class MockProgram:
            def __init__(self):
                self.divisions = {"IDENTIFICATION": True, "DATA": True, "PROCEDURE": True}
                self.data_division = MockDataDivision()
            
            def has_division(self, name):
                return name in self.divisions
            
            def get_division_by_name(self, name):
                if name == "DATA":
                    return self.data_division
                return None
        
        class MockDataDivision:
            def __init__(self):
                self.sections = {}  # No WORKING-STORAGE
            
            def has_section(self, name):
                return name in self.sections
        
        program = MockProgram()
        warnings = dialect.validate_program_structure(program)
        
        assert "Consider adding WORKING-STORAGE SECTION for local variables" in warnings
    
    def test_get_intrinsic_function_signature_existing(self):
        """Test getting signature for existing intrinsic functions."""
        dialect = IBMEnterpriseCobol()
        
        # Test CURRENT-DATE function
        sig = dialect.get_intrinsic_function_signature("CURRENT-DATE")
        assert sig is not None
        assert sig["return_type"] == "alphanumeric"
        assert sig["length"] == 21
        assert sig["parameters"] == []
        assert "Returns current date and time" in sig["description"]
        
        # Test LENGTH function
        sig = dialect.get_intrinsic_function_signature("LENGTH")
        assert sig is not None
        assert sig["return_type"] == "numeric"
        assert sig["parameters"] == ["string"]
        
        # Test case insensitive
        sig = dialect.get_intrinsic_function_signature("current-date")
        assert sig is not None
        assert sig["return_type"] == "alphanumeric"
    
    def test_get_intrinsic_function_signature_all_defined(self):
        """Test getting signatures for all defined functions."""
        dialect = IBMEnterpriseCobol()
        
        defined_functions = ["CURRENT-DATE", "LENGTH", "NUMVAL", "UPPER-CASE", "LOWER-CASE"]
        
        for func_name in defined_functions:
            sig = dialect.get_intrinsic_function_signature(func_name)
            assert sig is not None
            assert "return_type" in sig
            assert "parameters" in sig
            assert "description" in sig
    
    def test_get_intrinsic_function_signature_nonexistent(self):
        """Test getting signature for non-existent function."""
        dialect = IBMEnterpriseCobol()
        
        sig = dialect.get_intrinsic_function_signature("NONEXISTENT-FUNCTION")
        assert sig is None
    
    def test_is_reserved_word_true_cases(self):
        """Test is_reserved_word for true cases."""
        dialect = IBMEnterpriseCobol()
        
        reserved_words = ["COMP-3", "EXEC", "SQL", "CICS", "END-EXEC", "SQLCA"]
        
        for word in reserved_words:
            assert dialect.is_reserved_word(word) is True
            assert dialect.is_reserved_word(word.lower()) is True  # Case insensitive
    
    def test_is_reserved_word_false_cases(self):
        """Test is_reserved_word for false cases."""
        dialect = IBMEnterpriseCobol()
        
        non_reserved_words = ["HELLO", "WORLD", "CUSTOM-VARIABLE", "USER-DEFINED"]
        
        for word in non_reserved_words:
            assert dialect.is_reserved_word(word) is False
    
    def test_is_intrinsic_function_true_cases(self):
        """Test is_intrinsic_function for true cases."""
        dialect = IBMEnterpriseCobol()
        
        functions = ["CURRENT-DATE", "LENGTH", "NUMVAL", "SQRT", "RANDOM"]
        
        for func in functions:
            assert dialect.is_intrinsic_function(func) is True
            assert dialect.is_intrinsic_function(func.lower()) is True  # Case insensitive
    
    def test_is_intrinsic_function_false_cases(self):
        """Test is_intrinsic_function for false cases."""
        dialect = IBMEnterpriseCobol()
        
        non_functions = ["CUSTOM-FUNCTION", "USER-FUNC", "INVALID"]
        
        for func in non_functions:
            assert dialect.is_intrinsic_function(func) is False
    
    def test_is_cics_command_true_cases(self):
        """Test is_cics_command for true cases."""
        dialect = IBMEnterpriseCobol()
        
        commands = ["RECEIVE", "SEND", "RETURN", "READ", "WRITE", "LINK"]
        
        for cmd in commands:
            assert dialect.is_cics_command(cmd) is True
            assert dialect.is_cics_command(cmd.lower()) is True  # Case insensitive
    
    def test_is_cics_command_false_cases(self):
        """Test is_cics_command for false cases."""
        dialect = IBMEnterpriseCobol()
        
        non_commands = ["CUSTOM-COMMAND", "INVALID", "NOT-A-CICS-CMD"]
        
        for cmd in non_commands:
            assert dialect.is_cics_command(cmd) is False
    
    def test_get_dialect_info(self):
        """Test getting dialect information."""
        dialect = IBMEnterpriseCobol()
        
        info = dialect.get_dialect_info()
        
        assert info["name"] == "IBM Enterprise COBOL"
        assert info["version"] == "6.4"
        assert info["platform"] == "z/OS"
        assert isinstance(info["features"], list)
        assert len(info["features"]) == len(dialect.supported_features)
        assert info["reserved_words"] == len(dialect.IBM_RESERVED_WORDS)
        assert info["intrinsic_functions"] == len(dialect.IBM_INTRINSIC_FUNCTIONS)
        assert info["cics_commands"] == len(dialect.CICS_COMMANDS)
        
        # Verify feature list contains expected features
        assert "comp_3_packed_decimal" in info["features"]
        assert "exec_sql" in info["features"]
        assert "exec_cics" in info["features"]


class TestIBMEnterpriseIntegration:
    """Integration tests for IBM Enterprise components."""
    
    def test_comp3_full_workflow(self):
        """Test complete COMP-3 workflow from creation to validation."""
        dialect = IBMEnterpriseCobol()
        location = SourceLocation("test.cob", 50, 5)
        
        # Create COMP-3 item
        item = dialect.create_comp3_data_item("WS-TOTAL", "9(9)V99", location)
        
        # Validate it
        warnings = dialect.validate_data_item(item)
        assert len(warnings) == 0
        
        # Check storage calculation
        assert item.calculate_storage_size() == 6  # (11 + 1) / 2
        
        # Convert to dict
        result = item.to_dict()
        assert result["ibm_usage"] == "COMP-3"
        assert result["storage_size"] == 6
    
    def test_exec_sql_full_workflow(self):
        """Test complete EXEC SQL workflow."""
        dialect = IBMEnterpriseCobol()
        location = SourceLocation("test.cob", 60, 8)
        
        sql_text = "UPDATE EMPLOYEE SET SALARY = :WS-NEW-SALARY WHERE ID = :WS-EMP-ID"
        stmt = dialect.parse_exec_sql(sql_text, location)
        
        assert stmt.sql_type == "UPDATE"
        assert len(stmt.host_variables) == 2
        
        result = stmt.to_dict()
        assert result["statement_type"] == "EXEC-SQL"
        assert result["sql_type"] == "UPDATE"
        assert "WS-NEW-SALARY" in result["host_variables"]
        assert "WS-EMP-ID" in result["host_variables"]
    
    def test_exec_cics_full_workflow(self):
        """Test complete EXEC CICS workflow."""
        dialect = IBMEnterpriseCobol()
        location = SourceLocation("test.cob", 70, 8)
        
        cics_text = "READ DATASET(EMPFILE) INTO(WS-EMPLOYEE-REC) RIDFLD(WS-EMP-ID)"
        stmt = dialect.parse_exec_cics(cics_text, location)
        
        assert stmt.cics_command == "READ"
        assert "DATASET" in stmt.cics_options
        assert "INTO" in stmt.cics_options
        assert "RIDFLD" in stmt.cics_options
        
        result = stmt.to_dict()
        assert result["statement_type"] == "EXEC-CICS"
        assert result["cics_command"] == "READ"
    
    def test_all_usage_types_storage_calculation(self):
        """Test storage calculation for all IBM usage types."""
        dialect = IBMEnterpriseCobol()
        location = SourceLocation("test.cob", 80, 5)
        
        # Test all usage types with consistent picture
        picture = "9(5)"
        
        storage_expectations = {
            IBMDataType.COMP: 4,      # Binary: 5 digits = 4 bytes (fullword)
            IBMDataType.COMP_1: 4,    # Single precision float
            IBMDataType.COMP_2: 8,    # Double precision float
            IBMDataType.COMP_3: 3,    # Packed: (5+1)/2 = 3
            IBMDataType.COMP_4: 4,    # Binary: same as COMP
            IBMDataType.COMP_5: 4,    # Native binary: same as COMP
            IBMDataType.POINTER: 4,   # 32-bit pointer
            IBMDataType.DISPLAY: 5,   # Character: picture size
            IBMDataType.PROCEDURE_POINTER: 5,  # Uses base size
            IBMDataType.FUNCTION_POINTER: 5,   # Uses base size
            IBMDataType.OBJECT_REFERENCE: 5    # Uses base size
        }
        
        for usage_type, expected_size in storage_expectations.items():
            item = IBMDataItem(f"WS-{usage_type.name}", 5, location)
            item.picture_clause = PictureClause(picture, location)
            item.set_ibm_usage(usage_type)
            
            actual_size = item.calculate_storage_size()
            assert actual_size == expected_size, f"Failed for {usage_type.name}: expected {expected_size}, got {actual_size}"


def test_ibm_enterprise_comprehensive_coverage():
    """Test that ensures comprehensive coverage of IBM Enterprise module."""
    # This test serves as a checkpoint to ensure we've covered all major functionality
    
    # Test all enums exist
    assert IBMDataType is not None
    
    # Test all classes exist and can be instantiated
    location = SourceLocation("test.cob", 1, 1)
    
    sql_stmt = ExecSQLStatement(location)
    assert sql_stmt is not None
    
    cics_stmt = ExecCICSStatement(location)
    assert cics_stmt is not None
    
    ibm_item = IBMDataItem("TEST", 1, location)
    assert ibm_item is not None
    
    dialect = IBMEnterpriseCobol()
    assert dialect is not None
    
    # Test all major methods are callable
    assert callable(dialect.validate_data_item)
    assert callable(dialect.create_comp3_data_item)
    assert callable(dialect.parse_exec_sql)
    assert callable(dialect.parse_exec_cics)
    assert callable(dialect.validate_program_structure)
    assert callable(dialect.get_intrinsic_function_signature)
    assert callable(dialect.is_reserved_word)
    assert callable(dialect.is_intrinsic_function)
    assert callable(dialect.is_cics_command)
    assert callable(dialect.get_dialect_info)
    
    print("✅ IBM Enterprise COBOL comprehensive coverage test passed")