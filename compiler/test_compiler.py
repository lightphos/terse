#!/usr/bin/env python3
"""Unit tests for the Terse host compiler (tersec.py).

Aligned with SPEC 0.3: val/var (no let), go entry, modules, lists, tst.
Exit code may equal the go result when non-zero; tests primarily assert stdout.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import textwrap
import unittest

ROOT = os.path.abspath(os.path.dirname(__file__))
TERSEC = os.path.join(ROOT, "tersec.py")
SRC = os.path.join(ROOT, "src")


def compile_src(src: str, name: str = "t"):
    tmp = tempfile.mkdtemp(prefix="terse_test_")
    src_path = os.path.join(tmp, name + ".te")
    bin_path = os.path.join(tmp, name)
    with open(src_path, "w", encoding="utf-8") as f:
        f.write(src)
    r = subprocess.run(
        [sys.executable, TERSEC, "build", src_path, "-o", bin_path],
        capture_output=True,
        text=True,
    )
    return bin_path, r.returncode, r.stdout + r.stderr


def run_bin(bin_path: str, timeout: float = 5.0):
    r = subprocess.run([bin_path], capture_output=True, text=True, timeout=timeout)
    return r.returncode, r.stdout, r.stderr


def compile_and_run(src: str):
    bin_path, code, log = compile_src(src)
    if code != 0:
        raise AssertionError(f"compile failed:\n{log}")
    return run_bin(bin_path)


def assert_result(test: unittest.TestCase, src: str, expected: str):
    """Last stdout line equals expected (exit code may equal numeric result)."""
    rc, out, err = compile_and_run(src)
    lines = [ln for ln in out.strip().splitlines() if ln]
    test.assertTrue(lines, msg=f"empty stdout rc={rc} err={err!r}")
    test.assertEqual(lines[-1], expected, msg=f"stdout={out!r} stderr={err!r}")


class TestArithmetic(unittest.TestCase):
    def test_add(self):
        assert_result(self, "go 40 + 2", "42")

    def test_mul_div(self):
        assert_result(self, "go (3 * 4) + (10 / 2)", "17")

    def test_fact(self):
        src = textwrap.dedent("""\
            fn fact(n: i64) -> i64 =
              if n <= 1 { 1 } else { n * fact(n - 1) }
            go fact(6)
        """)
        assert_result(self, src, "720")


class TestControl(unittest.TestCase):
    def test_if(self):
        src = textwrap.dedent("""\
            fn abs(x: i64) -> i64 = if x < 0 { 0 - x } else { x }
            go abs(0 - 7) + abs(3)
        """)
        assert_result(self, src, "10")

    def test_ret_without_value(self):
        assert_result(self, "go { ret }", "0")

    def test_ret_with_value(self):
        src = textwrap.dedent("""\
            go {
              val x = 10
              ret x + 2
            }
        """)
        assert_result(self, src, "12")

    def test_val(self):
        src = textwrap.dedent("""\
            go {
              val a = 10
              val b = 32
              a + b
            }
        """)
        assert_result(self, src, "42")

    def test_typed_val(self):
        src = textwrap.dedent("""\
            go {
              val s: str = "s"
              val i = 1
              pr(s)
              pr(i)
            }
        """)
        rc, out, err = compile_and_run(src)
        self.assertIn("s", out)
        self.assertIn("1", out)

    def test_loop_while(self):
        src = textwrap.dedent("""\
            go {
              var i = 0
              var sum = 0
              lp i < 5 {
                sum = sum + i
                i = i + 1
              }
              sum
            }
        """)
        assert_result(self, src, "10")

    def test_loop_for(self):
        src = textwrap.dedent("""\
            go {
              var sum = 0
              lp i = 0; i < 10; i = i + 1 {
                sum = sum + i
              }
              sum
            }
        """)
        assert_result(self, src, "45")


class TestHigherOrder(unittest.TestCase):
    def test_apply(self):
        src = textwrap.dedent("""\
            fn apply(f: fn, x: i64) -> i64 = f(x)
            fn double(n: i64) -> i64 = n * 2
            go apply(double, 21)
        """)
        assert_result(self, src, "42")

    def test_lambda(self):
        src = textwrap.dedent("""\
            fn apply(f: fn, x: i64) -> i64 = f(x)
            go apply(|n| n + 100, 7)
        """)
        assert_result(self, src, "107")


class TestRecords(unittest.TestCase):
    def test_rec(self):
        src = textwrap.dedent("""\
            rec Point { x: i64, y: i64 }
            go {
              val p = Point { x: 3, y: 4 }
              p.x + p.y
            }
        """)
        assert_result(self, src, "7")

    def test_method(self):
        src = textwrap.dedent("""\
            Point { x: i64, y: i64 }
            fn Point.add() -> i64 { self.x + self.y }
            go {
              val p = Point { x: 3, y: 2 }
              p.add()
            }
        """)
        assert_result(self, src, "5")

    def test_record_return(self):
        src = textwrap.dedent("""\
            Pair { value: i64 }
            fn make_pair() -> Pair { Pair { value: 41 } }
            go {
              val pair = make_pair()
              pair.value + 1
            }
        """)
        assert_result(self, src, "42")


class TestStringsLists(unittest.TestCase):
    def test_print_int(self):
        rc, out, _ = compile_and_run("go { pr(42) }")
        self.assertIn("42", out)

    def test_string_concat(self):
        src = textwrap.dedent("""\
            go {
              val s = "hel" + "lo"
              pr(s)
              pr(len(s))
            }
        """)
        rc, out, _ = compile_and_run(src)
        self.assertIn("hello", out)
        self.assertIn("5", out)

    def test_pr_mixed_string_concat(self):
        src = textwrap.dedent("""\
            go {
              val a = 7
              pr("> " + a)
            }
        """)
        rc, out, _ = compile_and_run(src)
        self.assertIn("> 7", out)

    def test_list(self):
        src = textwrap.dedent("""\
            go {
              val xs = [10, 20, 30]
              pr(xs)
              pr(len(xs))
              pr(xs[1])
            }
        """)
        rc, out, _ = compile_and_run(src)
        self.assertIn("[10, 20, 30]", out)
        self.assertIn("3", out)
        self.assertIn("20", out)

    def test_list_push_concat(self):
        src = textwrap.dedent("""\
            go {
              var xs: [i64] = []
              xs = xs + 1
              xs = xs + [2, 3]
              len(xs)
            }
        """)
        assert_result(self, src, "3")


class TestEntryPoints(unittest.TestCase):
    def test_go_empty(self):
        assert_result(self, "go()", "0")

    def test_fn_main_rejected(self):
        _, code, log = compile_src("fn main() -> i64 = 1")
        self.assertNotEqual(code, 0)
        self.assertTrue("go" in log.lower() or "main" in log.lower())

    def test_go_expr(self):
        assert_result(self, "go 55", "55")

    def test_go_block_pr(self):
        rc, out, _ = compile_and_run("go { pr(3); 9 }")
        self.assertIn("3", out)


class TestModules(unittest.TestCase):
    def test_use_arith(self):
        arith = os.path.join(SRC, "arith.te")
        if not os.path.isfile(arith):
            self.skipTest("src/arith.te missing")
        tdir = os.path.join(ROOT, "tst")
        os.makedirs(tdir, exist_ok=True)
        tpath = os.path.join(tdir, "t_use_arith_unit.te")
        with open(tpath, "w", encoding="utf-8") as f:
            f.write("use arith\ngo { pr(add()) }\n")
        tmp = tempfile.mkdtemp(prefix="terse_mod_")
        bin_path = os.path.join(tmp, "t_use_arith")
        r = subprocess.run(
            [sys.executable, TERSEC, "build", tpath, "-o", bin_path],
            capture_output=True,
            text=True,
            cwd=ROOT,
        )
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        rc, out, err = run_bin(bin_path)
        self.assertIn("42", out)

    def test_unknown_import(self):
        _, code, log = compile_src("use no_such_module_xyz\ngo 0")
        self.assertNotEqual(code, 0)


class TestErrors(unittest.TestCase):
    def test_unknown_function(self):
        _, code, log = compile_src("go { pr(no_such_fn()) }")
        self.assertNotEqual(code, 0)
        self.assertIn("unknown", log.lower())

    def test_unknown_name(self):
        _, code, log = compile_src("go { pr(not_defined) }")
        self.assertNotEqual(code, 0)
        self.assertIn("undeclared identifier", log.lower())


class TestFix(unittest.TestCase):
    def test_fix_local(self):
        src = textwrap.dedent("""\
            fix N: i64 = 7
            go N + 1
        """)
        assert_result(self, src, "8")


class TestEnums(unittest.TestCase):
    def test_option_pattern(self):
        src = textwrap.dedent("""\
            en Option {
              Some(i64),
              None
            }
            fn unwrap(o: Option) -> i64 =
              if o {
                Option.Some(n) => n
                Option.None => 0
              }
            go unwrap(Option.Some(9))
        """)
        assert_result(self, src, "9")


class TestIo(unittest.TestCase):
    def test_io_roundtrip(self):
        with tempfile.TemporaryDirectory(prefix="terse_io_") as d:
            path = os.path.join(d, "f.txt").replace("\\", "/")
            src = (
                "use std.io\n"
                "go {\n"
                f'  io.out("{path}", "hello")\n'
                f'  pr(io.in("{path}"))\n'
                "}\n"
            )
            rc, out, err = compile_and_run(src)
            self.assertIn("hello", out)


class TestMaps(unittest.TestCase):
    def test_map_put_get(self):
        src = (
            "go {\n"
            "  var m: {str: i64} = {:}\n"
            '  m["a"] = 3\n'
            '  m["a"]\n'
            "}\n"
        )
        assert_result(self, src, "3")


if __name__ == "__main__":
    unittest.main()
