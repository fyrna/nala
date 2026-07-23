"""
bootstrap/nala_ast.py

AST (Abstract Syntax Tree) untuk bahasa Nala.

Prioritas desain: DEBUGGABILITY, bukan performa. AST direpresentasikan
sebagai dataclass sederhana yang bisa langsung di-print dan dibaca
manusia — bukan struktur yang dioptimalkan untuk kecepatan.

ARSITEKTUR DAN ALUR DATA:
    
    Parser (parser.py)
        ↓ menghasilkan AST "raw"
    AST Raw:
        - Masih mengandung node netral (DottedAccess, DottedCall)
        - Belum ada metadata semantik
        - Sintaks murni, tanpa inferensi
        ↓
    Type Checker (type_checker.py)
        ↓ menghasilkan AST "final"
    AST Final:
        - DottedAccess → di-resolve jadi FieldAccess/EnumVariantAccess/UnionLiteral
        - DottedCall → di-resolve jadi MethodCall/UnionLiteral
        - Metadata ditambahkan (union_name, bind_type, struct_name, dll)
        - Semua referensi ter-resolve dengan benar
        ↓
    Codegen (backend/codegen.py)
        ↓ menghasilkan C code
    C Code:
        - Terjemahan langsung dari AST final
        - Tidak ada inferensi atau keputusan semantik

Prinsip desain:
    1. Parser tidak boleh membuat keputusan semantik
    2. Type checker adalah satu-satunya yang melakukan resolusi
    3. Codegen hanya menerjemahkan, tidak menganalisis
    4. Setiap node AST harus jelas dan self-documenting
"""

from dataclasses import dataclass, field

@dataclass
class EnumDecl:
    """
    Merepresentasikan deklarasi `const Name = enum { A, B, C, }`.

    Enum di Nala adalah C-style enum sederhana:
        - Tanpa payload
        - Nilai otomatis dimulai dari 0
        - Hanya untuk konstanta diskrit

    Contoh: 
        const TokenKind = enum {
            EOF,
            IDENT,
            INTLITERAL,
        }

    Digunakan untuk:
        - Token kinds
        - Status codes
        - Flag sets

    Catatan scope: HANYA menangani variant TANPA payload.
    Untuk variant dengan payload, gunakan UnionDecl.
    """
    name: str
    variants: list[str] = field(default_factory=list)


@dataclass
class UnionVariant:
    """
    Satu variant di dalam union: `VariantName(type1, type2, ...)`.

    Union adalah tagged union (seperti enum di Rust atau std::variant di C++):
        - Setiap variant memiliki tag (nama)
        - Dapat memiliki 0 atau lebih payload types
        - Di C diterjemahkan jadi struct dengan tag enum + union payload

    Contoh:
        Option.Some(i32)   → payload_types = ["i32"]
        Option.None()      → payload_types = []
        Result.Ok(i32)     → payload_types = ["i32"]
        Result.Err(str)    → payload_types = ["str"]

    Untuk stage0 hanya support 0 atau 1 payload type.
    """
    name: str
    payload_types: list[str] = field(default_factory=list)


@dataclass
class UnionDecl:
    """
    Merepresentasikan deklarasi `const Name = union { Variant(type), ... }`.

    Union adalah tipe data sum type:
        - Seperti enum di Rust
        - Seperti tagged union di C
        - Memiliki beberapa varian dengan payload berbeda

    Contoh:
        const Option = union {
            Some(i32),
            None(),
        }

        const Result = union {
            Ok(i32),
            Err(str),
        }

    Di C diterjemahkan jadi struct dengan tag enum + union payload.
    """
    name: str
    variants: list[UnionVariant] = field(default_factory=list)


@dataclass
class StructField:
    """
    Satu field di dalam struct: `[mut] name: type_name`.

    Struct field bisa mutable atau immutable:
        - Tanpa mut → read-only
        - Dengan mut → bisa di-assign

    Contoh:
        mut pos: i32      → is_mut = True
        kind: TokenKind   → is_mut = False
    """
    name: str
    type_name: str
    is_mut: bool = False


@dataclass
class StructDecl:
    """
    Merepresentasikan deklarasi `const Name = struct { field: type, ... }`.

    Struct adalah tipe data product type:
        - Kumpulan field dengan tipe berbeda
        - Bisa memiliki methods
        - Di C diterjemahkan jadi struct biasa

    Contoh:
        const Token = struct {
            kind: TokenKind,
            text: str,
            mut pos: i32,
        }

    Struct bisa memiliki methods yang di-declare terpisah dengan `fn`.
    """
    name: str
    fields: list[StructField] = field(default_factory=list)
    methods: list["FnDecl"] = field(default_factory=list)

