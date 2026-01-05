      *****************************************************************
      * Real-World COBOL Example: Insurance Claims Processing
      * Demonstrates: Complex CALL patterns with exception handling
      * Use Case: Multi-step claims verification and payment
      *****************************************************************
       IDENTIFICATION DIVISION.
       PROGRAM-ID. CLAIMS-PROCESSOR.
       
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-CLAIM-HEADER.
           05  WS-CLAIM-ID         PIC X(12).
           05  WS-POLICY-NUMBER    PIC X(10).
           05  WS-CLAIM-DATE       PIC 9(8).
           05  WS-CLAIM-AMOUNT     PIC 9(9)V99 COMP-3.
           05  WS-CLAIM-TYPE       PIC X(15).
               88  TYPE-MEDICAL     VALUE 'MEDICAL'.
               88  TYPE-PROPERTY    VALUE 'PROPERTY'.
               88  TYPE-AUTO        VALUE 'AUTO'.
               88  TYPE-LIABILITY   VALUE 'LIABILITY'.
           05  WS-CLAIM-STATUS     PIC X(2).
               88  STATUS-INITIAL   VALUE '01'.
               88  STATUS-VALIDATED VALUE '02'.
               88  STATUS-APPROVED  VALUE '03'.
               88  STATUS-PAID      VALUE '04'.
               88  STATUS-REJECTED  VALUE '99'.
           
       01  WS-CLAIMANT-INFO.
           05  WS-CLAIMANT-ID      PIC X(10).
           05  WS-CLAIMANT-NAME    PIC X(40).
           05  WS-CLAIMANT-EMAIL   PIC X(50).
           05  WS-CLAIMANT-PHONE   PIC X(15).
           
       01  WS-CLAIM-DETAILS.
           05  WS-INCIDENT-DATE    PIC 9(8).
           05  WS-INCIDENT-DESC    PIC X(200).
           05  WS-DAMAGE-AMOUNT    PIC 9(9)V99 COMP-3.
           05  WS-DEDUCTIBLE       PIC 9(7)V99 COMP-3.
           05  WS-COVERAGE-LIMIT   PIC 9(10)V99 COMP-3.
           
       01  WS-VERIFICATION-STATUS.
           05  WS-POLICY-VALID     PIC X VALUE 'N'.
           05  WS-COVERAGE-CHECK   PIC X VALUE 'N'.
           05  WS-FRAUD-CHECK      PIC X VALUE 'N'.
           05  WS-DOCUMENTATION-OK PIC X VALUE 'N'.
           05  WS-APPROVED-AMOUNT  PIC 9(9)V99 COMP-3.
           
       01  WS-INTERNAL-FLAGS.
           05  WS-RETRY-ATTEMPTS   PIC 9 VALUE 0.
           05  WS-MAX-RETRIES      PIC 9 VALUE 3.
           05  WS-CONTINUE-FLAG    PIC X VALUE 'Y'.
           05  WS-FINAL-STATUS     PIC 9.
           
       01  WS-SERVICE-REGISTRY.
           05  WS-POLICY-LOOKUP    PIC X(20) VALUE 'LOOKUP-POLICY'.
           05  WS-COVERAGE-CHECK   PIC X(20) VALUE 'CHECK-COVERAGE'.
           05  WS-FRAUD-CHECK-SVC  PIC X(20) VALUE 'DETECT-FRAUD'.
           05  WS-VALIDATE-DOCS    PIC X(20) VALUE 'VALIDATE-DOCS'.
           05  WS-APPROVAL-SVC     PIC X(20) VALUE 'GET-APPROVAL'.
           05  WS-PAYMENT-SVC      PIC X(20) VALUE 'PROCESS-PAYMENT'.
           05  WS-NOTIFICATION-SVC PIC X(20) VALUE 'NOTIFY-CLAIMANT'.
           
       01  WS-ERROR-HANDLING.
           05  WS-ERROR-CODE       PIC 999.
           05  WS-ERROR-MSG        PIC X(100).
           05  WS-RECOVERY-FLAG    PIC X VALUE 'N'.
           
       PROCEDURE DIVISION.
       MAIN-CLAIMS-PROCESS.
           DISPLAY 'Insurance Claims Processor Started'
           PERFORM LOAD-CLAIM-DATA
           PERFORM VALIDATE-CLAIM-PROCESS
           DISPLAY 'Claims Processing Complete'
           STOP RUN.
           
       LOAD-CLAIM-DATA.
           MOVE 'CLM-2024-00001' TO WS-CLAIM-ID
           MOVE 'POL-5000123456' TO WS-POLICY-NUMBER
           MOVE 20240115 TO WS-CLAIM-DATE
           MOVE 'MEDICAL' TO WS-CLAIM-TYPE
           MOVE '01' TO WS-CLAIM-STATUS
           MOVE 'CLT-000042' TO WS-CLAIMANT-ID
           MOVE 'Jane Smith' TO WS-CLAIMANT-NAME
           MOVE 'jane.smith@email.com' TO WS-CLAIMANT-EMAIL
           MOVE '555-123-4567' TO WS-CLAIMANT-PHONE
           MOVE 20240110 TO WS-INCIDENT-DATE
           MOVE 'Emergency room visit' TO WS-INCIDENT-DESC
           MOVE 5000.00 TO WS-DAMAGE-AMOUNT
           MOVE 250.00 TO WS-DEDUCTIBLE
           MOVE 50000.00 TO WS-COVERAGE-LIMIT.
           
       VALIDATE-CLAIM-PROCESS.
           PERFORM POLICY-VALIDATION
           
           IF WS-POLICY-VALID = 'Y'
               PERFORM COVERAGE-VALIDATION
               
               IF WS-COVERAGE-CHECK = 'Y'
                   PERFORM FRAUD-DETECTION
                   
                   IF WS-FRAUD-CHECK = 'Y'
                       PERFORM DOCUMENT-VALIDATION
                       
                       IF WS-DOCUMENTATION-OK = 'Y'
                           PERFORM CLAIM-APPROVAL
                           
                           IF WS-APPROVED-AMOUNT > 0
                               PERFORM PROCESS-PAYMENT
                               PERFORM SEND-NOTIFICATION
                           END-IF
                       ELSE
                           PERFORM REJECT-CLAIM
                       END-IF
                   ELSE
                       PERFORM REJECT-CLAIM
                   END-IF
               ELSE
                   PERFORM REJECT-CLAIM
               END-IF
           ELSE
               PERFORM REJECT-CLAIM
           END-IF.
           
       POLICY-VALIDATION.
           DISPLAY 'Validating policy...'
           
           PERFORM VARYING WS-RETRY-ATTEMPTS FROM 1 BY 1
               UNTIL WS-RETRY-ATTEMPTS > WS-MAX-RETRIES
               
               CALL WS-POLICY-LOOKUP USING WS-POLICY-NUMBER
                                           WS-CLAIM-DATE
                                      BY REFERENCE WS-POLICY-VALID
                   ON EXCEPTION
                       MOVE 001 TO WS-ERROR-CODE
                       MOVE 'Policy lookup failed' TO WS-ERROR-MSG
                       IF WS-RETRY-ATTEMPTS < WS-MAX-RETRIES
                           CONTINUE
                       ELSE
                           MOVE 'N' TO WS-POLICY-VALID
                       END-IF
                   NOT ON EXCEPTION
                       MOVE WS-MAX-RETRIES TO WS-RETRY-ATTEMPTS
           END-PERFORM.
           
       COVERAGE-VALIDATION.
           DISPLAY 'Checking coverage...'
           
      *    CALL coverage check with multiple conditions
           CALL WS-COVERAGE-CHECK USING BY REFERENCE WS-POLICY-NUMBER
                                             WS-CLAIM-TYPE
                                             WS-CLAIM-AMOUNT
                                             WS-COVERAGE-LIMIT
                                        BY REFERENCE WS-COVERAGE-CHECK
                   RETURNING WS-APPROVED-AMOUNT
                   ON EXCEPTION
                       MOVE 002 TO WS-ERROR-CODE
                       MOVE 'Coverage check failed' TO WS-ERROR-MSG
                       MOVE 'N' TO WS-COVERAGE-CHECK.
           
       FRAUD-DETECTION.
           DISPLAY 'Checking for fraud...'
           
      *    CALL fraud detection service
           CALL WS-FRAUD-CHECK-SVC USING BY REFERENCE WS-CLAIM-ID
                                             WS-CLAIMANT-ID
                                             WS-CLAIM-AMOUNT
                                             WS-INCIDENT-DATE
                                        BY REFERENCE WS-FRAUD-CHECK
                   ON EXCEPTION
                       MOVE 003 TO WS-ERROR-CODE
                       MOVE 'Fraud check failed' TO WS-ERROR-MSG
                       MOVE 'N' TO WS-FRAUD-CHECK.
           
       DOCUMENT-VALIDATION.
           DISPLAY 'Validating documentation...'
           
      *    CALL documentation validator
           CALL WS-VALIDATE-DOCS USING BY REFERENCE WS-CLAIM-ID
                                             WS-CLAIM-TYPE
                                             WS-INCIDENT-DATE
                                        BY REFERENCE WS-DOCUMENTATION-OK
                   RETURNING WS-FINAL-STATUS
                   ON EXCEPTION
                       MOVE 004 TO WS-ERROR-CODE
                       MOVE 'Document validation failed' TO WS-ERROR-MSG
                       MOVE 'N' TO WS-DOCUMENTATION-OK.
           
       CLAIM-APPROVAL.
           DISPLAY 'Getting claim approval...'
           
      *    CALL approval service
           CALL WS-APPROVAL-SVC USING BY REFERENCE WS-CLAIM-ID
                                          WS-DAMAGE-AMOUNT
                                          WS-DEDUCTIBLE
                                          WS-COVERAGE-LIMIT
                                     BY REFERENCE WS-APPROVED-AMOUNT
                   ON EXCEPTION
                       MOVE 005 TO WS-ERROR-CODE
                       MOVE 'Approval failed' TO WS-ERROR-MSG
                       MOVE 0 TO WS-APPROVED-AMOUNT.
           
       PROCESS-PAYMENT.
           DISPLAY 'Processing payment...'
           
      *    CALL payment processing service
           CALL WS-PAYMENT-SVC USING BY REFERENCE WS-CLAIM-ID
                                          WS-CLAIMANT-ID
                                          WS-APPROVED-AMOUNT
                                          WS-POLICY-NUMBER
                                     BY REFERENCE WS-CONTINUE-FLAG
                   ON EXCEPTION
                       MOVE 006 TO WS-ERROR-CODE
                       MOVE 'Payment processing failed' TO WS-ERROR-MSG
                       MOVE 'N' TO WS-CONTINUE-FLAG
                   NOT ON EXCEPTION
                       MOVE '04' TO WS-CLAIM-STATUS.
           
       SEND-NOTIFICATION.
           DISPLAY 'Sending notification to claimant...'
           
      *    CALL notification service
           CALL WS-NOTIFICATION-SVC USING BY VALUE WS-CLAIMANT-NAME
                                           BY REFERENCE WS-CLAIMANT-EMAIL
                                                        WS-CLAIMANT-PHONE
                                                        WS-APPROVED-AMOUNT
                   ON EXCEPTION
                       DISPLAY 'Notification failed'.
           
       REJECT-CLAIM.
           DISPLAY 'Rejecting claim...'
           MOVE '99' TO WS-CLAIM-STATUS
           DISPLAY 'Error Code: ' WS-ERROR-CODE
           DISPLAY 'Error Message: ' WS-ERROR-MSG.
           
       END PROGRAM CLAIMS-PROCESSOR.
