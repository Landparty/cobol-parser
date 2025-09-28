      *****************************************************************
      * IBM Enterprise COBOL Sample Program - Employee Processing
      * Demonstrates: Data Division, Procedure Division, File I/O
      * Compatible with: IBM COBOL for MVS & VM, Enterprise COBOL
      *****************************************************************
       IDENTIFICATION DIVISION.
       PROGRAM-ID. EMPLOYEE-PROC.
       AUTHOR. COBOL PARSER TEAM.
       DATE-WRITTEN. 2024-01-15.
       DATE-COMPILED.
       
       ENVIRONMENT DIVISION.
       CONFIGURATION SECTION.
       SOURCE-COMPUTER. IBM-Z15.
       OBJECT-COMPUTER. IBM-Z15.
       
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT EMPLOYEE-FILE ASSIGN TO EMPFILE
           ORGANIZATION IS SEQUENTIAL
           ACCESS MODE IS SEQUENTIAL
           FILE STATUS IS WS-FILE-STATUS.
           
           SELECT REPORT-FILE ASSIGN TO RPTFILE
           ORGANIZATION IS SEQUENTIAL  
           ACCESS MODE IS SEQUENTIAL.
       
       DATA DIVISION.
       FILE SECTION.
       FD  EMPLOYEE-FILE
           RECORDING MODE IS F
           BLOCK CONTAINS 0 RECORDS
           RECORD CONTAINS 100 CHARACTERS.
       01  EMPLOYEE-RECORD.
           05  EMP-ID              PIC 9(6).
           05  EMP-NAME            PIC X(25).
           05  EMP-DEPT            PIC X(10).
           05  EMP-SALARY          PIC 9(7)V99 COMP-3.
           05  EMP-HIRE-DATE.
               10  EMP-HIRE-YEAR   PIC 9999.
               10  EMP-HIRE-MONTH  PIC 99.
               10  EMP-HIRE-DAY    PIC 99.
           05  FILLER              PIC X(50).
       
       FD  REPORT-FILE
           RECORDING MODE IS F
           BLOCK CONTAINS 0 RECORDS
           RECORD CONTAINS 132 CHARACTERS.
       01  REPORT-RECORD           PIC X(132).
       
       WORKING-STORAGE SECTION.
       01  WS-COUNTERS.
           05  WS-RECORD-COUNT     PIC 9(6) VALUE ZERO.
           05  WS-HIGH-SALARY-COUNT PIC 9(6) VALUE ZERO.
           
       01  WS-FILE-STATUS          PIC XX VALUE SPACES.
           88  FILE-OK             VALUE '00'.
           88  END-OF-FILE         VALUE '10'.
           88  FILE-ERROR          VALUE '30' THRU '99'.
           
       01  WS-SALARY-THRESHOLD     PIC 9(7)V99 COMP-3 VALUE 75000.00.
       
       01  WS-CURRENT-DATE.
           05  WS-CURR-YEAR        PIC 9999.
           05  WS-CURR-MONTH       PIC 99.
           05  WS-CURR-DAY         PIC 99.
           
       01  WS-REPORT-HEADER.
           05  FILLER              PIC X(20) VALUE 'EMPLOYEE REPORT - '.
           05  WS-REPORT-DATE      PIC X(10).
           05  FILLER              PIC X(102) VALUE SPACES.
       
       PROCEDURE DIVISION.
       MAIN-PROCESS.
           PERFORM INITIALIZE-PROGRAM
           PERFORM PROCESS-EMPLOYEES
           PERFORM FINALIZE-PROGRAM
           STOP RUN.
           
       INITIALIZE-PROGRAM.
           DISPLAY 'Starting Employee Processing Program'
           ACCEPT WS-CURRENT-DATE FROM DATE YYYYMMDD
           MOVE FUNCTION CURRENT-DATE(1:8) TO WS-REPORT-DATE
           OPEN INPUT EMPLOYEE-FILE
           OPEN OUTPUT REPORT-FILE
           IF NOT FILE-OK
               DISPLAY 'Error opening files: ' WS-FILE-STATUS
               STOP RUN
           END-IF
           WRITE REPORT-RECORD FROM WS-REPORT-HEADER.
           
       PROCESS-EMPLOYEES.
           PERFORM READ-EMPLOYEE
           PERFORM UNTIL END-OF-FILE
               PERFORM PROCESS-SINGLE-EMPLOYEE
               PERFORM READ-EMPLOYEE
           END-PERFORM.
           
       READ-EMPLOYEE.
           READ EMPLOYEE-FILE
           EVALUATE WS-FILE-STATUS
               WHEN '00'
                   CONTINUE
               WHEN '10'
                   CONTINUE  
               WHEN OTHER
                   DISPLAY 'File read error: ' WS-FILE-STATUS
                   STOP RUN
           END-EVALUATE.
           
       PROCESS-SINGLE-EMPLOYEE.
           ADD 1 TO WS-RECORD-COUNT
           IF EMP-SALARY > WS-SALARY-THRESHOLD
               ADD 1 TO WS-HIGH-SALARY-COUNT
               PERFORM WRITE-HIGH-SALARY-REPORT
           END-IF
           PERFORM CALCULATE-YEARS-SERVICE.
           
       WRITE-HIGH-SALARY-REPORT.
           MOVE SPACES TO REPORT-RECORD
           STRING 'High Salary Employee: '
                  EMP-ID DELIMITED BY SIZE
                  ' - '
                  EMP-NAME DELIMITED BY SPACE  
                  ' Salary: $'
                  EMP-SALARY DELIMITED BY SIZE
               INTO REPORT-RECORD
           END-STRING
           WRITE REPORT-RECORD.
           
       CALCULATE-YEARS-SERVICE.
           COMPUTE WS-YEARS-SERVICE = 
               WS-CURR-YEAR - EMP-HIRE-YEAR
           IF WS-CURR-MONTH < EMP-HIRE-MONTH OR
              (WS-CURR-MONTH = EMP-HIRE-MONTH AND 
               WS-CURR-DAY < EMP-HIRE-DAY)
               SUBTRACT 1 FROM WS-YEARS-SERVICE
           END-IF.
           
       01  WS-YEARS-SERVICE        PIC 9(3) VALUE ZERO.
       
       FINALIZE-PROGRAM.
           MOVE SPACES TO REPORT-RECORD
           STRING 'Total Employees Processed: '
                  WS-RECORD-COUNT DELIMITED BY SIZE
               INTO REPORT-RECORD
           END-STRING
           WRITE REPORT-RECORD
           
           MOVE SPACES TO REPORT-RECORD  
           STRING 'High Salary Employees: '
                  WS-HIGH-SALARY-COUNT DELIMITED BY SIZE
               INTO REPORT-RECORD
           END-STRING
           WRITE REPORT-RECORD
           
           CLOSE EMPLOYEE-FILE
           CLOSE REPORT-FILE
           DISPLAY 'Employee Processing Complete - ' 
                   WS-RECORD-COUNT ' records processed'.
                   
       END PROGRAM EMPLOYEE-PROC.