# --- AST ekspresi ---

@dataclass
class Ident:
    """
    Referensi ke sebuah nama -- parameter atau variabel lokal.

    Ident adalah node paling dasar untuk referensi nama:
        - Variabel lokal
        - Parameter fungsi
        - Nama konstanta

    Contoh: x, count, name, self
    """
    name: str


@dataclass
class StringLiteral:
    """
    Literal string, misal "hello" atau "".

    String di Nala adalah UTF-8 string:
        - Diapit double quote (")
        - Bisa kosong ("")
        - UTF-8 aware (bisa mengandung Unicode)

    Di C diterjemahkan jadi `const char*`.
    """
    value: str


@dataclass
class IntLiteral:
    """
    Literal integer, misal 42, 0, 100.

    Integer di Nala adalah i32 (32-bit signed):
        - Bilangan bulat desimal
        - Belum support hex/octal/binary
        - Belum support underscore separator

    Contoh: 42, 0, 100, -5 (unary minus)
    """
    value: str


@dataclass
class ByteLiteral:
    """
    Literal karakter tunggal, misal 'a' atau '0'.

    Byte literal adalah ASCII character:
        - Diapit single quote (')
        - Hanya satu karakter ASCII
        - Bukan Unicode (beda dengan StringLiteral)

    Contoh: 'a', '0', '\n' (belum support escape)

    Digunakan untuk:
        - Karakter dalam token
        - Byte values dalam parser
        - ASCII constants
    """
    value: str


@dataclass
class FieldAccess:
    """
    Akses field: `expr.field` — misal `self.pos`, `tok.span`.

    Field access untuk struct:
        - Mengambil nilai field dari instance struct
        - Bisa untuk membaca atau menulis (jika mut)

    Contoh:
        self.pos        → obj=self, field="pos"
        tok.span.start  → obj=tok.span, field="start"
    """
    obj: "Expr"
    field: str


@dataclass
class BinaryExpr:
    """
    Ekspresi biner: `left OP right`.

    Operator biner yang didukung:
        - Aritmetika: +, -, *, /
        - Perbandingan: ==, !=, <, >, <=, >= (belum semua)
        - Logika: &&, || (belum support)

    Contoh:
        a + b           → op="+", left=a, right=b
        x == y          → op="==", left=x, right=y
    """
    op: str
    left: "Expr"
    right: "Expr"


@dataclass
class UnaryExpr:
    """
    Ekspresi unary: `OP operand`.

    Operator unary yang didukung:
        - ! (logical not) - negasi boolean

    Contoh:
        !found          → op="!", operand=found
        -5              → op="-", operand=5 (belum support)

    Scope saat ini cuma '!' (logical not).
    """
    op: str
    operand: "Expr"


@dataclass
class CallExpr:
    """
    Pemanggilan fungsi/method: `callee(args)`.

    CallExpr adalah panggilan fungsi biasa:
        - callee adalah nama fungsi (string)
        - args adalah list ekspresi

    Contoh:
        print("hello")  → callee="print", args=["hello"]
        len("test")     → callee="len", args=["test"]

    Beda dengan MethodCall (obj.method()) dan IntrinsicCall (name!()).
    """
    callee: str
    args: list["Expr"] = field(default_factory=list)


@dataclass
class MethodCall:
    """
    Pemanggilan method: `obj.method(args)`.

    Method adalah fungsi yang terikat ke struct:
        - Dipanggil pada instance struct
        - Di C diterjemahkan jadi `StructName_method(obj, args)`

    Contoh:
        tok.get_pos()   → obj=tok, method="get_pos"

    Metadata semantik:
        - struct_name: nama struct dari obj (di-attach type checker)
    """
    obj: "Expr"
    method: str
    args: list["Expr"] = field(default_factory=list)

@dataclass
class IntrinsicCall:
    """
    Intrinsic call: `name!(args)`.

    Intrinsic adalah fungsi built-in dengan syntax khusus:
        - Diakhiri dengan ! (bang)
        - Dipanggil seperti fungsi biasa
        - Diimplementasikan di runtime

    Contoh:
        print!("hello")  → name="print", args=["hello"]
        sizeof!(i32)     → name="sizeof", args=[TypeName]
        assert!(cond)    → name="assert", args=[cond]

    Beda dengan CallExpr (fungsi biasa) karena intrinsic
    adalah built-in yang tidak dideklarasikan di source.
    """
    name: str
    args: list["Expr"] = field(default_factory=list)


