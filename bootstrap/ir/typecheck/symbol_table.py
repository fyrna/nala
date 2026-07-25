"""
bootstrap/ir/typecheck/symbol_table.py

Tabel simbol untuk lookup deklarasi top-level -- union, enum, struct, fn.

Dipisah dari type_checker.py lama sebagai bagian dari rework "soal tipe"
(lihat type_compat.py untuk verifikasi kecocokan tipe, inference.py untuk
penebakan tipe ekspresi). Modul ini murni indexing, tidak menyentuh AST/HIR
translation sama sekali.
"""

from __future__ import annotations

from nala_ast import EnumDecl, StructDecl, UnionDecl, FnDecl


class TypeCheckError(Exception):
    """Error semantik -- beda dari ParseError (syntax error)."""
    pass


class SymbolTable:
    """
    Tabel simbol untuk lookup deklarasi top-level.

    Menyimpan:
        - union_names, enum_names, struct_names: set[str]
        - union_variants: dict[union_name, set[variant_names]]
        - union_payload_types: dict[union_name, dict[variant_name, str|None]]
        - enum_variants: dict[enum_name, set[variant_names]]
        - struct_fields: dict[struct_name, dict[field_name, (type_name, is_mut)]]
        - fn_signatures: dict[fn_name, (param_types, return_type)] -- HANYA
          top-level `fn`, method (nested di StructDecl.methods) tidak ikut
          di sini karena resolusinya lewat jalur MethodCall yang terpisah.
        - method_signatures: dict[(struct_name, method_name), (param_types, return_type)]
          -- method yang di-nest di StructDecl.methods. Terpisah dari
          fn_signatures karena method dengan nama sama bisa ada di struct
          berbeda (mis. Point.distance vs Vector.distance), jadi butuh
          key gabungan (struct_name, method_name), bukan cuma nama method.
          param_types di sini TIDAK termasuk self -- cuma parameter selain
          self (konsisten dengan bagaimana method dipanggil: p.method(args),
          args tidak termasuk p itu sendiri).
    """

    def __init__(self) -> None:
        self.union_names: set[str] = set()
        self.enum_names: set[str] = set()
        self.struct_names: set[str] = set()

        self.union_variants: dict[str, set[str]] = {}
        self.union_payload_types: dict[str, dict[str, str | None]] = {}
        self.enum_variants: dict[str, set[str]] = {}
        self.struct_fields: dict[str, dict[str, tuple[str, bool]]] = {}

        # fn_name -> (list of param type_name, return_type)
        self.fn_signatures: dict[str, tuple[list[str], str]] = {}

        # (struct_name, method_name) -> (list of param type_name [tanpa self], return_type)
        self.method_signatures: dict[tuple[str, str], tuple[list[str], str]] = {}

    @classmethod
    def build(cls, decls: list) -> "SymbolTable":
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
                table.struct_fields[decl.name] = {}
                for f in decl.fields:
                    table.struct_fields[decl.name][f.name] = (f.type_name, f.is_mut)
                for m in decl.methods:
                    param_types = [p.type_name for p in m.params]
                    table.method_signatures[(decl.name, m.name)] = (
                        param_types, m.return_type
                    )
            elif isinstance(decl, FnDecl):
                # Hanya top-level fn -- method (struct_name terisi) di-skip,
                # karena dipanggil lewat MethodCall yang jalur resolusinya beda.
                if decl.struct_name is None:
                    param_types = [p.type_name for p in decl.params]
                    table.fn_signatures[decl.name] = (param_types, decl.return_type)
        return table
