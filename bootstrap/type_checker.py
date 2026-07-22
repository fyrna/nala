"""
type_checker.py

Tanggung jawab TUNGGAL modul ini: resolusi semantik AST hasil parser.

Filosofi: "Parser shall know nothing except language syntax."
Semua keputusan semantik — termasuk resolusi ambiguitas syntax dan
attach metadata — dilakukan di sini. Codegen HANYA menerjemahkan.

ARSITEKTUR DAN ALUR:

Parser menghasilkan AST "raw" dengan node netral:
    - DottedAccess: `base.name` (tanpa kurung)
    - DottedCall: `base.name(args...)` (dengan kurung)

Type checker mengubah AST raw menjadi AST final:
    1. Resolve DottedAccess:
       - Jika base adalah union → UnionLiteral (payload=None)
       - Jika base adalah enum → EnumVariantAccess
       - Jika base adalah variable/instance → FieldAccess
    
    2. Resolve DottedCall:
       - Jika base adalah union → UnionLiteral (payload dari args)
       - Jika base adalah variable/instance → MethodCall
       - Enum → error (enum tidak punya payload)
    
    3. Attach metadata semantik:
       - MatchStmt.union_name (derive dari arm pertama)
       - MatchArm.bind_type (dari payload type variant)
       - MethodCall.struct_name (dari tipe objek)
    
    4. (Future) Exhaustiveness checking, type consistency, dll

PRINSIP DESAIN:
    - Type checker adalah satu-satunya yang membuat keputusan semantik
    - Menggunakan SymbolTable untuk lookup deklarasi top-level
    - Traversal AST dilakukan secara post-order (resolve anak dulu)
    - Local type tracking untuk inferensi tipe variabel

OUTPUT: AST final yang bebas dari node netral dan sudah lengkap metadata-nya.
Codegen hanya menerjemahkan AST final tanpa inferensi tambahan.
"""

from __future__ import annotations

import dataclasses

from nala_ast import (
    EnumDecl, StructDecl, UnionDecl,
    FnDecl, LetStmt, StructLiteral,
    DottedAccess, DottedCall,
    UnionLiteral, EnumVariantAccess, FieldAccess, MethodCall,
    MatchStmt, MatchArm,
    Ident,
)


class TypeCheckError(Exception):
    """
    Kegagalan resolusi semantik — bukan kegagalan syntax.

    Exception ini dilempar ketika:
        - Referensi ke union/enum variant yang tidak dikenal
        - Union variant dipanggil dengan jumlah argumen yang salah
        - Match arm tidak konsisten (union berbeda)
        - Binding pada variant yang tidak punya payload
        - Enum variant dipanggil seperti fungsi (dengan kurung)

    Berbeda dengan ParseError (syntax error), TypeCheckError adalah
    semantic error yang terjadi setelah parsing berhasil.
    """
    pass


class SymbolTable:
    """
    Tabel nama type top-level, dikumpulkan sekali dari hasil parse_program().

    SymbolTable menyimpan informasi tentang deklarasi tipe di level global:
        - Union declarations: nama, variants, dan payload types
        - Enum declarations: nama dan variants
        - Struct declarations: nama (untuk method resolution)

    Hanya menyimpan NAMA (bukan detail field/variant) — cukup untuk
    menjawab pertanyaan "apakah identifier ini merujuk ke union/enum
    yang terdaftar, atau bukan?". Detail lebih dalam (jumlah payload
    variant, dst) belum dibutuhkan modul ini.

    STRUKTUR DATA:
        - union_names: set[str] - semua union yang dideklarasikan
        - enum_names: set[str] - semua enum yang dideklarasikan
        - struct_names: set[str] - semua struct yang dideklarasikan
        - union_variants: dict[str, set[str]] - variant per union
        - enum_variants: dict[str, set[str]] - variant per enum
        - union_payload_types: dict[str, dict[str, str | None]]
            - Untuk stage0: 0 atau 1 payload per variant
            - None berarti unit variant (tanpa payload)
    """

    def __init__(self) -> None:
        self.union_names: set[str] = set()
        self.enum_names: set[str] = set()
        self.struct_names: set[str] = set()

        # union_name -> set nama variant miliknya (untuk validasi variant
        # yang benar-benar ada, mencegah typo lolos diam-diam)
        self.union_variants: dict[str, set[str]] = {}
        self.enum_variants: dict[str, set[str]] = {}

        # union_name -> dict[variant_name, payload_type | None]
        # Untuk stage0: 0 atau 1 payload per variant
        self.union_payload_types: dict[str, dict[str, str | None]] = {}

    @classmethod
    def build(cls, decls: list) -> "SymbolTable":
        """
        Build SymbolTable dari list deklarasi top-level.

        Iterasi semua deklarasi dan kumpulkan informasi tentang:
            - Union: nama, variants, dan payload types
            - Enum: nama dan variants
            - Struct: nama (untuk method lookup)

        Args:
            decls: List of AST nodes dari parser

        Returns:
            SymbolTable: Tabel simbol yang sudah terisi
        """
        table = cls()
        for decl in decls:
            if isinstance(decl, UnionDecl):
                table.union_names.add(decl.name)
                table.union_variants[decl.name] = {v.name for v in decl.variants}
                table.union_payload_types[decl.name] = {}
                for v in decl.variants:
                    if len(v.payload_types) > 0:
                        table.union_payload_types[decl.name][v.name] = v.payload_types[0]
                    else:
                        table.union_payload_types[decl.name][v.name] = None
            elif isinstance(decl, EnumDecl):
                table.enum_names.add(decl.name)
                table.enum_variants[decl.name] = set(decl.variants)
            elif isinstance(decl, StructDecl):
                table.struct_names.add(decl.name)
        return table


