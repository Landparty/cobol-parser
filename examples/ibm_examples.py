#!/usr/bin/env python3
"""
IBM Enterprise COBOL Examples

This file demonstrates IBM-specific COBOL features including COMP-3,
EXEC SQL, EXEC CICS, and other enterprise extensions.
"""

from cobolparser import CobolParser, parse_cobol
from cobolparser.dialects.ibm_enterprise import IBMEnterpriseCobol, IBMDataType
from cobolparser.plugins.core import DialectType, ErrorRecoveryMode
from cobolparser.models.ast_base import SourceLocation


def example_1_comp3_data_types():
    """Demonstrate COMP-3 packed decimal data types."""
    print("=" * 60)
    print("IBM EXAMPLE 1: COMP-3 Packed Decimal")
    print("=" * 60)
    
    cobol_source = '''
       IDENTIFICATION DIVISION.
       PROGRAM-ID. COMP3-DEMO.
       
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-FINANCIAL-DATA.
           05  WS-ACCOUNT-NUM   PIC 9(8) COMP-3.
           05  WS-BALANCE       PIC 9(11)V99 COMP-3.
           05  WS-INTEREST-RATE PIC 9V9(4) COMP-3.
           05  WS-TRANSACTION   PIC S9(7)V99 COMP-3.
       
       01  WS-COUNTERS.
           05  WS-RECORD-COUNT  PIC 9(7) COMP-3 VALUE ZERO.
           05  WS-ERROR-COUNT   PIC 9(5) COMP-3 VALUE ZERO.
       
       PROCEDURE DIVISION.
       MAIN-PROCESS.
           MOVE 12345678 TO WS-ACCOUNT-NUM.
           MOVE 150000.50 TO WS-BALANCE.
           MOVE 0.0425 TO WS-INTEREST-RATE.
           
           DISPLAY "Account: " WS-ACCOUNT-NUM.
           DISPLAY "Balance: " WS-BALANCE.
           STOP RUN.
    '''
    
    # Use IBM Enterprise COBOL dialect
    parser = CobolParser(dialect=DialectType.IBM_ENTERPRISE)
    result = parser.parse(cobol_source, "comp3_demo.cob")
    
    print(f"✅ Parse Success: {result.success}")
    
    if result.ast:
        # Analyze COMP-3 fields
        ibm_dialect = IBMEnterpriseCobol()
        
        data_div = result.ast.get_division_by_name("DATA")
        if data_div:
            ws_section = data_div.get_section_by_name("WORKING-STORAGE")
            if ws_section:
                print(f"\n💰 COMP-3 Fields Analysis:")
                
                def analyze_comp3_items(items, indent=0):
                    for item in items:
                        if hasattr(item, 'usage') and 'COMP-3' in str(item.usage):
                            prefix = "  " * indent
                            picture = item.picture_clause.pattern if item.picture_clause else "N/A"
                            
                            # Create IBM data item for size calculation
                            if item.picture_clause:
                                ibm_item = ibm_dialect.create_comp3_data_item(
                                    item.name, picture, item.location
                                )
                                storage_size = ibm_item.calculate_storage_size()
                            else:
                                storage_size = 0
                            
                            print(f"{prefix}📊 {item.name}")
                            print(f"{prefix}   PIC: {picture}")
                            print(f"{prefix}   Storage: {storage_size} bytes")
                            print(f"{prefix}   Usage: COMP-3 (Packed Decimal)")
                        
                        if hasattr(item, 'children'):
                            analyze_comp3_items(item.children, indent + 1)
                
                analyze_comp3_items(ws_section.children)


