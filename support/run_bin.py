#!/usr/bin/env python3
"""Run a Terse-built binary (handles Windows .exe)."""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path


def win_status(code: int) -> str:
    u = code & 0xFFFFFFFF
    known = {
        0xC0000005: "STATUS_ACCESS_VIOLATION",
        0xC0000135: "STATUS_DLL_NOT_FOUND",
        0xC0000139: "STATUS_ENTRYPOINT_NOT_FOUND",
        0xC000007B: "STATUS_INVALID_IMAGE_FORMAT",
    }
    if u in known:
        return f"0x{u:08X} {known[u]}"
    if u >= 0xC0000000:
        return f"0x{u:08X} (Windows exception)"
    return str(code)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("binary")
    ap.add_argument("args", nargs="*")
    ap.add_argument("-v", "--verbose", action="store_true")
    ns = ap.parse_args()

    base = Path(ns.binary)
    candidates = [base]
    if base.suffix.lower() != ".exe":
        candidates.append(Path(str(base) + ".exe"))
        candidates.append(base.with_suffix(".exe"))
    bin_path = next((p for p in candidates if p.is_file()), None)
    if bin_path is None:
        print(f"missing binary: {base} (.exe)", file=sys.stderr)
        for p in candidates:
            print(f"  tried: {p}", file=sys.stderr)
        return 127

    if ns.verbose or os.environ.get("TERSE_VERBOSE"):
        print(f"run: {bin_path}", file=sys.stderr)

    r = subprocess.run([str(bin_path)] + list(ns.args))
    code = r.returncode or 0
    if code:
        u = code & 0xFFFFFFFF
        print(f"run failed: exit {code} ({win_status(code)})", file=sys.stderr)
        if u in (0xC0000135, 0xC0000139, 0xC000007B):
            print(
                "hint: DLL/runtime issue. Put MinGW bin on PATH, or:\n"
                "  export TERSE_NO_TLS=1\n"
                "  python3 compiler/tersec.py build ... -f",
                file=sys.stderr,
            )
    return code


if __name__ == "__main__":
    sys.exit(main())
