"""IBM Enterprise COBOL dialect implementation.

This module provides support for IBM Enterprise COBOL (z/OS) specific features
including COMP-3 data types, EXEC SQL statements, EXEC CICS commands, and
IBM-specific language extensions.
"""

from enum import Enum
from typing import Any

from ..models.ast_base import SourceLocation
from ..models.data_items import CobolDataItem, PictureClause
from ..models.statements import CobolStatement
from ..plugins.core import DialectType
from .le_signatures import LE_SERVICE_SIGNATURES


class IBMDataType(Enum):
    """IBM Enterprise COBOL specific data types."""

    COMP = "COMP"
    COMP_1 = "COMP-1"  # Single precision floating point
    COMP_2 = "COMP-2"  # Double precision floating point
    COMP_3 = "COMP-3"  # Packed decimal
    COMP_4 = "COMP-4"  # Binary
    COMP_5 = "COMP-5"  # Native binary
    DISPLAY = "DISPLAY"
    POINTER = "POINTER"
    PROCEDURE_POINTER = "PROCEDURE-POINTER"
    FUNCTION_POINTER = "FUNCTION-POINTER"
    OBJECT_REFERENCE = "OBJECT REFERENCE"


class ExecSQLStatement(CobolStatement):
    """AST node for EXEC SQL statements."""

    def __init__(self, location: SourceLocation):
        super().__init__("EXEC-SQL", location)
        self.sql_text: str = ""
        self._sql_type: str = "UNKNOWN"  # SELECT, INSERT, UPDATE, DELETE, etc.
        self.host_variables: list[str] = []

    @property
    def sql_type(self) -> str:
        """Return SQL type (SELECT, INSERT, UPDATE, DELETE, etc.)."""
        return self._sql_type

    def set_sql_text(self, sql_text: str) -> None:
        """Set the SQL statement text."""
        self.sql_text = sql_text.strip()

        # Determine SQL type
        first_word = sql_text.strip().split()[0].upper() if sql_text.strip() else ""
        if first_word in [
            "SELECT",
            "INSERT",
            "UPDATE",
            "DELETE",
            "CREATE",
            "DROP",
            "ALTER",
        ]:
            self._sql_type = first_word
        else:
            self._sql_type = "UNKNOWN"

    def add_host_variable(self, variable: str) -> None:
        """Add a host variable used in the SQL statement."""
        if variable not in self.host_variables:
            self.host_variables.append(variable)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary representation."""
        result = super().to_dict()
        result.update(
            {
                "sql_text": self.sql_text,
                "sql_type": self.sql_type,
                "host_variables": self.host_variables,
            }
        )
        return result


class ExecCICSStatement(CobolStatement):
    """AST node for EXEC CICS statements."""

    def __init__(self, location: SourceLocation):
        super().__init__("EXEC-CICS", location)
        self._cics_command: str = ""
        self.cics_options: dict[str, str] = {}

    @property
    def cics_command(self) -> str:
        """Return the CICS command."""
        return self._cics_command

    def set_command(self, command: str) -> None:
        """Set the CICS command."""
        self._cics_command = command.upper()

    def add_option(self, option: str, value: str = "") -> None:
        """Add a CICS command option."""
        self.cics_options[option.upper()] = value

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary representation."""
        result = super().to_dict()
        result.update(
            {"cics_command": self.cics_command, "cics_options": self.cics_options}
        )
        return result


