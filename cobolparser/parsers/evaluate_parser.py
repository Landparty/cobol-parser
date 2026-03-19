"""Parser for EVALUATE statements."""

from typing import Optional, List
from ..core.interfaces import StatementParser
from ..core.token_stream import TokenStream
from ..models.statements import EvaluateStatement, WhenClause, CobolExpression
from ..lexer import TokenType
from ..plugins.core import ParseError


class EvaluateStatementParser(StatementParser):
    """Parser for EVALUATE statements.

    NOTE: This parser only extracts the EVALUATE structure (subjects, WHEN clauses,
    selectors) but does NOT recursively parse nested statements. The nested statements
    are left to be parsed by the main statement parser when parse_statement() is called
    at the sentence level.
    """
    token_type = TokenType.EVALUATE

    def can_parse(self, stream: TokenStream) -> bool:
        token = stream.peek()
        if token is None:
            return False
        if token.type == TokenType.EVALUATE:
            return True
        if token.type == TokenType.IDENTIFIER and token.value and token.value.upper() == "EVALUATE":
            return True
        # Recovery: Check if previous token was EVALUATE
        prev = stream.peek(-1)
        if prev:
            if prev.type == TokenType.EVALUATE or (
                prev.type == TokenType.IDENTIFIER and prev.value and prev.value.upper() == "EVALUATE"
            ):
                return True
        return False
    
    def matches(self, stream: TokenStream) -> bool:
        """IStatementParser interface - same as can_parse."""
        return self.can_parse(stream)

    def parse(self, stream: TokenStream) -> EvaluateStatement:
        """Parse EVALUATE statement structure only.

        Supports:
        - EVALUATE subject [ALSO subject]...
        - WHEN selector [ALSO selector]...
        - WHEN OTHER
        - END-EVALUATE terminator
        
        Does NOT parse nested statements - those are handled by the main parser.
        """
        # Get parse context from stream if available
        context = getattr(stream, '_parse_context', None)
        
        start_token = stream.peek()
        # Consume EVALUATE if present
        if start_token and (
            start_token.type == TokenType.EVALUATE
            or (start_token.type == TokenType.IDENTIFIER and start_token.value and start_token.value.upper() == "EVALUATE")
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
            token = stream.peek()
            if not token:
                break
            
            # Check for WHEN (end of subjects)
            if token.type == TokenType.WHEN:
                break
            
            token_val_upper = token.value.upper() if token.value else ""
            
            # Check for ALSO (additional subject)
            if token_val_upper == "ALSO":
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
                if subject_str and subject_str.upper() != "ALSO":
                    subjects.append(subject_str)
                    stmt.add_subject(subject_str)

        # Parse WHEN clauses - just extract structure, don't parse nested statements
        has_when_clause = False
        found_end_evaluate = False
        found_when_other = False

        while not stream.is_at_end:
            stream.skip_whitespace_and_comments()
            token = stream.peek()
            if not token:
                break
            
            token_val_upper = token.value.upper() if token.value else ""
            
            # Check for END-EVALUATE
            if token_val_upper == "END-EVALUATE":
                stream.advance()
                found_end_evaluate = True
                break
            
            # Check for WHEN
            if token_val_upper != "WHEN":
                # End of EVALUATE or other statement
                break
            
            has_when_clause = True
            when_loc = token.location
            stream.advance()  # Skip WHEN
            stream.skip_whitespace_and_comments()
            
            # Check for WHEN OTHER
            token = stream.peek()
            if token and token.value and token.value.upper() == "OTHER":
                # Validate WHEN OTHER comes last
                if found_when_other:
                    if context and hasattr(context, 'host') and context.host:
                        err = context.host.create_error(
                            "Multiple WHEN OTHER clauses not allowed",
                            location=when_loc
                        )
                        context.host.add_error(err)
                
                found_when_other = True
                stream.advance()  # Skip OTHER
                stream.skip_whitespace_and_comments()
                
                # Skip statements until END-EVALUATE or WHEN
                while not stream.is_at_end:
                    token = stream.peek()
                    if not token:
                        break
                    
                    token_val_upper = token.value.upper() if token.value else ""
                    if token_val_upper in ("WHEN", "END-EVALUATE"):
                        # Check if there's another WHEN after WHEN OTHER
                        if token_val_upper == "WHEN":
                            if context and hasattr(context, 'host') and context.host:
                                err = context.host.create_error(
                                    "WHEN OTHER must be the last WHEN clause",
                                    location=when_loc
                                )
                                context.host.add_error(err)
                        break
                    
                    stream.advance()
                    stream.skip_whitespace_and_comments()
                
                # WhenClause constructor expects (selectors: list, location: SourceLocation)
                when_clause = WhenClause([], when_loc)
                stmt.set_default_when(when_clause)
                continue
            
            # Parse selectors (collect but don't validate count against subjects)
            selectors = []
            selectors_found = False
            last_was_also = False
            
            while not stream.is_at_end:
                stream.skip_whitespace_and_comments()
                token = stream.peek()
                if not token:
                    break
                
                token_val_upper = token.value.upper() if token.value else ""
                
                # Check if we've reached statement keywords or WHEN/END-EVALUATE
                if token_val_upper in ("WHEN", "END-EVALUATE"):
                    break
                
                # Check for ALSO between selectors
                if token_val_upper == "ALSO":
                    if last_was_also:
                        # Consecutive ALSO keywords
                        if context and hasattr(context, 'host') and context.host:
                            err = context.host.create_error(
                                "Consecutive ALSO keywords without selector",
                                location=token.location
                            )
                            context.host.add_error(err)
                    last_was_also = True
                    stream.advance()  # Skip ALSO
                    selectors_found = True
                    stream.skip_whitespace_and_comments()
                    continue
                
                # Collect selector tokens
                selector_tokens = []
                paren_depth = 0
                while not stream.is_at_end:
                    token = stream.peek()
                    if not token:
                        break
                    
                    token_val_upper = token.value.upper() if token.value else ""
                    
                    # Stop at ALSO (between selectors) or WHEN/END-EVALUATE
                    if paren_depth == 0 and token_val_upper in ("ALSO", "WHEN", "END-EVALUATE"):
                        break
                    
                    # Stop at statement keywords (DISPLAY, PERFORM, MOVE, CALL, ACCEPT, etc.)
                    # These should not be part of selectors
                    if paren_depth == 0 and token.type in (
                        TokenType.DISPLAY, TokenType.PERFORM, TokenType.MOVE, TokenType.CALL,
                        TokenType.ACCEPT, TokenType.EVALUATE, TokenType.IF, TokenType.SEARCH,
                        TokenType.STRING, TokenType.UNSTRING, TokenType.STOP, TokenType.ENTRY,
                        TokenType.EXIT, TokenType.CONTINUE
                    ):
                        break
                    
                    if token.type == TokenType.LEFT_PAREN:
                        paren_depth += 1
                    elif token.type == TokenType.RIGHT_PAREN:
                        paren_depth -= 1
                    
                    # Skip NEWLINE tokens - they shouldn't be part of selectors
                    if token.type == TokenType.NEWLINE:
                        stream.advance()
                        stream.skip_whitespace_and_comments()
                        continue
                    
                    selector_tokens.append(token.value if token.value else "")
                    stream.advance()
                    stream.skip_whitespace_and_comments()
                
                if selector_tokens:
                    selector_str = " ".join(selector_tokens).strip()
                    if selector_str and selector_str.upper() != "ALSO":
                        selectors.append(selector_str)
                        selectors_found = True
                        last_was_also = False
                
                # If we didn't find ALSO, stop looking for more selectors
                stream.skip_whitespace_and_comments()
                token = stream.peek()
                if token and token.value and token.value.upper() != "ALSO":
                    break
            
            # Skip statements until next WHEN or END-EVALUATE
            # These will be picked up by the procedure division parser when it
            # continues parsing the paragraph
            while not stream.is_at_end:
                token = stream.peek()
                if not token:
                    break
                
                token_val_upper = token.value.upper() if token.value else ""
                
                # Stop at WHEN or END-EVALUATE
                if token_val_upper in ("WHEN", "END-EVALUATE"):
                    break
                
                stream.advance()
                stream.skip_whitespace_and_comments()
            
            # Create WHEN clause with selectors (statements will be added later)
            # Convert selector strings to selector dicts
            selector_dicts = []
            
            # Check for empty WHEN clause (no selectors at all)
            if not selectors:
                if context and hasattr(context, 'host') and context.host:
                    err = context.host.create_error(
                        "WHEN clause must have at least one selector",
                        location=when_loc
                    )
                    context.host.add_error(err)
            
            for selector_str in selectors:
                # Check for invalid THRU/THROUGH ranges
                selector_upper = selector_str.upper().strip()
                
                # Check if selector ends with THRU/THROUGH or contains them without end value
                if " THRU" in selector_upper or " THROUGH" in selector_upper:
                    # Valid patterns: "1 THRU 10", "1 THROUGH 10"
                    # Invalid patterns: "5 THRU", "5 THROUGH"
                    parts = selector_upper.split()
                    for i, part in enumerate(parts):
                        if part in ("THRU", "THROUGH"):
                            # Check if there's a value after THRU
                            if i == len(parts) - 1:  # THRU is last part
                                if context and hasattr(context, 'host') and context.host:
                                    err = context.host.create_error(
                                        "THRU/THROUGH range is incomplete - missing end value",
                                        location=when_loc
                                    )
                                    context.host.add_error(err)
                                break
                
                # Check for empty selectors
                if not selector_str.strip():
                    if context and hasattr(context, 'host') and context.host:
                        err = context.host.create_error(
                            "WHEN clause has empty selector",
                            location=when_loc
                        )
                        context.host.add_error(err)
                
                # Create appropriate selector dict based on selector type
                selector_upper = selector_str.upper().strip()
                
                # Check for special keywords: ANY
                if selector_upper == "ANY":
                    selector_dicts.append({"type": "Any"})
                # Check for ranges: THRU/THROUGH
                elif " THRU " in selector_upper or " THROUGH " in selector_upper:
                    # It's a range like "1 THRU 10" or "1 THROUGH 10"
                    parts = selector_str.split()
                    # Find the THRU/THROUGH keyword position
                    thru_idx = -1
                    for idx, part in enumerate(parts):
                        if part.upper() in ("THRU", "THROUGH"):
                            thru_idx = idx
                            break
                    
                    if thru_idx > 0 and thru_idx < len(parts) - 1:
                        # Valid range: start THRU end
                        start_val = " ".join(parts[:thru_idx])  # Could be "2" or more complex
                        end_val = " ".join(parts[thru_idx + 1:])
                        selector_dicts.append({
                            "type": "Range",
                            "start": start_val,
                            "end": end_val
                        })
                    else:
                        # Invalid range but create as literal for now
                        selector_dicts.append({"type": "Literal", "value": selector_str})
                # Check for conditions: AND/OR operators
                elif " AND " in selector_upper or " OR " in selector_upper:
                    # It's a condition expression
                    operator = "OR" if " OR " in selector_upper else "AND"
                    selector_dicts.append({
                        "type": "Condition",
                        "value": selector_str,
                        "operator": operator
                    })
                else:
                    # It's a literal value
                    selector_dicts.append({"type": "Literal", "value": selector_str})
            
            # Validate selector/subject count match
            if subjects and selectors and len(selectors) != len(subjects):
                if context and hasattr(context, 'host') and context.host:
                    err = context.host.create_error(
                        f"Selector count mismatch: expected {len(subjects)} selectors, got {len(selectors)}",
                        location=when_loc
                    )
                    context.host.add_error(err)
            
            when_clause = WhenClause(selector_dicts, when_loc)
            
            stmt.add_when_clause(when_clause)

        # Report missing END-EVALUATE error
        if not found_end_evaluate:
            if context and hasattr(context, 'host') and context.host:
                err = context.host.create_error(
                    "EVALUATE statement missing END-EVALUATE terminator",
                    location=start_token_loc
                )
                context.host.add_error(err)
        
        # Report missing WHEN clause error
        if not has_when_clause:
            if context and hasattr(context, 'host') and context.host:
                err = context.host.create_error(
                    "EVALUATE statement must have at least one WHEN clause",
                    location=start_token_loc
                )
                context.host.add_error(err)

        return stmt
