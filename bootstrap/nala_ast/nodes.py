# nala_ast/nodes.py
"""
AST for Nala. Parser produces raw AST; type checker resolves semantics.

Prinsip: "parser shall know nothing except language syntax. be stupid."
Parser HANYA mencatat bentuk sintaksis -- tidak pernah menyimpulkan
makna (apakah nama valid, apakah generic argumen cocok, dst).
"""
from __future__ import annotations
from dataclasses import dataclass, field


class TypeExpr:
    pass


@dataclass
class NamedTypeExpr(TypeExpr):
    """Nama tipe polos: i32, User, std.mem.Allocator (path titik disimpan apa adanya)."""
    path: list[str]  # ["std", "mem", "Allocator"] atau ["User"] atau ["i32"]


@dataclass
class GenericTypeExpr(TypeExpr):
    """ArrayList<T>, X<A, B, C> -- generic instantiation SYNTAX, args belum di-expand."""
    base: NamedTypeExpr
    args: list[TypeExpr]


@dataclass
class ArrayTypeExpr(TypeExpr):
    """[N]T atau [_]T (size None berarti infer dari initializer, type_system.md)."""
    element: TypeExpr
    size: "int | None"


@dataclass
class SliceTypeExpr(TypeExpr):
    """[]T atau []mut T."""
    element: TypeExpr
    is_mut: bool = False


@dataclass
class PointerTypeExpr(TypeExpr):
    """*T atau *mut T."""
    pointee: TypeExpr
    is_mut: bool = False


@dataclass
class ReferenceTypeExpr(TypeExpr):
    """&T atau &mut T."""
    referent: TypeExpr
    is_mut: bool = False


@dataclass
class BoundedTypeExpr(TypeExpr):
    """'T atau 'mut T"""
    bounded: TypeExpr
    is_mut: bool = False

@dataclass
class SatisfyTypeExpr(TypeExpr):
    """satisfy Trait atau satisfy Trait + Other (multiple bound)."""
    traits: list[NamedTypeExpr]


@dataclass
class FunctionTypeExpr(TypeExpr):
    """(T1, T2) -> R -- function type anotasi."""
    params: list[TypeExpr]
    return_type: TypeExpr


@dataclass
class StableAddressFunctionTypeExpr(TypeExpr):
    """
    Tipe slot yang membutuhkan fungsi dengan stable address.
    BUKAN tipe dari named fn.
    (function.md, ffi.md §3)
    """
    params: list[TypeExpr]
    return_type: TypeExpr


@dataclass
class IntrinsicTypeExpr(TypeExpr):
    """
    Type-level intrinsic: self!, typeof!(expr), sizeof!(T), dst.
    self! tidak punya argumen; yang lain boleh.
    """
    name: str
    arg: list[TypeExpr] = field(default_factory=list)


@dataclass
class CompilerHint:
    """
    #[key] atau #[key(value, ...)]. Parser TIDAK
    tahu apakah 'key' ini hint yang valid/dikenal compiler -- itu
    validasi checker (closed-set hint).
    """
    name: str
    args: list["Expr"] = field(default_factory=list)


@dataclass
class UseDecl:
    """
    use <namespace> [as <alias>];

    `alias` Optional -- None berarti pakai default (segmen terakhir
    dari module_path), diselesaikan di checker/use_alias.py
    (default_alias_for()). `as` HANYA dipakai untuk override default
    itu (mis. menghindari konflik nama antar dua `use` yang segmen
    terakhirnya kebetulan sama).
    """
    module_path: str
    alias: "str | None" = None


@dataclass
class ConstDecl:
    """
    const Name [= type_params] = value;

    Dua peran:
      - Value const:  const x: i32 = 5;
      - Re-export:    const Result = std.core.Result;
        (value = path ke item; bukan namespace)

    struct/sum/enum/trait setelah `const Name =` diparse sebagai
    StructDecl/SumDecl/... tersendiri.
    """
    name: str
    value: "Expr"
    type: "TypeExpr | None" = None  # anotasi opsional
    type_params: list["TypeParam"] = field(default_factory=list)
    hints: list["CompilerHint"] = field(default_factory=list)


