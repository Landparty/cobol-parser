      *****************************************************************
      * Real-World COBOL Example: CALL with Comments
      * Demonstrates: CALL statements with comments in various positions
      * Use Case: Well-documented service integration layer
      *****************************************************************
       IDENTIFICATION DIVISION.
       PROGRAM-ID. CALL-WITH-COMMENTS.
       
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-TRANSACTION-DATA.
           05  WS-TRANS-ID         PIC X(12).
           05  WS-AMOUNT           PIC 9(9)V99 COMP-3.
           05  WS-ACCOUNT-NUM      PIC 9(10).
           05  WS-RESULT           PIC 99.
           
       01  WS-SERVICE-DATA.
           05  WS-SERVICE-NAME     PIC X(30).
           05  WS-STATUS-CODE      PIC 99.
           05  WS-ERROR-MSG        PIC X(100).
           
       PROCEDURE DIVISION.
       MAIN-SECTION.
           DISPLAY 'CALL Statements with Comments'.
           PERFORM PROCESS-WITH-COMMENTS.
           STOP RUN.
           
       PROCESS-WITH-COMMENTS.
      *    Comment before CALL statement
      *    This validates the transaction before processing
           CALL 'VALIDATE-TRANSACTION' USING WS-TRANS-ID.
           
      *    CALL with comment after program name
           CALL 'PROCESS-PAYMENT'  
      *         Service processes payment and returns status
                USING WS-AMOUNT
                      WS-ACCOUNT-NUM.
           
      *    CALL with comment before USING clause
           CALL 'CHECK-BALANCE'
      *         Parameters: account number and result code
                USING WS-ACCOUNT-NUM
                      WS-RESULT.
           
      *    CALL with comment between USING and parameters
           CALL 'UPDATE-ACCOUNT'
                USING
      *              First parameter is account number
                      WS-ACCOUNT-NUM
      *              Second parameter is transaction amount
                      WS-AMOUNT.
           
      *    CALL with comment in middle of parameter list
           CALL 'COMPLEX-PROCESSING'
                USING WS-TRANS-ID
      *              Account validation parameter
                      WS-ACCOUNT-NUM
      *              Amount to process
                      WS-AMOUNT
      *              Result code returned
                      WS-RESULT.
           
      *    CALL with comment before RETURNING
           CALL 'CALCULATE-FEE'
                USING WS-AMOUNT
      *         Returns the calculated fee amount
                RETURNING WS-RESULT.
           
      *    CALL with comment before ON EXCEPTION
           CALL 'RISKY-OPERATION'
                USING WS-TRANS-ID
      *         Exception handler for service failures
                ON EXCEPTION
                    DISPLAY 'Service call failed'
                END-CALL.
           
      *    CALL with comment after period
           CALL 'LOG-TRANSACTION' USING WS-TRANS-ID.
      *    Transaction logged successfully
           
      *    Multi-line CALL with comments on each line
      *    This is a comprehensive service call
           CALL 'COMPREHENSIVE-SERVICE'
      *         Transaction identifier
                USING WS-TRANS-ID
      *              Account number for validation
                      WS-ACCOUNT-NUM
      *              Transaction amount
                      WS-AMOUNT
      *         Return status code
                RETURNING WS-STATUS-CODE
      *         Handle any exceptions
                ON EXCEPTION
      *              Log the error
                    MOVE 'ERROR' TO WS-ERROR-MSG
                    DISPLAY WS-ERROR-MSG
      *         Success path
                NOT ON EXCEPTION
      *              Log success
                    MOVE 'SUCCESS' TO WS-ERROR-MSG
                END-CALL.
           
      *    CALL with inline comments (COBOL 2002 style if supported)
           CALL 'MODERN-SERVICE' USING WS-TRANS-ID
                                       WS-AMOUNT.
           
      *    CALL inside IF with comments
      *    Check if amount exceeds threshold
           IF WS-AMOUNT > 5000.00
      *        High value transaction requires special processing
               CALL 'HIGH-VALUE-ALERT'
                    USING WS-TRANS-ID
                          WS-AMOUNT
           END-IF.
           
      *    CALL with comment before dynamic program name
      *    Service name is determined at runtime
           MOVE 'DYNAMIC-SERVICE' TO WS-SERVICE-NAME
           CALL WS-SERVICE-NAME
      *         Pass transaction data
                USING WS-TRANS-ID
                      WS-AMOUNT.
           
      *    CALL with extensive documentation comments
      ******************************************************************
      * Service: AUDIT-TRAIL-SERVICE
      * Purpose: Records all transaction details for compliance
      * Parameters:
      *   - WS-TRANS-ID: Transaction identifier
      *   - WS-ACCOUNT-NUM: Account being processed
      *   - WS-AMOUNT: Transaction amount
      *   - WS-STATUS-CODE: Processing status
      * Returns: WS-RESULT (0=success, non-zero=error)
      ******************************************************************
           CALL 'AUDIT-TRAIL-SERVICE'
                USING WS-TRANS-ID
                      WS-ACCOUNT-NUM
                      WS-AMOUNT
                      WS-STATUS-CODE
                RETURNING WS-RESULT.
           
      *    CALL with comment before END-CALL
           CALL 'CLEANUP-SERVICE'
                USING WS-TRANS-ID
                ON EXCEPTION
                    DISPLAY 'Cleanup failed'
      *              End of exception handler
                END-CALL.
           
      *    CALL with comment before BY REFERENCE
           CALL 'REFERENCE-SERVICE'
                USING
      *              Pass by reference for modification
                      BY REFERENCE WS-AMOUNT
      *              Pass by value for read-only
                      BY VALUE WS-TRANS-ID.
           
      *    CALL inside PERFORM with comments
      *    Process batch of transactions
           PERFORM VARYING WS-RESULT FROM 1 BY 1
               UNTIL WS-RESULT > 10
      *        Call service for each iteration
               CALL 'BATCH-PROCESSOR'
                    USING WS-RESULT
                          WS-TRANS-ID
           END-PERFORM.
           
      *    CALL with comment explaining business logic
      *    Per regulatory requirement XYZ-123, all transactions
      *    over $10,000 must be reported to compliance system
           IF WS-AMOUNT > 10000.00
               CALL 'COMPLIANCE-REPORT'
                    USING WS-TRANS-ID
                          WS-ACCOUNT-NUM
                          WS-AMOUNT
           END-IF.
           
       END PROGRAM CALL-WITH-COMMENTS.
