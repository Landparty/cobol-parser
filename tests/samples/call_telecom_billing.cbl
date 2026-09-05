      *****************************************************************
      * Real-World COBOL Example: Telecommunications Billing System
      * Demonstrates: Complex CALL scenarios, nested processing
      * Use Case: Usage calculation, rating, and bill generation
      *****************************************************************
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TELECOM-BILLING-ENGINE.
       
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-ACCOUNT-MASTER.
           05  WS-ACCOUNT-ID       PIC X(12).
           05  WS-PHONE-NUMBER     PIC X(15).
           05  WS-CUSTOMER-NAME    PIC X(40).
           05  WS-BILLING-CYCLE    PIC 99.
           05  WS-PLAN-TYPE        PIC X(10).
               88  PREPAID-PLAN    VALUE 'PREPAID'.
               88  POSTPAID-PLAN   VALUE 'POSTPAID'.
           05  WS-BALANCE          PIC S9(8)V99 COMP-3.
           05  WS-CREDIT-LIMIT     PIC 9(8)V99 COMP-3.
           
       01  WS-USAGE-DETAIL.
           05  WS-CALL-MINUTES     PIC 9(8) COMP-3.
           05  WS-SMS-COUNT        PIC 9(8) COMP-3.
           05  WS-DATA-USAGE-MB    PIC 9(8)V99 COMP-3.
           05  WS-LOCAL-CALLS      PIC 9(8) COMP-3.
           05  WS-LONG-DISTANCE    PIC 9(8) COMP-3.
           05  WS-ROAMING-USAGE    PIC 9(8)V99 COMP-3.
           
       01  WS-CHARGE-BREAKDOWN.
           05  WS-BASE-CHARGE      PIC 9(7)V99 COMP-3.
           05  WS-CALL-CHARGES     PIC 9(7)V99 COMP-3.
           05  WS-SMS-CHARGES      PIC 9(7)V99 COMP-3.
           05  WS-DATA-CHARGES     PIC 9(7)V99 COMP-3.
           05  WS-ROAMING-CHARGES  PIC 9(7)V99 COMP-3.
           05  WS-SURCHARGES       PIC 9(7)V99 COMP-3.
           05  WS-TAXES            PIC 9(7)V99 COMP-3.
           05  WS-TOTAL-CHARGES    PIC 9(9)V99 COMP-3.
           05  WS-AMOUNT-DUE       PIC 9(9)V99 COMP-3.
           
       01  WS-BILL-METADATA.
           05  WS-BILL-ID          PIC X(12).
           05  WS-BILL-DATE        PIC 9(8).
           05  WS-DUE-DATE         PIC 9(8).
           05  WS-PERIOD-START     PIC 9(8).
           05  WS-PERIOD-END       PIC 9(8).
           05  WS-BILL-STATUS      PIC X(2).
               88  DRAFT            VALUE '01'.
               88  GENERATED        VALUE '02'.
               88  SENT             VALUE '03'.
               88  PAID             VALUE '04'.
           
       01  WS-DISCOUNTS-PROMOTIONS.
           05  WS-LOYALTY-DISCOUNT PIC 9(5)V99 COMP-3.
           05  WS-PROMOTIONAL-CODE PIC X(10).
           05  WS-PROMO-DISCOUNT   PIC 9(5)V99 COMP-3.
           05  WS-FAMILY-PLAN-DISC PIC 9(5)V99 COMP-3.
           05  WS-TOTAL-DISCOUNTS  PIC 9(7)V99 COMP-3.
           
       01  WS-CONTROL-PROCESSING.
           05  WS-VALIDATION-OK    PIC X VALUE 'N'.
           05  WS-CALCULATION-OK   PIC X VALUE 'N'.
           05  WS-ADJUSTMENT-OK    PIC X VALUE 'N'.
           05  WS-GENERATION-OK    PIC X VALUE 'N'.
           05  WS-ERROR-CODE       PIC 999.
           05  WS-ERROR-MSG        PIC X(100).
           
       01  WS-SERVICE-DIRECTORY.
           05  WS-USAGE-RETRIEVAL  PIC X(20) VALUE 'GET-USAGE-DETAIL'.
           05  WS-RATE-LOOKUP      PIC X(20) VALUE 'LOOKUP-RATES'.
           05  WS-CALL-RATING      PIC X(20) VALUE 'RATE-CALLS'.
           05  WS-SMS-RATING       PIC X(20) VALUE 'RATE-SMS'.
           05  WS-DATA-RATING      PIC X(20) VALUE 'RATE-DATA'.
           05  WS-ROAMING-RATING   PIC X(20) VALUE 'RATE-ROAMING'.
           05  WS-DISCOUNT-SVC     PIC X(20) VALUE 'APPLY-DISCOUNTS'.
           05  WS-TAX-CALC-SVC     PIC X(20) VALUE 'CALCULATE-TAXES'.
           05  WS-VALIDATION-SVC   PIC X(20) VALUE 'VALIDATE-BILL'.
           05  WS-GENERATION-SVC   PIC X(20) VALUE 'GENERATE-BILL'.
           05  WS-DELIVERY-SVC     PIC X(20) VALUE 'DELIVER-BILL'.
           
       PROCEDURE DIVISION.
       MAIN-BILLING-PROCESS.
           DISPLAY 'Telecom Billing Engine Started'
           PERFORM LOAD-ACCOUNT-DATA
           PERFORM RETRIEVE-USAGE-DETAIL
           PERFORM CALCULATE-CHARGES
           PERFORM APPLY-ADJUSTMENTS
           PERFORM VALIDATE-BILLING
           PERFORM GENERATE-BILL
           PERFORM DELIVER-BILL
           DISPLAY 'Billing Process Complete'
           STOP RUN.
           
       LOAD-ACCOUNT-DATA.
           MOVE 'ACC-2024001234' TO WS-ACCOUNT-ID
           MOVE '+1-555-987-6543' TO WS-PHONE-NUMBER
           MOVE 'Robert Johnson' TO WS-CUSTOMER-NAME
           MOVE 12 TO WS-BILLING-CYCLE
           MOVE 'POSTPAID' TO WS-PLAN-TYPE
           MOVE 150.00 TO WS-BALANCE
           MOVE 500.00 TO WS-CREDIT-LIMIT.
           
       RETRIEVE-USAGE-DETAIL.
           DISPLAY 'Retrieving usage details...'
           
      *    CALL usage retrieval service
           CALL WS-USAGE-RETRIEVAL USING BY REFERENCE WS-ACCOUNT-ID
                                              WS-PERIOD-START
                                              WS-PERIOD-END
                                         BY REFERENCE WS-CALL-MINUTES
                                                       WS-SMS-COUNT
                                                       WS-DATA-USAGE-MB
                                                       WS-LOCAL-CALLS
                                                       WS-LONG-DISTANCE
                                                       WS-ROAMING-USAGE
                   ON EXCEPTION
                       MOVE 001 TO WS-ERROR-CODE
                       MOVE 'Y' TO WS-ERROR-MSG
                       STOP RUN.
           
       CALCULATE-CHARGES.
           DISPLAY 'Calculating charges...'
           
      *    Get rate table
           CALL WS-RATE-LOOKUP USING WS-PLAN-TYPE
                                     BY REFERENCE WS-BASE-CHARGE
           
      *    Rate call charges
           CALL WS-CALL-RATING USING BY REFERENCE WS-CALL-MINUTES
                                          WS-LOCAL-CALLS
                                          WS-LONG-DISTANCE
                                     BY REFERENCE WS-CALL-CHARGES
                   ON EXCEPTION
                       MOVE 002 TO WS-ERROR-CODE
                       MOVE 'N' TO WS-CALCULATION-OK
           
      *    Rate SMS charges
           CALL WS-SMS-RATING USING WS-SMS-COUNT
                                    BY REFERENCE WS-SMS-CHARGES
                   ON EXCEPTION
                       MOVE 003 TO WS-ERROR-CODE
           
      *    Rate data charges
           CALL WS-DATA-RATING USING BY REFERENCE WS-DATA-USAGE-MB
                                         BY REFERENCE WS-DATA-CHARGES
                   ON EXCEPTION
                       MOVE 004 TO WS-ERROR-CODE
           
      *    Rate roaming charges
           CALL WS-ROAMING-RATING USING BY REFERENCE WS-ROAMING-USAGE
                                         BY REFERENCE WS-ROAMING-CHARGES
                   ON EXCEPTION
                       MOVE 005 TO WS-ERROR-CODE.
           
       APPLY-ADJUSTMENTS.
           DISPLAY 'Applying adjustments...'
           
      *    Calculate subtotal
           COMPUTE WS-TOTAL-CHARGES = 
               WS-BASE-CHARGE + WS-CALL-CHARGES + WS-SMS-CHARGES
               + WS-DATA-CHARGES + WS-ROAMING-CHARGES + WS-SURCHARGES
           
      *    CALL discount calculation service
           CALL WS-DISCOUNT-SVC USING BY REFERENCE WS-ACCOUNT-ID
                                          WS-PLAN-TYPE
                                          WS-PROMOTIONAL-CODE
                                          WS-TOTAL-CHARGES
                                     BY REFERENCE WS-LOYALTY-DISCOUNT
                                                   WS-PROMO-DISCOUNT
                                                   WS-FAMILY-PLAN-DISC
                   ON EXCEPTION
                       MOVE 006 TO WS-ERROR-CODE
           
      *    Calculate total discounts
           COMPUTE WS-TOTAL-DISCOUNTS = 
               WS-LOYALTY-DISCOUNT + WS-PROMO-DISCOUNT
               + WS-FAMILY-PLAN-DISC
           
      *    CALL tax calculation service
           CALL WS-TAX-CALC-SVC USING BY REFERENCE WS-TOTAL-CHARGES
                                          WS-TOTAL-DISCOUNTS
                                     BY REFERENCE WS-TAXES
                   RETURNING WS-TAXES
                   ON EXCEPTION
                       MOVE 007 TO WS-ERROR-CODE
           
      *    Calculate final amount due
           COMPUTE WS-AMOUNT-DUE = 
               WS-TOTAL-CHARGES - WS-TOTAL-DISCOUNTS + WS-TAXES.
           
       VALIDATE-BILLING.
           DISPLAY 'Validating bill...'
           
      *    CALL bill validation service
           CALL WS-VALIDATION-SVC USING BY REFERENCE WS-ACCOUNT-ID
                                             WS-AMOUNT-DUE
                                             WS-BALANCE
                                             WS-CREDIT-LIMIT
                                        BY REFERENCE WS-VALIDATION-OK
                   ON EXCEPTION
                       MOVE 008 TO WS-ERROR-CODE
                       MOVE 'Validation failed' TO WS-ERROR-MSG
                       MOVE 'N' TO WS-VALIDATION-OK.
           
       GENERATE-BILL.
           DISPLAY 'Generating bill...'
           
           IF WS-VALIDATION-OK = 'Y'
      *        CALL bill generation service
               CALL WS-GENERATION-SVC USING BY REFERENCE WS-ACCOUNT-ID
                                              WS-PHONE-NUMBER
                                              WS-CUSTOMER-NAME
                                              WS-PERIOD-START
                                              WS-PERIOD-END
                                              WS-TOTAL-CHARGES
                                              WS-TOTAL-DISCOUNTS
                                              WS-TAXES
                                              WS-AMOUNT-DUE
                                         BY REFERENCE WS-BILL-ID
                                                       WS-GENERATION-OK
                   ON EXCEPTION
                       MOVE 009 TO WS-ERROR-CODE
                       MOVE 'N' TO WS-GENERATION-OK
           END-IF.
           
       DELIVER-BILL.
           DISPLAY 'Delivering bill...'
           
           IF WS-GENERATION-OK = 'Y'
      *        CALL bill delivery service
               CALL WS-DELIVERY-SVC USING BY REFERENCE WS-BILL-ID
                                              WS-ACCOUNT-ID
                                              WS-CUSTOMER-NAME
                                              WS-AMOUNT-DUE
                   ON EXCEPTION
                       DISPLAY 'Delivery failed'
                   NOT ON EXCEPTION
                       MOVE '03' TO WS-BILL-STATUS
                       DISPLAY 'Bill delivered successfully'
           END-IF.
           
       END PROGRAM TELECOM-BILLING-ENGINE.