class ExecIMSStatement(CobolStatement):
    """AST node for EXEC IMS statements."""

    def __init__(self, location: SourceLocation):
        super().__init__("EXEC-IMS", location)
        self._ims_command: str = ""
        self.ims_options: dict[str, str] = {}
        self.ims_call_type: str = "UNKNOWN"  # GU, GN, GNP, ISRT, REPL, DLET, etc.

    @property
    def ims_command(self) -> str:
        """Return the IMS command."""
        return self._ims_command

    def set_command(self, command: str) -> None:
        """Set the IMS command."""
        self._ims_command = command.upper()
        # Determine IMS call type. Recognizes every DL/I call type
        # IBMEnterpriseCobol.IMS_COMMANDS does (GU/GN/GNP/ISRT/REPL/DLET plus
        # CHKP/ROLLB/TERM/ENQUEUE/DEQUEUE/PURG/XRST/XDLT/XRPL) -- restricting
        # this to the first six left `ims_call_type` at "UNKNOWN" for a
        # recognized command.
        if self._ims_command in IBMEnterpriseCobol.IMS_COMMANDS:
            self.ims_call_type = self._ims_command

    def add_option(self, option: str, value: str = "") -> None:
        """Add an IMS command option."""
        self.ims_options[option.upper()] = value

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary representation."""
        result = super().to_dict()
        result.update(
            {
                "ims_command": self.ims_command,
                "ims_call_type": self.ims_call_type,
                "ims_options": self.ims_options,
            }
        )
        return result


class IBMDataItem(CobolDataItem):
    """Extended data item with IBM Enterprise COBOL features."""

    def __init__(self, name: str, level: int, location: SourceLocation):
        super().__init__(name, level, location)
        self.ibm_usage: IBMDataType | None = None
        self.sign_clause: str | None = None  # LEADING, TRAILING, SEPARATE
        self.synchronized: bool = False
        self.justified: bool = False
        self.blank_when_zero: bool = False

    def set_ibm_usage(self, usage: IBMDataType) -> None:
        """Set IBM-specific USAGE clause."""
        self.ibm_usage = usage
        self.usage = usage.value

    def calculate_storage_size(self) -> int:
        """Calculate storage size in bytes using IBM rules."""
        if not self.picture_clause:
            return 0

        base_size = self.picture_clause.size or 0

        # POINTER doesn't depend on picture digits
        if self.ibm_usage == IBMDataType.POINTER:
            return 4  # 32-bit pointer on z/OS

        # For other types, we need total_digits
        if self.picture_clause.total_digits is None:
            return base_size  # DISPLAY and other character types

        if self.ibm_usage == IBMDataType.COMP_3:
            # COMP-3: Packed decimal - (digits + 1) / 2
            return (self.picture_clause.total_digits + 1) // 2
        elif self.ibm_usage == IBMDataType.COMP or self.ibm_usage == IBMDataType.COMP_4:
            # COMP/COMP-4: Binary
            if self.picture_clause.total_digits <= 4:
                return 2  # Halfword
            elif self.picture_clause.total_digits <= 9:
                return 4  # Fullword
            else:
                return 8  # Doubleword
        elif self.ibm_usage == IBMDataType.COMP_1:
            return 4  # Single precision float
        elif self.ibm_usage == IBMDataType.COMP_2:
            return 8  # Double precision float
        elif self.ibm_usage == IBMDataType.COMP_5:
            # Native binary - same as COMP but with different range
            if self.picture_clause.total_digits <= 4:
                return 2  # Halfword
            elif self.picture_clause.total_digits <= 9:
                return 4  # Fullword
            else:
                return 8  # Doubleword
        else:
            # DISPLAY and other character types
            return base_size

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary with IBM extensions."""
        result = super().to_dict()
        result.update(
            {
                "ibm_usage": self.ibm_usage.value if self.ibm_usage else None,
                "sign_clause": self.sign_clause,
                "synchronized": self.synchronized,
                "justified": self.justified,
                "blank_when_zero": self.blank_when_zero,
                "storage_size": self.calculate_storage_size(),
            }
        )
        return result