@dataclass
class StructLiteral:
    """
    Konstruksi instance struct: `TypeName { field: value, ... }`.

    Struct literal untuk membuat instance struct:
        - Nama struct diikuti block dengan field assignments
        - Semua field harus diisi (tidak ada default)

    Contoh:
        Token { kind: TokenKind.IDENT, text: "hello" }
        Point { x: 10, y: 20 }
    """
    type_name: str
    fields: list[tuple[str, "Expr"]] = field(default_factory=list)


@dataclass
class UnionLiteral:
    """
    Konstruksi instance union: `UnionName.VariantName(payload_expr)`.

    Union literal untuk membuat tagged union:
        - Union name + dot + variant name
        - Payload expression untuk variant yang ada data
        - Tanpa payload untuk unit variant

    Contoh:
        Option.Some(42)    → union_name="Option", variant="Some", payload=42
        Option.None()      → union_name="Option", variant="None", payload=None
        Result.Ok("ok")    → union_name="Result", variant="Ok", payload="ok"

    Untuk variant tanpa payload (void), payload None.
    """
    union_name: str
    variant_name: str
    payload: "Expr | None" = None


@dataclass
class ArrayLiteral:
    """
    Array literal: [1, 2, 3].

    Fixed-size array literal dengan elemen-elemen yang diberikan.
    Type dan size di-infer oleh type checker dari context.

    Contoh:
        [1, 2, 3]           → elements=[1, 2, 3]
        ["a", "b"]          → elements=["a", "b"]
        []                  → elements=[] (empty array, size 0)

    Type checker akan infer:
        - [1, 2, 3] sebagai [3]i32 (kalau context mengharapkan i32)
        - ["a", "b"] sebagai [2]str
    """
    elements: list["Expr"]


@dataclass
class ArrayIndex:
    """
    Array indexing: arr[i].

    Akses elemen array pada index tertentu.
    Hasil adalah elemen dengan tipe T (dari [N]T).

    Contoh:
        arr[0]      → obj=arr, index=0
        arr[i + 1]  → obj=arr, index=i+1

    Bounds checking: stage0 tidak ada runtime bounds check.
    """
    obj: "Expr"
    index: "Expr"


@dataclass
class EnumVariantAccess:
    """
    Akses variant enum: `EnumName.VariantName` (tanpa payload, tanpa kurung).

    Enum variant adalah konstanta:
        - Nama enum + dot + nama variant
        - Tanpa payload (beda dengan UnionLiteral)
        - Di C diterjemahkan jadi konstanta tunggal

    Contoh:
        TokenKind.EOF      → enum_name="TokenKind", variant="EOF"
        TokenKind.IDENT    → enum_name="TokenKind", variant="IDENT"

    Di C diterjemahkan jadi: ENUMNAME_VARIANTNAME
    Beda dari UnionLiteral (yang menghasilkan struct literal dengan tag)
    karena enum di Nala stage0 murni C enum tanpa payload sama sekali.
    """
    enum_name: str
    variant_name: str


@dataclass
class DottedAccess:
    """
    Node NETRAL sementara hasil parsing `base.name` TANPA kurung.

    INI ADALAH NODE SEMENTARA - HARUS DI-RESOLVE OLEH TYPE CHECKER!

    Parser TIDAK tahu (dan tidak boleh menebak) apakah `base` ini
    merujuk ke union type, enum type, atau instance variable — itu
    murni bentuk syntax, bukan keputusan semantik.

    Resolusi oleh type_checker.py:
        - Jika base adalah enum → EnumVariantAccess
        - Jika base adalah union → UnionLiteral (payload=None)
        - Jika base adalah variable/instance → FieldAccess

    Tidak boleh ada DottedAccess yang lolos sampai ke codegen.py.
    """
    base: "Expr"
    name: str