def example_2_exec_sql():
    """Demonstrate EXEC SQL embedded SQL statements."""
    print("\n" + "=" * 60)
    print("IBM EXAMPLE 2: EXEC SQL Statements")
    print("=" * 60)
    
    cobol_source = '''
       IDENTIFICATION DIVISION.
       PROGRAM-ID. SQL-DEMO.
       
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  SQLCA                COPY SQLCA.
       
       01  WS-EMPLOYEE-REC.
           05  WS-EMP-ID        PIC 9(6).
           05  WS-EMP-NAME      PIC X(30).
           05  WS-EMP-SALARY    PIC 9(7)V99 COMP-3.
           05  WS-DEPT-CODE     PIC X(3).
       
       01  WS-SEARCH-ID         PIC 9(6) VALUE 123456.
       01  WS-NEW-SALARY        PIC 9(7)V99 COMP-3.
       
       PROCEDURE DIVISION.
       MAIN-PROCESS.
           EXEC SQL
               CONNECT TO :DATABASE-NAME
           END-EXEC.
           
           PERFORM GET-EMPLOYEE.
           PERFORM UPDATE-SALARY.
           
           EXEC SQL
               COMMIT WORK
           END-EXEC.
           
           STOP RUN.
           
       GET-EMPLOYEE.
           EXEC SQL
               SELECT EMP_ID, EMP_NAME, SALARY, DEPT_CODE
               INTO :WS-EMP-ID, :WS-EMP-NAME, 
                    :WS-EMP-SALARY, :WS-DEPT-CODE
               FROM EMPLOYEE
               WHERE EMP_ID = :WS-SEARCH-ID
           END-EXEC.
           
           IF SQLCODE = 0
               DISPLAY "Employee found: " WS-EMP-NAME
               DISPLAY "Current salary: " WS-EMP-SALARY
           ELSE
               DISPLAY "Employee not found or SQL error: " SQLCODE
           END-IF.
           
       UPDATE-SALARY.
           IF SQLCODE = 0
               COMPUTE WS-NEW-SALARY = WS-EMP-SALARY * 1.05
               
               EXEC SQL
                   UPDATE EMPLOYEE
                   SET SALARY = :WS-NEW-SALARY
                   WHERE EMP_ID = :WS-EMP-ID
               END-EXEC.
               
               IF SQLCODE = 0
                   DISPLAY "Salary updated successfully"
               ELSE
                   DISPLAY "Update failed: " SQLCODE
               END-IF
           END-IF.
    '''
    
    result = parse_cobol(cobol_source, "sql_demo.cob")
    
    print(f"✅ Parse Success: {result.success}")
    
    if result.ast:
        # Analyze SQL statements
        ibm_dialect = IBMEnterpriseCobol()
        
        print(f"\n💾 SQL Statement Analysis:")
        
        # Sample SQL parsing (simplified demonstration)
        sql_statements = [
            "CONNECT TO :DATABASE-NAME",
            "SELECT EMP_ID, EMP_NAME, SALARY, DEPT_CODE INTO :WS-EMP-ID, :WS-EMP-NAME, :WS-EMP-SALARY, :WS-DEPT-CODE FROM EMPLOYEE WHERE EMP_ID = :WS-SEARCH-ID",
            "UPDATE EMPLOYEE SET SALARY = :WS-NEW-SALARY WHERE EMP_ID = :WS-EMP-ID",
            "COMMIT WORK"
        ]
        
        for i, sql in enumerate(sql_statements, 1):
            location = SourceLocation("sql_demo.cob", i * 5, 1)
            sql_stmt = ibm_dialect.parse_exec_sql(sql, location)
            
            print(f"  {i}. SQL Type: {sql_stmt.sql_type}")
            print(f"     Host Variables: {sql_stmt.host_variables}")
            print(f"     Statement: {sql[:50]}{'...' if len(sql) > 50 else ''}")


