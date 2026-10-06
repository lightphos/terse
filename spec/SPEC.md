# Terse Language Specification 0.1-beta

**Terse** is a succinct, statically typed language that compiles to native binaries. It emphasizes compact syntax, first-class functions, and practical facilities for I/O and services.

This document separates the intended 0.1 language contract from implementation status. **Implemented** means supported by the Python reference compiler (`tersec`); **Limited** means only a subset works; **Planned** means the syntax or behavior is not yet available. The Terse-written compiler (`tc.te`) is an experimental subset and is not the reference for language conformance. `spec/bnf.md` describes parser grammar and should stay aligned with the syntax here.

## 1. Design Goals

- Extremely terse syntax with high signal-to-noise.
- First-class functions and higher-order programming (pass, return, nest functions).
- Ahead-of-time compilation to a single native binary via a C-based backend.
- Small runtime footprint and straightforward code generation for portability.
- Practical built-ins for simple HTTP services and basic data I/O.
- Type checking and basic inference for the implemented subset.
- A pragmatic implementation path that favors working examples over a complete feature set.

## 2. Lexical Structure

### Comments
```
// line comment
/* block comment */
```

### Identifiers
```
ident ::= [a-zA-Z_][a-zA-Z0-9_]*
```

Keywords (reserved):  
`fn`, `let`, `type`, `if`, `else`, `match`, `use`, `return`, `ret`, `true`, `false`, `mut`, `struct`, `enum`, `impl`, `self`, `pub`, `in`, `for`, `while`, `loop`, `lp`, `break`, `continue`, `None`, `Some`, `Ok`, `Err`, `get`, `post`, `pr`, `put`, `go`, `env`, `delete`, `http`, `db`, `json`, `status`, `tr`

This is the intended keyword set. The current lexer does not reserve or implement every listed word; see Section 12 and `bnf.md` for the accepted 0.1 subset.

### Literals
- Integer: `42`, `-7`, `0xFF` (i64 by default)
- Float: `3.14` (f64)
- String: `"hello"`, support for basic escapes (`\n`, `\t`, `\"`, `\\`)
- Boolean: `true`, `false`
- Unit: `()`

The reference lexer currently accepts decimal integers, strings with basic escapes, and booleans. Hexadecimal integers and floating-point literals are not currently accepted; `()` is accepted as the empty `go` entrypoint, not as a general unit expression.

### Operators
Arithmetic: `+` `-` `*` `/` `%`  
Comparison: `==` `!=` `<` `>` `<=` `>=`  
Logical: `&&` `||` `!`  
Assignment: `=`  
Function: `|params| body` (lambda), `>>` (compose), `_` (placeholder for partial app)

### Core Semantics

- An executable has exactly one `go` entrypoint. `go()` returns `0`; `go expr` evaluates `expr`; there is no implicit entrypoint and `fn main` is rejected.
- Functions may call declared functions recursively. In the reference compiler, omitted parameter and return annotations default to `i64`; general type inference is a design goal, not current behavior.
- `&&` and `||` short-circuit. Comparisons and logical operators produce `bool`; arithmetic uses integer values unless `+` performs string concatenation.
- A block evaluates its statements in order and has the value of its final expression. An empty block has value `0`. `ret expr` exits the current function with that value; `ret` returns `0`.
- The intended binding rule is that `let` introduces an immutable local and `let mut` explicitly permits reassignment. The reference compiler currently permits reassignment of some `let` bindings and does not consistently enforce `mut`; that behavior is not yet portable to the intended contract.
- Strings are UTF-8 byte sequences. In the current implementation, `len(str)` counts bytes and `str[index]` returns the unsigned value of one byte, not a Unicode scalar value.
- `pr(value)` writes the value followed by a newline and returns `0`. If `go` returns `0` after printing, the current runtime suppresses the extra numeric `0`; otherwise it prints the integer result of `go`.
- Integer overflow and division by zero do not have portable behavior specified in 0.1. Programs should not depend on either until the rules are defined and enforced.

### Status Labels

Syntax listed in this document is not automatically implemented. Section 12 identifies the reference compiler's current support; reserved words may exist before their constructs are implemented. The parser-derived `bnf.md` describes accepted syntax, not every planned feature.

## 3. Types

### Primitive Types
- `i64`, `i32`, `u64`, `bool`, `f64`, `str` (UTF-8 string), `()` (unit)