@dataclass
class ForeignDecl:
    """
    foreign "libname" fn name(params) -> return_type;

    Declaration of an external C-ABI function. lib_name is the
    string literal identifying the source library (e.g. "libc").
    fn holds the signature (name, params, return_type) — body is
    always empty for foreign declarations.
    """
    lib_name: str
    fn: FnDecl


@dataclass
class EnumVariantDecl:
    """Variant enum -- label saja, atau dengan value eksplisit (#[enum(T)])."""
    name: str
    value: "Expr | None" = None  # None = auto (iota-like), Expr = eksplisit


@dataclass
class EnumDecl:
    name: str
    variants: list[EnumVariantDecl] = field(default_factory=list)
    methods: list["FnDecl"] = field(default_factory=list)
    hints: list[CompilerHint] = field(default_factory=list)


@dataclass
class SumVariantDecl:
    """Variant sum type: Name(type1, type2, ...) atau Name tanpa payload."""
    name: str
    payload_types: list[TypeExpr] = field(default_factory=list)


@dataclass
class TypeParam:
    """
    Slot compiler-syntax <Name : bound>.
    `<>` = ekspansi compile-time.
    bound None / type → meta-type type; satisfy Trait → bound check.
    """
    name: str
    bound: "TypeExpr | None" = None


@dataclass
class SumDecl:
    name: str
    variants: list[SumVariantDecl] = field(default_factory=list)
    methods: list["FnDecl"] = field(default_factory=list)
    type_params: list["TypeParam"] = field(default_factory=list)
    hints: list[CompilerHint] = field(default_factory=list)


@dataclass
class StructField:
    name: str
    type: TypeExpr
    default: "Expr | None" = None  # default field value


@dataclass
class StructDecl:
    name: str
    fields: list[StructField] = field(default_factory=list)
    methods: list["FnDecl"] = field(default_factory=list)
    type_params: list["TypeParam"] = field(default_factory=list)
    hints: list[CompilerHint] = field(default_factory=list)


@dataclass
class TraitMethodDecl:
    """Method signature di dalam trait { ... }, boleh dengan default body."""
    name: str
    params: list["Param"]
    return_type: TypeExpr
    default_body: "list[Stmt] | None" = None


@dataclass
class TraitDecl:
    name: str
    methods: list[TraitMethodDecl] = field(default_factory=list)
    associated_types: list[str] = field(default_factory=list)
    super_traits: list[NamedTypeExpr] = field(default_factory=list)  # trait(A + B) { ... }


@dataclass
class SatisfyDecl:
    """satisfy Type: Trait { ... }"""
    type_name: NamedTypeExpr
    trait_name: NamedTypeExpr
    methods: list["FnDecl"] = field(default_factory=list)
    associated_types: dict[str, TypeExpr] = field(default_factory=dict)  # type Item = i32


class Expr:
    pass


@dataclass
class Ident(Expr):
    name: str


@dataclass
class UnitLiteral(Expr):
    """Nilai literal dari tipe unit (`sole`). Satu-satunya penghuni himpunan unit."""
    pass


@dataclass
class StringLiteral(Expr):
    value: str


@dataclass
class IntLiteral(Expr):
    value: str  # raw text (angka SAJA, suffix sudah dipisah), konversi ke int adalah tugas checker
    suffix: "str | None" = None  # "i8"/"i16".../"u64"/"isize"/"usize", None = tidak ada (infer dari context)


@dataclass
class FloatLiteral(Expr):
    value: str  # raw text (angka SAJA, suffix sudah dipisah)
    suffix: "str | None" = None  # "f32"/"f64", None = tidak ada (infer dari context)


@dataclass
class BoolLiteral(Expr):
    value: bool


@dataclass
class ByteLiteral(Expr):
    value: str


@dataclass
class BinaryExpr(Expr):
    op: str
    left: Expr
    right: Expr


@dataclass
class UnaryExpr(Expr):
    op: str
    operand: Expr


@dataclass
class CallExpr(Expr):
    """foo(args) — callee biasanya Ident; bentuk lain (mis. hasil grouping)
    tetap Expr (parser be stupid, checker yang validasi)."""
    callee: Expr
    args: list[Expr] = field(default_factory=list)


