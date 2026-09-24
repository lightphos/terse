#!/usr/bin/env python3
"""
Terse test runner (terset).

Compiles and runs every t_*.te file under tests/ and reports pass/fail.
A test passes iff the resulting binary exits 0 (tst.check.equals aborts
with exit 1 on mismatch).

Usage:
    python3 compiler/terset.py [-v] [pattern]
"""
import os
import sys
import glob
import argparse
import subprocess

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
TERSEC = os.path.join(os.path.dirname(__file__), "tersec.py")
TEST_DIR = os.path.join(ROOT, "tests")
OUT_DIR = os.path.join(ROOT, "output", "tests")
TIMEOUT = 10.0


def discover(pattern=None):
    """Return sorted list of t_*.te test source paths under tests/."""
    tests = sorted(glob.glob(os.path.join(TEST_DIR, "**", "t_*.te"), recursive=True))
    if pattern:
        tests = [t for t in tests if pattern in os.path.basename(t)]
    return tests


def _find_runtime_sqlite():
    """Locate the runtime libsqlite3.so.* (libsqlite3-dev may not be installed)."""
    for pat in ("/usr/lib/*/libsqlite3.so.*", "/usr/lib64/*/libsqlite3.so.*",
                "/usr/lib/libsqlite3.so.*", "/lib/*/libsqlite3.so.*"):
        for path in glob.glob(pat):
            return path
    return None


def link_env():
    """Env for the tersec subprocess.

    tersec always links -lsqlite3 on non-Windows; if the link-time dev
    symlink is missing, shim it against the runtime .so via LIBRARY_PATH.
    """
    env = dict(os.environ)
    probe = subprocess.run(["gcc", "-print-file-name=libsqlite3.so"],
                           capture_output=True, text=True)
    if probe.returncode == 0 and os.path.isabs(probe.stdout.strip()):
        return env
    runtime = _find_runtime_sqlite()
    if not runtime:
        return env
    shim = os.path.join(OUT_DIR, ".link")
    os.makedirs(shim, exist_ok=True)
    link = os.path.join(shim, "libsqlite3.so")
    if not os.path.exists(link):
        os.symlink(runtime, link)
    env["LIBRARY_PATH"] = shim + os.pathsep + env.get("LIBRARY_PATH", "")
    return env


def compile_test(src_path, out_path, env):
    r = subprocess.run(
        [sys.executable, TERSEC, "build", src_path, "-o", out_path],
        capture_output=True, text=True, env=env,
    )
    return r.returncode, r.stdout + r.stderr


def run_test(out_path):
    try:
        r = subprocess.run([out_path], capture_output=True, text=True, timeout=TIMEOUT)
        return r.returncode, r.stdout + r.stderr, None
    except subprocess.TimeoutExpired:
        return -1, "", f"timed out after {TIMEOUT:.0f}s"


def main():
    ap = argparse.ArgumentParser(description="terset: compile+run all t_*.te tests")
    ap.add_argument("pattern", nargs="?", default=None,
                    help="run only tests whose filename contains PATTERN")
    ap.add_argument("-v", "--verbose", action="store_true",
                    help="show output of failing tests")
    args = ap.parse_args()

    tests = discover(args.pattern)
    if not tests:
        print("no t_*.te tests found" + (f" matching '{args.pattern}'" if args.pattern else ""))
        return 1

    os.makedirs(OUT_DIR, exist_ok=True)
    env = link_env()

    passed = 0
    failed = []
    for src_path in tests:
        name = os.path.splitext(os.path.basename(src_path))[0]
        out_path = os.path.join(OUT_DIR, name)
        code, log = compile_test(src_path, out_path, env)
        if code != 0:
            failed.append((name, "compile failed", log))
            print(f"FAIL {name}: compile failed")
            continue
        rc, out, err = run_test(out_path)
        if rc == 0:
            passed += 1
            print(f"PASS {name}")
        else:
            detail = err if err else f"exit code {rc}"
            failed.append((name, detail, out))
            print(f"FAIL {name}: {detail}")

    print()
    if failed:
        print(f"{passed} passed, {len(failed)} failed")
        if args.verbose:
            for name, detail, out in failed:
                print(f"\n--- {name} ({detail}) ---")
                print(out.strip())
        return 1
    print(f"all {passed} tests passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())