# bootstrap/ir/hir.py
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass(frozen=True)
class TypeRef:
    """
    Referensi tipe di HIR.

    Semua tipe di Nala direpresentasikan sebagai string name:
        - Primitive: "i32", "str", "bool", "void"
        - User-defined: "Token", "Option", "Result"
        - Array: "[]u8", "[]i32"
    """
    name: str

    def __str__(self) -> str:
        return self.name


# expression

@dataclass
class HIdent:
    """Referensi ke nama variabel/parameter dengan tipe."""
    name: str
    type_ref: TypeRef


@dataclass
class HStringLiteral:
    """Literal string."""
    value: str
    type_ref: TypeRef = field(default_factory=lambda: TypeRef("str"))


@dataclass
class HIntLiteral:
    """Literal integer."""
    value: str
    type_ref: TypeRef = field(default_factory=lambda: TypeRef("i32"))


@dataclass
class HFloatLiteral:
    """
    Literal float

    Mengikuti pola HIntLiteral: type_ref default "f32", belum
    context-aware terhadap tipe target (mis. f64). Perbaikan supaya
    literal numerik infer dari context adalah isu terpisah.
    """
    value: str
    type_ref: TypeRef = field(default_factory=lambda: TypeRef("f32"))


@dataclass
class HByteLiteral:
    """Literal byte (karakter ASCII tunggal)."""
    value: str
    type_ref: TypeRef = field(default_factory=lambda: TypeRef("u8"))


@dataclass
class HBoolLiteral:
    value: bool
    type_ref: TypeRef = field(default_factory=lambda: TypeRef("bool"))


@dataclass
class HFieldAccess:
    """Akses field: obj.field"""
    obj: HExpr
    field: str
    type_ref: TypeRef


@dataclass
class HArrayLiteral:
    elements: list[HExpr]
    type_ref: TypeRef


@dataclass
class HArrayIndex:
    obj: HExpr
    index: HExpr
    type_ref: TypeRef


@dataclass
class HBinaryExpr:
    """Ekspresi biner: left OP right."""
    op: str
    left: HExpr
    right: HExpr
    type_ref: TypeRef


@dataclass
class HUnaryExpr:
    """Ekspresi unary: OP operand."""
    op: str
    operand: HExpr
    type_ref: TypeRef


@dataclass
class HCallExpr:
    """Pemanggilan fungsi biasa: callee(args)."""
    callee: str
    args: list[HExpr]
    type_ref: TypeRef


@dataclass
class HMethodCall:
    """Pemanggilan method: obj.method(args).

    struct_name SELALU terisi (wajib di HIR).
    """
    obj: HExpr
    method: str
    args: list[HExpr]
    struct_name: str
    type_ref: TypeRef


@dataclass
class HIntrinsicCall:
    """Intrinsic call: name!(args)."""
    name: str
    args: list[HExpr]
    type_ref: TypeRef


@dataclass
class HStructLiteral:
    """Konstruksi instance struct: TypeName { field: value, ... }."""
    type_name: str
    fields: list[tuple[str, HExpr]]
    type_ref: TypeRef


@dataclass
class HUnionLiteral:
    """Konstruksi instance union: UnionName.VariantName(payload)."""
    union_name: str
    variant_name: str
    payload: HExpr | None
    type_ref: TypeRef


@dataclass
class HEnumVariantAccess:
    """Akses variant enum: EnumName.VariantName."""
    enum_name: str
    variant_name: str
    type_ref: TypeRef


@dataclass
class HIfExpr:
    """Ekspresi if: if cond { then_expr } else { else_expr }."""
    cond: HExpr
    then_branch: HExpr
    else_branch: HExpr
    type_ref: TypeRef


HExpr = (
    HIdent | HStringLiteral | HIntLiteral | HFloatLiteral | HBoolLiteral | HByteLiteral
    | HFieldAccess | HBinaryExpr | HUnaryExpr | HCallExpr
    | HMethodCall | HIntrinsicCall | HStructLiteral | HUnionLiteral
    | HEnumVariantAccess | HIfExpr
    | HArrayLiteral | HArrayIndex
)


@dataclass
class HParam:
    """Parameter fungsi di HIR."""
    name: str
    type_ref: TypeRef


@dataclass
class HSelfParam:
    """Parameter self untuk method."""
    is_mut: bool = False
    is_ref: bool = True


@dataclass
class HReturnStmt:
    """Statement ret expr;."""
    expr: HExpr


@dataclass
class HElifClause:
    """Klausa else if."""
    cond: HExpr
    body: list[HStmt]


@dataclass
class HIfStmt:
    """Statement if."""
    cond: HExpr
    body: list[HStmt]
    elifs: list[HElifClause] = field(default_factory=list)
    else_body: list[HStmt] = field(default_factory=list)


@dataclass
class HWhileStmt:
    """Statement for (while-style loop)."""
    cond: HExpr
    body: list[HStmt]


@dataclass
class HForInStmt:
    """Statement for x in arr (iterator-style loop)."""
    var_name: str
    iterable: HExpr
    body: list[HStmt]
    var_type: TypeRef  # tipe dari loop variable (element type)


@dataclass
class HAssignStmt:
    """Statement assignment: target = value; atau target += value;."""
    target: HExpr
    value: HExpr
    op: str = "="


@dataclass
class HExprStmt:
    """Statement berupa ekspresi standalone."""
    expr: HExpr


@dataclass
class HContinueStmt:
    """Statement continue;."""
    pass


@dataclass
class HBreakStmt:
    """Statement break;."""
    pass


@dataclass
class HLetStmt:
    """Statement let [mut] name [: type] = value;."""
    name: str
    value: HExpr
    type_ref: TypeRef
    is_mut: bool = False


@dataclass
class HMatchArm:
    """Satu arm di match statement."""
    variant: str
    body: list[HStmt]
    union_name: str
    bind: str | None = None
    bind_type: TypeRef | None = None
    guard: HExpr | None = None


@dataclass
class HMatchStmt:
    """Statement match."""
    expr: HExpr
    arms: list[HMatchArm]
    union_name: str


HStmt = (
    HReturnStmt | HIfStmt | HWhileStmt | HForInStmt | HAssignStmt | HLetStmt
    | HExprStmt | HMatchStmt | HContinueStmt | HBreakStmt
)


@dataclass
class HEnumDecl:
    """Deklarasi enum di HIR."""
    name: str
    variants: list[str]


@dataclass
class HStructField:
    """Field struct di HIR."""
    name: str
    type_ref: TypeRef
    is_mut: bool = False


@dataclass
class HStructDecl:
    """Deklarasi struct di HIR."""
    name: str
    fields: list[HStructField]
    methods: list[HFnDecl] = field(default_factory=list)


@dataclass
class HUnionVariant:
    """Variant union di HIR."""
    name: str
    payload_type: TypeRef | None = None


@dataclass
class HUnionDecl:
    """Deklarasi union di HIR."""
    name: str
    variants: list[HUnionVariant]


@dataclass
class HFnDecl:
    """Deklarasi fungsi di HIR."""
    name: str
    params: list[HParam]
    return_type: TypeRef
    body: list[HStmt]
    is_internal: bool = False
    self_param: HSelfParam | None = None
    struct_name: str | None = None


HDecl = HEnumDecl | HStructDecl | HUnionDecl | HFnDecl