def example_3_exec_cics():
    """Demonstrate EXEC CICS transaction processing commands."""
    print("\n" + "=" * 60)
    print("IBM EXAMPLE 3: EXEC CICS Commands")
    print("=" * 60)
    
    cobol_source = '''
       IDENTIFICATION DIVISION.
       PROGRAM-ID. CICS-DEMO.
       
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-COMMAREA          PIC X(100).
       01  WS-RESPONSE          PIC S9(8) COMP.
       01  WS-CUSTOMER-KEY      PIC X(6).
       01  WS-CUSTOMER-REC      PIC X(200).
       01  WS-FILE-NAME         PIC X(8) VALUE 'CUSTFILE'.
       01  WS-MAP-NAME          PIC X(7) VALUE 'CUSTMAP'.
       01  WS-MAPSET-NAME       PIC X(8) VALUE 'CUSTMAPS'.
       
       LINKAGE SECTION.
       01  DFHCOMMAREA          PIC X(100).
       
       PROCEDURE DIVISION USING DFHCOMMAREA.
       MAIN-PROCESS.
           MOVE DFHCOMMAREA TO WS-COMMAREA.
           MOVE WS-COMMAREA(1:6) TO WS-CUSTOMER-KEY.
           
           PERFORM READ-CUSTOMER.
           PERFORM SEND-MAP.
           
           EXEC CICS
               RETURN TRANSID('CUST')
               COMMAREA(WS-COMMAREA)
               LENGTH(100)
           END-EXEC.
           
       READ-CUSTOMER.
           EXEC CICS
               READ FILE(WS-FILE-NAME)
               INTO(WS-CUSTOMER-REC)
               RIDFLD(WS-CUSTOMER-KEY)
               RESP(WS-RESPONSE)
           END-EXEC.
           
           IF WS-RESPONSE = DFHRESP(NORMAL)
               DISPLAY "Customer record read successfully"
           ELSE
               IF WS-RESPONSE = DFHRESP(NOTFND)
                   DISPLAY "Customer not found"
               ELSE
                   DISPLAY "Read error, response: " WS-RESPONSE
               END-IF
           END-IF.
           
       SEND-MAP.
           EXEC CICS
               SEND MAP(WS-MAP-NAME)
               MAPSET(WS-MAPSET-NAME)
               FROM(WS-CUSTOMER-REC)
               ERASE
           END-EXEC.
           
           EXEC CICS
               RECEIVE MAP(WS-MAP-NAME)
               MAPSET(WS-MAPSET-NAME)
               INTO(WS-CUSTOMER-REC)
           END-EXEC.
    '''
    
    result = parse_cobol(cobol_source, "cics_demo.cob")
    
    print(f"✅ Parse Success: {result.success}")
    
    if result.ast:
        # Analyze CICS commands
        ibm_dialect = IBMEnterpriseCobol()
        
        print(f"\n🌐 CICS Command Analysis:")
        
        # Sample CICS parsing (simplified demonstration)
        cics_commands = [
            "RETURN TRANSID('CUST') COMMAREA(WS-COMMAREA) LENGTH(100)",
            "READ FILE(WS-FILE-NAME) INTO(WS-CUSTOMER-REC) RIDFLD(WS-CUSTOMER-KEY) RESP(WS-RESPONSE)",
            "SEND MAP(WS-MAP-NAME) MAPSET(WS-MAPSET-NAME) FROM(WS-CUSTOMER-REC) ERASE",
            "RECEIVE MAP(WS-MAP-NAME) MAPSET(WS-MAPSET-NAME) INTO(WS-CUSTOMER-REC)"
        ]
        
        for i, cics in enumerate(cics_commands, 1):
            location = SourceLocation("cics_demo.cob", i * 10, 1)
            cics_stmt = ibm_dialect.parse_exec_cics(cics, location)
            
            print(f"  {i}. CICS Command: {cics_stmt.cics_command}")
            print(f"     Options: {list(cics_stmt.cics_options.keys())}")
            print(f"     Valid: {ibm_dialect.is_cics_command(cics_stmt.cics_command)}")