class IBMEnterpriseCobol:
    """IBM Enterprise COBOL dialect support.

    This class provides parsing extensions and validation for IBM Enterprise COBOL
    features including:
    - COMP-3 packed decimal data types
    - EXEC SQL embedded SQL statements
    - EXEC CICS transaction processing commands
    - IBM-specific intrinsic functions
    - z/OS dataset and file handling extensions
    """

    # IBM Enterprise COBOL reserved words
    IBM_RESERVED_WORDS = {
        "COMP-3",
        "COMP-4",
        "COMP-5",
        "PACKED-DECIMAL",
        "BINARY",
        "POINTER",
        "PROCEDURE-POINTER",
        "FUNCTION-POINTER",
        "OBJECT",
        "REFERENCE",
        "EXEC",
        "SQL",
        "CICS",
        "END-EXEC",
        "SQLCA",
        "SQLDA",
        "DFHCOMMAREA",
        "DFHEIBLK",
        "CBL",
        "PROCESS",
    }

    # IBM intrinsic functions
    IBM_INTRINSIC_FUNCTIONS = {
        "ACOS",
        "ANNUITY",
        "ASIN",
        "ATAN",
        "CHAR",
        "COS",
        "CURRENT-DATE",
        "DATE-OF-INTEGER",
        "DATE-TO-YYYYMMDD",
        "DAY-OF-INTEGER",
        "DAY-TO-YYYYDDD",
        "FACTORIAL",
        "INTEGER",
        "INTEGER-OF-DATE",
        "INTEGER-OF-DAY",
        "LENGTH",
        "LOG",
        "LOG10",
        "LOWER-CASE",
        "MAX",
        "MEAN",
        "MEDIAN",
        "MIDRANGE",
        "MIN",
        "MOD",
        "NUMVAL",
        "NUMVAL-C",
        "ORD",
        "ORD-MAX",
        "ORD-MIN",
        "PRESENT-VALUE",
        "RANDOM",
        "RANGE",
        "REM",
        "REVERSE",
        "SIN",
        "SQRT",
        "STANDARD-DEVIATION",
        "SUM",
        "TAN",
        "UPPER-CASE",
        "VARIANCE",
        "WHEN-COMPILED",
        "YEAR-TO-YYYY",
    }

    # CICS commands
    CICS_COMMANDS = {
        "RECEIVE",
        "SEND",
        "RETURN",
        "XCTL",
        "LINK",
        "LOAD",
        "RELEASE",
        "GETMAIN",
        "FREEMAIN",
        "READ",
        "WRITE",
        "REWRITE",
        "DELETE",
        "UNLOCK",
        "STARTBR",
        "READNEXT",
        "READPREV",
        "RESETBR",
        "ENDBR",
        "PUSH",
        "POP",
        "PUT",
        "GET",
        "PURGE",
        "RETRIEVE",
        "START",
        "CANCEL",
        "SUSPEND",
        "RESUME",
        "DELAY",
        "ASKTIME",
        "FORMATTIME",
        "CONVERTTIME",
        "ENTER",
        "HANDLE",
        "IGNORE",
        "NOHANDLE",
    }

    # IBM Language Environment (LE) callable services (CEE* functions)
    IBM_LE_CALLABLE_SERVICES = {
        # Date and Time services
        "CEEDATM",  # Convert Lilian seconds to character timestamp
        "CEEDATE",  # Convert Lilian date to character date
        "CEEDAYS",  # Convert character date to Lilian date
        "CEECBLDY",  # Convert character date to COBOL integer date
        "CEEUTC",  # Get current Coordinated Universal Time (CEEGMT alias)
        "CEEISEC",  # Convert integer date/time components to Lilian seconds
        "CEESECI",  # Convert Lilian seconds to integer date/time components
        "CEEQCEN",  # Query the century window
        "CEESCEN",  # Set the century window
        "CEEFMDA",  # Get the default date picture string
        "CEEFMDT",  # Get the default date and time picture string
        "CEEFMTM",  # Get the default time picture string
        "CEETIME",  # Get current time
        "CEEGMT",  # Get current Greenwich Mean Time
        "CEELOCT",  # Get current local time
        "CEESECS",  # Convert date/time to Lilian seconds
        "CEEFMTDT",  # Format date/time
        "CEEDTTM",  # Convert character date/time to Lilian seconds
        "CEEDYWK",  # Calculate day of week from Lilian date
        "CEEGMTO",  # Get Greenwich Mean Time offset
        "CEEGMTCO",  # Get GMT offset for a date
        "CEEFMTVF",  # Format date/time using variable-length format
        # Heap Storage services
        "CEEGTST",  # Get heap storage
        "CEEFRST",  # Free heap storage
        "CEEFRMST",  # Free heap storage
        "CEECREH",  # Create heap
        "CEEDSHP",  # Destroy heap
        "CEECRHP",  # Create heap (alternate)
        # Mathematical services
        "CEEZLNG",  # Get string length
        # Condition and Error Handling services
        "CEEHDLR",  # Register a condition handler
        "CEEHDLU",  # Unregister a condition handler
        "CEEMOUT",  # Dispatch a message string
        "CEE3DMP",  # Generate a Language Environment dump
        "CEE3ABD",  # Terminate the enclave with an abend
        "CEETREC",  # Remove a condition handler
        "CEEHOOK",  # Set hook
        "CEEMRCR",  # Move condition record
        "CEENDUC",  # Non-destructive update of condition
        "CEERADR",  # Re-raise a condition
        "CEESGL",  # Signal a condition
        "CEEDUMP",  # Produce a system dump
        "CEEABND",  # Abend with condition
        # Environment services
        "CEENVST",  # Get next environment setting
        "CEEENV",  # Get environment variable
        "CEEGPID",  # Get program instance data
        "CEEGPIL",  # Get program instance level
        "CEEGMEM",  # Get member name
        "CEEGLS",  # Get language sensitive string length
        # Runtime services
        "CEE3PRM",  # Query the runtime parameter string
        "CEE3GRC",  # Get the enclave return code
        "CEE3SRC",  # Set the enclave return code
        "CEETERM",  # Terminate the run unit
        "CEEBINIT",  # Initialize Language Environment
        "CEEPCMD",  # Perform command
        "CEEMSG",  # Get message text
        "CEEGLOB",  # Get global data
        "CEEGSS",  # Get stack storage
        "CEESST",  # Get static storage
        # String conversion services
        "CEESG",  # Convert string
        "CEESQ",  # Convert string length
        "CEECZST",  # Convert string with terminator
        # IMS LE interface (also a LE service)
        "CEETDLI",  # IMS DL/I call through Language Environment
    }

    # Metadata for the most commonly used LE callable services.
    #
    # Derived from `le_signatures.LE_SERVICE_SIGNATURES` for every service
    # that module can describe exactly, so the two cannot drift; the entries
    # below are the leftovers, for services this dialect recognises but has
    # no catalogued call signature for. `parameters` here is a bare list of
    # operand names -- a consumer that needs the direction, the picture and
    # whether an operand may be omitted should read the signature catalogue
    # instead (or `cobol-parser le-info`).
    _UNCATALOGUED_LE_SERVICE_INFO: dict[str, dict] = {
        "CEEFMTDT": {
            "category": "datetime",
            "description": "Format date/time",
            "parameters": ["seconds", "picture-string", "output-string", "fc"],
        },
        "CEEFRMST": {
            "category": "storage",
            "description": "Free heap storage",
            "parameters": ["pointer", "fc"],
        },
        "CEETREC": {
            "category": "condition",
            "description": "Remove a condition handler",
            "parameters": ["token", "fc"],
        },
        "CEETERM": {
            "category": "runtime",
            "description": "Terminate the run unit",
            "parameters": ["termination-code"],
        },
    }

    IBM_LE_SERVICE_INFO: dict[str, dict] = {
        **_UNCATALOGUED_LE_SERVICE_INFO,
        **{
            name: {
                "category": sig.category,
                "description": sig.summary,
                "parameters": [p.name for p in sig.parameters],
            }
            for name, sig in LE_SERVICE_SIGNATURES.items()
        },
    }

    # Category lookup for every IBM LE callable service.
    # This is the single source of truth used by LanguageEnvironmentAnalyzer.
    IBM_LE_SERVICE_CATEGORIES: dict[str, str] = {
        "CEEDATM": "datetime",
        "CEEDAYS": "datetime",
        "CEECBLDY": "datetime",
        "CEEUTC": "datetime",
        "CEEISEC": "datetime",
        "CEESECI": "datetime",
        "CEEQCEN": "datetime",
        "CEESCEN": "datetime",
        "CEEFMDA": "datetime",
        "CEEFMDT": "datetime",
        "CEEFMTM": "datetime",
        "CEEDATE": "datetime",
        "CEETIME": "datetime",
        "CEEGMT": "datetime",
        "CEELOCT": "datetime",
        "CEESECS": "datetime",
        "CEEFMTDT": "datetime",
        "CEEDTTM": "datetime",
        "CEEDYWK": "datetime",
        "CEEGMTO": "datetime",
        "CEEGMTCO": "datetime",
        "CEEFMTVF": "datetime",
        "CEEGTST": "storage",
        "CEEFRST": "storage",
        "CEECZST": "storage",
        "CEEFRMST": "storage",
        "CEECREH": "storage",
        "CEEDSHP": "storage",
        "CEECRHP": "storage",
        "CEEGSS": "storage",
        "CEESST": "storage",
        "CEEZLNG": "string",
        "CEEGLS": "string",
        "CEESG": "string",
        "CEESQ": "string",
        "CEEHDLR": "condition",
        "CEEHDLU": "condition",
        "CEE3DMP": "condition",
        "CEE3ABD": "condition",
        "CEETREC": "condition",
        "CEEHOOK": "condition",
        "CEEMRCR": "condition",
        "CEENDUC": "condition",
        "CEERADR": "condition",
        "CEESGL": "condition",
        "CEEDUMP": "condition",
        "CEEABND": "condition",
        "CEENVST": "environment",
        "CEEENV": "environment",
        "CEEGPID": "environment",
        "CEEGPIL": "environment",
        "CEEGMEM": "environment",
        "CEETERM": "runtime",
        "CEEMOUT": "runtime",
        "CEE3PRM": "runtime",
        "CEE3GRC": "runtime",
        "CEE3SRC": "runtime",
        "CEEBINIT": "runtime",
        "CEEPCMD": "runtime",
        "CEEMSG": "runtime",
        "CEEGLOB": "runtime",
        "CEETDLI": "ims",
    }

    # IMS commands (DL/I call types)
    IMS_COMMANDS = {
        "GU",
        "GN",
        "GNP",  # Get Unique, Get Next, Get Next in Parent
        "ISRT",
        "REPL",
        "DLET",  # Insert, Replace, Delete
        "CHKP",
        "ROLLB",
        "TERM",  # Checkpoint, Rollback, Terminate
        "ENQUEUE",
        "DEQUEUE",
        "PURG",  # Queue operations
        "XRST",
        "XDLT",
        "XRPL",  # Extended operations
    }

    def __init__(self) -> None:
        """Initialize IBM Enterprise COBOL dialect."""
        self.dialect_type = DialectType.IBM_ENTERPRISE
        self.supported_features = {
            "comp_3_packed_decimal",
            "exec_sql",
            "exec_cics",
            "exec_ims",
            "ibm_intrinsic_functions",
            "le_callable_services",
            "pointer_data_types",
            "object_oriented_cobol",
            "zos_file_handling",
        }

    def validate_data_item(self, data_item: CobolDataItem) -> list[str]:
        """Validate data item against IBM Enterprise COBOL rules."""
        warnings = []

        # Check COMP-3 usage
        if data_item.usage == "COMP-3":
            if not data_item.picture_clause:
                warnings.append("COMP-3 items should have PICTURE clause")
            elif not data_item.picture_clause.pattern.startswith("9"):
                warnings.append("COMP-3 items should have numeric PICTURE")

        # Check level number restrictions
        if data_item.level == 77 and data_item.parent:
            warnings.append("Level 77 items must be independent")

        return warnings

    def create_comp3_data_item(
        self, name: str, picture: str, location: SourceLocation
    ) -> IBMDataItem:
        """Create a COMP-3 packed decimal data item."""
        item = IBMDataItem(name, 1, location)
        item.picture_clause = PictureClause(picture, location)
        item.set_ibm_usage(IBMDataType.COMP_3)
        return item

    def parse_exec_sql(
        self, sql_text: str, location: SourceLocation
    ) -> ExecSQLStatement:
        """Parse EXEC SQL statement."""
        stmt = ExecSQLStatement(location)
        stmt.set_sql_text(sql_text)

        # Extract host variables (simplified - look for :variable pattern)
        import re

        host_vars = re.findall(r":([A-Za-z][A-Za-z0-9-]*)", sql_text)
        for var in host_vars:
            stmt.add_host_variable(var)

        return stmt

    def parse_exec_cics(
        self, cics_text: str, location: SourceLocation
    ) -> ExecCICSStatement:
        """Parse EXEC CICS statement."""
        stmt = ExecCICSStatement(location)

        # Simple parsing - extract command and options
        parts = cics_text.strip().split()
        if parts:
            stmt.set_command(parts[0])

            # Parse options (simplified)
            for part in parts[1:]:
                if "(" in part:
                    option, value = part.split("(", 1)
                    value = value.rstrip(")")
                    stmt.add_option(option, value)
                else:
                    stmt.add_option(part)

        return stmt

    def parse_exec_ims(
        self, ims_text: str, location: SourceLocation
    ) -> ExecIMSStatement:
        """Parse EXEC IMS statement."""
        stmt = ExecIMSStatement(location)

        # Simple parsing - extract command and options
        parts = ims_text.strip().split()
        if parts:
            stmt.set_command(parts[0])

            # Parse options (simplified)
            for part in parts[1:]:
                if "(" in part:
                    option, value = part.split("(", 1)
                    value = value.rstrip(")")
                    stmt.add_option(option, value)
                else:
                    stmt.add_option(part)

        return stmt

    def validate_program_structure(self, program: Any) -> list[str]:
        """Validate program structure for IBM Enterprise COBOL."""
        warnings = []

        # Check for required divisions
        required_divisions = ["IDENTIFICATION", "DATA", "PROCEDURE"]
        for div_name in required_divisions:
            if not program.has_division(div_name):
                warnings.append(f"Missing required {div_name} DIVISION")

        # Check for IBM-specific sections
        data_division = program.get_division("DATA")
        if data_division:
            if not data_division.has_section("WORKING-STORAGE"):
                warnings.append(
                    "Consider adding WORKING-STORAGE SECTION for local variables"
                )

        return warnings

    def get_intrinsic_function_signature(
        self, function_name: str
    ) -> dict[str, Any] | None:
        """Get signature information for IBM intrinsic functions."""
        function_signatures: dict[str, dict[str, Any]] = {
            "CURRENT-DATE": {
                "return_type": "alphanumeric",
                "length": 21,
                "parameters": [],
                "description": "Returns current date and time",
            },
            "LENGTH": {
                "return_type": "numeric",
                "parameters": ["string"],
                "description": "Returns length of string argument",
            },
            "NUMVAL": {
                "return_type": "numeric",
                "parameters": ["alphanumeric"],
                "description": "Convert alphanumeric to numeric",
            },
            "UPPER-CASE": {
                "return_type": "alphanumeric",
                "parameters": ["alphanumeric"],
                "description": "Convert to uppercase",
            },
            "LOWER-CASE": {
                "return_type": "alphanumeric",
                "parameters": ["alphanumeric"],
                "description": "Convert to lowercase",
            },
        }

        return function_signatures.get(function_name.upper())

    def is_reserved_word(self, word: str) -> bool:
        """Check if word is reserved in IBM Enterprise COBOL."""
        return word.upper() in self.IBM_RESERVED_WORDS

    def is_intrinsic_function(self, function_name: str) -> bool:
        """Check if function is an IBM intrinsic function."""
        return function_name.upper() in self.IBM_INTRINSIC_FUNCTIONS

    def is_cics_command(self, command: str) -> bool:
        """Check if command is a valid CICS command."""
        return command.upper() in self.CICS_COMMANDS

    def is_ims_command(self, command: str) -> bool:
        """Check if command is a valid IMS command."""
        return command.upper() in self.IMS_COMMANDS

    def is_le_callable_service(self, name: str) -> bool:
        """Check if name is an IBM Language Environment callable service."""
        return name.upper() in self.IBM_LE_CALLABLE_SERVICES

    def get_le_service_info(self, name: str) -> dict | None:
        """Get metadata for an IBM LE callable service.

        Returns a dict with keys 'category', 'description', 'parameters',
        or None if the service is not known or has no metadata.
        """
        return self.IBM_LE_SERVICE_INFO.get(name.upper())

    def get_dialect_info(self) -> dict[str, Any]:
        """Get dialect information."""
        return {
            "name": "IBM Enterprise COBOL",
            "version": "6.4",
            "platform": "z/OS",
            "features": list(self.supported_features),
            "reserved_words": len(self.IBM_RESERVED_WORDS),
            "intrinsic_functions": len(self.IBM_INTRINSIC_FUNCTIONS),
            "cics_commands": len(self.CICS_COMMANDS),
            "ims_commands": len(self.IMS_COMMANDS),
            "le_callable_services": len(self.IBM_LE_CALLABLE_SERVICES),
        }
