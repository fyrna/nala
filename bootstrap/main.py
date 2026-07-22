"""
bootstrap/main.py

Entry point bootstrap Nala compiler.

Arsitektur:
    Frontend (syntax + semantik):
        lexer.py        → Token stream
        parser.py       → AST raw (masih ada DottedAccess/DottedCall)
        type_checker.py → AST final (resolved + metadata attached)

    Backend (code generation):
        backend/codegen.py   → C code
        backend/runtime.py   → C runtime (embedded)

    Alur: Parser → Type Checker → Codegen
    FILOSOFI FYRNA:
    - Parser shall know nothing except language syntax.
    - Codegen shall only translate. no inference, no semantic decisions.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Tambahkan direktori parent ke path Python agar modul-modul lokal dapat diimpor
sys.path.insert(0, str(Path(__file__).parent))

from parser import parse_source, ParseError


def _collect_na_files(source_path: str) -> list[Path]:
    """
    Kumpulkan semua file .na yang akan di-compile.

    Fungsi ini bertanggung jawab untuk menemukan dan mengumpulkan semua file
    sumber Nala yang akan diproses dalam satu sesi kompilasi.

    Alur pencarian:
        1. Jika source_path adalah folder:
           - Scan semua file dengan ekstensi .na atau .na.txt di folder tersebut
           - Pengurutan dilakukan secara alfabetis untuk konsistensi build
           - Hanya scan level flat (tidak rekursif ke subfolder)
        
        2. Jika source_path adalah file:
           - Cek apakah file dengan nama persis tersebut ada
           - Jika tidak ada, coba tambahkan ekstensi .na
           - Jika masih tidak ada, coba tambahkan ekstensi .na.txt
           - Validasi ekstensi file harus .na atau .na.txt
        
        3. Jika file tidak ditemukan sama sekali:
           - Tampilkan pesan error dan exit dengan kode 1

    Args:
        source_path (str): Path ke folder atau file sumber

    Returns:
        list[Path]: Daftar path file .na atau .na.txt yang valid

    Raises:
        SystemExit: Jika tidak ada file ditemukan atau file tidak valid
    """
    path = Path(source_path)

    # Kasus 1: Input adalah direktori
    if path.is_dir():
        # Scan BOTH *.na and *.na.txt
        na_files = sorted(path.glob("*.na")) + sorted(path.glob("*.na.txt"))
        if not na_files:
            print(f"error: tidak ada file .na atau .na.txt di folder: {source_path}", file=sys.stderr)
            sys.exit(1)
        return na_files

    # Kasus 2: Input adalah file
    if not path.exists():
        # Coba tambahkan ekstensi .na atau .na.txt
        path_with_ext = path.with_suffix(".na")
        if path_with_ext.exists():
            path = path_with_ext
        else:
            path_with_ext_txt = path.with_suffix(".na.txt")
            if path_with_ext_txt.exists():
                path = path_with_ext_txt
            else:
                print(f"error: file tidak ditemukan: {source_path}", file=sys.stderr)
                sys.exit(1)

    # Validasi ekstensi file (harus .na atau .na.txt)
    if not (str(path).endswith(".na") or str(path).endswith(".na.txt")):
        print(f"error: file harus ber-ekstensi .na atau .na.txt: {path}", file=sys.stderr)
        sys.exit(1)

    return [path]


def compile_to_c(source_path: str, output_path: str) -> None:
    """
    Fungsi utama kompilasi Nala ke C.

    Alur lengkap kompilasi:
        1. Kumpulkan semua file sumber (.na atau .na.txt)
        2. Parse setiap file menjadi AST (Abstract Syntax Tree)
        3. Type checking: resolve semua referensi dan attach metadata
        4. Generate kode C dari AST yang sudah di-type-check
        5. Tulis kode C ke file output

    Tahapan ini memisahkan dengan jelas antara frontend (parsing + type checking)
    dan backend (code generation), sesuai dengan arsitektur yang dirancang.

    Error handling:
        - ParseError: Error sintaks di source code
        - NotImplementedError: Fitur bahasa yang belum didukung
        - TypeCheckError: Error semantik (type mismatch, undefined variable, dll)
        - Semua error akan ditampilkan ke stderr dan exit dengan kode 1

    Args:
        source_path (str): Path ke folder atau file .na yang akan dikompilasi
        output_path (str): Path tujuan file .c yang akan dihasilkan

    Returns:
        None

    Raises:
        SystemExit: Jika terjadi error di setiap tahap kompilasi
    """
    from backend.codegen import gen_program
    from type_checker import check_program, TypeCheckError

    # Step 1: Kumpulkan semua file sumber
    na_files = _collect_na_files(source_path)
    all_decls: list = []

    # Step 2: Parse setiap file
    for na_file in na_files:
        source = na_file.read_text(encoding="utf-8")

        try:
            decls = parse_source(source)
        except ParseError as e:
            print(f"error parsing {na_file}: {e}", file=sys.stderr)
            sys.exit(1)
        except NotImplementedError as e:
            print(f"error: fitur belum didukung saat parsing {na_file}: {e}", file=sys.stderr)
            sys.exit(1)

        all_decls.extend(decls)
        print(f"  parsed: {na_file.name} ({len(decls)} deklarasi)")

    # Step 3: Frontend - Type checking
    # Resolve DottedAccess/DottedCall + attach metadata (union_name, bind_type)
    # Tahap ini mengubah AST raw menjadi AST final dengan semua informasi semantik
    try:
        all_decls = check_program(all_decls)
    except TypeCheckError as e:
        print(f"error type check: {e}", file=sys.stderr)
        sys.exit(1)

    # Step 4: Backend - Code generation
    # Terjemahkan AST final ke kode C murni tanpa inferensi tambahan
    c_code = gen_program(all_decls)

    # Step 5: Tulis output
    out_file = Path(output_path)
    out_file.write_text(c_code, encoding="utf-8")
    print(f"OK: {source_path} -> {output_path} ({len(all_decls)} total deklarasi dari {len(na_files)} file)")


if __name__ == "__main__":
    """
    Entry point utama ketika script dijalankan langsung.
    
    Validasi argumen command line:
        - Harus tepat 3 argumen (termasuk script name)
        - Argumen 1: input source (folder atau file .na)
        - Argumen 2: output file C
    
    Contoh penggunaan:
        python main.py . output.c       # Compile semua .na di folder saat ini
        python main.py src/ output.c    # Compile semua .na di folder src/
        python main.py program.na out.c # Compile satu file program.na
    """
    if len(sys.argv) != 3:
        print("usage: python main.py <input.na|folder> <output.c>")
        print("       python main.py . output.c       # compile semua .na di folder")
        print("       python main.py file.na output.c  # compile satu file")
        sys.exit(1)

    compile_to_c(sys.argv[1], sys.argv[2])