@dataclass
class FunctionLiteral(Expr):
    """
    Pure function value (function.md):
      (x: i32) -> i32 => x * x
    Bertipe FunctionType (T)->U — bukan item prosedural.
    """
    params: list  # list[Param]
    return_type: "TypeExpr"
    body: Expr  # expression body (pure)


@dataclass
class MethodCall(Expr):
    """obj.method(args) -- base SELALU ada & valid sebagai nilai runtime."""
    obj: Expr
    method: str
    args: list[Expr] = field(default_factory=list)


@dataclass
class IntrinsicCall(Expr):
    """name! atau name!(args) -- sizeof!, popcount!, dst"""
    name: str
    args: list[Expr] = field(default_factory=list)


@dataclass
class StructLiteral(Expr):
    type_name: str
    fields: list["FieldInit"] = field(default_factory=list)


@dataclass
class FieldInit:
    """Satu pasang (nama field, value)"""
    name: str
    value: Expr


@dataclass
class ArrayLiteral(Expr):
    size: "int | None"  # None = [_]T (infer dari elements)
    element_type: TypeExpr
    elements: list[Expr]


@dataclass
class ArrayIndex(Expr):
    obj: Expr
    index: Expr


# --- Dotted access dengan base EKSPLISIT (mis. math.abs, std.mem.copy) ---
# Base SELALU ada & merujuk module/value yang valid -- BUKA leading-dot.

@dataclass
class DottedAccess(Expr):
    base: Expr
    name: str


@dataclass
class DottedCall(Expr):
    base: Expr
    name: str
    args: list[Expr] = field(default_factory=list)


# --- Leading-dot: TANPA base sama sekali. Levelnya SAMA dengan generic
# <T> -- instruksi ekspansi compile-time yang butuh context type untuk
# berarti apa-apa (type_system.md: "Tanpa konteks... compile error").
# TERPISAH dari DottedAccess/DottedCall karena keduanya bukan variasi
# dari hal yang sama -- satu ekspresi runtime biasa, satu instruksi
# ekspansi yang menunggu context.

@dataclass
class LeadingDotAccess(Expr):
    """.Active — variant/assoc tanpa payload.
    (Bentuk `.{}` adalah LeadingDotStructLiteral, bukan name=="".)"""
    name: str


@dataclass
class LeadingDotCall(Expr):
    """.Ok(5), .Circle(3.0), .empty() -- sum variant/assoc fn dengan args."""
    name: str
    args: list[Expr] = field(default_factory=list)


@dataclass
class LeadingDotStructLiteral(Expr):
    """.{ field: value, ... } -- struct literal dengan tipe di-infer dari context."""
    fields: list[FieldInit] = field(default_factory=list)


@dataclass
class TryExpr(Expr):
    """
    try expr (error_handling.md) -- keyword posisi-ekspresi, MENGIKAT
    SELURUH CHAIN di kanannya (bukan menunggu chain selesai dulu --
    "try mengikat chain, tapi unwrap di titik Result paling awal"):

        try io.open().read()

    Secara tekstual "mencakup" seluruh chain (io.open().read()), tapi
    parser TIDAK perlu tahu di mana persisnya titik Result -- itu
    keputusan checker (hasil evaluasi expr, bukan bentuk sintaksis).
    Parser cukup mencatat: try membungkus SATU Expr penuh di kanannya
    (yang bisa berupa chain method call kompleks).

    Bisa dibatasi scope-nya eksplisit dengan parens:
        (try io.open()).read()
    Ini otomatis tertangani oleh precedence normal -- try mengikat
    _parse_postfix() penuh (termasuk chain), parens membatasi lewat
    grouping seperti biasa.
    """
    inner: Expr


