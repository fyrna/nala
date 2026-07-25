# bootstrap/main.py
"""
Bootstrap Nala compiler entry point.
Flow: lexer → parser → type checker (AST→HIR) → codegen (HIR→C).
"""
from __future__ import annotations
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from parser import parse_source, ParseError

def _collect_na_files(source_path: str) -> list[Path]:
    """
    Collect .na or .na.txt files.
    - If path is dir: collect all *.na/*.na.txt (flat, sorted).
    - If path is file: try exact, then with .na, then .na.txt; validate extension.
    """
    path = Path(source_path)
    if path.is_dir():
        na_files = sorted(path.glob("*.na")) + sorted(path.glob("*.na.txt"))
        if not na_files:
            print(f"error: no .na/.na.txt in {source_path}", file=sys.stderr)
            sys.exit(1)
        return na_files
    if not path.exists():
        for ext in (".na", ".na.txt"):
            p = path.with_suffix(ext)
            if p.exists():
                path = p
                break
        else:
            print(f"error: file not found: {source_path}", file=sys.stderr)
            sys.exit(1)
    if not (str(path).endswith(".na") or str(path).endswith(".na.txt")):
        print(f"error: file must have .na or .na.txt extension: {path}", file=sys.stderr)
        sys.exit(1)
    return [path]

def compile_to_c(source_path: str, output_path: str) -> None:
    """
    Full compilation: collect files, parse to raw AST, type-check to HIR, generate C.
    Errors: ParseError, NotImplementedError, TypeCheckError cause exit(1).
    """
    from backend.codegen import gen_program
    from ir.hir_builder import check_program
    from ir.typecheck.symbol_table import TypeCheckError

    na_files = _collect_na_files(source_path)
    all_decls = []
    for na_file in na_files:
        source = na_file.read_text(encoding="utf-8")
        try:
            decls = parse_source(source)
        except (ParseError, NotImplementedError) as e:
            print(f"error parsing {na_file}: {e}", file=sys.stderr)
            sys.exit(1)
        all_decls.extend(decls)
        print(f"  parsed: {na_file.name} ({len(decls)} decls)")
    try:
        hir_decls = check_program(all_decls)
    except TypeCheckError as e:
        print(f"error type check: {e}", file=sys.stderr)
        sys.exit(1)
    c_code = gen_program(hir_decls)
    Path(output_path).write_text(c_code, encoding="utf-8")
    print(f"OK: {source_path} -> {output_path} ({len(all_decls)} total decls from {len(na_files)} files)")

if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("usage: python main.py <input.na|folder> <output.c>")
        sys.exit(1)
    compile_to_c(sys.argv[1], sys.argv[2])
