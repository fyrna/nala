#!/usr/bin/env python
"""
tester.py
"""

import subprocess
import sys
from pathlib import Path

class Colors:
    RED = '\033[91m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    NORMAL = '\033[0m'

def run_test(test_file: Path, main_py: Path, out_dir: Path) -> tuple[str, str]: 
    name = test_file.stem

    if test_file.suffix == '.txt' and test_file.stem.endswith('.na'):
        name = test_file.stem[:-3]
    
    c_file = out_dir / f"{name}.c"
    bin_file = out_dir / name
    err_file = out_dir / f"{name}.err"
    
    print(f"Testing {Colors.YELLOW}{name}{Colors.NORMAL} ... ", end='', flush=True)
    
    # Step 1: Compile .na -> .c
    result = subprocess.run(
        [sys.executable, str(main_py), str(test_file), str(c_file)],
        capture_output=True,
        text=True
    )
    
    if result.returncode != 0:
        err_file.write_text(result.stderr + result.stdout)
        print(f"{Colors.RED}[COMPILE FAIL]{Colors.NORMAL}")
        return 'failed', f"Error log: {err_file}"
    
    # Step 2: Compile .c -> binary
    if not subprocess.run(['which', 'gcc'], capture_output=True).returncode == 0:
        print(f"{Colors.YELLOW}[COMPILE OK, no gcc]{Colors.NORMAL}")
        return 'skipped', ''
    
    result = subprocess.run(
        ['gcc', '-std=c11', '-o', str(bin_file), str(c_file)],
        capture_output=True,
        text=True
    )
    
    if result.returncode != 0:
        err_file.write_text(result.stderr + result.stdout)
        print(f"{Colors.RED}[GCC FAIL]{Colors.NORMAL}")
        return 'failed', f"Error log: {err_file}"
    
    # Step 3: Run binary
    bin_file.chmod(0o755)
    result = subprocess.run([str(bin_file)], capture_output=True, text=True)
    
    if result.returncode == 0:
        print(f"{Colors.GREEN}[PASS]{Colors.NORMAL}")
        return 'passed', ''
    else:
        err_file.write_text(result.stdout + result.stderr)
        print(f"{Colors.RED}[RUN FAIL] exit={result.returncode}{Colors.NORMAL}")
        return 'failed', f"Output: {err_file}"

def main():
    script_dir = Path(__file__).parent
    
    main_py = script_dir / 'bootstrap' / 'main.py'
    if not main_py.exists():
        main_py = script_dir / 'main.py'
    
    if not main_py.exists():
        print(f"{Colors.RED}main.py not found{Colors.NORMAL}")
        sys.exit(1)
    
    test_dir = script_dir / 'tests'
    out_dir = script_dir / '_test_out'
    
    out_dir.mkdir(exist_ok=True)
    
    # Find all test files
    test_files = sorted(
        list(test_dir.glob('*.na')) + 
        list(test_dir.glob('*.na.txt'))
    )
    
    if not test_files:
        print(f"{Colors.RED}No test files found in {test_dir}{Colors.NORMAL}")
        sys.exit(1)
    
    print()
    print(f"{Colors.BLUE}Test Start{Colors.NORMAL}")
    print(f"Found {len(test_files)} test file(s)")
    print(f"  script_dir: {script_dir}")
    print(f"  main.py:    {main_py}")
    print(f"  test_dir:   {test_dir}")
    print(f"  out_dir:    {out_dir}")
    print()
    
    stats = {'passed': 0, 'failed': 0, 'skipped': 0}
    
    for test_file in test_files:
        status, message = run_test(test_file, main_py, out_dir)
        stats[status] += 1
        if message:
            print(f"    {message}")
    
    # Summary
    print()
    print(f"Results: {Colors.GREEN}{stats['passed']} passed{Colors.NORMAL} | "
          f"{Colors.RED}{stats['failed']} failed{Colors.NORMAL} | "
          f"{Colors.YELLOW}{stats['skipped']} skipped")
    
    sys.exit(1 if stats['failed'] > 0 else 0)

if __name__ == '__main__':
    main()
