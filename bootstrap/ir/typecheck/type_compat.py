"""
bootstrap/ir/typecheck/type_compat.py

Verifikasi kecocokan tipe -- INTI dari perbaikan "type checker yang beneran
menegakkan tipe, bukan cuma mencatat nama tipe untuk codegen".

Sebelum modul ini ada, `TypeRef.name` di seluruh compiler cuma string mentah
yang tidak pernah dibandingkan secara semantik di titik-titik seperti:
    - let x: T = expr        (apakah tipe expr cocok T?)
    - f(args)                (apakah tipe tiap arg cocok parameter f?)
    - return expr            (apakah tipe expr cocok return_type fungsi?)

Modul ini menyediakan representasi tipe terstruktur (TypeKind) dan fungsi
tunggal `types_compatible()` yang jadi SATU-SATUNYA sumber kebenaran soal
"apakah tipe A boleh dipakai di tempat yang mengharapkan tipe B". Semua
titik pengecekan di hir_builder.py wajib manggil fungsi ini -- tidak boleh
ada perbandingan string manual tersebar di banyak tempat.

ATURAN KOMPATIBILITAS (keputusan desain, lihat diskusi sesi terkait):
    - STRICT, tidak ada implicit widening/narrowing sama sekali.
      i16 ke i64 tetap harus exact match -- kalau tidak, itu TypeCheckError.
    - Named type (struct/union/enum custom) harus persis sama namanya.
    - Array harus sama persis: ukuran (N) dan elemen (T) keduanya harus cocok.
"""

from __future__ import annotations

from dataclasses import dataclass


# ---------------------------------------------------------------------------
# TypeKind -- representasi tipe terstruktur
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class TypeKind:
    """Base class representasi tipe. Jangan diinstansiasi langsung."""
    pass


@dataclass(frozen=True)
class PrimitiveKind(TypeKind):
    """
    Tipe primitif bawaan bahasa.

    name salah satu dari: i8, i16, i32, i64, u8, u16, u32, u64,
    f32, f64, isize, usize, float, bool, string, void, unit.
    """
    name: str


@dataclass(frozen=True)
class ArrayKind(TypeKind):
    """
    Fixed-size array: [N]T.

    size dan element harus SAMA PERSIS antara dua ArrayKind supaya
    dianggap kompatibel -- lihat types_compatible().
    """
    size: int
    element: TypeKind


@dataclass(frozen=True)
class NamedKind(TypeKind):
    """
    Tipe custom (struct/union/enum) yang dirujuk lewat nama.

    name adalah nama tipe apa adanya (mis. "Option", "User").
    """
    name: str


@dataclass(frozen=True)
class UnknownKind(TypeKind):
    """
    Tipe yang gagal di-parse / tidak dikenal sama sekali.

    Sengaja dipisah dari None -- UnknownKind eksplisit menandakan
    "parsing tipe ini gagal", bukan "belum py diisi". types_compatible()
    SELALU return False kalau salah satu sisi UnknownKind, karena tidak
    ada dasar untuk bilang dua tipe yang gak dikenal itu "cocok".
    """
    raw: str


# ---------------------------------------------------------------------------
# Parsing: string type_name -> TypeKind
# ---------------------------------------------------------------------------

_PRIMITIVE_NAMES = frozenset({
    "i8", "i16", "i32", "i64",
    "u8", "u16", "u32", "u64",
    "f32", "f64",
    "isize", "usize", "float",
    "bool", "string", "str", "void", "unit",
})

# "str" adalah alias historis dari implementasi stage0 (codegen.py, dst)
# untuk tipe yang di spesifikasi bahasa (type_system.md) disebut "string".
# Dinormalisasi ke satu nama kanonik di sini supaya types_compatible tidak
# menganggap keduanya beda tipe.
_ALIAS_TO_CANONICAL = {
    "str": "string",
}

# Dipakai untuk memvalidasi apakah sebuah "expected type" dari context
# (mis. anotasi `let x: i64`) sah dijadikan tipe untuk literal numerik
# (IntLiteral/FloatLiteral). Integer literal cuma boleh "berubah bentuk"
# ke sesama tipe integer, float literal cuma ke sesama tipe float --
# TIDAK BOLEH lintas kelas (integer literal tidak bisa jadi f32 walau
# secara nilai memungkinkan, karena itu bukan literal apa adanya lagi).
_INTEGER_TYPE_NAMES = frozenset({
    "i8", "i16", "i32", "i64",
    "u8", "u16", "u32", "u64",
    "isize", "usize",
})

