      *****************************************************************
      * Real-World COBOL Application: Banking Transaction System
      * Demonstrates: Complete banking application with realistic CALL
      * Use Case: ATM/Online banking transaction processing
      *****************************************************************
       IDENTIFICATION DIVISION.
       PROGRAM-ID. CALL-REAL-WORLD-BANKING.
       
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-ACCOUNT-DATA.
           05  WS-ACCOUNT-NUMBER   PIC 9(10).
           05  WS-ACCOUNT-TYPE     PIC X(10).
           05  WS-CURRENT-BALANCE  PIC 9(11)V99 COMP-3.
           05  WS-AVAILABLE-BAL    PIC 9(11)V99 COMP-3.
           
       01  WS-TRANSACTION-DATA.
           05  WS-TRANS-ID         PIC X(16).
           05  WS-TRANS-TYPE       PIC X(10).
           05  WS-TRANS-AMOUNT     PIC 9(9)V99 COMP-3.
           05  WS-TRANS-DATE       PIC 9(8).
           05  WS-TRANS-TIME       PIC 9(6).
           
       01  WS-CUSTOMER-DATA.
           05  WS-CUSTOMER-ID      PIC 9(10).
           05  WS-CUSTOMER-NAME    PIC X(50).
           05  WS-CUSTOMER-STATUS  PIC X(10).
           05  WS-VIP-FLAG         PIC X VALUE 'N'.
           
       01  WS-VALIDATION-FLAGS.
           05  WS-AUTH-FLAG        PIC X VALUE 'N'.
           05  WS-FRAUD-FLAG       PIC X VALUE 'N'.
           05  WS-LIMIT-FLAG       PIC X VALUE 'N'.
           05  WS-BALANCE-FLAG     PIC X VALUE 'N'.
           
       01  WS-SERVICE-RESULTS.
           05  WS-RETURN-CODE      PIC 99.
           05  WS-ERROR-CODE       PIC 9(4).
           05  WS-STATUS-MESSAGE   PIC X(100).
           05  WS-APPROVAL-CODE    PIC X(12).
           
       01  WS-RETRY-CONTROL.
           05  WS-RETRY-COUNT      PIC 9 VALUE 0.
           05  WS-MAX-RETRIES      PIC 9 VALUE 3.
           
       PROCEDURE DIVISION.
       MAIN-BANKING-PROCESS.
           DISPLAY 'Banking Transaction Processing System'.
           PERFORM INITIALIZE-TRANSACTION.
           PERFORM VALIDATE-CUSTOMER.
           PERFORM AUTHENTICATE-TRANSACTION.
           PERFORM FRAUD-DETECTION.
           PERFORM PROCESS-TRANSACTION.
           PERFORM FINALIZE-TRANSACTION.
           STOP RUN.
           
       INITIALIZE-TRANSACTION.
      *    Generate unique transaction ID
           CALL 'GENERATE-TRANS-ID'
               RETURNING WS-TRANS-ID.
           
      *    Get current timestamp
           CALL 'GET-TIMESTAMP' USING WS-TRANS-DATE
                                      WS-TRANS-TIME.
           
      *    Initialize audit trail
           CALL 'INIT-AUDIT-TRAIL' USING WS-TRANS-ID
                                         WS-CUSTOMER-ID
                                         WS-TRANS-TYPE.
           
       VALIDATE-CUSTOMER.
      *    Retrieve customer information
           CALL 'GET-CUSTOMER-INFO' USING WS-CUSTOMER-ID
                                          WS-CUSTOMER-NAME
                                          WS-CUSTOMER-STATUS
                                          WS-VIP-FLAG
               RETURNING WS-RETURN-CODE.
           
      *    Check customer status
           IF WS-RETURN-CODE NOT = 0
               CALL 'LOG-ERROR' USING 'CUSTOMER-NOT-FOUND'
                                      WS-CUSTOMER-ID
               PERFORM ABORT-TRANSACTION
           END-IF.
           
      *    Validate account ownership
           CALL 'VALIDATE-ACCOUNT-OWNER' 
                USING WS-CUSTOMER-ID
                      WS-ACCOUNT-NUMBER
               RETURNING WS-RETURN-CODE
               ON EXCEPTION
                   DISPLAY 'Account validation service unavailable'
                   PERFORM RETRY-VALIDATION
               END-CALL.
           
      *    Get account details
           CALL 'GET-ACCOUNT-DETAILS'
                USING BY VALUE WS-ACCOUNT-NUMBER
                      BY REFERENCE WS-ACCOUNT-TYPE
                      BY REFERENCE WS-CURRENT-BALANCE
                      BY REFERENCE WS-AVAILABLE-BAL
               RETURNING WS-RETURN-CODE.
           
       AUTHENTICATE-TRANSACTION.
      *    Verify transaction authorization
           CALL 'VERIFY-AUTHORIZATION'
                USING WS-CUSTOMER-ID
                      WS-TRANS-TYPE
                      WS-TRANS-AMOUNT
               RETURNING WS-AUTH-FLAG
               ON EXCEPTION
                   MOVE 'N' TO WS-AUTH-FLAG
                   CALL 'LOG-AUTH-FAILURE' USING WS-TRANS-ID
               END-CALL.
           
      *    Check if authorization required
           IF WS-AUTH-FLAG = 'N'
               DISPLAY 'Transaction not authorized'
               CALL 'SEND-ALERT' USING WS-CUSTOMER-ID
                                       'UNAUTHORIZED-ATTEMPT'
               PERFORM ABORT-TRANSACTION
           END-IF.
           
      *    Validate transaction limits
           CALL 'CHECK-TRANSACTION-LIMITS'
                USING WS-ACCOUNT-NUMBER
                      WS-TRANS-TYPE
                      WS-TRANS-AMOUNT
                      WS-TRANS-DATE
               RETURNING WS-LIMIT-FLAG.
           
       FRAUD-DETECTION.
      *    Run fraud detection algorithms
           CALL 'FRAUD-DETECTION-SERVICE'
                USING BY VALUE WS-ACCOUNT-NUMBER
                      BY VALUE WS-TRANS-TYPE
                      BY VALUE WS-TRANS-AMOUNT
                      BY VALUE WS-TRANS-DATE
                      BY VALUE WS-TRANS-TIME
                      BY REFERENCE WS-FRAUD-FLAG
               ON EXCEPTION
                   DISPLAY 'Fraud detection service error'
                   MOVE 'Y' TO WS-FRAUD-FLAG
               NOT ON EXCEPTION
                   IF WS-FRAUD-FLAG = 'Y'
                       CALL 'FRAUD-ALERT' USING WS-ACCOUNT-NUMBER
                                                WS-TRANS-ID
                   END-IF
               END-CALL.
           
      *    Check fraud flag
           IF WS-FRAUD-FLAG = 'Y'
               CALL 'FREEZE-ACCOUNT' USING WS-ACCOUNT-NUMBER
               CALL 'NOTIFY-SECURITY' USING WS-CUSTOMER-ID
                                            WS-TRANS-ID
               PERFORM ABORT-TRANSACTION
           END-IF.
           
       PROCESS-TRANSACTION.
      *    Determine transaction type and process accordingly
           EVALUATE WS-TRANS-TYPE
               WHEN 'WITHDRAWAL'
                   PERFORM PROCESS-WITHDRAWAL
               WHEN 'DEPOSIT'
                   PERFORM PROCESS-DEPOSIT
               WHEN 'TRANSFER'
                   PERFORM PROCESS-TRANSFER
               WHEN 'PAYMENT'
                   PERFORM PROCESS-PAYMENT
               WHEN OTHER
                   CALL 'LOG-ERROR' USING 'INVALID-TRANS-TYPE'
                                          WS-TRANS-TYPE
           END-EVALUATE.
           
       PROCESS-WITHDRAWAL.
      *    Check sufficient balance
           CALL 'CHECK-BALANCE' USING WS-ACCOUNT-NUMBER
                                      WS-TRANS-AMOUNT
               RETURNING WS-BALANCE-FLAG.
           
           IF WS-BALANCE-FLAG = 'N'
               CALL 'INSUFFICIENT-FUNDS-HANDLER'
                    USING WS-ACCOUNT-NUMBER
                          WS-TRANS-AMOUNT
               PERFORM ABORT-TRANSACTION
           END-IF.
           
      *    Process withdrawal with retry logic
           PERFORM VARYING WS-RETRY-COUNT FROM 1 BY 1
               UNTIL WS-RETRY-COUNT > WS-MAX-RETRIES
                   OR WS-RETURN-CODE = 0
               CALL 'DEBIT-ACCOUNT' USING WS-ACCOUNT-NUMBER
                                          WS-TRANS-AMOUNT
                                          WS-TRANS-ID
                   RETURNING WS-RETURN-CODE
                   ON EXCEPTION
                       ADD 1 TO WS-RETRY-COUNT
                       CALL 'WAIT-AND-RETRY' USING WS-RETRY-COUNT
                   NOT ON EXCEPTION
                       MOVE 0 TO WS-RETURN-CODE
                   END-CALL
           END-PERFORM.
           
      *    Dispense cash (ATM scenario)
           IF WS-RETURN-CODE = 0
               CALL 'DISPENSE-CASH' USING WS-TRANS-AMOUNT
                   ON EXCEPTION
                       CALL 'REVERSE-TRANSACTION' USING WS-TRANS-ID
                       CALL 'CREDIT-ACCOUNT' USING WS-ACCOUNT-NUMBER
                                                   WS-TRANS-AMOUNT
                   END-CALL
           END-IF.
           
       PROCESS-DEPOSIT.
      *    Validate deposit amount
           CALL 'VALIDATE-DEPOSIT-AMOUNT' USING WS-TRANS-AMOUNT
               RETURNING WS-RETURN-CODE.
           
      *    Credit account
           CALL 'CREDIT-ACCOUNT' USING WS-ACCOUNT-NUMBER
                                       WS-TRANS-AMOUNT
                                       WS-TRANS-ID
               RETURNING WS-RETURN-CODE
               ON EXCEPTION
                   CALL 'LOG-ERROR' USING 'DEPOSIT-FAILED'
                                          WS-TRANS-ID
               END-CALL.
           
      *    Generate deposit receipt
           CALL 'GENERATE-RECEIPT' USING WS-TRANS-ID
                                         WS-ACCOUNT-NUMBER
                                         WS-TRANS-AMOUNT
                                         'DEPOSIT'.
           
       PROCESS-TRANSFER.
      *    Additional transfer-specific processing would go here
           CALL 'TRANSFER-FUNDS' USING WS-ACCOUNT-NUMBER
                                       WS-TRANS-AMOUNT
               RETURNING WS-RETURN-CODE.
           
       PROCESS-PAYMENT.
      *    Process bill payment
           CALL 'PROCESS-BILL-PAYMENT' USING WS-ACCOUNT-NUMBER
                                             WS-TRANS-AMOUNT
               RETURNING WS-RETURN-CODE.
           
       FINALIZE-TRANSACTION.
      *    Update account balance
           CALL 'UPDATE-ACCOUNT-BALANCE' USING WS-ACCOUNT-NUMBER
               RETURNING WS-CURRENT-BALANCE.
           
      *    Record transaction history
           CALL 'RECORD-TRANSACTION' USING WS-TRANS-ID
                                           WS-ACCOUNT-NUMBER
                                           WS-TRANS-TYPE
                                           WS-TRANS-AMOUNT
                                           WS-TRANS-DATE
                                           WS-TRANS-TIME.
           
      *    Send confirmation
           IF WS-VIP-FLAG = 'Y'
               CALL 'SEND-VIP-CONFIRMATION' USING WS-CUSTOMER-ID
                                                  WS-TRANS-ID
           ELSE
               CALL 'SEND-STANDARD-CONFIRMATION' USING WS-CUSTOMER-ID
                                                       WS-TRANS-ID
           END-IF.
           
      *    Update customer statistics
           CALL 'UPDATE-CUSTOMER-STATS' USING WS-CUSTOMER-ID
                                              WS-TRANS-TYPE
                                              WS-TRANS-AMOUNT.
           
      *    Close audit trail
           CALL 'CLOSE-AUDIT-TRAIL' USING WS-TRANS-ID
                                          WS-RETURN-CODE.
           
           DISPLAY 'Transaction completed successfully'.
           
       RETRY-VALIDATION.
           DISPLAY 'Retrying validation'.
           
       ABORT-TRANSACTION.
           DISPLAY 'Transaction aborted'.
           CALL 'ROLLBACK-TRANSACTION' USING WS-TRANS-ID.
           STOP RUN.
           
       END PROGRAM CALL-REAL-WORLD-BANKING.
