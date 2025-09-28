      *****************************************************************
      * IBM Enterprise COBOL Sample - Complex Data Structures
      * Demonstrates: Nested structures, OCCURS clauses, REDEFINES
      * Features: Advanced data handling, table processing 
      *****************************************************************
       IDENTIFICATION DIVISION.
       PROGRAM-ID. DATA-STRUCTURES.
       
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       
       01  WS-COMPANY-DATA.
           05  WS-COMPANY-NAME     PIC X(40) VALUE 'ABC CORPORATION'.
           05  WS-EMPLOYEE-TABLE.
               10  WS-EMP-COUNT    PIC 9(3) VALUE 5.
               10  WS-EMPLOYEES    OCCURS 1 TO 100 TIMES
                                   DEPENDING ON WS-EMP-COUNT
                                   INDEXED BY EMP-IDX.
                   15  WS-EMP-DETAILS.
                       20  WS-EMP-ID       PIC 9(6).
                       20  WS-EMP-NAME     PIC X(25).  
                       20  WS-EMP-SALARY   PIC 9(7)V99 COMP-3.
                   15  WS-EMP-ADDRESS.
                       20  WS-EMP-STREET   PIC X(30).
                       20  WS-EMP-CITY     PIC X(20).
                       20  WS-EMP-STATE    PIC XX.
                       20  WS-EMP-ZIP      PIC 9(5).
                   15  WS-EMP-BENEFITS.
                       20  WS-HEALTH-PLAN  PIC X.
                           88  HAS-HEALTH  VALUE 'Y'.
                       20  WS-DENTAL-PLAN  PIC X.  
                           88  HAS-DENTAL  VALUE 'Y'.
                       20  WS-401K-CONTRIB PIC 9(2)V99 COMP-3.
                       
       01  WS-SALARY-ANALYSIS.
           05  WS-TOTAL-SALARY     PIC 9(10)V99 COMP-3 VALUE ZERO.
           05  WS-AVG-SALARY       PIC 9(8)V99 COMP-3 VALUE ZERO. 
           05  WS-HIGH-SALARY      PIC 9(7)V99 COMP-3 VALUE ZERO.
           05  WS-LOW-SALARY       PIC 9(7)V99 COMP-3 VALUE 999999.99.
           
       01  WS-BENEFIT-COUNTS.
           05  WS-HEALTH-COUNT     PIC 9(3) VALUE ZERO.
           05  WS-DENTAL-COUNT     PIC 9(3) VALUE ZERO.
           05  WS-FULL-BENEFITS    PIC 9(3) VALUE ZERO.
           
      * REDEFINES for alternate data view
       01  WS-EMPLOYEE-FLAT-VIEW REDEFINES WS-EMPLOYEE-TABLE.
           05  WS-FLAT-COUNT       PIC 9(3).
           05  FILLER              PIC X(8700).  
           
       01  WS-DISPLAY-FIELDS.
           05  WS-DISPLAY-SALARY   PIC $$$,$$$,$$9.99.
           05  WS-DISPLAY-PERCENT  PIC ZZ9.99.
           
       PROCEDURE DIVISION.
       MAIN-PROCESSING.
           PERFORM INITIALIZE-EMPLOYEE-DATA
           PERFORM ANALYZE-EMPLOYEE-DATA  
           PERFORM DISPLAY-ANALYSIS-RESULTS
           STOP RUN.
           
       INITIALIZE-EMPLOYEE-DATA.
           DISPLAY 'Initializing employee data for: ' WS-COMPANY-NAME
           
      * Initialize sample employee data
           SET EMP-IDX TO 1
           MOVE 100001 TO WS-EMP-ID(EMP-IDX)
           MOVE 'JOHN SMITH' TO WS-EMP-NAME(EMP-IDX)  
           MOVE 75000.00 TO WS-EMP-SALARY(EMP-IDX)
           MOVE 'Y' TO WS-HEALTH-PLAN(EMP-IDX)
           MOVE 'Y' TO WS-DENTAL-PLAN(EMP-IDX)
           MOVE 6.00 TO WS-401K-CONTRIB(EMP-IDX)
           
           SET EMP-IDX TO 2  
           MOVE 100002 TO WS-EMP-ID(EMP-IDX)
           MOVE 'MARY JOHNSON' TO WS-EMP-NAME(EMP-IDX)
           MOVE 82000.00 TO WS-EMP-SALARY(EMP-IDX)  
           MOVE 'Y' TO WS-HEALTH-PLAN(EMP-IDX)
           MOVE 'N' TO WS-DENTAL-PLAN(EMP-IDX)
           MOVE 4.50 TO WS-401K-CONTRIB(EMP-IDX)
           
           SET EMP-IDX TO 3
           MOVE 100003 TO WS-EMP-ID(EMP-IDX)
           MOVE 'ROBERT WILLIAMS' TO WS-EMP-NAME(EMP-IDX)
           MOVE 95000.00 TO WS-EMP-SALARY(EMP-IDX)
           MOVE 'Y' TO WS-HEALTH-PLAN(EMP-IDX)  
           MOVE 'Y' TO WS-DENTAL-PLAN(EMP-IDX)
           MOVE 8.00 TO WS-401K-CONTRIB(EMP-IDX)
           
           SET EMP-IDX TO 4
           MOVE 100004 TO WS-EMP-ID(EMP-IDX)  
           MOVE 'LISA BROWN' TO WS-EMP-NAME(EMP-IDX)
           MOVE 68000.00 TO WS-EMP-SALARY(EMP-IDX)
           MOVE 'N' TO WS-HEALTH-PLAN(EMP-IDX)
           MOVE 'N' TO WS-DENTAL-PLAN(EMP-IDX)  
           MOVE 2.00 TO WS-401K-CONTRIB(EMP-IDX)
           
           SET EMP-IDX TO 5
           MOVE 100005 TO WS-EMP-ID(EMP-IDX)
           MOVE 'DAVID DAVIS' TO WS-EMP-NAME(EMP-IDX)
           MOVE 87500.00 TO WS-EMP-SALARY(EMP-IDX)
           MOVE 'Y' TO WS-HEALTH-PLAN(EMP-IDX)
           MOVE 'Y' TO WS-DENTAL-PLAN(EMP-IDX)
           MOVE 7.25 TO WS-401K-CONTRIB(EMP-IDX).
           
       ANALYZE-EMPLOYEE-DATA.
           DISPLAY 'Analyzing employee data...'
           
           PERFORM VARYING EMP-IDX FROM 1 BY 1
               UNTIL EMP-IDX > WS-EMP-COUNT
               
               ADD WS-EMP-SALARY(EMP-IDX) TO WS-TOTAL-SALARY
               
               IF WS-EMP-SALARY(EMP-IDX) > WS-HIGH-SALARY
                   MOVE WS-EMP-SALARY(EMP-IDX) TO WS-HIGH-SALARY
               END-IF
               
               IF WS-EMP-SALARY(EMP-IDX) < WS-LOW-SALARY  
                   MOVE WS-EMP-SALARY(EMP-IDX) TO WS-LOW-SALARY
               END-IF
               
               IF HAS-HEALTH(EMP-IDX)
                   ADD 1 TO WS-HEALTH-COUNT
               END-IF
               
               IF HAS-DENTAL(EMP-IDX)
                   ADD 1 TO WS-DENTAL-COUNT  
               END-IF
               
               IF HAS-HEALTH(EMP-IDX) AND HAS-DENTAL(EMP-IDX)
                   ADD 1 TO WS-FULL-BENEFITS
               END-IF
               
           END-PERFORM
           
           COMPUTE WS-AVG-SALARY = WS-TOTAL-SALARY / WS-EMP-COUNT.
           
       DISPLAY-ANALYSIS-RESULTS.
           DISPLAY 'Employee Analysis Results:'
           DISPLAY '========================='
           DISPLAY 'Total Employees: ' WS-EMP-COUNT
           
           MOVE WS-TOTAL-SALARY TO WS-DISPLAY-SALARY  
           DISPLAY 'Total Payroll: ' WS-DISPLAY-SALARY
           
           MOVE WS-AVG-SALARY TO WS-DISPLAY-SALARY
           DISPLAY 'Average Salary: ' WS-DISPLAY-SALARY
           
           MOVE WS-HIGH-SALARY TO WS-DISPLAY-SALARY
           DISPLAY 'Highest Salary: ' WS-DISPLAY-SALARY
           
           MOVE WS-LOW-SALARY TO WS-DISPLAY-SALARY  
           DISPLAY 'Lowest Salary: ' WS-DISPLAY-SALARY
           
           COMPUTE WS-DISPLAY-PERCENT = 
               (WS-HEALTH-COUNT / WS-EMP-COUNT) * 100
           DISPLAY 'Health Plan Participation: ' WS-DISPLAY-PERCENT '%'
           
           COMPUTE WS-DISPLAY-PERCENT =
               (WS-DENTAL-COUNT / WS-EMP-COUNT) * 100  
           DISPLAY 'Dental Plan Participation: ' WS-DISPLAY-PERCENT '%'
           
           COMPUTE WS-DISPLAY-PERCENT =
               (WS-FULL-BENEFITS / WS-EMP-COUNT) * 100
           DISPLAY 'Full Benefits Participation: ' WS-DISPLAY-PERCENT '%'.