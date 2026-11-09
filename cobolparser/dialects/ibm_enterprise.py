"""IBM Enterprise COBOL dialect tables.

Class-level lookup tables the parser and analyzers read: intrinsic
functions, Language Environment callable services and their categories,
and the IMS / EXEC DLI function codes.
"""


class IBMEnterpriseCobol:
    """IBM Enterprise COBOL lookup tables (used as class attributes)."""

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
        # Enterprise COBOL 3.x-6.4 additions beyond the COBOL-85 set.
        "ABS",
        "BIT-OF",
        "BIT-TO-CHAR",
        "BYTE-LENGTH",
        "COMBINED-DATETIME",
        "DISPLAY-OF",
        "E",
        "EXP",
        "EXP10",
        "FORMATTED-CURRENT-DATE",
        "FORMATTED-DATE",
        "FORMATTED-DATETIME",
        "FORMATTED-TIME",
        "HEX-OF",
        "HEX-TO-CHAR",
        "INTEGER-OF-FORMATTED-DATE",
        "INTEGER-PART",
        "NATIONAL-OF",
        "NUMVAL-F",
        "PI",
        "SECONDS-FROM-FORMATTED-TIME",
        "SECONDS-PAST-MIDNIGHT",
        "SIGN",
        "TEST-DATE-YYYYMMDD",
        "TEST-DAY-YYYYDDD",
        "TEST-FORMATTED-DATETIME",
        "TEST-NUMVAL",
        "TEST-NUMVAL-C",
        "TEST-NUMVAL-F",
        "TRIM",
        "ULENGTH",
        "UPOS",
        "USUBSTR",
        "USUPPLEMENTARY",
        "UUID4",
        "UVALID",
        "UWIDTH",
    }

    # IBM Language Environment (LE) callable services, each with its category.
    #
    # Rebuilt from the z/OS Language Environment Programming Reference
    # (SA38-0683) service list (#529). The single source of truth used by
    # LanguageEnvironmentAnalyzer (``is_known_service`` and ``category``);
    # ``IBM_LE_CALLABLE_SERVICES`` below is its key set. Names that are not in
    # the reference are deliberately absent, so a typo such as ``CEEDUMP`` for
    # CEE3DMP does not read as a valid service: the earlier set carried 24 of
    # them (CEEDUMP, CEEABND, CEETIME, CEEFMTDT, CEESG, ...). The math
    # services (CEESxyyy: CEESDSIN, CEESSLOG, ...) are not listed; a CALL to
    # one is still reported, as an unknown CEE-prefixed name. Pinned against a
    # checked-in copy of this list in
    # ``tests/regression/test_le_callable_services_issue_529.py``.
    IBM_LE_SERVICE_CATEGORIES: dict[str, str] = {
        # Date and time services
        "CEECBLDY": "datetime",  # Convert date to COBOL integer format
        "CEEDATE": "datetime",  # Convert Lilian date to character format
        "CEEDATM": "datetime",  # Convert seconds to character timestamp
        "CEEDAYS": "datetime",  # Convert date to Lilian format
        "CEEDYWK": "datetime",  # Calculate day of week from Lilian date
        "CEEFMDA": "datetime",  # Get default date format
        "CEEFMDT": "datetime",  # Get default date and time format
        "CEEFMTM": "datetime",  # Get default time format
        "CEEGMT": "datetime",  # Get current Greenwich Mean Time
        "CEEGMTO": "datetime",  # Get offset from Greenwich Mean Time
        "CEEISEC": "datetime",  # Convert integers to seconds
        "CEELOCT": "datetime",  # Get current local date or time
        "CEEQCEN": "datetime",  # Query the century window
        "CEESCEN": "datetime",  # Set the century window
        "CEESECI": "datetime",  # Convert seconds to integers
        "CEESECS": "datetime",  # Convert timestamp to seconds
        "CEEUTC": "datetime",  # Get Coordinated Universal Time
        # Storage management services
        "CEECRHP": "storage",  # Create new additional heap
        "CEECZST": "storage",  # Reallocate (change size of) storage
        "CEEDSHP": "storage",  # Discard heap
        "CEEFRST": "storage",  # Free heap storage
        "CEEGTST": "storage",  # Get heap storage
        "CEE3RPH": "storage",  # Set report heading
        # Condition handling services
        "CEEHDLR": "condition",  # Register user-written condition handler
        "CEEHDLU": "condition",  # Unregister user-written condition handler
        "CEESGL": "condition",  # Signal a condition
        "CEEMRCE": "condition",  # Move resume cursor explicit
        "CEEMRCR": "condition",  # Move resume cursor relative to handle cursor
        "CEE3SRP": "condition",  # Set resume point
        "CEEITOK": "condition",  # Return initial condition token
        "CEEGQDT": "condition",  # Retrieve q_data_token
        "CEENCOD": "condition",  # Construct a condition token
        "CEEDCOD": "condition",  # Decompose a condition token
        "CEE3CIB": "condition",  # Return pointer to condition information block
        "CEE3CNC": "condition",  # Handle nested conditions
        "CEE3GRN": "condition",  # Get name of routine that incurred condition
        "CEE3GRO": "condition",  # Get offset of condition
        "CEE3SPM": "condition",  # Query and modify hardware condition enablement
        "CEE3DMP": "condition",  # Generate dump
        "CEE3ABD": "condition",  # Terminate enclave with an abend
        "CEE3AB2": "condition",  # Terminate enclave with abend and reason code
        "CEETREC": "condition",  # Set the enclave return code and terminate
        # Message handling services
        "CEEMGET": "runtime",  # Get a message
        "CEEMOUT": "runtime",  # Dispatch a message
        "CEEMSG": "runtime",  # Get, format and dispatch a message
        # Program and enclave services
        "CEE3PRM": "runtime",  # Query parameter string
        "CEE3PR2": "runtime",  # Query parameter string (long)
        "CEE3GRC": "runtime",  # Get the enclave return code
        "CEE3SRC": "runtime",  # Set the enclave return code
        "CEE3DLY": "runtime",  # Suspend enclave execution (seconds)
        "CEEDLYM": "runtime",  # Suspend enclave execution (milliseconds)
        "CEETEST": "runtime",  # Invoke the debugger
        "CEETERM": "runtime",  # Terminate the run unit
        # Environment query services
        "CEE3INF": "environment",  # Query enclave information
        "CEE3USR": "environment",  # Set or query user area fields
        "CEEENV": "environment",  # Process environment variables
        "CEEGPID": "environment",  # Retrieve LE version and platform ID
        "CEEGTJS": "environment",  # Retrieve value of an exported JCL symbol
        # National language and locale services
        "CEE3CTY": "locale",  # Set default country
        "CEE3LNG": "locale",  # Set national language
        "CEE3MCS": "locale",  # Get default currency symbol
        "CEE3MDS": "locale",  # Get default decimal separator
        "CEE3MTS": "locale",  # Get default thousands separator
        "CEEFMON": "locale",  # Format monetary string
        "CEEFTDS": "locale",  # Format time and date into character string
        "CEELCNV": "locale",  # Query locale numeric conventions
        "CEEQDTC": "locale",  # Query locale date and time conventions
        "CEEQRYL": "locale",  # Query active locale environment
        "CEESCOL": "locale",  # Compare collation weight of two strings
        "CEESETL": "locale",  # Set locale operating environment
        "CEESTXF": "locale",  # Transform string into collation weights
        # Math and bit manipulation services
        "CEERAN0": "math",  # Calculate uniform random numbers
        "CEESICLR": "math",  # Bit clear
        "CEESISET": "math",  # Bit set
        "CEESISHF": "math",  # Bit shift
        "CEESITST": "math",  # Bit test
        # IMS interface
        "CEETDLI": "ims",  # Invoke IMS
    }

    IBM_LE_CALLABLE_SERVICES: set[str] = set(IBM_LE_SERVICE_CATEGORIES)

    # DL/I call function codes: the first operand of ``CALL 'CBLTDLI'`` /
    # ``'AIBTDLI'`` / ``'CEETDLI'`` (IMS Application Programming APIs, "DL/I
    # calls"). The one list of them: IMSSegmentAnalyzer reads it from here
    # (#595). ``ROLLB``, ``XDLT`` and ``XRPL`` are not DL/I calls (the
    # rollback calls are ROLB, ROLL and ROLS; #481).
    IMS_COMMANDS: frozenset[str] = frozenset(
        {
            # Database calls (plain and hold forms)
            "GU",
            "GN",
            "GNP",
            "GHU",
            "GHN",
            "GHNP",
            "ISRT",
            "REPL",
            "DLET",
            "FLD",
            "POS",
            # Message (TM) calls
            "AUTH",
            "CHNG",
            "CMD",
            "GCMD",
            "PURG",
            "SETO",
            # System service calls: checkpoint, restart and recovery
            "CHKP",
            "XRST",
            "SYNC",
            "ROLB",
            "ROLL",
            "ROLS",
            "SETS",
            "SETU",
            # System service calls: PSB scheduling, environment, logging
            "APSB",
            "DPSB",
            "PCB",
            "TERM",
            "CIMS",
            "DEQ",
            "GMSG",
            "GSCD",
            "ICAL",
            "ICMD",
            "RCMD",
            "INIT",
            "INQY",
            "LOG",
            "SNAP",
            "STAT",
        }
    )

    # EXEC DLI command words (the command-level interface), which the parser's
    # ``ExecImsStatement.ims_call_type`` reads (#481). A different vocabulary
    # from the CALL function codes above: no hold forms (a hold is implicit
    # in EXEC DLI) and no message calls, but its own LOAD / SCHD / SYMCHKP /
    # QUERY / REFRESH / RETRIEVE / ACCEPT. Only the abbreviated command word
    # is listed; the spelled-out forms (``GET UNIQUE``, ``SCHEDULE``, ...)
    # are not.
    EXEC_DLI_COMMANDS: frozenset[str] = frozenset(
        {
            # Database commands
            "GU",
            "GN",
            "GNP",
            "ISRT",
            "REPL",
            "DLET",
            "LOAD",
            "POS",
            "RETRIEVE",
            # PSB scheduling
            "SCHD",
            "TERM",
            # Checkpoint, restart and recovery
            "CHKP",
            "SYMCHKP",
            "XRST",
            "ROLB",
            "ROLL",
            "ROLS",
            "SETS",
            "SETU",
            # Other system services
            "ACCEPT",
            "DEQ",
            "LOG",
            "QUERY",
            "REFRESH",
            "STAT",
        }
    )