@dataclass
class IfExpr(Expr):
    """
    if cond expr [else expr]  -- single expression, TANPA ret
    if cond { stmt...; ret v; } [else ...]  -- block, value WAJIB dari
    ret EKSPLISIT di dalamnya (type_system.md: "Block { } tidak
    memiliki implicit return"). Parser TIDAK PERNAH menyisipkan ret
    tersembunyi untuk bentuk single-expr -- then_branch/else_branch
    bertipe Sum[Expr, list[Stmt]] PERSIS mencatat bentuk yang ada di
    source, dua representasi berbeda untuk dua bentuk yang berbeda.

    else_branch WAJIB ada kalau IfExpr ini dipakai sebagai VALUE (mis.
    let x = if ... else ...) -- tapi parser tidak tahu/tidak peduli
    konteks pemakaian itu (be stupid). else_branch: Optional di sini,
    validasi "wajib ada kalau dipakai sebagai value" adalah tugas
    checker, BUKAN IfStmt terpisah -- satu node yang sama dipakai baik
    sebagai statement (dibungkus ExprStmt) maupun sub-ekspresi.

    Tidak ada else-if berantai untuk bentuk ekspresi (sengaja dibatasi
    -- kalau butuh percabangan kompleks, pakai match atau nested
    parentheses eksplisit, bukan else-if yang "cantik").
    """
    cond: Expr
    then_branch: "Expr | list[Stmt]"
    else_branch: "Expr | list[Stmt] | None" = None


class Pattern:
    pass


@dataclass
class WildcardPattern(Pattern):
    """_"""
    pass


@dataclass
class BindPattern(Pattern):
    """x -- identifier polos, bind ke value apa pun."""
    name: str


@dataclass
class LiteralPattern(Pattern):
    """90, true, '\\n', EOF (const reference) -- dibandingkan by value."""
    value: Expr


@dataclass
class RangePattern(Pattern):
    """90..100 atau 60..<90."""
    low: Expr
    high: Expr
    inclusive: bool


@dataclass
class OrPattern(Pattern):
    """1 | 2 | (10..<20) | 30."""
    alternatives: list[Pattern]


@dataclass
class VariantPattern(Pattern):
    """.Circle(r), .Rectangle(w, h), .Point -- leading-dot, sum/enum variant."""
    variant_name: str
    bindings: list[Pattern] = field(default_factory=list)


@dataclass
class StructPattern(Pattern):
    """.{ username: "Fyrna", age } -- field bisa match literal atau bind."""
    fields: list[tuple[str, "Pattern | None"]]  # None = bind ke nama field itu sendiri
    ignore_rest: bool = False  # `..`


@dataclass
class AtBindPattern(Pattern):
    """r @ 1..10 -- bind sambil tetap match inner pattern."""
    name: str
    inner: Pattern


@dataclass
class MatchArm:
    """
    pattern [if guard] => body

    Tidak ada implicit return.
    - MatchStmt: `=> expr` hanya ExprStmt (nilai dibuang) kecuali ret eksplisit
    - MatchExpr: `=> expr` menyuplai nilai arm; block tetap wajib ret eksplisit
    """
    pattern: Pattern
    body: list["Stmt"]
    guard: "Expr | None" = None
    body_is_expr: bool = False  # True jika `=> expr` (bukan block/stmt)


@dataclass
class MatchStmt:
    """match sebagai statement."""
    expr: Expr
    arms: list[MatchArm]
    is_comp: bool = False


@dataclass
class MatchExpr(Expr):
    """
    match sebagai expression (mis. ret match x { 1 => 10, _ => 0 }).
    Semua arm value harus bertipe sama.
    """
    expr: Expr
    arms: list[MatchArm]
    is_comp: bool = False


class Stmt:
    pass


@dataclass
class Param:
    """
    is_value_mut: value mutability (mut T -- memory_management.md),
    BERBEDA dari binding mutability (yang untuk parameter fungsi tidak
    relevan -- parameter selalu "bind sekali", tidak pernah di-rebind
    seperti let mut).
    """
    name: str
    type: TypeExpr
    is_value_mut: bool = False