def _resolve_dotted_access(node: DottedAccess, table: SymbolTable, local_types: dict[str, str]) -> "Expr":
    """
    Resolusi bentuk TANPA kurung: `base.name`.

    Prioritas resolusi:
        1. Union: base adalah union → UnionLiteral (unit variant)
        2. Enum: base adalah enum → EnumVariantAccess
        3. Lainnya: base adalah variable/instance → FieldAccess

    Args:
        node: DottedAccess node yang akan di-resolve
        table: SymbolTable untuk lookup type declarations
        local_types: Dictionary tipe variabel lokal

    Returns:
        UnionLiteral | EnumVariantAccess | FieldAccess

    Raises:
        TypeCheckError: Jika variant tidak dikenal di union/enum
    """
    base_name = node.base.name if isinstance(node.base, Ident) else None

    # 1. Union — prioritas tertinggi.
    if base_name is not None and base_name in table.union_names:
        known_variants = table.union_variants.get(base_name, set())
        if node.name not in known_variants:
            raise TypeCheckError(
                f"\'{node.name}\' bukan variant yang dikenal di union "
                f"\'{base_name}\' (variant yang ada: {sorted(known_variants)})"
            )
        return UnionLiteral(union_name=base_name, variant_name=node.name, payload=None)

    # 2. Enum — prioritas kedua.
    if base_name is not None and base_name in table.enum_names:
        known_variants = table.enum_variants.get(base_name, set())
        if node.name not in known_variants:
            raise TypeCheckError(
                f"\'{node.name}\' bukan variant yang dikenal di enum "
                f"\'{base_name}\' (variant yang ada: {sorted(known_variants)})"
            )
        return EnumVariantAccess(enum_name=base_name, variant_name=node.name)

    # 3. Selain itu — instance/variable biasa, field access.
    return FieldAccess(obj=node.base, field=node.name)


def _resolve_dotted_call(
    node: DottedCall, table: SymbolTable, current_struct_name: str | None, local_types: dict[str, str]
) -> "Expr":
    """
    Resolusi bentuk DENGAN kurung: `base.name(args...)`.

    Prioritas resolusi:
        1. Union: base adalah union → UnionLiteral (payload dari args)
        2. Enum: error (enum tidak punya payload)
        3. Lainnya: base adalah variable/instance → MethodCall

    Args:
        node: DottedCall node yang akan di-resolve
        table: SymbolTable untuk lookup type declarations
        current_struct_name: Nama struct yang sedang diproses (untuk self)
        local_types: Dictionary tipe variabel lokal

    Returns:
        UnionLiteral | MethodCall

    Raises:
        TypeCheckError: Jika variant tidak dikenal, atau enum dipanggil,
                       atau payload > 1 (belum support)
    """
    base_name = node.base.name if isinstance(node.base, Ident) else None

    # 1. Union — konstruktor variant dengan payload.
    if base_name is not None and base_name in table.union_names:
        known_variants = table.union_variants.get(base_name, set())
        if node.name not in known_variants:
            raise TypeCheckError(
                f"\'{node.name}\' bukan variant yang dikenal di union "
                f"\'{base_name}\' (variant yang ada: {sorted(known_variants)})"
            )
        if len(node.args) > 1:
            # Stage0: UnionLiteral.payload masih satu slot. Union variant
            # dengan >1 payload (mis. Rectangle(float, float)) belum
            # didukung representasi AST-nya — sengaja dibiarkan menyusul,
            # bukan dipaksakan sekarang (kesepakatan sebelumnya).
            raise TypeCheckError(
                f"Union variant \'{base_name}.{node.name}\' dipanggil dengan "
                f"{len(node.args)} argumen, tapi stage0 baru mendukung "
                f"maksimal 1 payload per variant. Payload-list multi-value "
                f"belum diimplementasikan."
            )
        payload = node.args[0] if len(node.args) == 1 else None
        return UnionLiteral(union_name=base_name, variant_name=node.name, payload=payload)

    # 2. Enum — enum tidak pernah punya bentuk pemanggilan (tidak ada payload).
    if base_name is not None and base_name in table.enum_names:
        raise TypeCheckError(
            f"\'{base_name}.{node.name}(...)\' tidak valid — \'{base_name}\' "
            f"adalah enum, enum variant tidak pernah punya payload/kurung."
        )

    # 3. Selain itu — instance/variable biasa, method call.
    #    struct_name diambil dari tipe objek (dari local_types tracking),
    #    atau fallback ke current_struct_name kalau objeknya adalah `self`.
    struct_name = current_struct_name
    if base_name is not None:
        # Coba lookup tipe dari local variable tracking
        if base_name in local_types:
            struct_name = local_types[base_name]
        elif base_name == "self" and current_struct_name is not None:
            struct_name = current_struct_name

    return MethodCall(
        obj=node.base,
        method=node.name,
        args=node.args,
        struct_name=struct_name,
    )


