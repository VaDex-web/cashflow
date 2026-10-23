"""Мини-раннер тестов на случай, если pytest не установлен: ``python core/tests/run_tests.py``."""
import importlib
import sys
import time
import traceback
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE.parent), str(HERE)]


def main() -> int:
    only = sys.argv[1:]
    failed, passed = [], 0
    for f in sorted(HERE.glob("test_*.py")):
        mod = importlib.import_module(f.stem)
        for name in sorted(n for n in dir(mod) if n.startswith("test_")):
            if only and not any(o in f"{f.stem}.{name}" for o in only):
                continue
            t = time.time()
            try:
                getattr(mod, name)()
                passed += 1
                print(f"PASS {f.stem}.{name} ({time.time() - t:.1f}s)")
            except Exception:  # noqa: BLE001
                failed.append(f"{f.stem}.{name}")
                print(f"FAIL {f.stem}.{name}\n{traceback.format_exc()}")
    print(f"\n{passed} passed, {len(failed)} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