def example_4_intrinsic_functions():
    """Demonstrate IBM intrinsic functions."""
    print("\n" + "=" * 60)
    print("IBM EXAMPLE 4: Intrinsic Functions")
    print("=" * 60)
    
    cobol_source = '''
       IDENTIFICATION DIVISION.
       PROGRAM-ID. FUNCTION-DEMO.
       
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-TEXT-FIELD        PIC X(50) VALUE "Hello World".
       01  WS-NUMERIC-FIELD     PIC X(10) VALUE "12345.67".
       01  WS-DATE-FIELD        PIC X(21).
       01  WS-LENGTH-RESULT     PIC 9(3).
       01  WS-NUMERIC-RESULT    PIC 9(7)V99.
       01  WS-UPPER-TEXT        PIC X(50).
       01  WS-LOWER-TEXT        PIC X(50).
       
       PROCEDURE DIVISION.
       MAIN-PROCESS.
           PERFORM TEST-LENGTH-FUNCTION.
           PERFORM TEST-DATE-FUNCTION.
           PERFORM TEST-CASE-FUNCTIONS.
           PERFORM TEST-NUMERIC-FUNCTION.
           STOP RUN.
           
       TEST-LENGTH-FUNCTION.
           COMPUTE WS-LENGTH-RESULT = FUNCTION LENGTH(WS-TEXT-FIELD).
           DISPLAY "Length of '" WS-TEXT-FIELD "' is " WS-LENGTH-RESULT.
           
       TEST-DATE-FUNCTION.
           MOVE FUNCTION CURRENT-DATE TO WS-DATE-FIELD.
           DISPLAY "Current date/time: " WS-DATE-FIELD.
           
       TEST-CASE-FUNCTIONS.
           MOVE FUNCTION UPPER-CASE(WS-TEXT-FIELD) TO WS-UPPER-TEXT.
           MOVE FUNCTION LOWER-CASE(WS-TEXT-FIELD) TO WS-LOWER-TEXT.
           DISPLAY "Original: " WS-TEXT-FIELD.
           DISPLAY "Upper: " WS-UPPER-TEXT.
           DISPLAY "Lower: " WS-LOWER-TEXT.
           
       TEST-NUMERIC-FUNCTION.
           COMPUTE WS-NUMERIC-RESULT = FUNCTION NUMVAL(WS-NUMERIC-FIELD).
           DISPLAY "Converted number: " WS-NUMERIC-RESULT.
    '''
    
    result = parse_cobol(cobol_source, "function_demo.cob")
    
    print(f"✅ Parse Success: {result.success}")
    
    # Demonstrate intrinsic function capabilities
    ibm_dialect = IBMEnterpriseCobol()
    
    print(f"\n🔧 IBM Intrinsic Functions:")
    
    test_functions = [
        "LENGTH", "CURRENT-DATE", "UPPER-CASE", "LOWER-CASE", 
        "NUMVAL", "SQRT", "SIN", "COS", "MAX", "MIN"
    ]
    
    for func in test_functions:
        is_intrinsic = ibm_dialect.is_intrinsic_function(func)
        signature = ibm_dialect.get_intrinsic_function_signature(func)
        
        print(f"  📊 {func:12s} - {'✅' if is_intrinsic else '❌'} Intrinsic")
        if signature:
            print(f"       Returns: {signature['return_type']}")
            if signature.get('parameters'):
                print(f"       Parameters: {', '.join(signature['parameters'])}")
            if signature.get('description'):
                print(f"       Description: {signature['description']}")