_FLOAT_TYPE_NAMES = frozenset({"f32", "f64", "float"})


def is_integer_type_name(type_name: str | None) -> bool:
    """True kalau type_name adalah salah satu tipe integer yang dikenal."""
    return type_name in _INTEGER_TYPE_NAMES


def is_float_type_name(type_name: str | None) -> bool:
    """True kalau type_name adalah salah satu tipe float yang dikenal."""
    return type_name in _FLOAT_TYPE_NAMES


def parse_type_kind(type_name: str | None) -> TypeKind:
    """
    Parse string type_name (dari TypeRef.name / AST type_name mentah)
    jadi representasi TypeKind terstruktur.

    Ini satu-satunya tempat yang boleh parsing sintaks tipe dari string --
    kalau butuh info terstruktur soal suatu tipe di tempat lain, panggil
    fungsi ini, jangan parsing manual lagi.
    """
    if type_name is None:
        return UnknownKind(raw="<none>")

    type_name = type_name.strip()

    # Array: [N]T -- N wajib angka (konsisten dengan parser.py yang sudah
    # menolak syntax array lain).
    if type_name.startswith("["):
        close = type_name.find("]")
        if close == -1:
            return UnknownKind(raw=type_name)
        size_str = type_name[1:close]
        element_str = type_name[close + 1:]
        if not size_str.isdigit():
            return UnknownKind(raw=type_name)
        size = int(size_str)
        element_kind = parse_type_kind(element_str)
        if isinstance(element_kind, UnknownKind):
            return UnknownKind(raw=type_name)
        return ArrayKind(size=size, element=element_kind)

    if type_name in _PRIMITIVE_NAMES:
        canonical_name = _ALIAS_TO_CANONICAL.get(type_name, type_name)
        return PrimitiveKind(name=canonical_name)

    # Bukan primitif dan bukan array -- anggap named type (struct/union/enum).
    # Validitas nama ini (apakah benar terdaftar di SymbolTable) adalah
    # tanggung jawab caller, bukan parse_type_kind -- modul ini murni syntax
    # parsing, bukan symbol resolution.
    if type_name.isidentifier():
        return NamedKind(name=type_name)

    return UnknownKind(raw=type_name)


# ---------------------------------------------------------------------------
# Kompatibilitas
# ---------------------------------------------------------------------------

def types_compatible(expected: TypeKind, actual: TypeKind) -> bool:
    """
    True kalau tipe `actual` boleh dipakai di tempat yang meminta `expected`.

    STRICT -- tidak ada implicit widening/narrowing. i16 tidak kompatibel
    dengan i64 meskipun secara nilai aman; keduanya harus exact match.
    """
    if isinstance(expected, UnknownKind) or isinstance(actual, UnknownKind):
        # Tidak ada dasar untuk bilang cocok kalau salah satu gagal
        # di-parse -- caller yang menentukan bagaimana meng-handle ini
        # (biasanya: skip check, karena ini kemungkinan besar limitasi
        # parser type_name, bukan kesalahan program yang sebenarnya).
        return False

    if isinstance(expected, PrimitiveKind) and isinstance(actual, PrimitiveKind):
        return expected.name == actual.name

    if isinstance(expected, ArrayKind) and isinstance(actual, ArrayKind):
        return (
            expected.size == actual.size
            and types_compatible(expected.element, actual.element)
        )

    if isinstance(expected, NamedKind) and isinstance(actual, NamedKind):
        return expected.name == actual.name

    # Kind yang berbeda (mis. Primitive vs Array) selalu tidak kompatibel.
    return False


def types_compatible_str(expected_name: str | None, actual_name: str | None) -> bool:
    """
    Convenience wrapper: terima string type_name langsung (bentuk yang
    paling sering tersedia di titik pemanggilan -- TypeRef.name, dsb),
    parse dulu ke TypeKind, baru bandingkan.
    """
    return types_compatible(
        parse_type_kind(expected_name),
        parse_type_kind(actual_name),
    )
