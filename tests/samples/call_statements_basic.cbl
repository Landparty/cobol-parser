      *****************************************************************
      * Real-World COBOL Example: Basic CALL Statements
      * Demonstrates: Simple CALL, dynamic CALL, CALL with parameters
      * Use Case: Employee payroll processing with subprograms
      *****************************************************************
       IDENTIFICATION DIVISION.
       PROGRAM-ID. PAYROLL-MAIN.
       
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-EMPLOYEE-DATA.
           05  WS-EMP-ID           PIC 9(6).
           05  WS-EMP-NAME         PIC X(30).
           05  WS-SALARY           PIC 9(7)V99 COMP-3.
           05  WS-HOURS            PIC 9(3)V99 COMP-3.
           
       01  WS-PAYROLL-RESULTS.
           05  WS-GROSS-PAY        PIC 9(7)V99 COMP-3.
           05  WS-TAX-AMOUNT       PIC 9(7)V99 COMP-3.
           05  WS-NET-PAY          PIC 9(7)V99 COMP-3.
           
       01  WS-PROGRAM-NAMES.
           05  WS-CALC-PAY-PGM     PIC X(20) VALUE 'CALCPAY'.
           05  WS-CALC-TAX-PGM     PIC X(20) VALUE 'CALCTAX'.
           05  WS-REPORT-PGM       PIC X(20) VALUE 'RPTGEN'.
           
       01  WS-STATUS.
           05  WS-RETURN-CODE      PIC 99 VALUE 0.
           05  WS-ERROR-FLAG       PIC X VALUE 'N'.
           
       PROCEDURE DIVISION.
       MAIN-SECTION.
           DISPLAY 'Payroll Processing Started'
           MOVE 100001 TO WS-EMP-ID
           MOVE 'John Smith' TO WS-EMP-NAME
           MOVE 50000.00 TO WS-SALARY
           MOVE 40.00 TO WS-HOURS
           
      *    Simple CALL - static program name
           CALL 'CALCPAY' USING WS-SALARY 
                                WS-HOURS
                                WS-GROSS-PAY
           
      *    CALL with dynamic program name
           CALL WS-CALC-TAX-PGM USING WS-GROSS-PAY
                                      WS-TAX-AMOUNT
                                      
      *    CALL with multiple parameters
           CALL 'RPTGEN' USING WS-EMP-ID
                               WS-EMP-NAME
                               WS-GROSS-PAY
                               WS-TAX-AMOUNT
                               WS-NET-PAY
           
           DISPLAY 'Payroll Processing Complete'
           STOP RUN.
           
       END PROGRAM PAYROLL-MAIN.
