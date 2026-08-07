#!/usr/bin/env python3
"""Unit tests for the Terse compiler (tersec)."""
import os
import sys
import subprocess
import tempfile
import unittest
import textwrap

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
TERSEC = os.path.join(ROOT, "compiler", "tersec.py")
EXAMPLES = os.path.join(ROOT, "examples")


def compile_src(src: str, name: str = "t"):
    """Compile Terse source string; return (bin_path, compile_stderr)."""
    tmp = tempfile.mkdtemp(prefix="terse_test_")
    src_path = os.path.join(tmp, name + ".terse")
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
    rc, out, err = run_bin(bin_path)
    return rc, out, err


class TestArithmetic(unittest.TestCase):
    def test_add(self):
        rc, out, _ = compile_and_run("fn main() -> i64 = 40 + 2")
        self.assertEqual(rc, 0)
        self.assertEqual(out.strip(), "42")

    def test_mul_div(self):
        rc, out, _ = compile_and_run("fn main() -> i64 = (3 * 4) + (10 / 2)")
        self.assertEqual(rc, 0)
        self.assertEqual(out.strip(), "17")

    def test_fact(self):
        src = textwrap.dedent("""\
            fn fact(n: i64) -> i64 =
              if n <= 1 { 1 } else { n * fact(n - 1) }
            fn main() -> i64 = fact(6)
        """)
        rc, out, _ = compile_and_run(src)
        self.assertEqual(rc, 0)
        self.assertEqual(out.strip(), "720")


class TestControl(unittest.TestCase):
    def test_if(self):
        src = textwrap.dedent("""\
            fn abs(x: i64) -> i64 = if x < 0 { 0 - x } else { x }
            fn main() -> i64 = abs(0 - 7) + abs(3)
        """)
        rc, out, _ = compile_and_run(src)
        self.assertEqual(rc, 0)
        self.assertEqual(out.strip(), "10")

    def test_ret_without_value(self):
        src = textwrap.dedent("""\
            fn main() -> i64 {
              ret
            }
        """)
        rc, out, _ = compile_and_run(src)
        self.assertEqual(rc, 0)
        self.assertEqual(out.strip(), "0")

    def test_ret_with_value(self):
        src = textwrap.dedent("""\
            fn main() -> i64 {
              let x = 10
              ret x + 2
            }
        """)
        rc, out, _ = compile_and_run(src)
        self.assertEqual(rc, 0)
        self.assertEqual(out.strip(), "12")

    def test_let(self):
        src = textwrap.dedent("""\
            fn main() -> i64 {
              let a = 10
              let b = 32
              a + b
            }
        """)
        rc, out, _ = compile_and_run(src)
        self.assertEqual(rc, 0)
        self.assertEqual(out.strip(), "42")

    def test_typed_let(self):
        src = textwrap.dedent("""\
            fn main() -> i64 {
              let s: str = "s"
              let i = 1
              pr(s)
              pr(i)
            }
        """)
        rc, out, _ = compile_and_run(src)
        self.assertEqual(rc, 0)
        self.assertIn("s", out)
        self.assertIn("1", out)

    def test_loop_while(self):
        src = textwrap.dedent("""\
            fn main() -> i64 {
              let i = 0
              let sum = 0
              lp i < 5 {
                sum = sum + i
                i = i + 1
              }
              sum
            }
        """)
        rc, out, _ = compile_and_run(src)
        self.assertEqual(rc, 0)
        self.assertEqual(out.strip(), "10")

    def test_loop_for(self):
        src = textwrap.dedent("""\
            fn main() -> i64 {
              let sum = 0
              lp i = 0; i < 10; i = i + 1 {
                sum = sum + i
              }
              sum
            }
        """)
        rc, out, _ = compile_and_run(src)
        self.assertEqual(rc, 0)
        self.assertEqual(out.strip(), "45")


class TestHigherOrder(unittest.TestCase):
    def test_apply(self):
        src = textwrap.dedent("""\
            fn apply(f: fn, x: i64) -> i64 = f(x)
            fn double(n: i64) -> i64 = n * 2
            fn main() -> i64 = apply(double, 21)
        """)
        rc, out, _ = compile_and_run(src)
        self.assertEqual(rc, 0)
        self.assertEqual(out.strip(), "42")

    def test_lambda(self):
        src = textwrap.dedent("""\
            fn apply(f: fn, x: i64) -> i64 = f(x)
            fn main() -> i64 = apply(|n| n + 100, 7)
        """)
        rc, out, _ = compile_and_run(src)
        self.assertEqual(rc, 0)
        self.assertEqual(out.strip(), "107")


