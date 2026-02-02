from typing import Dict, Type, Optional, List
from .interfaces import StatementParser
from .token_stream import TokenStream
from ..lexer import TokenType

class StatementRegistry:
    """Maps tokens to their corresponding parsers."""
    
    def __init__(self):
        self._parsers: List[StatementParser] = []
    
    def register(self, parser: StatementParser) -> None:
        self._parsers.append(parser)
    
    def get_parser(self, stream: TokenStream) -> Optional[StatementParser]:
        for parser in self._parsers:
            if parser.can_parse(stream):
                return parser
        return None