@dataclass
class DottedCall:
    """
    Node NETRAL sementara hasil parsing `base.name(args...)` DENGAN kurung.

    INI ADALAH NODE SEMENTARA - HARUS DI-RESOLVE OLEH TYPE CHECKER!

    Sama seperti DottedAccess, tapi untuk bentuk yang diikuti argumen
    dalam kurung. Args di-parse penuh sebagai list comma-separated
    (0, 1, atau banyak) murni berdasarkan token — tanpa asumsi makna.

    Resolusi oleh type_checker.py:
        - Jika base adalah union → UnionLiteral (payload dari args[0])
        - Jika base adalah variable/instance → MethodCall

    Tidak boleh ada DottedCall yang lolos sampai ke codegen.py.

    Catatan: Untuk union payload, stage0 hanya support 1 argumen.
    Args lebih dari 1 pada union payload adalah error/belum didukung.
    """
    base: "Expr"
    name: str
    args: list["Expr"] = field(default_factory=list)


@dataclass
class IfExpr:
    """
    Ekspresi if: `if cond { then_expr } else { else_expr }`.

    If expression (bukan statement):
        - Menghasilkan nilai (value)
        - Wajib memiliki else branch
        - Kedua branch harus menghasilkan tipe yang sama

    Contoh:
        let x = if a > b { a } else { b }
        let max = if x > y { x } else { y }
    """
    cond: "Expr"
    then_branch: "Expr"
    else_branch: "Expr"


@dataclass
class MatchArm:
    """
    Satu arm di match: `Union.Variant(bind) => { body }`.

    Match arm adalah pola dalam match statement:
        - Pola: Union.Variant(bind) untuk matching union
        - body: list of statements yang dijalankan jika pola cocok
        - bind: optional variable name untuk payload

    Contoh:
        Option.Some(val)  → union="Option", variant="Some", bind="val"
        Option.None()     → union="Option", variant="None", bind=None

    Metadata semantik (di-attach oleh type checker):
        bind_type: tipe Nala dari payload variant (None kalau unit variant).
    """
    variant: str           # nama variant, mis. "Some", "None", "Ok"
    body: list["Stmt"]
    union: str | None = None   # nama union
    bind: str | None = None    # nama variabel binding untuk payload (opsional)
    guard: "Expr | None" = None # guard expression

@dataclass
class MatchStmt:
    """
    Statement match: `match expr { Pattern => { ... }, ... }`.

    Match statement untuk pattern matching:
        - Mengevaluasi ekspresi
        - Mencocokkan dengan pola-pola yang diberikan
        - Menjalankan body dari pola yang cocok

    Contoh:
        match opt {
            Option.Some(val) => { print!(val); }
            Option.None()    => { print!("none"); }
        }

    Metadata semantik (di-attach oleh type checker):
        union_name: nama union yang di-match (derive dari arm pertama).
    """
    expr: "Expr"
    arms: list[MatchArm]

# Type alias untuk semua jenis ekspresi
Expr = (
    BinaryExpr | UnaryExpr | CallExpr | MethodCall | IntrinsicCall | Ident
    | StringLiteral | IntLiteral | ByteLiteral | FieldAccess | IfExpr
    | StructLiteral | UnionLiteral | EnumVariantAccess
    | DottedAccess | DottedCall
    | ArrayLiteral | ArrayIndex
)

# Statement

@dataclass
class Param:
    """
    Satu parameter fungsi: `name: type_name`.

    Parameter adalah input ke fungsi:
        - Nama parameter
        - Tipe parameter (wajib di Nala)

    Contoh:
        fn add(a: i32, b: i32) -> i32 { a + b }
        fn print(msg: str) { ... }
    """
    name: str
    type_name: str


@dataclass 
class SelfParam:
    """
    Parameter self: `&self`, `&mut self`, atau `self`.

    Self parameter untuk method struct:
        - `&self`: read-only reference (default)
        - `&mut self`: mutable reference
        - `self`: owned value (belum support)

    Self parameter adalah cara untuk mengikat fungsi ke struct.
    Di C diterjemahkan jadi pointer ke struct sebagai parameter pertama.

    Contoh:
        fn get_pos(&self) -> i32 { self.pos }
        fn set_pos(&mut self, pos: i32) { self.pos = pos; }
    """
    is_mut: bool = False
    is_ref: bool = True


@dataclass
class ReturnStmt:
    """
    Statement `ret expr;`.

    Return statement untuk mengembalikan nilai dari fungsi:
        - Wajib ada expr (kecuali fungsi return_type void)
        - Menghentikan eksekusi fungsi

    Contoh:
        ret 42;
        ret "hello";
        ret;
    """
    expr: Expr


