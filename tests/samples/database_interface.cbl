      *****************************************************************
      * IBM Enterprise COBOL Sample - Database Interface Program  
      * Demonstrates: SQL INCLUDE, EXEC SQL blocks, error handling
      * Features: DB2 integration, cursor processing, transaction mgmt
      *****************************************************************
       IDENTIFICATION DIVISION.
       PROGRAM-ID. DB-INTERFACE.
       
       ENVIRONMENT DIVISION.
       
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       
      * SQL Communication Area
           EXEC SQL INCLUDE SQLCA END-EXEC.
           
      * Customer table structure
           EXEC SQL 
               DECLARE CUSTOMER TABLE
               ( CUST_ID     INTEGER NOT NULL,
                 CUST_NAME   CHAR(30),
                 CUST_ADDR   CHAR(50),
                 CUST_PHONE  CHAR(15),
                 CREDIT_LIMIT DECIMAL(10,2)
               )
           END-EXEC.
           
       01  WS-CUSTOMER-DATA.
           05  WS-CUST-ID          PIC 9(8) COMP.
           05  WS-CUST-NAME        PIC X(30).
           05  WS-CUST-ADDR        PIC X(50).
           05  WS-CUST-PHONE       PIC X(15).
           05  WS-CREDIT-LIMIT     PIC 9(8)V99 COMP-3.
           
       01  WS-SQL-STATUS.
           05  WS-SQLCODE          PIC S9(9) COMP VALUE ZERO.
               88  SQL-OK          VALUE 0.
               88  SQL-NOT-FOUND   VALUE +100.
               88  SQL-ERROR       VALUE -999 THRU -1.
               
       01  WS-COUNTERS.
           05  WS-RECORDS-PROCESSED PIC 9(6) VALUE ZERO.
           05  WS-ERROR-COUNT       PIC 9(6) VALUE ZERO.
           
       PROCEDURE DIVISION.
       MAIN-PROGRAM.
           PERFORM INITIALIZE-DATABASE
           PERFORM PROCESS-CUSTOMERS
           PERFORM CLEANUP-DATABASE
           DISPLAY 'Database processing complete'
           STOP RUN.
           
       INITIALIZE-DATABASE.
           DISPLAY 'Connecting to database...'
           
           EXEC SQL
               CONNECT TO SAMPLE
           END-EXEC
           
           MOVE SQLCODE TO WS-SQLCODE
           IF NOT SQL-OK
               DISPLAY 'Database connection failed: ' SQLCODE
               STOP RUN  
           END-IF
           
           DISPLAY 'Database connected successfully'.
           
       PROCESS-CUSTOMERS.
           DISPLAY 'Processing customer records...'
           
           EXEC SQL
               DECLARE CUST_CURSOR CURSOR FOR
               SELECT CUST_ID, CUST_NAME, CUST_ADDR, 
                      CUST_PHONE, CREDIT_LIMIT
               FROM CUSTOMER
               WHERE CREDIT_LIMIT > 1000.00
               ORDER BY CUST_ID
           END-EXEC
           
           EXEC SQL
               OPEN CUST_CURSOR
           END-EXEC
           
           PERFORM READ-CUSTOMER-CURSOR
           PERFORM UNTIL SQL-NOT-FOUND OR SQL-ERROR
               PERFORM PROCESS-SINGLE-CUSTOMER
               PERFORM READ-CUSTOMER-CURSOR
           END-PERFORM
           
           EXEC SQL
               CLOSE CUST_CURSOR  
           END-EXEC.
           
       READ-CUSTOMER-CURSOR.
           EXEC SQL
               FETCH CUST_CURSOR
               INTO :WS-CUST-ID, :WS-CUST-NAME, :WS-CUST-ADDR,
                    :WS-CUST-PHONE, :WS-CREDIT-LIMIT
           END-EXEC
           
           MOVE SQLCODE TO WS-SQLCODE
           
           IF SQL-ERROR
               ADD 1 TO WS-ERROR-COUNT
               DISPLAY 'Cursor fetch error: ' SQLCODE
           END-IF.
           
       PROCESS-SINGLE-CUSTOMER.
           ADD 1 TO WS-RECORDS-PROCESSED
           
           DISPLAY 'Customer: ' WS-CUST-ID ' - ' WS-CUST-NAME
           
           IF WS-CREDIT-LIMIT > 10000.00
               PERFORM UPDATE-PREMIUM-CUSTOMER
           END-IF.
           
       UPDATE-PREMIUM-CUSTOMER.
           DISPLAY 'Updating premium customer: ' WS-CUST-ID
           
           EXEC SQL
               UPDATE CUSTOMER
               SET CUST_ADDR = :WS-CUST-ADDR || ' (PREMIUM)'
               WHERE CUST_ID = :WS-CUST-ID
           END-EXEC
           
           MOVE SQLCODE TO WS-SQLCODE
           
           IF SQL-OK
               DISPLAY 'Premium customer updated successfully'
           ELSE
               DISPLAY 'Update failed: ' SQLCODE
               ADD 1 TO WS-ERROR-COUNT
           END-IF.
           
       CLEANUP-DATABASE.
           IF WS-ERROR-COUNT = ZERO
               EXEC SQL COMMIT WORK END-EXEC
               DISPLAY 'Transaction committed'
           ELSE
               EXEC SQL ROLLBACK WORK END-EXEC
               DISPLAY 'Transaction rolled back due to errors'
           END-IF
           
           EXEC SQL
               DISCONNECT ALL
           END-EXEC
           
           DISPLAY 'Records processed: ' WS-RECORDS-PROCESSED
           DISPLAY 'Errors encountered: ' WS-ERROR-COUNT.