#!/usr/bin/env python3
"""Unit tests for the Terse compiler (tersec)."""
import os
import sys
import subprocess
import tempfile
import unittest
import textwrap

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
TERSEC = os.path.join(os.path.dirname(__file__), "tersec.py")
EXAMPLES = os.path.join(ROOT, "src")


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
        rc, out, _ = compile_and_run("go 40 + 2")
        self.assertEqual(rc, 0)
        self.assertEqual(out.strip(), "42")

    def test_mul_div(self):
        rc, out, _ = compile_and_run("go (3 * 4) + (10 / 2)")
        self.assertEqual(rc, 0)
        self.assertEqual(out.strip(), "17")

    def test_fact(self):
        src = textwrap.dedent("""\
            fn fact(n: i64) -> i64 =
              if n <= 1 { 1 } else { n * fact(n - 1) }
            go fact(6)
        """)
        rc, out, _ = compile_and_run(src)
        self.assertEqual(rc, 0)
        self.assertEqual(out.strip(), "720")


class TestControl(unittest.TestCase):
    def test_if(self):
        src = textwrap.dedent("""\
            fn abs(x: i64) -> i64 = if x < 0 { 0 - x } else { x }
            go abs(0 - 7) + abs(3)
        """)
        rc, out, _ = compile_and_run(src)
        self.assertEqual(rc, 0)
        self.assertEqual(out.strip(), "10")

    def test_ret_without_value(self):
        src = textwrap.dedent("""\
            go {
              ret
            }
        """)
        rc, out, _ = compile_and_run(src)
        self.assertEqual(rc, 0)
        self.assertEqual(out.strip(), "0")

    def test_ret_with_value(self):
        src = textwrap.dedent("""\
            go {
              let x = 10
              ret x + 2
            }
        """)
        rc, out, _ = compile_and_run(src)
        self.assertEqual(rc, 0)
        self.assertEqual(out.strip(), "12")

    def test_let(self):
        src = textwrap.dedent("""\
            go {
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
            go {
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
            go {
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
            go {
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
            go apply(double, 21)
        """)
        rc, out, _ = compile_and_run(src)
        self.assertEqual(rc, 0)
        self.assertEqual(out.strip(), "42")

    def test_lambda(self):
        src = textwrap.dedent("""\
            fn apply(f: fn, x: i64) -> i64 = f(x)
            go apply(|n| n + 100, 7)
        """)
        rc, out, _ = compile_and_run(src)
        self.assertEqual(rc, 0)
        self.assertEqual(out.strip(), "107")


class TestRecords(unittest.TestCase):
    def test_record_returning_function(self):
        src = textwrap.dedent("""\
            Pair { value: i64 }
            fn make_pair() -> Pair = Pair { value: 41 }
            go {
              let pair = make_pair()
              pair.value + 1
            }
        """)
        rc, out, _ = compile_and_run(src)
        self.assertEqual(rc, 0)
        self.assertEqual(out.strip(), "42")

    def test_growable_record_list_for_ast_nodes(self):
        src = textwrap.dedent("""\
            Node { kind: i64, text: str, left: i64, right: i64 }
            go {
              let nodes: [Node] = []
                            nodes = push(nodes, Node { kind: 1, text: "int", left: 0, right: 0 })
                            nodes = push(nodes, Node { kind: 2, text: "add", left: 0, right: 1 })
              pr(len(nodes))
              pr(nodes[1].kind)
              0
            }
        """)
        rc, out, _ = compile_and_run(src)
        self.assertEqual(rc, 0)
        self.assertIn("2", out)

    def test_rec(self):
        src = textwrap.dedent("""\
            rec Point { x: i64, y: i64 }
            go {
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
            go {
              let p = Point { x: 1, y: 2 }
              p.x + p.y
            }
        """)
        rc, out, _ = compile_and_run(src)
        self.assertEqual(rc, 0)
        self.assertEqual(out.strip(), "3")

    def test_tr_implicit(self):
        src = textwrap.dedent("""\
            Point { x: i64, y: i64 }
            tr Printable {
              fn str() -> str
            }
            fn Point.show() -> i64 { 7 }
            fn Point.str() -> str {
              "ok"
            }
            go { 0 }
        """)
        rc, out, _ = compile_and_run(src)
        self.assertEqual(rc, 0)
        self.assertEqual(out.strip(), "0")

    def test_struct_satisfies_multiple_traits(self):
        src = textwrap.dedent("""\
            Point { x: i64, y: i64 }
            tr Printable {
              fn str() -> str
            }
            tr Coordinate {
              fn cord() -> i64
            }
            fn Point.show() -> i64 { 7 }
            fn Point.str() -> str {
              "ok"
            }
            fn Point.cord() -> i64 {
              self.x + self.y
            }
            go { 0 }
        """)
        rc, out, _ = compile_and_run(src)
        self.assertEqual(rc, 0)
        self.assertEqual(out.strip(), "0")

    def test_interface_parameter_polymorphism(self):
        src = textwrap.dedent("""\
            Point { x: i64, y: i64 }
            tr Printable {
              fn str() -> str
            }
            fn Point.str() -> str {
              "ok"
            }
            fn print(p: Printable) {
              pr(p.str())
            }
            go {
              let p = Point { x: 1, y: 2 }
              print(p)
              0
            }
        """)
        rc, out, _ = compile_and_run(src)
        self.assertEqual(rc, 0)
        self.assertIn("ok", out)