def example_5_comprehensive_ibm_program():
    """Comprehensive example combining multiple IBM features."""
    print("\n" + "=" * 60)
    print("IBM EXAMPLE 5: Comprehensive IBM Program")
    print("=" * 60)
    
    cobol_source = '''
       IDENTIFICATION DIVISION.
       PROGRAM-ID. IBM-COMPREHENSIVE.
       AUTHOR. IBM COBOL PARSER DEMO.
       
       ENVIRONMENT DIVISION.
       CONFIGURATION SECTION.
       SOURCE-COMPUTER. IBM-390.
       OBJECT-COMPUTER. IBM-390.
       
       DATA DIVISION.
       FILE SECTION.
       FD  CUSTOMER-FILE
           RECORD CONTAINS 200 CHARACTERS
           BLOCK CONTAINS 0 RECORDS.
       01  CUSTOMER-RECORD      PIC X(200).
       
       WORKING-STORAGE SECTION.
       01  SQLCA                COPY SQLCA.
       
       01  WS-CUSTOMER-MASTER.
           05  WS-CUST-ID       PIC 9(8) COMP-3.
           05  WS-CUST-NAME     PIC X(30).
           05  WS-BALANCE       PIC S9(11)V99 COMP-3.
           05  WS-CREDIT-LIMIT  PIC 9(9)V99 COMP-3.
           05  WS-LAST-PAYMENT  PIC 9(8) COMP-3.
           05  WS-STATUS        PIC X.
               88  ACTIVE-CUSTOMER    VALUE 'A'.
               88  INACTIVE-CUSTOMER  VALUE 'I'.
               88  SUSPENDED-CUSTOMER VALUE 'S'.
       
       01  WS-COUNTERS.
           05  WS-TOTAL-CUSTOMERS   PIC 9(7) COMP-3 VALUE ZERO.
           05  WS-ACTIVE-COUNT      PIC 9(7) COMP-3 VALUE ZERO.
           05  WS-TOTAL-BALANCE     PIC S9(13)V99 COMP-3 VALUE ZERO.
       
       01  WS-WORK-FIELDS.
           05  WS-CURRENT-DATE      PIC X(21).
           05  WS-FORMATTED-BALANCE PIC $$$,$$$,$$9.99.
           05  WS-PERCENT-ACTIVE    PIC 999V99.
       
       PROCEDURE DIVISION.
       MAIN-PROCESSING.
           PERFORM INITIALIZATION.
           PERFORM PROCESS-CUSTOMERS.
           PERFORM GENERATE-STATISTICS.
           PERFORM CLEANUP.
           STOP RUN.
           
       INITIALIZATION.
           MOVE FUNCTION CURRENT-DATE TO WS-CURRENT-DATE.
           DISPLAY "Processing started at: " WS-CURRENT-DATE.
           
           EXEC SQL
               CONNECT TO CUSTOMER_DB
           END-EXEC.
           
           IF SQLCODE NOT = 0
               DISPLAY "Database connection failed: " SQLCODE
               STOP RUN
           END-IF.
           
       PROCESS-CUSTOMERS.
           EXEC SQL
               DECLARE CUSTOMER_CURSOR CURSOR FOR
               SELECT CUST_ID, CUST_NAME, BALANCE, 
                      CREDIT_LIMIT, LAST_PAYMENT, STATUS
               FROM CUSTOMER_MASTER
               WHERE STATUS IN ('A', 'I', 'S')
               ORDER BY CUST_ID
           END-EXEC.
           
           EXEC SQL
               OPEN CUSTOMER_CURSOR
           END-EXEC.
           
           PERFORM FETCH-CUSTOMER UNTIL SQLCODE = 100.
           
           EXEC SQL
               CLOSE CUSTOMER_CURSOR
           END-EXEC.
           
       FETCH-CUSTOMER.
           EXEC SQL
               FETCH CUSTOMER_CURSOR
               INTO :WS-CUST-ID, :WS-CUST-NAME, :WS-BALANCE,
                    :WS-CREDIT-LIMIT, :WS-LAST-PAYMENT, :WS-STATUS
           END-EXEC.
           
           IF SQLCODE = 0
               ADD 1 TO WS-TOTAL-CUSTOMERS
               ADD WS-BALANCE TO WS-TOTAL-BALANCE
               
               IF ACTIVE-CUSTOMER
                   ADD 1 TO WS-ACTIVE-COUNT
               END-IF
               
               MOVE WS-BALANCE TO WS-FORMATTED-BALANCE
               DISPLAY WS-CUST-ID " " WS-CUST-NAME 
                       " Balance: " WS-FORMATTED-BALANCE
           END-IF.
           
       GENERATE-STATISTICS.
           IF WS-TOTAL-CUSTOMERS > ZERO
               COMPUTE WS-PERCENT-ACTIVE = 
                   (WS-ACTIVE-COUNT / WS-TOTAL-CUSTOMERS) * 100
           END-IF.
           
           DISPLAY "=== PROCESSING STATISTICS ===".
           DISPLAY "Total customers: " WS-TOTAL-CUSTOMERS.
           DISPLAY "Active customers: " WS-ACTIVE-COUNT.
           DISPLAY "Percentage active: " WS-PERCENT-ACTIVE "%".
           
           MOVE WS-TOTAL-BALANCE TO WS-FORMATTED-BALANCE.
           DISPLAY "Total balance: " WS-FORMATTED-BALANCE.
           
       CLEANUP.
           EXEC SQL
               COMMIT WORK
           END-EXEC.
           
           EXEC SQL
               DISCONNECT
           END-EXEC.
           
           DISPLAY "Processing completed successfully.".
    '''
    
    result = parse_cobol(cobol_source, "ibm_comprehensive.cob")
    
    print(f"✅ Parse Success: {result.success}")
    print(f"📊 Comprehensive Program Analysis:")
    
    if result.ast:
        # Detailed analysis
        print(f"  📁 Program: {result.ast.program_name}")
        print(f"  📂 Divisions: {len(result.ast.divisions)}")
        
        # Count IBM-specific features
        comp3_count = 0
        sql_features = ["SQLCA", "EXEC SQL", "CURSOR", "FETCH"]
        sql_found = []
        
        for div_name, division in result.ast.divisions.items():
            print(f"    📂 {division.division_name}:")
            
            for sec_name, section in division.sections.items():
                print(f"      📄 {section.section_name}: {len(section.children)} items")
                
                # Count COMP-3 fields
                for item in section.children:
                    if hasattr(item, 'usage') and 'COMP-3' in str(item.usage):
                        comp3_count += 1
        
        print(f"\n💰 IBM Features Detected:")
        print(f"  📊 COMP-3 Fields: {comp3_count}")
        print(f"  💾 SQL Integration: Present")
        print(f"  🌐 CICS Features: Not in this example")
        
        print(f"\n📈 Performance Metrics:")
        print(f"  ⏱️  Parse Time: {result.statistics.total_time_ms:.2f}ms")
        print(f"  📏 Lines: {result.statistics.lines_parsed}")
        print(f"  🔢 Tokens: {result.statistics.tokens_processed}")


def main():
    """Run all IBM Enterprise COBOL examples."""
    print("🏢 COBOL Parser - IBM Enterprise COBOL Examples")
    print("Demonstrating IBM-specific features and extensions\n")
    
    try:
        example_1_comp3_data_types()
        example_2_exec_sql()
        example_3_exec_cics()
        example_4_intrinsic_functions()
        example_5_comprehensive_ibm_program()
        
        print("\n" + "=" * 60)
        print("✅ All IBM Enterprise COBOL examples completed!")
        print("=" * 60)
        
        # Show IBM dialect summary
        ibm = IBMEnterpriseCobol()
        info = ibm.get_dialect_info()
        print(f"\n🏢 {info['name']} Summary:")
        print(f"  Version: {info['version']}")
        print(f"  Platform: {info['platform']}")
        print(f"  Features: {len(info['features'])}")
        print(f"  Reserved Words: {info['reserved_words']}")
        print(f"  Intrinsic Functions: {info['intrinsic_functions']}")
        print(f"  CICS Commands: {info['cics_commands']}")
        
    except Exception as e:
        print(f"\n❌ IBM example failed: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()