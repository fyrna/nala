# bootstrap/main.py
"""
Bootstrap Nala compiler entry point.
Flow: lexer → parser → type checker (AST→HIR) → NIR → C.
"""
from __future__ import annotations
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

from lexer import Lexer, LexError
from parser.parser import parse_source, ParseError
from nala_ast.nodes import UseDecl
from backend.codegen import gen_program
from ir.hir.builder import check_program, check_program_modules
from ir import NIRLower
from checker.symbol_table import SymbolTable, TypeCheckError


def _find_mod_na_root(start_path: Path) -> Path:
    """Find root project by searching for mod.na upwards from start_path."""
    path = start_path if start_path.is_dir() else start_path.parent
    while True:
        if (path / "mod.na").exists():
            return path
        parent = path.parent
        if parent == path:
            return start_path if start_path.is_dir() else start_path.parent
        path = parent


def _discover_modules(root: Path) -> dict[str, list[Path]]:
    """
    Discover all modules under root.
    Returns: module_name -> list of .na/.na.txt files.
    Folder = module; sub-folder = independent sub-module.
    """
    modules: dict[str, list[Path]] = {}

    def scan_dir(dir_path: Path, module_prefix: str) -> None:
        na_files = sorted(dir_path.glob("*.na")) + sorted(dir_path.glob("*.na.txt"))
        if na_files:
            modules[module_prefix] = na_files
        for subdir in sorted(dir_path.iterdir()):
            if subdir.is_dir():
                if module_prefix == "local":
                    sub_module = f"local.{subdir.name}"
                else:
                    sub_module = f"{module_prefix}.{subdir.name}"
                scan_dir(subdir, sub_module)

    scan_dir(root, "local")
    return modules


def _find_stdlib_path() -> Path:
    import os
    env_path = os.environ.get("NALA_STDLIB_PATH")
    if env_path:
        return Path(env_path)
    return Path.home() / ".nala" / "library" / "std"


def _discover_modules_with_prefix(root: Path, prefix: str) -> dict[str, list[Path]]:
    modules = {}
    def scan_dir(dir_path: Path, module_prefix: str) -> None:
        na_files = sorted(dir_path.glob("*.na")) + sorted(dir_path.glob("*.na.txt"))
        if na_files:
            modules[module_prefix] = na_files
        for subdir in sorted(dir_path.iterdir()):
            if subdir.is_dir():
                scan_dir(subdir, f"{module_prefix}.{subdir.name}")
    scan_dir(root, prefix)
    return modules


def compile_to_c(source_path: str, output_path: str) -> None:
    """
    Full compilation: discover modules via mod.na, parse per module,
    type-check with module context, generate C.
    """
    input_path = Path(source_path)

    # Single file mode: compile just that file as standalone module
    if input_path.is_file():
        root = input_path.parent
        user_modules = {"local": [input_path]}
        print(f"  single file mode: {input_path.name}")
    else:
        # Directory mode: discover modules via mod.na
        root = _find_mod_na_root(input_path)
        print(f"  root project: {root}")
        user_modules = _discover_modules(root)

    # Load stdlib
    stdlib_path = _find_stdlib_path()
    std_modules = {}
    if stdlib_path.exists():
        std_modules = _discover_modules_with_prefix(stdlib_path, "std")
        print(f"  stdlib found: {len(std_modules)} modules")
    else:
        print(f"  warning: stdlib not found at {stdlib_path}", file=sys.stderr)

    # Merge: std first, then user (user overrides)
    modules = {**std_modules, **user_modules}
    if not modules:
        print(f"error: no modules found", file=sys.stderr)
        sys.exit(1)

    module_decls: dict[str, list] = {}
    module_uses: dict[str, list] = {}

    for module_name, files in modules.items():
        module_decls[module_name] = []
        module_uses[module_name] = []
        for na_file in files:
            source = na_file.read_text(encoding="utf-8")
            try:
                decls = parse_source(source)
            except (ParseError, NotImplementedError) as e:
                print(f"error parsing {na_file}: {e}", file=sys.stderr)
                sys.exit(1)
            for d in decls:
                if isinstance(d, UseDecl):
                    module_uses[module_name].append(d)
                else:
                    module_decls[module_name].append(d)
            print(f"  parsed: {na_file.name} in module {module_name} ({len(decls)} decls)")

    # Duplicate identifier check within same module
    for module_name, decls in module_decls.items():
        seen: dict[str, int] = {}
        for d in decls:
            name = getattr(d, "name", None)
            if name is not None:
                if name in seen:
                    print(
                        f"error: duplicate identifier '{name}' in module '{module_name}' "
                        f"(first at decl {seen[name]}, second at decl {len(seen)})",
                        file=sys.stderr,
                    )
                    sys.exit(1)
                seen[name] = len(seen)

    try:
        hir_decls = check_program_modules(module_decls, module_uses)
    except TypeCheckError as e:
        print(f"error type check: {e}", file=sys.stderr)
        sys.exit(1)

    # LOWER HIR → NIR
    table = SymbolTable.build_modules(module_decls, module_uses)
    lower = NIRLower(table)
    nir_program = lower.lower_program(hir_decls)

    # GENERATE C FROM NIR
    c_code = gen_program(nir_program)
    Path(output_path).write_text(c_code, encoding="utf-8")
    total_decls = sum(len(d) for d in module_decls.values())
    print(f"OK: {source_path} -> {output_path} ({total_decls} total decls)")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("usage: python main.py <input.na|folder> <output.c>")
        sys.exit(1)
    compile_to_c(sys.argv[1], sys.argv[2])
