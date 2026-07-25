# bootstrap/lexer.py
"""
Tokenizer for Nala source. One-pass scanning, 1-char lookahead, UNKNOWN fallback.
Token includes kind, text, Span(start,end,line,col).
"""
from __future__ import annotations
from dataclasses import dataclass
from enum import Enum, auto
from typing import Optional

class TokenKind(Enum):
    # Literals: IDENT, INT_LITERAL, FLOAT_LITERAL, STRING_LITERAL, BYTE_LITERAL
    IDENT = auto()
    INT_LITERAL = auto()
    FLOAT_LITERAL = auto()
    STRING_LITERAL = auto()
    BYTE_LITERAL = auto()
    # Operators: PLUS, MINUS, STAR, SLASH, EQ, EQ_EQ, PLUS_EQ, GT_EQ, LT_EQ, BANG, AMPERSAND
    PLUS = auto()
    MINUS = auto()
    STAR = auto()
    SLASH = auto()
    EQ = auto()
    EQ_EQ = auto()
    PLUS_EQ = auto()
    GT_EQ = auto()
    LT_EQ = auto()
    BANG = auto()
    AMPERSAND = auto()
    # Delimiters: parens, braces, brackets, comma, colon, semicolon, dot, arrows
    LPAREN = auto()
    RPAREN = auto()
    LBRACE = auto()
    RBRACE = auto()
    LBRACKET = auto()
    RBRACKET = auto()
    COMMA = auto()
    COLON = auto()
    ARROW = auto()
    FAT_ARROW = auto()
    GT = auto()
    LT = auto()
    SEMICOLON = auto()
    DOT = auto()
    # Keywords
    LET = auto()
    MUT = auto()
    FN = auto()
    UNKNOWN = auto()
    EOF = auto()

_KEYWORDS = {
    "let": TokenKind.LET,
    "mut": TokenKind.MUT,
    "fn": TokenKind.FN,
}

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

class LexError(Exception):
    """Fatal lexing error (e.g., unterminated string/byte literal)."""
    pass

