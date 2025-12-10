      *****************************************************************
      * ACCEPT and DISPLAY Variations
      * Tests: ACCEPT FROM console/DATE/TIME/DAY, DISPLAY formats
      *****************************************************************
       IDENTIFICATION DIVISION.
       PROGRAM-ID. ACCEPTDISP.
       
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-USER-INPUT           PIC X(50).
       01  WS-NUMERIC-INPUT        PIC 9(5).
       01  WS-DATE-FIELDS.
           05  WS-CURRENT-DATE     PIC 9(8).
           05  WS-CURRENT-TIME     PIC 9(8).
           05  WS-CURRENT-DAY      PIC 9(7).
           
       01  WS-DATE-YYYYMMDD.
           05  WS-YEAR             PIC 9(4).
           05  WS-MONTH            PIC 9(2).
           05  WS-DAY              PIC 9(2).
           
       01  WS-TIME-HHMMSSCC.
           05  WS-HOURS            PIC 9(2).
           05  WS-MINUTES          PIC 9(2).
           05  WS-SECONDS          PIC 9(2).
           05  WS-CENTISECS        PIC 9(2).
           
       01  WS-DAY-OF-WEEK          PIC 9(7).
       01  WS-DAY-YYYYDDD.
           05  WS-D-YEAR           PIC 9(4).
           05  WS-D-DAY            PIC 9(3).
           
       01  WS-DISPLAY-MSG          PIC X(80).
       01  WS-COUNTER              PIC 9(3) VALUE 1.
       
       PROCEDURE DIVISION.
       MAIN-LOGIC.
           PERFORM ACCEPT-TESTS
           PERFORM DISPLAY-TESTS
           PERFORM DATE-TIME-TESTS
           STOP RUN.
           
       ACCEPT-TESTS.
      *    Simple ACCEPT from console
           DISPLAY 'Enter your name: ' WITH NO ADVANCING
           ACCEPT WS-USER-INPUT
           DISPLAY 'Hello, ' WS-USER-INPUT
           
      *    ACCEPT numeric input
           DISPLAY 'Enter a number: ' WITH NO ADVANCING
           ACCEPT WS-NUMERIC-INPUT
           DISPLAY 'You entered: ' WS-NUMERIC-INPUT
           
      *    ACCEPT from DATE (YYMMDD format)
           ACCEPT WS-CURRENT-DATE FROM DATE
           DISPLAY 'Current date (YYMMDD): ' WS-CURRENT-DATE
           
      *    ACCEPT from DATE YYYYMMDD
           ACCEPT WS-DATE-YYYYMMDD FROM DATE YYYYMMDD
           DISPLAY 'Year: ' WS-YEAR
           DISPLAY 'Month: ' WS-MONTH
           DISPLAY 'Day: ' WS-DAY
           
      *    ACCEPT from TIME
           ACCEPT WS-CURRENT-TIME FROM TIME
           DISPLAY 'Current time: ' WS-CURRENT-TIME
           
      *    ACCEPT from DAY (YYDDD format)
           ACCEPT WS-CURRENT-DAY FROM DAY
           DISPLAY 'Current day (YYDDD): ' WS-CURRENT-DAY
           
      *    ACCEPT from DAY YYYYDDD
           ACCEPT WS-DAY-YYYYDDD FROM DAY YYYYDDD
           DISPLAY 'Day year: ' WS-D-YEAR
           DISPLAY 'Day of year: ' WS-D-DAY
           
      *    ACCEPT from DAY-OF-WEEK
           ACCEPT WS-DAY-OF-WEEK FROM DAY-OF-WEEK
           DISPLAY 'Day of week (1-7): ' WS-DAY-OF-WEEK.
           
       DISPLAY-TESTS.
      *    Simple DISPLAY
           DISPLAY 'Simple display message'
           
      *    DISPLAY with NO ADVANCING
           DISPLAY 'This stays on same line' WITH NO ADVANCING
           DISPLAY ' - continued'
           
      *    DISPLAY multiple items
           DISPLAY 'Name: ' WS-USER-INPUT ' Number: ' WS-NUMERIC-INPUT
           
      *    DISPLAY with literal concatenation
           DISPLAY 'Date: ' WS-YEAR '-' WS-MONTH '-' WS-DAY
           
      *    DISPLAY with UPON CONSOLE
           DISPLAY 'Console message' UPON CONSOLE
           
      *    DISPLAY with UPON SYSERR (standard error)
           DISPLAY 'Error message' UPON SYSERR
           
      *    DISPLAY formatted output
           MOVE 'Formatted message with counter' TO WS-DISPLAY-MSG
           DISPLAY WS-DISPLAY-MSG
           
      *    DISPLAY in loop
           PERFORM VARYING WS-COUNTER FROM 1 BY 1
               UNTIL WS-COUNTER > 5
               DISPLAY 'Counter: ' WS-COUNTER
           END-PERFORM.
           
       DATE-TIME-TESTS.
      *    Get and display complete date/time information
           ACCEPT WS-TIME-HHMMSSCC FROM TIME
           MOVE WS-TIME-HHMMSSCC TO WS-CURRENT-TIME
           
           DISPLAY 'Current Time Details:'
           DISPLAY '  Hours: ' WS-HOURS
           DISPLAY '  Minutes: ' WS-MINUTES
           DISPLAY '  Seconds: ' WS-SECONDS
           DISPLAY '  Centiseconds: ' WS-CENTISECS
           
      *    Build formatted date string
           STRING WS-YEAR '/' WS-MONTH '/' WS-DAY
               DELIMITED BY SIZE
               INTO WS-DISPLAY-MSG
           END-STRING
           DISPLAY 'Formatted date: ' WS-DISPLAY-MSG
           
      *    Build formatted time string
           STRING WS-HOURS ':' WS-MINUTES ':' WS-SECONDS
               DELIMITED BY SIZE
               INTO WS-DISPLAY-MSG
           END-STRING
           DISPLAY 'Formatted time: ' WS-DISPLAY-MSG.
