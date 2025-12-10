      *****************************************************************
      * Communication Module
      * Tests: COMMUNICATION SECTION, MESSAGE queues (legacy feature)
      *****************************************************************
       IDENTIFICATION DIVISION.
       PROGRAM-ID. COMMTEST.
       
       ENVIRONMENT DIVISION.
       CONFIGURATION SECTION.
       SOURCE-COMPUTER. IBM-370.
       OBJECT-COMPUTER. IBM-370.
       
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT MESSAGE-FILE ASSIGN TO 'MESSAGES.DAT'
               ORGANIZATION IS SEQUENTIAL.
               
       DATA DIVISION.
       FILE SECTION.
       FD  MESSAGE-FILE.
       01  MESSAGE-RECORD          PIC X(200).
       
       WORKING-STORAGE SECTION.
       01  WS-MESSAGE-TEXT         PIC X(200).
       01  WS-MESSAGE-COUNT        PIC 9(5) VALUE ZERO.
       01  WS-EOF-FLAG             PIC X VALUE 'N'.
           88  EOF-REACHED         VALUE 'Y'.
           
       01  WS-QUEUE-NAME           PIC X(20) VALUE 'MAIN-QUEUE'.
       01  WS-TERMINAL-ID          PIC X(4) VALUE 'T001'.
       
       COMMUNICATION SECTION.
       
      *    Input message queue
       CD  INPUT-QUEUE FOR INPUT.
           05  MESSAGE-DATE        PIC 9(8).
           05  MESSAGE-TIME        PIC 9(6).
           05  SYMBOLIC-SOURCE     PIC X(12).
           05  TEXT-LENGTH         PIC 9(4).
           05  END-KEY-INDICATOR   PIC X.
           05  STATUS-KEY          PIC XX.
           05  MESSAGE-COUNT       PIC 9(6).
           
      *    Output message queue
       CD  OUTPUT-QUEUE FOR OUTPUT.
           05  DESTINATION-COUNT   PIC 9(4).
           05  DESTINATION-TABLE OCCURS 10 TIMES.
               10  ERROR-KEY       PIC X.
               10  SYMBOLIC-DEST   PIC X(12).
               
      *    I-O message queue (bidirectional)
       CD  IO-QUEUE FOR I-O
           INITIAL
           STATUS KEY IS WS-STATUS-KEY
           DESTINATION COUNT IS WS-DEST-COUNT
           TEXT LENGTH IS WS-TEXT-LEN
           END KEY IS WS-END-KEY
           MESSAGE DATE IS WS-MSG-DATE
           MESSAGE TIME IS WS-MSG-TIME.
           
       01  WS-STATUS-KEY           PIC XX.
       01  WS-DEST-COUNT           PIC 9(4).
       01  WS-TEXT-LEN             PIC 9(4).
       01  WS-END-KEY              PIC X.
       01  WS-MSG-DATE             PIC 9(8).
       01  WS-MSG-TIME             PIC 9(6).
       
       01  WS-IO-MESSAGE           PIC X(200).
       
       PROCEDURE DIVISION.
       MAIN-LOGIC.
           PERFORM ENABLE-QUEUES
           PERFORM SEND-MESSAGES
           PERFORM RECEIVE-MESSAGES
           PERFORM DISABLE-QUEUES
           STOP RUN.
           
       ENABLE-QUEUES.
      *    Enable input queue
           ENABLE INPUT INPUT-QUEUE
               WITH KEY 'INPUTKEY'
           
           DISPLAY 'Input queue enabled'
           
      *    Enable output queue
           ENABLE OUTPUT OUTPUT-QUEUE
               WITH KEY 'OUTPUTKEY'
           
           DISPLAY 'Output queue enabled'
           
      *    Enable I-O queue
           ENABLE I-O IO-QUEUE
               WITH KEY 'IOKEY'
           
           DISPLAY 'I-O queue enabled'.
           
       SEND-MESSAGES.
      *    Send message to output queue
           MOVE 'Hello from COBOL program' TO WS-MESSAGE-TEXT
           MOVE 30 TO TEXT-LENGTH
           MOVE 1 TO DESTINATION-COUNT
           MOVE 'TERM001' TO SYMBOLIC-DEST(1)
           MOVE SPACE TO ERROR-KEY(1)
           
           SEND OUTPUT-QUEUE FROM WS-MESSAGE-TEXT
           
           DISPLAY 'Message sent: ' WS-MESSAGE-TEXT
           
      *    Send with explicit destination
           MOVE 'Priority message' TO WS-MESSAGE-TEXT
           MOVE 16 TO TEXT-LENGTH
           
           SEND OUTPUT-QUEUE FROM WS-MESSAGE-TEXT
               WITH EMI
               REPLACING LINE
           
      *    Send to terminal
           MOVE 'Terminal message' TO WS-MESSAGE-TEXT
           
           SEND OUTPUT-QUEUE FROM WS-MESSAGE-TEXT
               WITH ESI
               ADVANCING PAGE
               
      *    Send to multiple destinations
           MOVE 'Broadcast message' TO WS-MESSAGE-TEXT
           MOVE 3 TO DESTINATION-COUNT
           MOVE 'TERM001' TO SYMBOLIC-DEST(1)
           MOVE 'TERM002' TO SYMBOLIC-DEST(2)
           MOVE 'TERM003' TO SYMBOLIC-DEST(3)
           
           SEND OUTPUT-QUEUE FROM WS-MESSAGE-TEXT.
           
       RECEIVE-MESSAGES.
      *    Receive from input queue
           RECEIVE INPUT-QUEUE MESSAGE INTO WS-MESSAGE-TEXT
               NO DATA
                   DISPLAY 'No data available'
               END-RECEIVE
           
           IF STATUS-KEY = '00'
               DISPLAY 'Received: ' WS-MESSAGE-TEXT
               DISPLAY 'From: ' SYMBOLIC-SOURCE
               DISPLAY 'Length: ' TEXT-LENGTH
               DISPLAY 'Date: ' MESSAGE-DATE
               DISPLAY 'Time: ' MESSAGE-TIME
               ADD 1 TO WS-MESSAGE-COUNT
           END-IF
           
      *    Receive with segment handling
           RECEIVE INPUT-QUEUE MESSAGE INTO WS-MESSAGE-TEXT
               NO DATA
                   DISPLAY 'Queue empty'
               SEGMENT
                   DISPLAY 'Segment received'
                   MOVE WS-MESSAGE-TEXT TO MESSAGE-RECORD
                   PERFORM PROCESS-SEGMENT
               END-RECEIVE
           
      *    Receive from I-O queue
           RECEIVE IO-QUEUE MESSAGE INTO WS-IO-MESSAGE
               NO DATA
                   DISPLAY 'I-O queue empty'
               END-RECEIVE
           
           IF WS-STATUS-KEY = '00'
               DISPLAY 'I-O message: ' WS-IO-MESSAGE
           END-IF.
           
       PROCESS-SEGMENT.
           DISPLAY 'Processing segment: ' MESSAGE-RECORD.
           
       DISABLE-QUEUES.
      *    Disable input queue
           DISABLE INPUT INPUT-QUEUE
               WITH KEY 'INPUTKEY'
           
           DISPLAY 'Input queue disabled'
           
      *    Disable output queue  
           DISABLE OUTPUT OUTPUT-QUEUE
               WITH KEY 'OUTPUTKEY'
           
           DISPLAY 'Output queue disabled'
           
      *    Disable I-O queue
           DISABLE I-O IO-QUEUE
               WITH KEY 'IOKEY'
           
           DISPLAY 'I-O queue disabled'
           DISPLAY 'Total messages processed: ' WS-MESSAGE-COUNT.
           
      *****************************************************************
      * Note: Communication module is a legacy COBOL feature
      * Modern applications typically use:
      * - EXEC CICS for CICS environments
      * - MQSeries/IBM MQ for message queuing
      * - Web services or REST APIs
      * - TCP/IP sockets
      *****************************************************************