def _resolve_expr(expr, table: SymbolTable, current_struct_name: str | None, local_types: dict[str, str]):
    """
    Traversal rekursif generik untuk semua kemungkinan bentuk Expr.

    STRATEGI POST-ORDER:
        1. Turun dulu ke semua field anak (rekursif)
        2. Resolve node saat ini (jika DottedAccess/DottedCall)

    Ini penting karena base dari DottedAccess/DottedCall mungkin berupa
    ekspresi kompleks yang perlu di-resolve terlebih dahulu.

    Args:
        expr: Ekspresi yang akan di-resolve
        table: SymbolTable untuk lookup
        current_struct_name: Nama struct saat ini (untuk self)
        local_types: Tipe variabel lokal

    Returns:
        Expr: Ekspresi yang sudah di-resolve (atau tetap sama)
    """
    if expr is None or not dataclasses.is_dataclass(expr):
        return expr

    # Turun dulu ke semua field anak (post-order).
    for f in dataclasses.fields(expr):
        value = getattr(expr, f.name)
        if dataclasses.is_dataclass(value):
            setattr(expr, f.name, _resolve_expr(value, table, current_struct_name, local_types))
        elif isinstance(value, list):
            new_list = []
            for item in value:
                if dataclasses.is_dataclass(item):
                    new_list.append(_resolve_expr(item, table, current_struct_name, local_types))
                elif isinstance(item, tuple):
                    # Kasus khusus: StructLiteral.fields berbentuk
                    # list[tuple[str, Expr]] -- (nama_field, value_expr).
                    # Cuma elemen Expr di dalam tuple yang perlu diresolusi,
                    # nama field (str) dibiarkan apa adanya.
                    new_item = tuple(
                        _resolve_expr(part, table, current_struct_name, local_types)
                        if dataclasses.is_dataclass(part)
                        else part
                        for part in item
                    )
                    new_list.append(new_item)
                else:
                    new_list.append(item)
            setattr(expr, f.name, new_list)

    # Resolusi node saat ini, kalau memang DottedAccess/DottedCall.
    if isinstance(expr, DottedAccess):
        return _resolve_dotted_access(expr, table, local_types)
    if isinstance(expr, DottedCall):
        return _resolve_dotted_call(expr, table, current_struct_name, local_types)

    return expr


def _collect_local_types(stmts: list, table: SymbolTable) -> dict[str, str]:
    """
    Kumpulkan tipe variabel lokal dari LetStmt di dalam body fungsi.

    Mendeteksi tipe variabel dari:
        1. Anotasi eksplisit: `let x: Type = value`
        2. Inferensi dari struct literal: `let x = Type { ... }`

    Mengembalikan dictionary: nama_variabel -> tipe Nala.

    Args:
        stmts: List of statements dalam body fungsi
        table: SymbolTable (untuk future type checking)

    Returns:
        dict[str, str]: Mapping nama variabel ke tipe
    """
    local_types: dict[str, str] = {}
    for stmt in stmts:
        if isinstance(stmt, LetStmt):
            type_name = stmt.type_name
            # Kalau tidak ada anotasi eksplisit, coba infer dari struct literal
            if type_name is None and isinstance(stmt.value, StructLiteral):
                type_name = stmt.value.type_name
            if type_name is not None:
                local_types[stmt.name] = type_name
    return local_types


def _resolve_stmt(stmt, table: SymbolTable, current_struct_name: str | None, local_types: dict[str, str]):
    """
    Traversal rekursif untuk statement — sama strateginya seperti _resolve_expr.

    Fungsi ini dipisah dari _resolve_expr murni untuk kejelasan nama
    (menegaskan bahwa titik masuk body FnDecl adalah statement, bukan ekspresi),
    meskipun secara mekanisme sama.

    Args:
        stmt: Statement yang akan di-resolve
        table: SymbolTable untuk lookup
        current_struct_name: Nama struct saat ini
        local_types: Tipe variabel lokal

    Returns:
        Stmt: Statement yang sudah di-resolve
    """
    return _resolve_expr(stmt, table, current_struct_name, local_types)


