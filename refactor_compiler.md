# Refactoring `tersec.py` for Maintainability and Testability

## Current State: 5300 lines, monolithic

```
tersec.py (5300 lines)
├── Lexer (110 lines)        ← Token types + lexer
├── AST (200 lines)          ← 35+ node classes
├── Parser (600 lines)       ← Recursive descent
├── TypeChecker (700 lines)  ← check(), specialize_*, _infer_generic_args
├── C Runtime (1500 lines)   ← Embedded C string
├── Codegen (1500 lines)     ← AST → C
└── CLI (100 lines)          ← argparse + build/run
```

---

## 1. Split into Modules

```
compiler/
├── __init__.py
├── lexer.py         # TT, Tok, Lexer
├── ast.py           # All node dataclasses (no methods)
├── parser.py        # Parser class only
├── typecheck.py     # TypeChecker class only
├── codegen.py       # C codegen, RUNTIME constant
├── runtime.py       # C runtime as separate .c file
├── main.py          # CLI only
└── test_compiler.py
```

**Benefits**: Each file < 1000 lines. Tests can import individual modules.

---

## 2. Extract the C Runtime to a Real File

**Current**: `RUNTIME = r'''...'''` — 1500 lines of C embedded in Python string.

**Problem**: Can't syntax-check C without running Python. Can't diff C changes easily.

**Fix**:
```python
# compiler/runtime.py
import os
RUNTIME_PATH = os.path.join(os.path.dirname(__file__), "runtime.c")
def get_runtime() -> str:
    return open(RUNTIME_PATH).read()
```

Then `runtime.c` is a normal C file — `gcc -fsyntax-only runtime.c` catches errors before Python runs.

---

## 3. Make AST Nodes Pure Dataclasses (No Methods)

**Current**: AST nodes are `@dataclass` with no methods (good), but `Parser` and `TypeChecker` are monolithic.

**Fix**: Keep AST as pure data. Move all logic to separate classes.

---

## 4. Add a `--check` Mode That Tests Each Phase

**Current**: `build`/`run` only. No way to test lexer/parser/typecheck in isolation.

**Fix**:
```python
# python3 tersec.py check --lexer file.te
# python3 tersec.py check --parser file.te
# python3 tersec.py check --typecheck file.te
```

Then `test_compiler.py` can test each phase:
```python
def test_lexer():
    toks = Lexer("go 42").tokenize()
    assert toks[0].t == TT.GO
    assert toks[1].t == TT.INT
    assert toks[1].v == 42

def test_parser():
    prog = Parser(Lexer("go 42").tokenize()).parse_program()
    assert prog.toplevel == IntLit(42)
```

---

## 5. Extract TypeChecker to a Separate Class with Testable Interface

**Current**: `TypeChecker` has 700 lines, mixes type inference, specialization, and error reporting.

**Fix**:
```python
class TypeChecker:
    def __init__(self):
        self.errors = []
        self.env = {}
        self.funcs = {}
        ...
    
    def check_program(self, prog) -> bool:
        """Returns True if no errors."""
        ...
    
    def check(self, e) -> str:
        """Returns type string or 'i64' on error."""
        ...
```

Test:
```python
def test_typecheck_add():
    tc = TypeChecker()
    prog = Parser(Lexer("go 40 + 2").tokenize()).parse_program()
    assert tc.check_program(prog)
    assert not tc.errors
```

---

## 6. Add Unit Tests for Each Phase

**Current**: Only `test_compiler.py` tests end-to-end builds.

**Add**:
```python
class TestLexer(unittest.TestCase):
    def test_int(self):
        toks = Lexer("42").tokenize()
        self.assertEqual(toks[0].t, TT.INT)
        self.assertEqual(toks[0].v, 42)
    
    def test_string_escape(self):
        toks = Lexer('"hello\\n"').tokenize()
        self.assertEqual(toks[0].v, "hello\n")

class TestParser(unittest.TestCase):
    def test_simple_expr(self):
        prog = Parser(Lexer("go 1 + 2").tokenize()).parse_program()
        self.assertIsInstance(prog.toplevel, Binary)
        self.assertEqual(prog.toplevel.op, '+')

class TestTypeChecker(unittest.TestCase):
    def test_type_mismatch(self):
        src = "go { val x: i64 = \"hello\" }"
        # Should produce type error
```

