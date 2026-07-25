"""
bootstrap/ir/typecheck/symbol_table.py

Tabel simbol untuk lookup deklarasi top-level -- union, enum, struct, fn.
Multi-module aware: tracks which module each decl belongs to,
and resolves use aliases per module.
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

    Module-aware additions:
        - module_decls: dict[module_name, list[decl]] -- decls per module
        - module_uses: dict[module_name, list[UseDecl]] -- use aliases per module
        - item_to_module: dict[item_name, module_name] -- which module owns each item
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

        # Module-aware additions
        self.module_decls: dict[str, list] = {}
        self.module_uses: dict[str, list] = {}
        self.item_to_module: dict[str, str] = {}

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

    @classmethod
    def build_modules(cls, module_decls: dict[str, list], module_uses: dict[str, list]) -> "SymbolTable":
        """Build SymbolTable from multi-module declarations."""
        all_decls = []
        for decls in module_decls.values():
            all_decls.extend(decls)
        table = cls.build(all_decls)
        table.module_decls = module_decls
        table.module_uses = module_uses
        # Map item name -> module name for quick lookup
        for module_name, decls in module_decls.items():
            for decl in decls:
                if hasattr(decl, "name"):
                    table.item_to_module[decl.name] = module_name
        return table

    def resolve_alias(self, current_module: str, alias: str) -> str | None:
        """Resolve use alias to target module name."""
        uses = self.module_uses.get(current_module, [])
        for use in uses:
            if use.alias is not None:
                if use.alias == alias:
                    return use.module_path
            else:
                default_alias = use.module_path.split(".")[-1]
                if default_alias == alias:
                    return use.module_path
        return None

    def find_item_in_module(self, module_name: str, item_name: str):
        """Find top-level decl by name in a specific module."""
        decls = self.module_decls.get(module_name, [])
        for decl in decls:
            if getattr(decl, "name", None) == item_name:
                return decl
        return None

    def find_variant_in_module(self, module_name: str, variant_name: str):
        """Find if variant_name is a variant of any union/enum in module."""
        decls = self.module_decls.get(module_name, [])
        for decl in decls:
            if isinstance(decl, UnionDecl):
                for v in decl.variants:
                    if v.name == variant_name:
                        return ("union", decl.name, v)
            elif isinstance(decl, EnumDecl):
                if variant_name in decl.variants:
                    return ("enum", decl.name, variant_name)
        return None

    def is_valid_std_namespace(self, namespace: str) -> bool:
        """Validate std.* namespace path. Stage0: std prefix always valid."""
        return namespace.startswith("std.") or namespace == "std"
