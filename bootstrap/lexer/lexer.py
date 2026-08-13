# lexer/lexer.py
"""
Tokenizer for Nala source. One-pass scanning, 1-char lookahead.
"""
from __future__ import annotations
from typing import Optional

from lexer.token import (
    Token, TokenKind, Span,
    Keyword, Operator, Delimiter, Literal, Special,
    KeywordKind, OperatorKind, DelimiterKind, LiteralKind, SpecialKind,
    get_keyword_kind,
)


class LexError(Exception):
    """Fatal lexing error (e.g., unterminated string/byte/backtick literal)."""
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
            return Token(Special(SpecialKind.EOF), "", Span(start_pos, start_pos, start_line, start_col))

        c = self._current()
    
        if c.isalpha() or c == "_":
            return self._lex_ident_or_keyword(start_pos, start_line, start_col)
        if c.isdigit():
            return self._lex_number(start_pos, start_line, start_col)
        if c == '"':
            return self._lex_string(start_pos, start_line, start_col)
        if c == "'":
            return self._lex_byte(start_pos, start_line, start_col)
        if c == "`":
            return self._lex_backtick_ident(start_pos, start_line, start_col)
        return self._lex_symbol(start_pos, start_line, start_col)

    def _is_eof(self) -> bool:
        return self.pos >= len(self.source)

    def _current(self) -> str:
        return self.source[self.pos]

    def _peek(self, offset: int = 1) -> Optional[str]:
        idx = self.pos + offset
        if idx >= len(self.source):
            return None
        return self.source[idx]

    def _advance(self) -> str:
        """Advance satu karakter, return karakter yang baru saja dilewati."""
        c = self._current()

        if c == "\n":
            self.line += 1
            self.col = 1
        else:
            self.col += 1
    
        self.pos += 1
        return c

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

    def _lex_ident_or_keyword(self, start_pos: int, start_line: int, start_col: int) -> Token:
        """
        Identifier, keyword
        """
        while not self._is_eof() and (self._current().isalnum() or self._current() == "_"):
            self._advance()

        text = self.source[start_pos:self.pos]
        span = Span(start_pos, self.pos, start_line, start_col)

        keyword_kind = get_keyword_kind(text)
        if keyword_kind is not None:
            return Token(Keyword(keyword_kind), text, span)

        return Token(Literal(LiteralKind.IDENT), text, span)

    def _lex_backtick_ident(self, start_pos: int, start_line: int, start_col: int) -> Token:
        """
        Backtick identifier: `for`, `1`, `my-var` (language.md). Isi di
        antara backtick BEBAS -- boleh keyword, boleh angka, boleh
        karakter non-alphanumeric seperti '-'. Lexer tidak validasi isi
        sama sekali di sini, cukup ambil apa adanya sampai backtick
        penutup -- validitas sebagai identifier yang sah adalah urusan
        parser/checker.
        """
        self._advance()  # `
        while not self._is_eof() and self._current() != "`":
            self._advance()

        if self._is_eof():
            raise LexError(f"unterminated backtick identifier at {start_line}:{start_col}")

        self._advance()  # closing `
        text = self.source[start_pos:self.pos]
        # text termasuk backtick pembuka/penutup -- parser yang strip
        # kalau perlu nama polosnya.
        return Token(Literal(LiteralKind.BACKTICK_IDENT), text, Span(start_pos, self.pos, start_line, start_col))

    # Suffix set -- HANYA berlaku untuk literal DESIMAL/BINARY, TIDAK
    # PERNAH untuk HEX. Alasan: f32/f64 (satu-satunya suffix float)
    # collision langsung dengan karakter hex digit ('f'/'F' valid hex
    # digit) -- 0xAf32 secara greedy-scan SELALU dibaca habis sebagai
    # hex digits "Af32" (semuanya valid 0-9a-fA-F), TIDAK PERNAH sampai
    # ke titik "coba cocokkan suffix" sama sekali. Ini bukan
    # keterbatasan yang perlu pesan error khusus -- hex literal secara
    # semantik SELALU integer (tidak ada hex-float di Nala), jadi
    # "hex + suffix float" tidak pernah masuk akal ditulis programmer;
    # dan suffix integer (u32, i64, dst) SEBENARNYA tidak collision
    # dengan hex digit sama sekali ('u'/'i'/'s' bukan hex digit) --
    # TAPI supaya aturannya SATU aturan simpel yang konsisten (bukan
    # "suffix integer boleh di hex, suffix float tidak boleh"), hex
    # literal SAMA SEKALI tidak mencoba scan suffix apa pun. Programmer
    # yang butuh hex dengan tipe spesifik pakai context (let x: u32 =
    # 0xFF;), persis seperti sebelum revisi suffix ada.
    _INT_SUFFIXES = ("isize", "usize", "i8", "i16", "i32", "i64", "u8", "u16", "u32", "u64")
    _FLOAT_SUFFIXES = ("f32", "f64")

    def _try_lex_suffix(self, allowed: tuple[str, ...]) -> str:
        """
        Coba cocokkan salah satu suffix di `allowed` PERSIS di posisi
        `self.pos` saat ini, TIDAK overlap dengan identifier lain yang
        kebetulan diawali huruf sama (mis. "100isizeof" HARUS gagal
        cocok "isize" -- suffix wajib diikuti karakter yang BUKAN
        alnum/underscore, kalau tidak itu bukan suffix, itu literal
        diikuti identifier tanpa spasi yang salah bentuk, dibiarkan
        gagal secara natural di parser). Return string suffix yang
        cocok (SUDAH meng-advance self.pos), atau "" kalau tidak ada
        yang cocok (self.pos TIDAK berubah).

        Longest-match TIDAK dibutuhkan secara eksplisit di sini walau
        "i8"/"i16"/"i32"/"i64"/"isize" sama-sama diawali 'i' -- karena
        Python `in` loop di bawah mencoba SEMUA kandidat dan set
        _INT_SUFFIXES sengaja diurutkan "isize"/"usize" (5 char) LEBIH
        DULU dari "i8" dst (supaya "isize" tidak keburu cuma cocok "i"
        lalu sisa "size" dianggap bukan bagian suffix -- tapi karena
        tidak ada suffix yang merupakan PREFIX suffix lain kecuali
        kasus ini, urutan eksplisit di tuple _INT_SUFFIXES cukup
        sebagai jaminan, tanpa perlu sorting dinamis di sini).
        """
        for candidate in allowed:
            end = self.pos + len(candidate)

            if self.source[self.pos:end] == candidate:
                after = self.source[end:end + 1]
                if after and (after.isalnum() or after == "_"):
                    continue  # bukan suffix murni -- ada identifier nyambung

                for _ in candidate:
                    self._advance()
                return candidate

        return ""

    def _lex_number(self, start_pos: int, start_line: int, start_col: int) -> Token:
        """
        Integer atau float literal. Mendukung:
        - Decimal dengan underscore separator: 1_000_000
        - Hex: 0xFF, 0xDEAD_BEEF
        - Binary: 0b1010, 0b1111_0000
        - Float: 1.0, 3.14 (titik HARUS diikuti digit, kalau tidak
          titik itu bukan bagian dari angka -- mis. "5.method()")
        - Type suffix valid & MENANG MUTLAK atas context kalau ada konflik
        """
        # Hex / binary prefix
        if self._current() == "0" and self._peek() in ("x", "X"):
            self._advance()  # 0
            self._advance()  # x
        
            while not self._is_eof() and (self._current() in "0123456789abcdefABCDEF_"):
                self._advance()
                
            text = self.source[start_pos:self.pos]
            return Token(Literal(LiteralKind.INT_LITERAL), text, Span(start_pos, self.pos, start_line, start_col))

        if self._current() == "0" and self._peek() in ("b", "B"):
            self._advance()  # 0
            self._advance()  # b
            
            while not self._is_eof() and (self._current() in "01_"):
                self._advance()
                
            self._try_lex_suffix(self._INT_SUFFIXES)
            text = self.source[start_pos:self.pos]
            return Token(Literal(LiteralKind.INT_LITERAL), text, Span(start_pos, self.pos, start_line, start_col))

        # Decimal, dengan underscore separator
        is_float = False
        
        while not self._is_eof() and (self._current().isdigit() or self._current() == "_"):
            self._advance()
            
        if not self._is_eof() and self._current() == ".":
            nxt = self._peek()
            
            if nxt is not None and nxt.isdigit():
                is_float = True
                self._advance()  # .
                
                while not self._is_eof() and (self._current().isdigit() or self._current() == "_"):
                    self._advance()
                    
        if is_float:
            self._try_lex_suffix(self._FLOAT_SUFFIXES)
        else:
            self._try_lex_suffix(self._INT_SUFFIXES)

        text = self.source[start_pos:self.pos]
        kind = Literal(LiteralKind.FLOAT_LITERAL) if is_float else Literal(LiteralKind.INT_LITERAL)
        return Token(kind, text, Span(start_pos, self.pos, start_line, start_col))

    _ESCAPE_MAP = {
        "n": "\n",
        '"': '"',
        "\\": "\\",
    }

    def _lex_string(self, start_pos: int, start_line: int, start_col: int) -> Token:
        """
        Double-quoted string dengan escape sequence dasar: \\n, \\", \\\\.
        Token.text menyimpan HASIL SETELAH escape diproses (bukan raw
        source dengan backslash literal) -- konsumer token tidak perlu
        proses escape lagi sendiri.
        """
        self._advance()  # opening "
        chars: list[str] = []
        
        while not self._is_eof() and self._current() != '"':
            c = self._current()
            
            if c == "\\":
                self._advance()  # backslash
                if self._is_eof():
                    raise LexError(f"unterminated escape sequence at {self.line}:{self.col}")
                
                esc = self._current()
                if esc not in self._ESCAPE_MAP:
                    raise LexError(
                        f"unknown escape sequence '\\{esc}' at {self.line}:{self.col} "
                        f"-- didukung hanya \\n, \\\", \\\\"
                    )
                
                chars.append(self._ESCAPE_MAP[esc])
                self._advance()  # karakter setelah backslash
            else:
                chars.append(c)
                self._advance()
                
        if self._is_eof():
            raise LexError(f"unterminated string literal at {start_line}:{start_col}")
        
        self._advance()  # closing "
        return Token(Literal(LiteralKind.STRING_LITERAL), "".join(chars), Span(start_pos, self.pos, start_line, start_col))

    def _lex_byte(self, start_pos: int, start_line: int, start_col: int) -> Token:
        """Single-quoted ASCII byte literal (no escape handling yet)."""
        self._advance()  # '
        
        if not self._is_eof():
            self._advance()
            
        if self._is_eof():
            raise LexError(f"unterminated byte literal at {start_line}:{start_col}")
        
        self._advance()  # closing '
        text = self.source[start_pos:self.pos]
        return Token(Literal(LiteralKind.BYTE_LITERAL), text, Span(start_pos, self.pos, start_line, start_col))

    def _lex_symbol(self, start_pos: int, start_line: int, start_col: int) -> Token:
        """
        Single or multi-char symbol/operator. IMPORTANT: peek() MUST be
        called before any advance() -- semua multi-char operator (termasuk
        ..< ) konsisten ditangani DI SINI, tidak ada yang sengaja dipecah
        jadi 2 token lalu dibebankan ke parser untuk digabungkan.
        """
        c = self._current()

        # 3-char lookahead dulu (paling panjang -- ..< )
        if c == "." and self._peek() == "." and self._peek(2) == "<":
            self._advance()
            self._advance()
            self._advance()
            return Token(Operator(OperatorKind.RANGE_EXCL), "..<", Span(start_pos, self.pos, start_line, start_col))

        # 2-char lookahead
        two_char_map = {
            ("=", "="): Operator(OperatorKind.EQ_EQ),
            ("!", "="): Operator(OperatorKind.NOT_EQ),
            ("+", "="): Operator(OperatorKind.PLUS_EQ),
            ("-", "="): Operator(OperatorKind.MINUS_EQ),
            ("*", "="): Operator(OperatorKind.STAR_EQ),
            ("/", "="): Operator(OperatorKind.SLASH_EQ),
            ("%", "="): Operator(OperatorKind.PERCENT_EQ),
            ("=", ">"): Delimiter(DelimiterKind.FAT_ARROW),
            ("-", ">"): Delimiter(DelimiterKind.ARROW),
            (">", "="): Operator(OperatorKind.GT_EQ),
            ("<", "="): Operator(OperatorKind.LT_EQ),
            ("<", "<"): Operator(OperatorKind.SHL),
            (">", ">"): Operator(OperatorKind.SHR),
            (".", "."): Operator(OperatorKind.RANGE),
        }
        nxt = self._peek()
        
        if nxt is not None and (c, nxt) in two_char_map:
            kind = two_char_map[(c, nxt)]
            
            self._advance()
            self._advance()
            return Token(kind, self.source[start_pos:self.pos], Span(start_pos, self.pos, start_line, start_col))

        # Single-char
        single_char_map = {
            "+": Operator(OperatorKind.PLUS),
            "-": Operator(OperatorKind.MINUS),
            "*": Operator(OperatorKind.STAR),
            "/": Operator(OperatorKind.SLASH),
            "%": Operator(OperatorKind.PERCENT),
            "=": Operator(OperatorKind.EQ),
            ">": Operator(OperatorKind.GT),
            "<": Operator(OperatorKind.LT),
            "!": Operator(OperatorKind.BANG),
            "&": Operator(OperatorKind.AMPERSAND),
            "|": Operator(OperatorKind.PIPE),
            "^": Operator(OperatorKind.CARET),
            "~": Operator(OperatorKind.TILDE),
            "@": Operator(OperatorKind.AT),
            "(": Delimiter(DelimiterKind.LPAREN),
            ")": Delimiter(DelimiterKind.RPAREN),
            "{": Delimiter(DelimiterKind.LBRACE),
            "}": Delimiter(DelimiterKind.RBRACE),
            "[": Delimiter(DelimiterKind.LBRACKET),
            "]": Delimiter(DelimiterKind.RBRACKET),
            ",": Delimiter(DelimiterKind.COMMA),
            ":": Delimiter(DelimiterKind.COLON),
            ";": Delimiter(DelimiterKind.SEMICOLON),
            ".": Delimiter(DelimiterKind.DOT),
            "#": Delimiter(DelimiterKind.HASH),
        }
        
        self._advance()
        kind = single_char_map.get(c, Special(SpecialKind.UNKNOWN))
        return Token(kind, c, Span(start_pos, self.pos, start_line, start_col))


# testing purpose
# i think ill do this to each bootstrap step.
def tokenize_all(source: str) -> list[Token]:
    """Debug helper: collect all tokens from source."""
    tokens = []
    lexer = Lexer(source)
    
    while True:
        tok = lexer.next_token()
        tokens.append(tok)
        
        if isinstance(tok.kind, Special) and tok.kind.value is SpecialKind.EOF:
            break
        
    return tokens


if __name__ == "__main__":
    import sys
    if len(sys.argv) != 2:
        print("usage: python -m lexer.lexer <file.na>")
        sys.exit(1)
    with open(sys.argv[1], "r", encoding="utf-8") as f:
        src = f.read()
    for t in tokenize_all(src):
        print(f"{type(t.kind).__name__}.{t.kind.value.name:20} {t.text!r:20} {t.span}")
