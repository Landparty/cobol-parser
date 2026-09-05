      *****************************************************************
      * Real-World COBOL Example: Banking Application
      * Demonstrates: Dynamic CALL, CALL variations, error handling
      * Use Case: Account processing with multiple service calls
      *****************************************************************
       IDENTIFICATION DIVISION.
       PROGRAM-ID. BANK-TRANSACTION-PROCESSOR.
       
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-ACCOUNT-INFO.
           05  WS-ACCOUNT-NUMBER   PIC X(12).
           05  WS-ACCOUNT-TYPE     PIC X(10).
           05  WS-BALANCE          PIC 9(12)V99 COMP-3.
           05  WS-AVAILABLE-BAL    PIC 9(12)V99 COMP-3.
           05  WS-OVERDRAFT-LIMIT  PIC 9(12)V99 COMP-3.
           
       01  WS-TRANSACTION.
           05  WS-TRANS-TYPE       PIC X(10).
           05  WS-AMOUNT           PIC 9(10)V99 COMP-3.
           05  WS-DESCRIPTION      PIC X(50).
           05  WS-TIMESTAMP        PIC X(20).
           
       01  WS-PROCESSING-FLAGS.
           05  WS-AUTH-FLAG        PIC X VALUE 'N'.
           05  WS-FRAUD-FLAG       PIC X VALUE 'N'.
           05  WS-LIMIT-FLAG       PIC X VALUE 'N'.
           05  WS-SUCCESS-FLAG     PIC X VALUE 'N'.
           
       01  WS-ERROR-HANDLING.
           05  WS-ERROR-CODE       PIC 999.
           05  WS-ERROR-MESSAGE    PIC X(100).
           05  WS-RETRY-COUNT      PIC 9 VALUE 0.
           
       01  WS-SERVICE-PROGRAMS.
           05  WS-AUTH-SERVICE     PIC X(20) VALUE 'AUTH-SERVICE'.
           05  WS-FRAUD-DETECT     PIC X(20) VALUE 'FRAUD-DETECT'.
           05  WS-LIMIT-CHECK      PIC X(20) VALUE 'LIMIT-CHECK'.
           05  WS-POSTING-ENGINE   PIC X(20) VALUE 'POST-TRANS'.
           05  WS-NOTIFICATION     PIC X(20) VALUE 'NOTIFY-SVC'.
           
       01  WS-DYNAMIC-PROG-NAME    PIC X(20).
       
       PROCEDURE DIVISION.
       MAIN-TRANSACTION-PROCESS.
           DISPLAY 'Banking Transaction Processor Started'
           
           PERFORM LOAD-ACCOUNT-DATA
           PERFORM PROCESS-TRANSACTION
           PERFORM COMMIT-TRANSACTION
           
           DISPLAY 'Transaction Processing Complete'
           STOP RUN.
           
       LOAD-ACCOUNT-DATA.
           MOVE '123456789012' TO WS-ACCOUNT-NUMBER
           MOVE 'CHECKING' TO WS-ACCOUNT-TYPE
           MOVE 5000.00 TO WS-BALANCE
           MOVE 5000.00 TO WS-AVAILABLE-BAL
           MOVE 500.00 TO WS-OVERDRAFT-LIMIT.
           
       PROCESS-TRANSACTION.
           DISPLAY 'Processing transaction...'
           
           MOVE 'WITHDRAWAL' TO WS-TRANS-TYPE
           MOVE 150.00 TO WS-AMOUNT
           MOVE 'ATM Withdrawal' TO WS-DESCRIPTION
           
      *    CALL authorization service - static name
           CALL WS-AUTH-SERVICE USING WS-ACCOUNT-NUMBER
                                      WS-AMOUNT
                                      BY REFERENCE WS-AUTH-FLAG
                   ON EXCEPTION
                       MOVE 001 TO WS-ERROR-CODE
                     MOVE 'Auth service unavailable' TO WS-ERROR-MESSAGE
           
           IF WS-AUTH-FLAG = 'Y'
      *        CALL fraud detection - static name
               CALL WS-FRAUD-DETECT USING BY REFERENCE WS-ACCOUNT-NUMBER
                                          WS-TRANS-TYPE
                                          WS-AMOUNT
                                          WS-TIMESTAMP
                                          BY REFERENCE WS-FRAUD-FLAG
                   ON EXCEPTION
                       MOVE 002 TO WS-ERROR-CODE
                       DISPLAY 'Fraud detection service error'
               
               IF WS-FRAUD-FLAG = 'N'
      *            CALL limit checking service
                   CALL WS-LIMIT-CHECK USING WS-ACCOUNT-NUMBER
                                              WS-TRANS-TYPE
                                              WS-AMOUNT
                                              WS-AVAILABLE-BAL
                                              WS-OVERDRAFT-LIMIT
                       BY REFERENCE WS-LIMIT-FLAG
                       RETURNING WS-AVAILABLE-BAL
                       ON EXCEPTION
                           MOVE 003 TO WS-ERROR-CODE
                           MOVE 'Limit check failed' TO WS-ERROR-MESSAGE
                   
                   IF WS-LIMIT-FLAG = 'Y'
      *                Post transaction to ledger
                       CALL WS-POSTING-ENGINE 
                           USING BY REFERENCE WS-ACCOUNT-NUMBER
                                            WS-TRANS-TYPE
                                            WS-AMOUNT
                                            WS-DESCRIPTION
                           BY REFERENCE WS-SUCCESS-FLAG
                           RETURNING WS-BALANCE
                           ON EXCEPTION
                               MOVE 004 TO WS-ERROR-CODE
                               MOVE 'Transaction posting failed' 
                                   TO WS-ERROR-MESSAGE
                               DISPLAY WS-ERROR-MESSAGE
                           NOT ON EXCEPTION
                               MOVE 'Y' TO WS-SUCCESS-FLAG
                   ELSE
                       MOVE 'N' TO WS-SUCCESS-FLAG
                       MOVE 005 TO WS-ERROR-CODE
                       MOVE 'Insufficient funds' TO WS-ERROR-MESSAGE
                   END-IF
               ELSE
                   MOVE 'N' TO WS-SUCCESS-FLAG
                   MOVE 006 TO WS-ERROR-CODE
                 MOVE 'Fraudulent activity detected' TO WS-ERROR-MESSAGE
               END-IF
           ELSE
               MOVE 'N' TO WS-SUCCESS-FLAG
               MOVE 007 TO WS-ERROR-CODE
               MOVE 'Authorization failed' TO WS-ERROR-MESSAGE
           END-IF.
           
       COMMIT-TRANSACTION.
           IF WS-SUCCESS-FLAG = 'Y'
      *        Send notification
               CALL WS-NOTIFICATION USING WS-ACCOUNT-NUMBER
                                          WS-TRANS-TYPE
                                          WS-AMOUNT
                                          WS-BALANCE
               DISPLAY 'Transaction committed successfully'
           ELSE
               DISPLAY 'Transaction failed: ' WS-ERROR-CODE
               DISPLAY WS-ERROR-MESSAGE
           END-IF.
           
       END PROGRAM BANK-TRANSACTION-PROCESSOR.
