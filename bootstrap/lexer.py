"""
bootstrap/lexer.py

Tokenizer untuk source .na — bagian dari bootstrap (Python), dipakai untuk
membaca semua file .na

(eum, awalnya mirror lexer.na dan sejenisnya. Tapi karena development fokus ke parser dulu, aku rasa ini jadi note saja.)

DESAIN DAN ARSITEKTUR:
    Lexer adalah komponen frontend paling dasar yang bertugas mengubah
    source code menjadi stream of tokens. Desainnya mengikuti prinsip:
        1. One-pass scanning: Scan source dari kiri ke kanan sekali saja
        2. Lookahead satu karakter: Hanya perlu peek satu karakter ke depan
           untuk menentukan token multi-karakter (==, ->, +=, >=, <=, =>)
        3. No backtracking: Setelah maju, tidak pernah mundur
        4. Error recovery: Karakter tak dikenal menghasilkan TokenKind.UNKNOWN
           bukan exception, memungkinkan parser untuk melaporkan error lebih baik
    
    Token-token yang dihasilkan memiliki informasi posisi (Span) yang penting
    untuk error reporting dan debugging.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto
from typing import Optional


class TokenKind(Enum):
    """
    Jenis-jenis token dalam bahasa Nala.
    
    Klasifikasi token:
        1. Literal: Nilai mentah dari source code
           - IDENT: Nama variabel/fungsi/modul
           - INT_LITERAL: Bilangan bulat (42)
           - FLOAT_LITERAL: Bilangan pecahan (3.14)
           - STRING_LITERAL: String UTF-8 ("hello")
           - BYTE_LITERAL: Satu byte ASCII ('a')
        
        2. Operator:
           - Aritmetika: PLUS, MINUS, STAR, SLASH
           - Perbandingan: EQ_EQ, GT_EQ, LT_EQ, GT, LT
           - Assignment: EQ, PLUS_EQ
           - Logika: BANG (digunakan juga untuk intrinsic seperti print!)
        
        3. Delimiter:
           - Kurung: LPAREN, RPAREN, LBRACE, RBRACE, LBRACKET, RBRACKET
           - Pemisah: COMMA, COLON, SEMICOLON, DOT
           - Panah: ARROW (-> return type), FAT_ARROW (=> match arm)
        
        4. Keyword: LET, MUT, FN
        
        5. Special:
           - AMPERSAND: Untuk reference parameter (&self, &mut self)
           - UNKNOWN: Fallback untuk karakter tak dikenal
           - EOF: End of file marker
    """
    # literal — nilai mentah disimpan di Token.text
    IDENT = auto()
    INT_LITERAL = auto()
    FLOAT_LITERAL = auto()
    STRING_LITERAL = auto()
    BYTE_LITERAL = auto()  # 'a', '0', dst -- SATU byte ASCII, delimiter '
                           # (bukan "). BUKAN untuk Unicode/non-ASCII (mis.
                           # China) -- itu tetap ranah STRING_LITERAL yang
                           # UTF-8 aware. Konsisten dengan asumsi ASCII-only
                           # yang sudah diakui sebagai utang teknis lexer.

    # operator dasar
    PLUS = auto()   # +
    MINUS = auto()  # -
    STAR = auto()   # *
    SLASH = auto()  # /
    EQ = auto()     # =
    EQ_EQ = auto()  # ==
    PLUS_EQ = auto()  # += -- compound assignment, dua karakter, sama pola
                       # lookahead dengan EQ_EQ/ARROW
    GT_EQ = auto()  # >= -- dua karakter, satu token, sama pola dengan EQ_EQ
    LT_EQ = auto()  # <= -- dua karakter, satu token, sama pola dengan EQ_EQ
    BANG = auto()   # ! -- CATATAN: '!' di Nala punya dua peran (operator
                    # logika DAN sufiks intrinsic print!/sizeof!/dst).
                    # Secara lexical tetap satu token yang sama -- beda
                    # makna ditentukan dari posisi, itu tugas parser.
    AMPERSAND = auto()  # & -- untuk reference parameter &self, &mut self

    # delimiter
    LPAREN = auto()  # (
    RPAREN = auto()  # )
    LBRACE = auto()  # {
    RBRACE = auto()  # }
    LBRACKET = auto()  # [
    RBRACKET = auto()  # ]
    COMMA = auto()   # ,
    COLON = auto()   # :
    ARROW = auto()     # -> (return type, dua karakter, satu token)
    FAT_ARROW = auto()   # => (match arm separator, sama pola lookahead)
    GT = auto()            # > (standalone, bukan >=)
    LT = auto()            # < (standalone, bukan <=)
    SEMICOLON = auto()  # ; — wajib di akhir setiap statement, lihat Language.md
    DOT = auto()       # . -- untuk field access (self.pos) dan method call

    # keyword minimal
    LET = auto()
    MUT = auto()
    FN = auto()

    # fallback eksplisit untuk karakter tak dikenal — TIDAK BOLEH jatuh ke EOF.
    UNKNOWN = auto()

    # control
    EOF = auto()


# Mapping keyword ke token kind untuk identifikasi cepat
_KEYWORDS = {
    "let": TokenKind.LET,
    "mut": TokenKind.MUT,
    "fn": TokenKind.FN,
}


@dataclass(frozen=True)
class Span:
    """
    Representasi posisi sebuah token dalam source code.
    
    Digunakan untuk:
        1. Error reporting: Menunjukkan di mana error terjadi
        2. Debugging: Melacak asal token
        3. Source mapping: Untuk tools seperti linter atau formatter
    
    Attributes:
        start (int): Offset karakter awal (inclusive), 0-indexed
        end (int): Offset karakter akhir (exclusive), 0-indexed
        line (int): Nomor baris (1-indexed) untuk user-friendly error messages
        col (int): Nomor kolom (1-indexed) untuk user-friendly error messages
    """
    start: int  # offset karakter awal, inclusive
    end: int    # offset karakter akhir, exclusive
    line: int   # baris, 1-indexed
    col: int    # kolom, 1-indexed

@dataclass(frozen=True)
class Token:
    """
    Unit dasar hasil lexing: sebuah token dengan jenis, teks, dan posisi.
    
    Token adalah hasil akhir dari proses lexing yang akan dikonsumsi oleh parser.
    Setiap token menyimpan informasi lengkap tentang apa yang ditemukan di source.
    
    Attributes:
        kind (TokenKind): Jenis token (IDENT, INT_LITERAL, PLUS, dll)
        text (str): Teks asli dari source yang membentuk token ini
        span (Span): Posisi token di source code
    """
    kind: TokenKind
    text: str
    span: Span


class LexError(Exception):
    """
    Exception untuk error fatal dalam proses lexing.
    
    Berbeda dengan TokenKind.UNKNOWN yang merupakan recovery mechanism,
    LexError digunakan untuk situasi yang tidak bisa direcovery:
        1. Unterminated string literal
        2. Unterminated byte literal
        3. Invalid escape sequences (belum diimplementasikan)
    
    Error ini akan menghentikan proses kompilasi karena source code
    tidak bisa dilanjutkan dengan aman.
    """
    pass

class Lexer:
    """
    Lexer utama untuk bahasa Nala - melakukan scanning source code ke token stream.
    
    State machine sederhana dengan satu karakter lookahead. Lexer mempertahankan
    state berupa posisi, baris, dan kolom saat scanning.
    
    ALUR KERJA:
        1. next_token() dipanggil
        2. Skip whitespace dan komentar
        3. Identifikasi karakter pertama:
           - Huruf/underscore → identifier/keyword
           - Digit → number (int/float)
           - " → string literal
           - ' → byte literal
           - Lainnya → symbol/operator
        4. Konsumsi karakter sesuai aturan token
        5. Kembalikan Token
    
    PRINSIP DESAIN:
        1. One-pass: Scan sekali, tidak pernah backtrack
        2. Lookahead satu: Cukup peek 1 karakter untuk token multi-char
        3. Deterministik: Setiap karakter punya tepat satu transisi
        4. Error resilient: Token UNKNOWN untuk karakter tak dikenal
    
    CATATAN IMPLEMENTASI:
        Operasi string Python (len(), indexing, slicing, isalpha(), dll)
        digunakan langsung karena lexer Python ini tidak akan ditranspile
        ke Nala - ia adalah bagian dari bootstrap compiler yang berjalan
        di Python.
    """
    
    def __init__(self, source: str):
        """
        Inisialisasi lexer dengan source code yang akan di-scan.
        
        Args:
            source (str): Source code Nala dalam bentuk string
        """
        self.source = source
        self.pos = 0
        self.line = 1
        self.col = 1

    def next_token(self) -> Token:
        """
        Ambil token berikutnya dari source code.
        
        Fungsi ini adalah entry point utama lexer. Dipanggil berulang
        oleh parser sampai mendapatkan TokenKind.EOF.
        
        Returns:
            Token: Token berikutnya dari source code
            
        Note:
            - Whitespace dan komentar akan dilewati secara otomatis
            - Karakter tak dikenal menghasilkan TokenKind.UNKNOWN
            - EOF ditandai dengan TokenKind.EOF
        """
        self._skip_whitespace_and_comments()

        start_pos, start_line, start_col = self.pos, self.line, self.col

        if self._is_eof():
            return Token(
                kind=TokenKind.EOF,
                text="",
                span=Span(start_pos, start_pos, start_line, start_col),
            )

        c = self._current()

        # Branching berdasarkan karakter pertama
        if c.isalpha() or c == "_":
            return self._lex_ident_or_keyword(start_pos, start_line, start_col)

        if c.isdigit():
            return self._lex_number(start_pos, start_line, start_col)

        if c == '"':
            return self._lex_string(start_pos, start_line, start_col)

        if c == "'":
            return self._lex_byte(start_pos, start_line, start_col)

        # Jika tidak ada yang cocok, treat sebagai symbol/operator
        return self._lex_symbol(start_pos, start_line, start_col)

    def _is_eof(self) -> bool:
        """Cek apakah sudah mencapai akhir source code."""
        return self.pos >= len(self.source)

    def _current(self) -> str:
        """Ambil karakter saat ini tanpa memajukan posisi.
        
        Precondition: self._is_eof() harus False
        """
        return self.source[self.pos]

    def _peek(self) -> Optional[str]:
        """Intip karakter berikutnya tanpa memajukan posisi.
        
        Digunakan untuk mendeteksi token multi-karakter seperti ==, ->, +=.
        
        Returns:
            Optional[str]: Karakter berikutnya, atau None jika EOF
        """
        if self.pos + 1 >= len(self.source):
            return None
        return self.source[self.pos + 1]

    def _advance(self) -> None:
        """
        Maju satu karakter dan update posisi baris/kolom.
        
        Penting: Fungsi ini HARUS dipanggil setelah semua lookahead selesai.
        Salah urutan pemanggilan dapat menyebabkan tokenizing error.
        """
        if self._current() == "\n":
            self.line += 1
            self.col = 1
        else:
            self.col += 1
        self.pos += 1

    def _skip_whitespace_and_comments(self) -> None:
        """
        Lewati whitespace dan komentar sampai menemukan token berikutnya.
        
        Whitespace yang dilewati:
            - Spasi (' ')
            - Tab ('\t')
            - Carriage return ('\r')
            - Newline ('\n')
        
        Komentar:
            - Single-line: // sampai akhir baris
        """
        while not self._is_eof():
            c = self._current()

            # Skip whitespace
            if c in (" ", "\t", "\r", "\n"):
                self._advance()
                continue

            # Skip single-line comment
            if c == "/" and self._peek() == "/":
                while not self._is_eof() and self._current() != "\n":
                    self._advance()
                continue

            # Bukan whitespace atau comment → stop
            break

    def _lex_ident_or_keyword(self, start_pos: int, start_line: int, start_col: int) -> Token:
        """
        Lex identifier atau keyword.
        
        Aturan:
            - Mulai dengan huruf atau underscore
            - Lanjut dengan alfanumerik atau underscore
            - Case-sensitive (let != LET)
        
        Keyword yang dikenali: let, mut, fn
        Selain itu dianggap IDENT (identifier biasa).
        """
        while not self._is_eof() and (self._current().isalnum() or self._current() == "_"):
            self._advance()

        text = self.source[start_pos:self.pos]
        kind = _KEYWORDS.get(text, TokenKind.IDENT)

        return Token(kind=kind, text=text, span=Span(start_pos, self.pos, start_line, start_col))

    def _lex_number(self, start_pos: int, start_line: int, start_col: int) -> Token:
        """
        Lex integer atau float literal.
        
        Format:
            - Integer: 42, 1234
            - Float: 3.14, 0.5 (harus ada digit di kedua sisi titik)
        
        Catatan:
            - Belum support exponent (1e10)
            - Belum support underscore separator (1_000_000)
            - Konsisten dengan implementasi di lexer.na
        """
        is_float = False

        # Konsumsi digit-digit pertama
        while not self._is_eof() and self._current().isdigit():
            self._advance()

        # Cek apakah ada titik yang diikuti digit (float)
        if not self._is_eof() and self._current() == ".":
            nxt = self._peek()
            if nxt is not None and nxt.isdigit():
                is_float = True
                self._advance()  # konsumsi '.'
                while not self._is_eof() and self._current().isdigit():
                    self._advance()

        text = self.source[start_pos:self.pos]
        kind = TokenKind.FLOAT_LITERAL if is_float else TokenKind.INT_LITERAL

        return Token(kind=kind, text=text, span=Span(start_pos, self.pos, start_line, start_col))

    def _lex_string(self, start_pos: int, start_line: int, start_col: int) -> Token:
        """
        Lex string literal yang diapit double quote (").
        
        Format: "hello world"
        
        Note:
            - Belum handle escape sequences (\", \n, \t, dll)
            - Belum handle string kosong ("")
            - UTF-8 aware karena menggunakan Python string
            
        Raises:
            LexError: Jika string tidak ditutup (unterminated)
        """
        self._advance()  # konsumsi opening quote

        # Konsumsi sampai menemukan closing quote
        while not self._is_eof() and self._current() != '"':
            self._advance()

        if self._is_eof():
            raise LexError(
                f"unterminated string literal dimulai di baris {start_line}, kolom {start_col}"
            )
        self._advance()  # konsumsi closing quote

        text = self.source[start_pos:self.pos]

        return Token(
            kind=TokenKind.STRING_LITERAL,
            text=text,
            span=Span(start_pos, self.pos, start_line, start_col),
        )

    def _lex_byte(self, start_pos: int, start_line: int, start_col: int) -> Token:
        """
        Lex byte literal yang diapit single quote (').
        
        Format: 'a', '0', '\n' (belum support escape)
        
        Perbedaan dengan string literal:
            - Byte literal SELALU tepat satu karakter ASCII
            - Menggunakan single quote (')
            - String literal menggunakan double quote (")
            - Byte literal untuk karakter ASCII saja, bukan Unicode
        
        Note:
            - Belum handle escape sequences (\\')
            - Belum handle empty byte literal ('')
            - Belum validasi bahwa isinya satu karakter
            
        Raises:
            LexError: Jika byte literal tidak ditutup (unterminated)
        """
        self._advance()  # konsumsi opening '

        # Konsumsi satu karakter isi byte literal
        if not self._is_eof():
            self._advance()

        if self._is_eof():
            raise LexError(
                f"unterminated byte literal dimulai di baris {start_line}, kolom {start_col}"
            )
        self._advance()  # konsumsi closing '

        text = self.source[start_pos:self.pos]

        return Token(
            kind=TokenKind.BYTE_LITERAL,
            text=text,
            span=Span(start_pos, self.pos, start_line, start_col),
        )

    def _lex_symbol(self, start_pos: int, start_line: int, start_col: int) -> Token:
        """
        Lex symbol/operator yang terdiri dari satu atau dua karakter.
        
        Dua karakter (lookahead):
            - ==, +=, ->, =>, >=, <=
        
        Satu karakter:
            - +, -, *, /, (, ), {, }, [, ], <, >, ,, :, ;, ., &, !
        
        Penting (bug fix penting):
            _peek() HARUS dipanggil SEBELUM _advance() apapun terjadi.
            _peek() mengintip source[pos+1] relatif ke posisi SAAT INI
            (sebelum konsumsi) — bukan posisi setelah karakter pertama
            dikonsumsi. Kalau _advance() dipanggil dulu baru _peek(),
            maka _peek() akan mengintip SATU POSISI TERLALU JAUH ke depan.
            
            Ini adalah bug nyata yang pernah terjadi dan ditangkap oleh
            test "a == b" yang keliru menjadi EQ,EQ dan "->" yang tidak
            terdeteksi.
        """
        c = self._current()

        # Mapping untuk symbol satu karakter
        simple = {
            "+": TokenKind.PLUS,
            "*": TokenKind.STAR,
            "/": TokenKind.SLASH,
            "(": TokenKind.LPAREN,
            ")": TokenKind.RPAREN,
            "{": TokenKind.LBRACE,
            "}": TokenKind.RBRACE,
            "[": TokenKind.LBRACKET,
            "]": TokenKind.RBRACKET,
            ">": TokenKind.GT,
            "<": TokenKind.LT,
            ",": TokenKind.COMMA,
            ":": TokenKind.COLON,
            ";": TokenKind.SEMICOLON,
            ".": TokenKind.DOT,
            "&": TokenKind.AMPERSAND,
        }

        # Deteksi token dua karakter (HARUS pakai _peek() SEBELUM _advance())
        if c == "=" and self._peek() == "=":
            self._advance()  # konsumsi '=' pertama
            self._advance()  # konsumsi '=' kedua
            kind = TokenKind.EQ_EQ
        elif c == "+" and self._peek() == "=":
            self._advance()  # konsumsi '+'
            self._advance()  # konsumsi '='
            kind = TokenKind.PLUS_EQ
        elif c == "=" and self._peek() == ">":
            self._advance()  # konsumsi '='
            self._advance()  # konsumsi '>'
            kind = TokenKind.FAT_ARROW
        elif c == "-" and self._peek() == ">":
            self._advance()  # konsumsi '-'
            self._advance()  # konsumsi '>'
            kind = TokenKind.ARROW
        elif c == ">" and self._peek() == "=":
            self._advance()  # konsumsi '>'
            self._advance()  # konsumsi '='
            kind = TokenKind.GT_EQ
        elif c == "<" and self._peek() == "=":
            self._advance()  # konsumsi '<'
            self._advance()  # konsumsi '='
            kind = TokenKind.LT_EQ
        else:
            # Token satu karakter
            self._advance()  # konsumsi satu karakter tunggal
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
                # karakter tak dikenal -> UNKNOWN, bukan EOF
                # (sama seperti perbaikan yang sudah dilakukan di lexer.na)
                kind = simple.get(c, TokenKind.UNKNOWN)

        text = self.source[start_pos:self.pos]

        return Token(kind=kind, text=text, span=Span(start_pos, self.pos, start_line, start_col))


def tokenize_all(source: str) -> list[Token]:
    """
    Helper untuk debugging/testing — panggil next_token() berulang sampai EOF.
    
    Fungsi ini mengumpulkan semua token dari source code ke dalam list.
    Berguna untuk:
        - Debugging lexer behavior
        - Testing tokenization results
        - Visual inspection of token stream
    
    Note:
        Ini BUKAN mengulang kesalahan yang sudah kita hindari di lexer.na
        (tokenize() -> ArrayList<Token>) — di sana masalahnya adalah lexer.na
        akan menyeret dependency std.ArrayList yang belum bootstrap-able.
        Di lexer.py, list Python bawaan tidak punya masalah sirkularitas
        semacam itu, jadi helper ini aman dipakai murni untuk keperluan
        debug/dump.
    
    Args:
        source (str): Source code Nala
        
    Returns:
        list[Token]: Daftar semua token dalam source code
    """
    tokens = []
    lexer = Lexer(source)
    while True:
        tok = lexer.next_token()
        tokens.append(tok)
        if tok.kind == TokenKind.EOF:
            break
    return tokens


if __name__ == "__main__":
    """
    Entry point untuk debugging lexer secara mandiri.
    
    Penggunaan:
        python lexer.py <file.na>
    
    Output:
        Daftar token dengan format:
            <TOKEN_KIND> <text> <Span(start, end, line, col)>
    
    Berguna untuk:
        - Memeriksa hasil tokenisasi sebelum parser
        - Debugging token yang tidak sesuai
        - Verifikasi implementasi lexer
    """
    import sys

    if len(sys.argv) != 2:
        print("usage: python lexer.py <file.na>")
        sys.exit(1)

    with open(sys.argv[1], "r", encoding="utf-8") as f:
        src = f.read()

    for t in tokenize_all(src):
        print(f"{t.kind.name:15} {t.text!r:20} {t.span}")
