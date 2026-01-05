      *****************************************************************
      * Real-World COBOL Example: CALL Statements with Periods
      * Demonstrates: CALL with periods in various contexts
      * Use Case: Payment processing system with period terminators
      *****************************************************************
       IDENTIFICATION DIVISION.
       PROGRAM-ID. CALL-WITH-PERIODS.
       
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-PAYMENT-DATA.
           05  WS-ACCOUNT-NUM      PIC 9(10).
           05  WS-AMOUNT           PIC 9(7)V99 COMP-3.
           05  WS-PAYMENT-TYPE     PIC X(10).
           05  WS-RESULT-CODE      PIC 99.
           
       01  WS-VALIDATION-DATA.
           05  WS-VALID-FLAG       PIC X VALUE 'N'.
           05  WS-ERROR-MSG        PIC X(50).
           05  WS-RETRY-COUNT      PIC 9 VALUE 0.
           
       01  WS-SERVICE-NAMES.
           05  WS-VALIDATE-SVC     PIC X(20) VALUE 'VALIDATE-PAYMENT'.
           05  WS-PROCESS-SVC      PIC X(20) VALUE 'PROCESS-PAYMENT'.
           05  WS-AUDIT-SVC        PIC X(20) VALUE 'AUDIT-LOG'.
           
       01  WS-COUNTERS.
           05  WS-COUNTER          PIC 9(3) VALUE 0.
           05  WS-MAX-RETRIES      PIC 9 VALUE 3.
           
       PROCEDURE DIVISION.
       MAIN-PROCESSING.
           DISPLAY 'Payment Processing with Periods'.
           PERFORM INITIALIZE-DATA.
           PERFORM VALIDATE-PAYMENT.
           PERFORM PROCESS-PAYMENT.
           PERFORM AUDIT-TRANSACTION.
           STOP RUN.
           
       INITIALIZE-DATA.
      *    Simple CALL with period immediately after
           CALL 'INIT-SYSTEM'.
           
      *    CALL with USING and period
           CALL 'LOAD-CONFIG' USING WS-PAYMENT-DATA.
           
      *    CALL with multiple parameters and period
           CALL 'SETUP-ACCOUNT' USING WS-ACCOUNT-NUM
                                      WS-PAYMENT-TYPE
                                      WS-RESULT-CODE.
           
       VALIDATE-PAYMENT.
      *    CALL with dynamic program name and period
           CALL WS-VALIDATE-SVC USING WS-PAYMENT-DATA.
           
      *    CALL with BY REFERENCE and period
           CALL 'CHECK-AMOUNT' USING BY REFERENCE WS-AMOUNT.
           
      *    CALL with mixed parameter modes and period
           CALL 'VALIDATE-ACCOUNT' USING BY VALUE WS-ACCOUNT-NUM
                                         BY REFERENCE WS-VALID-FLAG.
           
      *    CALL inside IF with period
           IF WS-AMOUNT > 1000.00
               CALL 'HIGH-VALUE-CHECK' USING WS-AMOUNT
                                             WS-RESULT-CODE.
           
      *    CALL inside IF-ELSE with periods
           IF WS-VALID-FLAG = 'Y'
               CALL 'PROCEED-VALIDATION' USING WS-PAYMENT-DATA
           ELSE
               CALL 'REJECT-PAYMENT' USING WS-PAYMENT-DATA
                                           WS-ERROR-MSG.
           
       PROCESS-PAYMENT.
      *    CALL with RETURNING and period
           CALL 'CALCULATE-FEE' USING WS-AMOUNT
               RETURNING WS-RESULT-CODE.
           
      *    CALL inside PERFORM with period
           PERFORM VARYING WS-COUNTER FROM 1 BY 1
               UNTIL WS-COUNTER > 5
               CALL 'BATCH-PROCESS' USING WS-COUNTER
                                          WS-PAYMENT-DATA.
           
      *    CALL with exception handler and period
           CALL 'RISKY-OPERATION' USING WS-PAYMENT-DATA
               ON EXCEPTION
                   DISPLAY 'Operation failed'
               END-CALL.
           
      *    CALL with NOT ON EXCEPTION and period
           CALL 'SAFE-OPERATION' USING WS-PAYMENT-DATA
               NOT ON EXCEPTION
                   DISPLAY 'Operation succeeded'
               END-CALL.
           
      *    CALL with both exception handlers and period
           CALL 'COMPLEX-OPERATION' USING WS-PAYMENT-DATA
               ON EXCEPTION
                   MOVE 1 TO WS-RESULT-CODE
               NOT ON EXCEPTION
                   MOVE 0 TO WS-RESULT-CODE
               END-CALL.
           
       AUDIT-TRANSACTION.
      *    Multiple CALLs on consecutive lines with periods
           CALL 'LOG-START' USING WS-ACCOUNT-NUM.
           CALL 'LOG-AMOUNT' USING WS-AMOUNT.
           CALL 'LOG-TYPE' USING WS-PAYMENT-TYPE.
           CALL 'LOG-END' USING WS-RESULT-CODE.
           
      *    CALL inside nested IF with periods
           IF WS-RESULT-CODE = 0
               IF WS-AMOUNT > 5000.00
                   CALL 'ALERT-HIGH-VALUE' USING WS-ACCOUNT-NUM
                                                 WS-AMOUNT.
           
      *    CALL with literal parameter and period
           CALL 'SEND-NOTIFICATION' USING 'PAYMENT-COMPLETE'
                                          WS-ACCOUNT-NUM.
           
      *    CALL with RETURNING and USING and period
           CALL 'FINALIZE-TRANSACTION' USING WS-PAYMENT-DATA
                                             WS-ACCOUNT-NUM
               RETURNING WS-RESULT-CODE.
           
       END PROGRAM CALL-WITH-PERIODS.
