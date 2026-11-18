#!/usr/bin/env python3
"""Build and run Terse tests. Cross-platform (Windows/macOS/Linux).

Usage:
  python3 support/run_tst.py              # all tst/t_*.te
  python3 support/run_tst.py t_hi         # one test (with or without .te)
  python3 support/run_tst.py --list
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path


def project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def out_dir() -> Path:
    env = os.environ.get("TERSE_OUT")
    if env:
        return Path(env).expanduser().resolve()
    return (Path.home() / ".terse" / "out").resolve()


def tersec() -> Path:
    return project_root() / "compiler" / "tersec.py"


def python_exe() -> str:
    return sys.executable


def build_and_run(test_stem: str, verbose: bool = False) -> int:
    root = project_root()
    src = root / "tst" / f"{test_stem}.te"
    if not src.is_file():
        # allow tst/t_hi.te passed as t_hi.te
        alt = root / "tst" / test_stem
        if alt.suffix == ".te" and alt.is_file():
            src = alt
            test_stem = alt.stem
        else:
            print(f"missing test: {src}", file=sys.stderr)
            return 1

    out = out_dir()
    out.mkdir(parents=True, exist_ok=True)
    bin_path = out / test_stem

    cmd = [
        python_exe(),
        str(tersec()),
        "build",
        str(src),
        "-o",
        str(bin_path),
        "-f",
    ]
    if verbose:
        print(" ", " ".join(cmd))
    r = subprocess.run(cmd, cwd=str(root))
    if r.returncode != 0:
        print(f"BUILD FAIL {test_stem}", file=sys.stderr)
        return r.returncode or 1

    # Windows may write bin.exe
    run_bin = bin_path
    if not run_bin.is_file():
        exe = Path(str(bin_path) + ".exe")
        if exe.is_file():
            run_bin = exe
    if not run_bin.is_file():
        print(f"missing binary after build: {bin_path} (.exe)", file=sys.stderr)
        return 127

    if verbose:
        print("  run", run_bin)
    r = subprocess.run([str(run_bin)], cwd=str(root))
    if r.returncode != 0:
        code = r.returncode
        u = code & 0xFFFFFFFF
        extra = ""
        if u == 0xC0000139:
            extra = " STATUS_ENTRYPOINT_NOT_FOUND (DLL mismatch — try TERSE_NO_TLS=1 or fix MinGW PATH)"
        elif u == 0xC0000135:
            extra = " STATUS_DLL_NOT_FOUND (put MinGW/OpenSSL bin on PATH, or TERSE_NO_TLS=1)"
        elif u == 0xC0000005:
            extra = " STATUS_ACCESS_VIOLATION"
        print(f"RUN FAIL {test_stem} exit={code}{extra}", file=sys.stderr)
        return code or 1
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Run Terse tst/t_*.te tests")
    ap.add_argument("tests", nargs="*", help="test names (default: all t_*.te)")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    root = project_root()
    tst_dir = root / "tst"
    all_tests = sorted(p.stem for p in tst_dir.glob("t_*.te"))

    if args.list:
        for n in all_tests:
            print(n)
        return 0

    names = args.tests or all_tests
    # normalize: strip path and .te
    norm = []
    for n in names:
        n = Path(n).name
        if n.endswith(".te"):
            n = n[:-3]
        norm.append(n)

    print(f"Running {len(norm)} test(s)  OUT={out_dir()}")
    failed = []
    for i, name in enumerate(norm, 1):
        sys.stdout.write(".")
        sys.stdout.flush()
        rc = build_and_run(name, verbose=args.verbose)
        if rc != 0:
            failed.append(name)
            print()
            print(f"FAIL {name} (rc={rc})")
            break
    print()
    if failed:
        print(f"{len(failed)} failed: {', '.join(failed)}")
        return 1
    print("all tst ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
