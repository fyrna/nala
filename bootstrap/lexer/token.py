# lexer/token.py
"""
Token definitions for Nala lexer.
"""
from __future__ import annotations
from dataclasses import dataclass
from enum import Enum, auto
from typing import Union


class KeywordKind(Enum):
    # --- Binding ---
    LET = auto()
    MUT = auto()
    CONST = auto()

    # --- Function ---
    FN = auto()
    RET = auto()

    # --- Composite type declaration ---
    STRUCT = auto()
    SUM = auto()
    ENUM = auto()
    TRAIT = auto()
    SATISFY = auto()
    TYPE = auto()  # meta-type `type` (type_system.md)

    # --- Function modifier ---
    INTERNAL = auto()
    INLINE = auto()
    COMP = auto()
    UNSAFE = auto()

    # --- Module ---
    USE = auto()
    AS = auto()

    # --- Control flow ---
    IF = auto()
    ELSE = auto()
    MATCH = auto()
    FOR = auto()
    LOOP = auto()
    IN = auto()
    BREAK = auto()
    CONTINUE = auto()
    DEFER = auto()

    # --- Error handling ---
    TRY = auto()

    # --- Boolean literal ---
    TRUE = auto()
    FALSE = auto()

    # --- Self ---
    SELF = auto()       # self (lowercase) -- parameter
    SELF_TYPE = auto()  # Self (uppercase) -- tipe abstrak, trait decl only

    # --- Special void-like types ---
    VOID = auto()
    UNIT = auto()
    SOLE = auto() # unit literal

    # --- Testing ---
    TEST = auto()

    # --- FFI ---
    FOREIGN = auto()

    # --- Logical ---
    AND = auto()
    OR = auto()

    # CATATAN: Primitive type names (i8/i32/bool/string/dst) SENGAJA
    # TIDAK ADA di sini -- lihat catatan module-level ("Lexer do
    # nothing"). Mereka lex sebagai Ident biasa.


class OperatorKind(Enum):
    PLUS = auto()    # +
    MINUS = auto()   # -
    STAR = auto()    # *
    SLASH = auto()   # /
    PERCENT = auto() # %
    EQ = auto()      # =
    GT = auto()      # >
    LT = auto()      # <

    EQ_EQ = auto()      # ==
    NOT_EQ = auto()     # !=
    GT_EQ = auto()      # >=
    LT_EQ = auto()      # <=
    PLUS_EQ = auto()    # +=
    MINUS_EQ = auto()   # -=
    STAR_EQ = auto()    # *=
    SLASH_EQ = auto()   # /=
    PERCENT_EQ = auto() # %=

    BANG = auto()       # ! -- unary not, DAN suffix intrinsic (sizeof!, self!, dst)
    AMPERSAND = auto()  # & -- &T, &mut T
    PIPE = auto()       # | -- bitwise or, flags, OR-pattern
    CARET = auto()      # ^ -- bitwise xor
    TILDE = auto()      # ~ -- bitwise not
    SHL = auto()        # << -- shift left
    SHR = auto()        # >> -- shift right
    AT = auto()         # @ -- binding pattern (r @ 1..10)
    RANGE = auto()      # .. -- range inclusive
    RANGE_EXCL = auto() # ..< -- range exclusive upper bound


class DelimiterKind(Enum):
    LPAREN = auto()    # (
    RPAREN = auto()    # )
    LBRACE = auto()    # {
    RBRACE = auto()    # }
    LBRACKET = auto()  # [
    RBRACKET = auto()  # ]
    COMMA = auto()     # ,
    COLON = auto()     # :
    ARROW = auto()     # ->
    FAT_ARROW = auto() # =>
    SEMICOLON = auto() # ;
    DOT = auto()       # .
    HASH = auto()      # #


class LiteralKind(Enum):
    IDENT = auto()
    BACKTICK_IDENT = auto()  # `for`, `1`, `my-var` (language.md)
    INT_LITERAL = auto()
    FLOAT_LITERAL = auto()
    STRING_LITERAL = auto()
    BYTE_LITERAL = auto()
    UNIT_LITERAL = auto()


class SpecialKind(Enum):
    UNKNOWN = auto()
    EOF = auto()


@dataclass(frozen=True)
class Keyword:
    value: KeywordKind


@dataclass(frozen=True)
class Operator:
    value: OperatorKind


@dataclass(frozen=True)
class Delimiter:
    value: DelimiterKind


@dataclass(frozen=True)
class Literal:
    value: LiteralKind


@dataclass(frozen=True)
class Special:
    value: SpecialKind


TokenKind = Union[Keyword, Operator, Delimiter, Literal, Special]


@dataclass(frozen=True)
class Span:
    """Token position: start/end offsets (0-indexed), line/col (1-indexed)."""
    start: int
    end: int
    line: int
    col: int


@dataclass(frozen=True)
class Token:
    """
    Lexical unit: kind, source text, span.

    `text` -- representasi text token itu sendiri APA ADANYA (mis.
    "100u32", "let", "+=")
    """
    kind: TokenKind
    text: str
    span: Span


_KEYWORDS: dict[str, KeywordKind] = {
    "let": KeywordKind.LET,
    "mut": KeywordKind.MUT,
    "const": KeywordKind.CONST,

    "fn": KeywordKind.FN,
    "ret": KeywordKind.RET,

    "struct": KeywordKind.STRUCT,
    "sum": KeywordKind.SUM,
    "enum": KeywordKind.ENUM,
    "trait": KeywordKind.TRAIT,
    "satisfy": KeywordKind.SATISFY,
    "type": KeywordKind.TYPE,

    "internal": KeywordKind.INTERNAL,
    "inline": KeywordKind.INLINE,
    "comp": KeywordKind.COMP,
    "unsafe": KeywordKind.UNSAFE,

    "use": KeywordKind.USE,
    "as": KeywordKind.AS,

    "if": KeywordKind.IF,
    "else": KeywordKind.ELSE,
    "match": KeywordKind.MATCH,
    "for": KeywordKind.FOR,
    "loop": KeywordKind.LOOP,
    "in": KeywordKind.IN,
    "break": KeywordKind.BREAK,
    "continue": KeywordKind.CONTINUE,
    "defer": KeywordKind.DEFER,

    "try": KeywordKind.TRY,

    "true": KeywordKind.TRUE,
    "false": KeywordKind.FALSE,

    "self": KeywordKind.SELF,
    "Self": KeywordKind.SELF_TYPE,

    "void": KeywordKind.VOID,
    "unit": KeywordKind.UNIT,
    "sole": KeywordKind.SOLE,

    "test": KeywordKind.TEST,
    "foreign": KeywordKind.FOREIGN,

    "and": KeywordKind.AND,
    "or": KeywordKind.OR,
}


def is_keyword(text: str) -> bool:
    """Check if text is a reserved keyword."""
    return text in _KEYWORDS


def get_keyword_kind(text: str) -> "KeywordKind | None":
    """Get KeywordKind for keyword text, or None if not a keyword."""
    return _KEYWORDS.get(text)

def describe_token_kind(kind: TokenKind) -> str:
    """
    Format TokenKind untuk pesan error yang manusiawi -- mis.
    "Keyword.LET", "Operator.PLUS", "Delimiter.LBRACE".
    """
    return f"{type(kind).__name__}.{kind.value.name}"