@dataclass
class SelfParam:
    """
    Empat bentuk receiver (memory_management.md ss3):
      &self      -> is_ref=True,  is_mut=False, is_binding_mut=False (tidak relevan, borrow)
      &mut self  -> is_ref=True,  is_mut=True,  is_binding_mut=False (tidak relevan, borrow)
      self       -> is_ref=False, is_mut=False, is_binding_mut=False (consume, binding immutable)
      mut self   -> is_ref=False, is_mut=False, is_binding_mut=True  (consume, binding mutable)

    `is_mut` HANYA relevan untuk is_ref=True (borrow mutability -- &self
    vs &mut self). `is_binding_mut` HANYA relevan untuk is_ref=False
    (consume: self vs mut self) -- PERSIS pola is_binding_mut yang
    sama dengan LetStmt (let x vs let mut x), diterapkan ke self
    sebagai binding yang di-consume.
    """
    is_mut: bool = False
    is_ref: bool = True
    is_binding_mut: bool = False


@dataclass
class ReturnStmt(Stmt):
    expr: "Expr | None"  # None = ret; tanpa nilai (fn -> void)


@dataclass
class ForStmt(Stmt):
    """for cond { ... }"""
    cond: Expr
    body: list["Stmt"] = field(default_factory=list)


@dataclass
class LoopStmt(Stmt):
    """
    loop { ... }
    """
    body: list["Stmt"] = field(default_factory=list)


@dataclass
class ForInStmt(Stmt):
    """
    for item in arr
    for i, item in &arr
    for i, _ in &mut arr
    for _, _ in arr
    """
    index_name: "str | None"  # None kalau single-binding
    var_name: str
    iterable: Expr
    body: list["Stmt"] = field(default_factory=list)
    is_inline: bool = False  # reserved: `inline for` (parser belum set)


@dataclass
class AssignStmt(Stmt):
    target: Expr
    value: Expr
    op: str = "="


@dataclass
class ExprStmt(Stmt):
    expr: Expr


@dataclass
class ContinueStmt(Stmt):
    label: "str | None" = None


@dataclass
class BreakStmt(Stmt):
    label: "str | None" = None


@dataclass
class DeferStmt(Stmt):
    """defer expr; atau defer { block }."""
    body: list["Stmt"]


@dataclass
class LetStmt(Stmt):
    """
    let selalu wajib diinisialisasi -- value WAJIB Expr, tidak ada
    bentuk `let x: T;` tanpa nilai (konsisten dengan NLetStmt di NIR).

    Dua sumbu mutability yang orthogonal (memory_management.md §2):
    - is_binding_mut: `let mut x` -- boleh di-rebind (assign ulang)
    - is_value_mut: `let x: mut T` -- value punya operasi mutating
    Keduanya independen, bisa dikombinasikan bebas (4 kombinasi valid,
    lihat memory_management.md §2).

    is_unsafe: `unsafe let x = ...;` -- treat `unsafe` MENEMPEL ke let
    statement ini SAJA (bukan block terpisah -- pointer.md/
    error_handling.md HANYA mendokumentasikan `unsafe let` dan
    `unsafe fn`, TIDAK ADA bentuk `unsafe { }` block berdiri sendiri).
    Mengizinkan operasi yang menyentuh pointer (dereference `p.*`,
    pointer arithmetic) di DALAM value expression let ini -- konsisten
    dengan aksioma "unsafe di titik sentuh, bukan di titik simpan"
    (pointer.md). Scope permission ini HANYA berlaku selama
    membangun `value` milik LetStmt ini, TIDAK "bocor" ke statement
    lain setelahnya.
    """
    name: str
    value: Expr
    type: "TypeExpr | None" = None
    is_binding_mut: bool = False
    is_value_mut: bool = False
    is_unsafe: bool = False


@dataclass
class FnDecl:
    name: str
    params: list[Param] = field(default_factory=list)
    return_type: "TypeExpr | None" = None  # None = void
    body: list[Stmt] = field(default_factory=list)
    is_internal: bool = False
    is_inline: bool = False
    is_comp: bool = False
    is_unsafe: bool = False
    self_param: "SelfParam | None" = None
    struct_name: "str | None" = None
    hints: list[CompilerHint] = field(default_factory=list)


@dataclass
class TestDecl:
    """test "nama" { ... } -- testing.md."""
    name: str
    body: list[Stmt] = field(default_factory=list)
