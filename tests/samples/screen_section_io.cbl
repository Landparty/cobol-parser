      *****************************************************************
      * Screen Section and ACCEPT/DISPLAY with Screen Handling
      * Tests: SCREEN SECTION, full-screen I/O, field attributes
      *****************************************************************
       IDENTIFICATION DIVISION.
       PROGRAM-ID. SCREENIO.
       
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-EMPLOYEE-DATA.
           05  WS-EMP-ID           PIC 9(6).
           05  WS-EMP-NAME         PIC X(30).
           05  WS-EMP-DEPT         PIC X(20).
           05  WS-EMP-SALARY       PIC 9(7)V99.
           05  WS-EMP-HIRE-DATE    PIC 9(8).
           
       01  WS-FUNCTION-KEY         PIC 9(2).
           88  F3-PRESSED          VALUE 3.
           88  F12-PRESSED         VALUE 12.
           88  ENTER-PRESSED       VALUE 0.
           
       01  WS-CURSOR-POSITION.
           05  WS-CURSOR-ROW       PIC 9(2).
           05  WS-CURSOR-COL       PIC 9(2).
           
       01  WS-ACCEPT-STATUS        PIC 9(4).
       01  WS-DISPLAY-STATUS       PIC 9(4).
       
       SCREEN SECTION.
       
      *    Main menu screen
       01  MAIN-MENU-SCREEN.
           05  BLANK SCREEN.
           05  LINE 1  COLUMN 1   VALUE '============================='.
           05  LINE 2  COLUMN 1   VALUE '     EMPLOYEE MAINTENANCE    '.
           05  LINE 3  COLUMN 1   VALUE '============================='.
           05  LINE 5  COLUMN 5    VALUE '1. Add Employee'.
           05  LINE 6  COLUMN 5    VALUE '2. Update Employee'.
           05  LINE 7  COLUMN 5    VALUE '3. Delete Employee'.
           05  LINE 8  COLUMN 5    VALUE '4. Display Employee'.
           05  LINE 9  COLUMN 5    VALUE '5. Exit'.
           05  LINE 11 COLUMN 5    VALUE 'Selection: '.
           05  LINE 11 COLUMN 17   PIC 9 TO WS-FUNCTION-KEY
               REQUIRED
               AUTO.
               
      *    Employee data entry screen
       01  EMPLOYEE-ENTRY-SCREEN.
           05  BLANK SCREEN.
           05  LINE 1  COLUMN 1    VALUE '==========================='.
           05  LINE 2  COLUMN 1    VALUE '     EMPLOYEE ENTRY        '.
           05  LINE 3  COLUMN 1    VALUE '==========================='.
           
           05  LINE 5  COLUMN 5    VALUE 'Employee ID: '.
           05  LINE 5  COLUMN 19   PIC 9(6) 
               FROM WS-EMP-ID
               TO WS-EMP-ID
               REQUIRED
               PROMPT
               SECURE.
               
           05  LINE 7  COLUMN 5    VALUE 'Name: '.
           05  LINE 7  COLUMN 19   PIC X(30)
               FROM WS-EMP-NAME
               TO WS-EMP-NAME
               REQUIRED
               FULL.
               
           05  LINE 9  COLUMN 5    VALUE 'Department: '.
           05  LINE 9  COLUMN 19   PIC X(20)
               FROM WS-EMP-DEPT
               TO WS-EMP-DEPT
               AUTO-SKIP.
               
           05  LINE 11 COLUMN 5    VALUE 'Salary: '.
           05  LINE 11 COLUMN 19   PIC $$$,$$$,$$9.99
               FROM WS-EMP-SALARY
               TO WS-EMP-SALARY
               BLANK WHEN ZERO.
               
           05  LINE 13 COLUMN 5    VALUE 'Hire Date (YYYYMMDD): '.
           05  LINE 13 COLUMN 28   PIC 9(8)
               FROM WS-EMP-HIRE-DATE
               TO WS-EMP-HIRE-DATE.
               
           05  LINE 20 COLUMN 1    VALUE 'F3=Exit  F12=Save'.
               HIGHLIGHT
               BLINK.
               
      *    Employee display screen with colors
       01  EMPLOYEE-DISPLAY-SCREEN.
           05  BLANK SCREEN.
           05  LINE 1  COLUMN 1    VALUE '============================='
               FOREGROUND-COLOR 1
               BACKGROUND-COLOR 7.
               
           05  LINE 2  COLUMN 1    VALUE '    EMPLOYEE INFORMATION     '
               FOREGROUND-COLOR 1
               BACKGROUND-COLOR 7
               HIGHLIGHT.
               
           05  LINE 3  COLUMN 1    VALUE '============================='
               FOREGROUND-COLOR 1
               BACKGROUND-COLOR 7.
               
           05  LINE 5  COLUMN 5    VALUE 'Employee ID: '
               FOREGROUND-COLOR 2.
           05  LINE 5  COLUMN 19   PIC 9(6)
               FROM WS-EMP-ID
               FOREGROUND-COLOR 3
               HIGHLIGHT.
               
           05  LINE 7  COLUMN 5    VALUE 'Name: '
               FOREGROUND-COLOR 2.
           05  LINE 7  COLUMN 19   PIC X(30)
               FROM WS-EMP-NAME
               FOREGROUND-COLOR 3
               UNDERLINE.
               
           05  LINE 9  COLUMN 5    VALUE 'Department: '
               FOREGROUND-COLOR 2.
           05  LINE 9  COLUMN 19   PIC X(20)
               FROM WS-EMP-DEPT
               FOREGROUND-COLOR 4.
               
           05  LINE 11 COLUMN 5    VALUE 'Salary: '
               FOREGROUND-COLOR 2.
           05  LINE 11 COLUMN 19   PIC $$$,$$$,$$9.99
               FROM WS-EMP-SALARY
               FOREGROUND-COLOR 6
               REVERSE-VIDEO.
               
           05  LINE 13 COLUMN 5    VALUE 'Hire Date: '
               FOREGROUND-COLOR 2.
           05  LINE 13 COLUMN 19   PIC 9999/99/99
               FROM WS-EMP-HIRE-DATE
               FOREGROUND-COLOR 5.
               
      *    Nested screen group
       01  MESSAGE-LINE-SCREEN.
           05  LINE 23 COLUMN 1    PIC X(80)
               FROM WS-DISPLAY-STATUS
               BELL
               ERASE EOL.
               
      *    Grid screen with OCCURS
       01  TABLE-DISPLAY-SCREEN.
           05  BLANK SCREEN.
           05  LINE 1  COLUMN 1    VALUE 'Employee List:'.
           05  LINE 3  COLUMN 1    VALUE 'ID    Name              Dept'.
           05  LINE 4  COLUMN 1    VALUE '===   ====              ===='.
           05  EMPLOYEE-LINES OCCURS 15 TIMES.
               10  LINE NUMBER PLUS 1.
                   15  COLUMN 1    PIC 9(6) FROM WS-EMP-ID.
                   15  COLUMN 8    PIC X(20) FROM WS-EMP-NAME.
                   15  COLUMN 30   PIC X(20) FROM WS-EMP-DEPT.
                   
       PROCEDURE DIVISION.
       MAIN-LOGIC.
           PERFORM DISPLAY-MAIN-MENU
           PERFORM UNTIL F3-PRESSED
               EVALUATE WS-FUNCTION-KEY
                   WHEN 1
                       PERFORM ADD-EMPLOYEE-SCREEN
                   WHEN 2
                       PERFORM UPDATE-EMPLOYEE-SCREEN
                   WHEN 3
                       PERFORM DELETE-EMPLOYEE-SCREEN
                   WHEN 4
                       PERFORM DISPLAY-EMPLOYEE-SCREEN
                   WHEN 5
                       SET F3-PRESSED TO TRUE
                   WHEN OTHER
                       DISPLAY 'Invalid selection'
               END-EVALUATE
               IF NOT F3-PRESSED
                   PERFORM DISPLAY-MAIN-MENU
               END-IF
           END-PERFORM
           STOP RUN.
           
       DISPLAY-MAIN-MENU.
           DISPLAY MAIN-MENU-SCREEN
           ACCEPT MAIN-MENU-SCREEN.
           
       ADD-EMPLOYEE-SCREEN.
      *    Clear employee data
           INITIALIZE WS-EMPLOYEE-DATA
           
      *    Display and accept screen
           DISPLAY EMPLOYEE-ENTRY-SCREEN
           ACCEPT EMPLOYEE-ENTRY-SCREEN
           
      *    Check function key
           ACCEPT WS-FUNCTION-KEY FROM ESCAPE KEY
           IF F12-PRESSED
               PERFORM SAVE-EMPLOYEE
           END-IF.
           
       UPDATE-EMPLOYEE-SCREEN.
      *    Load employee data (simulated)
           MOVE 123456 TO WS-EMP-ID
           MOVE 'John Doe' TO WS-EMP-NAME
           MOVE 'IT Department' TO WS-EMP-DEPT
           MOVE 75000.00 TO WS-EMP-SALARY
           MOVE 20200115 TO WS-EMP-HIRE-DATE
           
           DISPLAY EMPLOYEE-ENTRY-SCREEN
           ACCEPT EMPLOYEE-ENTRY-SCREEN
               ON EXCEPTION
                   DISPLAY 'Screen accept error'
               NOT ON EXCEPTION
                   PERFORM SAVE-EMPLOYEE
           END-ACCEPT.
           
       DELETE-EMPLOYEE-SCREEN.
           DISPLAY 'Delete functionality not implemented'
           ACCEPT WS-FUNCTION-KEY.
           
       DISPLAY-EMPLOYEE-SCREEN.
      *    Load employee data
           MOVE 123456 TO WS-EMP-ID
           MOVE 'Jane Smith' TO WS-EMP-NAME
           MOVE 'Finance' TO WS-EMP-DEPT
           MOVE 85000.50 TO WS-EMP-SALARY
           MOVE 20190301 TO WS-EMP-HIRE-DATE
           
      *    Display with colors and attributes
           DISPLAY EMPLOYEE-DISPLAY-SCREEN
               AT LINE 1 COLUMN 1
               WITH BELL
           
           DISPLAY 'Press any key to continue...'
               AT LINE 20 COLUMN 1
           
           ACCEPT WS-FUNCTION-KEY.
           
       SAVE-EMPLOYEE.
           DISPLAY 'Saving employee: ' WS-EMP-ID
           MOVE 'Employee saved successfully' TO WS-DISPLAY-STATUS
           DISPLAY MESSAGE-LINE-SCREEN.