### Composite
- Function types: `fn(T1, T2) -> R`
- Records / structs: `rec {field: Type, ...}`
- Option: `Option[T]` (Some(v) | None)
- Result: `Result[T, E]`
- Lists: `[T]`
- Tuples: `(T1, T2, ...)`

Type inference is Hindley-Milner inspired for local variables and lambdas. Top-level functions may require annotations for complex cases.

In the current compiler, `i64`, `bool`, `str`, integer lists, named records, and function values have the strongest support. `f64`, tuples, `Option`, `Result`, and general inference are incomplete or planned; listing a type here does not guarantee that it can be compiled.

## 4. Syntax (Core)

### Program
A program is a sequence of top-level declarations (functions, types, uses, traits, and methods) with one entrypoint: `go()` for an empty body or `go { ... }` for a program body. `fn main` is not a Terse entrypoint; the backend generates the native `main` wrapper.

```
program ::= { item } entrypoint { item }
item    ::= fn_decl | pub_fn_decl | record_decl | type_decl | use_decl
          | trait_decl | method_decl
entrypoint ::= "go" "(" ")" | "go" expr
```

### Functions
```
tr Printable {
  fn str() -> str
}

Point { x: i64, y: i64 }

fn Point.show() -> i64 { 7 }       // method on Point
fn Point.str() -> str { "ok" }     // satisfies Printable implicitly

fn name(params) -> RetType = expr
fn name(params) -> RetType { stmts }

// Lambda
|param1, param2| expr
|param1: Type| { stmts }
```

Parameters and return types may be omitted. In the current reference compiler, omitted types default to `i64` rather than being inferred generally. Function-type annotations and untyped lambdas are limited to cases the type checker can resolve.

Higher-order example:
```
fn apply(f: fn(i64) -> i64, x: i64) -> i64 = f(x)
let double = |n| n * 2
apply(double, 21)
```

### Let Bindings
```
let name = expr
let name: Type = expr
let mut name = expr
```

The intended contract is `let` for immutable bindings and `let mut` for mutable bindings. The current compiler does not consistently enforce that distinction; see Section 12.

### Control Flow
```terse
if cond { then } else { otherwise }
ret
ret expr

lp cond { body }
lp init; cond; post { body }

match expr {
  pat1 => result1
  pat2 if guard => result2
  _ => default
}
```

`if` is an expression and evaluates one branch. `lp` repeats its body while the condition remains true; without semicolons it behaves like a while loop, and with `init; cond; post` it behaves like a for loop. A loop evaluates to `0` when it exits normally. `match`, `break`, and `continue` are reserved/planned and are not part of the implemented 0.1 subset.

`ret` exits the current function immediately. When followed by an expression, it returns that value; otherwise, it returns `0`.

### Function Application & Composition
```
f(arg1, arg2)
f >> g          // composition: g(f(x))
add(5, _)       // partial application
```

## 5. Higher-Order Functions

Functions are first-class values. They can be:

- Stored in variables
- Passed as arguments
- Returned from functions
- Nested (closures)

Closures capture by immutable borrow / value for primitives in the current design. Mutable captures require explicit `mut` and are restricted.

Example:
```
fn make_multiplier(factor: i64) -> fn(i64) -> i64 {
  |x| x * factor
}

let times3 = make_multiplier(3)
times3(10)   // 30
```
## 6. Strings, Lists, Print, Basic I/O

### Strings
```
"hello"
"hel" + "lo"          // concat
len(s)                // length
s[i]                  // byte/char code at index (i64)
pr(s)
```

### Lists (of i64)
```
[1, 2, 3]
len(xs)
xs[i]
pr(xs)             // prints [1, 2, 3]
```

Type annotation: `list` or `[i64]` in signatures when needed.

### Printing
```
pr(42)
pr("hi")
pr([1, 2])
pr(x)
```
`pr` is a builtin; returns `0`.

### Basic I/O
- `pr` → stdout (ints, strings, lists)
- `fs.read_text(path)` reads a UTF-8 text file into a `str`.
- `fs.write_text(path, text)` writes text and returns the byte count.
- File operation errors print the operation/path and terminate the program.
- Stdin and binary file I/O are not implemented yet.

### Example
```
go {
  pr("hello terse")
  let xs = [10, 20, 30]
  pr(xs)
  pr(len(xs))
  pr(xs[1])
  let s = "hel" + "lo"
  pr(s)
}
```

## 7. REST APIs