class TestRecords(unittest.TestCase):
    def test_rec(self):
        src = textwrap.dedent("""\
            rec Point { x: i64, y: i64 }
            fn main() -> i64 {
              let p = Point { x: 1, y: 2 }
              p.x + p.y
            }
        """)
        rc, out, _ = compile_and_run(src)
        self.assertEqual(rc, 0)
        self.assertEqual(out.strip(), "3")

    def test_bare_structure(self):
        src = textwrap.dedent("""\
            Point { x: i64, y: i64 }
            fn main() -> i64 {
              let p = Point { x: 1, y: 2 }
              p.x + p.y
            }
        """)
        rc, out, _ = compile_and_run(src)
        self.assertEqual(rc, 0)
        self.assertEqual(out.strip(), "3")

    def test_sig_and_fit(self):
        src = textwrap.dedent("""\
            Point { x: i64, y: i64 }
            sig Printable {
              fn str() -> str
            }
            fit Point as Printable {
              fn show() -> i64 { 7 }
              fn str() -> str {
                "ok"
              }
            }
            fn main() -> i64 { 0 }
        """)
        rc, out, _ = compile_and_run(src)
        self.assertEqual(rc, 0)
        self.assertEqual(out.strip(), "0")

    def test_fit_multiple_interfaces(self):
        src = textwrap.dedent("""\
            Point { x: i64, y: i64 }
            sig Printable {
              fn str() -> str
            }
            sig Coordinate {
              fn cord() -> i64
            }
            fit Point as Printable, Coordinate {
              fn show() -> i64 { 7 }
              fn str() -> str {
                "ok"
              }
              fn cord() -> i64 {
                self.x + self.y
              }
            }
            fn main() -> i64 { 0 }
        """)
        rc, out, _ = compile_and_run(src)
        self.assertEqual(rc, 0)
        self.assertEqual(out.strip(), "0")

    def test_interface_parameter_polymorphism(self):
        src = textwrap.dedent("""\
            Point { x: i64, y: i64 }
            sig Printable {
              fn str() -> str
            }
            fit Point as Printable {
              fn str() -> str {
                "ok"
              }
            }
            fn print(p: Printable) {
              pr(p.str())
            }
            fn main() -> i64 {
              let p = Point { x: 1, y: 2 }
              print(p)
              0
            }
        """)
        rc, out, _ = compile_and_run(src)
        self.assertEqual(rc, 0)
        self.assertIn("ok", out)


class TestStringsLists(unittest.TestCase):
    def test_print_int(self):
        rc, out, _ = compile_and_run('fn main() -> i64 { pr(42) }')
        self.assertEqual(rc, 0)
        self.assertIn("42", out)

    def test_string_concat(self):
        src = textwrap.dedent("""\
            fn main() -> i64 {
              let s = "hel" + "lo"
              pr(s)
              pr(len(s))
            }
        """)
        rc, out, _ = compile_and_run(src)
        self.assertEqual(rc, 0)
        lines = [ln for ln in out.strip().splitlines() if ln]
        self.assertIn("hello", lines)
        self.assertIn("5", lines)

    def test_pr_mixed_string_concat(self):
        src = textwrap.dedent("""\
            fn main() -> i64 {
              let a = 7
              pr("> " + a)
            }
        """)
        rc, out, _ = compile_and_run(src)
        self.assertEqual(rc, 0)
        self.assertIn("> 7", out)

    def test_list(self):
        src = textwrap.dedent("""\
            fn main() -> i64 {
              let xs = [10, 20, 30]
              pr(xs)
              pr(len(xs))
              pr(xs[1])
            }
        """)
        rc, out, _ = compile_and_run(src)
        self.assertEqual(rc, 0)
        self.assertIn("[10, 20, 30]", out)
        self.assertIn("3", out)
        self.assertIn("20", out)

    def test_print_alias(self):
        rc, out, _ = compile_and_run('fn main() -> i64 { pr("ok"); 0 }')
        self.assertEqual(rc, 0)
        self.assertIn("ok", out)


class TestEntryPoints(unittest.TestCase):
    def test_fn_main(self):
        rc, out, _ = compile_and_run("fn main() -> i64 = 1")
        self.assertEqual(rc, 0)
        self.assertEqual(out.strip(), "1")

    def test_toplevel(self):
        rc, out, _ = compile_and_run("pr(7)\n42")
        self.assertEqual(rc, 0)
        self.assertIn("7", out)
        self.assertTrue(out.strip().endswith("42"))

    def test_go(self):
        rc, out, _ = compile_and_run("go { pr(3); 9 }")
        self.assertEqual(rc, 0)
        self.assertIn("3", out)
        self.assertTrue(out.strip().endswith("9"))

    def test_go_expr(self):
        rc, out, _ = compile_and_run("go 55")
        self.assertEqual(rc, 0)
        self.assertEqual(out.strip(), "55")