---

## 7. Add a `--keep-c` Test Mode

**Current**: `--keep-c` writes C files to `out/`. Test them by compiling.

**Fix**: Add a test that:
1. Compiles a known program
2. Checks the generated C compiles with `gcc -Wall -Wextra -Werror`
3. Runs it and checks output

```python
def test_c_compiles_clean():
    src = "go 42"
    c = generate_c(src)
    # Write to temp, compile with -Wall -Werror
    # Assert no warnings
```

---

## 8. Add a Test for Each BNF Rule

The BNF has ~50 productions. Test each one:
```python
BNF_TESTS = [
    ("go 42", "42"),           # <go-decl>
    ("fn add(a: i64, b: i64) -> i64 = a + b", None),  # <fn-decl>
    ("rec Point { x: i64, y: i64 }", None),  # <record-decl>
    ...
]
```

---

## 9. Add Error Recovery for Multi-Error Reporting

**Current**: First error aborts.

**Fix**: Collect all errors, report at end:
```python
def check_program(self, prog) -> List[Error]:
    errors = []
    for fn in prog.funcs:
        try:
            self.check(fn.body)
        except TypeErrorError as e:
            errors.append(e)
    return errors
```

---

## 10. Add `__repr__` to AST Nodes

**Current**: No debug output for AST.

**Fix**:
```python
@dataclass
class Binary(Expr):
    op: str
    left: Expr
    right: Expr
    
    def __repr__(self):
        return f"Binary({self.op!r}, {self.left!r}, {self.right!r})"
```

Then `print(prog)` shows the full AST tree for debugging.

---

## 11. Add a `--ast` Debug Flag

```bash
python3 tersec.py --ast src/eg.te
```
Prints the parsed AST as a tree. Useful for debugging parser bugs.

---

## 12. Add a `--typecheck-only` Mode

**Current**: `check` command exists but only prints "OK".

**Fix**: Make `check` print the inferred types:
```bash
python3 tersec.py check src/eg.te
# go { ... } -> i64
# fn add() -> i64
# fn mult(a: i64, b: i64) -> i64
```

---

## 13. Add a `Makefile` Test Target

```makefile
test:
	python3 -m unittest compiler.test_compiler -v

test-lexer:
	python3 -m unittest compiler.test_lexer -v

test-parser:
	python3 -m unittest compiler.test_parser -v

test-typecheck:
	python3 -m unittest compiler.test_typecheck -v

test-codegen:
	python3 -m unittest compiler.test_codegen -v
```

---

## 14. Add `pytest` Support

**Current**: Uses `unittest`. Add `pytest` compatibility:
```python
# conftest.py
import sys
sys.path.insert(0, 'compiler')

# tests/test_lexer.py
def test_int_lexer():
    toks = Lexer("42").tokenize()
    assert toks[0].v == 42
```

---

## 15. Add a `--profile` Mode

**Current**: No performance profiling.

**Fix**: Use `cProfile` to find slow parts:
```bash
python3 -m cProfile -s cumulative tersec.py build src/eg.te
```

---

## Summary: Concrete Refactoring Plan

| Step | Change | Effort | Impact |
|------|--------|--------|--------|
| 1 | Split into 6 modules | 2h | File size < 1000 lines each |
| 2 | Extract `runtime.c` | 1h | C syntax checkable independently |
| 3 | Add `--ast`, `--typecheck-only` flags | 1h | Debugging |
| 4 | Add unit tests per phase | 2h | Regression coverage |
| 5 | Add `__repr__` to AST nodes | 30min | Debugging |
| 6 | Add error recovery (multi-error) | 2h | Better diagnostics |
| 7 | Add `Makefile` test targets | 10min | CI automation |
| 8 | Add `pytest` support | 30min | Faster test iteration |

**Total**: ~10 hours for a much more maintainable, testable codebase.