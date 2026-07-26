#!/usr/bin/env python3
import logging
import pathlib
import sys

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("patch_nala")

PATCHES = []

def apply_patch(filepath: pathlib.Path, old_marker: str, new_content: str) -> bool:
    """Apply single marker-based patch."""
    content = filepath.read_text(encoding="utf-8")
    
    if old_marker not in content:
        logger.error(f"Marker not found in {filepath.name}")
        return False
    
    if content.count(old_marker) > 1:
        logger.error(f"Duplicate marker in {filepath.name}")
        return False
    
    new_text = content.replace(old_marker, new_content, 1)
    filepath.write_text(new_text, encoding="utf-8")
    logger.info(f"Patched {filepath.name}")
    return True


def validate_file(filepath: pathlib.Path) -> bool:
    """Validate that file can be imported (basic syntax check)."""
    try:
        compile(filepath.read_text(encoding="utf-8"), filepath.name, "exec")
        return True
    except SyntaxError as e:
        logger.error(f"Syntax error in {filepath.name}: {e}")
        return False


def main() -> int:
    base_dir = pathlib.Path(__file__).parent
    
    for filename, old_marker, new_content in PATCHES:
        filepath = base_dir / filename
        if not filepath.exists():
            logger.error(f"File not found: {filepath}")
            return 1
        
        if not apply_patch(filepath, old_marker, new_content):
            return 1
    
    logger.info("Validating patched files...")
    for filename, _, _ in PATCHES:
        filepath = base_dir / filename
        if not validate_file(filepath):
            return 1
    
    logger.info("All patches applied successfully!")
    return 0


if __name__ == "__main__":
    sys.exit(main())
