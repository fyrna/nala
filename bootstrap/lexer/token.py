# lexer/token.py
"""
Token definitions for Nala lexer.
Contains TokenKind enum, Span, and Token dataclasses.
"""
from __future__ import annotations
from dataclasses import dataclass
from enum import Enum, auto


class TokenKind(Enum):
    # Literals
    IDENT = auto()
    INT_LITERAL = auto()
    FLOAT_LITERAL = auto()
    STRING_LITERAL = auto()
    BYTE_LITERAL = auto()

    # Operators
    PLUS = auto() # +
    MINUS = auto() # -
    STAR = auto() # *
    SLASH = auto() # /
    PERCENT = auto() # %
    EQ = auto() # =
    GT = auto() # >
    LT = auto() # <
    EQ_EQ = auto() # ==
    PLUS_EQ = auto() # +=
    GT_EQ = auto() # >=
    LT_EQ = auto() # <=
    BANG = auto() # !, !unary, intristik!
    AMPERSAND = auto() # &, &T, &mut T

    # Delimiters
    LPAREN = auto() # (
    RPAREN = auto() # )
    LBRACE = auto() # {
    RBRACE = auto() # }
    LBRACKET = auto() # {
    RBRACKET = auto() # }
    COMMA = auto() # ,
    COLON = auto() # :
    ARROW = auto() # ->
    FAT_ARROW = auto() # =>
    SEMICOLON = auto() # ;
    DOT = auto() # .

    # Keywords
    LET = auto()
    MUT = auto()
    FN = auto()
    USE = auto()
    AS = auto()
    UNKNOWN = auto()
    EOF = auto()


@dataclass(frozen=True)
class Span:
    """Token position: start/end offsets (0-indexed), line/col (1-indexed)."""
    start: int
    end: int
    line: int
    col: int


@dataclass(frozen=True)
class Token:
    """Lexical unit: kind, original text, span."""
    kind: TokenKind
    text: str
    span: Span


# Keyword mapping
_KEYWORDS = {
    "let": TokenKind.LET,
    "mut": TokenKind.MUT,
    "fn": TokenKind.FN,
    "use": TokenKind.USE,
    "as": TokenKind.AS,
}


def is_keyword(text: str) -> bool:
    """Check if text is a keyword."""
    return text in _KEYWORDS


def get_keyword_kind(text: str) -> TokenKind | None:
    """Get TokenKind for keyword, or None if not a keyword."""
    return _KEYWORDS.get(text)