def _resolve_match_stmt(stmt: MatchStmt, table: SymbolTable) -> None:
    """
    Attach metadata semantik ke MatchStmt dan MatchArm.

    Proses:
        1. Derive union_name dari arm pertama
        2. Validasi: semua arm harus dari union yang sama
        3. Validasi: variant yang disebut benar-benar ada di union
        4. Attach bind_type ke setiap arm yang punya binding

    Metadata ini digunakan oleh codegen untuk:
        - Generate switch statement yang benar
        - Extract payload dengan tipe yang tepat
        - Type-safe pattern matching

    Args:
        stmt: MatchStmt yang akan di-attach metadata
        table: SymbolTable untuk lookup

    Raises:
        TypeCheckError: Jika arms tidak konsisten atau variant tidak dikenal
    """
    if not stmt.arms:
        return

    # Derive union_name dari arm pertama
    first_arm = stmt.arms[0]
    union_name = first_arm.union
    if union_name is None:
        raise TypeCheckError(
            "Match statement memiliki arm tanpa union name explicit — "
            "stage0 memerlukan format Union.Variant"
        )

    # Validasi: semua arm harus dari union yang sama
    for arm in stmt.arms:
        if arm.union != union_name:
            raise TypeCheckError(
                f"Match arm \'{arm.union}.{arm.variant}\' tidak konsisten — "
                f"semua arm harus dari union yang sama (\'{union_name}\')."
            )
        # Validasi variant ada di union
        known_variants = table.union_variants.get(union_name, set())
        if arm.variant not in known_variants:
            raise TypeCheckError(
                f"\'{arm.variant}\' bukan variant yang dikenal di union "
                f"\'{union_name}\' (variant yang ada: {sorted(known_variants)})"
            )

    stmt.union_name = union_name

    # Attach bind_type untuk setiap arm yang punya binding
    payload_types = table.union_payload_types.get(union_name, {})
    for arm in stmt.arms:
        if arm.bind is not None:
            arm.bind_type = payload_types.get(arm.variant)
            if arm.bind_type is None:
                raise TypeCheckError(
                    f"Match arm \'{union_name}.{arm.variant}\' memiliki binding "
                    f"\'{arm.bind}\', tapi variant ini tidak punya payload."
                )


def check_program(decls: list) -> list:
    """
    Entry point utama. Terima hasil Parser.parse_program(), kembalikan
    AST yang sudah bebas dari DottedAccess/DottedCall dan lengkap metadata.

    PROSES DUA TAHAP:
        1. Bangun SymbolTable dari semua deklarasi top-level.
        2. Traverse ulang setiap FnDecl (baik top-level maupun method di
           dalam StructDecl), resolusi semua DottedAccess/DottedCall dan
           attach metadata MatchStmt di badannya.

    Args:
        decls: List of AST nodes dari parser (raw)

    Returns:
        list: AST final yang sudah di-resolve dan lengkap metadata

    Note:
        - EnumDecl / UnionDecl tidak punya body Expr/Stmt apapun di dalamnya
          (stage0) — tidak ada yang perlu diresolusi.
        - StructDecl methods di-resolve secara terpisah.
    """
    table = SymbolTable.build(decls)

    for decl in decls:
        if isinstance(decl, FnDecl):
            _resolve_fn_decl(decl, table)
        elif isinstance(decl, StructDecl):
            for method in decl.methods:
                _resolve_fn_decl(method, table)
        # EnumDecl / UnionDecl tidak punya body Expr/Stmt apapun di
        # dalamnya (stage0) — tidak ada yang perlu diresolusi.

    return decls


def _resolve_fn_decl(fn: FnDecl, table: SymbolTable) -> None:
    """
    Resolve semua ekspresi dan statement dalam body sebuah fungsi.

    Proses:
        1. Kumpulkan tipe variabel lokal dari LetStmt
        2. Resolve match metadata SEBELUM recursive resolution
        3. Resolve semua statement (termasuk DottedAccess/DottedCall)

    Args:
        fn: FnDecl yang akan di-resolve
        table: SymbolTable untuk lookup
    """
    current_struct_name = fn.struct_name
    # Kumpulkan tipe variabel lokal dari body fungsi
    local_types = _collect_local_types(fn.body, table)
    for i, stmt in enumerate(fn.body):
        # Resolve match metadata SEBELUM recursive resolution
        if isinstance(stmt, MatchStmt):
            _resolve_match_stmt(stmt, table)
        fn.body[i] = _resolve_stmt(stmt, table, current_struct_name, local_types)
