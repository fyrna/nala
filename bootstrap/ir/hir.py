"""
bootstrap/ir/hir.py

High-level Intermediate Representation (HIR) untuk bahasa Nala.

HIR adalah hasil dari type checker -- AST yang sudah:
    1. Semua referensi ter-resolve (tidak ada DottedAccess/DottedCall)
    2. Setiap ekspresi punya type annotation (TypeRef)
    3. Semua metadata semantik sudah lengkap
    4. Immutable -- codegen HANYA membaca, tidak pernah mutasi

FILOSOFI:
    - HIR adalah "kontrak" antara frontend (type checker) dan backend (codegen).
    - Codegen tidak boleh melakukan inferensi atau keputusan semantik apapun.
    - Semua informasi yang codegen butuhkan HARUS sudah ada di HIR.

BEDA DENGAN AST:
    - AST (nala_ast.py) adalah pure syntax tree -- stupid, netral.
    - HIR adalah semantic tree -- resolved, typed, final.
    - Type checker adalah satu-satunya yang membuat HIR.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


# ---------------------------------------------------------------------------
# TypeRef -- representasi tipe di HIR
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class TypeRef:
    """
    Referensi tipe di HIR.

    Semua tipe di Nala direpresentasikan sebagai string name:
        - Primitive: "i32", "str", "bool", "void"
        - User-defined: "Token", "Option", "Result"
        - Array: "[]u8", "[]i32"

    TypeRef bersifat frozen (immutable) sehingga bisa digunakan sebagai
    key di dictionary dan tidak bisa dimutasi setelah dibuat.

    Attributes:
        name: Nama tipe dalam bentuk string
    """
    name: str

    def __str__(self) -> str:
        return self.name


# ---------------------------------------------------------------------------
# HIR Expressions -- semua sudah resolved dan typed
# ---------------------------------------------------------------------------

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
    Literal float -- sudah typed.

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
class HFieldAccess:
    """Akses field: obj.field -- sudah divalidasi type checker."""
    obj: HExpr
    field: str
    type_ref: TypeRef


@dataclass
class HArrayLiteral:
    """Array literal: [1, 2, 3] — sudah typed."""
    elements: list[HExpr]
    type_ref: TypeRef


@dataclass
class HArrayIndex:
    """Array indexing: arr[i] — sudah typed."""
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
    """Konstruksi instance union: UnionName.VariantName(payload).

    union_name SELALU terisi (wajib di HIR).
    """
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


# Union type untuk semua ekspresi HIR
HExpr = (
    HIdent | HStringLiteral | HIntLiteral | HFloatLiteral | HByteLiteral
    | HFieldAccess | HBinaryExpr | HUnaryExpr | HCallExpr
    | HMethodCall | HIntrinsicCall | HStructLiteral | HUnionLiteral
    | HEnumVariantAccess | HIfExpr
    | HArrayLiteral | HArrayIndex
)


# ---------------------------------------------------------------------------
# HIR Statements
# ---------------------------------------------------------------------------

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
    """Satu arm di match statement.

    union_name SELALU terisi (wajib di HIR).
    bind_type SELALU terisi kalau bind tidak None.
    """
    variant: str
    body: list[HStmt]
    union_name: str
    bind: str | None = None
    bind_type: TypeRef | None = None
    guard: HExpr | None = None


@dataclass
class HMatchStmt:
    """Statement match.

    union_name SELALU terisi (wajib di HIR).
    """
    expr: HExpr
    arms: list[HMatchArm]
    union_name: str


# Union type untuk semua statement HIR
HStmt = (
    HReturnStmt | HIfStmt | HWhileStmt | HForInStmt | HAssignStmt | HLetStmt
    | HExprStmt | HMatchStmt | HContinueStmt | HBreakStmt
)


# ---------------------------------------------------------------------------
# HIR Top-level Declarations
# ---------------------------------------------------------------------------

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
    """Deklarasi fungsi di HIR.

    struct_name SELALU terisi kalau ini method.
    """
    name: str
    params: list[HParam]
    return_type: TypeRef
    body: list[HStmt]
    is_internal: bool = False
    self_param: HSelfParam | None = None
    struct_name: str | None = None


# Union type untuk semua deklarasi top-level HIR
HDecl = HEnumDecl | HStructDecl | HUnionDecl | HFnDecl
