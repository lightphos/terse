# Terse

A compact, statically typed language that compiles to native binaries. 

## Install

```bash
curl -fsSL https://raw.githubusercontent.com/lightphos/terse/main/install.sh | sh
export PATH="$HOME/.terse/bin:$PATH"
```

Places the host compiler in `$HOME/.terse/compiler`, libs in `$HOME/.terse/lib`, and `tc|tersec` in `$HOME/.terse/bin`.

## Quick start
```bash
# app.te

go {
  pr("This is terse!")
}

or

go pr("This is terse!")
```

### Build & Run

```bash
# build
tersec app.te
or
tc app.te

# run
$HOME/.terse/out/app
```

## Prerequisites

- Python 3.12+
- `gcc` or `clang` on `PATH`
- **OpenSSL development files** (needed for HTTPS; optional otherwise)


> Aim:
> Native compiler written in terse which produces machine code

## Test

```bash
make verify    # host unit tests
make tst       # tst/t_*.te

WIP:
make tcc && make tcc1 && make bootstrap   # native frontend stages

C Intermediate:
python3 compiler/tersec.py build src/hi.te -o out/hi --keep-c
```

## Layout

```text
compiler/     Host compiler (tersec.py, runtime.c, tc.te)
lib/          Standard and optional packages
src/          Examples
tst/          Tests (t_*.te)
install.sh    Install tc → $HOME/.terse/
SPEC.md       Language specification
BNF.md        Grammar
benchmark/    HTTP concurrency notes
```

## Language (see SPEC)

Details live in **[SPEC.md](./SPEC.md)** and **[BNF.md](./BNF.md)**. Topics covered there:

- Keywords
- Types and primitives (`long`, `int`, `str`, lists, maps, …)
- Functions, methods, modules (`use` / `pub`)
- Control flow, pattern `if`, loops
- Records, enums, traits, generics
- Lambdas and closures
- Pipe `|>`
- Thread async `~~` / `~` and event-loop `~~>` / `~>`
- Awaitable I/O (`io.wait`, `io.recv`, `io.send`, `io.connect`)
- Arena, sockets, HTTP

## Tooling

- tersec | tec
  - build 
- terser | ter
  - run
  - test
- te -c -r -t

## Roadmap

**[roadmap.md](./roadmap.md)** 

## License

MIT
