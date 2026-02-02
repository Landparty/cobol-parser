"""Parser for EVALUATE statements."""

from typing import Optional, List
from ..core.interfaces import StatementParser, ParseContext
from ..core.token_stream import TokenStream
from ..models.statements import EvaluateStatement, WhenClause, CobolExpression
from ..lexer import TokenType


class EvaluateStatementParser(StatementParser):
    """Parser for EVALUATE statements."""

    def can_parse(self, stream: TokenStream) -> bool:
        token = stream.peek()
        if token is None:
            return False
        if token.type == TokenType.EVALUATE:
            return True
        if token.type == TokenType.IDENTIFIER and token.value.upper() == "EVALUATE":
            return True
        # Recovery: Check if previous token was EVALUATE
        prev = stream.peek(-1)
        if prev:
            if prev.type == TokenType.EVALUATE or (
                prev.type == TokenType.IDENTIFIER and prev.value.upper() == "EVALUATE"
            ):
                return True
        return False

    def parse(self, stream: TokenStream, context: ParseContext) -> EvaluateStatement:
        """Parse EVALUATE statement.

        Supports:
        - EVALUATE subject [ALSO subject]...
        - WHEN selector [ALSO selector]... statements
        - WHEN OTHER statements
        - END-EVALUATE terminator
        """
        start_token = stream.peek()
        # Consume EVALUATE if present
        if start_token and (
            start_token.type == TokenType.EVALUATE
            or (start_token.type == TokenType.IDENTIFIER and start_token.value.upper() == "EVALUATE")
        ):
            start_token = stream.advance()
        else:
            start_token = stream.peek(-1)
        
        if not start_token:
            from ..models.ast_base import SourceLocation
            start_token_loc = SourceLocation(0, 0)
        else:
            start_token_loc = start_token.location

        stmt = EvaluateStatement(start_token_loc)
        stream.skip_whitespace_and_comments()

        # Parse subjects (one or more separated by ALSO)
        subjects = []
        while not stream.is_at_end:
            print("DEBUG: Subjects loop")
            token = stream.peek()
            if not token:
                break
            
            # Check for WHEN (end of subjects)
            if token.type == TokenType.WHEN:
                break
            
            # Check for ALSO (additional subject)
            if token.type == TokenType.IDENTIFIER and token.value and token.value.upper() == "ALSO":
                stream.advance()  # Skip ALSO
                stream.skip_whitespace_and_comments()
                continue
            
            # Collect subject expression tokens
            subject_tokens = []
            paren_depth = 0
            while not stream.is_at_end:
                token = stream.peek()
                if not token:
                    break
                
                token_val_upper = token.value.upper() if token.value else ""
                
                # Stop at ALSO or WHEN
                if paren_depth == 0 and token_val_upper in ("ALSO", "WHEN"):
                    break
                
                if token.type == TokenType.LEFT_PAREN:
                    paren_depth += 1
                elif token.type == TokenType.RIGHT_PAREN:
                    paren_depth -= 1
                
                subject_tokens.append(token.value if token.value else "")
                stream.advance()
                stream.skip_whitespace_and_comments()
            
            if subject_tokens:
                subject_str = " ".join(subject_tokens).strip()
                if subject_str:
                    subjects.append(subject_str)
                    stmt.add_subject(subject_str)

        # Parse WHEN clauses
        while not stream.is_at_end:
            print("DEBUG: EvaluateParser WHEN loop")
            token = stream.peek()
            if not token:
                break
            
            stream.skip_whitespace_and_comments()
            token = stream.peek()
            if not token:
                break
            
            token_val_upper = token.value.upper() if token.value else ""
            
            # Check for END-EVALUATE
            if token_val_upper == "END-EVALUATE":
                stream.advance()
                break
            
            # Check for WHEN
            if token_val_upper != "WHEN":
                # End of EVALUATE or other statement
                break
            
            stream.advance()  # Skip WHEN
            stream.skip_whitespace_and_comments()
            
            # Check for WHEN OTHER
            token = stream.peek()
            if token and (token.type == TokenType.OTHER or (token.value and token.value.upper() == "OTHER")):
                other_loc = token.location
                stream.advance()  # Skip OTHER
                stream.skip_whitespace_and_comments()
                
                # Parse statements until END-EVALUATE
                other_stmts = []
                while not stream.is_at_end:
                    token = stream.peek()
                    if not token:
                        break
                    
                    if token.value and token.value.upper() == "END-EVALUATE":
                        break
                    
                    # Use context.host to parse nested statement
                    if context and hasattr(context, 'host') and context.host:
                        nested_stmt = context.host.parse_statement()
                        if nested_stmt:
                            other_stmts.append(nested_stmt)
                    else:
                        # Fallback: skip token
                        stream.advance()
                    
                    stream.skip_whitespace_and_comments()
                
                when_clause = WhenClause([], other_loc)
                for s in other_stmts:
                    when_clause.add_statement(s)
                stmt.set_default_when(when_clause)
                continue
            
            # Parse selectors (must match number of subjects)
            selectors = []
            for _ in range(len(subjects)):
                stream.skip_whitespace_and_comments()
                token = stream.peek()
                if not token:
                    break
                
                # Check for ALSO between selectors
                if token.value and token.value.upper() == "ALSO" and selectors:
                    stream.advance()  # Skip ALSO
                    stream.skip_whitespace_and_comments()
                    token = stream.peek()
                
                # Collect selector tokens
                selector_tokens = []
                paren_depth = 0
                while not stream.is_at_end:
                    token = stream.peek()
                    if not token:
                        break
                    
                    token_val_upper = token.value.upper() if token.value else ""
                    
                    # Stop at ALSO (between selectors) or statement-starting keywords
                    # Stop at ALSO (between selectors) or statement-starting keywords
                    if paren_depth == 0 and token_val_upper in ("ALSO", "MOVE", "DISPLAY", "PERFORM", "IF", "CALL", "WHEN", "END-EVALUATE"):
                        break
                    
                    if token.type == TokenType.LEFT_PAREN:
                        paren_depth += 1
                    elif token.type == TokenType.RIGHT_PAREN:
                        paren_depth -= 1
                    
                    selector_tokens.append(token.value if token.value else "")
                    stream.advance()
                    stream.skip_whitespace_and_comments()
                
                if selector_tokens:
                    selector_str = " ".join(selector_tokens).strip()
                    if selector_str:
                        selectors.append(selector_str)
            
            # Parse statements for this WHEN clause
            when_stmts = []
            while not stream.is_at_end:
                token = stream.peek()
                if not token:
                    break
                
                token_val_upper = token.value.upper() if token.value else ""
                
                # Stop at WHEN or END-EVALUATE
                if token_val_upper in ("WHEN", "END-EVALUATE"):
                    break
                
                # Use context.host to parse nested statement
                if context and hasattr(context, 'host') and context.host:
                    nested_stmt = context.host.parse_statement()
                    if nested_stmt:
                        when_stmts.append(nested_stmt)
                else:
                    # Fallback: skip token
                    stream.advance()
                
                stream.skip_whitespace_and_comments()
            
            # Create WHEN clause
            when_clause = WhenClause(start_token_loc)
            for selector in selectors:
                when_clause.add_selector(selector)
            for when_stmt in when_stmts:
                when_clause.add_statement(when_stmt)
            
            stmt.add_when_clause(when_clause)

        return stmt
