      * Outer nested procedure copybook - contains statements AND a nested COPY
           MOVE "OUTER-START" TO WS-STATUS.
           DISPLAY "Outer copybook start".
           COPY PROC-NESTED-INNER.
           DISPLAY "Outer copybook end".