class TestJsonEnv(unittest.TestCase):
    def test_json_int(self):
        src = textwrap.dedent("""\
            fn main() -> i64 {
              pr(json(42))
            }
        """)
        rc, out, _ = compile_and_run(src)
        self.assertEqual(rc, 0)
        self.assertIn("42", out)

    def test_json_list(self):
        src = textwrap.dedent("""\
            fn main() -> i64 {
              pr(json([1, 2, 3]))
            }
        """)
        rc, out, _ = compile_and_run(src)
        self.assertEqual(rc, 0)
        self.assertIn("[1,2,3]", out.replace(" ", ""))


class TestExamples(unittest.TestCase):
    """Compile+run checked-in examples."""

    def _run_example(self, name, expect_in_stdout=None, expect_exact=None):
        src_path = os.path.join(EXAMPLES, name)
        self.assertTrue(os.path.isfile(src_path), f"missing {src_path}")
        bin_path = os.path.join(tempfile.mkdtemp(prefix="terse_ex_"), name.replace(".terse", ""))
        r = subprocess.run(
            [sys.executable, TERSEC, "build", src_path, "-o", bin_path],
            capture_output=True, text=True,
        )
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        rc, out, err = run_bin(bin_path)
        self.assertEqual(rc, 0, err)
        if expect_exact is not None:
            self.assertEqual(out.strip(), expect_exact)
        if expect_in_stdout is not None:
            for s in expect_in_stdout:
                self.assertIn(s, out)

    def test_hello(self):
        self._run_example("hello.terse", expect_exact="hello")

    def test_add_fn(self):
        self._run_example("add.terse", expect_exact="42")

    def test_fact(self):
        self._run_example("fact.terse", expect_exact="3628800")

    def test_hof(self):
        self._run_example("hof.terse", expect_exact="149")

    def test_io(self):
        self._run_example("io.terse", expect_in_stdout=["hello terse", "[10, 20, 30, 40]"])

    def test_minicompiler(self):
        self._run_example("minicompiler.terse", expect_exact="77")


class TestHttp(unittest.TestCase):
    def test_compile_http_hello(self):
        src_path = os.path.join(EXAMPLES, "http_hello.terse")
        if not os.path.isfile(src_path):
            self.skipTest("http_hello.terse missing")
        bin_path = os.path.join(tempfile.mkdtemp(prefix="terse_http_"), "http_hello")
        r = subprocess.run(
            [sys.executable, TERSEC, "build", src_path, "-o", bin_path],
            capture_output=True, text=True,
        )
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        self.assertTrue(os.path.isfile(bin_path))

    def test_http_live(self):
        """Start server briefly and hit /hello."""
        import socket
        import time
        import urllib.request

        src = textwrap.dedent("""\
            http.serve(18099) {
              get "/hello" => "world"
              get "/n" => json(7)
            }
        """)
        bin_path, code, log = compile_src(src, "http_live")
        self.assertEqual(code, 0, log)

        proc = subprocess.Popen(
            [bin_path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
        try:
            for _ in range(50):
                try:
                    with socket.create_connection(("127.0.0.1", 18099), timeout=0.1):
                        break
                except OSError:
                    time.sleep(0.05)
            else:
                self.fail("server did not start")

            with urllib.request.urlopen("http://127.0.0.1:18099/hello", timeout=2) as resp:
                body = resp.read().decode()
            self.assertEqual(body, "world")

            with urllib.request.urlopen("http://127.0.0.1:18099/n", timeout=2) as resp:
                body = resp.read().decode()
            self.assertEqual(body, "7")
        finally:
            proc.kill()
            try:
                proc.wait(timeout=2)
            except Exception:
                pass


class TestErrors(unittest.TestCase):
    def test_syntax_error(self):
        bin_path, code, log = compile_src("fn main( {")
        self.assertNotEqual(code, 0)
        self.assertTrue("Syntax" in log or "Error" in log or "error" in log.lower())

    def test_check_ok(self):
        r = subprocess.run(
            [sys.executable, TERSEC, "check", os.path.join(EXAMPLES, "hello.terse")],
            capture_output=True, text=True,
        )
        self.assertEqual(r.returncode, 0)
        self.assertIn("OK", r.stdout)


if __name__ == "__main__":
    unittest.main(verbosity=2)