```
use std.http

http.serve(port: i64) {
  get "/path" => expr_or_block
  get "/users/:id" => |id: i64| { ... }
  post "/users" => |body: User| { ... }
  put ...
  delete ...

  // Middleware / groups
  group "/admin" {
    use require_auth
    get "/stats" => ...
  }
}
```

- The current compiler implements a minimal `http.serve` construct for simple route handlers.
- Route handlers may return strings or JSON values; the runtime responds with text/JSON output.
- The implementation is intentionally small and does not yet provide full middleware, path-parameter plumbing, or framework-style request decoding.
- The `http.serve` block is the main event loop of the process for the current runtime.

## 8. Database Access (Limited)

```
use std.db

db.connect(url: str)          // or from env
db.query[T](sql: str, args...) -> [T]
db.query_one[T](sql: str, args...) -> Option[T]
db.exec(sql: str, args...) -> i64   // rows affected
db.tx { ... }                   // transaction block
```

The reference compiler has an experimental SQLite-backed `db.*` implementation with positional parameters. This is compiler/runtime support, not a separately packaged Terse library. Untyped queries are limited; typed record queries support only selected field types. `query_one` currently lowers to a list query rather than the `Option[T]` contract shown above. PostgreSQL, transactions, migrations, generic drivers, and full `Option` behavior remain planned.

## 9. Modules & Visibility

```
use std.http
use std.fs
use usage.moduse

go { mod() }

use usage/moduse
go { moduse.mod() }

use usage.moduse.mod
go { mod() }
```

- `std.*` names refer to compiler-provided modules such as `std.fs`.
- A source import path is relative to the project's `src/` directory and names a `.te` file without its extension.
- Dotted paths import all public functions into the current scope; slash paths import a module namespace.
- Standard modules may also use an explicit namespace alias, such as `use std.fs as files`.
- A dotted final component imports a function into the current scope: `use usage.moduse.mod` makes `mod()` available.
- Source modules currently export functions only. Functions are private by default; prefix public API declarations with `pub fn`.
- Imported files contain declarations only and cannot contain a `go()` or `go { ... }` entrypoint.
- Glob, selective function, and namespace imports are supported; imported records and cyclic imports are not.
- `std.fs`, `std.http`, and `std.db` currently name compiler-provided behavior, not ordinary source modules. Moving HTTP/DB APIs into Terse libraries requires a stable low-level native interface.

## 10. Memory & Safety Model (Current Implementation)

- The full language is still intended to evolve toward an ownership-and-borrowing model.
- The current reference compiler uses a simplified runtime model with value-based semantics and function pointers.
- There is no full borrow checker or ownership system in the current implementation.
- The compiler is currently focused on correctness and portability over advanced safety features.

## 11. Compilation Model

```sh
python tersec.py build main.te -o app
python tersec.py run main.te
python tersec.py check main.te
```

- Frontend: lexer → parser → type checker → code generation
- Backend: currently C code generation + system C compiler (gcc/clang)
- `check` parses and type-checks without producing a binary; `build` emits a native executable; `run` builds and executes it.
- Compile-time errors return a nonzero status and include source locations where available. Runtime failures such as file or SQLite errors report to stderr and terminate nonzero.
- Possible future backend: direct LLVM IR emission for better optimization and cross-compilation.

## 12. Current Compiler Status (0.1beta)

### Implemented in `tersec`

- Integer arithmetic and comparisons
- Booleans and if-expressions
- Named functions and recursion
- Higher-order functions (function values / pointers)
- Simple lambdas
- let bindings and blocks
- Basic type checking
- Compilation to native binary via C
- String literals, string concatenation, length, and indexing
- Lists, list indexing, and printing
- Structs / records and `tr`-defined interfaces
- Implicit interface satisfaction (a struct satisfies a `tr` when its methods match)
- Built-in `pr`, `len`, `json`, and a minimal `http.serve` runtime
- `go()` and `go { ... }` program entrypoints; native `main` is generated by the backend
- Source-module imports for functions and basic `std.fs` text I/O

### Limited or Planned

- Full closures with environment capture
- Pattern matching (`match`)
- General generics, tuples, `Option`, and `Result`
- Full ownership / borrowing / borrow checking
- Database support beyond the experimental SQLite runtime described in Section 8
- HTTP middleware, path-parameter plumbing, and framework-style request decoding
- `let mut`, `break`, and `continue` semantics are not consistently implemented

The native compiler in `compiler/tc.te` supports a much smaller subset; its
coverage is tracked separately from this reference-compiler status.

## 13. Example Programs

See `src/` directory.


