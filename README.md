# Terse

A succinct language that compiles to native binaries, with structures, interfaces, first-class higher-order functions, and (specified) support for REST APIs and databases.

## Quick Start

> Requires python3

### CLI Run
```bash
# Build program in example directory to a binary
make terse.hello dir=examples
./output/hello          # prints hello world
```
### VS Code Support
```bash
make vscode-terse
make vconde-install
```
In vscode ide, reload window:

```
Ctrl+Shift+P
Developer: Reload Window
```

Select a terse file, then

Compile:

```
Ctrl+Shift+P

Terse: Compile
```

Run:

```
Ctrl+Shift+P
Terse: Run
```

## Language Spec

See [docs/SPEC.md](docs/SPEC.md) for the full language specification.

## Compiler Status (0.1beta)

The reference compiler (`compiler/tersec.py`) implements:

- Lexer, recursive-descent parser, minimal type checker
- C code generation + gcc/clang backend → native binary
- Integers (`i64`), booleans, arithmetic & comparisons
- `if` expressions, `let` bindings, blocks
- Named functions + recursion
- **Higher-order functions**: pass functions as values, simple lambdas (`|x| x*2`)
- Function pointers under the hood (no environment capture yet)

Not yet implemented (but specified):

- Full closures with captures
- Strings beyond basic support
- Records / structs / pattern matching
- SQLite database runtime: `db.connect`, `db.exec`, `db.query`, and `db.query_one`
- Generics, modules, ownership system

## Examples

| File | Description | Output |
|------|-------------|--------|
| `examples/hello.te` | Basic arithmetic | 42 |
| `examples/fact.te` | Recursion | 3628800 |
| `examples/hof.te` | Higher-order + lambda | 149 |
| `examples/iflet.te` | if + let | 59 |

## Architecture

```
.terse source
    ↓ Lexer
  tokens
    ↓ Parser
   AST
    ↓ TypeChecker (basic)
   AST
    ↓ CodeGen → C source
    ↓ gcc -O2
  native binary
```

Future backends: direct LLVM IR.

## License

MIT (for this reference implementation)


## 0.1beta features

- Strings: `"hi"`, `"a" + "b"`, `len(s)`, `s[i]`
- Lists: `[1, 2, 3]`, `len(xs)`, `xs[i]`, `pr(xs)`
- `pr(x)` for ints, strings, lists
- See `examples/io.te`
