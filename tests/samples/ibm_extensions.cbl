      *****************************************************************
      * IBM Enterprise COBOL Extensions
      * Tests: EXEC SQL, EXEC CICS, EXEC IMS, COMP-3, intrinsics
      *****************************************************************
       IDENTIFICATION DIVISION.
       PROGRAM-ID. IBMEXT.
       
       DATA DIVISION.
       WORKING-STORAGE SECTION.
      *    IBM computational formats
       01  WS-IBM-FORMATS.
           05  WS-COMP             PIC 9(5) COMP.
           05  WS-COMP-1           COMP-1.
           05  WS-COMP-2           COMP-2.
           05  WS-COMP-3           PIC 9(7)V99 COMP-3.
           05  WS-COMP-4           PIC 9(9) COMP-4.
           05  WS-COMP-5           PIC 9(9) COMP-5.
           05  WS-BINARY           PIC 9(4) BINARY.
           05  WS-PACKED-DECIMAL   PIC 9(7)V99 PACKED-DECIMAL.
           
      *    SQL host variables
       01  WS-SQL-VARS.
           05  WS-EMPLOYEE-ID      PIC 9(6).
           05  WS-EMPLOYEE-NAME    PIC X(30).
           05  WS-EMPLOYEE-SALARY  PIC 9(7)V99 COMP-3.
           05  WS-SQL-CODE         PIC S9(9) COMP.
           05  WS-SQL-STATE        PIC X(5).
           
      *    CICS variables
       01  WS-CICS-VARS.
           05  WS-MAP-NAME         PIC X(8) VALUE 'EMPMAP'.
           05  WS-MAPSET-NAME      PIC X(8) VALUE 'EMPSET'.
           05  WS-TRANS-ID         PIC X(4) VALUE 'EMP1'.
           05  WS-COMMAREA         PIC X(100).
           05  WS-RESP-CODE        PIC S9(8) COMP.
           05  WS-RESP2-CODE       PIC S9(8) COMP.
           
      *    IMS variables
       01  WS-IMS-VARS.
           05  WS-PCB-POINTER      POINTER.
           05  WS-SEGMENT-NAME     PIC X(8).
           05  WS-STATUS-CODE      PIC XX.
           
       01  WS-WORK-FIELDS.
           05  WS-RESULT           PIC 9(10)V99.
           05  WS-DATE-FIELD       PIC 9(8).
           05  WS-TIME-FIELD       PIC 9(8).
           
      *    SQL Communication Area
           EXEC SQL
               INCLUDE SQLCA
           END-EXEC.
           
      *    SQL Declare Section
           EXEC SQL BEGIN DECLARE SECTION
           END-EXEC.
           
       01  SQLCA-AREA.
           05  SQLCODE             PIC S9(9) COMP.
           
           EXEC SQL END DECLARE SECTION
           END-EXEC.
           
       PROCEDURE DIVISION.
       MAIN-LOGIC.
           DISPLAY 'IBM Enterprise COBOL Extensions Test'
           PERFORM SQL-OPERATIONS
           PERFORM CICS-OPERATIONS
           PERFORM IMS-OPERATIONS
           PERFORM INTRINSIC-FUNCTIONS
           STOP RUN.
           
       SQL-OPERATIONS.
      *    Simple SQL SELECT
           EXEC SQL
               SELECT EMPLOYEE_ID, EMPLOYEE_NAME, SALARY
               INTO :WS-EMPLOYEE-ID,
                    :WS-EMPLOYEE-NAME,
                    :WS-EMPLOYEE-SALARY
               FROM EMPLOYEES
               WHERE EMPLOYEE_ID = 100
           END-EXEC
           
           IF SQLCODE = 0
               DISPLAY 'Employee found: ' WS-EMPLOYEE-NAME
           ELSE
               DISPLAY 'SQL Error: ' SQLCODE
           END-IF
           
      *    SQL INSERT
           EXEC SQL
               INSERT INTO EMPLOYEES
                   (EMPLOYEE_ID, EMPLOYEE_NAME, SALARY)
               VALUES
                   (:WS-EMPLOYEE-ID,
                    :WS-EMPLOYEE-NAME,
                    :WS-EMPLOYEE-SALARY)
           END-EXEC
           
      *    SQL UPDATE
           EXEC SQL
               UPDATE EMPLOYEES
               SET SALARY = :WS-EMPLOYEE-SALARY
               WHERE EMPLOYEE_ID = :WS-EMPLOYEE-ID
           END-EXEC
           
      *    SQL DELETE
           EXEC SQL
               DELETE FROM EMPLOYEES
               WHERE EMPLOYEE_ID = :WS-EMPLOYEE-ID
           END-EXEC
           
      *    SQL Cursor operations
           EXEC SQL
               DECLARE EMP_CURSOR CURSOR FOR
               SELECT EMPLOYEE_ID, EMPLOYEE_NAME
               FROM EMPLOYEES
               WHERE SALARY > 50000
           END-EXEC
           
           EXEC SQL
               OPEN EMP_CURSOR
           END-EXEC
           
           EXEC SQL
               FETCH EMP_CURSOR
               INTO :WS-EMPLOYEE-ID,
                    :WS-EMPLOYEE-NAME
           END-EXEC
           
           EXEC SQL
               CLOSE EMP_CURSOR
           END-EXEC
           
      *    SQL COMMIT/ROLLBACK
           EXEC SQL
               COMMIT WORK
           END-EXEC
           
           EXEC SQL
               ROLLBACK WORK
           END-EXEC
           
      *    SQL with host variables and indicators
           EXEC SQL
               SELECT COUNT(*)
               INTO :WS-RESULT
               FROM EMPLOYEES
               WHERE DEPARTMENT = :WS-EMPLOYEE-NAME
           END-EXEC.
           
       CICS-OPERATIONS.
      *    CICS SEND MAP
           EXEC CICS
               SEND MAP(WS-MAP-NAME)
                    MAPSET(WS-MAPSET-NAME)
                    ERASE
                    RESP(WS-RESP-CODE)
           END-EXEC
           
      *    CICS RECEIVE MAP
           EXEC CICS
               RECEIVE MAP(WS-MAP-NAME)
                       MAPSET(WS-MAPSET-NAME)
                       RESP(WS-RESP-CODE)
           END-EXEC
           
      *    CICS READ
           EXEC CICS
               READ FILE('EMPFILE')
                    INTO(WS-COMMAREA)
                    RIDFLD(WS-EMPLOYEE-ID)
                    RESP(WS-RESP-CODE)
                    RESP2(WS-RESP2-CODE)
           END-EXEC
           
      *    CICS WRITE
           EXEC CICS
               WRITE FILE('EMPFILE')
                     FROM(WS-COMMAREA)
                     RIDFLD(WS-EMPLOYEE-ID)
                     RESP(WS-RESP-CODE)
           END-EXEC
           
      *    CICS REWRITE
           EXEC CICS
               REWRITE FILE('EMPFILE')
                       FROM(WS-COMMAREA)
                       RESP(WS-RESP-CODE)
           END-EXEC
           
      *    CICS DELETE
           EXEC CICS
               DELETE FILE('EMPFILE')
                      RIDFLD(WS-EMPLOYEE-ID)
                      RESP(WS-RESP-CODE)
           END-EXEC
           
      *    CICS LINK
           EXEC CICS
               LINK PROGRAM('SUBPROG')
                    COMMAREA(WS-COMMAREA)
                    LENGTH(100)
                    RESP(WS-RESP-CODE)
           END-EXEC
           
      *    CICS XCTL
           EXEC CICS
               XCTL PROGRAM('NEXTPROG')
                    COMMAREA(WS-COMMAREA)
                    LENGTH(100)
           END-EXEC
           
      *    CICS RETURN
           EXEC CICS
               RETURN TRANSID(WS-TRANS-ID)
                      COMMAREA(WS-COMMAREA)
                      LENGTH(100)
           END-EXEC.
           
       IMS-OPERATIONS.
      *    IMS GET UNIQUE
           EXEC IMS
               GU SEGMENT-NAME(WS-SEGMENT-NAME)
                  INTO(WS-COMMAREA)
                  STATUS(WS-STATUS-CODE)
           END-EXEC
           
      *    IMS GET NEXT
           EXEC IMS
               GN SEGMENT-NAME(WS-SEGMENT-NAME)
                  INTO(WS-COMMAREA)
                  STATUS(WS-STATUS-CODE)
           END-EXEC
           
      *    IMS INSERT
           EXEC IMS
               ISRT SEGMENT-NAME(WS-SEGMENT-NAME)
                    FROM(WS-COMMAREA)
                    STATUS(WS-STATUS-CODE)
           END-EXEC
           
      *    IMS DELETE
           EXEC IMS
               DLET STATUS(WS-STATUS-CODE)
           END-EXEC
           
      *    IMS REPLACE
           EXEC IMS
               REPL FROM(WS-COMMAREA)
                    STATUS(WS-STATUS-CODE)
           END-EXEC.
           
       INTRINSIC-FUNCTIONS.
      *    IBM Intrinsic Functions
           COMPUTE WS-RESULT = FUNCTION LENGTH(WS-EMPLOYEE-NAME)
           DISPLAY 'Length: ' WS-RESULT
           
           COMPUTE WS-RESULT = FUNCTION NUMVAL('12345.67')
           DISPLAY 'Numeric value: ' WS-RESULT
           
           COMPUTE WS-RESULT = FUNCTION UPPER-CASE(WS-EMPLOYEE-NAME)
           DISPLAY 'Upper case: ' WS-RESULT
           
           COMPUTE WS-RESULT = FUNCTION LOWER-CASE(WS-EMPLOYEE-NAME)
           DISPLAY 'Lower case: ' WS-RESULT
           
           COMPUTE WS-RESULT = FUNCTION REVERSE(WS-EMPLOYEE-NAME)
           DISPLAY 'Reversed: ' WS-RESULT
           
           COMPUTE WS-RESULT = FUNCTION MAX(10, 20, 30)
           DISPLAY 'Maximum: ' WS-RESULT
           
           COMPUTE WS-RESULT = FUNCTION MIN(10, 20, 30)
           DISPLAY 'Minimum: ' WS-RESULT
           
           COMPUTE WS-RESULT = FUNCTION MEDIAN(10, 20, 30, 40, 50)
           DISPLAY 'Median: ' WS-RESULT
           
           COMPUTE WS-RESULT = FUNCTION SUM(10, 20, 30)
           DISPLAY 'Sum: ' WS-RESULT
           
           COMPUTE WS-RESULT = FUNCTION MEAN(10, 20, 30)
           DISPLAY 'Mean: ' WS-RESULT
           
           ACCEPT WS-DATE-FIELD FROM DATE YYYYMMDD
           DISPLAY 'Current date: ' WS-DATE-FIELD
           
           ACCEPT WS-TIME-FIELD FROM TIME
           DISPLAY 'Current time: ' WS-TIME-FIELD
           
           COMPUTE WS-RESULT = FUNCTION CURRENT-DATE
           DISPLAY 'Current date/time: ' WS-RESULT.
