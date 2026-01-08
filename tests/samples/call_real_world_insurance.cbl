      *****************************************************************
      * Real-World COBOL Application: Insurance Claims Processing
      * Demonstrates: Complete insurance system with realistic CALL
      * Use Case: Claims adjudication and payment processing
      *****************************************************************
       IDENTIFICATION DIVISION.
       PROGRAM-ID. CALL-REAL-WORLD-INSURANCE.
       
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-CLAIM-DATA.
           05  WS-CLAIM-NUMBER     PIC X(12).
           05  WS-POLICY-NUMBER    PIC X(15).
           05  WS-CLAIM-AMOUNT     PIC 9(9)V99 COMP-3.
           05  WS-CLAIM-DATE       PIC 9(8).
           05  WS-CLAIM-TYPE       PIC X(20).
           05  WS-CLAIM-STATUS     PIC X(10).
           
       01  WS-POLICY-DATA.
           05  WS-POLICY-HOLDER    PIC X(50).
           05  WS-POLICY-TYPE      PIC X(20).
           05  WS-COVERAGE-AMOUNT  PIC 9(9)V99 COMP-3.
           05  WS-DEDUCTIBLE       PIC 9(7)V99 COMP-3.
           05  WS-PREMIUM          PIC 9(7)V99 COMP-3.
           05  WS-POLICY-STATUS    PIC X(10).
           
       01  WS-CLAIMANT-DATA.
           05  WS-CLAIMANT-ID      PIC 9(10).
           05  WS-CLAIMANT-NAME    PIC X(50).
           05  WS-CLAIMANT-ADDRESS PIC X(100).
           05  WS-CLAIMANT-PHONE   PIC X(15).
           
       01  WS-ADJUDICATION-DATA.
           05  WS-APPROVED-AMOUNT  PIC 9(9)V99 COMP-3.
           05  WS-DENIED-AMOUNT    PIC 9(9)V99 COMP-3.
           05  WS-PENDING-AMOUNT   PIC 9(9)V99 COMP-3.
           05  WS-ADJUSTER-ID      PIC X(10).
           05  WS-DECISION-CODE    PIC 99.
           
       01  WS-PAYMENT-DATA.
           05  WS-PAYMENT-METHOD   PIC X(10).
           05  WS-PAYMENT-AMOUNT   PIC 9(9)V99 COMP-3.
           05  WS-PAYMENT-DATE     PIC 9(8).
           05  WS-CHECK-NUMBER     PIC X(10).
           
       01  WS-VALIDATION-FLAGS.
           05  WS-POLICY-VALID     PIC X VALUE 'N'.
           05  WS-COVERAGE-VALID   PIC X VALUE 'N'.
           05  WS-FRAUD-CHECK      PIC X VALUE 'N'.
           05  WS-DUPLICATE-CHECK  PIC X VALUE 'N'.
           
       01  WS-CONTROL-DATA.
           05  WS-RETURN-CODE      PIC 99.
           05  WS-ERROR-CODE       PIC 9(4).
           05  WS-WORKFLOW-STEP    PIC 99.
           
       PROCEDURE DIVISION.
       MAIN-CLAIMS-PROCESSING.
           DISPLAY 'Insurance Claims Processing System'.
           PERFORM INITIALIZE-CLAIM.
           PERFORM VALIDATE-POLICY.
           PERFORM VALIDATE-CLAIM.
           PERFORM FRAUD-SCREENING.
           PERFORM ADJUDICATE-CLAIM.
           PERFORM PROCESS-PAYMENT.
           PERFORM FINALIZE-CLAIM.
           STOP RUN.
           
       INITIALIZE-CLAIM.
      *    Generate claim number
           CALL 'GENERATE-CLAIM-NUMBER'
               RETURNING WS-CLAIM-NUMBER.
           
      *    Retrieve policy information
           CALL 'GET-POLICY-INFO' USING WS-POLICY-NUMBER
                                        WS-POLICY-HOLDER
                                        WS-POLICY-TYPE
                                        WS-COVERAGE-AMOUNT
                                        WS-DEDUCTIBLE
                                        WS-POLICY-STATUS
               RETURNING WS-RETURN-CODE.
           
      *    Initialize claim workflow
           CALL 'INIT-CLAIM-WORKFLOW' USING WS-CLAIM-NUMBER
                                            WS-POLICY-NUMBER
               RETURNING WS-WORKFLOW-STEP.
           
       VALIDATE-POLICY.
      *    Check policy active status
           CALL 'VALIDATE-POLICY-STATUS' USING WS-POLICY-NUMBER
                                               WS-CLAIM-DATE
               RETURNING WS-POLICY-VALID
               ON EXCEPTION
                   MOVE 'N' TO WS-POLICY-VALID
                   CALL 'LOG-VALIDATION-ERROR' USING 'POLICY-CHECK-FAIL'
                                                     WS-CLAIM-NUMBER
               END-CALL.
           
           IF WS-POLICY-VALID = 'N'
               CALL 'REJECT-CLAIM' USING WS-CLAIM-NUMBER
                                         'INVALID-POLICY'
               PERFORM ABORT-CLAIM-PROCESSING
           END-IF.
           
      *    Verify premium payments current
           CALL 'CHECK-PREMIUM-STATUS' USING WS-POLICY-NUMBER
               RETURNING WS-RETURN-CODE.
           
           IF WS-RETURN-CODE NOT = 0
               CALL 'SEND-PREMIUM-NOTICE' USING WS-POLICY-HOLDER
                                                WS-POLICY-NUMBER
               CALL 'SUSPEND-CLAIM' USING WS-CLAIM-NUMBER
                                          'PREMIUM-OVERDUE'
               PERFORM ABORT-CLAIM-PROCESSING
           END-IF.
           
      *    Validate coverage for claim type
           CALL 'VALIDATE-COVERAGE' USING WS-POLICY-NUMBER
                                          WS-CLAIM-TYPE
                                          WS-CLAIM-AMOUNT
               RETURNING WS-COVERAGE-VALID.
           
       VALIDATE-CLAIM.
      *    Check for duplicate claims
           CALL 'CHECK-DUPLICATE-CLAIM' USING WS-POLICY-NUMBER
                                              WS-CLAIM-TYPE
                                              WS-CLAIM-DATE
               RETURNING WS-DUPLICATE-CHECK
               ON EXCEPTION
                   DISPLAY 'Duplicate check service unavailable'
                   CALL 'MANUAL-REVIEW-REQUIRED' USING WS-CLAIM-NUMBER
               END-CALL.
           
           IF WS-DUPLICATE-CHECK = 'Y'
               CALL 'FLAG-DUPLICATE' USING WS-CLAIM-NUMBER
               CALL 'NOTIFY-ADJUSTER' USING WS-CLAIM-NUMBER
                                            'DUPLICATE-CLAIM'
           END-IF.
           
      *    Validate claim amount
           CALL 'VALIDATE-CLAIM-AMOUNT' USING WS-CLAIM-AMOUNT
                                              WS-COVERAGE-AMOUNT
                                              WS-DEDUCTIBLE
               RETURNING WS-RETURN-CODE.
           
      *    Retrieve claimant information
           CALL 'GET-CLAIMANT-INFO' USING WS-CLAIMANT-ID
                                          WS-CLAIMANT-NAME
                                          WS-CLAIMANT-ADDRESS
                                          WS-CLAIMANT-PHONE.
           
       FRAUD-SCREENING.
      *    Run fraud detection algorithms
           CALL 'FRAUD-DETECTION-CLAIMS'
                USING BY VALUE WS-CLAIM-NUMBER
                      BY VALUE WS-POLICY-NUMBER
                      BY VALUE WS-CLAIM-AMOUNT
                      BY VALUE WS-CLAIM-TYPE
                      BY REFERENCE WS-FRAUD-CHECK
               ON EXCEPTION
                   MOVE 'Y' TO WS-FRAUD-CHECK
                   CALL 'ESCALATE-TO-SIU' USING WS-CLAIM-NUMBER
               NOT ON EXCEPTION
                   IF WS-FRAUD-CHECK = 'Y'
                       CALL 'FRAUD-INVESTIGATION' USING WS-CLAIM-NUMBER
                                                        WS-POLICY-NUMBER
                       PERFORM ABORT-CLAIM-PROCESSING
                   END-IF
               END-CALL.
           
      *    Check claim history patterns
           CALL 'ANALYZE-CLAIM-HISTORY' USING WS-POLICY-NUMBER
                                              WS-CLAIMANT-ID
               RETURNING WS-RETURN-CODE.
           
       ADJUDICATE-CLAIM.
      *    Assign to adjuster
           CALL 'ASSIGN-ADJUSTER' USING WS-CLAIM-NUMBER
                                        WS-CLAIM-TYPE
               RETURNING WS-ADJUSTER-ID.
           
      *    Calculate approved amount
           CALL 'CALCULATE-BENEFIT' USING WS-CLAIM-AMOUNT
                                          WS-COVERAGE-AMOUNT
                                          WS-DEDUCTIBLE
                                          WS-POLICY-TYPE
               RETURNING WS-APPROVED-AMOUNT.
           
      *    Apply business rules
           EVALUATE WS-CLAIM-TYPE
               WHEN 'MEDICAL'
                   CALL 'APPLY-MEDICAL-RULES' USING WS-CLAIM-NUMBER
                                                    WS-APPROVED-AMOUNT
               WHEN 'DENTAL'
                   CALL 'APPLY-DENTAL-RULES' USING WS-CLAIM-NUMBER
                                                   WS-APPROVED-AMOUNT
               WHEN 'VISION'
                   CALL 'APPLY-VISION-RULES' USING WS-CLAIM-NUMBER
                                                   WS-APPROVED-AMOUNT
               WHEN 'PHARMACY'
                   CALL 'APPLY-PHARMACY-RULES' USING WS-CLAIM-NUMBER
                                                     WS-APPROVED-AMOUNT
               WHEN OTHER
                   CALL 'APPLY-GENERAL-RULES' USING WS-CLAIM-NUMBER
                                                    WS-APPROVED-AMOUNT
           END-EVALUATE.
           
      *    Make adjudication decision
           CALL 'MAKE-DECISION' USING WS-CLAIM-NUMBER
                                      WS-APPROVED-AMOUNT
                                      WS-ADJUSTER-ID
               RETURNING WS-DECISION-CODE
               ON EXCEPTION
                   CALL 'MANUAL-ADJUDICATION' USING WS-CLAIM-NUMBER
               END-CALL.
           
       PROCESS-PAYMENT.
      *    Determine payment method
           CALL 'DETERMINE-PAYMENT-METHOD' USING WS-POLICY-NUMBER
                                                 WS-CLAIMANT-ID
               RETURNING WS-PAYMENT-METHOD.
           
      *    Calculate final payment amount
           CALL 'CALCULATE-PAYMENT' USING WS-APPROVED-AMOUNT
                                          WS-DEDUCTIBLE
               RETURNING WS-PAYMENT-AMOUNT.
           
      *    Process payment based on method
           EVALUATE WS-PAYMENT-METHOD
               WHEN 'CHECK'
                   CALL 'ISSUE-CHECK' USING WS-CLAIMANT-ID
                                            WS-PAYMENT-AMOUNT
                       RETURNING WS-CHECK-NUMBER
               WHEN 'EFT'
                   CALL 'PROCESS-EFT' USING WS-CLAIMANT-ID
                                            WS-PAYMENT-AMOUNT
               WHEN 'DIRECT'
                   CALL 'DIRECT-PAYMENT' USING WS-CLAIMANT-ID
                                               WS-PAYMENT-AMOUNT
           END-EVALUATE.
           
      *    Record payment transaction
           CALL 'RECORD-PAYMENT' USING WS-CLAIM-NUMBER
                                       WS-PAYMENT-AMOUNT
                                       WS-PAYMENT-METHOD
                                       WS-PAYMENT-DATE.
           
       FINALIZE-CLAIM.
      *    Update claim status
           CALL 'UPDATE-CLAIM-STATUS' USING WS-CLAIM-NUMBER
                                            'PAID'
               RETURNING WS-RETURN-CODE.
           
      *    Generate EOB (Explanation of Benefits)
           CALL 'GENERATE-EOB' USING WS-CLAIM-NUMBER
                                     WS-POLICY-NUMBER
                                     WS-CLAIM-AMOUNT
                                     WS-APPROVED-AMOUNT
                                     WS-PAYMENT-AMOUNT.
           
      *    Send notifications
           CALL 'NOTIFY-CLAIMANT' USING WS-CLAIMANT-ID
                                        WS-CLAIM-NUMBER
                                        WS-PAYMENT-AMOUNT.
           
           CALL 'NOTIFY-PROVIDER' USING WS-CLAIM-NUMBER
                                        WS-PAYMENT-METHOD.
           
      *    Update policy statistics
           CALL 'UPDATE-POLICY-STATS' USING WS-POLICY-NUMBER
                                            WS-CLAIM-AMOUNT
                                            WS-PAYMENT-AMOUNT.
           
      *    Archive claim documents
           CALL 'ARCHIVE-CLAIM' USING WS-CLAIM-NUMBER
                                      WS-WORKFLOW-STEP.
           
           DISPLAY 'Claim processing completed'.
           
       ABORT-CLAIM-PROCESSING.
           DISPLAY 'Claim processing aborted'.
           CALL 'CLOSE-CLAIM-WORKFLOW' USING WS-CLAIM-NUMBER
                                             WS-WORKFLOW-STEP.
           STOP RUN.
           
       END PROGRAM CALL-REAL-WORLD-INSURANCE.
