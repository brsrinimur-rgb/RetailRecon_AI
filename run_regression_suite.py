from __future__ import annotations
import pathlib, subprocess, sys

ROOT = pathlib.Path(__file__).resolve().parent
REAL_DATA_REQUIREMENTS = {
    "REGRESSION_V37_AMEX_STATEMENT_PARSER.py": "SE-2026_07_31-9710107967.xlsx",
    "REGRESSION_V38_AMEX_WIRE_TO_BANK.py": "SE-2026_07_31-9710107967.xlsx",
    "REGRESSION_V39_REAL_ANB_FULL_STATEMENT.py": "ACC_0108095820370014_2026-08-02-084639231 - Final.xlsx",
}

def find_fixture(name: str) -> pathlib.Path | None:
    candidates = [ROOT / name, ROOT / "test_data" / name, ROOT / "tests" / "fixtures" / name]
    for p in candidates:
        if p.exists():
            return p
    return None

def main() -> int:
    tests = sorted(ROOT.glob("REGRESSION_*.py"))
    passed = failed = skipped = 0
    print(f"RetailRecon AI regression suite: {len(tests)} tests")
    print("=" * 72)
    for test in tests:
        req = REAL_DATA_REQUIREMENTS.get(test.name)
        if req and find_fixture(req) is None:
            skipped += 1
            print(f"SKIP {test.name}  [requires real fixture: {req}]")
            continue
        proc = subprocess.run([sys.executable, str(test)], cwd=ROOT)
        if proc.returncode == 0:
            passed += 1
            print(f"PASS {test.name}")
        else:
            failed += 1
            print(f"FAIL {test.name} (exit {proc.returncode})")
    print("=" * 72)
    print(f"PASS={passed}  FAIL={failed}  SKIP={skipped}  TOTAL={len(tests)}")
    if skipped:
        print("Skipped tests are evidence-backed real-file tests; copy the named fixture into")
        print("the repository root, test_data/, or tests/fixtures/ and rerun.")
    return 1 if failed else 0

if __name__ == "__main__":
    raise SystemExit(main())