@dataclass
class ElifClause:
    """
    Klausa `else if cond { body }` dalam if/else if/else chain.

    Elif adalah rantai kondisi dalam if statement:
        - Di-evaluasi berurutan
        - Hanya body pertama yang cocok yang dijalankan

    Contoh:
        if x > 0 { ... }
        else if x == 0 { ... }
        else { ... }
    """
    cond: Expr
    body: list["Stmt"]


@dataclass
class IfStmt:
    """
    Statement `if cond { body } [else if ...] [else { body_else }]`.

    If statement (bukan ekspresi):
        - Tidak menghasilkan nilai (unit)
        - Bisa memiliki elif dan else
        - Body adalah list of statements

    Contoh:
        if x > 0 {
            print!("positive");
        } else if x == 0 {
            print!("zero");
        } else {
            print!("negative");
        }
    """
    cond: Expr
    body: list["Stmt"] = field(default_factory=list)
    elifs: list[ElifClause] = field(default_factory=list)
    else_body: list["Stmt"] = field(default_factory=list)


@dataclass
class WhileStmt:
    """
    Statement `for cond { body }` -- while-style loop.

    While loop:
        - Mengevaluasi kondisi setiap iterasi
        - Jika true, jalankan body
        - Jika false, keluar dari loop

    Contoh:
        for i < 10 {
            print!(i);
            i += 1;
        }

    Note: Syntax `for` bukan `while` untuk konsistensi dengan Nala.
    """
    cond: Expr
    body: list["Stmt"] = field(default_factory=list)


@dataclass
class AssignStmt:
    """
    Statement assignment: `target = value;` atau `target += value;` dst.

    Assignment statement:
        - target: ekspresi yang bisa di-assign (ident, field access)
        - value: ekspresi nilai baru
        - op: operator assignment (=, +=)

    Contoh:
        x = 42;
        x += 1;
        self.pos = 0;
    """
    target: Expr
    value: Expr
    op: str = "="


@dataclass
class ExprStmt:
    """
    Statement berupa ekspresi standalone.

    Ekspresi yang berdiri sendiri sebagai statement:
        - Biasanya function calls
        - Nilai yang dihasilkan diabaikan

    Contoh:
        print!("hello");
        x + y;  // valid tapi tidak berguna
    """
    expr: Expr


@dataclass
class ContinueStmt:
    """
    Statement `continue;`.

    Continue untuk loop:
        - Langsung ke iterasi berikutnya
        - Mengevaluasi kondisi loop lagi

    Contoh:
        for i < 10 {
            if i == 5 { continue; }
            print!(i);
        }
    """
    pass


@dataclass
class BreakStmt:
    """
    Statement `break;`.

    Break untuk loop:
        - Keluar dari loop terdekat
        - Melanjutkan eksekusi setelah loop

    Contoh:
        for i < 10 {
            if i == 5 { break; }
            print!(i);
        }
    """
    pass


@dataclass
class LetStmt:
    """
    Statement `let name: type_name = value;` -- deklarasi variabel lokal.

    Let statement untuk deklarasi variabel:
        - Nama variabel (wajib)
        - Tipe (opsional, bisa di-infer)
        - Nilai awal (wajib)
        - Mutable atau immutable (opsional, default immutable)

    Contoh:
        let x: i32 = 42;
        let mut count = 0;
        let name = "hello";
    """
    name: str
    value: Expr
    type_name: str | None = None
    is_mut: bool = False

# Type alias untuk semua jenis statement
Stmt = ReturnStmt | IfStmt | WhileStmt | AssignStmt | LetStmt | ExprStmt | MatchStmt | ContinueStmt | BreakStmt

@dataclass
class FnDecl:
    """
    Merepresentasikan `fn name(params) -> return_type { body }`.

    Fungsi adalah unit kode yang bisa dipanggil:
        - Nama fungsi
        - Parameter (list of Param)
        - Return type (default "void")
        - Body (list of Stmt)
        - Metadata: is_internal (dari runtime), self_param, struct_name

    Contoh:
        fn add(a: i32, b: i32) -> i32 {
            ret a + b;
        }

        fn print(&self, msg: str) {
            // method dengan self parameter
        }

    Method functions memiliki self_param dan struct_name yang di-attach
    oleh type checker.
    """
    name: str
    params: list[Param] = field(default_factory=list)
    return_type: str = "void"
    body: list[Stmt] = field(default_factory=list)
    is_internal: bool = False
    self_param: SelfParam | None = None
    struct_name: str | None = None