class Lexer:
    """
    One-pass scanner with 1-char lookahead. Skips whitespace/comments.
    next_token() returns next token; EOF at end.
    """
    def __init__(self, source: str):
        self.source = source
        self.pos = 0
        self.line = 1
        self.col = 1

    def next_token(self) -> Token:
        """Return next token, skipping whitespace/comments. EOF on end."""
        self._skip_whitespace_and_comments()
        start_pos, start_line, start_col = self.pos, self.line, self.col
        if self._is_eof():
            return Token(TokenKind.EOF, "", Span(start_pos,start_pos,start_line,start_col))
        c = self._current()
        if c.isalpha() or c == "_":
            return self._lex_ident_or_keyword(start_pos,start_line,start_col)
        if c.isdigit():
            return self._lex_number(start_pos,start_line,start_col)
        if c == '"':
            return self._lex_string(start_pos,start_line,start_col)
        if c == "'":
            return self._lex_byte(start_pos,start_line,start_col)
        return self._lex_symbol(start_pos,start_line,start_col)

    def _is_eof(self) -> bool:
        return self.pos >= len(self.source)

    def _current(self) -> str:
        return self.source[self.pos]

    def _peek(self) -> Optional[str]:
        if self.pos + 1 >= len(self.source):
            return None
        return self.source[self.pos + 1]

    def _advance(self) -> None:
        if self._current() == "\n":
            self.line += 1
            self.col = 1
        else:
            self.col += 1
        self.pos += 1

    def _skip_whitespace_and_comments(self) -> None:
        """Skip spaces, tabs, newlines, and // comments."""
        while not self._is_eof():
            c = self._current()
            if c in (" ", "\t", "\r", "\n"):
                self._advance()
            elif c == "/" and self._peek() == "/":
                while not self._is_eof() and self._current() != "\n":
                    self._advance()
            else:
                break

    def _lex_ident_or_keyword(self, start_pos:int, start_line:int, start_col:int) -> Token:
        """Identifier or keyword (let, mut, fn)."""
        while not self._is_eof() and (self._current().isalnum() or self._current() == "_"):
            self._advance()
        text = self.source[start_pos:self.pos]
        kind = _KEYWORDS.get(text, TokenKind.IDENT)
        return Token(kind, text, Span(start_pos,self.pos,start_line,start_col))

    def _lex_number(self, start_pos:int, start_line:int, start_col:int) -> Token:
        """Integer or float literal (no exponent/underscore support yet)."""
        is_float = False
        while not self._is_eof() and self._current().isdigit():
            self._advance()
        if not self._is_eof() and self._current() == ".":
            nxt = self._peek()
            if nxt is not None and nxt.isdigit():
                is_float = True
                self._advance()
                while not self._is_eof() and self._current().isdigit():
                    self._advance()
        text = self.source[start_pos:self.pos]
        kind = TokenKind.FLOAT_LITERAL if is_float else TokenKind.INT_LITERAL
        return Token(kind, text, Span(start_pos,self.pos,start_line,start_col))

    def _lex_string(self, start_pos:int, start_line:int, start_col:int) -> Token:
        """Double-quoted string (no escape handling yet)."""
        self._advance()  # "
        while not self._is_eof() and self._current() != '"':
            self._advance()
        if self._is_eof():
            raise LexError(f"unterminated string literal at {start_line}:{start_col}")
        self._advance()  # closing "
        text = self.source[start_pos:self.pos]
        return Token(TokenKind.STRING_LITERAL, text, Span(start_pos,self.pos,start_line,start_col))

    def _lex_byte(self, start_pos:int, start_line:int, start_col:int) -> Token:
        """Single-quoted ASCII byte literal (no escape handling yet)."""
        self._advance()  # '
        if not self._is_eof():
            self._advance()
        if self._is_eof():
            raise LexError(f"unterminated byte literal at {start_line}:{start_col}")
        self._advance()  # closing '
        text = self.source[start_pos:self.pos]
        return Token(TokenKind.BYTE_LITERAL, text, Span(start_pos,self.pos,start_line,start_col))

    def _lex_symbol(self, start_pos:int, start_line:int, start_col:int) -> Token:
        """
        Single or multi-char symbol/operator.
        IMPORTANT: peek() MUST be called before any advance().
        """
        c = self._current()
        simple = {
            "+": TokenKind.PLUS, "*": TokenKind.STAR, "/": TokenKind.SLASH,
            "(": TokenKind.LPAREN, ")": TokenKind.RPAREN,
            "{": TokenKind.LBRACE, "}": TokenKind.RBRACE,
            "[": TokenKind.LBRACKET, "]": TokenKind.RBRACKET,
            ">": TokenKind.GT, "<": TokenKind.LT,
            ",": TokenKind.COMMA, ":": TokenKind.COLON,
            ";": TokenKind.SEMICOLON, ".": TokenKind.DOT,
            "&": TokenKind.AMPERSAND,
        }
        if c == "=" and self._peek() == "=":
            self._advance(); self._advance(); kind = TokenKind.EQ_EQ
        elif c == "+" and self._peek() == "=":
            self._advance(); self._advance(); kind = TokenKind.PLUS_EQ
        elif c == "=" and self._peek() == ">":
            self._advance(); self._advance(); kind = TokenKind.FAT_ARROW
        elif c == "-" and self._peek() == ">":
            self._advance(); self._advance(); kind = TokenKind.ARROW
        elif c == ">" and self._peek() == "=":
            self._advance(); self._advance(); kind = TokenKind.GT_EQ
        elif c == "<" and self._peek() == "=":
            self._advance(); self._advance(); kind = TokenKind.LT_EQ
        else:
            self._advance()
            if c == "=":
                kind = TokenKind.EQ
            elif c == "-":
                kind = TokenKind.MINUS
            elif c == "!":
                kind = TokenKind.BANG
            elif c == ">":
                kind = TokenKind.GT
            elif c == "<":
                kind = TokenKind.LT
            else:
                kind = simple.get(c, TokenKind.UNKNOWN)
        text = self.source[start_pos:self.pos]
        return Token(kind, text, Span(start_pos,self.pos,start_line,start_col))

def tokenize_all(source: str) -> list[Token]:
    """Debug helper: collect all tokens from source."""
    tokens = []
    lexer = Lexer(source)
    while True:
        tok = lexer.next_token()
        tokens.append(tok)
        if tok.kind == TokenKind.EOF:
            break
    return tokens

if __name__ == "__main__":
    import sys
    if len(sys.argv) != 2:
        print("usage: python lexer.py <file.na>")
        sys.exit(1)
    with open(sys.argv[1], "r", encoding="utf-8") as f:
        src = f.read()
    for t in tokenize_all(src):
        print(f"{t.kind.name:15} {t.text!r:20} {t.span}")
