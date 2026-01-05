      *****************************************************************
      * Real-World COBOL Example: Multi-Line CALL Statements
      * Demonstrates: CALL statements spanning multiple lines
      * Use Case: Enterprise service orchestration with complex params
      *****************************************************************
       IDENTIFICATION DIVISION.
       PROGRAM-ID. CALL-MULTILINE-COMPREHENSIVE.
       
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-CUSTOMER-DATA.
           05  WS-CUST-ID          PIC 9(10).
           05  WS-CUST-NAME        PIC X(50).
           05  WS-CUST-ADDRESS     PIC X(100).
           05  WS-CUST-PHONE       PIC X(15).
           05  WS-CUST-EMAIL       PIC X(50).
           05  WS-CUST-STATUS      PIC X(10).
           
       01  WS-ORDER-DATA.
           05  WS-ORDER-ID         PIC 9(12).
           05  WS-PRODUCT-CODE     PIC X(20).
           05  WS-QUANTITY         PIC 9(5).
           05  WS-UNIT-PRICE       PIC 9(7)V99 COMP-3.
           05  WS-TOTAL-AMOUNT     PIC 9(9)V99 COMP-3.
           05  WS-TAX-AMOUNT       PIC 9(7)V99 COMP-3.
           05  WS-DISCOUNT         PIC 9(5)V99 COMP-3.
           
       01  WS-RESULT-DATA.
           05  WS-RETURN-CODE      PIC 99.
           05  WS-ERROR-CODE       PIC 9(4).
           05  WS-STATUS-MSG       PIC X(100).
           05  WS-VALIDATION-FLAG  PIC X.
           
       01  WS-SERVICE-REGISTRY.
           05  WS-CUSTOMER-SVC     PIC X(30) VALUE 'CUSTOMER-SERVICE'.
           05  WS-ORDER-SVC        PIC X(30) VALUE 'ORDER-PROCESSING'.
           05  WS-INVENTORY-SVC    PIC X(30) VALUE 'INVENTORY-CHECK'.
           
       PROCEDURE DIVISION.
       MAIN-ORCHESTRATION.
           DISPLAY 'Multi-Line CALL Demonstration'.
           PERFORM PROCESS-CUSTOMER-DATA.
           PERFORM PROCESS-ORDER-DATA.
           PERFORM COMPLEX-CALCULATIONS.
           STOP RUN.
           
       PROCESS-CUSTOMER-DATA.
      *    CALL with 2 parameters on separate lines
           CALL 'VALIDATE-CUSTOMER' USING WS-CUST-ID
                                          WS-VALIDATION-FLAG.
           
      *    CALL with 3 parameters on separate lines
           CALL 'UPDATE-CUSTOMER' USING WS-CUST-ID
                                        WS-CUST-NAME
                                        WS-CUST-STATUS.
           
      *    CALL with 5 parameters on separate lines
           CALL 'CREATE-CUSTOMER-RECORD' 
                USING WS-CUST-ID
                      WS-CUST-NAME
                      WS-CUST-ADDRESS
                      WS-CUST-PHONE
                      WS-CUST-EMAIL.
           
      *    CALL with 6 parameters on separate lines
           CALL 'COMPREHENSIVE-CUSTOMER-UPDATE'
                USING WS-CUST-ID
                      WS-CUST-NAME
                      WS-CUST-ADDRESS
                      WS-CUST-PHONE
                      WS-CUST-EMAIL
                      WS-CUST-STATUS.
           
       PROCESS-ORDER-DATA.
      *    CALL with BY REFERENCE on separate lines
           CALL 'VALIDATE-ORDER'
                USING BY REFERENCE WS-ORDER-ID
                      BY REFERENCE WS-PRODUCT-CODE
                      BY REFERENCE WS-QUANTITY.
           
      *    CALL with BY VALUE on separate lines
           CALL 'CALCULATE-PRICE'
                USING BY VALUE WS-QUANTITY
                      BY VALUE WS-UNIT-PRICE
                      BY REFERENCE WS-TOTAL-AMOUNT.
           
      *    CALL with mixed parameter modes on separate lines
           CALL 'PROCESS-ORDER-DETAILS'
                USING BY VALUE WS-ORDER-ID
                      BY REFERENCE WS-PRODUCT-CODE
                      BY VALUE WS-QUANTITY
                      BY REFERENCE WS-TOTAL-AMOUNT
                      BY REFERENCE WS-RETURN-CODE.
           
      *    CALL with USING on one line, RETURNING on next
           CALL 'CALCULATE-TAX'
                USING WS-TOTAL-AMOUNT
                RETURNING WS-TAX-AMOUNT.
           
      *    CALL with multiple USING params and RETURNING
           CALL 'APPLY-DISCOUNT'
                USING WS-TOTAL-AMOUNT
                      WS-CUST-STATUS
                      WS-QUANTITY
                RETURNING WS-DISCOUNT.
           
       COMPLEX-CALCULATIONS.
      *    CALL with deeply indented continuation
           CALL 'COMPLEX-CALCULATION'
                USING BY REFERENCE WS-ORDER-ID
                                   WS-PRODUCT-CODE
                                   WS-QUANTITY
                                   WS-UNIT-PRICE
                      BY REFERENCE WS-TOTAL-AMOUNT
                                   WS-TAX-AMOUNT
                                   WS-DISCOUNT
                      BY REFERENCE WS-RETURN-CODE.
           
      *    CALL with exception handler on continuation lines
           CALL 'RISKY-CALCULATION'
                USING WS-TOTAL-AMOUNT
                      WS-TAX-AMOUNT
                ON EXCEPTION
                    MOVE 1 TO WS-ERROR-CODE
                    DISPLAY 'Calculation failed'
                NOT ON EXCEPTION
                    MOVE 0 TO WS-ERROR-CODE
                    DISPLAY 'Calculation succeeded'
                END-CALL.
           
      *    CALL with 10 parameters spanning many lines
           CALL 'COMPREHENSIVE-ORDER-PROCESSING'
                USING BY VALUE     WS-ORDER-ID
                      BY REFERENCE WS-CUST-ID
                      BY VALUE     WS-PRODUCT-CODE
                      BY REFERENCE WS-QUANTITY
                      BY VALUE     WS-UNIT-PRICE
                      BY REFERENCE WS-TOTAL-AMOUNT
                      BY REFERENCE WS-TAX-AMOUNT
                      BY REFERENCE WS-DISCOUNT
                      BY REFERENCE WS-RETURN-CODE
                      BY REFERENCE WS-STATUS-MSG.
           
      *    CALL with dynamic program name on separate line
           CALL WS-CUSTOMER-SVC
                USING WS-CUST-ID
                      WS-CUST-NAME
                      WS-CUST-STATUS.
           
      *    CALL with mixed indentation levels
           CALL 'FLEXIBLE-FORMATTING'
                USING WS-ORDER-ID
                WS-PRODUCT-CODE
                      WS-QUANTITY
                WS-UNIT-PRICE
                      WS-TOTAL-AMOUNT.
           
      *    CALL inside IF with multi-line parameters
           IF WS-TOTAL-AMOUNT > 1000.00
               CALL 'HIGH-VALUE-PROCESSING'
                    USING WS-ORDER-ID
                          WS-CUST-ID
                          WS-TOTAL-AMOUNT
                          WS-RETURN-CODE.
           
      *    CALL inside PERFORM with multi-line parameters
           PERFORM VARYING WS-QUANTITY FROM 1 BY 1
               UNTIL WS-QUANTITY > 10
               CALL 'BATCH-ITEM-PROCESSING'
                    USING WS-QUANTITY
                          WS-PRODUCT-CODE
                          WS-UNIT-PRICE
                          WS-TOTAL-AMOUNT
           END-PERFORM.
           
      *    CALL with RETURNING and exception on separate lines
           CALL 'FINALIZE-ORDER'
                USING WS-ORDER-ID
                      WS-TOTAL-AMOUNT
                      WS-TAX-AMOUNT
                RETURNING WS-RETURN-CODE
                ON EXCEPTION
                    DISPLAY 'Finalization failed'
                END-CALL.
           
      *    CALL with all clauses on separate lines
           CALL 'ULTIMATE-PROCESSING'
                USING BY REFERENCE WS-ORDER-ID
                                   WS-CUST-ID
                      BY VALUE     WS-TOTAL-AMOUNT
                RETURNING WS-RETURN-CODE
                ON EXCEPTION
                    MOVE 'FAILED' TO WS-STATUS-MSG
                    MOVE 99 TO WS-ERROR-CODE
                NOT ON EXCEPTION
                    MOVE 'SUCCESS' TO WS-STATUS-MSG
                    MOVE 0 TO WS-ERROR-CODE
                END-CALL.
           
       END PROGRAM CALL-MULTILINE-COMPREHENSIVE.