class TestStringsLists(unittest.TestCase):
    def test_substr(self):
        rc, out, _ = compile_and_run('go { pr(substr("terse", 1, 3)) }')
        self.assertEqual(rc, 0)
        self.assertIn("ers", out)

    def test_print_int(self):
        rc, out, _ = compile_and_run('go { pr(42) }')
        self.assertEqual(rc, 0)
        self.assertIn("42", out)

    def test_string_concat(self):
        src = textwrap.dedent("""\
            go {
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
            go {
              let a = 7
              pr("> " + a)
            }
        """)
        rc, out, _ = compile_and_run(src)
        self.assertEqual(rc, 0)
        self.assertIn("> 7", out)

    def test_list(self):
        src = textwrap.dedent("""\
            go {
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
        rc, out, _ = compile_and_run('go { pr("ok"); 0 }')
        self.assertEqual(rc, 0)
        self.assertIn("ok", out)


class TestEntryPoints(unittest.TestCase):
    def test_go_empty(self):
        rc, out, _ = compile_and_run("go()")
        self.assertEqual(rc, 0)
        self.assertEqual(out.strip(), "0")

    def test_fn_main_is_not_an_entrypoint(self):
        _, code, log = compile_src("fn main() -> i64 = 1")
        self.assertNotEqual(code, 0)
        self.assertIn("use go", log)

    def test_toplevel(self):
        rc, out, _ = compile_and_run("go { pr(7); 42 }")
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


class TestModules(unittest.TestCase):
    def test_glob_source_import(self):
        source_path = os.path.join(EXAMPLES, "usemod.te")
        output_dir = tempfile.mkdtemp(prefix="terse_module_")
        binary_path = os.path.join(output_dir, "usemod")
        result = subprocess.run(
            [sys.executable, TERSEC, "run", source_path, "-o", binary_path],
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertIn("from moduse", result.stdout)
        self.assertIn("from moduse2", result.stdout)

    def test_private_module_function_is_not_importable(self):
        src = "use usage.moduse._say\ngo 0"
        _, return_code, log = compile_src(src)
        self.assertNotEqual(return_code, 0)
        self.assertIn("has no function '_say'", log)

    def test_source_module_namespace_call(self):
        src = textwrap.dedent("""\
            use usage/moduse
            go { moduse.mod() }
        """)
        rc, out, _ = compile_and_run(src)
        self.assertEqual(rc, 0)
        self.assertIn("from moduse", out)


class TestTerseCompiler(unittest.TestCase):
    def test_tc_cli_compiles_arithmetic_with_gcc(self):
        with tempfile.TemporaryDirectory(prefix="terse_tc_") as directory:
            source_path = os.path.join(directory, "program.te")
            binary_path = os.path.join(directory, "program")
            with open(source_path, "w", encoding="utf-8") as source_file:
                source_file.write("go { (3 * 4) + (10 / 2) }\n")

            compiled = subprocess.run(
                [os.path.join(ROOT, "tc"), source_path, "-o", binary_path],
                capture_output=True, text=True, cwd=ROOT,
            )
            self.assertEqual(compiled.returncode, 0, compiled.stderr + compiled.stdout)
            self.assertTrue(os.path.isfile(binary_path))
            self.assertTrue(os.path.isfile(binary_path + ".c"))

            result = subprocess.run([binary_path], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.strip(), "17")

    def test_tc_falls_back_for_recursive_functions(self):
        with tempfile.TemporaryDirectory(prefix="terse_tc_fallback_") as directory:
            binary_path = os.path.join(directory, "fact")
            compiled = subprocess.run(
                [os.path.join(ROOT, "tc"), os.path.join(EXAMPLES, "fact.te"), "-o", binary_path],
                capture_output=True, text=True, cwd=ROOT,
            )
            self.assertEqual(compiled.returncode, 0, compiled.stderr + compiled.stdout)
            self.assertIn("reference compiler", compiled.stderr)
            result = subprocess.run([binary_path], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.strip(), "3628800")


class TestFileIO(unittest.TestCase):
    def test_text_file_round_trip(self):
        with tempfile.TemporaryDirectory(prefix="terse_file_io_") as directory:
            path = os.path.join(directory, "source.te")
            src = textwrap.dedent(f'''\
                                use std.fs as files
                go {{
                                    pr(files.write_text("{path}", "go 42"))
                                    pr(files.read_text("{path}"))
                  0
                }}
            ''')
            rc, out, _ = compile_and_run(src)
            self.assertEqual(rc, 0)
            self.assertIn("go 42", out)
            with open(path, encoding="utf-8") as source_file:
                self.assertEqual(source_file.read(), "go 42")


class TestJsonEnv(unittest.TestCase):
    def test_json_int(self):
        src = textwrap.dedent("""\
            go {
              pr(json(42))
            }
        """)
        rc, out, _ = compile_and_run(src)
        self.assertEqual(rc, 0)
        self.assertIn("42", out)

    def test_json_list(self):
        src = textwrap.dedent("""\
            go {
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
        self._run_example("hello.te", expect_exact="hello world")

    def test_add_fn(self):
        self._run_example("add.te", expect_exact="42")

    def test_fact(self):
        self._run_example("fact.te", expect_exact="3628800")

    def test_hof(self):
        self._run_example("hof.te", expect_exact="149")

    def test_io(self):
        self._run_example("io.te", expect_in_stdout=["hello terse", "[10, 20, 30, 40]"])

    def test_minicompiler(self):
        self._run_example("minicompiler.te", expect_exact="77")


class TestHttp(unittest.TestCase):
    def test_serve_post_then_get_user(self):
        """POST a user to serve.te, then fetch it through its dynamic route."""
        import socket
        import time
        import urllib.request

        bin_path = os.path.join(tempfile.mkdtemp(prefix="terse_serve_"), "serve")
        r = subprocess.run(
            [sys.executable, TERSEC, "build", os.path.join(EXAMPLES, "serve.te"), "-o", bin_path],
            capture_output=True, text=True,
        )
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)

        proc = subprocess.Popen(
            [bin_path], cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        try:
            for _ in range(50):
                try:
                    with socket.create_connection(("127.0.0.1", 18081), timeout=0.1):
                        break
                except OSError:
                    time.sleep(0.05)
            else:
                self.fail("serve.te server did not start")

            request = urllib.request.Request(
                "http://127.0.0.1:18081/user",
                data=b"Charlie",
                method="POST",
            )
            with urllib.request.urlopen(request, timeout=2) as resp:
                self.assertEqual(resp.read().decode(), "created")

            with urllib.request.urlopen("http://127.0.0.1:18081/user/44", timeout=2) as resp:
                body = resp.read().decode()
            self.assertIn('"name":"Charlie"', body)
        finally:
            proc.kill()
            try:
                proc.wait(timeout=2)
            except Exception:
                pass

    def test_http_live(self):
        """Start server briefly and hit /hello."""
        import socket
        import time
        import urllib.request

        src = textwrap.dedent("""\
                        go {
            http.serve(18099) {
              get "/hello" => "world"
              get "/n" => json(7)
            }
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
        bin_path, code, log = compile_src("go {")
        self.assertNotEqual(code, 0)
        self.assertTrue("Syntax" in log or "Error" in log or "error" in log.lower())

    def test_check_ok(self):
        r = subprocess.run(
            [sys.executable, TERSEC, "check", os.path.join(EXAMPLES, "hello.te")],
            capture_output=True, text=True,
        )
        self.assertEqual(r.returncode, 0)
        self.assertIn("OK", r.stdout)


if __name__ == "__main__":
    unittest.main(verbosity=2)
