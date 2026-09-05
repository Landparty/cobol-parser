      *****************************************************************
      * Real-World COBOL Example: Advanced CALL Patterns
      * Demonstrates: BY REFERENCE, BY VALUE, RETURNING, EXCEPTION
      * Use Case: Complex financial calculations with error handling
      *****************************************************************
       IDENTIFICATION DIVISION.
       PROGRAM-ID. LOAN-CALCULATOR.
       
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-LOAN-INFO.
           05  WS-PRINCIPAL        PIC 9(10)V99 COMP-3.
           05  WS-ANNUAL-RATE      PIC 9V99 COMP-3.
           05  WS-YEARS            PIC 99 COMP.
           05  WS-MONTHLY-RATE     PIC 9V9(9) COMP-3.
           05  WS-MONTHS           PIC 999 COMP.
           
       01  WS-PAYMENT-INFO.
           05  WS-MONTHLY-PAYMENT  PIC 9(8)V99 COMP-3.
           05  WS-TOTAL-INTEREST   PIC 9(10)V99 COMP-3.
           05  WS-TOTAL-PAID       PIC 9(10)V99 COMP-3.
           
       01  WS-VALIDATION.
           05  WS-VALID-FLAG       PIC X VALUE 'N'.
           05  WS-ERROR-CODE       PIC 99 VALUE 0.
           05  WS-ERROR-MSG        PIC X(100).
           
       01  WS-RETURN-INFO.
           05  WS-RESULT-CODE      PIC 9.
           05  WS-RESULT-MSG       PIC X(100).
           
       PROCEDURE DIVISION.
       MAIN-LOAN-CALC.
           DISPLAY 'Loan Calculator Started'
           
           MOVE 500000.00 TO WS-PRINCIPAL
           MOVE 6.5 TO WS-ANNUAL-RATE
           MOVE 30 TO WS-YEARS
           
      *    CALL with BY REFERENCE (parameters can be modified)
           CALL 'VALIDATE-LOAN' USING BY REFERENCE WS-PRINCIPAL
                                            WS-ANNUAL-RATE
                                            WS-YEARS
                                            WS-VALID-FLAG
                                            WS-ERROR-CODE
           
           IF WS-VALID-FLAG = 'Y'
               DISPLAY 'Loan parameters validated'
               
      *        CALL with BY VALUE (parameters NOT modified)
               CALL 'CALC-RATE' USING BY VALUE WS-ANNUAL-RATE
                                      BY REFERENCE WS-MONTHLY-RATE
                                      
      *        CALL with RETURNING clause
               CALL 'CALC-MONTHS' USING WS-YEARS
                   RETURNING WS-MONTHS
                   
      *        CALL with RETURNING and exception handling
               CALL 'CALC-PAYMENT' 
                   USING WS-PRINCIPAL
                         WS-MONTHLY-RATE
                         WS-MONTHS
                         WS-MONTHLY-PAYMENT
                         WS-TOTAL-INTEREST
                   RETURNING WS-RESULT-CODE
                   ON EXCEPTION
                       MOVE 1 TO WS-ERROR-CODE
                       MOVE 'Calculation failed' TO WS-ERROR-MSG
                       DISPLAY WS-ERROR-MSG
                   NOT ON EXCEPTION
                       DISPLAY 'Monthly Payment: ' WS-MONTHLY-PAYMENT
                       DISPLAY 'Total Interest: ' WS-TOTAL-INTEREST
           ELSE
               DISPLAY 'Loan validation failed: ' WS-ERROR-CODE
           END-IF
           
           STOP RUN.
           
       END PROGRAM LOAN-CALCULATOR.
