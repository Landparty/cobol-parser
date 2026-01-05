      *****************************************************************
      * Real-World COBOL Example: CALL Exception Handlers Complete
      * Demonstrates: All exception handling patterns for CALL
      * Use Case: Robust service integration with error recovery
      *****************************************************************
       IDENTIFICATION DIVISION.
       PROGRAM-ID. CALL-EXCEPTION-HANDLERS-COMPLETE.
       
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-SERVICE-DATA.
           05  WS-SERVICE-NAME     PIC X(30).
           05  WS-REQUEST-ID       PIC X(12).
           05  WS-RESPONSE-CODE    PIC 99.
           05  WS-ERROR-COUNT      PIC 9(3) VALUE 0.
           
       01  WS-TRANSACTION-DATA.
           05  WS-TRANS-ID         PIC X(12).
           05  WS-AMOUNT           PIC 9(9)V99 COMP-3.
           05  WS-ACCOUNT-NUM      PIC 9(10).
           
       01  WS-RETRY-CONTROL.
           05  WS-RETRY-COUNT      PIC 9 VALUE 0.
           05  WS-MAX-RETRIES      PIC 9 VALUE 3.
           05  WS-RETRY-FLAG       PIC X VALUE 'N'.
           
       01  WS-STATUS-FLAGS.
           05  WS-SUCCESS-FLAG     PIC X VALUE 'N'.
           05  WS-FAILURE-FLAG     PIC X VALUE 'N'.
           05  WS-OVERFLOW-FLAG    PIC X VALUE 'N'.
           
       PROCEDURE DIVISION.
       MAIN-EXCEPTION-DEMO.
           DISPLAY 'Exception Handler Demonstration'.
           PERFORM EXCEPTION-ONLY-EXAMPLES.
           PERFORM NOT-EXCEPTION-EXAMPLES.
           PERFORM BOTH-HANDLERS-EXAMPLES.
           PERFORM OVERFLOW-EXAMPLES.
           PERFORM NESTED-EXAMPLES.
           PERFORM TERMINATOR-EXAMPLES.
           STOP RUN.
           
       EXCEPTION-ONLY-EXAMPLES.
      *    CALL with ON EXCEPTION only - simple
           CALL 'SIMPLE-SERVICE' USING WS-REQUEST-ID
               ON EXCEPTION
                   DISPLAY 'Service failed'
               END-CALL.
           
      *    CALL with ON EXCEPTION - with error handling
           CALL 'VALIDATION-SERVICE' USING WS-TRANS-ID
               ON EXCEPTION
                   ADD 1 TO WS-ERROR-COUNT
                   MOVE 'Y' TO WS-FAILURE-FLAG
               END-CALL.
           
      *    CALL with ON EXCEPTION - multiple statements
           CALL 'PAYMENT-SERVICE' USING WS-AMOUNT
                                        WS-ACCOUNT-NUM
               ON EXCEPTION
                   MOVE 99 TO WS-RESPONSE-CODE
                   DISPLAY 'Payment service unavailable'
                   PERFORM LOG-ERROR
               END-CALL.
           
      *    CALL with ON EXCEPTION - nested PERFORM
           CALL 'COMPLEX-SERVICE' USING WS-TRANS-ID
               ON EXCEPTION
                   PERFORM HANDLE-SERVICE-FAILURE
               END-CALL.
           
      *    CALL with ON EXCEPTION - nested CALL
           CALL 'PRIMARY-SERVICE' USING WS-REQUEST-ID
               ON EXCEPTION
                   CALL 'FALLBACK-SERVICE' USING WS-REQUEST-ID
               END-CALL.
           
       NOT-EXCEPTION-EXAMPLES.
      *    CALL with NOT ON EXCEPTION only
           CALL 'SUCCESS-SERVICE' USING WS-REQUEST-ID
               NOT ON EXCEPTION
                   DISPLAY 'Service succeeded'
               END-CALL.
           
      *    CALL with NOT ON EXCEPTION - success handling
           CALL 'AUDIT-SERVICE' USING WS-TRANS-ID
               NOT ON EXCEPTION
                   MOVE 'Y' TO WS-SUCCESS-FLAG
                   MOVE 0 TO WS-RESPONSE-CODE
               END-CALL.
           
      *    CALL with NOT ON EXCEPTION - multiple statements
           CALL 'REPORTING-SERVICE' USING WS-TRANS-ID
                                          WS-AMOUNT
               NOT ON EXCEPTION
                   DISPLAY 'Report generated successfully'
                   MOVE 0 TO WS-ERROR-COUNT
                   PERFORM LOG-SUCCESS
               END-CALL.
           
       BOTH-HANDLERS-EXAMPLES.
      *    CALL with both ON EXCEPTION and NOT ON EXCEPTION
           CALL 'DUAL-HANDLER-SERVICE' USING WS-REQUEST-ID
               ON EXCEPTION
                   MOVE 1 TO WS-RESPONSE-CODE
                   DISPLAY 'Service call failed'
               NOT ON EXCEPTION
                   MOVE 0 TO WS-RESPONSE-CODE
                   DISPLAY 'Service call succeeded'
               END-CALL.
           
      *    CALL with both handlers - complex logic
           CALL 'TRANSACTION-SERVICE' USING WS-TRANS-ID
                                            WS-AMOUNT
                                            WS-ACCOUNT-NUM
               ON EXCEPTION
                   ADD 1 TO WS-ERROR-COUNT
                   MOVE 'Y' TO WS-FAILURE-FLAG
                   PERFORM ROLLBACK-TRANSACTION
               NOT ON EXCEPTION
                   MOVE 'Y' TO WS-SUCCESS-FLAG
                   PERFORM COMMIT-TRANSACTION
               END-CALL.
           
      *    CALL with both handlers - retry logic
           CALL 'RETRY-SERVICE' USING WS-REQUEST-ID
               ON EXCEPTION
                   ADD 1 TO WS-RETRY-COUNT
                   IF WS-RETRY-COUNT < WS-MAX-RETRIES
                       MOVE 'Y' TO WS-RETRY-FLAG
                   ELSE
                       DISPLAY 'Max retries exceeded'
                   END-IF
               NOT ON EXCEPTION
                   MOVE 0 TO WS-RETRY-COUNT
                   MOVE 'N' TO WS-RETRY-FLAG
               END-CALL.
           
      *    CALL with both handlers and RETURNING
           CALL 'CALCULATION-SERVICE' USING WS-AMOUNT
               RETURNING WS-RESPONSE-CODE
               ON EXCEPTION
                   MOVE 99 TO WS-RESPONSE-CODE
                   DISPLAY 'Calculation failed'
               NOT ON EXCEPTION
                   DISPLAY 'Calculation result: ' WS-RESPONSE-CODE
               END-CALL.
           
       OVERFLOW-EXAMPLES.
      *    CALL with ON OVERFLOW
           CALL 'OVERFLOW-SERVICE' USING WS-REQUEST-ID
               ON OVERFLOW
                   DISPLAY 'Service overflow occurred'
                   MOVE 'Y' TO WS-OVERFLOW-FLAG
               END-CALL.
           
      *    CALL with ON OVERFLOW - with recovery
           CALL 'BUFFER-SERVICE' USING WS-TRANS-ID
                                       WS-AMOUNT
               ON OVERFLOW
                   DISPLAY 'Buffer overflow detected'
                   PERFORM CLEAR-BUFFER
                   PERFORM RETRY-OPERATION
               END-CALL.
           
      *    CALL with both OVERFLOW and EXCEPTION
           CALL 'DUAL-ERROR-SERVICE' USING WS-REQUEST-ID
               ON OVERFLOW
                   DISPLAY 'Overflow condition'
                   MOVE 'Y' TO WS-OVERFLOW-FLAG
               ON EXCEPTION
                   DISPLAY 'Exception condition'
                   MOVE 'Y' TO WS-FAILURE-FLAG
               END-CALL.
           
       NESTED-EXAMPLES.
      *    CALL with nested IF in exception handler
           CALL 'CONDITIONAL-SERVICE' USING WS-TRANS-ID
               ON EXCEPTION
                   IF WS-ERROR-COUNT < 5
                       DISPLAY 'Recoverable error'
                       PERFORM RETRY-OPERATION
                   ELSE
                       DISPLAY 'Fatal error'
                       PERFORM ABORT-PROCESSING
                   END-IF
               END-CALL.
           
      *    CALL with nested EVALUATE in exception handler
           CALL 'MULTI-ERROR-SERVICE' USING WS-REQUEST-ID
               ON EXCEPTION
                   EVALUATE WS-ERROR-COUNT
                       WHEN 1
                           DISPLAY 'First error - retry'
                       WHEN 2
                           DISPLAY 'Second error - alert'
                       WHEN OTHER
                           DISPLAY 'Multiple errors - abort'
                   END-EVALUATE
               END-CALL.
           
      *    CALL with nested CALL in both handlers
           CALL 'ORCHESTRATION-SERVICE' USING WS-TRANS-ID
               ON EXCEPTION
                   CALL 'ERROR-LOGGER' USING WS-TRANS-ID
                                             WS-ERROR-COUNT
               NOT ON EXCEPTION
                   CALL 'SUCCESS-LOGGER' USING WS-TRANS-ID
               END-CALL.
           
       TERMINATOR-EXAMPLES.
      *    CALL with END-CALL terminator
           CALL 'EXPLICIT-TERMINATOR' USING WS-REQUEST-ID
               ON EXCEPTION
                   DISPLAY 'Error with explicit terminator'
               END-CALL.
           
      *    CALL with period terminator (no END-CALL)
           CALL 'IMPLICIT-TERMINATOR' USING WS-REQUEST-ID
               ON EXCEPTION
                   DISPLAY 'Error with period terminator'.
           
      *    CALL with END-CALL after both handlers
           CALL 'BOTH-HANDLERS-TERMINATED' USING WS-TRANS-ID
               ON EXCEPTION
                   MOVE 1 TO WS-RESPONSE-CODE
               NOT ON EXCEPTION
                   MOVE 0 TO WS-RESPONSE-CODE
               END-CALL.
           
      *    CALL inside IF with exception handler
           IF WS-AMOUNT > 1000.00
               CALL 'HIGH-VALUE-SERVICE' USING WS-AMOUNT
                   ON EXCEPTION
                       DISPLAY 'High value processing failed'
                   END-CALL
           END-IF.
           
      *    CALL inside PERFORM with exception handler
           PERFORM VARYING WS-RETRY-COUNT FROM 1 BY 1
               UNTIL WS-RETRY-COUNT > WS-MAX-RETRIES
               CALL 'BATCH-SERVICE' USING WS-RETRY-COUNT
                                          WS-TRANS-ID
                   ON EXCEPTION
                       DISPLAY 'Batch item failed'
                   NOT ON EXCEPTION
                       DISPLAY 'Batch item succeeded'
                   END-CALL
           END-PERFORM.
           
       HANDLE-SERVICE-FAILURE.
           ADD 1 TO WS-ERROR-COUNT.
           DISPLAY 'Handling service failure'.
           
       LOG-ERROR.
           DISPLAY 'Logging error to audit trail'.
           
       LOG-SUCCESS.
           DISPLAY 'Logging success to audit trail'.
           
       ROLLBACK-TRANSACTION.
           DISPLAY 'Rolling back transaction'.
           
       COMMIT-TRANSACTION.
           DISPLAY 'Committing transaction'.
           
       CLEAR-BUFFER.
           DISPLAY 'Clearing buffer'.
           
       RETRY-OPERATION.
           DISPLAY 'Retrying operation'.
           
       ABORT-PROCESSING.
           DISPLAY 'Aborting processing'.
           
       END PROGRAM CALL-EXCEPTION-HANDLERS-COMPLETE.
